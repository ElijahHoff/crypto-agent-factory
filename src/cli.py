"""CLI interface: Rich + Typer for interactive pipeline management."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

app = typer.Typer(
    name="agentfactory",
    help="🏭 Crypto Strategy Agent Factory — R&D pipeline for systematic trading",
    rich_markup_mode="rich",
)
console = Console()


@app.command()
def run(
    strategy: str = typer.Option("unnamed", "--strategy", "-s", help="Strategy name"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Run the full R&D pipeline for a strategy."""
    from src.pipeline import run_pipeline

    console.print(Panel.fit(
        f"[bold green]🏭 Agent Factory Pipeline[/]\nStrategy: [cyan]{strategy}[/]",
        border_style="green",
    ))

    result = run_pipeline(strategy)

    # Display decision
    decision = result.get("agent_outputs", {}).get("decision", {})
    if isinstance(decision, str):
        try:
            decision = json.loads(decision)
        except Exception:
            pass

    d = decision.get("decision", "unknown") if isinstance(decision, dict) else "unknown"
    color = {"advance": "green", "refine": "yellow", "reject": "red"}.get(d, "white")
    console.print(f"\n[bold {color}]Decision: {d.upper()}[/]")

    if verbose and isinstance(decision, dict):
        console.print(f"Reasoning: {decision.get('reasoning', 'N/A')}")

    # Generate report
    from src.utils.reports import generate_experiment_report
    report = generate_experiment_report(result)
    report_path = Path(f"experiments/{strategy}_report.md")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report)
    console.print(f"\n📄 Report saved: [cyan]{report_path}[/]")


@app.command()
def agents() -> None:
    """List all available agents in the factory."""
    from src.agents import AGENT_CLASSES

    table = Table(title="🤖 Agent Factory — Available Agents")
    table.add_column("Name", style="cyan")
    table.add_column("Role", style="green")
    table.add_column("Temperature", style="yellow", justify="right")

    for name, cls in AGENT_CLASSES.items():
        instance = cls()
        table.add_row(name, instance.role, f"{instance.temperature:.1f}")

    console.print(table)


@app.command()
def registry(
    stage: str | None = typer.Option(None, "--stage", help="Filter by stage"),
) -> None:
    """Show experiment registry summary."""
    from src.utils.registry import ExperimentRegistry

    reg = ExperimentRegistry()
    summary = reg.summary()

    console.print(Panel.fit(
        f"[bold]📊 Experiment Registry[/]\n"
        f"Total: [cyan]{summary['total_experiments']}[/]",
        border_style="blue",
    ))

    if summary["by_stage"]:
        table = Table(title="By Stage")
        table.add_column("Stage", style="cyan")
        table.add_column("Count", justify="right")
        for s, c in summary["by_stage"].items():
            table.add_row(s, str(c))
        console.print(table)


@app.command()
def ideate(
    n: int = typer.Option(3, "--n", "-n", help="Number of strategies to generate"),
    strategy_class: str = typer.Option("any", "--class", "-c", help="Strategy class filter"),
) -> None:
    """Generate strategy hypotheses without running the full pipeline."""
    from src.agents import get_agent

    console.print(f"[bold]💡 Generating {n} strategy hypotheses...[/]")
    agent = get_agent("strategy_ideation")
    result = agent.run({
        "stage": "ideation",
        "n_strategies": n,
        "strategy_class": strategy_class,
    })

    if result.structured:
        for i, h in enumerate(result.structured.get("hypotheses", []), 1):
            console.print(Panel(
                f"[bold]{h.get('name', 'N/A')}[/]\n"
                f"Type: [cyan]{h.get('strategy_type', 'N/A')}[/] | "
                f"Timeframe: [yellow]{h.get('timeframe', 'N/A')}[/]\n\n"
                f"[italic]{h.get('idea', 'N/A')}[/]\n\n"
                f"Logic: {h.get('economic_logic', 'N/A')}\n\n"
                f"Edge death: {', '.join(h.get('edge_death_conditions', []))}",
                title=f"Hypothesis #{i}",
                border_style="cyan",
            ))
    else:
        console.print(result.content)


@app.command()
def pipeline_viz() -> None:
    """Show the pipeline architecture as a tree."""
    tree = Tree("🏭 [bold]Agent Factory Pipeline[/]")

    stage_a = tree.add("[cyan]A. Hypothesis Generation[/]")
    stage_a.add("strategy_ideation → Generate hypotheses")
    stage_a.add("market_analyst → Validate market logic")

    stage_b = tree.add("[cyan]B. Formalization[/]")
    stage_b.add("quant_formalization → Entry/exit rules, sizing, risk")

    stage_c = tree.add("[cyan]C. Data & Features[/]")
    stage_c.add("data_engineer → Data spec, quality checks")
    stage_c.add("feature_engineer → Feature design, lag validation")

    stage_d = tree.add("[cyan]D. Backtest Design[/]")
    stage_d.add("backtesting_engineer → Cost model, splits, benchmarks")

    stage_e = tree.add("[cyan]E. Backtest Execution[/]")
    stage_e.add("BacktestEngine → Realistic simulation")
    stage_e.add("RobustnessTester → Stress tests, perturbation")

    stage_f = tree.add("[cyan]F. Review & Validation[/]")
    stage_f.add("risk_manager → Risk assessment, controls")
    stage_f.add("statistician → Anti-overfitting, p-values")
    stage_f.add("auditor → Adversarial red team")

    stage_g = tree.add("[cyan]G. Decision[/]")
    stage_g.add("research_director → REJECT / REFINE / ADVANCE")

    stage_pt = tree.add("[green]Paper Trading (if advanced)[/]")
    stage_pt.add("paper_trading → Live shadow setup, monitoring")

    console.print(tree)


@app.command()
def fetch_data(
    symbol: str = typer.Option("BTC/USDT", "--symbol", "-s"),
    timeframe: str = typer.Option("1h", "--timeframe", "-t"),
    limit: int = typer.Option(500, "--limit", "-l"),
) -> None:
    """Fetch market data and display quality summary."""
    from src.data import MarketDataFetcher

    fetcher = MarketDataFetcher()
    console.print(f"[bold]📈 Fetching {symbol} {timeframe}...[/]")

    df = fetcher.fetch_ohlcv(symbol, timeframe, limit=limit)
    console.print(f"Rows: {len(df)} | Range: {df.index[0]} → {df.index[-1]}")
    console.print(f"Price: {df['close'].iloc[-1]:.2f} | Avg Volume: {df['volume'].mean():.0f}")


if __name__ == "__main__":
    app()
