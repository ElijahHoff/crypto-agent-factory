"""
Iterative Signal Generator v0.9 — Memory + Multi-TF + Parameter Sweep.

Flow:
1. Load memory of past experiments
2. Analyze market (1h) + trend (4h)
3. Claude writes signal code with full context
4. Parameter sweep (50 combos) on best code
5. Apply 4h trend filter to final signals
6. Save result to memory
"""

import json
import numpy as np
import pandas as pd
from loguru import logger

from src.backtesting.signal_sandbox import SignalSandbox
from src.backtesting.experiment_memory import get_memory_context, save_experiment
from src.backtesting.param_sweep import run_parameter_sweep
from src.config import settings

try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False

MAX_ITERATIONS = 5
SHARPE_THRESHOLD = 0.0


def analyze_market(prices: pd.DataFrame) -> dict:
    close = prices["close"]
    total_return = close.iloc[-1] / close.iloc[0] - 1
    returns = close.pct_change().dropna()
    vol_ann = returns.std() * np.sqrt(8760)
    max_dd = ((close / close.cummax()) - 1).min()
    half = len(close) // 2
    first_ret = close.iloc[half] / close.iloc[0] - 1
    second_ret = close.iloc[-1] / close.iloc[half] - 1
    sma50 = close.rolling(50).mean()
    pct_above = (close > sma50).sum() / len(close)
    regime = "bear" if total_return < -0.1 else "bull" if total_return > 0.1 else "sideways"
    return {
        "total_return": f"{total_return:.1%}", "regime": regime,
        "volatility": f"{vol_ann:.1%}", "max_drawdown": f"{max_dd:.1%}",
        "bars": len(close), "first_half": f"{first_ret:.1%}",
        "second_half": f"{second_ret:.1%}", "pct_above_sma50": f"{pct_above:.0%}",
        "price_range": f"${close.min():,.0f}-${close.max():,.0f}",
        "current": f"${close.iloc[-1]:,.0f}",
    }


SYSTEM_PROMPT = """You write Python signal generation functions for crypto trading.
Output ONLY valid JSON: {"reasoning": "...", "signal_code": "def generate_signals(prices):\\n    ..."}

RULES:
- def generate_signals(prices) → pd.Series of +1/-1/0, same length as prices
- prices has: open, high, low, close, volume (DatetimeIndex)
- Use numpy, pandas only. Handle NaN with .fillna()
- Generate 50-500 trades. Use CONFIGURABLE parameters (e.g. fast_period = 12)
- NEVER use future data. No .shift(-1).

WHAT WORKS: EMA crossovers with ADX filter, Donchian breakout + ATR stop,
RSI divergence + volume confirmation, multi-period momentum (ROC 6h + 24h + 168h),
Bollinger squeeze breakout, VWAP reversion with volume surge.

KEY: In bearish markets → short-biased or trend-following. In bullish → momentum/breakout.
In sideways → mean reversion or range strategies. ADAPT to regime.
Use at least 2-3 combined indicators. Always include a volatility or volume filter.
Make parameters TUNABLE (use variable names, not magic numbers).
"""


def generate_signals_iterative(
    prices: pd.DataFrame,
    strategy_name: str,
    quant_spec: dict | None = None,
    max_iterations: int = MAX_ITERATIONS,
    trend_context: dict | None = None,
) -> tuple[pd.Series | None, str, dict]:
    if not HAS_ANTHROPIC:
        return None, "", {}

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    sandbox = SignalSandbox()
    market = analyze_market(prices)
    memory = get_memory_context(limit=10)

    logger.info(f"Market: {market['regime']}, return={market['total_return']}")

    log = {"iterations": [], "final_source": "none"}
    best_signals = None
    best_sharpe = -999
    best_code = ""

    for attempt in range(max_iterations):
        logger.info(f"🧠 Signal iteration {attempt + 1}/{max_iterations}...")

        prompt = _build_prompt(
            strategy_name, market, memory, trend_context,
            quant_spec, best_code, log["iterations"][-1] if log["iterations"] else None,
            attempt,
        )

        try:
            response = client.messages.create(
                model=settings.anthropic_model,
                max_tokens=4096, temperature=0.7 + attempt * 0.05,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text
        except Exception as e:
            logger.warning(f"Claude failed: {e}")
            break

        code = _extract_code(text)
        if not code:
            log["iterations"].append({"attempt": attempt + 1, "error": "no code"})
            continue

        # Execute
        signals = sandbox.execute(code, prices)
        if signals is None:
            log["iterations"].append({"attempt": attempt + 1, "error": "execution failed"})
            continue

        sharpe, total_ret, n_trades = _evaluate(prices, signals)

        iter_result = {
            "attempt": attempt + 1, "sharpe": round(sharpe, 3),
            "total_return": f"{total_ret:.2%}", "n_trades": n_trades,
        }
        log["iterations"].append(iter_result)
        logger.info(f"  Attempt {attempt+1}: Sharpe={sharpe:.3f}, Return={total_ret:.2%}, Trades={n_trades}")

        if sharpe > best_sharpe:
            best_sharpe = sharpe
            best_signals = signals
            best_code = code

        if sharpe > SHARPE_THRESHOLD:
            logger.info(f"✅ Positive Sharpe! Running parameter sweep...")
            break

    # Parameter sweep on best code
    if best_code and best_sharpe > -5:
        try:
            swept_signals, swept_params, sweep_log = run_parameter_sweep(best_code, prices)
            if swept_signals is not None:
                swept_sharpe, swept_ret, swept_trades = _evaluate(prices, swept_signals)
                logger.info(f"  Sweep best: Sharpe={swept_sharpe:.3f} (was {best_sharpe:.3f}), params={swept_params}")
                if swept_sharpe > best_sharpe:
                    best_signals = swept_signals
                    best_sharpe = swept_sharpe
                    best_code = f"# Swept params: {swept_params}\n{best_code}"
                log["sweep"] = sweep_log
        except Exception as e:
            logger.warning(f"Sweep failed: {e}")

    log["best_sharpe"] = round(best_sharpe, 3)
    log["total_attempts"] = len(log["iterations"])
    log["final_source"] = "agent_iterated" if best_signals is not None else "none"

    return best_signals, best_code, log


def _build_prompt(name, market, memory, trend_ctx, spec, prev_code, prev_result, attempt):
    parts = [f'Write generate_signals() for: "{name}"']
    parts.append(f"\nMARKET: {market['regime']}, return={market['total_return']}, "
                 f"vol={market['volatility']}, price={market['current']}, "
                 f"range={market['price_range']}, first_half={market['first_half']}, "
                 f"second_half={market['second_half']}")

    if trend_ctx:
        parts.append(f"\n4H TREND: {trend_ctx.get('note', 'unknown')}")

    if memory:
        parts.append(f"\n{memory}")

    if spec and isinstance(spec, dict):
        for k in ["entry_rules", "exit_rules", "indicators"]:
            if k in spec:
                parts.append(f"\nHint ({k}): {json.dumps(spec[k], default=str)[:300]}")

    if prev_result and attempt > 0:
        parts.append(f"\nPREVIOUS ATTEMPT: Sharpe={prev_result.get('sharpe', 'N/A')}, "
                     f"Return={prev_result.get('total_return', 'N/A')}, "
                     f"Trades={prev_result.get('n_trades', 'N/A')}")
        if prev_result.get("sharpe", 0) < 0:
            parts.append("⚠️ NEGATIVE SHARPE — make MEANINGFUL changes! Different indicators, logic, or direction.")
        if prev_result.get("n_trades", 0) < 50:
            parts.append("⚠️ Too few trades — loosen conditions!")
        if prev_result.get("n_trades", 0) > 1000:
            parts.append("⚠️ Too many trades — costs eating returns! Tighten filters.")

    parts.append(f"\nUse CONFIGURABLE parameters (fast_period=12 not hardcoded 12).")
    parts.append(f"Attempt {attempt+1}/{MAX_ITERATIONS}. {'Be creative, try something NEW.' if attempt > 1 else ''}")
    return "\n".join(parts)


def _extract_code(text):
    try:
        clean = text.strip()
        if clean.startswith("```"):
            clean = clean.split("```")[1]
            if clean.startswith("json"): clean = clean[4:]
        if clean.endswith("```"): clean = clean[:-3]
        data = json.loads(clean)
        code = data.get("signal_code", "")
        if code and "def " in code:
            return code.replace("\\n", "\n").replace("\\t", "    ")
    except json.JSONDecodeError:
        pass
    if "def generate_signals" in text:
        start = text.find("def generate_signals")
        block = text.rfind("```", 0, start)
        if block >= 0:
            code_start = text.find("\n", block) + 1
            end = text.find("```", start)
            if end > 0:
                return text[code_start:end].strip()
        lines = text[start:].split("\n")
        func = [lines[0]]
        for line in lines[1:]:
            if line.strip() == "" or line[0:1] in (" ", "\t"):
                func.append(line)
            else:
                break
        return "\n".join(func)
    return None


def _evaluate(prices, signals):
    returns = prices["close"].pct_change().fillna(0)
    strat = returns * signals.shift(1).fillna(0)
    trades = (signals != signals.shift(1)).astype(float)
    strat = strat - trades * 0.0017
    std = strat.std()
    sharpe = float(strat.mean() / std * np.sqrt(8760)) if std > 0 else 0
    total_ret = float((1 + strat).prod() - 1)
    return sharpe, total_ret, int(trades.sum())
