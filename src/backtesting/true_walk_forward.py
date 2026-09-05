"""
True Walk-Forward v1.0 — re-optimise, then trade forward.

``walk_forward.py`` slices ONE fixed signal series into 8 chunks and reports
the Sharpe of each chunk. That is sub-period analysis, not walk-forward:
the parameters were chosen with knowledge of every chunk.

This module does the real thing (Pardo 2008):

    [ train_0 ][ test_0 ]
              [ train_1 ][ test_1 ]
                        [ train_2 ][ test_2 ] ...

For every fold the parameter sweep runs on ``train_k`` only, the chosen
parameters are frozen and applied to ``test_k``. Concatenating the test
segments gives an out-of-sample equity curve whose Sharpe is what you
should expect going forward (minus the residual selection bias of choosing
the *strategy family*, which the deflated Sharpe handles).

Walk-forward efficiency (WFE) = OOS Sharpe / IS Sharpe. Pardo's rule of
thumb: WFE < 0.5 means the optimisation is mostly fitting noise.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from loguru import logger

from src.backtesting.param_sweep import run_parameter_sweep, _inject_params, _extract_params
from src.backtesting.signal_sandbox import SignalSandbox
from src.backtesting.validation import strategy_returns, sharpe_ratio


@dataclass
class WFFold:
    fold: int
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    params: dict
    is_sharpe: float
    oos_sharpe: float
    oos_return: float
    oos_trades: int


@dataclass
class TrueWalkForwardResult:
    folds: list[WFFold] = field(default_factory=list)
    oos_sharpe: float = 0.0            # Sharpe of concatenated OOS returns
    mean_is_sharpe: float = 0.0
    wf_efficiency: float = 0.0         # oos / is
    positive_folds: int = 0
    n_folds: int = 0
    n_trials: int = 0                  # total sweep evaluations across folds
    oos_returns: pd.Series | None = None
    param_stability: float = 0.0       # share of folds where params == modal params
    summary: str = ""


def run_true_walk_forward(
    code: str,
    prices: pd.DataFrame,
    n_folds: int = 4,
    train_frac: float = 0.6,
    anchored: bool = False,
    warmup_bars: int = 500,
) -> TrueWalkForwardResult:
    """Rolling (or anchored) walk-forward with per-fold parameter re-selection.

    ``train_frac`` is the share of each fold's window used for training.
    ``warmup_bars`` of history are prepended to each test segment so
    rolling indicators are warm at the first test bar; the warm-up bars'
    returns are discarded.
    """
    n = len(prices)
    if not code or n < 2000:
        return TrueWalkForwardResult(summary="not enough data or no code")

    sandbox = SignalSandbox()
    param_ranges = _extract_params(code)

    test_len = n // (n_folds + 1)
    train_len = int(test_len * train_frac / (1 - train_frac))
    if train_len + test_len > n:
        train_len = n - test_len * n_folds

    folds: list[WFFold] = []
    oos_pieces = []
    n_trials = 0

    for k in range(n_folds):
        test_start = n - (n_folds - k) * test_len
        test_end = test_start + test_len
        train_start = 0 if anchored else max(0, test_start - train_len)
        train = prices.iloc[train_start:test_start]
        test_with_warm = prices.iloc[max(0, test_start - warmup_bars):test_end]

        if len(train) < 500:
            continue

        # Re-select parameters on this fold's training window
        if param_ranges:
            _, params, sweep_log = run_parameter_sweep(code, train, param_ranges=param_ranges)
            n_trials += int(sweep_log.get("n_trials", 0))
            fold_code = _inject_params(code, params) if params else code
        else:
            params, fold_code = {}, code

        sig_train = sandbox.execute(fold_code, train)
        sig_test = sandbox.execute(fold_code, test_with_warm)
        if sig_train is None or sig_test is None:
            logger.warning(f"WF fold {k}: code failed")
            continue

        is_sharpe = sharpe_ratio(strategy_returns(train, sig_train))
        rets_test = strategy_returns(test_with_warm, sig_test).iloc[-test_len:]
        oos_sharpe = sharpe_ratio(rets_test)
        pos = sig_test.shift(1).fillna(0).iloc[-test_len:]
        n_tr = int(np.ceil(pos.diff().abs().fillna(0).sum() / 2))

        folds.append(WFFold(
            fold=k,
            train_start=str(train.index[0])[:10], train_end=str(train.index[-1])[:10],
            test_start=str(prices.index[test_start])[:10], test_end=str(prices.index[test_end - 1])[:10],
            params={kk: float(v) for kk, v in params.items()},
            is_sharpe=round(is_sharpe, 3), oos_sharpe=round(oos_sharpe, 3),
            oos_return=round(float((1 + rets_test).prod() - 1), 4), oos_trades=n_tr,
        ))
        oos_pieces.append(rets_test)
        logger.info(f"WF fold {k}: IS={is_sharpe:+.2f} OOS={oos_sharpe:+.2f} trades={n_tr} params={params}")

    if not folds:
        return TrueWalkForwardResult(summary="all folds failed")

    oos = pd.concat(oos_pieces)
    oos_sharpe = sharpe_ratio(oos)
    mean_is = float(np.mean([f.is_sharpe for f in folds]))
    wfe = oos_sharpe / mean_is if mean_is > 0.05 else 0.0

    # Parameter stability: how often did the sweep pick the same combo?
    keys = [tuple(sorted(f.params.items())) for f in folds]
    modal = max(set(keys), key=keys.count) if keys else ()
    stability = keys.count(modal) / len(keys) if keys else 0.0

    res = TrueWalkForwardResult(
        folds=folds, oos_sharpe=round(oos_sharpe, 3), mean_is_sharpe=round(mean_is, 3),
        wf_efficiency=round(wfe, 3), positive_folds=sum(f.oos_sharpe > 0 for f in folds),
        n_folds=len(folds), n_trials=n_trials, oos_returns=oos,
        param_stability=round(stability, 2),
    )
    res.summary = (
        f"True walk-forward ({len(folds)} folds, {'anchored' if anchored else 'rolling'}): "
        f"OOS Sharpe={oos_sharpe:+.2f}, mean IS={mean_is:+.2f}, WFE={wfe:.2f}, "
        f"{res.positive_folds}/{len(folds)} folds positive, param stability={stability:.0%}"
    )
    logger.info(res.summary)
    return res


def to_dict(r: TrueWalkForwardResult) -> dict:
    return {
        "oos_sharpe": r.oos_sharpe, "mean_is_sharpe": r.mean_is_sharpe,
        "wf_efficiency": r.wf_efficiency, "positive_folds": r.positive_folds,
        "n_folds": r.n_folds, "n_trials": r.n_trials, "param_stability": r.param_stability,
        "folds": [f.__dict__ for f in r.folds], "summary": r.summary,
    }
