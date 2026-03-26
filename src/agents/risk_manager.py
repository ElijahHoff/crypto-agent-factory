"""Risk Manager Agent: evaluates strategies like a risk committee."""

from __future__ import annotations

from typing import Any

from src.agents.base import BaseAgent


class RiskManager(BaseAgent):
    name = "risk_manager"
    role = "Risk Manager — independent risk assessment and controls"
    temperature = 0.2

    def system_prompt(self) -> str:
        return """You are the Risk Manager for a systematic crypto trading operation.
You evaluate strategies as if you're the risk committee at a prop firm.

You must analyze:
- Volatility profile (annualized vol, conditional vol, vol clustering)
- Drawdown analysis (max DD, time underwater, recovery patterns)
- Tail risk (VaR, CVaR, worst scenarios, left tail behavior)
- Distribution quality (skew, kurtosis, return distribution shape)
- Concentration risk (single asset dependency, regime dependency)
- Market beta (correlation to BTC, ETH, total market)
- Leverage usage (peak, average, margin utilization)
- Liquidation risk (probability of forced liquidation)
- Gap risk (weekend gaps, flash crash exposure)
- Correlation with existing book / benchmark strategies

You must PROPOSE:
- Position limits (per asset, per strategy, gross, net)
- Kill-switch rules (when to auto-stop the strategy)
- Daily/weekly loss limits
- Drawdown brakes (reduce size at -5%, stop at -15%)
- Regime filters (disable strategy in certain regimes)
- De-risking playbook

Be CONSERVATIVE. Your job is to prevent blowups, not to maximize returns.

Respond in structured JSON."""

    def build_user_prompt(self, context: dict[str, Any]) -> str:
        strategy = context.get("strategy", {})
        backtest = context.get("backtest_results", {})
        return f"""Perform a full risk assessment:

Strategy: {strategy}
Backtest Results: {backtest}

Return JSON:
{{
  "risk_assessment": {{
    "overall_risk_rating": "low|medium|high|critical",
    "volatility_analysis": "string",
    "drawdown_analysis": "string",
    "tail_risk": "string",
    "concentration_risk": "string",
    "leverage_risk": "string",
    "liquidation_probability": "string",
    "market_beta_concern": "string",
    "gap_risk": "string"
  }},
  "risk_controls": {{
    "max_position_pct": 0.0,
    "max_gross_exposure_pct": 0.0,
    "max_net_exposure_pct": 0.0,
    "daily_loss_limit_pct": 0.0,
    "weekly_loss_limit_pct": 0.0,
    "drawdown_brake_levels": [
      {{"drawdown_pct": 5, "action": "reduce 50%"}},
      {{"drawdown_pct": 10, "action": "reduce 75%"}},
      {{"drawdown_pct": 15, "action": "stop"}}
    ],
    "kill_switch_conditions": ["string"],
    "regime_filters": ["string"],
    "max_leverage": 0.0
  }},
  "stress_scenarios": [
    {{
      "scenario": "string",
      "estimated_loss_pct": 0.0,
      "mitigation": "string"
    }}
  ],
  "approval_status": "approved|conditional|rejected",
  "conditions_for_approval": ["string"],
  "hard_stops": ["string"]
}}"""
