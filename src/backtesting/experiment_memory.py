"""
Experiment Memory v0.9 — Learns from past failures.

Stores: strategy name, signal type, Sharpe, key failure reasons.
Provides context to Claude: "These approaches already failed..."
"""

import json
from pathlib import Path
from datetime import datetime
from loguru import logger

MEMORY_FILE = Path("experiments/memory.json")
MAX_MEMORY = 50  # keep last 50 experiments


def load_memory() -> list[dict]:
    """Load experiment memory."""
    if not MEMORY_FILE.exists():
        return []
    try:
        data = json.loads(MEMORY_FILE.read_text())
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_experiment(
    strategy_name: str,
    strategy_type: str,
    sharpe: float,
    total_return: float,
    n_trades: int,
    signal_source: str,
    decision: str,
    key_failure: str = "",
    code_snippet: str = "",
    holdout_sharpe: float | None = None,
    holdout_trades: int = 0,
    dsr: float = 0.0,
    n_trials: int = 0,
    wf_efficiency: float = 0.0,
    dev_sharpe: float | None = None,
) -> None:
    """Save experiment result to memory."""
    memory = load_memory()

    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "strategy_name": strategy_name,
        "strategy_type": strategy_type,
        "sharpe": round(sharpe, 3),
        "total_return": round(total_return, 4),
        "n_trades": n_trades,
        "signal_source": signal_source,
        "decision": decision,
        "key_failure": key_failure[:200],
        "code_snippet": code_snippet[:300],
        # v1.0 — what the LLM never saw
        "holdout_sharpe": round(holdout_sharpe, 3) if holdout_sharpe is not None else None,
        "holdout_trades": int(holdout_trades),
        "dev_sharpe": round(dev_sharpe, 3) if dev_sharpe is not None else None,
        "psr": round(float(dsr), 3),
        "dsr": round(float(dsr), 3),
        "n_trials": int(n_trials),
        "wf_efficiency": round(float(wf_efficiency), 3),
    }

    memory.append(entry)

    # Keep only last MAX_MEMORY
    if len(memory) > MAX_MEMORY:
        memory = memory[-MAX_MEMORY:]

    MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    MEMORY_FILE.write_text(json.dumps(memory, indent=2))
    logger.debug(f"Memory saved: {strategy_name} Sharpe={sharpe:.3f}")


def get_memory_context(limit: int = 10) -> str:
    """Get formatted memory context for Claude prompt."""
    memory = load_memory()
    if not memory:
        return ""

    # The generator only ever sees DEVELOPMENT-window numbers. Feeding holdout
    # results back into the prompt would let the LLM learn the holdout across
    # experiments and quietly turn it into another in-sample set.
    def _dev(m):
        d = m.get("dev_sharpe")
        return d if d is not None else m.get("sharpe", -999)
    memory.sort(key=_dev, reverse=True)

    lines = ["=== PAST EXPERIMENT RESULTS (development window only) ===",
             "Sharpe below is on the development window. The holdout verdict is NOT shown on purpose."]

    # Best results
    best = [m for m in memory if _dev(m) > -1]
    if best:
        lines.append("\nBEST APPROACHES (dev Sharpe):")
        for m in best[:5]:
            lines.append(
                f"  {m['strategy_name']} [{m.get('strategy_type', '?')}]: "
                f"dev Sharpe={_dev(m)}, Trades={m.get('n_trades', 0)}"
            )
            if m.get("code_snippet"):
                lines.append(f"    Code hint: {m['code_snippet'][:100]}...")

    # Worst failures (to avoid)
    worst = [m for m in memory if _dev(m) < -3 or m.get("key_failure", "").startswith("look-ahead")]
    if worst:
        lines.append("\nFAILED APPROACHES (DO NOT REPEAT):")
        for m in worst[-5:]:
            kf = m.get("key_failure", "")
            reason = "look-ahead in code" if kf.startswith("look-ahead") else "negative dev Sharpe"
            lines.append(
                f"  ❌ {m['strategy_name']} [{m.get('strategy_type', '?')}]: "
                f"dev Sharpe={_dev(m)}, {reason}"
            )

    # Summary stats
    all_sharpes = [_dev(m) for m in memory]  # dev-window only
    if all_sharpes:
        lines.append(f"\nSummary: {len(memory)} experiments, "
                     f"avg dev Sharpe={sum(all_sharpes)/len(all_sharpes):.2f}, "
                     f"best={max(all_sharpes):.2f}, worst={min(all_sharpes):.2f}")

        positive = sum(1 for s in all_sharpes if s > 0)
        lines.append(f"Positive dev Sharpe: {positive}/{len(all_sharpes)} ({positive/len(all_sharpes):.0%})")

    lines.append("=== END MEMORY ===")
    return "\n".join(lines)
