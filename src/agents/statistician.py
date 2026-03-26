"""Statistician / Validation Agent: fights false discoveries and p-hacking."""

from __future__ import annotations

from typing import Any

from src.agents.base import BaseAgent


class Statistician(BaseAgent):
    name = "statistician"
    role = "Statistician — anti-overfitting, anti-p-hacking validation"
    temperature = 0.2

    def system_prompt(self) -> str:
        return """You are the Statistician and Validation Agent. Your job is to
DESTROY false confidence and prevent data-mined garbage from reaching production.

You must rigorously check:
1. SAMPLE SIZE — enough trades for statistical significance?
2. SUBPERIOD STABILITY — does it work in all time periods or just one?
3. BOOTSTRAP / RESAMPLING — confidence intervals on key metrics.
4. PERMUTATION TESTS — is the edge real or random?
5. PARAMETER SENSITIVITY — does a small param change destroy returns?
6. MULTIPLE TESTING — how many strategies were tested? Bonferroni/BH correction?
7. OVERFITTING PROBABILITY — Probability of Backtest Overfitting (PBO) estimate.
8. SURVIVORSHIP OF EDGE — does it persist after realistic cost assumptions?
9. DISTRIBUTIONAL ANALYSIS — are returns normally distributed? Fat tails? Skew?

You must EXPLICITLY state:
- The probability the observed results are due to chance.
- What tests the strategy FAILED.
- How robust the observed edge is.
- Whether the sample is sufficient for the claims being made.

Be brutally honest. Better to reject a good strategy than accept a bad one.

Respond in structured JSON."""

    def build_user_prompt(self, context: dict[str, Any]) -> str:
        strategy = context.get("strategy", {})
        backtest = context.get("backtest_results", {})
        n_strategies_tested = context.get("n_strategies_tested", 1)

        return f"""Perform statistical validation:

Strategy: {strategy}
Backtest Results: {backtest}
Total strategies tested in this research wave: {n_strategies_tested}

Return JSON:
{{
  "sample_analysis": {{
    "total_trades": 0,
    "sufficient": true,
    "min_recommended": 0,
    "confidence_note": "string"
  }},
  "subperiod_stability": {{
    "stable": true,
    "worst_period": "string",
    "best_period": "string",
    "variance_across_periods": 0.0,
    "concern_level": "none|low|medium|high"
  }},
  "statistical_tests": [
    {{
      "test_name": "string",
      "result": "pass|fail|marginal",
      "p_value": null,
      "details": "string"
    }}
  ],
  "overfitting_assessment": {{
    "n_parameters_optimized": 0,
    "n_strategies_tested": 0,
    "estimated_pbo": 0.0,
    "multiple_testing_adjustment": "string",
    "adjusted_significance": 0.0,
    "overfitting_risk": "low|medium|high|critical"
  }},
  "edge_robustness": {{
    "survives_2x_costs": true,
    "survives_param_perturbation": true,
    "survives_regime_shift": true,
    "survives_asset_removal": true,
    "overall_robustness": "fragile|moderate|robust"
  }},
  "verdict": {{
    "probability_random": 0.0,
    "confidence_in_edge": "low|medium|high",
    "key_concerns": ["string"],
    "recommendation": "reject|needs_more_data|marginal|validated"
  }}
}}"""
