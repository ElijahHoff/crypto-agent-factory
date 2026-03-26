"""Strategy configuration loader: reads YAML strategy definitions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from loguru import logger

from src.models import (
    BacktestDesign,
    EntryRule,
    ExitRule,
    FormalizedStrategy,
    RiskFramework,
    StrategyHypothesis,
    StrategyType,
    Timeframe,
)


STRATEGY_CONFIG_DIR = Path("config/strategies")


def load_strategy_config(path: str | Path) -> dict[str, Any]:
    """Load a raw YAML strategy config."""
    p = Path(path)
    if not p.exists():
        # Try in default config dir
        p = STRATEGY_CONFIG_DIR / p
        if not p.suffix:
            p = p.with_suffix(".yaml")
    if not p.exists():
        raise FileNotFoundError(f"Strategy config not found: {p}")
    with open(p) as f:
        return yaml.safe_load(f)


def config_to_hypothesis(config: dict[str, Any]) -> StrategyHypothesis:
    """Convert YAML config to StrategyHypothesis model."""
    hyp = config.get("hypothesis", {})
    return StrategyHypothesis(
        name=config["name"],
        idea=hyp.get("idea", ""),
        economic_logic=hyp.get("economic_logic", ""),
        strategy_type=StrategyType(config.get("type", "momentum")),
        timeframe=Timeframe(config.get("timeframe", "1h")),
        universe=config.get("universe", {}).get("exclude", [])
        or [f"top_{config.get('universe', {}).get('n_assets', 20)}"],
        long_logic=str(config.get("entry_rules", {})),
        short_logic=None,
        risk_factors=[],
        edge_death_conditions=hyp.get("edge_death_conditions", []),
    )


def config_to_formalization(config: dict[str, Any]) -> FormalizedStrategy:
    """Convert YAML config to FormalizedStrategy model."""
    entry_cfg = config.get("entry_rules", {})
    exit_cfg = config.get("exit_rules", {})
    risk_cfg = config.get("risk_framework", {})
    sizing_cfg = config.get("position_sizing", {})

    entry_rules = [
        EntryRule(
            condition=f"{k} = {v}",
            description=f"Entry parameter: {k}",
            parameters={k: v},
        )
        for k, v in entry_cfg.items()
    ]

    exit_rules = [
        ExitRule(
            condition=f"{k} = {v}",
            description=f"Exit parameter: {k}",
            parameters={k: v},
        )
        for k, v in exit_cfg.items()
    ]

    risk_framework = RiskFramework(
        max_position_size_pct=sizing_cfg.get("max_position_pct", 10.0),
        max_leverage=risk_cfg.get("max_leverage", 3.0),
        stop_loss_pct=exit_cfg.get("stop_loss_pct") or exit_cfg.get("stop_loss_per_position_pct"),
        max_concurrent_positions=risk_cfg.get("max_concurrent_positions", 10),
        daily_loss_limit_pct=risk_cfg.get("daily_loss_limit_pct", 3.0),
        drawdown_brake_pct=risk_cfg.get("max_drawdown_pct", 15.0),
    )

    return FormalizedStrategy(
        hypothesis_id=config.get("name", "unknown"),
        entry_rules=entry_rules,
        exit_rules=exit_rules,
        position_sizing=f"{sizing_cfg.get('method', 'equal_weight')} — max {sizing_cfg.get('max_position_pct', 10)}%",
        rebalance_logic=f"Every {exit_cfg.get('rebalance_frequency', '24h')}",
        risk_framework=risk_framework,
        parameters=config.get("parameters", {}),
        hyperparameters=config.get("hyperparameters", {}),
        frozen_params=config.get("frozen_params", []),
        pseudocode=_generate_pseudocode(config),
    )


def config_to_backtest_design(config: dict[str, Any]) -> BacktestDesign:
    """Convert YAML config to BacktestDesign model."""
    bt = config.get("backtest", {})
    return BacktestDesign(
        commission_bps=bt.get("commission_bps", 10.0),
        slippage_bps=bt.get("slippage_bps", 5.0),
        funding_bps=bt.get("funding_bps", 1.0),
        walk_forward_windows=bt.get("walk_forward_windows", 5),
        benchmarks=bt.get("benchmarks", ["buy_and_hold_btc"]),
    )


def list_strategy_configs() -> list[Path]:
    """List all YAML strategy configs in the config dir."""
    if not STRATEGY_CONFIG_DIR.exists():
        return []
    return sorted(STRATEGY_CONFIG_DIR.glob("*.yaml"))


def _generate_pseudocode(config: dict[str, Any]) -> str:
    """Auto-generate pseudocode from config."""
    name = config.get("name", "strategy")
    entry = config.get("entry_rules", {})
    exit_r = config.get("exit_rules", {})

    lines = [
        f"# Pseudocode for {name}",
        f"# Type: {config.get('type', 'unknown')}",
        f"# Timeframe: {config.get('timeframe', '1h')}",
        "",
        "for each bar:",
        "    # Update features",
        "    features = compute_features(data, params)",
        "",
        "    # Entry logic",
    ]
    for k, v in entry.items():
        lines.append(f"    # {k}: {v}")

    lines.extend([
        "",
        "    if entry_conditions_met(features):",
        "        size = compute_position_size(risk_params)",
        "        place_order(direction, size)",
        "",
        "    # Exit logic",
    ])
    for k, v in exit_r.items():
        lines.append(f"    # {k}: {v}")

    lines.extend([
        "",
        "    if exit_conditions_met(position, features):",
        "        close_position()",
        "",
        "    # Risk checks",
        "    enforce_drawdown_brakes()",
        "    enforce_daily_loss_limit()",
    ])

    return "\n".join(lines)
