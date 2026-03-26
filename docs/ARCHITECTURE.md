# Architecture — Crypto Strategy Agent Factory

## System Overview

The Agent Factory is a multi-agent R&D pipeline for developing, testing, and
validating systematic crypto trading strategies. It enforces strict research
discipline to prevent overfitting, data leakage, and unrealistic expectations.

## Agent Architecture

```
                    ┌──────────────────────┐
                    │   Research Director   │
                    │   (orchestrator)      │
                    └─────────┬────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
   ┌────▼────┐         ┌─────▼─────┐         ┌─────▼─────┐
   │ Market  │         │ Strategy  │         │  Auditor  │
   │ Analyst │         │ Ideation  │         │ (Critic)  │
   └────┬────┘         └─────┬─────┘         └─────▲─────┘
        │                     │                     │
        │              ┌──────▼──────┐              │
        │              │    Quant    │              │
        │              │Formalization│              │
        │              └──────┬──────┘              │
        │                     │                     │
        │         ┌───────────┼───────────┐         │
        │         │           │           │         │
        │    ┌────▼───┐  ┌────▼───┐  ┌────▼───┐    │
        │    │  Data  │  │Feature │  │Backtest│    │
        │    │Engineer│  │Engineer│  │Engineer│    │
        │    └────────┘  └────────┘  └───┬────┘    │
        │                                │         │
        │              ┌─────────────────┤         │
        │              │                 │         │
        │         ┌────▼───┐       ┌─────▼────┐    │
        │         │  Risk  │       │Statistici│    │
        │         │Manager │       │   an     │    │
        │         └────┬───┘       └─────┬────┘    │
        │              │                 │         │
        │              └────────┬────────┘         │
        │                       │                  │
        │                ┌──────▼──────┐           │
        │                │  Decision   │───────────┘
        │                │   Gate      │
        │                └──────┬──────┘
        │                       │
        │              ┌────────▼────────┐
        │              │  Paper Trading  │
        │              │    Agent        │
        │              └────────┬────────┘
        │                       │
        │              ┌────────▼────────┐
        └──────────────│   Portfolio     │
                       │ Construction   │
                       └─────────────────┘
```

## Pipeline Stages

| Stage | Agent(s) | Input | Output | Quality Gate |
|-------|----------|-------|--------|--------------|
| A. Hypothesis | Strategy Ideation + Market Analyst | Research priorities | Validated hypothesis | Economic logic check |
| B. Formalization | Quant Formalization | Hypothesis | Formal rules + pseudocode | No ambiguity |
| C. Data & Features | Data Engineer + Feature Engineer | Formal rules | Data spec + feature set | No lookahead |
| D. Backtest Design | Backtesting Engineer | Strategy + data | Test framework | Realistic costs |
| E. Backtest Run | BacktestEngine (code) | Signals + prices | Metrics + equity curve | Rejection criteria |
| F. Robustness | Risk Manager + Statistician + Auditor | Results | Risk report | Multiple checks |
| G. Decision | Research Director | All outputs | REJECT / REFINE / ADVANCE | Committee review |
| Paper | Paper Trading Agent | Approved strategy | Live config | Monitoring setup |

## Technology Stack

### Core
- **Python 3.11+** — Main language
- **LangGraph** — Agent workflow orchestration with conditional routing
- **Anthropic Claude** — LLM backbone for all agents
- **Pydantic v2** — Data validation, serialization, settings

### Data & Compute
- **ccxt** — Exchange connectivity (120+ exchanges)
- **pandas / numpy / scipy** — Numerical computing
- **vectorbt** — Vectorized backtesting (optional accelerator)

### Infrastructure
- **FastAPI** — REST API for pipeline control
- **Redis** — Caching, task queue
- **TimescaleDB** — Time-series data storage (optional)
- **Docker Compose** — Container orchestration

### Quality
- **pytest** — Testing framework
- **ruff** — Linting + formatting
- **mypy** — Static type checking
- **GitHub Actions** — CI/CD

## Data Flow

```
Exchange API (ccxt)
    │
    ▼
MarketDataFetcher (quality checks)
    │
    ▼
Feature Engineering Pipeline (lag-safe)
    │
    ▼
Signal Generation (strategy rules)
    │
    ▼
BacktestEngine (realistic costs)
    │
    ▼
RobustnessTester (stress tests)
    │
    ▼
Experiment Registry (persistent storage)
    │
    ▼
Report Generator (markdown)
```

## Key Design Decisions

1. **Agents are LLM-powered reviewers, not executors.** The actual backtesting,
   data fetching, and computation is done by deterministic Python code. Agents
   provide analysis, critique, and decision-making.

2. **Sequential pipeline with gate checks.** Each stage must pass before the
   next begins. The Research Director can halt the pipeline at any point.

3. **Auditor is independent.** The Auditor agent has no stake in the strategy
   succeeding — its job is purely adversarial.

4. **File-based registry (upgradeable).** Experiments are stored as JSON on
   disk for simplicity. The `ExperimentRegistry` interface abstracts this so
   you can swap to a database later.

5. **Cost-first backtesting.** The `BacktestEngine` applies costs by default.
   There is no way to accidentally run a backtest without fees.

## Extension Points

- **Custom agents**: Inherit from `BaseAgent`, implement `system_prompt()` and
  `build_user_prompt()`.
- **Custom data sources**: Extend `MarketDataFetcher` or create new data classes.
- **Strategy configs**: Add YAML files to `config/strategies/`.
- **Robustness checks**: Add methods to `RobustnessTester`.
- **Export formats**: Extend `reports.py` for PDF, HTML, Notion, etc.
