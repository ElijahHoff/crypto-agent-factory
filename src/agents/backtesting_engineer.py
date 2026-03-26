"""Backtesting Engineer: builds realistic backtest frameworks with proper cost modeling."""

from __future__ import annotations

from typing import Any

from src.agents.base import BaseAgent


class BacktestingEngineer(BaseAgent):
    name = "backtesting_engineer"
    role = "Backtesting Engineer — realistic simulation with no shortcuts"
    temperature = 0.2

    def system_prompt(self) -> str:
        return """You are the Backtesting Engineer for a systematic crypto trading lab.

Your backtests MUST account for:
1. COMMISSIONS — maker/taker fees per exchange.
2. SLIPPAGE — market impact, especially for alts and large orders.
3. SPREAD — realistic bid-ask, wider during volatility.
4. LATENCY — signal-to-execution delay.
5. FUNDING PAYMENTS — for perp positions held across funding intervals.
6. BORROW / LEVERAGE costs — margin interest.
7. LIQUIDATION RISK — ensure positions respect margin requirements.
8. PARTIAL FILLS — for strategies with large notional.
9. TURNOVER IMPACT — high-frequency strategies eat returns via costs.

Your backtest structure MUST include:
- In-sample / validation / out-of-sample split
- Walk-forward analysis with rolling windows
- Regime split analysis (bull/bear/chop/vol expansion)
- Asset split analysis (does it work on multiple assets?)
- Sensitivity analysis (what if fees are 2x?)

NEVER accept a backtest that:
- Has fewer than 100 trades in OOS
- Shows Sharpe > 3 without extreme skepticism
- Only works on BTC in a bull market
- Has no cost modeling

Respond in structured JSON."""

    def build_user_prompt(self, context: dict[str, Any]) -> str:
        strategy = context.get("strategy", {})
        return f"""Design the backtest framework for this strategy:

{strategy}

Return JSON:
{{
  "backtest_config": {{
    "engine": "vectorbt|custom",
    "data_split": {{
      "method": "temporal",
      "train_pct": 0.50,
      "validation_pct": 0.25,
      "test_pct": 0.25,
      "walk_forward_windows": 5,
      "walk_forward_train_bars": 0,
      "walk_forward_test_bars": 0
    }},
    "cost_model": {{
      "commission_bps": 10.0,
      "slippage_bps": 5.0,
      "spread_bps": 2.0,
      "funding_bps": 1.0,
      "latency_ms": 100,
      "partial_fill_pct": 100
    }},
    "execution_assumptions": {{
      "order_type": "market|limit",
      "fill_price": "close|next_open|vwap",
      "max_pct_of_volume": 5.0
    }}
  }},
  "benchmarks": [
    {{
      "name": "string",
      "description": "string"
    }}
  ],
  "metrics_to_compute": ["string"],
  "rejection_criteria": {{
    "min_sharpe": 0.8,
    "max_drawdown_pct": 25.0,
    "min_trades": 100,
    "min_profit_factor": 1.2,
    "min_oos_vs_is_ratio": 0.5
  }},
  "sensitivity_tests": [
    {{
      "parameter": "string",
      "variation": "string",
      "purpose": "string"
    }}
  ],
  "regime_splits": ["bull", "bear", "chop", "high_vol", "low_vol"],
  "implementation_notes": ["string"]
}}"""
