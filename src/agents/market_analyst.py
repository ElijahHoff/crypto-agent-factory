"""Market Structure Analyst: studies regime behavior & crypto microstructure."""

from __future__ import annotations

from typing import Any

from src.agents.base import BaseAgent


class MarketAnalyst(BaseAgent):
    name = "market_analyst"
    role = "Market Structure Analyst — crypto regime & microstructure expert"
    temperature = 0.4

    def system_prompt(self) -> str:
        return """You are a Market Structure Analyst specializing in crypto markets.

Your domain expertise covers:
- Regime identification: trend, mean reversion, vol expansion/compression, panic, chop.
- Crypto-specific structure: 24/7 markets, funding rates, liquidation cascades,
  dominance shifts, weekend behavior, exchange fragmentation, listing/delisting effects.
- Cross-asset dynamics: BTC dominance → altcoin rotation, ETH/BTC ratio behavior,
  correlation breakdowns during stress.
- Microstructure: bid-ask dynamics, order flow imbalance, market impact modeling.

Key principles:
- Ground hypotheses in market MECHANICS, not just indicator patterns.
- Always ask "WHO is on the other side of this trade and WHY are they losing?"
- Distinguish structural edges (persist) from transient anomalies (decay).
- Account for the 24/7 nature and the role of funding/liquidations as unique crypto features.

Respond in structured JSON."""

    def build_user_prompt(self, context: dict[str, Any]) -> str:
        action = context.get("action", "analyze_regimes")

        if action == "analyze_regimes":
            return """Analyze the main market regimes in crypto and propose regime-conditional hypotheses.

Return JSON:
{
  "regimes": [
    {
      "name": "string",
      "characteristics": ["string"],
      "typical_duration": "string",
      "detection_signals": ["string"],
      "profitable_strategy_types": ["string"],
      "dangerous_strategy_types": ["string"]
    }
  ],
  "crypto_specific_features": [
    {
      "feature": "string",
      "exploitability": "string",
      "data_source": "string",
      "decay_risk": "low/medium/high"
    }
  ],
  "hypotheses": [
    {
      "name": "string",
      "logic": "string",
      "regime_dependency": "string",
      "counterparty": "string (who loses)"
    }
  ]
}"""

        elif action == "assess_hypothesis":
            hypothesis = context.get("hypothesis", {})
            return f"""Assess this hypothesis from a market structure perspective:

{hypothesis}

Return JSON:
{{
  "structural_validity": "strong/moderate/weak",
  "counterparty_analysis": "string",
  "regime_sensitivity": "string",
  "crowding_risk": "low/medium/high",
  "edge_persistence_estimate": "string",
  "recommended_modifications": ["string"],
  "red_flags": ["string"]
}}"""

        return f"Analyze: {context}. Return structured JSON."
