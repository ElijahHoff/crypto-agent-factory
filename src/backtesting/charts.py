"""
Charts v0.5 — Uses correct BacktestMetrics field names.
Builds equity curve from actual backtest returns when available.
"""

import numpy as np
import pandas as pd
from pathlib import Path
from loguru import logger

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.gridspec import GridSpec
    HAS_MPL = True
except ImportError:
    HAS_MPL = False


def generate_report_charts(prices, signals, backtest_result, strategy_name,
                           benchmarks=None, walk_forward=None,
                           output_dir="experiments"):
    if not HAS_MPL:
        return {}
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    charts = {}
    try:
        p = _combined(prices, signals, backtest_result, strategy_name,
                      benchmarks, walk_forward, output_path)
        charts["combined"] = str(p)
        p2 = _signals_chart(prices, signals, strategy_name, output_path)
        charts["signals"] = str(p2)
    except Exception as e:
        logger.error(f"Chart generation failed: {e}")
    return charts


def generate_chart_description(bt_result, benchmarks, wf_result, signals):
    """Text description of charts for AI agents."""
    lines = ["=== CHART ANALYSIS ==="]
    total = len(signals)
    n_long = int((signals == 1).sum())
    n_short = int((signals == -1).sum())
    n_flat = int((signals == 0).sum())
    transitions = int((signals != signals.shift(1)).sum())
    lines.append(f"\nSignals: {n_long} long ({n_long/total:.1%}), "
                 f"{n_short} short ({n_short/total:.1%}), {n_flat} flat ({n_flat/total:.1%})")
    lines.append(f"Transitions: {transitions}")

    is_r = bt_result.get("in_sample") if bt_result else None
    if is_r:
        sharpe = getattr(is_r, "sharpe", 0)
        ret = getattr(is_r, "return_after_costs_pct", 0)
        dd = getattr(is_r, "max_drawdown_pct", 0)
        lines.append(f"\nStrategy: Sharpe={sharpe:.3f}, Return={ret:.1f}%, MaxDD={dd:.1f}%")

    if benchmarks:
        bh = benchmarks.get("buy_and_hold")
        if bh:
            lines.append(f"Buy&Hold: Sharpe={bh.sharpe:.3f}, Return={bh.total_return:.2%}, MaxDD={bh.max_drawdown:.2%}")
            if is_r:
                if getattr(is_r, "sharpe", 0) > bh.sharpe:
                    lines.append("✅ Strategy beats Buy&Hold")
                else:
                    lines.append("❌ Strategy LOSES to Buy&Hold")

    if wf_result:
        lines.append(f"\n{wf_result.summary_text}")

    lines.append("=== END ===")
    return "\n".join(lines)


def _combined(prices, signals, bt_result, name, benchmarks, walk_forward, out):
    has_wf = walk_forward and walk_forward.periods
    n_panels = 5 if has_wf else 4
    ratios = [2, 1.5, 1, 1, 1.2][:n_panels]
    fig = plt.figure(figsize=(16, 3.5 * n_panels))
    gs = GridSpec(n_panels, 1, height_ratios=ratios, hspace=0.35)

    close = prices["close"]
    is_r = bt_result.get("in_sample") if bt_result else None
    oos_r = bt_result.get("out_of_sample") if bt_result else None

    # Build equity from price returns × signals (actual strategy equity)
    returns = close.pct_change().fillna(0)
    strat_returns = returns * signals.shift(1).fillna(0)
    # Rough cost deduction: ~17bps round-trip
    trades = (signals != signals.shift(1)).astype(float)
    strat_returns = strat_returns - trades * 0.0017
    equity = (1 + strat_returns).cumprod().values
    bh_equity = (close.values / close.values[0])

    # Panel 1: Price + Signals
    ax1 = fig.add_subplot(gs[0])
    ax1.plot(close.index, close.values, color="#2196F3", linewidth=0.8, label="Price")
    long_mask = signals == 1
    short_mask = signals == -1
    if long_mask.any():
        ax1.fill_between(close.index, close.min(), close.max(),
                         where=long_mask, alpha=0.08, color="green", label="Long")
    if short_mask.any():
        ax1.fill_between(close.index, close.min(), close.max(),
                         where=short_mask, alpha=0.08, color="red", label="Short")
    ax1.set_title(f"{name} — Price & Signals", fontsize=14, fontweight="bold")
    ax1.legend(loc="upper left", fontsize=9)
    ax1.set_ylabel("Price (USDT)")
    ax1.grid(True, alpha=0.3)
    _fmt_dates(ax1)

    # Panel 2: Equity vs Benchmark
    ax2 = fig.add_subplot(gs[1])
    is_sharpe = getattr(is_r, "sharpe", 0) if is_r else 0
    ax2.plot(range(len(equity)), equity, color="#4CAF50", linewidth=1.2,
             label=f"Strategy (Sharpe={is_sharpe:.2f})")
    bh_sharpe = benchmarks.get("buy_and_hold").sharpe if benchmarks and benchmarks.get("buy_and_hold") else 0
    ax2.plot(range(len(bh_equity)), bh_equity, color="#9E9E9E", linewidth=1,
             linestyle="--", label=f"Buy&Hold (Sharpe={bh_sharpe:.2f})")
    ax2.axhline(y=1.0, color="black", linewidth=0.5, alpha=0.3)
    ax2.set_title("Equity Curve vs Benchmark", fontsize=12)
    ax2.legend(loc="upper left", fontsize=9)
    ax2.set_ylabel("Equity")
    ax2.grid(True, alpha=0.3)

    # Panel 3: Drawdown
    ax3 = fig.add_subplot(gs[2])
    peak = np.maximum.accumulate(equity)
    dd = (equity - peak) / np.where(peak > 0, peak, 1) * 100
    ax3.fill_between(range(len(dd)), dd, 0, color="#F44336", alpha=0.4)
    ax3.set_title("Drawdown", fontsize=12)
    ax3.set_ylabel("Drawdown %")
    if dd.min() < 0:
        ax3.set_ylim(top=0)
    ax3.grid(True, alpha=0.3)

    # Panel 4: Rolling Sharpe
    ax4 = fig.add_subplot(gs[3])
    if len(strat_returns) > 168:
        roll = strat_returns.rolling(168).mean() / strat_returns.rolling(168).std() * np.sqrt(8760)
        ax4.plot(roll.values, color="#9C27B0", linewidth=0.8, label="Rolling Sharpe (7d)")
        ax4.axhline(y=0, color="gray", linestyle="--", alpha=0.5)
        ax4.axhline(y=1, color="green", linestyle=":", alpha=0.3)
        ax4.axhline(y=-1, color="red", linestyle=":", alpha=0.3)
        ax4.legend(loc="upper left", fontsize=8)
    ax4.set_title("Rolling Sharpe (7-day window)", fontsize=12)
    ax4.set_ylabel("Sharpe")
    ax4.grid(True, alpha=0.3)

    # Panel 5: Walk-Forward
    if has_wf and n_panels == 5:
        ax5 = fig.add_subplot(gs[4])
        wf_sharpes = [p.sharpe for p in walk_forward.periods]
        colors = ["#4CAF50" if s > 0 else "#F44336" for s in wf_sharpes]
        ax5.bar(range(len(wf_sharpes)), wf_sharpes, color=colors, alpha=0.7, edgecolor="white")
        labels = [f"P{p.period_num}\n{p.start_date}" for p in walk_forward.periods]
        ax5.set_xticks(range(len(labels)))
        ax5.set_xticklabels(labels, fontsize=7, rotation=45, ha="right")
        ax5.axhline(y=0, color="black", linewidth=0.8)
        ax5.set_title(
            f"Walk-Forward: {walk_forward.positive_periods}/{walk_forward.n_periods} positive "
            f"({walk_forward.consistency_ratio:.0%})", fontsize=12)
        ax5.set_ylabel("Sharpe")
        ax5.grid(True, alpha=0.3, axis="y")

    filepath = out / f"{name}_report_chart.png"
    fig.savefig(filepath, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    logger.info(f"Combined chart saved: {filepath}")
    return filepath


def _signals_chart(prices, signals, name, out):
    fig, ax = plt.subplots(figsize=(14, 5))
    close = prices["close"]
    ax.plot(close.index, close.values, color="#2196F3", linewidth=0.7)
    el = (signals == 1) & (signals.shift(1) != 1)
    es = (signals == -1) & (signals.shift(1) != -1)
    if el.any():
        ax.scatter(close.index[el], close.values[el], marker="^", color="green", s=25, alpha=0.7, label="Long")
    if es.any():
        ax.scatter(close.index[es], close.values[es], marker="v", color="red", s=25, alpha=0.7, label="Short")
    ax.set_title(f"{name} — Signals", fontsize=13, fontweight="bold")
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(True, alpha=0.3)
    _fmt_dates(ax)
    p = out / f"{name}_signals.png"
    fig.savefig(p, dpi=120, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return p


def _fmt_dates(ax):
    try:
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha="right")
    except Exception:
        pass
