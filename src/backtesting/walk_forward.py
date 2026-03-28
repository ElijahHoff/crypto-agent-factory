"""
Walk-Forward Validator v0.5 — Uses run_backtest() with correct BacktestMetrics fields.

BacktestMetrics fields: sharpe, return_after_costs_pct, max_drawdown_pct,
                        total_trades, hit_rate, profit_factor, cagr_pct
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from loguru import logger


@dataclass
class SubperiodResult:
    period_num: int
    start_date: str
    end_date: str
    bars: int
    sharpe: float
    total_return: float
    max_drawdown: float
    total_trades: int
    win_rate: float
    profit_factor: float
    passed: bool


@dataclass
class WalkForwardResult:
    n_periods: int
    periods: list
    positive_periods: int
    negative_periods: int
    consistency_ratio: float
    avg_sharpe: float
    sharpe_std: float
    worst_period: dict
    best_period: dict
    summary_text: str


def run_walk_forward(prices, signals, backtest_engine, n_periods=8):
    n = len(prices)
    period_size = n // n_periods

    if period_size < 50:
        n_periods = max(n // 50, 2)
        period_size = n // n_periods

    periods = []
    sharpes = []

    for i in range(n_periods):
        start_idx = i * period_size
        end_idx = min((i + 1) * period_size, n)
        sub_prices = prices.iloc[start_idx:end_idx]
        sub_signals = signals.iloc[start_idx:end_idx]

        if len(sub_prices) < 20:
            continue

        try:
            bt = backtest_engine.run_backtest(sub_prices, sub_signals)
            # run_backtest returns dict with "in_sample" key containing BacktestMetrics
            m = bt.get("in_sample")
            if m is None:
                m = bt.get("metrics")

            sharpe = getattr(m, "sharpe", 0) if m else 0
            total_return = getattr(m, "return_after_costs_pct", 0) / 100 if m else 0
            max_dd = getattr(m, "max_drawdown_pct", 0) / 100 if m else 0
            trades = getattr(m, "total_trades", 0) if m else 0
            hit = getattr(m, "hit_rate", 0) if m else 0
            pf = getattr(m, "profit_factor", 0) if m else 0

            sp = SubperiodResult(
                period_num=i + 1,
                start_date=str(sub_prices.index[0])[:10],
                end_date=str(sub_prices.index[-1])[:10],
                bars=len(sub_prices),
                sharpe=round(sharpe, 3),
                total_return=round(total_return, 4),
                max_drawdown=round(max_dd, 4),
                total_trades=trades,
                win_rate=round(hit, 3),
                profit_factor=round(pf, 2),
                passed=sharpe > 0,
            )
            periods.append(sp)
            sharpes.append(sharpe)

        except Exception as e:
            logger.warning(f"Walk-forward period {i+1} failed: {e}")
            periods.append(SubperiodResult(
                period_num=i + 1,
                start_date=str(sub_prices.index[0])[:10],
                end_date=str(sub_prices.index[-1])[:10],
                bars=len(sub_prices),
                sharpe=0, total_return=0, max_drawdown=0,
                total_trades=0, win_rate=0, profit_factor=0, passed=False,
            ))
            sharpes.append(0)

    positive = sum(1 for s in sharpes if s > 0)
    negative = len(sharpes) - positive
    consistency = positive / max(len(sharpes), 1)
    avg_sharpe = float(np.mean(sharpes)) if sharpes else 0
    sharpe_std = float(np.std(sharpes)) if sharpes else 0

    worst = min(periods, key=lambda p: p.sharpe) if periods else None
    best = max(periods, key=lambda p: p.sharpe) if periods else None

    summary = "\n".join([
        f"Walk-Forward ({n_periods} periods):",
        f"  Consistency: {positive}/{len(sharpes)} positive ({consistency:.0%})",
        f"  Avg Sharpe: {avg_sharpe:.3f} ± {sharpe_std:.3f}",
        f"  Sharpes: [{', '.join(f'{s:.2f}' for s in sharpes)}]",
    ])

    logger.info(f"Walk-forward: {positive}/{len(sharpes)} positive, avg Sharpe={avg_sharpe:.3f}")

    return WalkForwardResult(
        n_periods=len(periods),
        periods=periods,
        positive_periods=positive,
        negative_periods=negative,
        consistency_ratio=consistency,
        avg_sharpe=avg_sharpe,
        sharpe_std=sharpe_std,
        worst_period=_to_dict(worst),
        best_period=_to_dict(best),
        summary_text=summary,
    )


def _to_dict(p):
    if p is None:
        return {}
    return {
        "period_num": p.period_num, "start_date": p.start_date,
        "end_date": p.end_date, "sharpe": p.sharpe,
        "total_return": p.total_return, "max_drawdown": p.max_drawdown,
        "total_trades": p.total_trades,
    }
