"""
Report Generator v0.5 — Crash-proof markdown reports.

NEVER crashes on None/missing data. Always produces a valid report.
"""

from datetime import datetime
from pathlib import Path
from loguru import logger


def generate_report(experiment: dict, output_dir: str = "experiments") -> str:
    """Generate markdown report. Never crashes — handles all None cases."""
    name = experiment.get("strategy_name", "unknown")
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Safe extraction with fallbacks
    hypothesis = _dict(experiment.get("hypothesis"))
    backtest = _dict(experiment.get("backtest_result"))
    risk_review = _dict(experiment.get("risk_review"))
    stat_validation = _dict(experiment.get("statistical_validation"))
    audit = _dict(experiment.get("audit"))
    decision = _dict(experiment.get("decision"))
    charts = _dict(backtest.get("charts") or experiment.get("charts"))
    config = _dict(backtest.get("config"))
    benchmarks = _dict(backtest.get("benchmarks"))
    walk_forward = _dict(backtest.get("walk_forward"))
    is_data = _dict(backtest.get("in_sample"))
    oos_data = _dict(backtest.get("out_of_sample"))
    signal_stats = _dict(backtest.get("signal_stats"))
    robustness = _dict(backtest.get("robustness"))
    chart_analysis = backtest.get("chart_analysis", "")

    s = []  # sections

    # Header
    verdict = decision.get("decision", "UNKNOWN")
    if isinstance(verdict, str):
        verdict = verdict.upper()
    confidence = decision.get("confidence_level", "N/A")
    emoji = "🟢" if verdict == "ACCEPT" else "🔴" if verdict == "REJECT" else "🟡"
    s.append(f"# Strategy Report: {name}")
    s.append(f"**Generated**: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    s.append(f"**Verdict**: {emoji} **{verdict}** (confidence: {confidence})\n")

    # Executive Summary
    s.append("## Executive Summary")
    s.append(decision.get("reasoning", "_No decision provided — agents may have encountered API errors._") + "\n")

    # Key Metrics
    s.append("## Key Metrics\n")
    s.append("| Metric | In-Sample | Out-of-Sample |")
    s.append("|--------|-----------|---------------|")
    _row(s, "Sharpe Ratio", is_data.get("sharpe"), oos_data.get("sharpe"))
    _row(s, "Total Return", is_data.get("total_return"), oos_data.get("total_return"), pct=True)
    _row(s, "CAGR", is_data.get("cagr"), None, pct=True)
    _row(s, "Max Drawdown", is_data.get("max_drawdown"), oos_data.get("max_drawdown"), pct=True)
    _row(s, "Total Trades", is_data.get("total_trades"), oos_data.get("total_trades"), fmt="d")
    _row(s, "Win Rate", is_data.get("win_rate"), None, pct=True)
    _row(s, "Profit Factor", is_data.get("profit_factor"), None)
    _row(s, "Calmar", is_data.get("calmar"), None)
    _row(s, "Sortino", is_data.get("sortino"), None)
    s.append("")

    if config:
        s.append(f"**Config**: `{config.get('symbol', '?')}` / `{config.get('timeframe', '?')}` / "
                 f"`{config.get('strategy_type', '?')}` / {config.get('bars', '?')} bars")
        s.append(f"**Period**: {config.get('period', 'N/A')}")
    if signal_stats:
        s.append(f"**Signals**: {signal_stats.get('long_bars', 0)} long / "
                 f"{signal_stats.get('short_bars', 0)} short / "
                 f"{signal_stats.get('flat_bars', 0)} flat "
                 f"({signal_stats.get('transitions', 0)} transitions)")
    s.append("")

    # Benchmark Comparison
    if benchmarks:
        s.append("## Benchmark Comparison\n")
        s.append("| Benchmark | Return | Sharpe | Max DD |")
        s.append("|-----------|--------|--------|--------|")
        s.append(f"| **Strategy** | {_fv(is_data.get('total_return'), pct=True)} | "
                 f"{_fv(is_data.get('sharpe'))} | {_fv(is_data.get('max_drawdown'), pct=True)} |")
        for bm_name, bm in benchmarks.items():
            if isinstance(bm, dict):
                s.append(f"| {bm_name.replace('_',' ').title()} | "
                         f"{_fv(bm.get('total_return'), pct=True)} | "
                         f"{_fv(bm.get('sharpe'))} | "
                         f"{_fv(bm.get('max_drawdown'), pct=True)} |")
        bh = benchmarks.get("buy_and_hold", {})
        if isinstance(bh, dict) and bh.get("sharpe") is not None and is_data.get("sharpe") is not None:
            if is_data["sharpe"] > bh["sharpe"]:
                s.append(f"\n✅ Strategy Sharpe ({is_data['sharpe']:.3f}) **beats** Buy & Hold ({bh['sharpe']:.3f})")
            else:
                s.append(f"\n❌ Strategy Sharpe ({is_data['sharpe']:.3f}) **loses to** Buy & Hold ({bh['sharpe']:.3f})")
        s.append("")

    # Walk-Forward
    if walk_forward:
        s.append("## Walk-Forward Analysis\n")
        n_per = walk_forward.get("n_periods", 0)
        pos = walk_forward.get("positive_periods", 0)
        cons = walk_forward.get("consistency_ratio", 0)
        avg_s = walk_forward.get("avg_sharpe", 0)
        std_s = walk_forward.get("sharpe_std", 0)
        s.append(f"**{pos}/{n_per} periods positive** (consistency: {cons:.0%})")
        s.append(f"Average Sharpe: {avg_s:.3f} ± {std_s:.3f}\n")

        subs = walk_forward.get("subperiods", [])
        if subs:
            s.append("| Period | Dates | Sharpe | Return | Max DD | Trades | ✓ |")
            s.append("|--------|-------|--------|--------|--------|--------|---|")
            for sp in subs:
                ok = "✅" if sp.get("passed") else "❌"
                s.append(f"| P{sp.get('period','?')} | {sp.get('dates','')} | "
                         f"{_fv(sp.get('sharpe'))} | {_fv(sp.get('return'), pct=True)} | "
                         f"{_fv(sp.get('max_dd'), pct=True)} | {sp.get('trades',0)} | {ok} |")
        s.append("")

    # Charts
    if charts:
        s.append("## Performance Charts\n")
        for cn, cp in charts.items():
            label = cn.replace("_", " ").title()
            s.append(f"![{label}]({Path(cp).name})\n")

    # Chart Analysis
    if chart_analysis:
        s.append("## Chart Analysis\n```")
        s.append(str(chart_analysis))
        s.append("```\n")

    # Robustness
    s.append("## Robustness Analysis\n")
    score = robustness.get("overall_score", 0)
    passed = robustness.get("tests_passed", 0)
    total = robustness.get("total_tests", 0)
    s.append(f"**Score**: {score:.1%} ({passed}/{total} tests passed)\n")
    details = robustness.get("details", {})
    if details:
        s.append("| Test | ✓ | Details |")
        s.append("|------|---|---------|")
        for tn, td in details.items():
            if isinstance(td, dict):
                ok = "✅" if td.get("passed") else "❌"
                s.append(f"| {tn} | {ok} | {td.get('detail', '')} |")
    s.append("")

    # Hypothesis
    s.append("## Hypothesis\n")
    if isinstance(hypothesis, dict):
        s.append(f"**Title**: {hypothesis.get('title', hypothesis.get('name', 'N/A'))}")
        s.append(f"**Thesis**: {hypothesis.get('thesis', hypothesis.get('description', 'N/A'))}")
    s.append("")

    # Agent Reviews
    s.append("## Agent Reviews\n")
    for label, review in [("Risk Manager", risk_review), ("Statistician", stat_validation), ("Auditor", audit)]:
        if review:
            s.append(f"### {label}")
            v = review.get("verdict", review.get("recommendation", review.get("decision", "N/A")))
            s.append(f"**Verdict**: {v}")
            for k in ["summary", "analysis", "reasoning", "concerns", "key_findings"]:
                val = review.get(k)
                if val:
                    if isinstance(val, list):
                        for item in val:
                            s.append(f"- {item}")
                    else:
                        s.append(str(val))
            s.append("")

    # Decision Details
    s.append("## Final Decision\n")
    for key, label in [("key_risks", "Key Risks"), ("improvements_needed", "Improvements"),
                       ("edge_evidence", "Edge Evidence")]:
        items = decision.get(key, [])
        if items and isinstance(items, list):
            s.append(f"**{label}:**")
            for item in items:
                s.append(f"- {item}")
            s.append("")
    dv = decision.get("dissenting_view")
    if dv:
        s.append(f"**Dissenting View:**\n> {dv}\n")

    # Write
    report = "\n".join(s)
    filepath = output_path / f"{name}_report.md"
    filepath.write_text(report, encoding="utf-8")
    logger.info(f"📄 Report saved: {filepath}")
    return report


def generate_experiment_report(state: dict) -> str:
    """CLI-compatible wrapper. Merges experiment + agent_outputs."""
    experiment = state.get("experiment", {})
    if isinstance(experiment, str):
        experiment = {"strategy_name": experiment}
    agent_outputs = state.get("agent_outputs", {})
    merged = {}
    if isinstance(experiment, dict):
        merged.update(experiment)
    if isinstance(agent_outputs, dict):
        merged.update(agent_outputs)
    return generate_report(merged)


# ─── Helpers ───

def _dict(val):
    """Ensure value is a dict, never None/str."""
    if val is None:
        return {}
    if isinstance(val, str):
        return {"value": val}
    if isinstance(val, dict):
        return val
    return {}


def _row(sections, label, is_val, oos_val=None, pct=False, fmt=".3f"):
    sections.append(f"| {label} | {_fv(is_val, pct=pct, fmt=fmt)} | {_fv(oos_val, pct=pct, fmt=fmt) if oos_val is not None else '—'} |")


def _fv(val, pct=False, fmt=".3f"):
    if val is None:
        return "N/A"
    try:
        v = float(val)
        if pct:
            return f"{v:.2%}"
        if fmt == "d":
            return str(int(v))
        return f"{v:{fmt}}"
    except (ValueError, TypeError):
        return str(val)
