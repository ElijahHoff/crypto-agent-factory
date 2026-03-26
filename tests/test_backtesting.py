"""Tests for the backtesting engine."""

import numpy as np
import pandas as pd
import pytest

from src.backtesting import BacktestEngine, CostModel, Trade


@pytest.fixture
def sample_prices() -> pd.DataFrame:
    """Generate synthetic price data."""
    np.random.seed(42)
    dates = pd.date_range("2022-01-01", periods=1000, freq="1h", tz="UTC")
    returns = np.random.normal(0.0001, 0.01, len(dates))
    close = 100 * np.exp(np.cumsum(returns))
    return pd.DataFrame({
        "open": close * (1 + np.random.normal(0, 0.001, len(dates))),
        "high": close * (1 + abs(np.random.normal(0, 0.005, len(dates)))),
        "low": close * (1 - abs(np.random.normal(0, 0.005, len(dates)))),
        "close": close,
        "volume": np.random.lognormal(10, 1, len(dates)),
    }, index=dates)


@pytest.fixture
def momentum_signals(sample_prices: pd.DataFrame) -> pd.Series:
    """Simple momentum signal: +1 if last 20 bars up, -1 if down, 0 otherwise."""
    ret = sample_prices["close"].pct_change(20)
    signals = pd.Series(0, index=sample_prices.index)
    signals[ret > 0.01] = 1
    signals[ret < -0.01] = -1
    return signals


class TestCostModel:
    def test_defaults(self):
        cm = CostModel()
        assert cm.commission_bps == 10.0
        assert cm.total_entry_cost_bps == 17.0  # 10 + 5 + 2
        assert cm.total_round_trip_bps == 34.0

    def test_custom(self):
        cm = CostModel(commission_bps=5, slippage_bps=3, spread_bps=1)
        assert cm.total_entry_cost_bps == 9.0


class TestBacktestEngine:
    def test_basic_backtest(self, sample_prices, momentum_signals):
        engine = BacktestEngine()
        result = engine.run_backtest(sample_prices, momentum_signals)

        assert "in_sample" in result
        assert "validation" in result
        assert "out_of_sample" in result
        assert "equity_net" in result
        assert "trades" in result
        assert result["in_sample"].total_trades >= 0

    def test_no_trades_with_zero_signals(self, sample_prices):
        signals = pd.Series(0, index=sample_prices.index)
        engine = BacktestEngine()
        result = engine.run_backtest(sample_prices, signals)
        assert result["in_sample"].total_trades == 0

    def test_costs_reduce_returns(self, sample_prices, momentum_signals):
        engine_no_cost = BacktestEngine(
            cost_model=CostModel(commission_bps=0, slippage_bps=0, spread_bps=0, funding_bps=0)
        )
        engine_with_cost = BacktestEngine()

        r_no_cost = engine_no_cost.run_backtest(sample_prices, momentum_signals)
        r_with_cost = engine_with_cost.run_backtest(sample_prices, momentum_signals)

        # Net returns should be lower with costs
        assert r_with_cost["equity_net"].iloc[-1] <= r_no_cost["equity_net"].iloc[-1]

    def test_walk_forward_windows(self, sample_prices, momentum_signals):
        from src.models import BacktestDesign
        design = BacktestDesign(walk_forward_windows=4)
        engine = BacktestEngine()
        result = engine.run_backtest(sample_prices, momentum_signals, design)
        assert len(result["walk_forward"]) == 4

    def test_metrics_sanity(self, sample_prices, momentum_signals):
        engine = BacktestEngine()
        result = engine.run_backtest(sample_prices, momentum_signals)
        m = result["in_sample"]

        assert -100 <= m.max_drawdown_pct <= 100
        assert 0 <= m.hit_rate <= 1
        assert m.total_trades >= 0


class TestTrade:
    def test_trade_creation(self):
        t = Trade(
            entry_time=pd.Timestamp("2022-01-01", tz="UTC"),
            exit_time=pd.Timestamp("2022-01-02", tz="UTC"),
            symbol="BTC/USDT",
            side="long",
            entry_price=100.0,
            exit_price=105.0,
            size=1.0,
            pnl_gross=0.05,
            pnl_net=0.045,
        )
        assert t.side == "long"
        assert t.pnl_net == 0.045
