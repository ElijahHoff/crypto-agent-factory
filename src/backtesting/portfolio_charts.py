"""
Portfolio Charts v0.8 — Multi-asset visualization.

Generates: per-asset equity, portfolio comparison, correlation heatmap, weight allocation.
"""

import numpy as np
import pandas as pd
from pathlib import Path
from loguru import logger

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.gridspec import GridSpec
    HAS_MPL = True
except ImportError:
    HAS_MPL = False


def generate_portfolio_charts(
    multi_result: dict,
    strategy_name: str,
    output_dir: str = "experiments",
) -> dict:
    """Generate multi-asset portfolio charts."""
    if not HAS_MPL:
        return {}

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    charts = {}

    try:
        p = _portfolio_overview(multi_result, strategy_name, out)
        charts["portfolio_overview"] = str(p)
    except Exception as e:
        logger.warning(f"Portfolio chart failed: {e}")

    return charts


def _portfolio_overview(result: dict, name: str, out: Path) -> Path:
    """4-panel portfolio overview."""
    fig = plt.figure(figsize=(16, 14))
    gs = GridSpec(2, 2, hspace=0.3, wspace=0.3)

    portfolios = result.get("portfolios", {})
    asset_results = result.get("asset_results", {})
    corr = result.get("correlation_matrix", {})

    # Panel 1: Per-asset Sharpe bars
    ax1 = fig.add_subplot(gs[0, 0])
    if asset_results:
        symbols = list(asset_results.keys())
        sharpes = [asset_results[s]["sharpe"] for s in symbols]
        colors = ["#4CAF50" if s > 0 else "#F44336" for s in sharpes]
        short_names = [s.replace("/USDT", "") for s in symbols]
        ax1.bar(short_names, sharpes, color=colors, alpha=0.7, edgecolor="white")
        ax1.axhline(y=0, color="black", linewidth=0.8)
        ax1.set_title("Per-Asset Sharpe Ratio", fontsize=13, fontweight="bold")
        ax1.set_ylabel("Sharpe")
        ax1.grid(True, alpha=0.3, axis="y")

    # Panel 2: Portfolio comparison
    ax2 = fig.add_subplot(gs[0, 1])
    if portfolios:
        methods = list(portfolios.keys())
        p_sharpes = [portfolios[m]["sharpe"] for m in methods]
        p_returns = [portfolios[m]["total_return"] for m in methods]
        x = range(len(methods))
        w = 0.35
        bars1 = ax2.bar([i - w/2 for i in x], p_sharpes, w, label="Sharpe", color="#2196F3", alpha=0.7)
        ax2_twin = ax2.twinx()
        bars2 = ax2_twin.bar([i + w/2 for i in x], [r * 100 for r in p_returns], w,
                             label="Return %", color="#FF9800", alpha=0.7)
        ax2.set_xticks(list(x))
        ax2.set_xticklabels([m.replace("_", "\n") for m in methods], fontsize=8)
        ax2.set_ylabel("Sharpe", color="#2196F3")
        ax2_twin.set_ylabel("Return %", color="#FF9800")
        ax2.set_title("Portfolio Methods Comparison", fontsize=13, fontweight="bold")
        ax2.axhline(y=0, color="black", linewidth=0.5)
        ax2.grid(True, alpha=0.3, axis="y")

    # Panel 3: Correlation heatmap
    ax3 = fig.add_subplot(gs[1, 0])
    if corr and len(corr) > 1:
        corr_df = pd.DataFrame(corr)
        short_cols = [c.replace("/USDT", "") for c in corr_df.columns]
        corr_df.columns = short_cols
        corr_df.index = short_cols
        im = ax3.imshow(corr_df.values, cmap="RdYlGn_r", vmin=-1, vmax=1)
        ax3.set_xticks(range(len(short_cols)))
        ax3.set_yticks(range(len(short_cols)))
        ax3.set_xticklabels(short_cols, fontsize=9)
        ax3.set_yticklabels(short_cols, fontsize=9)
        # Add values
        for i in range(len(short_cols)):
            for j in range(len(short_cols)):
                ax3.text(j, i, f"{corr_df.values[i,j]:.2f}", ha="center", va="center", fontsize=9)
        fig.colorbar(im, ax=ax3, shrink=0.8)
        ax3.set_title("Strategy Return Correlations", fontsize=13, fontweight="bold")

    # Panel 4: Best portfolio weights
    ax4 = fig.add_subplot(gs[1, 1])
    best_method = result.get("best_portfolio", {}).get("method", "equal_weight")
    best_p = portfolios.get(best_method, {})
    weights = best_p.get("weights", {})
    if weights:
        labels = [k.replace("/USDT", "") for k in weights.keys()]
        sizes = list(weights.values())
        colors_pie = ["#2196F3", "#4CAF50", "#FF9800", "#9C27B0", "#F44336"][:len(labels)]
        wedges, texts, autotexts = ax4.pie(
            sizes, labels=labels, autopct="%1.0f%%",
            colors=colors_pie, startangle=90,
        )
        for t in autotexts:
            t.set_fontsize(10)
        best_sharpe = best_p.get("sharpe", 0)
        best_ret = best_p.get("total_return", 0)
        ax4.set_title(
            f"Best: {best_method.replace('_', ' ').title()}\n"
            f"Sharpe={best_sharpe:.3f}, Return={best_ret:.2%}",
            fontsize=12, fontweight="bold"
        )

    fig.suptitle(f"{name} — Multi-Asset Portfolio", fontsize=16, fontweight="bold", y=1.02)

    filepath = out / f"{name}_portfolio_chart.png"
    fig.savefig(filepath, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    logger.info(f"Portfolio chart saved: {filepath}")
    return filepath
