"""Auditor / Critic Agent: independent skeptic trying to disprove strategy validity."""

from __future__ import annotations

from typing import Any

from src.agents.base import BaseAgent


class Auditor(BaseAgent):
    name = "auditor"
    role = "Auditor / Critic — independent adversarial review"
    temperature = 0.4

    def system_prompt(self) -> str:
        return """You are the Auditor / Critic Agent. You are an INDEPENDENT adversary
whose SOLE JOB is to find reasons why a strategy should NOT be deployed.

You must actively try to DISPROVE the strategy through:
1. HIDDEN LEAKAGE — is there any subtle future data contamination?
2. UNREALISTIC FILLS — would these fills actually occur in live markets?
3. UNSTABLE PARAMETERS — small changes destroy the edge?
4. REGIME DEPENDENCY — only works in one market condition?
5. DATA SNOOPING — was the strategy data-mined?
6. BENCHMARK ILLUSION — does it actually beat a naive benchmark?
7. EXCESSIVE COMPLEXITY — Occam's razor violation?
8. NON-REPRODUCIBILITY — could someone else replicate this?
9. SURVIVORSHIP BIAS — only works on surviving assets?
10. SELECTION BIAS — was it cherry-picked from many attempts?

You are the last line of defense before capital is at risk.
Be ruthless but fair. If the strategy is genuinely good, say so — but still list every concern.

Your output should read like a red team report.

Respond in structured JSON."""

    def build_user_prompt(self, context: dict[str, Any]) -> str:
        experiment = context.get("experiment", {})
        return f"""Conduct an adversarial audit of this complete experiment:

{experiment}

Return JSON:
{{
  "audit_result": "pass|conditional_pass|fail",
  "findings": [
    {{
      "category": "leakage|unrealistic_fills|parameter_instability|regime_dependency|data_snooping|benchmark_illusion|complexity|reproducibility|survivorship|selection_bias|other",
      "severity": "info|low|medium|high|critical",
      "finding": "string",
      "evidence": "string",
      "recommendation": "string"
    }}
  ],
  "critical_issues": ["string"],
  "things_done_well": ["string"],
  "overall_confidence": 0.0,
  "would_you_trade_this": "yes|no|with_modifications",
  "required_modifications": ["string"],
  "summary": "string (2-3 sentences red team verdict)"
}}"""
