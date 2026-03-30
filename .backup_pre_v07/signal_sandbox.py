"""
Signal Sandbox v0.6 — Safe execution of agent-generated signal code.

The quant formalization agent writes a Python function:
    def generate_signals(prices: pd.DataFrame) -> pd.Series

This module safely executes that code on real OHLCV data with:
- Restricted imports (only numpy, pandas, math)
- 30-second timeout
- Exception handling with fallback to built-in signals
- Logging of what the agent wrote vs what executed
"""

import signal as signal_module
import traceback
from io import StringIO
from loguru import logger

import numpy as np
import pandas as pd


# Allowed modules in sandbox
import math as _math

_ALLOWED_MODULES = {"numpy": np, "np": np, "pandas": pd, "pd": pd, "math": _math}

def _safe_import(name, *args, **kwargs):
    if name in _ALLOWED_MODULES:
        return _ALLOWED_MODULES[name]
    raise ImportError(f"Module '{name}' not allowed in sandbox")

SAFE_GLOBALS = {
    "__builtins__": {
        "range": range, "len": len, "abs": abs, "min": min, "max": max,
        "sum": sum, "int": int, "float": float, "bool": bool, "str": str,
        "list": list, "dict": dict, "tuple": tuple, "set": set,
        "enumerate": enumerate, "zip": zip, "map": map, "filter": filter,
        "sorted": sorted, "reversed": reversed, "round": round,
        "isinstance": isinstance, "hasattr": hasattr, "getattr": getattr,
        "print": lambda *a, **k: None,
        "True": True, "False": False, "None": None,
        "__import__": _safe_import,
    },
    "np": np,
    "numpy": np,
    "pd": pd,
    "pandas": pd,
    "math": __import__("math"),
}

TIMEOUT_SECONDS = 30


class SignalSandbox:
    """Execute agent-generated signal code safely."""

    def execute(self, code: str, prices: pd.DataFrame) -> pd.Series | None:
        """
        Execute agent-generated signal code on price data.

        Args:
            code: Python code containing generate_signals(prices) function
            prices: OHLCV DataFrame

        Returns:
            pd.Series of signals (+1/-1/0) or None if execution fails
        """
        if not code or not isinstance(code, str) or len(code.strip()) < 20:
            logger.warning("Signal code is empty or too short")
            return None

        logger.info(f"Executing agent signal code ({len(code)} chars)...")

        # Prepare sandbox environment
        sandbox = dict(SAFE_GLOBALS)
        sandbox["prices"] = prices.copy()

        try:
            # Compile the code
            compiled = compile(code, "<agent_signal_code>", "exec")

            # Execute with timeout
            signals = self._run_with_timeout(compiled, sandbox, prices)

            if signals is None:
                return None

            # Validate output
            signals = self._validate_signals(signals, prices)
            if signals is None:
                return None

            n_long = int((signals == 1).sum())
            n_short = int((signals == -1).sum())
            n_flat = int((signals == 0).sum())
            logger.info(
                f"Agent signals generated: {n_long} long, {n_short} short, {n_flat} flat"
            )
            return signals

        except SyntaxError as e:
            logger.warning(f"Agent code syntax error: {e}")
            return None
        except Exception as e:
            logger.warning(f"Agent code execution failed: {e}")
            logger.debug(f"Code was:\n{code[:500]}...")
            return None

    def _run_with_timeout(self, compiled, sandbox, prices):
        """Execute compiled code with timeout."""
        # Execute the code to define the function
        try:
            exec(compiled, sandbox)
        except Exception as e:
            logger.warning(f"Agent code definition failed: {e}")
            return None

        # Find the generate_signals function
        func = sandbox.get("generate_signals")
        if func is None:
            # Try alternate names
            for name in ["signal", "signals", "gen_signals", "compute_signals", "get_signals"]:
                func = sandbox.get(name)
                if func is not None:
                    break

        if func is None:
            logger.warning("Agent code has no generate_signals() function")
            # Try to find any callable that was defined
            for key, val in sandbox.items():
                if callable(val) and key not in SAFE_GLOBALS and not key.startswith("_"):
                    func = val
                    logger.info(f"Using function '{key}' as signal generator")
                    break

        if func is None:
            logger.warning("No callable function found in agent code")
            return None

        # Call with timeout
        try:
            # Simple timeout using signal alarm (Unix only)
            def _timeout_handler(signum, frame):
                raise TimeoutError("Signal generation timed out")

            old_handler = signal_module.signal(signal_module.SIGALRM, _timeout_handler)
            signal_module.alarm(TIMEOUT_SECONDS)

            try:
                result = func(prices)
            finally:
                signal_module.alarm(0)
                signal_module.signal(signal_module.SIGALRM, old_handler)

            return result

        except TimeoutError:
            logger.warning(f"Agent code timed out after {TIMEOUT_SECONDS}s")
            return None
        except Exception as e:
            logger.warning(f"Agent function execution failed: {e}")
            return None

    def _validate_signals(self, signals, prices) -> pd.Series | None:
        """Validate and clean signal output."""
        if signals is None:
            return None

        # Convert to Series if needed
        if isinstance(signals, (list, np.ndarray)):
            if len(signals) != len(prices):
                logger.warning(f"Signal length mismatch: {len(signals)} vs {len(prices)}")
                return None
            signals = pd.Series(signals, index=prices.index)

        if not isinstance(signals, pd.Series):
            logger.warning(f"Signals is {type(signals)}, expected pd.Series")
            return None

        if len(signals) != len(prices):
            logger.warning(f"Signal length mismatch: {len(signals)} vs {len(prices)}")
            return None

        # Clamp to -1, 0, 1
        signals = signals.fillna(0)
        signals = signals.clip(-1, 1).round().astype(int)

        # Sanity check: not all same value
        unique = signals.unique()
        if len(unique) == 1:
            logger.warning(f"All signals are {unique[0]} — no trading activity")
            return None

        return signals


def extract_signal_code(quant_spec: dict) -> str | None:
    """Extract signal code from quant formalization output."""
    if not isinstance(quant_spec, dict):
        return None

    # Try direct field
    for key in ["signal_code", "code", "python_code", "trading_logic", "signal_function"]:
        code = quant_spec.get(key)
        if code and isinstance(code, str) and "def " in code:
            return code

    # Try nested
    rules = quant_spec.get("rules", quant_spec.get("strategy", {}))
    if isinstance(rules, dict):
        for key in ["signal_code", "code", "implementation"]:
            code = rules.get(key)
            if code and isinstance(code, str) and "def " in code:
                return code

    return None
