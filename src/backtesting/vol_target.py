"""
Volatility targeting & ensemble overlays v1.0.

Two things every systematic desk does that the factory did not:

1. VOLATILITY TARGETING. A {-1, 0, +1} signal bets the same notional in a
   20%-vol regime and an 120%-vol regime. Scaling the position by
   ``target_vol / realised_vol`` (Moreira & Muir 2017; Harvey et al. 2018)
   equalises risk over time, cuts drawdowns in vol spikes and — because
   crypto vol is negatively correlated with returns — usually raises the
   Sharpe of trend strategies. Realised vol is computed from PAST bars only
   and lagged by one bar so it is known when the position is set.

2. SIGNAL ENSEMBLE. Averaging several weak, low-correlated signals is the
   most reliable way to get a robust one (the "1/N" result). This takes a
   dict of signal series, drops those with pairwise correlation above a cap,
   and returns the equal-weight (or vote-thresholded) combination.

Both return fractional positions; ``BacktestEngine`` already multiplies
returns by the position, so it handles them unchanged.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def vol_target_positions(
    prices: pd.DataFrame,
    signals: pd.Series,
    target_vol_annual: float = 0.30,
    lookback: int = 72,
    max_leverage: float = 2.0,
    periods_per_year: float = 8760,
) -> pd.Series:
    """Scale a directional signal to a constant annualised volatility target."""
    ret = prices["close"].pct_change()
    realised = ret.rolling(lookback, min_periods=lookback // 2).std() * np.sqrt(periods_per_year)
    realised = realised.shift(1)  # known at bar close, applied to next position
    scale = (target_vol_annual / realised).clip(upper=max_leverage).fillna(0)
    return (signals.reindex(prices.index).fillna(0) * scale).astype(float)


def ensemble_signals(
    signal_dict: dict[str, pd.Series],
    index: pd.DatetimeIndex,
    max_pairwise_corr: float = 0.7,
    vote_threshold: float | None = None,
) -> tuple[pd.Series, dict]:
    """Equal-weight ensemble of signals after removing near-duplicates.

    ``vote_threshold``: if set (e.g. 0.5), output is +1/-1 only when the
    mean signal exceeds it in absolute value, else 0. Otherwise the raw mean
    in [-1, 1] is returned (fractional position).
    """
    if not signal_dict:
        return pd.Series(0.0, index=index), {"kept": [], "dropped": []}

    df = pd.DataFrame({k: v.reindex(index).fillna(0).astype(float) for k, v in signal_dict.items()})
    df = df.loc[:, df.std() > 0]
    kept, dropped = [], []
    for col in df.columns:
        if any(abs(df[col].corr(df[k])) > max_pairwise_corr for k in kept):
            dropped.append(col)
        else:
            kept.append(col)

    if not kept:
        return pd.Series(0.0, index=index), {"kept": [], "dropped": dropped}

    mean = df[kept].mean(axis=1)
    if vote_threshold is not None:
        out = pd.Series(0, index=index)
        out[mean > vote_threshold] = 1
        out[mean < -vote_threshold] = -1
        return out.astype(int), {"kept": kept, "dropped": dropped}
    return mean, {"kept": kept, "dropped": dropped}
