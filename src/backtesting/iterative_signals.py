"""
Iterative Signal Generator v0.7 — Claude writes signal code, gets feedback, improves.

Loop:
1. Analyze market data (trend, volatility, regime)
2. Ask Claude to write generate_signals() code
3. Execute on real data → backtest
4. If Sharpe < threshold → send results back, ask for improvement
5. Up to MAX_ITERATIONS attempts
"""

import json
import numpy as np
import pandas as pd
from loguru import logger

from src.backtesting.signal_sandbox import SignalSandbox
from src.config import settings

try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False

MAX_ITERATIONS = 5
SHARPE_THRESHOLD = 0.0  # must beat zero to be considered


def analyze_market(prices: pd.DataFrame) -> dict:
    """Compute market context for the agent."""
    close = prices["close"]
    high = prices["high"]
    low = prices["low"]
    volume = prices["volume"]

    total_return = close.iloc[-1] / close.iloc[0] - 1
    n_bars = len(close)

    # Trend
    sma50 = close.rolling(50).mean()
    sma200 = close.rolling(200).mean()
    pct_above_sma50 = (close > sma50).sum() / n_bars
    pct_above_sma200 = (close > sma200).sum() / n_bars

    # Volatility
    returns = close.pct_change().dropna()
    vol_ann = returns.std() * np.sqrt(8760)
    max_dd = ((close / close.cummax()) - 1).min()

    # Regime splits
    half = n_bars // 2
    first_half_ret = close.iloc[half] / close.iloc[0] - 1
    second_half_ret = close.iloc[-1] / close.iloc[half] - 1

    # Volume profile
    avg_volume = volume.mean()
    volume_trend = volume.iloc[-168:].mean() / volume.iloc[:168].mean()

    # Price range
    price_high = high.max()
    price_low = low.min()
    price_current = close.iloc[-1]

    regime = "bear" if total_return < -0.1 else "bull" if total_return > 0.1 else "sideways"

    return {
        "total_return": f"{total_return:.1%}",
        "regime": regime,
        "annual_volatility": f"{vol_ann:.1%}",
        "max_drawdown": f"{max_dd:.1%}",
        "bars": n_bars,
        "timeframe": "1h",
        "price_range": f"${price_low:,.0f} - ${price_high:,.0f}",
        "current_price": f"${price_current:,.0f}",
        "pct_above_sma50": f"{pct_above_sma50:.0%}",
        "pct_above_sma200": f"{pct_above_sma200:.0%}",
        "first_half_return": f"{first_half_ret:.1%}",
        "second_half_return": f"{second_half_ret:.1%}",
        "volume_trend": f"{volume_trend:.2f}x",
        "regime_note": (
            "STRONG DOWNTREND — price dropped significantly. "
            "Mean reversion will FAIL. Trend-following or short-biased strategies preferred."
            if regime == "bear" else
            "UPTREND — momentum and trend strategies should work." if regime == "bull" else
            "SIDEWAYS — mean reversion and range strategies may work."
        ),
    }


SYSTEM_PROMPT = """You are an expert quantitative developer. You write Python signal generation functions
that are executed on real crypto OHLCV data (1-hour bars, ~8760 bars = 1 year).

You MUST output ONLY valid JSON with this structure:
{
  "reasoning": "Brief explanation of strategy logic",
  "signal_code": "def generate_signals(prices):\\n    import numpy as np\\n    ..."
}

CRITICAL RULES FOR signal_code:
1. Function: def generate_signals(prices) -> pd.Series
2. prices has columns: open, high, low, close, volume (DatetimeIndex)
3. Return pd.Series of int: +1 (long), -1 (short), 0 (flat), same length as prices
4. You can import numpy, pandas, math — anything in standard Python
5. Handle NaN from rolling() with .fillna()
6. Generate at least 50 trades (signal changes) — not too many, not too few
7. NEVER use future data (no .shift(-1), no reverse lookback)

WHAT WORKS IN CRYPTO:
- Trend following (EMA crossovers, breakouts) works in trending markets
- In BEAR markets: short-biased strategies, trend following to the downside
- In BULL markets: momentum, breakout strategies
- Mean reversion ONLY works in sideways/ranging markets
- Volume spikes often precede reversals
- ATR-based stops adapt to volatility regimes
- Multi-timeframe confirmation (fast + slow signals) reduces false signals

WHAT FAILS:
- Mean reversion in trending markets (buying dips in a crash = disaster)
- Overly tight parameters (RSI < 10 triggers too rarely)
- No volatility filter (trading in low-vol = death by fees)
- Static thresholds that don't adapt to market regime
"""


def generate_signals_iterative(
    prices: pd.DataFrame,
    strategy_name: str,
    quant_spec: dict | None = None,
    max_iterations: int = MAX_ITERATIONS,
) -> tuple[pd.Series | None, str, dict]:
    """
    Iteratively generate and improve signal code.

    Returns: (signals, signal_code, iteration_log)
    """
    if not HAS_ANTHROPIC:
        logger.warning("anthropic not available — cannot iterate")
        return None, "", {}

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    sandbox = SignalSandbox()
    market = analyze_market(prices)

    logger.info(f"Market context: {market['regime']} regime, return={market['total_return']}")

    iteration_log = {"iterations": [], "final_source": "none"}
    best_signals = None
    best_sharpe = -999
    best_code = ""

    for attempt in range(max_iterations):
        logger.info(f"🧠 Signal iteration {attempt + 1}/{max_iterations}...")

        # Build prompt
        if attempt == 0:
            prompt = _first_prompt(strategy_name, market, quant_spec)
        else:
            prompt = _improvement_prompt(
                strategy_name, market, best_code,
                iteration_log["iterations"][-1]
            )

        # Call Claude
        try:
            response = client.messages.create(
                model=settings.anthropic_model,
                max_tokens=4096,
                temperature=0.7,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text
        except Exception as e:
            logger.warning(f"Claude call failed: {e}")
            break

        # Parse response
        code = _extract_code(text)
        if not code:
            logger.warning("Could not extract signal_code from response")
            iteration_log["iterations"].append({"attempt": attempt + 1, "error": "no code"})
            continue

        # Execute
        signals = sandbox.execute(code, prices)
        if signals is None:
            logger.warning("Signal code produced no valid signals")
            iteration_log["iterations"].append({"attempt": attempt + 1, "error": "no signals", "code_len": len(code)})
            continue

        # Quick backtest (simplified — just Sharpe from returns)
        returns = prices["close"].pct_change().fillna(0)
        strat_returns = returns * signals.shift(1).fillna(0)
        # Deduct costs
        trades = (signals != signals.shift(1)).astype(float)
        strat_returns = strat_returns - trades * 0.0017
        sharpe = _quick_sharpe(strat_returns)
        total_return = float((1 + strat_returns).prod() - 1)
        n_trades = int(trades.sum())

        iter_result = {
            "attempt": attempt + 1,
            "sharpe": round(sharpe, 3),
            "total_return": f"{total_return:.2%}",
            "n_trades": n_trades,
            "n_long": int((signals == 1).sum()),
            "n_short": int((signals == -1).sum()),
            "code_len": len(code),
        }
        iteration_log["iterations"].append(iter_result)

        logger.info(
            f"  Attempt {attempt + 1}: Sharpe={sharpe:.3f}, "
            f"Return={total_return:.2%}, Trades={n_trades}"
        )

        if sharpe > best_sharpe:
            best_sharpe = sharpe
            best_signals = signals
            best_code = code

        # Success condition: positive Sharpe
        if sharpe > SHARPE_THRESHOLD:
            logger.info(f"✅ Found positive strategy! Sharpe={sharpe:.3f}")
            break

    iteration_log["best_sharpe"] = round(best_sharpe, 3)
    iteration_log["total_attempts"] = len(iteration_log["iterations"])
    iteration_log["final_source"] = "agent_iterated" if best_signals is not None else "none"

    return best_signals, best_code, iteration_log


def _first_prompt(strategy_name: str, market: dict, quant_spec: dict | None) -> str:
    """First iteration prompt — generate initial code."""
    spec_text = ""
    if quant_spec and isinstance(quant_spec, dict):
        # Extract key ideas from quant spec
        for key in ["entry_rules", "exit_rules", "signal_logic", "indicators", "parameters"]:
            if key in quant_spec:
                spec_text += f"\n{key}: {json.dumps(quant_spec[key], default=str)[:500]}"

    return f"""Write a generate_signals() function for strategy: "{strategy_name}"

MARKET CONTEXT (THIS IS REAL DATA — adapt your strategy!):
- Regime: {market['regime']} ({market['regime_note']})
- Total return over period: {market['total_return']}
- Price range: {market['price_range']}, current: {market['current_price']}
- Annual volatility: {market['annual_volatility']}
- Max drawdown: {market['max_drawdown']}
- First half return: {market['first_half_return']}, Second half: {market['second_half_return']}
- % time above SMA50: {market['pct_above_sma50']}, above SMA200: {market['pct_above_sma200']}
- Volume trend (recent vs early): {market['volume_trend']}
- Data: {market['bars']} hourly bars

{f"STRATEGY HINTS FROM QUANT AGENT:{spec_text}" if spec_text else ""}

IMPORTANT: The market is in a {market['regime']} regime. Design your strategy accordingly!
If bearish: consider short-biased, trend-following to downside, or adaptive strategies.
If bullish: momentum and breakout strategies.
If sideways: mean reversion may work.

Generate a strategy that could realistically produce positive Sharpe in this specific market.
Use at least 2-3 indicators combined. Include a volatility filter.
"""


def _improvement_prompt(strategy_name: str, market: dict,
                        prev_code: str, prev_result: dict) -> str:
    """Improvement prompt — fix based on results."""
    return f"""Your previous signal code for "{strategy_name}" produced:
- Sharpe: {prev_result.get('sharpe', 'N/A')}
- Return: {prev_result.get('total_return', 'N/A')}
- Trades: {prev_result.get('n_trades', 'N/A')}
- Long bars: {prev_result.get('n_long', 'N/A')}, Short bars: {prev_result.get('n_short', 'N/A')}

MARKET: {market['regime']} regime, total return {market['total_return']}, vol {market['annual_volatility']}

Previous code:
```python
{prev_code[:1500]}
```

PROBLEMS TO FIX:
{"- Sharpe is negative — the strategy loses money. CHANGE THE APPROACH, don't just tweak parameters." if prev_result.get('sharpe', 0) < 0 else ""}
{"- Too few trades — loosen entry conditions or use shorter lookback periods." if prev_result.get('n_trades', 0) < 50 else ""}
{"- Strategy is long-biased in a BEAR market — add more short signals or trend filter!" if prev_result.get('n_long', 0) > prev_result.get('n_short', 0) * 1.5 and market['regime'] == 'bear' else ""}
{"- Strategy is short-biased in a BULL market — add more long signals!" if prev_result.get('n_short', 0) > prev_result.get('n_long', 0) * 1.5 and market['regime'] == 'bull' else ""}

Write an IMPROVED generate_signals() function. Make MEANINGFUL changes, not just parameter tweaks.
Consider: different indicators, different logic, regime filters, adaptive thresholds.
"""


def _extract_code(text: str) -> str | None:
    """Extract signal code from Claude's response."""
    # Try JSON parse first
    try:
        # Clean markdown fences
        clean = text.strip()
        if clean.startswith("```"):
            clean = clean.split("```")[1]
            if clean.startswith("json"):
                clean = clean[4:]
        if clean.endswith("```"):
            clean = clean[:-3]

        data = json.loads(clean)
        code = data.get("signal_code", "")
        if code and "def " in code:
            # Unescape newlines
            code = code.replace("\\n", "\n").replace("\\t", "    ")
            return code
    except json.JSONDecodeError:
        pass

    # Try to find code block
    if "def generate_signals" in text:
        # Extract the function
        start = text.find("def generate_signals")
        if start >= 0:
            # Find the code block boundaries
            code_start = start
            # Look backwards for ```python
            block_start = text.rfind("```", 0, start)
            if block_start >= 0:
                code_start = block_start + 3
                if text[code_start:code_start+6] == "python":
                    code_start += 6
                code_start = text.find("\n", code_start) + 1

            # Find end
            block_end = text.find("```", start)
            if block_end > 0:
                return text[code_start:block_end].strip()
            else:
                # Take until end or next non-indented line after function
                lines = text[start:].split("\n")
                func_lines = [lines[0]]
                for line in lines[1:]:
                    if line.strip() == "":
                        func_lines.append(line)
                    elif line[0] in (" ", "\t"):
                        func_lines.append(line)
                    else:
                        break
                return "\n".join(func_lines)

    return None


def _quick_sharpe(returns: pd.Series) -> float:
    """Quick annualized Sharpe from returns series."""
    if returns.std() == 0:
        return 0.0
    return float(returns.mean() / returns.std() * np.sqrt(8760))
