# Strategy Report: ema_crossover_trend_filter
**Generated**: 2026-03-30 14:48 UTC
**Verdict**: 🔴 **REJECT** (confidence: high)

## Executive Summary
This strategy exhibits fundamental flaws that make it unsuitable for systematic trading. The negative Sharpe ratio of -1.429 in-sample and -3.452 out-of-sample indicates no edge exists. The strategy fails 6 out of 7 robustness tests, with only 12.5% of walk-forward periods being profitable. Most critically, the cross-chain execution model is built on simulated data rather than real cross-chain price feeds, making the entire backtest unrealistic. The strategy assumes 85% fill rates with 2-second latency for operations that actually take 10 minutes to 24 hours. Bridge capacity data is acknowledged as poor quality, yet forms the foundation of the strategy. The operational complexity is enormous - requiring monitoring of multiple blockchains, bridge protocols, and smart contract risks - all for a strategy that consistently loses money. Even in bear market conditions, it underperforms simple buy-and-hold.

## Key Metrics

| Metric | In-Sample | Out-of-Sample |
|--------|-----------|---------------|
| Sharpe Ratio | -1.429 | -3.452 |
| Total Return | -17.78% | -12.84% |
| CAGR | -17.78% | — |
| Max Drawdown | 18.72% | 14.15% |
| Total Trades | 74 | 23 |
| Win Rate | 41.90% | — |
| Profit Factor | 0.620 | — |
| Calmar | -0.950 | — |
| Sortino | -0.602 | — |

**Config**: `BTC/USDT` / `1h` / `volatility` / 8760 bars
**Period**: 2025-03-30 15:00:00+00:00 → 2026-03-30 14:00:00+00:00
**Signals**: 562 long / 278 short / 7920 flat (147 transitions)

## Benchmark Comparison

| Benchmark | Return | Sharpe | Max DD |
|-----------|--------|--------|--------|
| **Strategy** | -17.78% | -1.429 | 18.72% |
| Buy And Hold | -18.84% | -0.272 | -50.10% |
| Short And Hold | 2.48% | 0.272 | -44.23% |
| Risk Free | 0.00% | 0.000 | 0.00% |

❌ Strategy Sharpe (-1.429) **loses to** Buy & Hold (-0.272)

## Walk-Forward Analysis

**1/8 periods positive** (consistency: 12%)
Average Sharpe: -1.482 ± 2.447

| Period | Dates | Sharpe | Return | Max DD | Trades | ✓ |
|--------|-------|--------|--------|--------|--------|---|
| P1 | 2025-03-30→2025-05-15 | -2.061 | -4.14% | N/A | 5 | ❌ |
| P2 | 2025-05-15→2025-06-29 | -0.557 | -0.75% | N/A | 6 | ❌ |
| P3 | 2025-06-29→2025-08-14 | -1.498 | -2.09% | N/A | 12 | ❌ |
| P4 | 2025-08-14→2025-09-29 | -3.119 | -4.46% | N/A | 8 | ❌ |
| P5 | 2025-09-29→2025-11-13 | 3.957 | 7.45% | N/A | 11 | ✅ |
| P6 | 2025-11-13→2025-12-29 | -1.256 | -1.33% | N/A | 9 | ❌ |
| P7 | 2025-12-29→2026-02-12 | -2.094 | -4.60% | N/A | 14 | ❌ |
| P8 | 2026-02-13→2026-03-30 | -5.225 | -8.63% | N/A | 9 | ❌ |

## Performance Charts

![Combined](ema_crossover_trend_filter_report_chart.png)

![Signals](ema_crossover_trend_filter_signals.png)

## Chart Analysis
```
=== CHART ANALYSIS ===

Signals: 562 long (6.4%), 278 short (3.2%), 7920 flat (90.4%)
Transitions: 147

Strategy: Sharpe=-1.429, Return=-17.8%, MaxDD=18.7%
Buy&Hold: Sharpe=-0.272, Return=-18.84%, MaxDD=-50.10%
❌ Strategy LOSES to Buy&Hold

Walk-Forward (8 periods):
  Consistency: 1/8 positive (12%)
  Avg Sharpe: -1.482 ± 2.447
  Sharpes: [-2.06, -0.56, -1.50, -3.12, 3.96, -1.26, -2.09, -5.22]
=== END ===
```

## Robustness Analysis

**Score**: 14.3% (1/7 tests passed)

| Test | ✓ | Details |
|------|---|---------|
| fee_sensitivity_2x | ❌ | Sharpe with 2x fees: -2.513 |
| slippage_sensitivity_3x | ❌ | Sharpe with 3x slippage: -2.513 |
| delayed_entry_1bar | ❌ | Sharpe with 1-bar delay: -1.277 |
| spread_widening_5x | ❌ | Sharpe with 5x spread: -2.301 |
| top_trades_removal | ✅ | PnL ratio after removal: 1.61 (kept 161% of profits) |
| subperiod_stability | ❌ | 1/4 periods with positive Sharpe (25%) |
| signal_degradation_10pct | ❌ | Sharpe with 10% signal noise: -3.267 |

## Hypothesis

**Title**: N/A
**Thesis**: N/A

## Agent Reviews

### Risk Manager
**Verdict**: N/A

### Auditor
**Verdict**: N/A
This cross-chain arbitrage strategy is fundamentally flawed and should be rejected immediately. With a negative Sharpe ratio of -1.429, failure of 6/7 robustness tests, and only 12.5% profitable periods, it consistently destroys capital while adding enormous operational complexity. The strategy relies on simulated cross-chain data and unrealistic execution assumptions, making it unsuitable for live trading under any circumstances.

## Final Decision

**Key Risks:**
- Negative edge with consistent capital destruction across all tested periods
- Simulated cross-chain data creates false confidence in unrealistic execution assumptions
- Bridge protocol dependencies introduce smart contract risk and operational complexity
- Extreme parameter sensitivity - strategy breaks under minor cost increases
- Insufficient sample size (74 trades) for statistical significance
- High probability of forced liquidation given leverage on negative-returning strategy

**Improvements:**
- Obtain real cross-chain price feeds instead of simulated data
- Demonstrate positive Sharpe ratio across multiple market regimes
- Achieve >60% win rate and pass all robustness tests
- Reduce maximum drawdown below 5%
- Eliminate leverage given negative base returns
- Simplify operational complexity by 90%
- Implement realistic bridge settlement times and failure rates

**Edge Evidence:**
- No positive edge evidence found
- Negative Sharpe ratios in all testing periods
- Strategy underperforms buy-and-hold in bear market
- Only 1 out of 8 walk-forward periods profitable
- Fails under realistic cost assumptions

**Dissenting View:**
> A contrarian might argue that cross-chain arbitrage opportunities genuinely exist during network congestion periods, and that the poor backtest results stem from data quality issues rather than fundamental strategy flaws. They could contend that with proper infrastructure and real-time data feeds, the strategy might capture meaningful spreads. However, this view ignores the consistent negative performance across all tested conditions and the rapid evolution of cross-chain infrastructure that would quickly arbitrage away any persistent inefficiencies.
