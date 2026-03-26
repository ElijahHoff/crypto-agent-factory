"""Data Engineer Agent: data sourcing, quality control, schema validation."""

from __future__ import annotations

from typing import Any

from src.agents.base import BaseAgent


class DataEngineer(BaseAgent):
    name = "data_engineer"
    role = "Data Engineer — data quality, schema, survivorship bias control"
    temperature = 0.2

    def system_prompt(self) -> str:
        return """You are the Data Engineer for a systematic crypto trading lab.

Your responsibilities:
1. Define exact data requirements for each strategy.
2. Specify schemas, frequencies, sources.
3. Identify and document data quality issues:
   - Missing candles, bad OHLCV, duplicate timestamps
   - Timezone inconsistencies, DST issues
   - Survivorship bias (delisted coins appearing in historical data)
   - Contract changes, symbol migrations
   - Funding rate timestamp alignment
   - Listing effects (first N days of trading are anomalous)
4. Design preprocessing pipelines.
5. Flag any data issues that could cause lookahead bias.

Available data types: OHLCV, order book snapshots, trades, funding rates,
open interest, liquidations, perp premium/basis, on-chain indicators,
sentiment proxies, BTC dominance, market breadth, cross-sectional features.

CRITICAL: Always document what data is point-in-time safe vs potentially leaked.

Respond in structured JSON."""

    def build_user_prompt(self, context: dict[str, Any]) -> str:
        strategy = context.get("strategy", {})
        return f"""Define the data specification for this strategy:

{strategy}

Return JSON:
{{
  "datasets": [
    {{
      "name": "string",
      "source": "string (e.g. ccxt/binance, custom)",
      "frequency": "string",
      "fields": ["string"],
      "start_date": "YYYY-MM-DD",
      "end_date": "latest",
      "point_in_time_safe": true,
      "notes": "string"
    }}
  ],
  "universe_selection": {{
    "method": "string",
    "criteria": ["string"],
    "rebalance_frequency": "string",
    "survivorship_handling": "string"
  }},
  "quality_checks": [
    {{
      "check": "string",
      "severity": "critical|high|medium",
      "remediation": "string"
    }}
  ],
  "preprocessing_pipeline": [
    {{
      "step": "string",
      "description": "string",
      "order": 1
    }}
  ],
  "known_issues": ["string"],
  "data_lag_assumptions": "string"
}}"""
