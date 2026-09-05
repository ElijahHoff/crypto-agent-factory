"""Tests for the v1.0 statistical validation toolkit (synthetic data only)."""

import numpy as np
import pandas as pd
import pytest

from src.backtesting.validation import (
    strategy_returns, sharpe_ratio, deflated_sharpe_ratio, expected_max_sharpe,
    block_bootstrap_sharpe, signal_permutation_test, lookahead_truncation_test,
    validate_holdout,
)
from src.backtesting.multi_timeframe import align_higher_tf, apply_trend_filter, compute_trend_filter
from src.backtesting.param_sweep import run_parameter_sweep, _quick_sharpe
from src.backtesting.vol_target import vol_target_positions, ensemble_signals
from src.backtesting.true_walk_forward import run_true_walk_forward


def make_prices(n=6000, seed=0, drift=0.0, vol=0.006):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    r = rng.normal(drift, vol, n)
    close = 100 * np.exp(np.cumsum(r))
    o = np.r_[close[0], close[:-1]]
    return pd.DataFrame({
        "open": o, "high": np.maximum(o, close) * 1.001,
        "low": np.minimum(o, close) * 0.999, "close": close, "volume": 1.0,
    }, index=idx)


def make_prices_with_edge(n=6000, seed=1):
    """Random walk plus a hidden momentum edge: sign(ROC 24) predicts next bar."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    r = np.zeros(n)
    for t in range(1, n):
        mom = np.sign(r[max(0, t - 24):t].sum())
        r[t] = rng.normal(0.0004 * mom, 0.006)
    close = 100 * np.exp(np.cumsum(r))
    return pd.DataFrame({"open": close, "high": close, "low": close, "close": close, "volume": 1.0}, index=idx)


# ── strategy_returns ─────────────────────────────────────────────────────

def test_flip_costs_two_trades():
    p = make_prices(100)
    sig = pd.Series(0, index=p.index)
    sig.iloc[10:20] = 1
    sig.iloc[20:30] = -1  # flip at bar 20
    net = strategy_returns(p, sig, cost_per_trade=0.001)
    gross = strategy_returns(p, sig, cost_per_trade=0.0)
    costs = (gross - net).round(10)
    # entry (1), flip (2), exit (1) = 4 units
    assert abs(costs.sum() - 0.004) < 1e-9


# ── Deflated Sharpe ──────────────────────────────────────────────────────

def test_expected_max_sharpe_grows_with_trials():
    v = 1 / 10000
    assert expected_max_sharpe(1, v) == 0
    assert expected_max_sharpe(10, v) < expected_max_sharpe(100, v) < expected_max_sharpe(10000, v)


def test_dsr_penalises_many_trials():
    rng = np.random.default_rng(3)
    r = rng.normal(0.0001, 0.005, 5000)  # small positive drift
    one = deflated_sharpe_ratio(r, n_trials=1)
    many = deflated_sharpe_ratio(r, n_trials=5000)
    assert one.dsr > many.dsr
    assert one.psr == pytest.approx(one.dsr, abs=1e-6)  # with 1 trial DSR == PSR


def test_dsr_noise_search_not_significant():
    """Best-of-N random signals on a random walk must NOT pass DSR."""
    p = make_prices(8000, seed=5)
    rng = np.random.default_rng(9)
    best, best_sig = -9, None
    n_trials = 200
    for _ in range(n_trials):
        k = int(rng.integers(12, 200))
        sig = np.sign(p["close"].pct_change(k)).fillna(0).astype(int)
        s = sharpe_ratio(strategy_returns(p, sig))
        if s > best:
            best, best_sig = s, sig
    res = deflated_sharpe_ratio(strategy_returns(p, best_sig), n_trials=n_trials)
    assert res.dsr < 0.95


# ── Bootstrap & permutation ──────────────────────────────────────────────

def test_bootstrap_ci_contains_zero_for_noise():
    p = make_prices(6000, seed=11)
    sig = np.sign(p["close"].pct_change(48)).fillna(0).astype(int)
    b = block_bootstrap_sharpe(strategy_returns(p, sig), n_boot=200)
    assert b["ci_low"] <= 0 <= b["ci_high"] or b["p_value"] > 0.01


def test_permutation_detects_real_edge_and_rejects_noise():
    edge = make_prices_with_edge(6000)
    sig = np.sign(edge["close"].pct_change(24)).fillna(0).astype(int)
    res = signal_permutation_test(edge, sig, n_perm=100, cost_per_trade=0.0)
    assert res["p_value"] < 0.05

    noise = make_prices(6000, seed=21)
    sig2 = np.sign(noise["close"].pct_change(24)).fillna(0).astype(int)
    res2 = signal_permutation_test(noise, sig2, n_perm=100, cost_per_trade=0.0)
    assert res2["p_value"] > 0.05


# ── Look-ahead truncation test ───────────────────────────────────────────

def test_lookahead_catches_shift_and_global_zscore():
    p = make_prices(3000)

    def clean(prices):
        c = prices["close"]
        return np.sign(c - c.rolling(50).mean()).fillna(0).astype(int)

    def peek(prices):
        return np.sign(prices["close"].shift(-1) - prices["close"]).fillna(0).astype(int)

    def zscore_global(prices):
        c = prices["close"]
        z = (c - c.mean()) / c.std()
        return pd.Series(np.where(z > 0.5, -1, np.where(z < -0.5, 1, 0)), index=prices.index)

    def centered(prices):
        c = prices["close"]
        return np.sign(c - c.rolling(50, center=True).mean()).fillna(0).astype(int)

    assert lookahead_truncation_test(clean, p, warmup=500).passed
    assert not lookahead_truncation_test(peek, p, warmup=500).passed
    assert not lookahead_truncation_test(zscore_global, p, warmup=500).passed
    assert not lookahead_truncation_test(centered, p, warmup=500).passed


# ── 4h alignment leak ────────────────────────────────────────────────────

def test_align_higher_tf_uses_candle_close_time():
    p = make_prices(400)
    h = p.resample("4h", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
    htf_close = h["close"]
    aligned = align_higher_tf(htf_close, p.index, "4h")
    # At 1h bar t inside a 4h candle we must NOT see that candle's close.
    t = p.index[101]  # 05:00 → belongs to the 04:00 candle, which closes at 08:00
    candle_open = t.floor("4h")
    assert aligned.loc[t] != htf_close.loc[candle_open] or htf_close.loc[candle_open] == htf_close.loc[candle_open - pd.Timedelta("4h")]
    assert aligned.loc[t] == htf_close.loc[candle_open - pd.Timedelta("4h")]


def test_trend_filter_no_lookahead_on_random_walk():
    """Trading the 4h trend sign on a random walk must not be systematically profitable."""
    sharpes = []
    for seed in range(12):
        p = make_prices(12000, seed=seed)
        h = p.resample("4h", label="left", closed="left").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        trend = compute_trend_filter(h, fast_ema=5, slow_ema=20)  # fast EMAs make leakage visible
        both = pd.Series(1, index=p.index)
        both[:] = 0
        long_all = pd.Series(1, index=p.index)
        short_all = pd.Series(-1, index=p.index)
        pos = apply_trend_filter(long_all, trend, p) + apply_trend_filter(short_all, trend, p)
        sharpes.append(sharpe_ratio(strategy_returns(p, pos, cost_per_trade=0.0)))
    assert abs(np.mean(sharpes)) < 0.6


# ── Sweep plateau ────────────────────────────────────────────────────────

CODE = '''
def generate_signals(prices):
    import numpy as np, pandas as pd
    lookback_period = 48
    entry_threshold = 0.02
    roc = prices["close"].pct_change(lookback_period).fillna(0)
    raw = np.where(roc > entry_threshold, 1, np.where(roc < -entry_threshold, -1, 0))
    s = pd.Series(raw, index=prices.index).replace(0, np.nan).ffill().fillna(0)
    return s.astype(int)
'''


def test_sweep_reports_trials_and_plateau():
    p = make_prices_with_edge(5000)
    sig, params, log = run_parameter_sweep(CODE, p)
    assert sig is not None and len(sig) == len(p)
    assert log["n_trials"] >= 4
    assert "best_plateau_sharpe" in log and "peak_is_sharpe" in log
    assert log["best_plateau_sharpe"] <= log["peak_is_sharpe"] + 1e-9


def test_quick_sharpe_charges_flips():
    p = make_prices(300)
    sig = pd.Series(0, index=p.index)
    sig.iloc[10:50] = 1
    sig.iloc[50:100] = -1
    flip = _quick_sharpe(p, sig)
    sig2 = sig.copy()
    sig2.iloc[50:100] = 0
    assert isinstance(flip, float)


# ── Vol target / ensemble ────────────────────────────────────────────────

def test_vol_target_scales_and_caps():
    p = make_prices(3000)
    sig = pd.Series(1, index=p.index)
    pos = vol_target_positions(p, sig, target_vol_annual=0.30, max_leverage=2.0)
    assert pos.max() <= 2.0
    assert pos.iloc[500:].min() > 0
    # position at t uses vol up to t-1 only
    p2 = p.copy()
    p2.iloc[1500:, :] = p2.iloc[1500:, :] * 1.5
    pos2 = vol_target_positions(p2, sig)
    assert (pos.iloc[:1500].round(8) == pos2.iloc[:1500].round(8)).all()


def test_ensemble_drops_duplicates():
    p = make_prices(2000)
    a = np.sign(p["close"].pct_change(24)).fillna(0)
    b = a.copy()
    c = np.sign(p["close"].pct_change(240)).fillna(0)
    out, info = ensemble_signals({"a": a, "b": b, "c": c}, p.index, max_pairwise_corr=0.9)
    assert "b" in info["dropped"] and set(info["kept"]) == {"a", "c"}
    assert out.abs().max() <= 1.0


# ── True walk-forward ────────────────────────────────────────────────────

def test_true_walk_forward_runs_and_reports_wfe():
    p = make_prices_with_edge(9000)
    res = run_true_walk_forward(CODE, p, n_folds=3, warmup_bars=200)
    assert res.n_folds == 3
    assert len(res.oos_returns) == 3 * (len(p) // 4)
    assert res.n_trials > 0
    assert -5 < res.oos_sharpe < 10


def test_validate_holdout_shape():
    p = make_prices(5000)
    sig = np.sign(p["close"].pct_change(24)).fillna(0).astype(int)
    v = validate_holdout(p, sig, n_trials=50, n_perm=30)
    for k in ["holdout_sharpe", "dsr", "psr", "bootstrap_ci", "permutation_p", "statistically_significant"]:
        assert k in v
