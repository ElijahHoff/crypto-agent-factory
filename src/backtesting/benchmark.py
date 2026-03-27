"""
Benchmark Calculator v0.4 — Buy-and-hold and risk-free benchmarks.

Computes benchmark returns to compare strategy performance against.
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from loguru import logger


@dataclass
class BenchmarkResult:
    """Benchmark performance metrics."""
    name: str
    total_return: float = 0.0
    cagr: float = 0.0
    sharpe: float = 0.0
    max_drawdown: float = 0.0
    volatility: float = 0.0
    equity_curve: list = field(default_factory=list)
    calmar: float = 0.0


def compute_benchmarks(prices: pd.DataFrame, periods_per_year: float = 8760) -> dict:
    """
    Compute benchmark results for comparison.

    Args:
        prices: OHLCV DataFrame
        periods_per_year: annualization factor (8760 for hourly crypto)

    Returns:
        dict of {name: BenchmarkResult}
    """
    benchmarks = {}

    # 1. Buy and Hold
    bh = _buy_and_hold(prices, periods_per_year)
    benchmarks["buy_and_hold"] = bh
    logger.info(
        f"Benchmark Buy&Hold: return={bh.total_return:.2%}, "
        f"Sharpe={bh.sharpe:.3f}, MaxDD={bh.max_drawdown:.2%}"
    )

    # 2. Inverse (short and hold)
    inv = _short_and_hold(prices, periods_per_year)
    benchmarks["short_and_hold"] = inv

    # 3. Risk-free proxy (0% — flat line)
    rf = BenchmarkResult(
        name="risk_free",
        total_return=0.0,
        cagr=0.0,
        sharpe=0.0,
        max_drawdown=0.0,
        volatility=0.0,
        equity_curve=[1.0] * len(prices),
        calmar=0.0,
    )
    benchmarks["risk_free"] = rf

    return benchmarks


def _buy_and_hold(prices: pd.DataFrame, periods_per_year: float) -> BenchmarkResult:
    """Simple buy-and-hold benchmark."""
    close = prices["close"].values
    returns = np.diff(close) / close[:-1]

    equity = np.cumprod(1 + returns)
    equity = np.insert(equity, 0, 1.0)

    total_return = equity[-1] / equity[0] - 1
    n_periods = len(returns)
    years = n_periods / periods_per_year
    cagr = (1 + total_return) ** (1 / max(years, 0.01)) - 1

    vol = np.std(returns) * np.sqrt(periods_per_year)
    sharpe = (np.mean(returns) * periods_per_year) / vol if vol > 0 else 0

    peak = np.maximum.accumulate(equity)
    dd = (equity - peak) / np.where(peak > 0, peak, 1)
    max_dd = np.min(dd)

    calmar = cagr / abs(max_dd) if abs(max_dd) > 0.001 else 0

    return BenchmarkResult(
        name="buy_and_hold",
        total_return=total_return,
        cagr=cagr,
        sharpe=sharpe,
        max_drawdown=max_dd,
        volatility=vol,
        equity_curve=equity.tolist(),
        calmar=calmar,
    )


def _short_and_hold(prices: pd.DataFrame, periods_per_year: float) -> BenchmarkResult:
    """Short-and-hold benchmark (inverse)."""
    close = prices["close"].values
    returns = -np.diff(close) / close[:-1]  # negated

    equity = np.cumprod(1 + returns)
    equity = np.insert(equity, 0, 1.0)

    total_return = equity[-1] / equity[0] - 1
    n_periods = len(returns)
    years = n_periods / periods_per_year
    cagr = (1 + total_return) ** (1 / max(years, 0.01)) - 1 if total_return > -1 else -1

    vol = np.std(returns) * np.sqrt(periods_per_year)
    sharpe = (np.mean(returns) * periods_per_year) / vol if vol > 0 else 0

    peak = np.maximum.accumulate(equity)
    dd = (equity - peak) / np.where(peak > 0, peak, 1)
    max_dd = np.min(dd)

    calmar = cagr / abs(max_dd) if abs(max_dd) > 0.001 else 0

    return BenchmarkResult(
        name="short_and_hold",
        total_return=total_return,
        cagr=cagr,
        sharpe=sharpe,
        max_drawdown=max_dd,
        volatility=vol,
        equity_curve=equity.tolist(),
        calmar=calmar,
    )
