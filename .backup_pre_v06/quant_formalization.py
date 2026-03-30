"""Quant Formalization Agent: converts ideas into precise trading rules."""

from __future__ import annotations

from typing import Any

from src.agents.base import BaseAgent


class QuantFormalization(BaseAgent):
    name = "quant_formalization"
    role = "Quant Formalization — translates hypotheses into executable rules"
    temperature = 0.2

    def system_prompt(self) -> str:
        return """You are a Quant Formalization Agent. Your job is to translate trading
hypotheses into precise, unambiguous, implementable trading rules.

For every strategy you must specify:
1. ENTRY rules — exact conditions, no ambiguity.
2. EXIT rules — stop loss, take profit, time-based, signal reversal.
3. POSITION SIZING — fixed fraction, volatility-adjusted, Kelly, etc.
4. REBALANCE logic — frequency, trigger conditions.
5. COOLDOWN — minimum time between trades / re-entries.
6. LEVERAGE constraints — max leverage, margin rules.
7. PORTFOLIO rules — max positions, sector caps, correlation limits.
8. PARAMETERS — list all params with default values.
9. HYPERPARAMETERS — which params can be optimized (and ranges).
10. FROZEN PARAMS — which params MUST NOT be optimized (to prevent overfitting).

Your pseudocode must be precise enough that a junior developer could implement it
without any ambiguity. Use Python-like pseudocode.

CRITICAL: Every parameter choice must be JUSTIFIED. No magic numbers without rationale.

Respond in structured JSON."""

    def build_user_prompt(self, context: dict[str, Any]) -> str:
        hypothesis = context.get("hypothesis", {})
        return f"""Formalize this hypothesis into exact trading rules:

{hypothesis}

Return JSON:
{{
  "hypothesis_id": "string",
  "entry_rules": [
    {{
      "condition": "string (precise logical condition)",
      "description": "string",
      "parameters": {{"param_name": "value"}}
    }}
  ],
  "exit_rules": [
    {{
      "condition": "string",
      "description": "string",
      "parameters": {{}}
    }}
  ],
  "position_sizing": "string (methodology + formula)",
  "rebalance_logic": "string",
  "cooldown_bars": 0,
  "risk_framework": {{
    "max_position_size_pct": 10.0,
    "max_leverage": 3.0,
    "stop_loss_pct": null,
    "trailing_stop_pct": null,
    "max_concurrent_positions": 10,
    "daily_loss_limit_pct": 3.0,
    "drawdown_brake_pct": 15.0,
    "kill_switch_conditions": ["string"]
  }},
  "parameters": {{"name": "value with rationale"}},
  "hyperparameters": {{
    "name": {{"default": "value", "range": [0, 100], "rationale": "string"}}
  }},
  "frozen_params": ["string"],
  "pseudocode": "string (multi-line Python-like pseudocode)",
  "complexity_score": "low|medium|high",
  "implementation_notes": ["string"]
}}"""
