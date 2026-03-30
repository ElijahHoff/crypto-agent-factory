"""
Signal Sandbox v0.7 — Unrestricted execution with timeout.

No import restrictions. Your machine, your code.
Just timeout protection (30s) and basic validation.
"""

import signal as signal_module
import numpy as np
import pandas as pd
from loguru import logger

TIMEOUT = 30


class SignalSandbox:
    """Execute agent-generated signal code."""

    def execute(self, code: str, prices: pd.DataFrame) -> pd.Series | None:
        if not code or len(code.strip()) < 20:
            return None

        logger.info(f"Executing agent signal code ({len(code)} chars)...")

        try:
            # Full Python environment - no restrictions
            env = {"np": np, "numpy": np, "pd": pd, "pandas": pd,
                   "prices": prices.copy()}

            # Timeout
            def _timeout(signum, frame):
                raise TimeoutError("Signal code timed out")

            old = signal_module.signal(signal_module.SIGALRM, _timeout)
            signal_module.alarm(TIMEOUT)
            try:
                exec(code, env)
            finally:
                signal_module.alarm(0)
                signal_module.signal(signal_module.SIGALRM, old)

            # Find the function
            func = env.get("generate_signals")
            if func is None:
                for k, v in env.items():
                    if callable(v) and k not in ("np", "pd", "numpy", "pandas") and not k.startswith("_"):
                        func = v
                        break

            if func is None:
                logger.warning("No generate_signals() function found")
                return None

            # Call it
            signal_module.alarm(TIMEOUT)
            try:
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


def extract_signal_code(quant_spec: dict) -> str | None:
    if not isinstance(quant_spec, dict):
        return None
    for key in ["signal_code", "code", "python_code", "trading_logic", "signal_function"]:
        code = quant_spec.get(key)
        if code and isinstance(code, str) and ("def " in code or "signals" in code):
            return code
    return None
