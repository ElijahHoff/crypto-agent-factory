"""
Report Generator v0.4 — Comprehensive markdown reports.

Includes: executive summary, key metrics table, benchmark comparison,
walk-forward subperiod table, robustness details, charts, agent reviews.
"""

from datetime import datetime
from pathlib import Path
from loguru import logger


def generate_report(experiment: dict, output_dir: str = "experiments") -> str:
    """Generate comprehensive markdown report from pipeline results."""
    name = experiment.get("strategy_name", "unknown")
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    hypothesis = experiment.get("hypothesis", {})
    quant_spec = experiment.get("quant_formalization", {})
    backtest = experiment.get("backtest_result", {})
    robustness = experiment.get("robustness", backtest.get("robustness", {}))
    risk_review = experiment.get("risk_review", {})
    stat_validation = experiment.get("statistical_validation", {})
    audit = experiment.get("audit", {})
    decision = experiment.get("decision", {})
    if isinstance(decision, str):
        decision = {"decision": decision, "reasoning": decision}
    if decision is None:
        decision = {}
    charts = backtest.get("charts", experiment.get("charts", {}))
    config = backtest.get("config", {})
    benchmarks = backtest.get("benchmarks", {})
    walk_forward = backtest.get("walk_forward", {})
    multi_asset = backtest.get("multi_asset", {})
    chart_analysis = backtest.get("chart_analysis", "")

    sections = []

    # ─── Header ───
    verdict = decision.get("decision", "N/A").upper()
    confidence = decision.get("confidence_level", "N/A")
    emoji = "🟢" if verdict == "ACCEPT" else "🟡" if verdict == "CONDITIONAL" else "🔴"
    sections.append(f"# Strategy Report: {name}")
    sections.append(f"**Generated**: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    sections.append(f"**Verdict**: {emoji} **{verdict}** (confidence: {confidence})")
    sections.append("")

    # ─── Executive Summary ───
    sections.append("## Executive Summary")
    if decision.get("reasoning"):
        sections.append(decision["reasoning"])
    sections.append("")

    # ─── Key Metrics Table ───
    sections.append("## Key Metrics")
    is_data = backtest.get("in_sample") or {}
    oos_data = backtest.get("out_of_sample") or {}
    signal_stats = backtest.get("signal_stats", {})

    sections.append("| Metric | In-Sample | Out-of-Sample |")
    sections.append("|--------|-----------|---------------|")
    _row(sections, "Sharpe Ratio", is_data.get("sharpe"), _oos(oos_data, "sharpe"))
    _row(sections, "Total Return", is_data.get("total_return"), _oos(oos_data, "total_return"), fmt=".2%")
    _row(sections, "CAGR", is_data.get("cagr"), None, fmt=".2%")
    _row(sections, "Max Drawdown", is_data.get("max_drawdown"), _oos(oos_data, "max_drawdown"), fmt=".2%")
    _row(sections, "Total Trades", is_data.get("total_trades"), _oos(oos_data, "total_trades"), fmt="d")
    _row(sections, "Win Rate", is_data.get("win_rate"), None, fmt=".1%")
    _row(sections, "Profit Factor", is_data.get("profit_factor"), None)
    _row(sections, "Calmar Ratio", is_data.get("calmar"), None)
    _row(sections, "Volatility (ann.)", is_data.get("volatility"), None, fmt=".2%")
    sections.append("")

    # Config
    if config:
        sections.append("**Config:**")
        sections.append(f"- Symbol: `{config.get('symbol', 'N/A')}`")
        sections.append(f"- Timeframe: `{config.get('timeframe', 'N/A')}`")
        sections.append(f"- Strategy Type: `{config.get('strategy_type', 'N/A')}`")
        sections.append(f"- Bars: {config.get('bars', 'N/A')}")
        sections.append(f"- Period: {config.get('period', 'N/A')}")
    if signal_stats:
        long_b = signal_stats.get("long_bars", 0)
        short_b = signal_stats.get("short_bars", 0)
        flat_b = signal_stats.get("flat_bars", 0)
        trans = signal_stats.get("transitions", 0)
        sections.append(f"- Signals: {long_b} long / {short_b} short / {flat_b} flat ({trans} transitions)")
    sections.append("")

    # ─── Benchmark Comparison ───
    if benchmarks:
        sections.append("## Benchmark Comparison")
        sections.append("| Benchmark | Return | Sharpe | Max DD | Volatility |")
        sections.append("|-----------|--------|--------|--------|------------|")
        # Strategy row first
        s_ret = is_data.get("total_return", 0)
        s_sharpe = is_data.get("sharpe", 0)
        s_dd = is_data.get("max_drawdown", 0)
        s_vol = is_data.get("volatility", 0)
        sections.append(f"| **Strategy** | {_fv(s_ret, '.2%')} | {_fv(s_sharpe)} | {_fv(s_dd, '.2%')} | {_fv(s_vol, '.2%')} |")
        for bm_name, bm_data in benchmarks.items():
            if isinstance(bm_data, dict):
                sections.append(
                    f"| {bm_name.replace('_', ' ').title()} | "
                    f"{_fv(bm_data.get('total_return'), '.2%')} | "
                    f"{_fv(bm_data.get('sharpe'))} | "
                    f"{_fv(bm_data.get('max_drawdown'), '.2%')} | "
                    f"{_fv(bm_data.get('volatility'), '.2%')} |"
                )
        sections.append("")

        # Verdict
        bh = benchmarks.get("buy_and_hold", {})
        if bh:
            bh_sharpe = bh.get("sharpe", 0)
            if s_sharpe > bh_sharpe:
                sections.append(f"✅ Strategy Sharpe ({s_sharpe:.3f}) **beats** Buy & Hold ({bh_sharpe:.3f})")
            else:
                sections.append(f"❌ Strategy Sharpe ({s_sharpe:.3f}) **loses to** Buy & Hold ({bh_sharpe:.3f})")
        sections.append("")

    # ─── Walk-Forward Analysis ───
    if walk_forward:
        sections.append("## Walk-Forward Analysis")
        n_per = walk_forward.get("n_periods", 0)
        pos = walk_forward.get("positive_periods", 0)
        neg = walk_forward.get("negative_periods", 0)
        cons = walk_forward.get("consistency_ratio", 0)
        avg_s = walk_forward.get("avg_sharpe", 0)
        std_s = walk_forward.get("sharpe_std", 0)

        sections.append(f"**{pos}/{n_per} periods positive** (consistency: {cons:.0%})")
        sections.append(f"Average Sharpe: {avg_s:.3f} ± {std_s:.3f}")
        sections.append("")

        subperiods = walk_forward.get("subperiods", [])
        if subperiods:
            sections.append("| Period | Dates | Sharpe | Return | Max DD | Trades | Status |")
            sections.append("|--------|-------|--------|--------|--------|--------|--------|")
            for sp in subperiods:
                status = "✅" if sp.get("passed") else "❌"
                sections.append(
                    f"| P{sp.get('period', '?')} | {sp.get('dates', '')} | "
                    f"{_fv(sp.get('sharpe'))} | {_fv(sp.get('return'), '.2%')} | "
                    f"{_fv(sp.get('max_dd'), '.2%')} | {sp.get('trades', 0)} | {status} |"
                )
        sections.append("")

        # Best/worst
        best = walk_forward.get("best_period", {})
        worst = walk_forward.get("worst_period", {})
        if best:
            sections.append(f"**Best**: P{best.get('period_num', '?')} "
                          f"({best.get('start_date', '')}→{best.get('end_date', '')}) "
                          f"Sharpe={best.get('sharpe', 0):.3f}")
        if worst:
            sections.append(f"**Worst**: P{worst.get('period_num', '?')} "
                          f"({worst.get('start_date', '')}→{worst.get('end_date', '')}) "
                          f"Sharpe={worst.get('sharpe', 0):.3f}")
        sections.append("")

    # ─── Performance Charts ───
    if charts:
        sections.append("## Performance Charts")
        for chart_name, chart_path in charts.items():
            rel = Path(chart_path).name
            label = chart_name.replace("_", " ").title()
            sections.append(f"### {label}")
            sections.append(f"![{label}]({rel})")
            sections.append("")

    # ─── Chart Analysis (text) ───
    if chart_analysis:
        sections.append("## Chart Analysis (Quantitative)")
        sections.append("```")
        sections.append(chart_analysis)
        sections.append("```")
        sections.append("")

    # ─── Robustness ───
    sections.append("## Robustness Analysis")
    if isinstance(robustness, dict):
        score = robustness.get("overall_score", 0)
        passed = robustness.get("tests_passed", 0)
        total = robustness.get("total_tests", 7)
        sections.append(f"**Overall Score**: {score:.1%} ({passed}/{total} tests passed)")
        sections.append("")

        details = robustness.get("details", {})
        if details:
            sections.append("| Test | Result | Details |")
            sections.append("|------|--------|---------|")
            for test_name, test_data in details.items():
                if isinstance(test_data, dict):
                    p_str = "✅" if test_data.get("passed", False) else "❌"
                    detail = test_data.get("detail", test_data.get("message", ""))
                    sections.append(f"| {test_name} | {p_str} | {detail} |")
                else:
                    sections.append(f"| {test_name} | — | {test_data} |")
    sections.append("")

    # ─── Multi-Asset Cross-Validation ───
    if multi_asset:
        sections.append("## Multi-Asset Cross-Validation")
        sections.append("| Symbol | Sharpe | Return | Max DD | Trades |")
        sections.append("|--------|--------|--------|--------|--------|")
        for sym, data in multi_asset.items():
            sections.append(
                f"| {sym} | {_fv(data.get('sharpe'))} | "
                f"{_fv(data.get('total_return'), '.2%')} | "
                f"{_fv(data.get('max_drawdown'), '.2%')} | "
                f"{data.get('total_trades', 0)} |"
            )
        sections.append("")

    # ─── Hypothesis ───
    sections.append("## Hypothesis")
    if isinstance(hypothesis, dict):
        sections.append(f"**Title**: {hypothesis.get('title', hypothesis.get('name', 'N/A'))}")
        sections.append(f"**Thesis**: {hypothesis.get('thesis', hypothesis.get('description', 'N/A'))}")
        sections.append(f"**Edge Source**: {hypothesis.get('edge', hypothesis.get('edge_source', 'N/A'))}")
    elif isinstance(hypothesis, str):
        sections.append(hypothesis)
    sections.append("")

    # ─── Agent Reviews ───
    sections.append("## Agent Reviews")
    if risk_review:
        sections.append("### Risk Manager")
        _add_review(sections, risk_review)
    if stat_validation:
        sections.append("### Statistician")
        _add_review(sections, stat_validation)
    if audit:
        sections.append("### Auditor / Critic")
        _add_review(sections, audit)
    sections.append("")

    # ─── Decision Details ───
    sections.append("## Final Decision")
    if decision:
        for key, label in [("key_risks", "Key Risks"), ("improvements_needed", "Improvements Needed"),
                           ("edge_evidence", "Edge Evidence")]:
            items = decision.get(key, [])
            if items:
                sections.append(f"**{label}:**")
                for item in items:
                    sections.append(f"- {item}")
                sections.append("")
        if decision.get("dissenting_view"):
            sections.append("**Dissenting View:**")
            sections.append(f"> {decision['dissenting_view']}")
            sections.append("")

    # Write
    report_text = "\n".join(sections)
    filepath = output_path / f"{name}_report.md"
    filepath.write_text(report_text, encoding="utf-8")
    logger.info(f"📄 Report saved: {filepath}")
    return str(filepath)


# ─── Helpers ───

def _oos(oos_data, key):
    if oos_data and isinstance(oos_data, dict):
        return oos_data.get(key)
    return None

def _row(sections, label, is_val, oos_val, fmt=".3f"):
    sections.append(f"| {label} | {_fv(is_val, fmt)} | {_fv(oos_val, fmt) if oos_val is not None else '—'} |")

def _fv(val, fmt=".3f"):
    if val is None:
        return "N/A"
    try:
        if fmt == "d":
            return str(int(val))
        return f"{val:{fmt}}"
    except (ValueError, TypeError):
        return str(val)

def _add_review(sections, review):
    if isinstance(review, str):
        sections.append(review)
        return
    verdict = review.get("verdict", review.get("recommendation", review.get("decision", "N/A")))
    sections.append(f"**Verdict**: {verdict}")
    for key in ["summary", "analysis", "reasoning", "key_findings", "concerns"]:
        if key in review:
            val = review[key]
            if isinstance(val, list):
                for item in val:
                    sections.append(f"- {item}")
            elif isinstance(val, str):
                sections.append(val)
    sections.append("")


# Alias for CLI compatibility
def generate_experiment_report(state: dict) -> str:
    experiment = state.get("experiment", {})
    agent_outputs = state.get("agent_outputs", {})
    merged = {**experiment, **agent_outputs}
    return generate_report(merged)
