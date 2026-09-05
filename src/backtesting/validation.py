"""
Statistical validation v1.0 — the "is this real?" toolkit.

Everything the factory was missing to separate signal from noise:

- Probabilistic / Deflated Sharpe Ratio (Bailey & López de Prado, 2014):
  corrects the observed Sharpe for the number of trials, non-normal returns
  and sample length. A strategy found after N trials must clear a much
  higher bar than one found after 1.
- Minimum track record length: how many bars you'd need for the observed
  Sharpe to be significant at a given confidence.
- Block-bootstrap confidence interval for the Sharpe ratio.
- Signal permutation test: reshuffles the *signal* in blocks (preserving
  its autocorrelation, exposure and turnover) and asks how often a random
  signal with the same structure does as well.
- Look-ahead (truncation) test for agent-generated code: if
  f(prices[:t]) != f(prices)[:t], the function is peeking at the future
  (explicit shift(-1) or implicit whole-sample normalisation).

All functions are pure and work on plain pandas/numpy objects so they can be
unit-tested on synthetic data without touching the exchange.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd
from scipy import stats

COST_PER_TRADE = 0.0017  # 17 bps, same as the rest of the factory


# ── Basic helpers ────────────────────────────────────────────────────────


def strategy_returns(
    prices: pd.DataFrame,
    signals: pd.Series,
    cost_per_trade: float = COST_PER_TRADE,
) -> pd.Series:
    """Net per-bar strategy returns with position held from the NEXT bar.

    A flip long->short costs two units (close + open), which the old
    ``(signals != signals.shift(1))`` counter under-charged.
    """
    returns = prices["close"].pct_change().fillna(0)
    position = signals.reindex(prices.index).fillna(0).shift(1).fillna(0)
    turnover = position.diff().abs().fillna(position.abs())
    return position * returns - turnover * cost_per_trade


def sharpe_ratio(returns: pd.Series | np.ndarray, periods_per_year: float = 8760) -> float:
    r = np.asarray(returns, dtype=float)
    r = r[~np.isnan(r)]
    if len(r) < 2 or r.std(ddof=1) == 0:
        return 0.0
    return float(r.mean() / r.std(ddof=1) * np.sqrt(periods_per_year))


# ── Probabilistic & Deflated Sharpe ──────────────────────────────────────


def probabilistic_sharpe_ratio(
    sharpe_obs: float,
    sharpe_benchmark: float,
    n_obs: int,
    skew: float = 0.0,
    kurt: float = 3.0,
) -> float:
    """PSR: P(true Sharpe > benchmark) given the observed, per-period Sharpe.

    ``sharpe_obs`` and ``sharpe_benchmark`` must be *per-period* (not
    annualised). ``kurt`` is the raw (non-excess) kurtosis.
    """
    if n_obs < 2:
        return 0.0
    denom = np.sqrt(max(1e-12, 1 - skew * sharpe_obs + (kurt - 1) / 4 * sharpe_obs**2))
    z = (sharpe_obs - sharpe_benchmark) * np.sqrt(n_obs - 1) / denom
    return float(stats.norm.cdf(z))


def expected_max_sharpe(n_trials: int, var_sharpe: float) -> float:
    """E[max Sharpe] of ``n_trials`` independent null strategies (per-period).

    Bailey & López de Prado approximation with the Euler–Mascheroni constant.
    """
    if n_trials <= 1:
        return 0.0
    gamma = 0.5772156649
    e = np.e
    return float(
        np.sqrt(var_sharpe)
        * ((1 - gamma) * stats.norm.ppf(1 - 1 / n_trials) + gamma * stats.norm.ppf(1 - 1 / (n_trials * e)))
    )


@dataclass
class DeflatedSharpeResult:
    sharpe_annual: float
    n_trials: int
    n_obs: int
    expected_max_sharpe_annual: float
    psr: float  # P(SR > 0)
    dsr: float  # P(SR > expected max under null)
    min_track_record_bars: float
    passed: bool
    note: str = ""


def deflated_sharpe_ratio(
    returns: pd.Series | np.ndarray,
    n_trials: int,
    periods_per_year: float = 8760,
    var_sharpe_trials: float | None = None,
    confidence: float = 0.95,
) -> DeflatedSharpeResult:
    """Deflated Sharpe Ratio for a strategy that was selected out of ``n_trials``.

    ``var_sharpe_trials`` is the variance of the (per-period) Sharpe ratios
    across the trials that were run. If unknown we assume the null variance
    ``1/n_obs`` (independent noise strategies), which is conservative-ish
    for correlated trials.
    """
    r = np.asarray(returns, dtype=float)
    r = r[~np.isnan(r)]
    n = len(r)
    if n < 10 or r.std(ddof=1) == 0:
        return DeflatedSharpeResult(0.0, n_trials, n, 0.0, 0.0, 0.0, float("inf"), False, "no variance")

    sr = r.mean() / r.std(ddof=1)
    skew = float(stats.skew(r))
    kurt = float(stats.kurtosis(r, fisher=False))
    var_trials = var_sharpe_trials if var_sharpe_trials is not None else 1.0 / n
    sr_max = expected_max_sharpe(max(1, n_trials), var_trials)

    psr = probabilistic_sharpe_ratio(sr, 0.0, n, skew, kurt)
    dsr = probabilistic_sharpe_ratio(sr, sr_max, n, skew, kurt)

    # Min track record length for SR > 0 at `confidence`
    z = stats.norm.ppf(confidence)
    if sr > 0:
        mtrl = 1 + (1 - skew * sr + (kurt - 1) / 4 * sr**2) * (z / sr) ** 2
    else:
        mtrl = float("inf")

    ann = np.sqrt(periods_per_year)
    return DeflatedSharpeResult(
        sharpe_annual=round(sr * ann, 3),
        n_trials=n_trials,
        n_obs=n,
        expected_max_sharpe_annual=round(sr_max * ann, 3),
        psr=round(psr, 4),
        dsr=round(dsr, 4),
        min_track_record_bars=round(mtrl, 0),
        passed=dsr >= confidence,
        note=(
            f"After {n_trials} trials a pure-noise search is expected to reach "
            f"Sharpe {sr_max * ann:+.2f}; observed {sr * ann:+.2f}. DSR={dsr:.2%}"
        ),
    )


# ── Bootstrap CI ─────────────────────────────────────────────────────────


def block_bootstrap_sharpe(
    returns: pd.Series | np.ndarray,
    n_boot: int = 500,
    block: int = 24,
    periods_per_year: float = 8760,
    seed: int = 42,
) -> dict:
    """Stationary block bootstrap CI for the annualised Sharpe ratio."""
    r = np.asarray(returns, dtype=float)
    r = r[~np.isnan(r)]
    n = len(r)
    if n < block * 4:
        return {"ci_low": 0.0, "ci_high": 0.0, "p_value": 1.0, "n_boot": 0}
    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(n / block))
    starts = rng.integers(0, n - block, size=(n_boot, n_blocks))
    offs = np.arange(block)
    sharpes = np.empty(n_boot)
    for i in range(n_boot):
        idx = (starts[i][:, None] + offs[None, :]).ravel()[:n]
        sharpes[i] = sharpe_ratio(r[idx], periods_per_year)
    return {
        "ci_low": round(float(np.percentile(sharpes, 2.5)), 3),
        "ci_high": round(float(np.percentile(sharpes, 97.5)), 3),
        "p_value": round(float((sharpes <= 0).mean()), 4),
        "n_boot": n_boot,
    }


# ── Permutation (signal shuffling) test ──────────────────────────────────


def signal_permutation_test(
    prices: pd.DataFrame,
    signals: pd.Series,
    n_perm: int = 200,
    block: int = 24,
    cost_per_trade: float = COST_PER_TRADE,
    periods_per_year: float = 8760,
    seed: int = 42,
) -> dict:
    """How often does a *random* signal with the same block structure beat ours?

    Blocks of the signal series are shuffled in time, which keeps the
    signal's exposure, holding-time distribution and roughly its turnover,
    but destroys any alignment with future returns. p-value = share of
    permutations with Sharpe >= observed.
    """
    sig = signals.reindex(prices.index).fillna(0).astype(float)
    obs = sharpe_ratio(strategy_returns(prices, sig, cost_per_trade), periods_per_year)
    n = len(sig)
    n_blocks = int(np.ceil(n / block))
    rng = np.random.default_rng(seed)
    vals = sig.values
    null = np.empty(n_perm)
    for i in range(n_perm):
        order = rng.permutation(n_blocks)
        idx = (order[:, None] * block + np.arange(block)[None, :]).ravel()
        idx = idx[idx < n]
        perm = pd.Series(vals[idx][:n], index=prices.index[: len(idx)]).reindex(prices.index).fillna(0)
        null[i] = sharpe_ratio(strategy_returns(prices, perm, cost_per_trade), periods_per_year)
    p = float((null >= obs).mean())
    return {
        "observed_sharpe": round(obs, 3),
        "null_mean": round(float(null.mean()), 3),
        "null_95pct": round(float(np.percentile(null, 95)), 3),
        "p_value": round(p, 4),
        "passed": p < 0.05,
        "n_perm": n_perm,
    }


# ── Look-ahead / truncation test ─────────────────────────────────────────


@dataclass
class LookaheadResult:
    passed: bool
    n_cuts: int
    max_mismatch_pct: float
    detail: str = ""
    mismatches: list = field(default_factory=list)


def lookahead_truncation_test(
    generate: Callable[[pd.DataFrame], pd.Series | None],
    prices: pd.DataFrame,
    n_cuts: int = 4,
    tail: int = 48,
    warmup: int = 1000,
    seed: int = 7,
) -> LookaheadResult:
    """Detect future leakage in a signal function.

    For random cut points t, the last ``tail`` signals of ``generate(prices[:t])``
    must equal ``generate(prices)[:t]``'s tail. Any mismatch means the signal
    at time t depended on data after t. Catches:
      * explicit ``.shift(-1)``, ``.iloc[i+1]``
      * whole-sample z-scores / min-max scaling / percentile ranks
      * centered rolling windows (``center=True``)
      * ``rolling(...).apply`` on reversed series, etc.
    """
    full = generate(prices)
    if full is None:
        return LookaheadResult(False, 0, 100.0, "function returned None on full data")
    full = full.reindex(prices.index).fillna(0)

    n = len(prices)
    if n < warmup + tail * 2:
        return LookaheadResult(True, 0, 0.0, "series too short for test")
    rng = np.random.default_rng(seed)
    cuts = sorted(rng.integers(warmup, n - 1, size=n_cuts).tolist())

    worst = 0.0
    mism = []
    for t in cuts:
        part = generate(prices.iloc[:t])
        if part is None:
            return LookaheadResult(False, n_cuts, 100.0, f"function failed on truncated data (t={t})")
        part = part.reindex(prices.index[:t]).fillna(0)
        a = part.iloc[-tail:].values
        b = full.iloc[t - tail : t].values
        pct = float((a != b).mean() * 100)
        worst = max(worst, pct)
        if pct > 0:
            mism.append({"cut": int(t), "mismatch_pct": round(pct, 1)})

    passed = worst == 0.0
    detail = "no dependence on future bars detected" if passed else (
        f"signals change when future bars are removed (max {worst:.0f}% of the last {tail} bars) — "
        f"future leakage or whole-sample normalisation"
    )
    return LookaheadResult(passed, n_cuts, round(worst, 1), detail, mism)


# ── Aggregate ────────────────────────────────────────────────────────────


def validate_holdout(
    prices_holdout: pd.DataFrame,
    signals_holdout: pd.Series,
    n_trials: int,
    periods_per_year: float = 8760,
    n_perm: int = 200,
    prices_dev: pd.DataFrame | None = None,
    signals_dev: pd.Series | None = None,
    n_prior_experiments: int = 0,
) -> dict:
    """Run the full statistical battery.

    Two different selection problems, two different corrections:

    * WITHIN-RUN: the LLM loop + sweep picked the best of ``n_trials`` on the
      development window. The dev Sharpe must therefore be *deflated* by
      ``n_trials`` (``dev_dsr``). A strategy whose dev Sharpe does not
      survive its own search is noise before we even look at the holdout.
    * HOLDOUT: evaluated once → the Probabilistic Sharpe Ratio
      (``holdout_psr``, P(SR > 0)) is the right test. BUT the same holdout
      period is reused by every experiment in the batch, so across the
      batch you are again taking a best-of-N: ``holdout_dsr_batch`` deflates
      by ``n_prior_experiments + 1``. This is why the leaderboard's top
      entry always looks better than it is.
    """
    rets = strategy_returns(prices_holdout, signals_holdout)
    ho_single = deflated_sharpe_ratio(rets, 1, periods_per_year)               # PSR
    ho_batch = deflated_sharpe_ratio(rets, max(1, n_prior_experiments + 1), periods_per_year)
    boot = block_bootstrap_sharpe(rets, periods_per_year=periods_per_year)
    perm = signal_permutation_test(prices_holdout, signals_holdout, n_perm=n_perm, periods_per_year=periods_per_year)

    dev = None
    if prices_dev is not None and signals_dev is not None:
        dev = deflated_sharpe_ratio(strategy_returns(prices_dev, signals_dev), max(1, n_trials), periods_per_year)

    dev_ok = dev.passed if dev is not None else True
    verdict = dev_ok and ho_single.psr >= 0.95 and perm["passed"]
    note = (
        (f"Dev: {dev.note}. " if dev is not None else "")
        + f"Holdout PSR={ho_single.psr:.2%}; deflated for {n_prior_experiments + 1} experiments sharing "
        f"this holdout: DSR={ho_batch.dsr:.2%}."
    )
    return {
        "holdout_sharpe": ho_single.sharpe_annual,
        "holdout_bars": ho_single.n_obs,
        "n_trials": n_trials,
        "dev_sharpe": dev.sharpe_annual if dev is not None else None,
        "dev_expected_max_sharpe_null": dev.expected_max_sharpe_annual if dev is not None else None,
        "dev_dsr": dev.dsr if dev is not None else None,
        "psr": ho_single.psr,
        "n_experiments_sharing_holdout": n_prior_experiments + 1,
        "holdout_dsr_batch": ho_batch.dsr,
        "dsr": ho_batch.dsr,   # backwards-compatible alias (batch-deflated)
        "min_track_record_bars": ho_single.min_track_record_bars,
        "bootstrap_ci": [boot["ci_low"], boot["ci_high"]],
        "bootstrap_p": boot["p_value"],
        "permutation_p": perm["p_value"],
        "permutation_null_95": perm["null_95pct"],
        "statistically_significant": bool(verdict),
        "note": note,
    }
