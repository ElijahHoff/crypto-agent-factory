"""Tests for core domain models."""

import pytest
from src.models import (
    BacktestDesign,
    BacktestMetrics,
    Decision,
    DecisionMemo,
    ExperimentRecord,
    FeatureSpec,
    FormalizedStrategy,
    EntryRule,
    ExitRule,
    MarketRegime,
    PipelineStage,
    PipelineState,
    RiskFramework,
    RobustnessCheck,
    RobustnessReport,
    StrategyHypothesis,
    StrategyType,
    Timeframe,
)


class TestStrategyHypothesis:
    def test_creation(self):
        h = StrategyHypothesis(
            name="test_momentum",
            idea="Go long when momentum is strong",
            economic_logic="Herding behavior creates persistence",
            strategy_type=StrategyType.MOMENTUM,
            timeframe=Timeframe.H1,
            universe=["BTC/USDT", "ETH/USDT"],
            long_logic="return > 0 over lookback",
            risk_factors=["regime change"],
            edge_death_conditions=["crowding"],
        )
        assert h.name == "test_momentum"
        assert h.strategy_type == StrategyType.MOMENTUM
        assert len(h.id) == 8

    def test_auto_id(self):
        h1 = StrategyHypothesis(
            name="a", idea="b", economic_logic="c",
            strategy_type=StrategyType.MOMENTUM, timeframe=Timeframe.H1,
            universe=["X"], long_logic="Y", edge_death_conditions=["Z"],
        )
        h2 = StrategyHypothesis(
            name="a", idea="b", economic_logic="c",
            strategy_type=StrategyType.MOMENTUM, timeframe=Timeframe.H1,
            universe=["X"], long_logic="Y", edge_death_conditions=["Z"],
        )
        assert h1.id != h2.id


class TestBacktestMetrics:
    def test_creation(self):
        m = BacktestMetrics(
            cagr_pct=15.0, annualized_return_pct=15.0, sharpe=1.2,
            sortino=1.5, calmar=0.8, max_drawdown_pct=18.0,
            max_drawdown_duration_days=45, hit_rate=0.55,
            avg_trade_return_pct=0.15, profit_factor=1.4,
            turnover_annual=200, avg_exposure_pct=80,
            total_trades=500, avg_holding_period_hours=12,
            skewness=-0.3, kurtosis=4.5,
            return_before_costs_pct=20, return_after_costs_pct=15,
            total_fees_pct=3, total_slippage_pct=2,
        )
        assert m.sharpe == 1.2
        assert m.total_trades == 500


class TestBacktestDesign:
    def test_defaults(self):
        d = BacktestDesign()
        assert d.train_pct + d.validation_pct + d.test_pct == 1.0
        assert d.commission_bps == 10.0
        assert d.rejection_criteria["min_trades"] == 100


class TestRobustnessReport:
    def test_scoring(self):
        checks = [
            RobustnessCheck(name="a", description="", passed=True, details="ok", severity="high"),
            RobustnessCheck(name="b", description="", passed=False, details="fail", severity="critical"),
        ]
        report = RobustnessReport(checks=checks, overall_score=0.5, critical_failures=["b"])
        assert report.overall_score == 0.5
        assert len(report.critical_failures) == 1


class TestExperimentRecord:
    def test_creation(self):
        r = ExperimentRecord(strategy_name="test", stage=PipelineStage.HYPOTHESIS)
        assert r.strategy_name == "test"
        assert len(r.experiment_id) == 8


class TestDecisionMemo:
    def test_reject(self):
        d = DecisionMemo(
            strategy_id="abc",
            strategy_name="test",
            decision=Decision.REJECT,
            reasoning="Too few trades",
            key_risks=["sample size"],
        )
        assert d.decision == Decision.REJECT


class TestPipelineState:
    def test_defaults(self):
        exp = ExperimentRecord(strategy_name="test", stage=PipelineStage.HYPOTHESIS)
        state = PipelineState(experiment=exp)
        assert state.current_stage == PipelineStage.HYPOTHESIS
        assert not state.should_stop
