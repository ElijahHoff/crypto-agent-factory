"""Strategy Ideation Agent: generates trading hypotheses grounded in market logic."""

from __future__ import annotations

from typing import Any

from src.agents.base import BaseAgent


class StrategyIdeation(BaseAgent):
    name = "strategy_ideation"
    role = "Strategy Ideation — generates testable trading hypotheses"
    temperature = 0.6  # Higher creativity

    def system_prompt(self) -> str:
        return """You are a Strategy Ideation Agent for systematic crypto trading.

Your job is to generate high-quality, testable trading hypotheses.

Every hypothesis MUST have:
1. A clear economic or behavioral logic (not just "indicator crosses X").
2. An identifiable counterparty (who loses money on the other side).
3. Defined conditions where the edge SHOULD disappear (falsifiability).
4. Realistic assessment of execution feasibility.

Strategy classes you can propose:
- Momentum / trend-following (time-series or cross-sectional)
- Mean reversion (intraday, swing, cross-asset)
- Breakout / volatility expansion
- Cross-sectional relative value (long-short)
- Market-neutral (funding, basis, stat arb)
- Sentiment / event driven
- Regime-adaptive / meta-strategies
- Volume / volatility structure
- Liquidation / funding cascade strategies

NEVER propose strategies based solely on:
- Overfitted indicator combinations
- "Buy when RSI < 30" without deeper logic
- Strategies that require knowledge of future data
- Strategies with no clear edge source

Be creative but grounded. Think like a quant researcher, not a YouTube trader.

Respond in structured JSON."""

    def build_user_prompt(self, context: dict[str, Any]) -> str:
        n = context.get("n_strategies", 3)
        strategy_class = context.get("strategy_class", "any")
        constraints = context.get("constraints", "No specific constraints.")

        return f"""Generate {n} trading hypotheses for class: {strategy_class}.

Constraints: {constraints}

Return JSON:
{{
  "hypotheses": [
    {{
      "name": "string",
      "idea": "string (1-2 sentences)",
      "economic_logic": "string (detailed)",
      "strategy_type": "momentum|mean_reversion|breakout|cross_sectional|market_neutral|funding_basis|sentiment|regime_adaptive|volatility_structure|statistical_arbitrage",
      "timeframe": "1m|5m|15m|1h|4h|1d",
      "universe": ["string"],
      "long_logic": "string",
      "short_logic": "string or null",
      "risk_factors": ["string"],
      "edge_death_conditions": ["string"],
      "estimated_sharpe_range": "string (e.g. 0.5-1.5)",
      "min_data_years": 2,
      "implementation_complexity": "low|medium|high"
    }}
  ]
}}"""
