"""Portfolio Construction Agent: builds multi-strategy portfolios with correlation awareness."""

from __future__ import annotations

from typing import Any

from src.agents.base import BaseAgent


class PortfolioConstruction(BaseAgent):
    name = "portfolio_construction"
    role = "Portfolio Construction — correlation-aware multi-strategy allocation"
    temperature = 0.2

    def system_prompt(self) -> str:
        return """You are the Portfolio Construction Agent. When multiple strategies
are validated, you combine them into a portfolio.

Your principles:
1. DIVERSIFICATION — prefer uncorrelated strategies.
2. ROBUSTNESS > RAW SHARPE — don't concentrate in the highest Sharpe strategy.
3. CAPITAL CONSTRAINTS — respect total leverage and gross exposure limits.
4. TURNOVER BUDGET — high-turnover strategies compete for execution bandwidth.
5. REGIME AWARENESS — don't load up on strategies that all fail in the same regime.
6. CLUSTER EXPOSURE — identify hidden correlations between strategies.

Methods you can use:
- Equal weight (baseline)
- Inverse volatility
- Risk parity
- Mean-variance with shrinkage
- Maximum diversification
- Hierarchical risk parity (HRP)

Always provide the EQUAL WEIGHT baseline for comparison.

Respond in structured JSON."""

    def build_user_prompt(self, context: dict[str, Any]) -> str:
        strategies = context.get("strategies", [])
        return f"""Construct a portfolio from these validated strategies:

{strategies}

Return JSON:
{{
  "portfolio_name": "string",
  "allocation_method": "string",
  "allocations": [
    {{
      "strategy_name": "string",
      "weight_pct": 0.0,
      "rationale": "string"
    }}
  ],
  "equal_weight_baseline": {{
    "expected_sharpe": 0.0,
    "expected_max_dd": 0.0
  }},
  "optimized_portfolio": {{
    "expected_sharpe": 0.0,
    "expected_max_dd": 0.0,
    "diversification_ratio": 0.0
  }},
  "correlation_matrix_summary": "string",
  "regime_exposure": {{
    "bull": "string",
    "bear": "string",
    "chop": "string"
  }},
  "constraints_applied": ["string"],
  "rebalance_frequency": "string",
  "warnings": ["string"]
}}"""
