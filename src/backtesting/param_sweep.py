"""
Parameter Sweep v0.9 — Grid search over signal parameters.

Takes agent-generated code with configurable params, tests 50+ combos,
picks best on in-sample, validates on out-of-sample.
"""

import re
import numpy as np
import pandas as pd
from itertools import product
from loguru import logger

from src.backtesting.signal_sandbox import SignalSandbox

COST_PER_TRADE = 0.0017
MAX_COMBOS = 60  # cap grid size


def run_parameter_sweep(
    code: str,
    prices: pd.DataFrame,
    param_ranges: dict | None = None,
) -> tuple[pd.Series | None, dict, dict]:
    """
    Grid search over parameter combinations in agent code.

    Args:
        code: Python signal code with configurable parameters
        prices: OHLCV DataFrame
        param_ranges: {param_name: [val1, val2, ...]} or auto-detect

    Returns:
        (best_signals, best_params, sweep_log)
    """
    if not code or len(code) < 30:
        return None, {}, {"error": "no code"}

    # Auto-detect parameters if not provided
    if not param_ranges:
        param_ranges = _extract_params(code)

    if not param_ranges:
        logger.info("No tunable parameters found — running code as-is")
        sandbox = SignalSandbox()
        signals = sandbox.execute(code, prices)
        return signals, {}, {"combos_tested": 1}

    # Generate grid
    combos = _build_grid(param_ranges)
    logger.info(f"Parameter sweep: {len(combos)} combinations from {len(param_ranges)} params")

    # Split data: 70% in-sample, 30% out-of-sample
    split = int(len(prices) * 0.7)
    is_prices = prices.iloc[:split]
    oos_prices = prices.iloc[split:]

    sandbox = SignalSandbox()
    results = []

    for i, params in enumerate(combos):
        # Inject params into code
        modified_code = _inject_params(code, params)

        # Run on in-sample
        signals = sandbox.execute(modified_code, is_prices)
        if signals is None:
            continue

        # Quick Sharpe
        sharpe = _quick_sharpe(is_prices, signals)
        n_trades = int((signals != signals.shift(1)).sum())

        results.append({
            "params": params,
            "is_sharpe": round(sharpe, 3),
            "n_trades": n_trades,
            "signals_is": signals,
            "code": modified_code,
        })

    if not results:
        logger.warning("All parameter combinations failed")
        return None, {}, {"combos_tested": len(combos), "successful": 0}

    # Sort by IS Sharpe
    results.sort(key=lambda x: x["is_sharpe"], reverse=True)
    best = results[0]

    # Validate best on OOS
    oos_signals = sandbox.execute(best["code"], oos_prices)
    oos_sharpe = _quick_sharpe(oos_prices, oos_signals) if oos_signals is not None else -999

    # Run best on full data
    full_signals = sandbox.execute(best["code"], prices)

    sweep_log = {
        "combos_tested": len(combos),
        "successful": len(results),
        "best_is_sharpe": best["is_sharpe"],
        "best_oos_sharpe": round(oos_sharpe, 3),
        "best_params": best["params"],
        "top5": [
            {"params": r["params"], "sharpe": r["is_sharpe"], "trades": r["n_trades"]}
            for r in results[:5]
        ],
        "overfitting_ratio": round(best["is_sharpe"] / oos_sharpe, 2) if oos_sharpe > 0.01 else "N/A",
    }

    logger.info(
        f"Sweep done: {len(results)}/{len(combos)} valid, "
        f"best IS Sharpe={best['is_sharpe']:.3f}, OOS={oos_sharpe:.3f}, "
        f"params={best['params']}"
    )

    return full_signals, best["params"], sweep_log


def _extract_params(code: str) -> dict:
    """Auto-detect tunable parameters from code patterns."""
    params = {}

    # Pattern: PARAM_NAME = value  (UPPERCASE)
    for match in re.finditer(r'([A-Z_]{3,})\s*=\s*(\d+\.?\d*)', code):
        name, val = match.group(1), float(match.group(2))
        if name in ("True", "False", "None"):
            continue
        params[name] = _generate_range(val)

    # Pattern: param_name = value (in function body, lowercase)
    for match in re.finditer(r'(\w+_(?:period|window|length|threshold|mult|lookback|ema|sma))\s*=\s*(\d+\.?\d*)', code):
        name, val = match.group(1), float(match.group(2))
        params[name] = _generate_range(val)

    # Limit to 4 params max (otherwise grid explodes)
    if len(params) > 4:
        # Keep the 4 most likely important
        priority = sorted(params.keys(), key=lambda k: len(params[k]), reverse=True)
        params = {k: params[k] for k in priority[:4]}

    return params


def _generate_range(default: float) -> list:
    """Generate reasonable range around default value."""
    if default == 0:
        return [0]
    if default >= 100:
        # Likely a period in bars
        d = int(default)
        return [max(5, d // 2), d, d * 2]
    if default >= 10:
        d = int(default)
        return [max(3, d - d // 3), d, d + d // 3]
    if default >= 1:
        return [default * 0.5, default, default * 1.5, default * 2]
    # Small float (threshold, multiplier)
    return [default * 0.5, default, default * 1.5, default * 2.5]


def _build_grid(param_ranges: dict) -> list[dict]:
    """Build parameter grid, capped at MAX_COMBOS."""
    names = list(param_ranges.keys())
    values = list(param_ranges.values())

    all_combos = list(product(*values))

    if len(all_combos) > MAX_COMBOS:
        # Random subsample
        rng = np.random.RandomState(42)
        indices = rng.choice(len(all_combos), MAX_COMBOS, replace=False)
        all_combos = [all_combos[i] for i in indices]

    return [dict(zip(names, combo)) for combo in all_combos]


def _inject_params(code: str, params: dict) -> str:
    """Replace parameter values in code."""
    modified = code
    for name, value in params.items():
        # Replace: NAME = old_value → NAME = new_value
        pattern = rf'({name}\s*=\s*)(\d+\.?\d*)'
        replacement = rf'\g<1>{value}'
        modified = re.sub(pattern, replacement, modified, count=1)
    return modified


def _quick_sharpe(prices: pd.DataFrame, signals: pd.Series) -> float:
    if signals is None:
        return -999
    returns = prices["close"].pct_change().fillna(0)
    strat = returns * signals.shift(1).fillna(0)
    trades = (signals != signals.shift(1)).astype(float)
    strat = strat - trades * COST_PER_TRADE
    std = strat.std()
    if std == 0:
        return 0
    return float(strat.mean() / std * np.sqrt(8760))
