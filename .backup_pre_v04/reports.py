"""Report generator: produces structured experiment reports."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from src.models import BacktestMetrics, DecisionMemo


def generate_experiment_report(state: dict[str, Any]) -> str:
    """Generate a full markdown report from pipeline state."""
    outputs = state.get("agent_outputs", {})
    lines: list[str] = []

    lines.append("# Strategy R&D Experiment Report")
    lines.append(f"Generated: {datetime.utcnow().isoformat()}")
    lines.append("")

    # 1. Strategy Thesis
    hyp = outputs.get("hypothesis", {})
    lines.append("## 1. Strategy Thesis")
    if isinstance(hyp, dict):
        hypotheses = hyp.get("hypotheses", [hyp])
        for h in hypotheses:
            lines.append(f"**Name:** {h.get('name', 'N/A')}")
            lines.append(f"**Idea:** {h.get('idea', 'N/A')}")
            lines.append(f"**Type:** {h.get('strategy_type', 'N/A')}")
            lines.append(f"**Timeframe:** {h.get('timeframe', 'N/A')}")
            lines.append("")
    lines.append("")

    # 2. Market Logic
    market = outputs.get("market_analysis", {})
    lines.append("## 2. Market Logic")
    if isinstance(market, dict):
        lines.append(f"**Structural Validity:** {market.get('structural_validity', 'N/A')}")
        lines.append(f"**Counterparty:** {market.get('counterparty_analysis', 'N/A')}")
        lines.append(f"**Crowding Risk:** {market.get('crowding_risk', 'N/A')}")
    lines.append("")

    # 3. Formal Rules
    formal = outputs.get("formalization", {})
    lines.append("## 3. Formal Rules")
    if isinstance(formal, dict):
        lines.append(f"**Position Sizing:** {formal.get('position_sizing', 'N/A')}")
        lines.append(f"**Complexity:** {formal.get('complexity_score', 'N/A')}")
        pc = formal.get("pseudocode", "")
        if pc:
            lines.append("```")
            lines.append(pc)
            lines.append("```")
    lines.append("")

    # 4. Data & Features
    lines.append("## 4. Required Data")
    data_spec = outputs.get("data_spec", {})
    if isinstance(data_spec, dict):
        for ds in data_spec.get("datasets", []):
            if isinstance(ds, dict):
                lines.append(f"- {ds.get('name', 'N/A')}: {ds.get('source', '')} @ {ds.get('frequency', '')}")
    lines.append("")

    lines.append("## 5. Feature Set")
    features = outputs.get("features", {})
    if isinstance(features, dict):
        for f in features.get("features", []):
            if isinstance(f, dict):
                lines.append(f"- **{f.get('name', 'N/A')}** [{f.get('category', '')}]: {f.get('hypothesis', '')}")
    lines.append("")

    # 6. Backtest Design
    lines.append("## 6. Backtest Design")
    bt_design = outputs.get("backtest_design", {})
    if isinstance(bt_design, dict):
        config = bt_design.get("backtest_config", {})
        if isinstance(config, dict):
            split = config.get("data_split", {})
            lines.append(f"Train/Val/Test: {split.get('train_pct', 0.5)}/{split.get('validation_pct', 0.25)}/{split.get('test_pct', 0.25)}")
            cost = config.get("cost_model", {})
            lines.append(f"Costs: {cost.get('commission_bps', 10)}bps commission + {cost.get('slippage_bps', 5)}bps slippage")
    lines.append("")

    # 7. Risk Controls
    lines.append("## 7. Risk Controls")
    risk = outputs.get("risk_review", {})
    if isinstance(risk, dict):
        ra = risk.get("risk_assessment", {})
        lines.append(f"**Overall Risk:** {ra.get('overall_risk_rating', 'N/A')}")
        controls = risk.get("risk_controls", {})
        if isinstance(controls, dict):
            lines.append(f"Daily Loss Limit: {controls.get('daily_loss_limit_pct', 'N/A')}%")
            lines.append(f"Max Leverage: {controls.get('max_leverage', 'N/A')}")
    lines.append("")

    # 8. Validation
    lines.append("## 8. Validation Plan")
    validation = outputs.get("validation", {})
    if isinstance(validation, dict):
        verdict = validation.get("verdict", {})
        lines.append(f"**Confidence:** {verdict.get('confidence_in_edge', 'N/A')}")
        lines.append(f"**P(Random):** {verdict.get('probability_random', 'N/A')}")
        lines.append(f"**Recommendation:** {verdict.get('recommendation', 'N/A')}")
    lines.append("")

    # 9. Audit
    lines.append("## 9. Failure Modes (Audit)")
    audit = outputs.get("audit", {})
    if isinstance(audit, dict):
        lines.append(f"**Audit Result:** {audit.get('audit_result', 'N/A')}")
        lines.append(f"**Overall Confidence:** {audit.get('overall_confidence', 'N/A')}")
        for finding in audit.get("findings", []):
            if isinstance(finding, dict):
                sev = finding.get("severity", "")
                lines.append(f"- [{sev.upper()}] {finding.get('finding', '')}")
    lines.append("")

    # 10. Decision
    lines.append("## 10. Decision")
    decision = outputs.get("decision", {})
    if isinstance(decision, dict):
        lines.append(f"**Decision:** {decision.get('decision', 'N/A')}")
        lines.append(f"**Reasoning:** {decision.get('reasoning', 'N/A')}")
        lines.append(f"**Confidence:** {decision.get('confidence_level', 'N/A')}")
    lines.append("")

    # 11. Paper Trading (if advanced)
    pt = outputs.get("paper_trading", {})
    if pt:
        lines.append("## 11. Paper Trading Setup")
        if isinstance(pt, dict):
            grad = pt.get("graduation_criteria", {})
            lines.append(f"Min paper days: {grad.get('min_paper_days', 30)}")
            lines.append(f"Min trades: {grad.get('min_trades', 50)}")
        lines.append("")

    return "\n".join(lines)


def format_metrics_table(metrics: BacktestMetrics) -> str:
    """Format BacktestMetrics as a readable table."""
    rows = [
        ("CAGR", f"{metrics.cagr_pct:.2f}%"),
        ("Annualized Return", f"{metrics.annualized_return_pct:.2f}%"),
        ("Sharpe", f"{metrics.sharpe:.3f}"),
        ("Sortino", f"{metrics.sortino:.3f}"),
        ("Calmar", f"{metrics.calmar:.3f}"),
        ("Max Drawdown", f"{metrics.max_drawdown_pct:.2f}%"),
        ("Max DD Duration", f"{metrics.max_drawdown_duration_days:.0f} days"),
        ("Hit Rate", f"{metrics.hit_rate:.1%}"),
        ("Avg Trade", f"{metrics.avg_trade_return_pct:.4f}%"),
        ("Profit Factor", f"{metrics.profit_factor:.3f}"),
        ("Turnover (annual)", f"{metrics.turnover_annual:.0f}"),
        ("Exposure", f"{metrics.avg_exposure_pct:.1f}%"),
        ("Total Trades", f"{metrics.total_trades}"),
        ("Avg Holding", f"{metrics.avg_holding_period_hours:.1f}h"),
        ("Skewness", f"{metrics.skewness:.3f}"),
        ("Kurtosis", f"{metrics.kurtosis:.3f}"),
        ("Return Before Costs", f"{metrics.return_before_costs_pct:.2f}%"),
        ("Return After Costs", f"{metrics.return_after_costs_pct:.2f}%"),
    ]
    max_label = max(len(r[0]) for r in rows)
    return "\n".join(f"  {label:<{max_label}}  {val}" for label, val in rows)
