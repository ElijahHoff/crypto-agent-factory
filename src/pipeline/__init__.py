"""LangGraph pipeline: orchestrates the full R&D workflow across all agents."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph
from loguru import logger

from src.agents import get_agent
from src.models import (
    Decision,
    ExperimentRecord,
    PipelineStage,
    PipelineState,
)


# ─── LangGraph State ────────────────────────────────────────────────────────

class GraphState(TypedDict):
    experiment: dict[str, Any]
    messages: list[dict[str, str]]
    current_stage: str
    agent_outputs: dict[str, Any]
    errors: list[str]
    should_stop: bool



def _enrich_backtest_context(experiment: dict) -> str:
    """Build enriched context string with charts, benchmarks, walk-forward for agents."""
    parts = []
    bt = experiment.get("backtest_result") or {}

    # Chart analysis (text description of visual patterns)
    chart_text = bt.get("chart_analysis", experiment.get("chart_analysis", ""))
    if chart_text:
        parts.append(chart_text)

    # Benchmark comparison
    benchmarks = bt.get("benchmarks", {})
    if benchmarks:
        parts.append("\n=== BENCHMARK COMPARISON ===")
        for name, data in benchmarks.items():
            if isinstance(data, dict):
                parts.append(f"  {name}: return={data.get('total_return', 0):.2%}, "
                           f"Sharpe={data.get('sharpe', 0):.3f}, "
                           f"MaxDD={data.get('max_drawdown', 0):.2%}")

    # Walk-forward
    wf = bt.get("walk_forward", {})
    if wf:
        parts.append(f"\n=== WALK-FORWARD ({wf.get('n_periods', 0)} periods) ===")
        parts.append(f"  Consistency: {wf.get('positive_periods', 0)}/{wf.get('n_periods', 0)} positive "
                   f"({wf.get('consistency_ratio', 0):.0%})")
        parts.append(f"  Avg Sharpe: {wf.get('avg_sharpe', 0):.3f} ± {wf.get('sharpe_std', 0):.3f}")
        subperiods = wf.get("subperiods", [])
        if subperiods:
            sharpes = [f"{s.get('sharpe', 0):.2f}" for s in subperiods]
            parts.append(f"  Per-period Sharpes: [{', '.join(sharpes)}]")

    # Multi-asset
    multi = bt.get("multi_asset", {})
    if multi:
        parts.append("\n=== MULTI-ASSET CROSS-VALIDATION ===")
        for sym, data in multi.items():
            parts.append(f"  {sym}: Sharpe={data.get('sharpe', 0):.3f}, "
                       f"return={data.get('total_return', 0):.2%}")

    return "\n".join(parts)


def _to_state(d: GraphState) -> PipelineState:
    return PipelineState(
        experiment=ExperimentRecord(**d["experiment"]),
        messages=d["messages"],
        current_stage=PipelineStage(d["current_stage"]),
        agent_outputs=d["agent_outputs"],
        errors=d["errors"],
        should_stop=d["should_stop"],
    )


# ─── Node functions ─────────────────────────────────────────────────────────

def hypothesis_node(state: GraphState) -> GraphState:
    """Stage A: Generate / validate hypothesis."""
    logger.info("═══ Stage A: Hypothesis Generation ═══")
    agent = get_agent("strategy_ideation")
    result = agent.run({"stage": "hypothesis", "n_strategies": 1, "strategy_class": "any"})

    state["agent_outputs"]["hypothesis"] = result.structured or result.content
    state["current_stage"] = PipelineStage.FORMALIZATION.value
    state["messages"].append({"role": "strategy_ideation", "content": result.content})
    return state


def market_analysis_node(state: GraphState) -> GraphState:
    """Market Structure Analyst reviews the hypothesis."""
    logger.info("═══ Market Structure Analysis ═══")
    agent = get_agent("market_analyst")
    hypothesis = state["agent_outputs"].get("hypothesis", {})
    result = agent.run({"stage": "market_analysis", "action": "assess_hypothesis", "hypothesis": hypothesis})

    state["agent_outputs"]["market_analysis"] = result.structured or result.content
    state["messages"].append({"role": "market_analyst", "content": result.content})
    return state


def formalization_node(state: GraphState) -> GraphState:
    """Stage B: Formalize strategy rules."""
    logger.info("═══ Stage B: Quant Formalization ═══")
    agent = get_agent("quant_formalization")
    hypothesis = state["agent_outputs"].get("hypothesis", {})
    result = agent.run({"stage": "formalization", "hypothesis": hypothesis})

    state["agent_outputs"]["formalization"] = result.structured or result.content
    state["current_stage"] = PipelineStage.DATA_SPEC.value
    state["messages"].append({"role": "quant_formalization", "content": result.content})
    return state


def data_spec_node(state: GraphState) -> GraphState:
    """Stage C: Data & feature specification."""
    logger.info("═══ Stage C: Data Specification ═══")
    data_agent = get_agent("data_engineer")
    strategy = {
        "hypothesis": state["agent_outputs"].get("hypothesis", {}),
        "formalization": state["agent_outputs"].get("formalization", {}),
    }
    data_result = data_agent.run({"stage": "data_spec", "strategy": strategy})
    state["agent_outputs"]["data_spec"] = data_result.structured or data_result.content

    logger.info("═══ Stage C: Feature Engineering ═══")
    feat_agent = get_agent("feature_engineer")
    feat_result = feat_agent.run({"stage": "features", "strategy": strategy})
    state["agent_outputs"]["features"] = feat_result.structured or feat_result.content

    state["current_stage"] = PipelineStage.BACKTEST_DESIGN.value
    state["messages"].append({"role": "data_engineer", "content": data_result.content})
    state["messages"].append({"role": "feature_engineer", "content": feat_result.content})
    return state


def backtest_design_node(state: GraphState) -> GraphState:
    """Stage D: Design backtest framework."""
    logger.info("═══ Stage D: Backtest Design ═══")
    agent = get_agent("backtesting_engineer")
    strategy = {
        "hypothesis": state["agent_outputs"].get("hypothesis", {}),
        "formalization": state["agent_outputs"].get("formalization", {}),
        "data_spec": state["agent_outputs"].get("data_spec", {}),
        "features": state["agent_outputs"].get("features", {}),
    }
    result = agent.run({"stage": "backtest_design", "strategy": strategy})

    state["agent_outputs"]["backtest_design"] = result.structured or result.content
    state["current_stage"] = PipelineStage.BACKTEST_RUN.value
    state["messages"].append({"role": "backtesting_engineer", "content": result.content})
    return state


def backtest_run_node(state: GraphState) -> GraphState:
    """Stage E: Fetch real market data, generate signals, run backtest + robustness."""
    logger.info("═══ Stage E: LIVE Backtest Execution ═══")

    try:
        from src.backtesting.live_runner import LiveBacktestRunner

        runner = LiveBacktestRunner()
        result = runner.run(
            state["agent_outputs"].get("formalization", {}),
            state["agent_outputs"].get("backtest_design", {}),
            strategy_name=state["experiment"]["strategy_name"],
        )

        if result.get("status") == "error":
            logger.warning(f"Backtest error: {result.get('error')}")
            state["agent_outputs"]["backtest_result"] = result
            state["errors"].append(f"Backtest failed: {result.get('error')}")
        else:
            state["agent_outputs"]["backtest_result"] = result
            is_data = result.get("in_sample", {})
            logger.info(
                f"✅ Backtest done: Sharpe={is_data.get('sharpe', 'N/A')}, "
                f"Trades={is_data.get('total_trades', 0)}, "
                f"MaxDD={is_data.get('max_drawdown_pct', 'N/A')}%"
            )

    except Exception as e:
        logger.exception(f"Backtest execution failed: {e}")
        state["agent_outputs"]["backtest_result"] = {
            "status": "error",
            "error": str(e),
            "in_sample": None,
            "out_of_sample": None,
            "robustness": None,
        }
        state["errors"].append(str(e))

    state["current_stage"] = PipelineStage.ROBUSTNESS.value
    return state


def risk_review_node(state: GraphState) -> GraphState:
    """Stage F (part 1): Risk assessment."""
    logger.info("═══ Stage F: Risk Review ═══")
    agent = get_agent("risk_manager")

    # v0.4: Inject chart analysis, benchmarks, walk-forward into agent context

    try:
        _extra_context = _enrich_backtest_context(state.get("experiment", {}))

    except Exception:
        _extra_context = ""
    if _extra_context:

        if isinstance(experiment.get("backtest_result"), dict):

            experiment["backtest_result"]["_enriched_analysis"] = _extra_context

    result = agent.run({
        "stage": "risk_review",
        "strategy": state["agent_outputs"].get("formalization", {}),
        "backtest_results": state["agent_outputs"].get("backtest_result", {}),
    })

    state["agent_outputs"]["risk_review"] = result.structured or result.content
    state["messages"].append({"role": "risk_manager", "content": result.content})
    return state


def validation_node(state: GraphState) -> GraphState:
    """Stage F (part 2): Statistical validation."""
    logger.info("═══ Stage F: Statistical Validation ═══")
    agent = get_agent("statistician")

    # v0.4: Inject chart analysis, benchmarks, walk-forward into agent context

    try:
        _extra_context = _enrich_backtest_context(state.get("experiment", {}))

    except Exception:
        _extra_context = ""
    if _extra_context:

        if isinstance(experiment.get("backtest_result"), dict):

            experiment["backtest_result"]["_enriched_analysis"] = _extra_context

    result = agent.run({
        "stage": "validation",
        "strategy": state["agent_outputs"].get("formalization", {}),
        "backtest_results": state["agent_outputs"].get("backtest_result", {}),
        "n_strategies_tested": 1,
    })

    state["agent_outputs"]["validation"] = result.structured or result.content
    state["current_stage"] = PipelineStage.VALIDATION.value
    state["messages"].append({"role": "statistician", "content": result.content})
    return state


def audit_node(state: GraphState) -> GraphState:
    """Independent adversarial audit."""
    logger.info("═══ Audit / Critic Review ═══")
    agent = get_agent("auditor")

    # v0.4: Inject chart analysis, benchmarks, walk-forward into agent context

    try:
        _extra_context = _enrich_backtest_context(state.get("experiment", {}))

    except Exception:
        _extra_context = ""
    if _extra_context:

        if isinstance(experiment.get("backtest_result"), dict):

            experiment["backtest_result"]["_enriched_analysis"] = _extra_context

    result = agent.run({"stage": "audit", "experiment": state["agent_outputs"]})

    state["agent_outputs"]["audit"] = result.structured or result.content
    state["messages"].append({"role": "auditor", "content": result.content})
    return state


def decision_node(state: GraphState) -> GraphState:
    """Stage G: Research Director makes final decision."""
    logger.info("═══ Stage G: Final Decision ═══")
    agent = get_agent("research_director")
    result = agent.run({"stage": "decision", "action": "review", "experiment": state["agent_outputs"]})

    state["agent_outputs"]["decision"] = result.structured or result.content
    state["current_stage"] = PipelineStage.DECISION.value
    state["messages"].append({"role": "research_director", "content": result.content})
    return state


def paper_trading_node(state: GraphState) -> GraphState:
    """Prepare for paper trading (only if decision = advance)."""
    logger.info("═══ Paper Trading Setup ═══")
    agent = get_agent("paper_trading")
    result = agent.run({
        "stage": "paper_trading",
        "strategy": state["agent_outputs"].get("formalization", {}),
    })

    state["agent_outputs"]["paper_trading"] = result.structured or result.content
    state["current_stage"] = PipelineStage.PAPER_TRADING.value
    state["messages"].append({"role": "paper_trading", "content": result.content})
    return state


# ─── Routing logic ──────────────────────────────────────────────────────────

def should_continue_to_paper(state: GraphState) -> str:
    """After decision node, route to paper trading or end."""
    decision_data = state["agent_outputs"].get("decision", {})
    if isinstance(decision_data, str):
        try:
            decision_data = json.loads(decision_data)
        except json.JSONDecodeError:
            pass

    decision = ""
    if isinstance(decision_data, dict):
        decision = decision_data.get("decision", "reject")

    if decision == "advance":
        return "paper_trading"
    return "end"


# ─── Build the graph ────────────────────────────────────────────────────────

def build_pipeline() -> StateGraph:
    """Construct the full LangGraph R&D pipeline."""

    workflow = StateGraph(GraphState)

    # Add nodes
    workflow.add_node("hypothesis", hypothesis_node)
    workflow.add_node("market_analysis", market_analysis_node)
    workflow.add_node("formalization", formalization_node)
    workflow.add_node("data_spec", data_spec_node)
    workflow.add_node("backtest_design", backtest_design_node)
    workflow.add_node("backtest_run", backtest_run_node)
    workflow.add_node("risk_review", risk_review_node)
    workflow.add_node("validation", validation_node)
    workflow.add_node("audit", audit_node)
    workflow.add_node("decision", decision_node)
    workflow.add_node("paper_trading", paper_trading_node)

    # Define edges (sequential pipeline)
    workflow.set_entry_point("hypothesis")
    workflow.add_edge("hypothesis", "market_analysis")
    workflow.add_edge("market_analysis", "formalization")
    workflow.add_edge("formalization", "data_spec")
    workflow.add_edge("data_spec", "backtest_design")
    workflow.add_edge("backtest_design", "backtest_run")
    workflow.add_edge("backtest_run", "risk_review")
    workflow.add_edge("risk_review", "validation")
    workflow.add_edge("validation", "audit")
    workflow.add_edge("audit", "decision")

    # Conditional: advance → paper trading, else → end
    workflow.add_conditional_edges(
        "decision",
        should_continue_to_paper,
        {"paper_trading": "paper_trading", "end": END},
    )
    workflow.add_edge("paper_trading", END)

    return workflow


def create_initial_state(strategy_name: str = "unnamed") -> GraphState:
    """Create a fresh pipeline state for a new experiment."""
    experiment = ExperimentRecord(
        strategy_name=strategy_name,
        stage=PipelineStage.HYPOTHESIS,
    )
    return GraphState(
        experiment=experiment.model_dump(mode="json"),
        messages=[],
        current_stage=PipelineStage.HYPOTHESIS.value,
        agent_outputs={},
        errors=[],
        should_stop=False,
    )


def run_pipeline(strategy_name: str = "unnamed") -> GraphState:
    """Build and execute the full pipeline synchronously."""
    logger.info(f"🏭 Starting Agent Factory pipeline for: {strategy_name}")
    graph = build_pipeline()
    app = graph.compile()

    initial = create_initial_state(strategy_name)
    final_state = app.invoke(initial)

    logger.info(f"✅ Pipeline complete. Decision: {final_state['agent_outputs'].get('decision', 'N/A')}")
    return final_state
