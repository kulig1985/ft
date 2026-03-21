"""
RangeBreakoutPullbackStrategy - Kitörés + visszazárás intraday stratégia

Logika:
  1. A nap első 4 órájának range-e a referencia időzóna szerint (default: America/New_York)
     - 5m gyertyákból aggregálva (mert az exchange 4H gyertyák UTC-aligned-ek:
       NY 00:00-04:00 EST = UTC 05:00-09:00, ami KÉT exchange 4H gyertyát fed át)
     - A range AZONOS azzal, amit egy timezone-aligned 4H gyertya high/low-ja adna
  2. Kitörés felfelé (close > range_high) → nyomon követjük a max HIGH-t
     → Visszazárás (close <= range_high) → SHORT belépési jel
  3. Kitörés lefelé (close < range_low) → nyomon követjük a min LOW-t
     → Visszazárás (close >= range_low) → LONG belépési jel
  4. Stop loss: kitörési szakasz szélső értéke + stop_buffer_pct
  5. Take profit: R-alapú (entry ± R × risk_reward_ratio)

Időzóna megjegyzés:
  - Minden Freqtrade gyertya UTC-ben tárolódik (exchange standard)
  - A VPS Budapesti időzónában fut, de ez a stratégia logikáját NEM érinti
  - A range számításhoz az UTC időket pytz-szel konvertáljuk a ref TZ-be (DST-aware)
  - America/New_York télen (EST, UTC-5): NY 00:00-04:00 = UTC 05:00-09:00
  - America/New_York nyáron (EDT, UTC-4): NY 00:00-04:00 = UTC 04:00-08:00
  - Budapesti logolás: datetime.now(Europe/Budapest) csak a logsorokban
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import pytz
from pandas import DataFrame

from freqtrade.persistence import Trade
from freqtrade.strategy import (
    BooleanParameter,
    CategoricalParameter,
    DecimalParameter,
    IntParameter,
    IStrategy,
    stoploss_from_absolute,
)

logger = logging.getLogger(__name__)


class RangeBreakoutPullbackStrategy(IStrategy):

    INTERFACE_VERSION = 3
    can_short = True
    timeframe = "5m"

    # 300 db 5m gyertya = ~25 óra; elegendő az előző nap teljes range-éhez
    startup_candle_count = 300

    # Hard SL disabled - custom_stoploss kezeli
    stoploss = -0.99
    use_custom_stoploss = True

    # ROI disabled - custom_exit kezeli a TP-t
    minimal_roi = {"0": 999}

    # --- Hyperopt paraméterek (mind space="buy") ---
    # FONTOS: --analyze-per-epoch KÖTELEZŐ hyperoptnál, mert ezek a paraméterek
    # a populate_indicators()-t érintik (range számítás, kitörési szűrők, SL/TP)
    risk_reward_ratio = DecimalParameter(1.0, 4.0, default=2.0, decimals=1, space="buy")
    min_breakout_distance_pct = DecimalParameter(0.0, 0.5, default=0.0, decimals=2, space="buy")
    min_range_size_pct = DecimalParameter(0.1, 2.0, default=0.3, decimals=2, space="buy")
    max_range_size_pct = DecimalParameter(1.0, 10.0, default=5.0, decimals=1, space="buy")
    max_setup_bars = IntParameter(6, 48, default=24, space="buy")  # 24 * 5m = 2 óra
    stop_buffer_pct = DecimalParameter(0.01, 0.5, default=0.05, decimals=2, space="buy")
    range_timezone = CategoricalParameter(
        ["America/New_York", "Europe/London", "UTC"],
        default="America/New_York",
        space="buy",
        # Opcionális: más időzóna alapján is tesztelhető a range logika.
        # Alap: America/New_York (NY sessziós range).
    )

    # Gyertyánkénti logolás nyomon követéséhez (BBRsiAdx minta)
    _last_logged_candle: dict = {}
    _last_range_notified: dict = {}  # Naponta 1x Telegram üzenet páronként

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        cfg_path = Path(__file__).parent / "rb_pair_configs.json"
        if cfg_path.exists():
            with open(cfg_path) as f:
                self.pair_configs = json.load(f)
            logger.info(
                f"RangeBreakout | rb_pair_configs.json betöltve, "
                f"{len(self.pair_configs)} pár konfigurálva"
            )
        else:
            self.pair_configs = {}
            logger.warning(
                "RangeBreakout | rb_pair_configs.json nem található, "
                "default hyperopt értékek lesznek használva"
            )
        self._bp_tz = pytz.timezone("Europe/Budapest")

    def _p(self, pair: str, key: str):
        """Páronkénti paraméter lookup. Ha a pár benne van rb_pair_configs.json-ban,
        onnan adja vissza az értéket. Egyébként a hyperopt/default értékre esik vissza.
        Hyperopthoz: távolítsd el a párt a rb_pair_configs.json-ból (vagy _ prefix),
        így a hyperopt próbálgatja az értékeket."""
        if pair in self.pair_configs and key in self.pair_configs[pair]:
            return self.pair_configs[pair][key]
        return getattr(self, key).value

    def informative_pairs(self):
        # A range 5m gyertyák timezone-aware aggregálásából számolódik.
        # Az exchange 4H gyertyák UTC-aligned-ek (00:00, 04:00, 08:00...),
        # NY 00:00-04:00 EST = UTC 05:00-09:00 = két exchange 4H gyertya → nem használható.
        return []

    def custom_stake_amount(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_stake: float,
        min_stake: Optional[float],
        max_stake: float,
        leverage: float,
        entry_tag: Optional[str],
        side: str,
        **kwargs,
    ) -> float:
        return 5.0  # Fix 5 USDC fedezet (margin) per trade; 5 * 20x = 100 USDC pozíció

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        pair = metadata["pair"]

        # Paraméterek kiolvasása (rb_pair_configs.json vagy hyperopt default)
        tz_str = self._p(pair, "range_timezone")
        ref_tz = pytz.timezone(tz_str)
        min_range_pct = self._p(pair, "min_range_size_pct")
        max_range_pct = self._p(pair, "max_range_size_pct")
        min_bo_dist_pct = self._p(pair, "min_breakout_distance_pct")
        max_bars = self._p(pair, "max_setup_bars")
        stop_buf = self._p(pair, "stop_buffer_pct")
        rr_ratio = self._p(pair, "risk_reward_ratio")

        logger.info(
            f"RangeBreakout | {pair} | tz={tz_str}, rr={rr_ratio}, "
            f"range=[{min_range_pct}%-{max_range_pct}%], max_bars={max_bars}, "
            f"buf={stop_buf}"
        )

        # --- Vektorizált UTC → referencia időzóna konverzió ---
        # A Freqtrade datetime-ek UTC-ben vannak (néha timezone-naive, néha aware)
        date_idx = pd.DatetimeIndex(dataframe["date"])
        if date_idx.tz is None:
            date_idx = date_idx.tz_localize("UTC")
        else:
            date_idx = date_idx.tz_convert("UTC")
        date_ref = date_idx.tz_convert(ref_tz)
        ref_hours = date_ref.hour.to_numpy()       # numpy int array
        ref_dates = date_ref.strftime("%Y-%m-%d")  # pandas Index of strings

        # --- Pre-allokált eredmény oszlopok ---
        n = len(dataframe)
        dataframe["range_high"] = np.nan
        dataframe["range_low"] = np.nan
        dataframe["range_valid"] = np.int8(0)
        dataframe["ref_date_str"] = ref_dates.values  # debug / logoláshoz
        dataframe["signal_long"] = np.int8(0)
        dataframe["signal_short"] = np.int8(0)
        dataframe["sl_price"] = np.nan
        dataframe["tp_price"] = np.nan

        # Oszlop index cache (gyorsabb .iat[] hozzáférés)
        col = {c: dataframe.columns.get_loc(c) for c in [
            "range_high", "range_low", "range_valid",
            "signal_long", "signal_short", "sl_price", "tp_price",
            "close", "high", "low",
        ]}

        # --- Iteratív állapotgép ---
        # Szükséges mert a kitörés és visszazárás közötti állapot (bo_dir, bo_extreme)
        # nem fejezhető ki tisztán vektorizált pandas műveletekkel.
        current_ref_date = ""
        range_build_high = -np.inf  # Gyűjti a high-t a 00:00-03:55 ablakban
        range_build_low = np.inf    # Gyűjti a low-t a 00:00-03:55 ablakban
        range_h = np.nan            # Lezárt, érvényes range high
        range_l = np.nan            # Lezárt, érvényes range low
        range_is_valid = False

        bo_dir = 0          # 0=nincs aktív kitörés, 1=felső, -1=alsó
        bo_extreme = np.nan # felső: max HIGH; alsó: min LOW a kitörési szakaszon
        bo_bars = 0         # hány bar telt el a kitörés óta

        for i in range(n):
            ref_date = ref_dates[i]
            ref_hour = int(ref_hours[i])
            close = dataframe.iat[i, col["close"]]
            high = dataframe.iat[i, col["high"]]
            low = dataframe.iat[i, col["low"]]

            # --- Új referencia nap detektálás → teljes állapot reset ---
            if ref_date != current_ref_date:
                if current_ref_date:
                    logger.debug(
                        f"RangeBreakout | {pair} | Napi reset: {current_ref_date} → {ref_date}"
                    )
                current_ref_date = ref_date
                range_build_high = -np.inf
                range_build_low = np.inf
                range_h = np.nan
                range_l = np.nan
                range_is_valid = False
                bo_dir = 0
                bo_extreme = np.nan
                bo_bars = 0

            # --- Range ablak (00:00–03:55 ref TZ): 5m gyertyák aggregálása ---
            if ref_hour < 4:
                # Még az ablakban vagyunk: gyűjtsük a szélső értékeket
                range_build_high = max(range_build_high, high)
                range_build_low = min(range_build_low, low)
                # range_is_valid marad False amíg az ablak le nem zárt

            elif not range_is_valid and range_build_high > -np.inf:
                # Első gyertya ref_hour >= 4 után: az ablak lezárt, rögzítjük a range-et
                range_h = range_build_high
                range_l = range_build_low
                range_is_valid = True
                range_size_pct = (range_h - range_l) / range_l * 100
                logger.info(
                    f"RangeBreakout | {pair} | {ref_date} ({tz_str}) | "
                    f"Range kész: H={range_h:.6f} L={range_l:.6f} "
                    f"({range_size_pct:.2f}%)"
                )

            # Oszlop értékek írása minden gyertyára
            dataframe.iat[i, col["range_high"]] = range_h
            dataframe.iat[i, col["range_low"]] = range_l
            dataframe.iat[i, col["range_valid"]] = 1 if range_is_valid else 0

            # --- Ha nincs érvényes range, nincs trading ---
            if not range_is_valid:
                continue

            # --- Range méret szűrés ---
            range_size_pct = (range_h - range_l) / range_l * 100
            if range_size_pct < min_range_pct or range_size_pct > max_range_pct:
                # Range túl kicsi vagy túl nagy ezen a napon
                continue

            # --- Breakout + Pullback állapotgép ---

            if bo_dir == 0:
                # Felső kitörés: close szigorúan a range_high fölött zár
                if close > range_h:
                    dist = (close - range_h) / range_h * 100
                    if dist >= min_bo_dist_pct:
                        bo_dir = 1
                        bo_extreme = high   # Az első kitörő gyertya HIGH-ja
                        bo_bars = 0
                        logger.debug(
                            f"RangeBreakout | {pair} | Felső kitörés: "
                            f"close={close:.4f} > range_h={range_h:.4f} (+{dist:.2f}%)"
                        )

                # Alsó kitörés: close szigorúan a range_low alatt zár
                elif close < range_l:
                    dist = (range_l - close) / range_l * 100
                    if dist >= min_bo_dist_pct:
                        bo_dir = -1
                        bo_extreme = low    # Az első kitörő gyertya LOW-ja
                        bo_bars = 0
                        logger.debug(
                            f"RangeBreakout | {pair} | Alsó kitörés: "
                            f"close={close:.4f} < range_l={range_l:.4f} (-{dist:.2f}%)"
                        )

            elif bo_dir == 1:
                # Felső kitörés aktív → SHORT-ra várunk (visszazárásra)
                bo_bars += 1
                bo_extreme = max(bo_extreme, high)  # Running max HIGH frissítés

                if bo_bars > max_bars:
                    # Setup lejárt
                    logger.debug(
                        f"RangeBreakout | {pair} | Felső kitörés lejárt "
                        f"({max_bars} bar = {max_bars * 5} perc)"
                    )
                    bo_dir = 0
                    bo_extreme = np.nan

                elif close <= range_h:
                    # Visszazárás a range-be → SHORT belépési jel
                    sl = bo_extreme * (1.0 + stop_buf / 100.0)
                    r = abs(sl - close)
                    tp = close - r * rr_ratio

                    dataframe.iat[i, col["signal_short"]] = 1
                    dataframe.iat[i, col["sl_price"]] = sl
                    dataframe.iat[i, col["tp_price"]] = tp

                    logger.info(
                        f"RangeBreakout | {pair} | SHORT SIGNAL | "
                        f"entry~={close:.4f} SL={sl:.4f} TP={tp:.4f} | "
                        f"kitörés extreme={bo_extreme:.4f} ({bo_bars} bar alatt)"
                    )
                    # Reset: ugyanazon a napon új setup indulhat
                    bo_dir = 0
                    bo_extreme = np.nan

            elif bo_dir == -1:
                # Alsó kitörés aktív → LONG-ra várunk (visszazárásra)
                bo_bars += 1
                bo_extreme = min(bo_extreme, low)   # Running min LOW frissítés

                if bo_bars > max_bars:
                    # Setup lejárt
                    logger.debug(
                        f"RangeBreakout | {pair} | Alsó kitörés lejárt "
                        f"({max_bars} bar = {max_bars * 5} perc)"
                    )
                    bo_dir = 0
                    bo_extreme = np.nan

                elif close >= range_l:
                    # Visszazárás a range-be → LONG belépési jel
                    sl = bo_extreme * (1.0 - stop_buf / 100.0)
                    r = abs(close - sl)
                    tp = close + r * rr_ratio

                    dataframe.iat[i, col["signal_long"]] = 1
                    dataframe.iat[i, col["sl_price"]] = sl
                    dataframe.iat[i, col["tp_price"]] = tp

                    logger.info(
                        f"RangeBreakout | {pair} | LONG SIGNAL | "
                        f"entry~={close:.4f} SL={sl:.4f} TP={tp:.4f} | "
                        f"kitörés extreme={bo_extreme:.4f} ({bo_bars} bar alatt)"
                    )
                    # Reset: ugyanazon a napon új setup indulhat
                    bo_dir = 0
                    bo_extreme = np.nan

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["signal_long"] == 1) & (dataframe["volume"] > 0),
            ["enter_long", "enter_tag"],
        ] = (1, "rb_pullback_long")

        dataframe.loc[
            (dataframe["signal_short"] == 1) & (dataframe["volume"] > 0),
            ["enter_short", "enter_tag"],
        ] = (1, "rb_pullback_short")

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Kilépés kizárólag custom_exit (TP) és custom_stoploss (SL) által
        return dataframe

    def order_filled(
        self, pair: str, trade: Trade, order, current_time: datetime, **kwargs
    ) -> None:
        """Belépési order teljesülésekor rögzíti az SL és TP árakat a trade-en."""
        if order.ft_order_side == trade.entry_side:
            dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
            if dataframe.empty:
                return
            last = dataframe.iloc[-1]

            sl_price = last["sl_price"]
            tp_price = last["tp_price"]

            if not np.isnan(float(sl_price)):
                trade.set_custom_data("sl_price", float(sl_price))
            if not np.isnan(float(tp_price)):
                trade.set_custom_data("tp_price", float(tp_price))

            logger.info(
                f"RangeBreakout | {pair} | {'SHORT' if trade.is_short else 'LONG'} "
                f"filled @ {order.safe_price:.6f} | SL={sl_price:.6f} TP={tp_price:.6f}"
            )

    def custom_stoploss(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        after_fill: bool,
        **kwargs,
    ) -> Optional[float]:
        """ATR alapú SL visszaadása - az order_filled-ben tárolt ár alapján."""
        sl_price = trade.get_custom_data("sl_price")
        if sl_price is not None:
            return stoploss_from_absolute(
                sl_price, current_rate, trade.is_short, trade.leverage
            )
        return None

    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ) -> Optional[str]:
        """R-alapú take profit ellenőrzés minden gyertyán."""
        tp_price = trade.get_custom_data("tp_price")
        if tp_price is None:
            return None

        if trade.is_short and current_rate <= tp_price:
            logger.info(
                f"RangeBreakout | {pair} | SHORT TP hit @ {current_rate:.6f} "
                f"(target={tp_price:.6f}, profit={current_profit:.2%})"
            )
            return "rb_tp_hit"
        elif not trade.is_short and current_rate >= tp_price:
            logger.info(
                f"RangeBreakout | {pair} | LONG TP hit @ {current_rate:.6f} "
                f"(target={tp_price:.6f}, profit={current_profit:.2%})"
            )
            return "rb_tp_hit"

        return None

    def leverage(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_leverage: float,
        max_leverage: float,
        entry_tag: Optional[str],
        side: str,
        **kwargs,
    ) -> float:
        return 20.0  # Fix 20x leverage, isolated margin

    def bot_loop_start(self, current_time: datetime, **kwargs) -> None:
        """Gyertyánkénti logolás: range állapot, close, Budapest idő."""
        bp_now = datetime.now(self._bp_tz)

        for pair in self.dp.current_whitelist():
            dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
            if dataframe.empty:
                continue

            last = dataframe.iloc[-1]
            candle_time = last["date"]

            # Csak új gyertyánál logol (nem minden 5 másodpercben)
            if self._last_logged_candle.get(pair) == candle_time:
                continue
            self._last_logged_candle[pair] = candle_time

            range_h = last.get("range_high", float("nan"))
            range_l = last.get("range_low", float("nan"))
            range_valid = last.get("range_valid", 0)
            ref_date = last.get("ref_date_str", "")
            close = last["close"]
            tz_str = self._p(pair, "range_timezone")

            logger.info(
                f"[{pair}] {candle_time} (BP: {bp_now:%H:%M}) | "
                f"close={close:.4f} | "
                f"range[{range_l:.4f} / {range_h:.4f}] valid={int(range_valid)} | "
                f"ref_date={ref_date} ({tz_str})"
            )

            # Telegram értesítés: új napi range kialakult (naponta egyszer páronként)
            if range_valid and ref_date:
                last_notified = self._last_range_notified.get(pair)
                if last_notified != ref_date:
                    self._last_range_notified[pair] = ref_date
                    if not np.isnan(float(range_h)) and not np.isnan(float(range_l)):
                        range_size_pct = (range_h - range_l) / range_l * 100
                        msg = (
                            f"*{pair}* - Napi range ({ref_date})\n"
                            f"High: `{range_h:.4f}`\n"
                            f"Low: `{range_l:.4f}`\n"
                            f"Meret: `{range_size_pct:.2f}%`\n"
                            f"TZ: {tz_str}"
                        )
                        try:
                            self.dp.send_msg(msg)
                        except Exception:
                            logger.info(
                                f"RangeBreakout | {pair} | Napi range ({ref_date}): "
                                f"H={range_h:.4f} L={range_l:.4f} ({range_size_pct:.2f}%)"
                            )
