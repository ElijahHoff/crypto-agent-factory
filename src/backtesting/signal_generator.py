"""
Signal Generator v0.4 — Multi-strategy signal generation.

Supports: momentum, mean_reversion, breakout, volatility, trend_following
Each produces genuinely different trading signals from OHLCV data.
"""

import numpy as np
import pandas as pd
from loguru import logger


class SignalGenerator:
    """Generate trading signals from OHLCV data based on strategy type."""

    STRATEGY_MAP = {
        "momentum": "_momentum_signals",
        "mean_reversion": "_mean_reversion_signals",
        "breakout": "_breakout_signals",
        "volatility": "_volatility_signals",
        "trend_following": "_trend_following_signals",
    }

    _FAMILY_KEYWORDS = {
        "mean_reversion": [
            "mean_reversion", "mean reversion", "reversion", "contrarian",
            "oversold", "overbought", "rsi", "bollinger", "z-score", "zscore",
            "liquidation", "dip", "fade",
        ],
        "breakout": [
            "breakout", "break_out", "range", "squeeze", "keltner",
            "donchian", "channel", "expansion", "compression",
        ],
        "volatility": [
            "volatility", "vol_", "vix", "garch", "atr", "straddle",
            "gamma", "implied_vol", "realised_vol", "vol_smile",
        ],
        "trend_following": [
            "trend", "trend_following", "moving_average", "ema_cross",
            "supertrend", "ichimoku", "macd", "adx",
        ],
        "momentum": [
            "momentum", "cross_sectional", "relative_strength",
            "funding_rate", "carry", "basis", "roc",
        ],
    }

    def classify_strategy(self, strategy_name: str, description: str = "") -> str:
        text = f"{strategy_name} {description}".lower()
        scores = {}
        for family, keywords in self._FAMILY_KEYWORDS.items():
            scores[family] = sum(1 for kw in keywords if kw in text)
        best = max(scores, key=scores.get)
        return best if scores[best] > 0 else "momentum"

    def generate(self, prices: pd.DataFrame, strategy_type: str = "momentum",
                 params: dict | None = None) -> pd.Series:
        params = params or {}
        method_name = self.STRATEGY_MAP.get(strategy_type, "_momentum_signals")
        method = getattr(self, method_name)
        logger.info(f"Generating signals: type={strategy_type}, generator={method_name}")
        signals = method(prices, params)
        n_long = (signals == 1).sum()
        n_short = (signals == -1).sum()
        n_flat = (signals == 0).sum()
        logger.info(f"Signals: {n_long} long, {n_short} short, {n_flat} flat bars")
        return signals

    # ────────────────────── MOMENTUM ──────────────────────
    def _momentum_signals(self, prices: pd.DataFrame, params: dict) -> pd.Series:
        fast = params.get("fast_period", 20)
        slow = params.get("slow_period", 50)
        roc_period = params.get("roc_period", 14)
        roc_threshold = params.get("roc_threshold", 0.0)
        close = prices["close"]
        sma_fast = close.rolling(fast).mean()
        sma_slow = close.rolling(slow).mean()
        roc = close.pct_change(roc_period)
        signals = pd.Series(0, index=prices.index)
        signals[(sma_fast > sma_slow) & (roc > roc_threshold)] = 1
        signals[(sma_fast < sma_slow) & (roc < -roc_threshold)] = -1
        return signals

    # ────────────────────── MEAN REVERSION ──────────────────────
    def _mean_reversion_signals(self, prices: pd.DataFrame, params: dict) -> pd.Series:
        lookback = params.get("lookback", 20)
        entry_z = params.get("entry_z", 2.0)
        exit_z = params.get("exit_z", 0.5)
        close = prices["close"]
        volume = prices["volume"]
        rolling_mean = close.rolling(lookback).mean()
        rolling_std = close.rolling(lookback).std()
        z_score = (close - rolling_mean) / rolling_std.replace(0, np.nan)
        vol_ma = volume.rolling(lookback).mean()
        vol_filter = volume > vol_ma * 0.8
        signals = pd.Series(0, index=prices.index)
        signals[(z_score < -entry_z) & vol_filter] = 1
        signals[(z_score > entry_z) & vol_filter] = -1
        signals[(z_score > -exit_z) & (z_score < exit_z)] = 0
        return self._apply_state_machine(signals, z_score, entry_z, exit_z)

    def _apply_state_machine(self, raw_signals, z_score, entry_z, exit_z):
        signals = pd.Series(0, index=raw_signals.index, dtype=int)
        position = 0
        for i in range(len(signals)):
            z = z_score.iloc[i]
            if np.isnan(z):
                signals.iloc[i] = 0
                continue
            if position == 0:
                if z < -entry_z:
                    position = 1
                elif z > entry_z:
                    position = -1
            elif position == 1:
                if z > -exit_z:
                    position = 0
            elif position == -1:
                if z < exit_z:
                    position = 0
            signals.iloc[i] = position
        return signals

    # ────────────────────── BREAKOUT ──────────────────────
    def _breakout_signals(self, prices: pd.DataFrame, params: dict) -> pd.Series:
        channel_period = params.get("channel_period", 20)
        atr_period = params.get("atr_period", 14)
        high, low, close = prices["high"], prices["low"], prices["close"]
        upper = high.rolling(channel_period).max()
        lower = low.rolling(channel_period).min()
        mid = (upper + lower) / 2
        tr = pd.concat([high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1).max(axis=1)
        atr = tr.rolling(atr_period).mean()
        atr_expanding = atr > atr.rolling(atr_period * 2).mean()
        signals = pd.Series(0, index=prices.index)
        signals[(close > upper.shift(1)) & atr_expanding] = 1
        signals[(close < lower.shift(1)) & atr_expanding] = -1
        return self._hold_until_mid(signals, close, mid)

    def _hold_until_mid(self, raw_signals, close, mid):
        signals = pd.Series(0, index=raw_signals.index, dtype=int)
        position = 0
        for i in range(len(signals)):
            raw = raw_signals.iloc[i]
            c, m = close.iloc[i], mid.iloc[i]
            if np.isnan(m):
                signals.iloc[i] = 0
                continue
            if raw != 0 and position == 0:
                position = raw
            elif position == 1 and c < m:
                position = 0
            elif position == -1 and c > m:
                position = 0
            signals.iloc[i] = position
        return signals

    # ────────────────────── VOLATILITY ──────────────────────
    def _volatility_signals(self, prices: pd.DataFrame, params: dict) -> pd.Series:
        short_w = params.get("short_vol_window", 10)
        long_w = params.get("long_vol_window", 30)
        squeeze_th = params.get("squeeze_threshold", 0.6)
        exp_mult = params.get("expansion_multiplier", 1.5)
        close = prices["close"]
        returns = close.pct_change()
        short_vol = returns.rolling(short_w).std() * np.sqrt(365 * 24)
        long_vol = returns.rolling(long_w).std() * np.sqrt(365 * 24)
        vol_ratio = short_vol / long_vol.replace(0, np.nan)
        in_squeeze = vol_ratio < squeeze_th
        expanding = vol_ratio > exp_mult
        sma_20 = close.rolling(20).mean()
        trend_up = close > sma_20
        trend_down = close < sma_20
        signals = pd.Series(0, index=prices.index)
        squeeze_ended = in_squeeze.shift(1) & ~in_squeeze
        signals[squeeze_ended & trend_up] = 1
        signals[squeeze_ended & trend_down] = -1
        signals[expanding & trend_up & ~in_squeeze] = 1
        signals[expanding & trend_down & ~in_squeeze] = -1
        return signals

    # ────────────────────── TREND FOLLOWING ──────────────────────
    def _trend_following_signals(self, prices: pd.DataFrame, params: dict) -> pd.Series:
        fast_ema = params.get("fast_ema", 12)
        mid_ema = params.get("mid_ema", 26)
        slow_ema = params.get("slow_ema", 50)
        adx_period = params.get("adx_period", 14)
        adx_threshold = params.get("adx_threshold", 25)
        close = prices["close"]
        high, low = prices["high"], prices["low"]
        ema_f = close.ewm(span=fast_ema).mean()
        ema_m = close.ewm(span=mid_ema).mean()
        ema_s = close.ewm(span=slow_ema).mean()
        adx = self._compute_adx(high, low, close, adx_period)
        strong = adx > adx_threshold
        signals = pd.Series(0, index=prices.index)
        signals[(ema_f > ema_m) & (ema_m > ema_s) & strong] = 1
        signals[(ema_f < ema_m) & (ema_m < ema_s) & strong] = -1
        return signals

    def _compute_adx(self, high, low, close, period):
        plus_dm = high.diff()
        minus_dm = -low.diff()
        plus_dm[plus_dm < 0] = 0
        minus_dm[minus_dm < 0] = 0
        plus_dm[(plus_dm < minus_dm)] = 0
        minus_dm[(minus_dm < plus_dm)] = 0
        tr = pd.concat([high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1).max(axis=1)
        atr = tr.ewm(span=period).mean()
        plus_di = 100 * (plus_dm.ewm(span=period).mean() / atr)
        minus_di = 100 * (minus_dm.ewm(span=period).mean() / atr)
        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
        adx = dx.ewm(span=period).mean()
        return adx.fillna(0)
