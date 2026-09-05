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
    holdout = _dict(backtest.get("holdout"))
    validation = _dict(backtest.get("validation"))
    lookahead = _dict(backtest.get("lookahead_test"))
    true_wf = _dict(backtest.get("true_walk_forward"))
    vol_target = _dict(backtest.get("vol_target"))
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
    s.append("| Metric | Full sample (dev+holdout) | HOLDOUT (never seen by generator) |")
    s.append("|--------|-----------|---------------|")
    _row(s, "Sharpe Ratio", is_data.get("sharpe"), holdout.get("sharpe"))
    _row(s, "Total Return", is_data.get("total_return"), holdout.get("total_return"), pct=True)
    _row(s, "CAGR", is_data.get("cagr"), None, pct=True)
    _row(s, "Max Drawdown", is_data.get("max_drawdown"), holdout.get("max_drawdown"), pct=True)
    _row(s, "Total Trades", is_data.get("total_trades"), holdout.get("total_trades"), fmt="d")
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

    # Statistical validation (v1.0)
    if validation or lookahead or true_wf:
        s.append("## Statistical Validation (holdout)\n")
        if holdout.get("start"):
            s.append(f"Holdout starts **{str(holdout.get('start'))[:10]}**; the LLM loop and parameter sweep never saw it.\n")
        if validation:
            sig = "✅ significant" if validation.get("statistically_significant") else "❌ NOT significant"
            s.append("| Test | Value | Meaning |")
            s.append("|------|-------|---------|")
            s.append(f"| Holdout Sharpe | {_fv(validation.get('holdout_sharpe'))} | {validation.get('holdout_bars', '?')} bars |")
            s.append(f"| Dev Sharpe | {_fv(validation.get('dev_sharpe'))} | what the generator optimised |")
            s.append(f"| Trials run on dev | {validation.get('n_trials', '?')} | LLM attempts + sweep combos |")
            s.append(f"| Noise max on dev after that many trials | {_fv(validation.get('dev_expected_max_sharpe_null'))} | E[max Sharpe] of random strategies |")
            s.append(f"| Dev deflated Sharpe (DSR) | {_fv(validation.get('dev_dsr'))} | P(dev edge is not the search artefact); need ≥ 0.95 |")
            s.append(f"| Holdout PSR | {_fv(validation.get('psr'))} | P(true holdout Sharpe > 0); need ≥ 0.95 |")
            s.append(f"| Holdout DSR across batch | {_fv(validation.get('holdout_dsr_batch'))} | deflated for {validation.get('n_experiments_sharing_holdout', '?')} experiments sharing this holdout |")
            ci = validation.get("bootstrap_ci") or [None, None]
            s.append(f"| Bootstrap 95% CI | [{_fv(ci[0])}, {_fv(ci[1])}] | block bootstrap, 24h blocks |")
            s.append(f"| Permutation p-value | {_fv(validation.get('permutation_p'))} | share of shuffled signals doing as well |")
            s.append(f"| Min track record | {_fv(validation.get('min_track_record_bars'), fmt='.0f')} bars | to be 95% sure Sharpe > 0 |")
            s.append(f"\n**Verdict**: {sig}. {validation.get('note', '')}\n")
        if lookahead:
            ok = "✅ passed" if lookahead.get("passed") else "❌ FAILED"
            s.append(f"**Look-ahead truncation test**: {ok} — {lookahead.get('detail', '')}\n")
        if true_wf and true_wf.get("n_folds"):
            s.append(f"**True walk-forward** (params re-selected per fold): OOS Sharpe {_fv(true_wf.get('oos_sharpe'))}, "
                     f"mean IS {_fv(true_wf.get('mean_is_sharpe'))}, WFE {_fv(true_wf.get('wf_efficiency'), fmt='.2f')} "
                     f"(need ≥ 0.5), {true_wf.get('positive_folds')}/{true_wf.get('n_folds')} folds positive, "
                     f"param stability {_fv(true_wf.get('param_stability'), pct=True)}\n")
            folds = true_wf.get("folds") or []
            if folds:
                s.append("| Fold | Train | Test | IS Sharpe | OOS Sharpe | OOS Return | Trades | Params |")
                s.append("|------|-------|------|-----------|------------|------------|--------|--------|")
                for f in folds:
                    s.append(f"| {f.get('fold')} | {f.get('train_start')}→{f.get('train_end')} | "
                             f"{f.get('test_start')}→{f.get('test_end')} | {_fv(f.get('is_sharpe'))} | "
                             f"{_fv(f.get('oos_sharpe'))} | {_fv(f.get('oos_return'), pct=True)} | "
                             f"{f.get('oos_trades')} | `{f.get('params')}` |")
                s.append("")
        if vol_target:
            s.append(f"**Vol-targeting overlay (30% ann.)**: holdout Sharpe {_fv(vol_target.get('holdout_sharpe'))} "
                     f"vs raw {_fv(vol_target.get('raw_holdout_sharpe'))}; max DD "
                     f"{_fv(vol_target.get('holdout_max_dd'), fmt='.1f')}% vs {_fv(vol_target.get('raw_holdout_max_dd'), fmt='.1f')}%\n")

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
        s.append("## Sub-period Analysis (fixed signal, 8 chunks)\n")
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

    # ─── Multi-Asset Portfolio ───
    multi = _dict(backtest.get("multi_asset"))
    if multi and multi.get("portfolios"):
        s.append("## Multi-Asset Portfolio\n")
        s.append(f"**Universe**: {', '.join(multi.get('universe', []))} ({multi.get('n_assets', 0)} assets)")
        s.append(f"**Lookback**: {multi.get('lookback_days', 0)} days\n")

        # Per-asset results
        ar = multi.get("asset_results", {})
        if ar:
            s.append("### Per-Asset Results\n")
            s.append("| Asset | Sharpe | Return | Max DD | Trades |")
            s.append("|-------|--------|--------|--------|--------|")
            for sym, data in ar.items():
                s.append(f"| {sym} | {_fv(data.get('sharpe'))} | "
                         f"{_fv(data.get('total_return'), pct=True)} | "
                         f"{_fv(data.get('max_drawdown'), pct=True)} | "
                         f"{data.get('n_trades', 0)} |")
            s.append("")

        # Portfolio methods
        ports = multi.get("portfolios", {})
        if ports:
            s.append("### Portfolio Methods\n")
            s.append("| Method | Sharpe | Return | Max DD | CAGR | Calmar |")
            s.append("|--------|--------|--------|--------|------|--------|")
            for method, data in ports.items():
                s.append(f"| {method.replace('_', ' ').title()} | "
                         f"{_fv(data.get('sharpe'))} | "
                         f"{_fv(data.get('total_return'), pct=True)} | "
                         f"{_fv(data.get('max_drawdown'), pct=True)} | "
                         f"{_fv(data.get('cagr'), pct=True)} | "
                         f"{_fv(data.get('calmar'))} |")
            s.append("")

        # Best portfolio
        best = multi.get("best_portfolio", {})
        if best:
            s.append(f"**Best**: {best.get('method', '?').replace('_', ' ').title()} "
                     f"(Sharpe={best.get('sharpe', 0):.3f}, Return={best.get('total_return', 0):.2%})")
            s.append("")

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
