"""Signal Generator: converts formalized strategy rules into concrete trading signals on real data."""

from __future__ import annotations

import numpy as np
import pandas as pd
from loguru import logger


class SignalGenerator:
    """Generate trading signals from strategy type + parameters + OHLCV data."""

    def generate(
        self,
        prices: pd.DataFrame,
        strategy_type: str,
        parameters: dict,
    ) -> pd.Series:
        """Route to the appropriate signal generator based on strategy type."""
        generators = {
            "momentum": self._momentum_signals,
            "mean_reversion": self._mean_reversion_signals,
            "breakout": self._breakout_signals,
            "volatility_structure": self._breakout_signals,
            "funding_basis": self._momentum_signals,  # simplified: trend-follow on funding
            "cross_sectional": self._momentum_signals,
            "market_neutral": self._mean_reversion_signals,
            "statistical_arbitrage": self._mean_reversion_signals,
            "sentiment": self._momentum_signals,
            "regime_adaptive": self._regime_adaptive_signals,
        }

        gen_func = generators.get(strategy_type, self._momentum_signals)
        logger.info(f"Generating signals: type={strategy_type}, generator={gen_func.__name__}")

        signals = gen_func(prices, parameters)

        # Ensure no lookahead: shift signals by 1 bar
        signals = signals.shift(1).fillna(0)

        n_long = (signals > 0).sum()
        n_short = (signals < 0).sum()
        n_flat = (signals == 0).sum()
        logger.info(f"Signals: {n_long} long, {n_short} short, {n_flat} flat bars")

        return signals

    # ── Momentum / Trend Following ───────────────────────────────────────

    def _momentum_signals(self, prices: pd.DataFrame, params: dict) -> pd.Series:
        """
        Time-series momentum: go long when price is above moving average,
        short when below. Uses fast/slow MA crossover.
        """
        close = prices["close"]
        fast = params.get("fast_period", 20)
        slow = params.get("slow_period", 60)

        ma_fast = close.rolling(fast, min_periods=fast).mean()
        ma_slow = close.rolling(slow, min_periods=slow).mean()

        signals = pd.Series(0.0, index=prices.index)
        signals[ma_fast > ma_slow] = 1.0
        signals[ma_fast < ma_slow] = -1.0

        # Optional: require minimum trend strength
        min_spread = params.get("min_spread_pct", 0.0)
        if min_spread > 0:
            spread = (ma_fast - ma_slow) / ma_slow
            signals[spread.abs() < min_spread / 100] = 0.0

        return signals

    # ── Mean Reversion ───────────────────────────────────────────────────

    def _mean_reversion_signals(self, prices: pd.DataFrame, params: dict) -> pd.Series:
        """
        Mean reversion: go long when price is oversold (below lower band),
        short when overbought (above upper band). Uses z-score of returns.
        """
        close = prices["close"]
        lookback = params.get("lookback_period", 48)
        entry_z = params.get("entry_zscore", 2.0)
        exit_z = params.get("exit_zscore", 0.5)

        # Rolling z-score of price relative to its own moving average
        ma = close.rolling(lookback, min_periods=lookback).mean()
        std = close.rolling(lookback, min_periods=lookback).std()
        zscore = (close - ma) / std.replace(0, np.nan)
        zscore = zscore.fillna(0)

        signals = pd.Series(0.0, index=prices.index)

        # Stateful signal generation (need to track position)
        position = 0.0
        for i in range(len(zscore)):
            z = zscore.iloc[i]
            if position == 0:
                if z < -entry_z:
                    position = 1.0   # oversold → buy
                elif z > entry_z:
                    position = -1.0  # overbought → sell
            elif position == 1.0:
                if z > -exit_z:
                    position = 0.0   # z reverted → exit long
            elif position == -1.0:
                if z < exit_z:
                    position = 0.0   # z reverted → exit short
            signals.iloc[i] = position

        return signals

    # ── Breakout / Volatility Expansion ──────────────────────────────────

    def _breakout_signals(self, prices: pd.DataFrame, params: dict) -> pd.Series:
        """
        Volatility breakout: enter on Bollinger Band breakout after
        compression period. Direction follows the breakout.
        """
        close = prices["close"]
        lookback = params.get("compression_lookback", 48)
        bb_period = params.get("bb_period", 20)
        bb_std = params.get("bb_std", 2.0)
        compression_pct = params.get("compression_percentile", 20)

        # Bollinger Bands
        ma = close.rolling(bb_period, min_periods=bb_period).mean()
        std = close.rolling(bb_period, min_periods=bb_period).std()
        upper = ma + bb_std * std
        lower = ma - bb_std * std

        # Bandwidth (volatility measure)
        bandwidth = (upper - lower) / ma
        bandwidth = bandwidth.fillna(0)

        # Rolling percentile of bandwidth (compression detector)
        bw_pct = bandwidth.rolling(lookback, min_periods=lookback).apply(
            lambda x: pd.Series(x).rank(pct=True).iloc[-1], raw=False
        )
        bw_pct = bw_pct.fillna(0.5)

        # Volume confirmation
        vol = prices.get("volume", pd.Series(1, index=prices.index))
        vol_ma = vol.rolling(20, min_periods=1).mean()
        vol_ratio = vol / vol_ma.replace(0, 1)

        signals = pd.Series(0.0, index=prices.index)
        min_vol_ratio = params.get("vol_min_ratio", 1.3)

        # Breakout: compressed bandwidth + price outside bands + volume spike
        is_compressed = bw_pct < (compression_pct / 100)
        vol_confirm = vol_ratio > min_vol_ratio

        # Look for breakout after compression
        was_compressed = is_compressed.rolling(5, min_periods=1).max() > 0

        long_breakout = (close > upper) & was_compressed & vol_confirm
        short_breakout = (close < lower) & was_compressed & vol_confirm

        # Hold for N bars after breakout
        hold_bars = params.get("hold_bars", 12)
        position = 0.0
        bars_held = 0

        for i in range(len(close)):
            if position == 0:
                if long_breakout.iloc[i]:
                    position = 1.0
                    bars_held = 0
                elif short_breakout.iloc[i]:
                    position = -1.0
                    bars_held = 0
            else:
                bars_held += 1
                # Time-based exit
                if bars_held >= hold_bars:
                    position = 0.0
                # Stop loss: price reverts back inside bands
                elif position == 1.0 and close.iloc[i] < ma.iloc[i]:
                    position = 0.0
                elif position == -1.0 and close.iloc[i] > ma.iloc[i]:
                    position = 0.0

            signals.iloc[i] = position

        return signals

    # ── Regime Adaptive ──────────────────────────────────────────────────

    def _regime_adaptive_signals(self, prices: pd.DataFrame, params: dict) -> pd.Series:
        """
        Switches between momentum and mean-reversion based on detected regime.
        Uses ADX-like trend strength as regime indicator.
        """
        close = prices["close"]
        regime_lookback = params.get("regime_lookback", 48)
        trend_threshold = params.get("trend_threshold", 0.02)

        # Simple regime detection: trending vs ranging
        returns = close.pct_change(regime_lookback).fillna(0)
        volatility = close.pct_change().rolling(regime_lookback).std().fillna(0.01)
        trend_strength = returns.abs() / (volatility * np.sqrt(regime_lookback))
        trend_strength = trend_strength.fillna(0)

        # Trending regime → momentum signals
        mom_signals = self._momentum_signals(prices, params)
        # Ranging regime → mean reversion signals
        mr_signals = self._mean_reversion_signals(prices, params)

        is_trending = trend_strength > trend_threshold
        signals = pd.Series(0.0, index=prices.index)
        signals[is_trending] = mom_signals[is_trending]
        signals[~is_trending] = mr_signals[~is_trending]

        return signals


def extract_parameters(agent_output: dict) -> dict:
    """Extract usable signal parameters from agent formalization output."""
    params = {}

    # Try to get parameters from various agent output formats
    if isinstance(agent_output, dict):
        # Direct parameters
        if "parameters" in agent_output:
            raw = agent_output["parameters"]
            if isinstance(raw, dict):
                for k, v in raw.items():
                    # Handle "value with rationale" format
                    if isinstance(v, (int, float)):
                        params[k] = v
                    elif isinstance(v, str):
                        try:
                            params[k] = float(v.split()[0])
                        except (ValueError, IndexError):
                            pass
                    elif isinstance(v, dict) and "default" in v:
                        params[k] = v["default"]

        # Hyperparameters defaults
        if "hyperparameters" in agent_output:
            hyp = agent_output["hyperparameters"]
            if isinstance(hyp, dict):
                for k, v in hyp.items():
                    if k not in params and isinstance(v, dict) and "default" in v:
                        params[k] = v["default"]

    # Ensure minimum defaults for each strategy type
    defaults = {
        "fast_period": 20,
        "slow_period": 60,
        "lookback_period": 48,
        "entry_zscore": 2.0,
        "exit_zscore": 0.5,
        "compression_lookback": 48,
        "bb_period": 20,
        "bb_std": 2.0,
        "compression_percentile": 20,
        "hold_bars": 12,
        "vol_min_ratio": 1.3,
        "regime_lookback": 48,
        "trend_threshold": 0.02,
    }

    for k, v in defaults.items():
        if k not in params:
            params[k] = v

    return params


def detect_strategy_type(agent_output: dict) -> str:
    """Detect strategy type from hypothesis or formalization output."""
    if isinstance(agent_output, dict):
        # Check multiple possible locations
        for key in ["strategy_type", "type"]:
            if key in agent_output:
                return str(agent_output[key]).lower()

        # Check in nested hypothesis
        hypotheses = agent_output.get("hypotheses", [])
        if hypotheses and isinstance(hypotheses[0], dict):
            st = hypotheses[0].get("strategy_type", "")
            if st:
                return st.lower()

    return "momentum"  # safe default
