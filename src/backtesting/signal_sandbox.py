"""
Signal Sandbox v0.9.2 — Robust code execution.

Handles all Claude output formats:
- Bare function: def generate_signals(prices)
- Inside class: class Strategy: def generate_signals(self, prices)
- Renamed: def compute_signals(prices), def signal(prices)
- With helper functions before/after
- With imports at top level
"""

import signal as signal_module
import inspect
import numpy as np
import pandas as pd
from loguru import logger

TIMEOUT = 30


class SignalSandbox:
    def execute(self, code: str, prices: pd.DataFrame) -> pd.Series | None:
        if not code or len(code.strip()) < 20:
            return None

        logger.info(f"Executing agent signal code ({len(code)} chars)...")

        # Pre-process: unwrap class if needed
        code = _unwrap_class(code)

        try:
            env = {"np": np, "numpy": np, "pd": pd, "pandas": pd,
                   "prices": prices.copy()}

            def _timeout(signum, frame):
                raise TimeoutError("timeout")

            old = signal_module.signal(signal_module.SIGALRM, _timeout)
            signal_module.alarm(TIMEOUT)
            try:
                exec(code, env)
            finally:
                signal_module.alarm(0)
                signal_module.signal(signal_module.SIGALRM, old)

            # Find the function — try multiple names and locations
            func = _find_signal_function(env)

            if func is None:
                logger.warning("No signal function found in agent code")
                return None

            # Call it
            signal_module.alarm(TIMEOUT)
            try:
                # Check if function expects 'self' (method from a class)
                sig = inspect.signature(func)
                params = list(sig.parameters.keys())
                if params and params[0] == "self":
                    result = func(None, prices)  # pass None as self
                else:
                    result = func(prices)
            finally:
                signal_module.alarm(0)

            return self._validate(result, prices)

        except TimeoutError:
            logger.warning(f"Agent code timed out ({TIMEOUT}s)")
            return None
        except Exception as e:
            logger.warning(f"Agent code failed: {e}")
            return None

    def _validate(self, signals, prices) -> pd.Series | None:
        if signals is None:
            return None
        if isinstance(signals, (list, np.ndarray)):
            if len(signals) != len(prices):
                logger.warning(f"Length mismatch: {len(signals)} vs {len(prices)}")
                return None
            signals = pd.Series(signals, index=prices.index)
        if not isinstance(signals, pd.Series):
            return None
        if len(signals) != len(prices):
            return None

        signals = signals.fillna(0).clip(-1, 1).round().astype(int)

        n_long = int((signals == 1).sum())
        n_short = int((signals == -1).sum())
        if n_long + n_short < 10:
            logger.warning(f"Too few trades: {n_long} long + {n_short} short")
            return None

        logger.info(f"Agent signals: {n_long} long, {n_short} short, {int((signals==0).sum())} flat")
        return signals


def _find_signal_function(env):
    """Find signal function in exec environment — checks multiple names and classes."""
    # 1. Direct name matches (most common)
    for name in ["generate_signals", "gen_signals", "compute_signals",
                 "signal", "signals", "get_signals", "make_signals",
                 "trading_signals", "strategy_signals"]:
        func = env.get(name)
        if func and callable(func):
            return func

    # 2. Look inside classes
    for key, val in env.items():
        if isinstance(val, type):  # it's a class
            # Try to find generate_signals method
            for method_name in ["generate_signals", "run", "execute",
                                "compute", "signals", "get_signals"]:
                method = getattr(val, method_name, None)
                if method and callable(method):
                    # Return bound method with dummy instance
                    try:
                        instance = val.__new__(val)
                        return getattr(instance, method_name)
                    except Exception:
                        return method

    # 3. Look for any function that takes a single DataFrame-like arg
    skip = {"np", "pd", "numpy", "pandas", "prices", "math",
            "print", "len", "range", "int", "float", "str",
            "list", "dict", "tuple", "set", "abs", "min", "max", "sum",
            "round", "sorted", "enumerate", "zip", "map", "filter",
            "isinstance", "hasattr", "getattr", "type", "callable"}
    
    candidates = []
    for key, val in env.items():
        if key.startswith("_") or key in skip:
            continue
        if callable(val) and not isinstance(val, type):
            try:
                sig = inspect.signature(val)
                params = [p for p in sig.parameters.keys() if p != "self"]
                if len(params) == 1:
                    candidates.append((key, val))
            except (ValueError, TypeError):
                continue

    # Prefer functions with "signal" in the name
    for name, func in candidates:
        if "signal" in name.lower():
            return func

    # Otherwise return first single-arg function
    if candidates:
        return candidates[0][1]

    return None


def _unwrap_class(code: str) -> str:
    """If code is wrapped in a class, extract the method and make it standalone."""
    lines = code.split("\n")

    # Check if there's a class definition wrapping generate_signals
    class_indent = None
    method_start = None
    method_indent = None

    for i, line in enumerate(lines):
        stripped = line.lstrip()
        indent = len(line) - len(stripped)

        if stripped.startswith("class ") and stripped.endswith(":"):
            class_indent = indent

        if class_indent is not None and "def " in stripped and "signal" in stripped.lower():
            method_start = i
            method_indent = indent
            break

    if method_start is None or method_indent is None:
        return code  # no class wrapping detected

    # Extract imports and top-level code before the class
    pre_class = []
    for line in lines[:method_start]:
        stripped = line.lstrip()
        if stripped.startswith("import ") or stripped.startswith("from "):
            pre_class.append(line.lstrip())
        elif stripped and not stripped.startswith("class ") and not stripped.startswith("#"):
            indent = len(line) - len(stripped)
            if indent == 0:
                pre_class.append(line)

    # Extract the method and dedent it
    method_lines = []
    for line in lines[method_start:]:
        if not line.strip() and method_lines:
            method_lines.append("")
            continue
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if method_lines and indent <= method_indent and stripped and not stripped.startswith("#"):
            break
        # Dedent by method_indent
        if len(line) >= method_indent:
            method_lines.append(line[method_indent:])
        else:
            method_lines.append(line.lstrip())

    if not method_lines:
        return code

    # Fix: rename method to generate_signals if needed, remove self param
    first_line = method_lines[0]
    if "def " in first_line:
        # Remove 'self' parameter
        first_line = first_line.replace("(self, ", "(").replace("(self,", "(").replace("(self)", "(prices)")
        # Rename to generate_signals
        if "generate_signals" not in first_line:
            import re
            first_line = re.sub(r"def \w+\(", "def generate_signals(", first_line)
        method_lines[0] = first_line

    result = "\n".join(pre_class + [""] + method_lines)
    logger.debug(f"Unwrapped class → standalone function ({len(result)} chars)")
    return result


def extract_signal_code(quant_spec: dict) -> str | None:
    if not isinstance(quant_spec, dict):
        return None
    for key in ["signal_code", "code", "python_code", "trading_logic", "signal_function"]:
        code = quant_spec.get(key)
        if code and isinstance(code, str) and ("def " in code or "signals" in code):
            return code
    return None
