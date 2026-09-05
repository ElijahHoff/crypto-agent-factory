"""
Iterative Signal Generator v1.0 — honest development / holdout protocol.

What changed vs v0.9.2 (and why):

1. HOLDOUT. The last ``holdout_pct`` of the history is never shown to the
   LLM, never used by the feedback loop and never used by the parameter
   sweep. Before, the LLM was told the full-period return/regime ("bear,
   -37%") and told to short in bear markets: that is look-ahead bias by
   prompt. All selection now happens on the development window only.
2. LOOK-AHEAD TEST. Every candidate is run through the truncation test
   (validation.lookahead_truncation_test). Code that changes its past
   signals when future bars are removed (shift(-1), whole-sample z-scores,
   centered windows, …) is rejected and the LLM is told why.
3. TRIAL COUNTING. Every executed candidate and every sweep combo is a
   trial. The count is returned so the holdout Sharpe can be deflated.
4. DIAGNOSTIC FEEDBACK. Instead of "market is bear, short more" the LLM
   gets turnover, exposure, cost drag and hit rate — things it can fix
   without being told the future.
5. Correct turnover accounting (a long->short flip costs two trades).
"""

import json
import numpy as np
import pandas as pd
from loguru import logger

from src.backtesting.signal_sandbox import SignalSandbox
from src.backtesting.code_extractor import extract_code
from src.backtesting.experiment_memory import get_memory_context
from src.backtesting.param_sweep import run_parameter_sweep
from src.backtesting.validation import (
    strategy_returns, sharpe_ratio, lookahead_truncation_test,
)
from src.config import settings

try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False

MAX_ITERATIONS = 5
SHARPE_THRESHOLD = 0.0
HOLDOUT_PCT = 0.30


def analyze_market(prices: pd.DataFrame) -> dict:
    """Describe the market — call this on the DEVELOPMENT window only."""
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
    # Autocorrelation of daily returns — tells the LLM whether trend or
    # mean-reversion is even plausible without revealing direction.
    daily = close.resample("1D").last().pct_change().dropna()
    ac1 = float(daily.autocorr(1)) if len(daily) > 30 else 0.0
    return {
        "total_return": f"{total_return:.1%}", "regime": regime,
        "volatility": f"{vol_ann:.1%}", "max_drawdown": f"{max_dd:.1%}",
        "bars": len(close), "first_half": f"{first_ret:.1%}",
        "second_half": f"{second_ret:.1%}", "pct_above_sma50": f"{pct_above:.0%}",
        "price_range": f"${close.min():,.0f}-${close.max():,.0f}",
        "current": f"${close.iloc[-1]:,.0f}",
        "daily_autocorr_lag1": f"{ac1:+.3f}",
    }


SYSTEM_PROMPT = """You write Python signal generation functions for crypto trading.

RESPOND WITH ONLY A PYTHON CODE BLOCK. No JSON wrapping. No explanation outside the code block.
Just a single ```python ... ``` block containing the function.

```python
def generate_signals(prices):
    import numpy as np
    import pandas as pd

    close = prices["close"]
    # ... your logic ...

    signals = pd.Series(0, index=prices.index)
    # signals[condition] = 1 or -1
    return signals
```

CRITICAL RULES:
1. Function MUST be named generate_signals with ONE argument: prices
2. prices has columns: open, high, low, close, volume (DatetimeIndex, 1h bars)
3. Return pd.Series of int: +1 (long), -1 (short), 0 (flat), same length as prices
4. Put ALL imports INSIDE the function (import numpy as np, import pandas as pd)
5. Handle NaN with .fillna()
6. Target 50-500 position changes over ~1.5 years. Hourly flip-flopping is killed by 17 bps per trade.
7. Use CONFIGURABLE parameters as variables (fast_period = 12, not magic numbers)

NO FUTURE INFORMATION — the code is tested by truncating the data and comparing signals:
- NEVER use .shift(-n), .iloc[i+1], center=True, or reversed series
- NEVER normalise with whole-sample statistics: close.mean(), close.std(), (x - x.min())/(x.max()-x.min()),
  rank(pct=True) over the whole series, StandardScaler, etc. Use .rolling(N) or .expanding() instead.
- NEVER decide today's signal from anything computed on data after today.
If the signal at time t changes when bars after t are removed, the code is REJECTED.

GOOD PRACTICE:
- Hysteresis / bands: enter above a threshold, exit below a lower one (cuts turnover)
- Minimum holding period or "confirm for N bars" before flipping
- ATR-based stops and volatility-normalised thresholds
- Regime filters (ADX, realised vol) that switch the strategy OFF, not just the direction

You are optimising on a DEVELOPMENT window. A separate holdout you never see decides the verdict,
so prefer simple, economically motivated rules over anything tuned to the given period.
"""


def generate_signals_iterative(
    prices: pd.DataFrame,
    strategy_name: str,
    quant_spec: dict | None = None,
    max_iterations: int = MAX_ITERATIONS,
    trend_context: dict | None = None,
    holdout_pct: float = HOLDOUT_PCT,
) -> tuple[pd.Series | None, str, dict]:
    """Generate signals with an LLM loop that only ever sees the development window.

    Returns (signals_on_full_history, best_code, log). ``log["holdout_start"]``
    tells the caller where the untouched holdout begins; ``log["n_trials"]``
    is the number of candidate evaluations for Sharpe deflation.
    """
    if not HAS_ANTHROPIC:
        return None, "", {}

    split = int(len(prices) * (1 - holdout_pct))
    dev = prices.iloc[:split]
    holdout_start = prices.index[split]

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    sandbox = SignalSandbox()
    market = analyze_market(dev)
    memory = get_memory_context(limit=10)

    logger.info(
        f"Dev window: {dev.index[0].date()} → {dev.index[-1].date()} ({len(dev)} bars), "
        f"holdout from {holdout_start.date()} ({len(prices) - split} bars, never shown to LLM)"
    )
    logger.info(f"Dev market: {market['regime']}, return={market['total_return']}")

    log = {"iterations": [], "final_source": "none", "holdout_start": str(holdout_start),
           "dev_bars": int(split), "holdout_bars": int(len(prices) - split), "n_trials": 0}
    best_signals_dev = None
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

        code = extract_code(text)
        if not code:
            logger.warning(f"Code extraction failed (attempt {attempt+1})")
            log["iterations"].append({"attempt": attempt + 1, "error": "extraction_failed"})
            continue

        signals = sandbox.execute(code, dev)
        log["n_trials"] += 1
        if signals is None:
            log["iterations"].append({"attempt": attempt + 1, "error": "execution_failed", "code_len": len(code)})
            continue

        # Look-ahead test on the development window
        la = lookahead_truncation_test(lambda p: sandbox.execute(code, p), dev)
        if not la.passed:
            logger.warning(f"  Attempt {attempt+1}: LOOK-AHEAD detected — {la.detail}")
            log["iterations"].append({
                "attempt": attempt + 1, "error": "lookahead",
                "detail": la.detail, "sharpe_if_trusted": _evaluate(dev, signals)["sharpe"],
            })
            continue

        ev = _evaluate(dev, signals)
        iter_result = {"attempt": attempt + 1, **ev}
        log["iterations"].append(iter_result)
        logger.info(
            f"  Attempt {attempt+1}: dev Sharpe={ev['sharpe']:.3f}, Return={ev['total_return']}, "
            f"Trades={ev['n_trades']}, cost drag={ev['cost_drag_pct']}"
        )

        if ev["sharpe"] > best_sharpe:
            best_sharpe = ev["sharpe"]
            best_signals_dev = signals
            best_code = code

        if ev["sharpe"] > SHARPE_THRESHOLD:
            logger.info("Positive dev Sharpe — moving to parameter sweep")
            break

    # Parameter sweep — on the development window only
    if best_code and best_sharpe > -5:
        try:
            swept_signals, swept_params, sweep_log = run_parameter_sweep(best_code, dev)
            log["n_trials"] += int(sweep_log.get("n_trials", sweep_log.get("combos_tested", 0)))
            if swept_signals is not None:
                swept = _evaluate(dev, swept_signals)
                logger.info(f"  Sweep (plateau) dev Sharpe={swept['sharpe']:.3f} (was {best_sharpe:.3f})")
                if swept["sharpe"] > best_sharpe and swept_params:
                    best_signals_dev = swept_signals
                    best_sharpe = swept["sharpe"]
                    best_code = _apply_params(best_code, swept_params)
                log["sweep"] = sweep_log
        except Exception as e:
            logger.warning(f"Sweep failed: {e}")

    log["best_dev_sharpe"] = round(best_sharpe, 3)
    log["total_attempts"] = len(log["iterations"])

    if best_signals_dev is None:
        log["final_source"] = "none"
        return None, best_code, log

    # Final: run the frozen code once over the FULL history (dev + holdout).
    full_signals = sandbox.execute(best_code, prices)
    if full_signals is None:
        logger.warning("Best code failed on full history — falling back to dev signals only")
        full_signals = best_signals_dev.reindex(prices.index).fillna(0).astype(int)
    log["final_source"] = "agent_iterated"
    return full_signals, best_code, log


def _apply_params(code: str, params: dict) -> str:
    """Bake swept parameters into the code so the frozen code is self-contained."""
    from src.backtesting.param_sweep import _inject_params
    return f"# Swept params (plateau optimum): {params}\n" + _inject_params(code, params)


def _build_prompt(name, market, memory, trend_ctx, spec, prev_code, prev_result, attempt):
    parts = [f'Write a generate_signals() function for strategy: "{name}"']
    parts.append(
        f"\nDEVELOPMENT WINDOW ({market['bars']} hourly bars): regime={market['regime']}, "
        f"return={market['total_return']}, vol={market['volatility']}, max_dd={market['max_drawdown']}, "
        f"daily return autocorr(1)={market['daily_autocorr_lag1']}, "
        f"price range={market['price_range']}, last={market['current']}"
    )
    parts.append("The holdout window that decides the verdict is NOT described here and may differ.")

    if trend_ctx:
        parts.append(f"\n4H TREND (development window): {trend_ctx.get('note', 'unknown')}")

    if memory:
        parts.append(f"\n{memory}")

    if spec and isinstance(spec, dict):
        for k in ["entry_rules", "exit_rules", "indicators"]:
            if k in spec:
                parts.append(f"\nHint ({k}): {json.dumps(spec[k], default=str)[:300]}")

    if prev_result and attempt > 0:
        if prev_result.get("error") == "lookahead":
            parts.append(
                f"\nPREVIOUS ATTEMPT WAS REJECTED FOR LOOK-AHEAD: {prev_result.get('detail')}. "
                "Remove any whole-sample statistics, negative shifts or centered windows. "
                "Use rolling/expanding windows only."
            )
        elif prev_result.get("error"):
            parts.append(f"\nPREVIOUS ATTEMPT FAILED: {prev_result['error']}. Follow the template exactly.")
        else:
            parts.append(
                f"\nPREVIOUS ATTEMPT (dev window): Sharpe={prev_result.get('sharpe')}, "
                f"Return={prev_result.get('total_return')}, Trades={prev_result.get('n_trades')}, "
                f"exposure={prev_result.get('exposure_pct')}, hit rate={prev_result.get('hit_rate')}, "
                f"gross Sharpe before costs={prev_result.get('gross_sharpe')}, "
                f"cost drag={prev_result.get('cost_drag_pct')} of gross P&L"
            )
            if prev_result.get("sharpe", 0) < 0:
                parts.append("NEGATIVE SHARPE — change the logic, not just the numbers.")
            if prev_result.get("gross_sharpe", 0) > 0.3 and prev_result.get("sharpe", 0) < 0:
                parts.append("The edge exists before costs but dies after — reduce turnover "
                             "(hysteresis, minimum hold, confirmation bars).")
            if prev_result.get("n_trades", 0) < 50:
                parts.append("Too few trades — loosen conditions or shorten lookbacks.")
            if prev_result.get("n_trades", 0) > 1000:
                parts.append("Too many trades — costs are killing returns; add hysteresis or a minimum hold.")
        if prev_code:
            parts.append(f"\nPREVIOUS CODE:\n```python\n{prev_code[:2500]}\n```")

    parts.append("\nRespond with ONLY a ```python code block. No JSON. No explanation outside the block.")
    parts.append(f"Attempt {attempt+1}/{MAX_ITERATIONS}.")
    return "\n".join(parts)


def _evaluate(prices: pd.DataFrame, signals: pd.Series) -> dict:
    """Net & gross Sharpe with correct flip accounting, plus diagnostics for the LLM."""
    net = strategy_returns(prices, signals)
    gross = strategy_returns(prices, signals, cost_per_trade=0.0)
    position = signals.reindex(prices.index).fillna(0).shift(1).fillna(0)
    turnover = position.diff().abs().fillna(0)
    n_trades = int(np.ceil(turnover.sum() / 2))
    gross_pnl = float(gross.abs().sum())
    cost_total = float((gross - net).sum())
    hit = 0.0
    if n_trades:
        grp = (position != position.shift(1)).cumsum()
        pnl_by_pos = net.groupby(grp).sum()
        active = position.groupby(grp).first() != 0
        trade_pnls = pnl_by_pos[active]
        hit = float((trade_pnls > 0).mean()) if len(trade_pnls) else 0.0
    return {
        "sharpe": round(sharpe_ratio(net), 3),
        "gross_sharpe": round(sharpe_ratio(gross), 3),
        "total_return": f"{float((1 + net).prod() - 1):.2%}",
        "n_trades": n_trades,
        "exposure_pct": f"{float((position != 0).mean()):.0%}",
        "hit_rate": f"{hit:.0%}",
        "cost_drag_pct": f"{(cost_total / gross_pnl if gross_pnl > 0 else 0):.0%}",
    }
