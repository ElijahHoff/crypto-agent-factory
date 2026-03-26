"""Core domain models for the strategy R&D pipeline."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ─── Enums ───────────────────────────────────────────────────────────────────

class StrategyType(str, Enum):
    MOMENTUM = "momentum"
    MEAN_REVERSION = "mean_reversion"
    BREAKOUT = "breakout"
    CROSS_SECTIONAL = "cross_sectional"
    MARKET_NEUTRAL = "market_neutral"
    FUNDING_BASIS = "funding_basis"
    SENTIMENT = "sentiment"
    REGIME_ADAPTIVE = "regime_adaptive"
    VOLATILITY_STRUCTURE = "volatility_structure"
    STATISTICAL_ARBITRAGE = "statistical_arbitrage"


class MarketRegime(str, Enum):
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    MEAN_REVERTING = "mean_reverting"
    HIGH_VOLATILITY = "high_volatility"
    LOW_VOLATILITY = "low_volatility"
    PANIC = "panic"
    CHOP = "chop"
    EXPANSION = "expansion"
    COMPRESSION = "compression"


class Timeframe(str, Enum):
    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    H1 = "1h"
    H4 = "4h"
    D1 = "1d"


class Decision(str, Enum):
    REJECT = "reject"
    REFINE = "refine"
    ADVANCE = "advance"


class PipelineStage(str, Enum):
    HYPOTHESIS = "hypothesis"
    FORMALIZATION = "formalization"
    DATA_SPEC = "data_spec"
    FEATURE_ENGINEERING = "feature_engineering"
    BACKTEST_DESIGN = "backtest_design"
    BACKTEST_RUN = "backtest_run"
    ROBUSTNESS = "robustness"
    RISK_REVIEW = "risk_review"
    VALIDATION = "validation"
    DECISION = "decision"
    PAPER_TRADING = "paper_trading"


# ─── Hypothesis ──────────────────────────────────────────────────────────────

class StrategyHypothesis(BaseModel):
    """Stage A: A trading hypothesis before formalization."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str
    idea: str
    economic_logic: str = Field(description="Why should this edge exist?")
    strategy_type: StrategyType
    timeframe: Timeframe
    universe: list[str] = Field(description="Target assets / pairs")
    long_logic: str
    short_logic: str | None = None
    risk_factors: list[str] = Field(default_factory=list)
    edge_death_conditions: list[str] = Field(
        description="Conditions under which the edge should disappear"
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ─── Formalized Strategy ─────────────────────────────────────────────────────

class EntryRule(BaseModel):
    condition: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class ExitRule(BaseModel):
    condition: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class RiskFramework(BaseModel):
    max_position_size_pct: float = 10.0
    max_leverage: float = 3.0
    stop_loss_pct: float | None = None
    trailing_stop_pct: float | None = None
    max_concurrent_positions: int = 10
    daily_loss_limit_pct: float = 3.0
    drawdown_brake_pct: float = 15.0
    cooldown_bars: int = 0
    kill_switch_conditions: list[str] = Field(default_factory=list)


class FormalizedStrategy(BaseModel):
    """Stage B: Fully specified trading rules."""

    hypothesis_id: str
    entry_rules: list[EntryRule]
    exit_rules: list[ExitRule]
    position_sizing: str = Field(description="Sizing methodology")
    rebalance_logic: str
    risk_framework: RiskFramework = Field(default_factory=RiskFramework)
    parameters: dict[str, Any] = Field(description="Fixed parameters")
    hyperparameters: dict[str, Any] = Field(description="Optimizable params")
    frozen_params: list[str] = Field(
        default_factory=list, description="Params forbidden from optimization"
    )
    pseudocode: str


# ─── Data & Feature Spec ─────────────────────────────────────────────────────

class DataSpec(BaseModel):
    """Stage C: Data requirements."""

    datasets: list[str] = Field(description="e.g. ['ohlcv', 'funding_rates', 'open_interest']")
    frequency: Timeframe
    start_date: str
    end_date: str = "latest"
    universe: list[str]
    preprocessing: list[str] = Field(default_factory=list)
    quality_checks: list[str] = Field(
        default_factory=lambda: [
            "missing_candles",
            "duplicate_timestamps",
            "timezone_consistency",
            "survivorship_bias",
            "delisting_events",
        ]
    )


class FeatureSpec(BaseModel):
    name: str
    formula: str
    lag: int = Field(ge=0, description="Minimum bars of lag to avoid lookahead")
    category: str = Field(description="e.g. momentum, volatility, volume, cross_sectional")
    hypothesis: str = Field(description="Why this feature should be predictive")
    stability_note: str = ""


# ─── Backtest Design & Results ───────────────────────────────────────────────

class BacktestDesign(BaseModel):
    """Stage D: How we test."""

    train_pct: float = 0.50
    validation_pct: float = 0.25
    test_pct: float = 0.25
    walk_forward_windows: int = 5
    walk_forward_retrain: bool = False
    benchmarks: list[str] = Field(default_factory=lambda: ["buy_and_hold_btc", "equal_weight"])
    commission_bps: float = 10.0
    slippage_bps: float = 5.0
    funding_bps: float = 1.0
    rejection_criteria: dict[str, float] = Field(
        default_factory=lambda: {
            "min_sharpe": 0.8,
            "max_drawdown_pct": 25.0,
            "min_trades": 100,
            "min_profit_factor": 1.2,
            "min_oos_sharpe_ratio": 0.5,  # OOS sharpe / IS sharpe
        }
    )


class BacktestMetrics(BaseModel):
    """Stage E: Structured results."""

    cagr_pct: float
    annualized_return_pct: float
    sharpe: float
    sortino: float
    calmar: float
    max_drawdown_pct: float
    max_drawdown_duration_days: float
    hit_rate: float
    avg_trade_return_pct: float
    profit_factor: float
    turnover_annual: float
    avg_exposure_pct: float
    total_trades: int
    avg_holding_period_hours: float
    skewness: float
    kurtosis: float
    # Cost breakdown
    return_before_costs_pct: float
    return_after_costs_pct: float
    total_fees_pct: float
    total_slippage_pct: float
    # Stability
    sharpe_by_year: dict[str, float] = Field(default_factory=dict)
    sharpe_by_quarter: dict[str, float] = Field(default_factory=dict)
    sharpe_by_asset: dict[str, float] = Field(default_factory=dict)
    sharpe_by_regime: dict[str, float] = Field(default_factory=dict)


class BacktestResult(BaseModel):
    in_sample: BacktestMetrics
    validation: BacktestMetrics | None = None
    out_of_sample: BacktestMetrics | None = None
    walk_forward: list[BacktestMetrics] = Field(default_factory=list)


# ─── Robustness Checks ──────────────────────────────────────────────────────

class RobustnessCheck(BaseModel):
    name: str
    description: str
    passed: bool
    details: str
    severity: str = Field(description="low / medium / high / critical")


class RobustnessReport(BaseModel):
    """Stage F: Failure analysis."""

    checks: list[RobustnessCheck]
    parameter_sensitivity: dict[str, str] = Field(default_factory=dict)
    stress_scenarios: list[dict[str, Any]] = Field(default_factory=list)
    overall_score: float = Field(ge=0.0, le=1.0)
    critical_failures: list[str] = Field(default_factory=list)


# ─── Decision Memo ───────────────────────────────────────────────────────────

class DecisionMemo(BaseModel):
    """Stage G: Final verdict."""

    strategy_id: str
    strategy_name: str
    decision: Decision
    reasoning: str
    key_risks: list[str]
    improvements_needed: list[str] = Field(default_factory=list)
    edge_evidence: list[str] = Field(default_factory=list)
    dissenting_opinions: list[str] = Field(default_factory=list)
    reviewer: str = "auditor_agent"
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ─── Experiment Registry ─────────────────────────────────────────────────────

class ExperimentRecord(BaseModel):
    """One row in the experiment registry."""

    experiment_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    strategy_name: str
    stage: PipelineStage
    hypothesis: StrategyHypothesis | None = None
    formalization: FormalizedStrategy | None = None
    data_spec: DataSpec | None = None
    features: list[FeatureSpec] = Field(default_factory=list)
    backtest_design: BacktestDesign | None = None
    backtest_result: BacktestResult | None = None
    robustness: RobustnessReport | None = None
    decision: DecisionMemo | None = None
    tags: list[str] = Field(default_factory=list)
    notes: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ─── Pipeline State (for LangGraph) ─────────────────────────────────────────

class PipelineState(BaseModel):
    """Shared state passed between agents in the LangGraph workflow."""

    experiment: ExperimentRecord
    messages: list[dict[str, str]] = Field(default_factory=list)
    current_stage: PipelineStage = PipelineStage.HYPOTHESIS
    agent_outputs: dict[str, Any] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    should_stop: bool = False
