# 🏭 Crypto Strategy Agent Factory

> Autonomous AI agent pipeline for researching, developing, backtesting, and validating algorithmic crypto trading strategies with rigorous statistical discipline.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    ORCHESTRATOR (LangGraph)                   │
├──────────┬──────────┬──────────┬──────────┬─────────────────┤
│ Research │ Market   │ Strategy │  Quant   │     Data        │
│ Director │ Analyst  │ Ideation │ Formal.  │   Engineer      │
├──────────┼──────────┼──────────┼──────────┼─────────────────┤
│ Feature  │Backtest  │   Risk   │  Stats   │   Portfolio     │
│ Engineer │ Engine   │ Manager  │ Validator│  Construction   │
├──────────┼──────────┼──────────┴──────────┴─────────────────┤
│  Paper   │ Auditor  │           Experiment Registry          │
│ Trading  │ /Critic  │                                        │
└──────────┴──────────┴────────────────────────────────────────┘
```

## Tech Stack

| Layer | Technology |
|---|---|
| Agent Orchestration | LangGraph + LangChain |
| LLM Backbone | Anthropic Claude (via API) |
| Data Validation | Pydantic v2 |
| Market Data | ccxt (120+ exchanges) |
| Backtesting | vectorbt + custom engine |
| Time-Series DB | TimescaleDB (PostgreSQL) |
| Cache / Queue | Redis |
| API | FastAPI |
| Monitoring | Prometheus + Grafana |
| CLI | Typer + Rich |
| Containerization | Docker Compose |

## Quick Start

```bash
# Clone
git clone https://github.com/yourname/crypto-agent-factory.git
cd crypto-agent-factory

# Setup
cp .env.example .env
# Edit .env with your ANTHROPIC_API_KEY

# Install
pip install -e ".[dev]"

# Run
python -m src.main run --strategy momentum_cross_sectional

# Or with Docker
docker compose up -d
```

## Pipeline Stages

```
A. Hypothesis → B. Formalization → C. Data/Features → D. Test Design
→ E. Backtest → F. Robustness → G. Decision (reject/refine/advance)
```

## Quality Rules

1. No future data leakage — ever
2. No metrics without fees/slippage/funding
3. No strategies surviving on a single period
4. No Sharpe without drawdown + trade count analysis
5. No trust in "beautiful equity curves"
6. Every claim must be reproducible
7. Prefer simple robust over complex fragile

## License

MIT
