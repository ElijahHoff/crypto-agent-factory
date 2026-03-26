"""Backtesting engine: realistic simulation with cost modeling and walk-forward support."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from loguru import logger

from src.config import settings
from src.models import BacktestDesign, BacktestMetrics


@dataclass
class CostModel:
    """Realistic transaction cost model for crypto."""

    commission_bps: float = 10.0   # maker/taker avg
    slippage_bps: float = 5.0     # market impact
    spread_bps: float = 2.0       # half-spread
    funding_bps: float = 1.0      # per 8h funding interval
    latency_ms: float = 100.0     # signal-to-fill delay

    @property
    def total_entry_cost_bps(self) -> float:
        return self.commission_bps + self.slippage_bps + self.spread_bps

    @property
    def total_round_trip_bps(self) -> float:
        return 2 * self.total_entry_cost_bps


@dataclass
class Trade:
    """Record of a single completed trade."""

    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    symbol: str
    side: str  # "long" | "short"
    entry_price: float
    exit_price: float
    size: float
    pnl_gross: float = 0.0
    pnl_net: float = 0.0
    fees: float = 0.0
    slippage: float = 0.0
    funding_paid: float = 0.0
    holding_bars: int = 0


@dataclass
class BacktestEngine:
    """Core backtest engine with walk-forward and cost modeling."""

    cost_model: CostModel = field(default_factory=CostModel)
    initial_capital: float = 100_000.0

    def run_backtest(
        self,
        prices: pd.DataFrame,
        signals: pd.Series,
        design: BacktestDesign | None = None,
    ) -> dict[str, Any]:
        """
        Run a vectorized backtest.

        Args:
            prices: DataFrame with 'close' column (and optionally 'high', 'low', 'volume').
            signals: Series of position signals (-1, 0, +1) aligned with prices index.
            design: Optional backtest design for split configuration.

        Returns:
            Dictionary with metrics, equity curve, and trade list.
        """
        if design is None:
            design = BacktestDesign()

        # Align
        signals = signals.reindex(prices.index).fillna(0)
        close = prices["close"]

        # ── Compute returns ──────────────────────────────────────────
        raw_returns = close.pct_change().fillna(0)
        position = signals.shift(1).fillna(0)  # Execute on NEXT bar (no lookahead)

        # Gross strategy returns
        strategy_returns_gross = position * raw_returns

        # ── Cost calculation ─────────────────────────────────────────
        trades_mask = position.diff().abs().fillna(0)  # 1 on trade bars
        cost_per_trade = self.cost_model.total_entry_cost_bps / 10_000
        costs = trades_mask * cost_per_trade

        # Funding cost for positions held (approximate: per-bar cost)
        bars_per_8h = max(1, 8 * 60 // self._estimate_bar_minutes(prices.index))
        funding_per_bar = (self.cost_model.funding_bps / 10_000) / bars_per_8h
        funding_costs = position.abs() * funding_per_bar

        # Net returns
        strategy_returns_net = strategy_returns_gross - costs - funding_costs

        # ── Equity curve ─────────────────────────────────────────────
        equity_gross = (1 + strategy_returns_gross).cumprod() * self.initial_capital
        equity_net = (1 + strategy_returns_net).cumprod() * self.initial_capital

        # ── Trade extraction ─────────────────────────────────────────
        trades = self._extract_trades(close, position, signals)

        # ── Compute metrics ──────────────────────────────────────────
        metrics_is = self._compute_metrics(strategy_returns_net, equity_net, trades, "in_sample")

        # ── Split analysis ───────────────────────────────────────────
        n = len(strategy_returns_net)
        train_end = int(n * design.train_pct)
        val_end = int(n * (design.train_pct + design.validation_pct))

        metrics_val = self._compute_metrics(
            strategy_returns_net.iloc[train_end:val_end],
            equity_net.iloc[train_end:val_end],
            [t for t in trades if t.entry_time >= prices.index[train_end] and t.exit_time < prices.index[min(val_end, n - 1)]],
            "validation",
        )
        metrics_oos = self._compute_metrics(
            strategy_returns_net.iloc[val_end:],
            equity_net.iloc[val_end:],
            [t for t in trades if t.entry_time >= prices.index[min(val_end, n - 1)]],
            "out_of_sample",
        )

        # ── Walk-forward ─────────────────────────────────────────────
        wf_metrics = self._walk_forward(strategy_returns_net, equity_net, trades, prices.index, design)

        return {
            "in_sample": metrics_is,
            "validation": metrics_val,
            "out_of_sample": metrics_oos,
            "walk_forward": wf_metrics,
            "equity_gross": equity_gross,
            "equity_net": equity_net,
            "trades": trades,
            "total_costs_pct": float(costs.sum() + funding_costs.sum()) * 100,
        }

    # ── Metrics ──────────────────────────────────────────────────────────

    def _compute_metrics(
        self,
        returns: pd.Series,
        equity: pd.Series,
        trades: list[Trade],
        label: str,
    ) -> BacktestMetrics:
        """Compute comprehensive performance metrics."""
        if len(returns) < 2 or equity.iloc[-1] == 0:
            return self._empty_metrics()

        ann_factor = self._annualization_factor(returns.index)
        total_return = equity.iloc[-1] / equity.iloc[0] - 1
        years = max(len(returns) / ann_factor, 1 / 365)
        cagr = (1 + total_return) ** (1 / years) - 1

        mean_ret = returns.mean() * ann_factor
        std_ret = returns.std() * np.sqrt(ann_factor) if returns.std() > 0 else 1e-10
        sharpe = mean_ret / std_ret

        downside = returns[returns < 0].std() * np.sqrt(ann_factor) if (returns < 0).any() else 1e-10
        sortino = mean_ret / downside

        # Drawdown
        cum_max = equity.cummax()
        drawdown = (equity - cum_max) / cum_max
        max_dd = abs(drawdown.min())
        calmar = cagr / max_dd if max_dd > 0 else 0.0

        # Time under water
        underwater = drawdown < 0
        if underwater.any():
            uw_groups = (~underwater).cumsum()
            uw_durations = underwater.groupby(uw_groups).sum()
            max_uw_days = uw_durations.max()
        else:
            max_uw_days = 0

        # Trade stats
        n_trades = len(trades)
        winners = [t for t in trades if t.pnl_net > 0]
        losers = [t for t in trades if t.pnl_net <= 0]
        hit_rate = len(winners) / n_trades if n_trades > 0 else 0
        avg_trade = np.mean([t.pnl_net for t in trades]) if trades else 0
        gross_profit = sum(t.pnl_net for t in winners) if winners else 0
        gross_loss = abs(sum(t.pnl_net for t in losers)) if losers else 1e-10
        profit_factor = gross_profit / gross_loss

        # Turnover
        turnover = n_trades * 2 / years if years > 0 else 0

        total_fees = sum(t.fees for t in trades)
        total_slip = sum(t.slippage for t in trades)

        return BacktestMetrics(
            cagr_pct=round(cagr * 100, 2),
            annualized_return_pct=round(mean_ret * 100, 2),
            sharpe=round(sharpe, 3),
            sortino=round(sortino, 3),
            calmar=round(calmar, 3),
            max_drawdown_pct=round(max_dd * 100, 2),
            max_drawdown_duration_days=float(max_uw_days),
            hit_rate=round(hit_rate, 3),
            avg_trade_return_pct=round(float(avg_trade) * 100, 4),
            profit_factor=round(profit_factor, 3),
            turnover_annual=round(turnover, 1),
            avg_exposure_pct=round(float(returns.ne(0).mean()) * 100, 1),
            total_trades=n_trades,
            avg_holding_period_hours=round(
                np.mean([t.holding_bars for t in trades]) if trades else 0, 1
            ),
            skewness=round(float(returns.skew()), 3),
            kurtosis=round(float(returns.kurtosis()), 3),
            return_before_costs_pct=round(float(returns.sum()) * 100, 2),
            return_after_costs_pct=round(total_return * 100, 2),
            total_fees_pct=round(total_fees, 4),
            total_slippage_pct=round(total_slip, 4),
        )

    # ── Walk-Forward ─────────────────────────────────────────────────────

    def _walk_forward(
        self,
        returns: pd.Series,
        equity: pd.Series,
        trades: list[Trade],
        index: pd.DatetimeIndex,
        design: BacktestDesign,
    ) -> list[BacktestMetrics]:
        """Rolling walk-forward analysis."""
        n = len(returns)
        window_size = n // design.walk_forward_windows
        results = []

        for i in range(design.walk_forward_windows):
            start = i * window_size
            end = min((i + 1) * window_size, n)
            window_rets = returns.iloc[start:end]
            window_eq = equity.iloc[start:end]
            window_trades = [
                t for t in trades
                if t.entry_time >= index[start] and t.exit_time < index[min(end - 1, n - 1)]
            ]
            metrics = self._compute_metrics(window_rets, window_eq, window_trades, f"wf_{i}")
            results.append(metrics)

        return results

    # ── Trade Extraction ─────────────────────────────────────────────────

    def _extract_trades(
        self,
        close: pd.Series,
        position: pd.Series,
        signals: pd.Series,
    ) -> list[Trade]:
        """Extract individual trades from position series."""
        trades: list[Trade] = []
        pos_changes = position.diff().fillna(position)
        entries = pos_changes[pos_changes != 0].index

        current_entry: pd.Timestamp | None = None
        current_side: str = ""
        current_price: float = 0.0

        for ts in entries:
            new_pos = position.loc[ts]
            if current_entry is not None and new_pos != position.shift(1).get(ts, 0):
                # Close previous trade
                exit_price = close.loc[ts]
                entry_price = current_price
                side_mult = 1.0 if current_side == "long" else -1.0
                gross_pnl = side_mult * (exit_price / entry_price - 1)
                cost = self.cost_model.total_round_trip_bps / 10_000
                net_pnl = gross_pnl - cost

                trades.append(Trade(
                    entry_time=current_entry,
                    exit_time=ts,
                    symbol="",
                    side=current_side,
                    entry_price=entry_price,
                    exit_price=exit_price,
                    size=1.0,
                    pnl_gross=gross_pnl,
                    pnl_net=net_pnl,
                    fees=self.cost_model.commission_bps / 10_000 * 2,
                    slippage=self.cost_model.slippage_bps / 10_000 * 2,
                    holding_bars=len(close.loc[current_entry:ts]) - 1,
                ))
                current_entry = None

            if new_pos != 0:
                current_entry = ts
                current_side = "long" if new_pos > 0 else "short"
                current_price = close.loc[ts]

        return trades

    # ── Helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _estimate_bar_minutes(index: pd.DatetimeIndex) -> int:
        if len(index) < 2:
            return 60
        median_delta = pd.Series(index).diff().dropna().median()
        return max(1, int(median_delta.total_seconds() / 60))

    @staticmethod
    def _annualization_factor(index: pd.DatetimeIndex) -> float:
        if len(index) < 2:
            return 365
        median_delta = pd.Series(index).diff().dropna().median()
        bars_per_day = pd.Timedelta(days=1) / median_delta
        return float(bars_per_day * 365)

    @staticmethod
    def _empty_metrics() -> BacktestMetrics:
        return BacktestMetrics(
            cagr_pct=0, annualized_return_pct=0, sharpe=0, sortino=0, calmar=0,
            max_drawdown_pct=0, max_drawdown_duration_days=0, hit_rate=0,
            avg_trade_return_pct=0, profit_factor=0, turnover_annual=0,
            avg_exposure_pct=0, total_trades=0, avg_holding_period_hours=0,
            skewness=0, kurtosis=0, return_before_costs_pct=0,
            return_after_costs_pct=0, total_fees_pct=0, total_slippage_pct=0,
        )
