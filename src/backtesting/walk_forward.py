"""
Walk-Forward Validator v0.4 — Detailed subperiod analysis.

Splits data into N windows and runs backtest on each,
producing a table of per-period metrics for the report.
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from loguru import logger


@dataclass
class SubperiodResult:
    """Metrics for a single walk-forward subperiod."""
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
    passed: bool  # Sharpe > 0


@dataclass
class WalkForwardResult:
    """Full walk-forward analysis results."""
    n_periods: int
    periods: list  # list of SubperiodResult
    positive_periods: int
    negative_periods: int
    consistency_ratio: float  # % of periods with positive Sharpe
    avg_sharpe: float
    sharpe_std: float
    worst_period: dict
    best_period: dict
    summary_text: str  # human-readable for agents


def run_walk_forward(
    prices: pd.DataFrame,
    signals: pd.Series,
    backtest_engine,
    n_periods: int = 8,
) -> WalkForwardResult:
    """
    Run walk-forward validation across N subperiods.

    Args:
        prices: OHLCV DataFrame
        signals: trading signals Series
        backtest_engine: BacktestEngine instance
        n_periods: number of subperiods
    """
    n = len(prices)
    period_size = n // n_periods

    if period_size < 50:
        logger.warning(f"Walk-forward periods too small ({period_size} bars). Using 4 periods.")
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
            # Run backtest on subperiod
            sub_bt = backtest_engine.run_backtest(sub_prices, sub_signals)
            sub_m = sub_bt.get("in_sample") or sub_bt.get("metrics")

            sp = SubperiodResult(
                period_num=i + 1,
                start_date=str(sub_prices.index[0])[:10],
                end_date=str(sub_prices.index[-1])[:10],
                bars=len(sub_prices),
                sharpe=round(getattr(sub_m, 'sharpe', 0), 3),
                total_return=round(getattr(sub_m, 'return_after_costs_pct', 0) / 100, 4),
                max_drawdown=round(getattr(sub_m, 'max_drawdown_pct', 0) / 100, 4),
                total_trades=getattr(sub_m, 'total_trades', 0),
                win_rate=round(getattr(sub_m, 'hit_rate', 0), 3),
                profit_factor=round(getattr(sub_m, 'profit_factor', 0), 2),
                passed=getattr(sub_m, 'sharpe', 0) > 0,
            )
            periods.append(sp)
            sharpes.append(sp.sharpe)

        except Exception as e:
            logger.warning(f"Walk-forward period {i+1} failed: {e}")
            periods.append(SubperiodResult(
                period_num=i + 1,
                start_date=str(sub_prices.index[0])[:10],
                end_date=str(sub_prices.index[-1])[:10],
                bars=len(sub_prices),
                sharpe=0.0, total_return=0.0, max_drawdown=0.0,
                total_trades=0, win_rate=0.0, profit_factor=0.0,
                passed=False,
            ))
            sharpes.append(0.0)

    # Aggregate
    positive = sum(1 for s in sharpes if s > 0)
    negative = len(sharpes) - positive
    consistency = positive / max(len(sharpes), 1)
    avg_sharpe = float(np.mean(sharpes)) if sharpes else 0
    sharpe_std = float(np.std(sharpes)) if sharpes else 0

    worst = min(periods, key=lambda p: p.sharpe) if periods else None
    best = max(periods, key=lambda p: p.sharpe) if periods else None

    worst_dict = _period_to_dict(worst) if worst else {}
    best_dict = _period_to_dict(best) if best else {}

    # Build text summary for agents
    summary_lines = [
        f"Walk-Forward Analysis ({n_periods} periods):",
        f"  Consistency: {positive}/{len(sharpes)} periods positive ({consistency:.0%})",
        f"  Avg Sharpe: {avg_sharpe:.3f} ± {sharpe_std:.3f}",
        f"  Best period: #{best.period_num} Sharpe={best.sharpe:.3f} ({best.start_date}→{best.end_date})" if best else "  No best period",
        f"  Worst period: #{worst.period_num} Sharpe={worst.sharpe:.3f} ({worst.start_date}→{worst.end_date})" if worst else "  No worst period",
        f"  Per-period Sharpes: [{', '.join(f'{s:.2f}' for s in sharpes)}]",
    ]
    summary_text = "\n".join(summary_lines)

    logger.info(f"Walk-forward: {positive}/{len(sharpes)} positive, avg Sharpe={avg_sharpe:.3f}")

    return WalkForwardResult(
        n_periods=len(periods),
        periods=periods,
        positive_periods=positive,
        negative_periods=negative,
        consistency_ratio=consistency,
        avg_sharpe=avg_sharpe,
        sharpe_std=sharpe_std,
        worst_period=worst_dict,
        best_period=best_dict,
        summary_text=summary_text,
    )


def _period_to_dict(p: SubperiodResult) -> dict:
    if p is None:
        return {}
    return {
        "period_num": p.period_num,
        "start_date": p.start_date,
        "end_date": p.end_date,
        "sharpe": p.sharpe,
        "total_return": p.total_return,
        "max_drawdown": p.max_drawdown,
        "total_trades": p.total_trades,
    }
