"""
Quant Agent Signal Code Prompt v0.6

This module monkey-patches the QuantFormalization agent to include
instructions for generating executable Python signal code.
"""

SIGNAL_CODE_ADDENDUM = """

=== CRITICAL: EXECUTABLE SIGNAL CODE ===

You MUST include a "signal_code" field in your JSON output.
This field contains a Python function that will be EXECUTED on real OHLCV data.

FUNCTION TEMPLATE:
def generate_signals(prices):
    import numpy as np
    import pandas as pd
    close = prices["close"]
    high = prices["high"]
    low = prices["low"]
    volume = prices["volume"]
    # Your indicator calculations here
    signals = pd.Series(0, index=prices.index)
    # signals[long_condition] = 1
    # signals[short_condition] = -1
    return signals

RULES:
- Function name: generate_signals, single arg: prices (DataFrame with open/high/low/close/volume)
- Returns: pd.Series of int (+1=long, -1=short, 0=flat), same length as prices
- Allowed: numpy, pandas, math only. NO external libs.
- Compute indicators from scratch: RSI, VWAP, ATR, OBV, Bollinger, MACD, etc.
- Use economically justified parameters.
- Code must handle NaN from rolling calculations (use fillna).

EXAMPLE — RSI + Volume Surge Mean Reversion:
def generate_signals(prices):
    import numpy as np
    import pandas as pd
    close = prices["close"]
    volume = prices["volume"]
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = (100 - (100 / (1 + rs))).fillna(50)
    vol_surge = volume / volume.rolling(20).mean()
    signals = pd.Series(0, index=prices.index)
    signals[(rsi < 30) & (vol_surge > 2.0)] = 1
    signals[(rsi > 70) & (vol_surge > 2.0)] = -1
    return signals

EXAMPLE — Bollinger + OBV Trend:
def generate_signals(prices):
    import numpy as np
    import pandas as pd
    close = prices["close"]
    volume = prices["volume"]
    sma = close.rolling(20).mean()
    std = close.rolling(20).std()
    upper = sma + 2 * std
    lower = sma - 2 * std
    obv = (volume * np.sign(close.diff())).cumsum()
    obv_sma = obv.rolling(20).mean()
    signals = pd.Series(0, index=prices.index)
    signals[(close < lower) & (obv > obv_sma)] = 1
    signals[(close > upper) & (obv < obv_sma)] = -1
    return signals

EXAMPLE — Multi-Timeframe Momentum:
def generate_signals(prices):
    import numpy as np
    import pandas as pd
    close = prices["close"]
    high = prices["high"]
    low = prices["low"]
    roc_fast = close.pct_change(6)
    roc_slow = close.pct_change(24)
    roc_trend = close.pct_change(168)
    tr = pd.concat([high-low, (high-close.shift(1)).abs(), (low-close.shift(1)).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    atr_pct = (atr / close).fillna(0)
    signals = pd.Series(0, index=prices.index)
    signals[(roc_fast > 0) & (roc_slow > 0) & (roc_trend > 0) & (atr_pct > 0.005)] = 1
    signals[(roc_fast < 0) & (roc_slow < 0) & (roc_trend < 0) & (atr_pct > 0.005)] = -1
    return signals

The signal_code must be a STRING in your JSON. Escape newlines as literal \\n characters.
This is the MOST IMPORTANT field — it determines what actually gets backtested.
"""


def patch_quant_agent():
    """Monkey-patch QuantFormalization to include signal_code instructions."""
    try:
        from src.agents.quant_formalization import QuantFormalization

        original = QuantFormalization.system_prompt

        def enhanced_system_prompt(self):
            return original(self) + SIGNAL_CODE_ADDENDUM

        QuantFormalization.system_prompt = enhanced_system_prompt
        return True
    except ImportError:
        return False
