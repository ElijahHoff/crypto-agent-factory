"""Paper Trading Agent: prepares strategies for live shadow trading."""

from __future__ import annotations

from typing import Any

from src.agents.base import BaseAgent


class PaperTrading(BaseAgent):
    name = "paper_trading"
    role = "Paper Trading — live shadow execution setup and monitoring"
    temperature = 0.2

    def system_prompt(self) -> str:
        return """You are the Paper Trading Agent. You prepare validated strategies
for shadow/paper trading before any real capital is deployed.

You must define:
1. LIVE INPUTS — exactly what data feeds are needed in real-time.
2. SIGNAL SCHEDULE — when signals are computed (cron, event-driven).
3. EXECUTION POLICY — order types, timing, split logic.
4. MONITORING — what metrics to track in real-time.
5. ALERTING — conditions that trigger human review.
6. LOGGING — what to log for post-mortem analysis.
7. SHADOW vs BACKTEST — how to compare live signals to historical.
8. DRIFT DETECTION — how to spot when the strategy stops working.
9. GRADUATION CRITERIA — when to move from paper to live.
10. KILL CONDITIONS — when to stop paper trading immediately.

Respond in structured JSON."""

    def build_user_prompt(self, context: dict[str, Any]) -> str:
        strategy = context.get("strategy", {})
        return f"""Design the paper trading setup:

{strategy}

Return JSON:
{{
  "live_inputs": [
    {{
      "data_source": "string",
      "frequency": "string",
      "latency_requirement_ms": 0
    }}
  ],
  "signal_schedule": {{
    "type": "cron|event_driven|hybrid",
    "cron_expression": "string or null",
    "event_triggers": ["string"]
  }},
  "execution_policy": {{
    "order_type": "market|limit|twap",
    "execution_window_seconds": 0,
    "max_slippage_bps": 0,
    "retry_logic": "string"
  }},
  "monitoring_metrics": [
    {{
      "metric": "string",
      "frequency": "string",
      "alert_threshold": "string"
    }}
  ],
  "drift_detection": {{
    "method": "string",
    "lookback_days": 30,
    "trigger_conditions": ["string"]
  }},
  "graduation_criteria": {{
    "min_paper_days": 30,
    "min_trades": 50,
    "max_deviation_from_backtest_pct": 20,
    "required_metrics": ["string"]
  }},
  "kill_conditions": ["string"],
  "infrastructure_requirements": ["string"]
}}"""
