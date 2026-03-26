"""Research Director: pipeline orchestration, experiment prioritization, go/no-go decisions."""

from __future__ import annotations

from typing import Any

from src.agents.base import BaseAgent


class ResearchDirector(BaseAgent):
    name = "research_director"
    role = "Head of Research — owns the experiment roadmap and quality gates"
    temperature = 0.2

    def system_prompt(self) -> str:
        return """You are the Research Director of a systematic crypto trading R&D lab.

Your responsibilities:
1. Manage the research roadmap and prioritize which hypotheses to test first.
2. Design experiments with proper controls and reject sloppy methodology.
3. Gate each pipeline stage: decide REJECT / REFINE / ADVANCE for every strategy.
4. Maintain intellectual honesty — never hype results, always surface weaknesses.

You think like a senior quant PM at a prop shop:
- Skeptical by default.
- Demand statistical rigor.
- Prefer simple robust edges over complex fragile ones.
- Insist on out-of-sample validation before any advancement.

When reviewing a strategy, always ask:
- Is the edge economically justified, or is it data-mined?
- Would this survive with 2x worse slippage?
- How many trades? Is the sample sufficient?
- Is there regime dependency that isn't being accounted for?
- What's the probability this is a false discovery?

Respond in structured JSON matching the requested schema."""

    def build_user_prompt(self, context: dict[str, Any]) -> str:
        action = context.get("action", "prioritize")

        if action == "prioritize":
            return """Propose a research roadmap for systematic crypto strategy development.

Return JSON:
{
  "strategy_classes": [
    {
      "name": "string",
      "type": "string",
      "priority": "high/medium/low",
      "rationale": "string",
      "estimated_edge_persistence": "string",
      "data_requirements": ["string"],
      "complexity": "low/medium/high",
      "competition_level": "low/medium/high"
    }
  ],
  "first_wave": ["strategy_name_1", "strategy_name_2", "strategy_name_3"],
  "first_wave_rationale": "string",
  "key_risks": ["string"],
  "timeline_weeks": 4
}"""

        elif action == "review":
            experiment = context.get("experiment", {})
            return f"""Review this experiment and make a go/no-go decision.

Experiment data:
{experiment}

Return JSON:
{{
  "decision": "reject|refine|advance",
  "reasoning": "string (detailed)",
  "key_risks": ["string"],
  "improvements_needed": ["string"],
  "edge_evidence": ["string"],
  "confidence_level": "low|medium|high",
  "dissenting_view": "string"
}}"""

        else:
            return f"Context: {context}. Analyze and respond in structured JSON."
