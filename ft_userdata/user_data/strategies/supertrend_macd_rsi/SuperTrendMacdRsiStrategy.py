"""
SuperTrendMacdRsiStrategy - SuperTrend + MACD + RSI Futures Strategy

Long:  close > SuperTrend (uptrend) AND RSI > threshold AND MACD > Signal
Short: close < SuperTrend (downtrend) AND RSI < (100-threshold) AND MACD < Signal

Stop Loss:  swing-based (lowest low / highest high over lookback)
Take Profit: R-based (risk_reward_ratio × distance to SL)
Leverage:   fixed 20x, isolated margin
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import talib.abstract as ta
from pandas import DataFrame

from freqtrade.persistence import Trade
from freqtrade.strategy import (
    DecimalParameter,
    IStrategy,
    IntParameter,
    stoploss_from_absolute,
)

logger = logging.getLogger(__name__)


class SuperTrendMacdRsiStrategy(IStrategy):

    INTERFACE_VERSION = 3

    can_short = True

    timeframe = "1h"
    startup_candle_count = 150

    # Hard stoploss kikapcsolva (custom_stoploss kezeli)
    stoploss = -0.99
    use_custom_stoploss = True

    # ROI kikapcsolva (TP custom_exit kezeli, SL custom_stoploss)
    minimal_roi = {"0": 999}

    # --- Hyperopt paraméterek ---
    supertrend_atr_period = IntParameter(7, 21, default=10, space="buy")
    supertrend_multiplier = DecimalParameter(1.5, 4.0, default=3.0, space="buy")
    rsi_threshold = IntParameter(45, 60, default=50, space="buy")
    swing_lookback = IntParameter(5, 20, default=10, space="buy")
    risk_reward_ratio = DecimalParameter(1.0, 3.0, default=1.5, space="buy")
    # 0.0 = kikapcsolt szűrő
    max_candle_size_pct = DecimalParameter(0.0, 5.0, default=0.0, space="buy")
    # Trade méret USD-ben - plain float, nem hyperopt paraméter
    # Páronként felülírható az st_pair_configs.json-ban: "stake_amount_usd": 15.0
    stake_amount_usd: float = 10.0

    # Gyertyánkénti logoláshoz: utolsó logolt gyertya timestamp páronként
    _last_logged_candle: dict = {}

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        cfg_path = Path(__file__).parent / "st_pair_configs.json"
        if cfg_path.exists():
            with open(cfg_path) as f:
                self.pair_configs = json.load(f)
            logger.info(
                f"SuperTrendMacdRsi | st_pair_configs.json betöltve, "
                f"{len(self.pair_configs)} pár konfigurálva"
            )
        else:
            self.pair_configs = {}
            logger.warning(
                "SuperTrendMacdRsi | st_pair_configs.json nem található, "
                "default értékek lesznek használva"
            )

    def _p(self, pair: str, key: str):
        """Páronkénti paraméter lookup.
        Ha a pár benne van a st_pair_configs.json-ban, onnan adja vissza az értéket,
        egyébként a hyperopt/default paraméterre esik vissza."""
        if pair in self.pair_configs and key in self.pair_configs[pair]:
            return self.pair_configs[pair][key]
        return getattr(self, key).value

    def custom_stake_amount(
        self,
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
        """Páronkénti trade méret USD-ben.
        Az st_pair_configs.json-ban felülírható: "stake_amount_usd": 15.0"""
        pair = kwargs.get("pair", "")
        stake = float(self.pair_configs.get(pair, {}).get("stake_amount_usd", self.stake_amount_usd))
        return min(stake, max_stake)

    @property
    def plot_config(self):
        return {
            "main_plot": {
                # SuperTrend vonal (ahol az SL "mozog" amíg nincs trade)
                "supertrend": {
                    "color": "#2962FF",
                    "type": "line",
                    "width": 2
                },
                # Swing pontok = ahol az SL kerül belépéskor
                "swing_high": {
                    "color": "#F44336",
                    "type": "line",
                    "width": 1
                },
                "swing_low": {
                    "color": "#4CAF50",
                    "type": "line",
                    "width": 1
                },
            },
            "subplots": {
                "RSI": {
                    "rsi": {
                        "color": "#9C27B0",
                        "width": 1
                    }
                },
                "MACD": {
                    "macd": {"color": "#2196F3"},
                    "macdsignal": {"color": "#FF9800"},
                    "macdhist": {
                        "color": "#B0BEC5",
                        "type": "bar",
                        "width": 4
                    }
                }
            }
        }

    def informative_pairs(self):
        # Csak 1H timeframe-et használunk, nincs informative pair
        return []

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        pair = metadata["pair"]

        atr_period = int(self._p(pair, "supertrend_atr_period"))
        multiplier = float(self._p(pair, "supertrend_multiplier"))
        swing_lb = int(self._p(pair, "swing_lookback"))

        # --- RSI ---
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)

        # --- MACD ---
        macd = ta.MACD(dataframe)
        dataframe["macd"] = macd["macd"]
        dataframe["macdsignal"] = macd["macdsignal"]
        dataframe["macdhist"] = macd["macdhist"]

        # --- ATR (SuperTrend alapja) ---
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=atr_period)

        # --- SuperTrend explicit implementáció ---
        # Képletek:
        #   hl2 = (high + low) / 2
        #   basicUpperBand = hl2 + multiplier * ATR
        #   basicLowerBand = hl2 - multiplier * ATR
        #
        # Végleges sávok (állapotfüggő, sor-by-sor loop szükséges):
        #   upperBand = basicUpperBand ha basicUpperBand < prev_upperBand VAGY prev_close > prev_upperBand
        #               egyébként upperBand = prev_upperBand
        #   lowerBand = basicLowerBand ha basicLowerBand > prev_lowerBand VAGY prev_close < prev_lowerBand
        #               egyébként lowerBand = prev_lowerBand
        #
        # Trendirány:
        #   ATR hiánya esetén: downtrend
        #   ha prev_superTrend == prev_upperBand:
        #     close > upperBand → uptrend, különben downtrend
        #   egyébként:
        #     close < lowerBand → downtrend, különben uptrend
        #
        # Végső SuperTrend: uptrend → lowerBand, downtrend → upperBand

        hl2 = (dataframe["high"] + dataframe["low"]) / 2
        basic_upper = hl2 + multiplier * dataframe["atr"]
        basic_lower = hl2 - multiplier * dataframe["atr"]

        n = len(dataframe)
        upper_band = np.full(n, np.nan)
        lower_band = np.full(n, np.nan)
        supertrend = np.full(n, np.nan)
        direction = np.full(n, -1, dtype=np.int8)  # -1 = downtrend, 1 = uptrend

        close_arr = dataframe["close"].values
        basic_upper_arr = basic_upper.values
        basic_lower_arr = basic_lower.values
        atr_arr = dataframe["atr"].values

        for i in range(n):
            # ATR még nem elérhető → downtrend default
            if np.isnan(atr_arr[i]):
                upper_band[i] = basic_upper_arr[i] if not np.isnan(basic_upper_arr[i]) else 0.0
                lower_band[i] = basic_lower_arr[i] if not np.isnan(basic_lower_arr[i]) else 0.0
                supertrend[i] = upper_band[i]
                direction[i] = -1
                continue

            # Felső sáv számítása
            if i == 0:
                upper_band[i] = basic_upper_arr[i]
            elif basic_upper_arr[i] < upper_band[i - 1] or close_arr[i - 1] > upper_band[i - 1]:
                # basicUpperBand kisebb az előzőnél VAGY az előző close az előző upperBand felett volt
                upper_band[i] = basic_upper_arr[i]
            else:
                upper_band[i] = upper_band[i - 1]

            # Alsó sáv számítása
            if i == 0:
                lower_band[i] = basic_lower_arr[i]
            elif basic_lower_arr[i] > lower_band[i - 1] or close_arr[i - 1] < lower_band[i - 1]:
                # basicLowerBand nagyobb az előzőnél VAGY az előző close az előző lowerBand alatt volt
                lower_band[i] = basic_lower_arr[i]
            else:
                lower_band[i] = lower_band[i - 1]

            # Trendirány meghatározása
            if i == 0:
                direction[i] = -1  # Első gyertya: downtrend default
            elif supertrend[i - 1] == upper_band[i - 1]:
                # Előző SuperTrend az upperBand volt → downtrend volt
                if close_arr[i] > upper_band[i]:
                    direction[i] = 1   # Áttört az upperBand fölé → uptrend
                else:
                    direction[i] = -1  # Marad downtrend
            else:
                # Előző SuperTrend a lowerBand volt → uptrend volt
                if close_arr[i] < lower_band[i]:
                    direction[i] = -1  # Áttört a lowerBand alá → downtrend
                else:
                    direction[i] = 1   # Marad uptrend

            # Végső SuperTrend érték
            if direction[i] == 1:
                supertrend[i] = lower_band[i]   # Uptrend: SuperTrend = lowerBand
            else:
                supertrend[i] = upper_band[i]   # Downtrend: SuperTrend = upperBand

        dataframe["supertrend"] = supertrend
        dataframe["supertrend_direction"] = direction.astype(float)
        dataframe["st_upperband"] = upper_band
        dataframe["st_lowerband"] = lower_band

        # --- Swing pontok az SL-hez ---
        dataframe["swing_low"] = dataframe["low"].rolling(window=swing_lb).min()
        dataframe["swing_high"] = dataframe["high"].rolling(window=swing_lb).max()

        logger.info(
            f"SuperTrendMacdRsi | {pair} | "
            f"atr_period={atr_period}, multiplier={multiplier}, swing_lookback={swing_lb}"
        )

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        pair = metadata["pair"]
        rsi_thr = self._p(pair, "rsi_threshold")
        max_candle = self._p(pair, "max_candle_size_pct")

        # Gyertya mérete (body) százalékban a close-hoz képest
        candle_body_pct = (abs(dataframe["close"] - dataframe["open"]) / dataframe["close"]) * 100

        # --- LONG belépési feltételek ---
        # Csak a trendváltás első gyertyáján lép be:
        # az előző gyertya DOWN volt, a jelenlegi UP → trendváltás pillanata
        long_cond = (
            (dataframe["supertrend_direction"] == 1)           # jelenlegi: uptrend
            & (dataframe["supertrend_direction"].shift(1) == -1)  # előző: downtrend (váltás!)
            & (dataframe["rsi"] > rsi_thr)
            & (dataframe["macd"] > dataframe["macdsignal"])
            & (dataframe["volume"] > 0)
        )

        # --- SHORT belépési feltételek ---
        # Csak a trendváltás első gyertyáján lép be:
        # az előző gyertya UP volt, a jelenlegi DOWN → trendváltás pillanata
        short_cond = (
            (dataframe["supertrend_direction"] == -1)          # jelenlegi: downtrend
            & (dataframe["supertrend_direction"].shift(1) == 1)   # előző: uptrend (váltás!)
            & (dataframe["rsi"] < (100 - rsi_thr))
            & (dataframe["macd"] < dataframe["macdsignal"])
            & (dataframe["volume"] > 0)
        )

        # Opcionális gyertya méret szűrő (max_candle_size_pct > 0 esetén aktív)
        if max_candle > 0:
            long_cond = long_cond & (candle_body_pct < max_candle)
            short_cond = short_cond & (candle_body_pct < max_candle)

        dataframe.loc[long_cond, ["enter_long", "enter_tag"]] = (1, "st_macd_rsi_long")
        dataframe.loc[short_cond, ["enter_short", "enter_tag"]] = (1, "st_macd_rsi_short")

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Kilépést custom_exit (TP) és custom_stoploss (SL) kezeli
        return dataframe

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
        return 20.0

    def order_filled(
        self, pair: str, trade: Trade, order, current_time: datetime, **kwargs
    ) -> None:
        """Belépési megbízás teljesülése után SL és TP ár kiszámítása és tárolása."""
        if order.ft_order_side != trade.entry_side:
            return

        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe.empty:
            return

        last_candle = dataframe.iloc[-1]

        # Swing-alapú stop loss
        if trade.is_short:
            sl_price = float(last_candle["swing_high"])  # SHORT SL: legutóbbi swing high fölé
        else:
            sl_price = float(last_candle["swing_low"])   # LONG SL: legutóbbi swing low alá

        # Ellenőrzés NaN-ra (nem elegendő adat a rolling ablakhoz)
        if np.isnan(sl_price):
            logger.warning(
                f"SuperTrendMacdRsi | {pair} | "
                f"swing {'high' if trade.is_short else 'low'} NaN - SL nem kerül beállításra"
            )
            return

        # R-alapú take profit
        entry_price = float(order.safe_price)
        rr_ratio = self._p(pair, "risk_reward_ratio")
        r = abs(entry_price - sl_price)

        if trade.is_short:
            tp_price = entry_price - r * rr_ratio   # SHORT TP: belépési ár - R*RR
        else:
            tp_price = entry_price + r * rr_ratio   # LONG TP: belépési ár + R*RR

        trade.set_custom_data("sl_price", sl_price)
        trade.set_custom_data("tp_price", tp_price)

        direction = "SHORT" if trade.is_short else "LONG"
        logger.info(
            f"SuperTrendMacdRsi | {pair} | "
            f"{direction} filled @ {entry_price:.6f} | "
            f"SL={sl_price:.6f} | TP={tp_price:.6f} | "
            f"R={r:.6f} | RR={rr_ratio}"
        )

        # Telegram értesítés TP/SL szintekkel
        sl_pct = abs(entry_price - sl_price) / entry_price * 100
        tp_pct = abs(tp_price - entry_price) / entry_price * 100
        self.dp.send_msg(
            f"📊 *{pair}* {direction} #{trade.id}\n"
            f"Entry: `{entry_price:.4f}` USDC\n"
            f"🛑 SL: `{sl_price:.4f}` ({sl_pct:.2f}%)\n"
            f"🎯 TP: `{tp_price:.4f}` ({tp_pct:.2f}%)\n"
            f"RR: {rr_ratio:.1f}x | Stake: {trade.stake_amount:.1f} USDC"
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
        """Swing-alapú stop loss visszaadása a custom_data-ból."""
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
        """R-alapú take profit ellenőrzése minden gyertyán."""
        tp_price = trade.get_custom_data("tp_price")
        if tp_price is None:
            return None

        if trade.is_short and current_rate <= tp_price:
            logger.info(
                f"SuperTrendMacdRsi | {pair} | SHORT TP hit @ {current_rate:.6f} "
                f"(target={tp_price:.6f})"
            )
            return "st_tp_hit"
        elif not trade.is_short and current_rate >= tp_price:
            logger.info(
                f"SuperTrendMacdRsi | {pair} | LONG TP hit @ {current_rate:.6f} "
                f"(target={tp_price:.6f})"
            )
            return "st_tp_hit"

        return None

    def bot_loop_start(self, current_time: datetime, **kwargs) -> None:
        """Gyertyánkénti logolás - csak új gyertyánál fut (nem minden 5 másodpercben)."""
        for pair in self.dp.current_whitelist():
            dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
            if dataframe.empty:
                continue

            last = dataframe.iloc[-1]
            candle_time = last["date"]

            # Csak új gyertyánál logol
            if self._last_logged_candle.get(pair) == candle_time:
                continue
            self._last_logged_candle[pair] = candle_time

            rsi_thr = self._p(pair, "rsi_threshold")

            close = last["close"]
            supertrend = last.get("supertrend", float("nan"))
            st_dir = last.get("supertrend_direction", float("nan"))
            rsi = last.get("rsi", float("nan"))
            macd = last.get("macd", float("nan"))
            macdsignal = last.get("macdsignal", float("nan"))
            swing_low = last.get("swing_low", float("nan"))
            swing_high = last.get("swing_high", float("nan"))

            trend_str = "UP" if st_dir == 1 else "DOWN"

            logger.info(
                f"[{pair}] {candle_time} | "
                f"close={close:.4f}  ST={supertrend:.4f}({trend_str})  "
                f"RSI={rsi:.1f}  MACD={macd:.4f}/SIG={macdsignal:.4f}  "
                f"SwLow={swing_low:.4f}  SwHigh={swing_high:.4f}"
            )

            # --- LONG feltételek ellenőrzése ---
            long_blocks = []
            if st_dir != 1:
                long_blocks.append(f"ST downtrend (dir={st_dir:.0f})")
            if not (rsi > rsi_thr):
                long_blocks.append(f"RSI {rsi:.1f} <= {rsi_thr}")
            if not (macd > macdsignal):
                long_blocks.append(f"MACD {macd:.4f} <= SIG {macdsignal:.4f}")

            if long_blocks:
                logger.info(f"[{pair}] LONG  blokkolt: {' | '.join(long_blocks)}")
            else:
                logger.info(f"[{pair}] LONG  >>> SIGNAL READY <<<")

            # --- SHORT feltételek ellenőrzése ---
            short_blocks = []
            if st_dir != -1:
                short_blocks.append(f"ST uptrend (dir={st_dir:.0f})")
            if not (rsi < (100 - rsi_thr)):
                short_blocks.append(f"RSI {rsi:.1f} >= {100 - rsi_thr}")
            if not (macd < macdsignal):
                short_blocks.append(f"MACD {macd:.4f} >= SIG {macdsignal:.4f}")

            if short_blocks:
                logger.info(f"[{pair}] SHORT blokkolt: {' | '.join(short_blocks)}")
            else:
                logger.info(f"[{pair}] SHORT >>> SIGNAL READY <<<")

            # --- Nyitott trade TP/SL logolása (ha van) ---
            open_trades = Trade.get_open_trades()
            pair_trade = next((t for t in open_trades if t.pair == pair), None)
            if pair_trade:
                tp = pair_trade.get_custom_data("tp_price")
                sl = pair_trade.get_custom_data("sl_price")
                direction = "SHORT" if pair_trade.is_short else "LONG"
                profit_pct = pair_trade.calc_profit_ratio(close) * 100
                tp_dist = ((tp - close) / close * 100) if tp else float("nan")
                sl_dist = ((sl - close) / close * 100) if sl else float("nan")
                logger.info(
                    f"[{pair}] OPEN {direction} #{pair_trade.id} | "
                    f"entry={pair_trade.open_rate:.6f} | "
                    f"TP={tp:.6f} ({tp_dist:+.2f}%) | "
                    f"SL={sl:.6f} ({sl_dist:+.2f}%) | "
                    f"profit={profit_pct:+.2f}%"
                )
