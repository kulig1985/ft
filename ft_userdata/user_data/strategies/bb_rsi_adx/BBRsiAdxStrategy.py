"""
BBRsiAdxStrategy - Bollinger Bands + RSI + ADX Futures Strategy

Long: 4H RSI > threshold, 1H & 4H ADX > threshold, close < BB lower
Short: 4H RSI < (100 - threshold), 1H & 4H ADX > threshold, close > BB upper

Exit Long: close > BB upper
Exit Short: close < BB lower

Stoploss: ATR-based, set at signal candle and held until exit.
Leverage: fixed 20x, isolated margin.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

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


class BBRsiAdxStrategy(IStrategy):

    INTERFACE_VERSION = 3

    can_short = True

    timeframe = "1h"
    startup_candle_count = 150

    # Hard stoploss disabled (custom stoploss handles it)
    stoploss = -0.99
    use_custom_stoploss = True

    # ROI disabled (exit via BB signal only)
    minimal_roi = {"0": 999}

    # --- Hyperopt parameters ---
    bb_period = IntParameter(15, 20, default=20, space="buy")
    bb_std = DecimalParameter(1.5, 2.0, default=2.0, space="buy")
    rsi_threshold = IntParameter(50, 55, default=55, space="buy")
    adx_threshold_1h = IntParameter(20, 25, default=20, space="buy")
    adx_threshold_4h = IntParameter(25, 30, default=25, space="buy")
    atr_multiplier = DecimalParameter(3.0, 5.0, default=4.5, space="buy")

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        cfg_path = Path(__file__).parent / "pair_configs.json"
        if cfg_path.exists():
            with open(cfg_path) as f:
                self.pair_configs = json.load(f)
            logger.info(
                f"BBRsiAdx | pair_configs.json betöltve, "
                f"{len(self.pair_configs)} pár konfigurálva"
            )
        else:
            self.pair_configs = {}
            logger.warning("BBRsiAdx | pair_configs.json nem található, default értékek lesznek használva")

    # Gyertyánkénti logoláshoz: utolsó logolt gyertya timestamp páronként
    _last_logged_candle: dict = {}
    _last_tg_trade_update: dict = {}  # Telegram trade update throttle (5 perc)

    def bot_loop_start(self, current_time: datetime, **kwargs) -> None:
        if self.config.get("runmode") not in (RunMode.LIVE, RunMode.DRY_RUN):
            return

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

            rsi_thr    = self._p(pair, "rsi_threshold")
            adx_thr_1h = self._p(pair, "adx_threshold_1h")
            adx_thr_4h = self._p(pair, "adx_threshold_4h")

            close     = last["close"]
            bb_upper  = last.get("bb_upper", float("nan"))
            bb_lower  = last.get("bb_lower", float("nan"))
            adx_1h    = last.get("adx",    float("nan"))
            adx_4h    = last.get("adx_4h", float("nan"))
            rsi_4h    = last.get("rsi_4h", float("nan"))

            logger.info(
                f"[{pair}] {candle_time} | "
                f"close={close:.4f}  BB[{bb_lower:.4f} / {bb_upper:.4f}]  "
                f"ADX1h={adx_1h:.1f}(>{adx_thr_1h})  "
                f"ADX4h={adx_4h:.1f}(>{adx_thr_4h})  "
                f"RSI4h={rsi_4h:.1f}"
            )

            # --- LONG feltételek ellenőrzése ---
            long_blocks = []
            if not (rsi_4h   > rsi_thr):    long_blocks.append(f"RSI4h {rsi_4h:.1f} <= {rsi_thr}")
            if not (adx_1h   > adx_thr_1h): long_blocks.append(f"ADX1h {adx_1h:.1f} <= {adx_thr_1h}")
            if not (adx_4h   > adx_thr_4h): long_blocks.append(f"ADX4h {adx_4h:.1f} <= {adx_thr_4h}")
            if not (close    < bb_lower):    long_blocks.append(f"close {close:.4f} >= BB_lower {bb_lower:.4f}")

            if long_blocks:
                logger.info(f"[{pair}] LONG  blokkolt: {' | '.join(long_blocks)}")
            else:
                logger.info(f"[{pair}] LONG  >>> SIGNAL READY <<<")

            # --- SHORT feltételek ellenőrzése ---
            short_blocks = []
            if not (rsi_4h < (100 - rsi_thr)): short_blocks.append(f"RSI4h {rsi_4h:.1f} >= {100 - rsi_thr}")
            if not (adx_1h > adx_thr_1h):      short_blocks.append(f"ADX1h {adx_1h:.1f} <= {adx_thr_1h}")
            if not (adx_4h > adx_thr_4h):      short_blocks.append(f"ADX4h {adx_4h:.1f} <= {adx_thr_4h}")
            if not (close  > bb_upper):         short_blocks.append(f"close {close:.4f} <= BB_upper {bb_upper:.4f}")

            if short_blocks:
                logger.info(f"[{pair}] SHORT blokkolt: {' | '.join(short_blocks)}")
            else:
                logger.info(f"[{pair}] SHORT >>> SIGNAL READY <<<")

        # --- Nyitott trade Telegram frissítés (5 percenként) ---
        for trade in Trade.get_open_trades():
            pair = trade.pair
            last_update = self._last_tg_trade_update.get(pair)
            if last_update is not None and (current_time - last_update).total_seconds() < 300:
                continue
            self._last_tg_trade_update[pair] = current_time

            dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
            if dataframe.empty:
                continue
            last = dataframe.iloc[-1]
            current_rate = float(last["close"])

            sl = trade.get_custom_data("sl_price")
            if sl is None:
                continue

            direction = "SHORT" if trade.is_short else "LONG"
            if trade.is_short:
                tp_10 = trade.open_rate * (1 - 0.10 / trade.leverage)
                sl_5 = trade.open_rate * (1 + 0.05 / trade.leverage)
            else:
                tp_10 = trade.open_rate * (1 + 0.10 / trade.leverage)
                sl_5 = trade.open_rate * (1 - 0.05 / trade.leverage)

            sl_atr_dist = abs(current_rate - sl) / current_rate * 100
            sl_5_dist = abs(current_rate - sl_5) / current_rate * 100
            tp_dist = abs(tp_10 - current_rate) / current_rate * 100
            profit_pct = trade.calc_profit_ratio(current_rate) * 100

            logger.info(
                f"[{pair}] OPEN {direction} #{trade.id} | "
                f"entry={trade.open_rate:.4f} | SL_ATR={sl:.4f} | "
                f"SL_5%={sl_5:.4f} | TP={tp_10:.4f} | profit={profit_pct:+.2f}%"
            )

            try:
                self.dp.send_msg(
                    f"📈 *{pair}* {direction} `{profit_pct:+.2f}%`\n"
                    f"Ár: `{current_rate:.4f}`\n"
                    f"🛑 SL ATR: `{sl:.4f}` táv: `{sl_atr_dist:.2f}%`\n"
                    f"🛑 SL 5%: `{sl_5:.4f}` táv: `{sl_5_dist:.2f}%`\n"
                    f"🎯 TP 10%: `{tp_10:.4f}` táv: `{tp_dist:.2f}%`"
                )
            except Exception:
                pass

    def _p(self, pair: str, key: str):
        """Páronkénti paraméter lookup. Ha a pár benne van a pair_configs-ban,
        onnan adja vissza az értéket, egyébként a hyperopt/default paraméterre esik vissza."""
        if pair in self.pair_configs and key in self.pair_configs[pair]:
            return self.pair_configs[pair][key]
        return getattr(self, key).value

    def informative_pairs(self):
        pairs = self.dp.current_whitelist()
        return [(pair, "4h") for pair in pairs]

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        pair = metadata["pair"]

        # --- 1H indicators ---
        bb_period = self._p(pair, "bb_period")
        bb_std = self._p(pair, "bb_std")
        atr_mult = self._p(pair, "atr_multiplier")

        bollinger = ta.BBANDS(
            dataframe,
            timeperiod=bb_period,
            nbdevup=bb_std,
            nbdevdn=bb_std,
            matype=0,
        )
        dataframe["bb_upper"] = bollinger["upperband"]
        dataframe["bb_mid"] = bollinger["middleband"]
        dataframe["bb_lower"] = bollinger["lowerband"]

        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)

        # Pre-calculate SL levels per candle (used in order_filled)
        dataframe["sl_long"] = dataframe["close"] - atr_mult * dataframe["atr"]
        dataframe["sl_short"] = dataframe["close"] + atr_mult * dataframe["atr"]

        logger.info(
            f"BBRsiAdx | {pair} | bb_period={bb_period}, bb_std={bb_std}, "
            f"atr_multiplier={atr_mult}"
        )

        # --- 4H informative ---
        inf_df = self.dp.get_pair_dataframe(pair=metadata["pair"], timeframe="4h")
        if not inf_df.empty:
            inf_df["rsi"] = ta.RSI(inf_df, timeperiod=14)
            inf_df["adx"] = ta.ADX(inf_df, timeperiod=14)

            dataframe = merge_informative_pair(
                dataframe, inf_df, self.timeframe, "4h", ffill=True
            )

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        pair = metadata["pair"]
        rsi_thr = self._p(pair, "rsi_threshold")
        adx_thr_1h = self._p(pair, "adx_threshold_1h")
        adx_thr_4h = self._p(pair, "adx_threshold_4h")

        # LONG entry
        dataframe.loc[
            (
                (dataframe["rsi_4h"] > rsi_thr)
                & (dataframe["adx"] > adx_thr_1h)
                & (dataframe["adx_4h"] > adx_thr_4h)
                & (dataframe["close"] < dataframe["bb_lower"])
                & (dataframe["volume"] > 0)
            ),
            ["enter_long", "enter_tag"],
        ] = (1, "bb_lower_rsi_adx")

        # SHORT entry
        dataframe.loc[
            (
                (dataframe["rsi_4h"] < (100 - rsi_thr))
                & (dataframe["adx"] > adx_thr_1h)
                & (dataframe["adx_4h"] > adx_thr_4h)
                & (dataframe["close"] > dataframe["bb_upper"])
                & (dataframe["volume"] > 0)
            ),
            ["enter_short", "enter_tag"],
        ] = (1, "bb_upper_rsi_adx")

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # LONG exit: price reaches upper band
        dataframe.loc[
            (
                (dataframe["close"] > dataframe["bb_upper"])
                & (dataframe["volume"] > 0)
            ),
            ["exit_long", "exit_tag"],
        ] = (1, "bb_upper_exit")

        # SHORT exit: price reaches lower band
        dataframe.loc[
            (
                (dataframe["close"] < dataframe["bb_lower"])
                & (dataframe["volume"] > 0)
            ),
            ["exit_short", "exit_tag"],
        ] = (1, "bb_lower_exit")

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
        if order.ft_order_side == trade.entry_side:
            dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
            if dataframe.empty:
                return
            last_candle = dataframe.iloc[-1]

            if trade.is_short:
                sl_price = last_candle["sl_short"]
            else:
                sl_price = last_candle["sl_long"]

            trade.set_custom_data("sl_price", float(sl_price))

            entry_price = float(order.safe_price)
            sl_atr = float(sl_price)
            direction = "SHORT" if trade.is_short else "LONG"
            if trade.is_short:
                tp_10 = entry_price * (1 - 0.10 / trade.leverage)
                sl_5 = entry_price * (1 + 0.05 / trade.leverage)
            else:
                tp_10 = entry_price * (1 + 0.10 / trade.leverage)
                sl_5 = entry_price * (1 - 0.05 / trade.leverage)

            logger.info(
                f"BBRsiAdx | {pair} | {direction} "
                f"entry filled @ {entry_price}, SL_ATR={sl_atr:.6f}, "
                f"SL_5%={sl_5:.6f}, TP={tp_10:.6f}"
            )

            try:
                self.dp.send_msg(
                    f"📊 *{pair}* {direction} nyitva\n"
                    f"Entry: `{entry_price:.4f}`\n"
                    f"🛑 SL ATR: `{sl_atr:.4f}`\n"
                    f"🛑 SL 5%: `{sl_5:.4f}`\n"
                    f"🎯 TP 10%: `{tp_10:.4f}`"
                )
            except Exception:
                pass

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
        if current_profit >= 0.10:
            logger.info(
                f"BBRsiAdx | {pair} | TP 10% hit @ {current_rate:.6f} "
                f"(profit={current_profit:.2%})"
            )
            return "tp_10pct"
        if current_profit <= -0.05:
            logger.info(
                f"BBRsiAdx | {pair} | SL 5% hit @ {current_rate:.6f} "
                f"(profit={current_profit:.2%})"
            )
            return "sl_5pct"
        return None
