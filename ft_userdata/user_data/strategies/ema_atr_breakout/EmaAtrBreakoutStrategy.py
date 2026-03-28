"""
EmaAtrBreakoutStrategy — EMA ± ATR Multi-Timeframe Breakout

Belépés (12H vezérli):
  LONG:  close < EMA(12H) - X * ATR(12H)  (ár visszaesett az EMA alá)
  SHORT: close > EMA(12H) + X * ATR(12H)  (ár felszúrt az EMA fölé)
  + gyertyavalidáció (zöld/piros)
  + polynomial regression curvature > 0 (trend gyengülés → fordulás)

Kilépés (1D vezérli):
  LONG TP:  close > EMA(1D) + X * ATR(1D)
  SHORT TP: close < EMA(1D) - X * ATR(1D)

StopLoss: swing-alapú (legutóbbi swing low/high)
Leverage: fix 20x, isolated margin
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import talib.abstract as ta
from pandas import DataFrame

from freqtrade.enums import RunMode
from freqtrade.persistence import Trade
from freqtrade.strategy import (
    DecimalParameter,
    IStrategy,
    IntParameter,
    merge_informative_pair,
    stoploss_from_absolute,
)

logger = logging.getLogger(__name__)


class EmaAtrBreakoutStrategy(IStrategy):

    INTERFACE_VERSION = 3
    can_short = True
    timeframe = "1h"
    startup_candle_count = 200

    stoploss = -0.99
    use_custom_stoploss = True
    minimal_roi = {"0": 999}

    # --- Hyperopt paraméterek ---
    ema_period = IntParameter(10, 50, default=21, space="buy")
    atr_period = IntParameter(7, 21, default=14, space="buy")
    atr_multiplier = DecimalParameter(1.0, 3.0, default=1.5, space="buy")
    swing_lookback = IntParameter(5, 20, default=10, space="buy")
    poly_lookback = IntParameter(5, 20, default=10, space="buy")

    # Trade méret (nem hyperopt, pair_configs-ban állítható)
    stake_amount_usd: float = 10.0

    _last_logged_candle: dict = {}

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        cfg_path = Path(__file__).parent / "eab_pair_configs.json"
        if cfg_path.exists():
            with open(cfg_path) as f:
                self.pair_configs = json.load(f)
            logger.info(f"EmaAtrBreakout | eab_pair_configs.json betöltve, {len(self.pair_configs)} pár")
        else:
            self.pair_configs = {}
            logger.warning("EmaAtrBreakout | eab_pair_configs.json nem található")

    def _p(self, pair: str, key: str):
        if pair in self.pair_configs and key in self.pair_configs[pair]:
            return self.pair_configs[pair][key]
        return getattr(self, key).value

    def informative_pairs(self):
        pairs = self.dp.current_whitelist()
        return [(pair, "12h") for pair in pairs] + [(pair, "1d") for pair in pairs]

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        pair = metadata["pair"]
        ema_p = int(self._p(pair, "ema_period"))
        atr_p = int(self._p(pair, "atr_period"))
        atr_x = float(self._p(pair, "atr_multiplier"))
        swing_lb = int(self._p(pair, "swing_lookback"))
        poly_lb = int(self._p(pair, "poly_lookback"))

        # === 12H informative (BELÉPÉSI szintek) ===
        inf_12h = self.dp.get_pair_dataframe(pair=pair, timeframe="12h")
        if not inf_12h.empty:
            inf_12h["ema"] = ta.EMA(inf_12h, timeperiod=ema_p)
            inf_12h["atr"] = ta.ATR(inf_12h, timeperiod=atr_p)
            dataframe = merge_informative_pair(dataframe, inf_12h, self.timeframe, "12h", ffill=True)

        # 12H belépési szintek
        dataframe["entry_long_level"] = dataframe["ema_12h"] - atr_x * dataframe["atr_12h"]
        dataframe["entry_short_level"] = dataframe["ema_12h"] + atr_x * dataframe["atr_12h"]

        # === 1D informative (KILÉPÉSI szintek) ===
        inf_1d = self.dp.get_pair_dataframe(pair=pair, timeframe="1d")
        if not inf_1d.empty:
            inf_1d["ema"] = ta.EMA(inf_1d, timeperiod=ema_p)
            inf_1d["atr"] = ta.ATR(inf_1d, timeperiod=atr_p)
            dataframe = merge_informative_pair(dataframe, inf_1d, self.timeframe, "1d", ffill=True)

        # 1D kilépési szintek
        dataframe["exit_long_level"] = dataframe["ema_1d"] + atr_x * dataframe["atr_1d"]
        dataframe["exit_short_level"] = dataframe["ema_1d"] - atr_x * dataframe["atr_1d"]

        # === Swing pontok (SL-hez) ===
        dataframe["swing_low"] = dataframe["low"].rolling(window=swing_lb).min()
        dataframe["swing_high"] = dataframe["high"].rolling(window=swing_lb).max()

        # === Polynomial regression (trend validáció) ===
        close_arr = dataframe["close"].values
        poly_curv = np.full(len(close_arr), np.nan)

        for i in range(poly_lb, len(close_arr)):
            window = close_arr[i - poly_lb:i]
            if np.any(np.isnan(window)):
                continue
            x = np.arange(poly_lb)
            coeffs = np.polyfit(x, window, 2)
            poly_curv[i] = coeffs[0]  # másodfokú együttható = curvature

        dataframe["poly_curvature"] = poly_curv

        logger.info(
            f"EmaAtrBreakout | {pair} | ema={ema_p}, atr={atr_p}, X={atr_x}, "
            f"swing={swing_lb}, poly={poly_lb}"
        )

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # LONG: ár visszaesett a 12H EMA-X*ATR alá + zöld gyertya + trend gyengül
        dataframe.loc[
            (dataframe["close"] < dataframe["entry_long_level"])
            & (dataframe["close"] > dataframe["open"])        # zöld gyertya
            & (dataframe["poly_curvature"] > 0)                # csökkenés gyengül
            & (dataframe["volume"] > 0),
            ["enter_long", "enter_tag"],
        ] = (1, "ema_atr_long")

        # SHORT: ár felszúrt a 12H EMA+X*ATR fölé + piros gyertya + trend gyengül
        dataframe.loc[
            (dataframe["close"] > dataframe["entry_short_level"])
            & (dataframe["close"] < dataframe["open"])        # piros gyertya
            & (dataframe["poly_curvature"] > 0)                # emelkedés gyengül
            & (dataframe["volume"] > 0),
            ["enter_short", "enter_tag"],
        ] = (1, "ema_atr_short")

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return dataframe

    def leverage(self, pair, current_time, current_rate, proposed_leverage,
                 max_leverage, entry_tag, side, **kwargs) -> float:
        return 20.0

    def custom_stake_amount(self, current_time, current_rate, proposed_stake,
                            min_stake, max_stake, leverage, entry_tag, side, **kwargs) -> float:
        pair = kwargs.get("pair", "")
        stake = float(self.pair_configs.get(pair, {}).get("stake_amount_usd", self.stake_amount_usd))
        return min(stake, max_stake)

    def order_filled(self, pair, trade: Trade, order, current_time, **kwargs) -> None:
        if order.ft_order_side != trade.entry_side:
            return
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe.empty:
            return
        last = dataframe.iloc[-1]

        # Swing-alapú SL
        sl_price = float(last["swing_high"]) if trade.is_short else float(last["swing_low"])
        if np.isnan(sl_price):
            return

        trade.set_custom_data("sl_price", sl_price)

        entry_price = float(order.safe_price)
        direction = "SHORT" if trade.is_short else "LONG"
        logger.info(
            f"EmaAtrBreakout | {pair} | {direction} filled @ {entry_price:.4f} | SL={sl_price:.4f}"
        )

        # Telegram értesítés
        self.dp.send_msg(
            f"📊 *{pair}* {direction}\n"
            f"Entry: `{entry_price:.4f}`\n"
            f"🛑 SL: `{sl_price:.4f}`\n"
            f"🎯 TP: 1D EMA+ATR szintje"
        )

    def custom_stoploss(self, pair, trade: Trade, current_time, current_rate,
                        current_profit, after_fill, **kwargs) -> Optional[float]:
        sl_price = trade.get_custom_data("sl_price")
        if sl_price is not None:
            return stoploss_from_absolute(sl_price, current_rate, trade.is_short, trade.leverage)
        return None

    def custom_exit(self, pair, trade: Trade, current_time, current_rate,
                    current_profit, **kwargs) -> Optional[str]:
        """Kilépés az 1D EMA ± X*ATR szintje alapján."""
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe.empty:
            return None
        last = dataframe.iloc[-1]

        if not trade.is_short:
            # LONG TP ← 1D: EMA(1D) + X * ATR(1D)
            exit_level = last.get("exit_long_level", None)
            if exit_level and current_rate > exit_level:
                logger.info(f"EmaAtrBreakout | {pair} | LONG TP @ {current_rate:.4f} (1D level={exit_level:.4f})")
                return "ema_atr_tp"
        else:
            # SHORT TP ← 1D: EMA(1D) - X * ATR(1D)
            exit_level = last.get("exit_short_level", None)
            if exit_level and current_rate < exit_level:
                logger.info(f"EmaAtrBreakout | {pair} | SHORT TP @ {current_rate:.4f} (1D level={exit_level:.4f})")
                return "ema_atr_tp"

        return None

    @property
    def plot_config(self):
        return {
            "main_plot": {
                "ema_12h": {"color": "#2196F3", "width": 2},
                "entry_long_level": {"color": "#4CAF50", "type": "line"},
                "entry_short_level": {"color": "#F44336", "type": "line"},
                "exit_long_level": {"color": "#4CAF50", "type": "line", "width": 1},
                "exit_short_level": {"color": "#F44336", "type": "line", "width": 1},
                "swing_low": {"color": "#81C784"},
                "swing_high": {"color": "#E57373"},
            },
            "subplots": {
                "Poly Curvature": {
                    "poly_curvature": {"color": "#9C27B0"}
                }
            }
        }

    def bot_loop_start(self, current_time: datetime, **kwargs) -> None:
        if self.config.get("runmode") not in (RunMode.LIVE, RunMode.DRY_RUN):
            return

        for pair in self.dp.current_whitelist():
            dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
            if dataframe.empty:
                continue
            last = dataframe.iloc[-1]
            candle_time = last["date"]
            if self._last_logged_candle.get(pair) == candle_time:
                continue
            self._last_logged_candle[pair] = candle_time

            close = last["close"]
            entry_long = last.get("entry_long_level", float("nan"))
            entry_short = last.get("entry_short_level", float("nan"))
            exit_long = last.get("exit_long_level", float("nan"))
            exit_short = last.get("exit_short_level", float("nan"))
            curv = last.get("poly_curvature", float("nan"))

            logger.info(
                f"[{pair}] {candle_time} | close={close:.4f} | "
                f"12H entry: L<{entry_long:.4f} S>{entry_short:.4f} | "
                f"1D exit: L>{exit_long:.4f} S<{exit_short:.4f} | "
                f"curv={curv:.6f}"
            )

            # Nyitott trade logolás
            open_trades = Trade.get_open_trades()
            pair_trade = next((t for t in open_trades if t.pair == pair), None)
            if pair_trade:
                sl = pair_trade.get_custom_data("sl_price")
                direction = "SHORT" if pair_trade.is_short else "LONG"
                tp_level = exit_short if pair_trade.is_short else exit_long
                profit_pct = pair_trade.calc_profit_ratio(close) * 100
                logger.info(
                    f"[{pair}] OPEN {direction} #{pair_trade.id} | "
                    f"entry={pair_trade.open_rate:.4f} | "
                    f"SL={sl:.4f} | TP(1D)={tp_level:.4f} | "
                    f"profit={profit_pct:+.2f}%"
                )
