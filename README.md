# Crypto Agent Factory

A systematic crypto trading strategy R&D pipeline powered by AI agents. The system generates trading hypotheses, writes executable signal code, backtests on real market data, stress-tests results, and learns from past experiments to improve over time.

This is not a trading bot. It is a research factory that automates the scientific process of strategy discovery: hypothesis generation, formalization, testing, and rejection of ideas that don't work.

## How It Works

The pipeline runs 12 AI agents in sequence, each with a specific role:

```
Strategy Ideation --> Market Analyst --> Quant Formalization --> Data Engineer
     --> Feature Engineer --> Backtest Engineer --> [Live Backtest on Real Data]
     --> Risk Manager --> Statistician --> Auditor --> Research Director --> Decision
```

The key innovation is in Stage E (Live Backtest): instead of mapping strategy names to hardcoded signal generators, the system asks Claude to write executable Python code for each strategy. If the code produces a negative Sharpe ratio, the system sends the results back to Claude with feedback ("you lost money, the market is bearish, you had too many long signals") and asks it to rewrite the code. This loop runs up to 5 times per strategy.

After signal generation, the best code goes through a parameter sweep (50+ combinations), gets filtered by a 4h trend overlay, and faces a full battery of robustness tests. Results are saved to a persistent memory file so that future runs can learn from past failures.

## Architecture

```
src/
  agents/              12 AI agents (LangGraph + Anthropic Claude)
    base.py            Base agent with retry logic
    strategy_ideation.py
    market_analyst.py
    quant_formalization.py   Generates executable signal code
    data_engineer.py
    feature_engineer.py
    backtesting_engineer.py
    risk_manager.py
    statistician.py
    auditor.py
    research_director.py     Final go/no-go decision

  backtesting/
    __init__.py              BacktestEngine (realistic costs, IS/OOS split)
    signal_generator.py      5 built-in signal types (fallback)
    signal_sandbox.py        Unrestricted code execution with timeout
    iterative_signals.py     Claude writes code --> tests --> improves (5 iterations)
    experiment_memory.py     Persists learnings across runs (JSON)
    param_sweep.py           Grid search over 50+ parameter combinations
    multi_timeframe.py       4h EMA trend filter on 1h signals
    robustness.py            7 stress tests (fees, slippage, noise, subperiods)
    benchmark.py             Buy and Hold comparison
    walk_forward.py          8-period walk-forward validation
    charts.py                5-panel strategy charts
    multi_asset.py           BTC/ETH/SOL/BNB portfolio construction
    portfolio_charts.py      Per-asset equity curves, correlation heatmap, portfolio comparison
    live_runner.py           Main orchestrator

  data/                      MarketDataFetcher (ccxt/Binance, free public API)
  models/                    Pydantic v2 models (BacktestMetrics, RobustnessReport, etc.)
  pipeline/                  LangGraph state machine orchestration
  utils/reports.py           Crash-proof markdown report generator
  config.py                  Settings (API keys, model selection)
  cli.py                     Typer CLI

experiments/                 Reports, charts, memory.json
```

## Tech Stack

- LangGraph for agent orchestration
- Anthropic Claude Sonnet 4 for AI reasoning and code generation
- ccxt for market data (Binance public API, no auth needed)
- Pydantic v2 for data validation
- matplotlib for charts
- Typer + Rich for CLI
- Python 3.10+

## Setup

```bash
git clone https://github.com/ElijahHoff/crypto-agent-factory.git
cd crypto-agent-factory
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Set your Anthropic API key:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

Or create `.env`:

```
ANTHROPIC_API_KEY=sk-ant-...
```

## Usage

Run a single strategy:

```bash
agentfactory run -s adaptive_momentum --verbose
```

Run a batch:

```bash
for s in ema_trend_filter breakout_atr_stop rsi_volume_divergence multi_roc_momentum; do
  agentfactory run -s $s --verbose
done
```

Check experiment memory (what the system has learned):

```bash
cat experiments/memory.json | python3 -c "
import json,sys
data=json.load(sys.stdin)
for e in sorted(data, key=lambda x: x['sharpe'], reverse=True):
    print(f'{e[\"sharpe\"]:+.3f}  {e[\"strategy_name\"]:35s}  trades={e.get(\"n_trades\",0)}')
"
```

## What Happens During a Run

1. Strategy Ideation agent generates a trading hypothesis based on the strategy name.
2. Market Analyst assesses current market conditions.
3. Quant Formalization agent writes executable Python signal code.
4. Data and Feature Engineers specify data requirements.
5. Backtest Engineer designs the test protocol.
6. Live Backtest executes on real data:
   - Fetches 2 years of hourly OHLCV data from Binance (17,520 bars).
   - Fetches 4h data for trend filtering.
   - Claude writes signal code adapted to detected market regime (bear/bull/sideways).
   - If Sharpe < 0, Claude rewrites with feedback (up to 5 iterations).
   - Parameter sweep tests 50+ combinations of the best code.
   - 4h EMA(50/200) trend filter removes counter-trend signals.
   - Full backtest with realistic transaction costs (17bps round-trip).
   - 7 robustness tests (2x fees, 3x slippage, delayed entry, signal noise, etc.).
   - Walk-forward validation (8 periods).
   - Multi-asset portfolio (BTC, ETH, SOL, BNB) with 3 weighting methods.
7. Risk Manager, Statistician, and Auditor review independently.
8. Research Director makes final accept/reject decision.
9. Results saved to experiment memory for future runs.
10. Full report (markdown), strategy chart, portfolio chart, and per-asset chart generated.

## Output Files

Each run produces:

```
experiments/
  {strategy}_report.md              Full markdown report with metrics tables
  {strategy}_report_chart.png       5-panel chart (price+signals, equity, drawdown, rolling Sharpe, walk-forward)
  {strategy}_portfolio_chart.png    4-panel portfolio (per-asset Sharpe, portfolio comparison, correlation, weights)
  {strategy}_per_asset_chart.png    Individual equity curve for each asset with drawdown overlay
  {strategy}_signals.png            Signal entry/exit points on price chart
  memory.json                       Accumulated experiment results
```

## Experiment Memory

The system maintains a JSON file of past experiment results. Each run adds an entry with strategy name, Sharpe ratio, number of trades, failure reason, and a code snippet. When generating new strategies, Claude receives this history and is instructed to avoid approaches that already failed and build on approaches that showed promise.

Example memory after several runs:

```
+0.675  multi_roc_momentum              trades=2
-1.351  ema_trend_filter                trades=16
-1.485  breakout_atr_stop               trades=36
-2.093  donchian_breakout               trades=814
-2.907  rsi_volume_divergence           trades=431
-4.072  adaptive_momentum               trades=267
```

## Costs

- Market data: free (Binance public API)
- AI: approximately $0.30-0.60 per strategy run (5 iterations with Claude Sonnet 4)
- A batch of 10 strategies costs roughly $3-6
- Prepaid Anthropic credits at console.anthropic.com

## Version History

- v0.1-v0.2 -- Initial 47-file project, real-data backtesting via ccxt
- v0.3-v0.4 -- 5 signal types, matplotlib charts, Buy and Hold benchmark, walk-forward validation
- v0.5 -- Fixed report generation, strategy classifier, API retry, correct field mappings
- v0.6 -- Agent-generated signals via sandbox execution
- v0.7 -- Iterative signal generation (Claude writes, tests, improves up to 5 times)
- v0.8 -- Multi-asset portfolio (BTC/ETH/SOL/BNB), 2-year history, 3 weighting methods
- v0.9 -- Experiment memory, parameter sweep (50 combos), multi-timeframe (4h trend filter), per-asset charts

## Limitations

All strategies tested so far have negative in-sample Sharpe ratios, with one exception (multi_roc_momentum at +0.675 with only 2 trades). This is expected: finding profitable systematic strategies is genuinely difficult, and the system is doing its job by correctly rejecting bad ideas.

Claude sometimes wraps signal code in classes instead of a bare function, causing sandbox execution to fail. The system falls back to built-in signals in those cases.

No live trading capability. This is a research tool.

Market data is limited to OHLCV. Funding rates, orderbook depth, and on-chain data are not available through the current data pipeline.

## License

MIT
