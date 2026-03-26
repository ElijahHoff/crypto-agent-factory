# Strategy R&D Experiment Report
Generated: 2026-03-26T17:42:59.908413

## 1. Strategy Thesis
**Name:** Cross-Exchange Funding Rate Momentum
**Idea:** Trade perpetual futures momentum based on diverging funding rates across exchanges, exploiting delayed arbitrage and capital constraints.
**Type:** momentum
**Timeframe:** 1h


## 2. Market Logic
**Structural Validity:** strong
**Counterparty:** The losing counterparty is typically the exchange-specific whale or institutional trader creating the funding divergence through concentrated positioning. They lose because: (1) they're paying extreme funding rates while holding directional exposure, (2) their position size creates local supply/demand imbalance that eventually self-corrects through liquidations or forced unwinding, and (3) they often lack cross-exchange arbitrage capabilities due to operational constraints or risk limits. The strategy profits by front-running the inevitable position adjustment that normalizes funding rates.
**Crowding Risk:** medium

## 3. Formal Rules
**Position Sizing:** volatility_adjusted: position_size = (target_risk_pct * portfolio_value) / (asset_volatility_20d * sqrt(252))
**Complexity:** high
```
# Cross-Exchange Funding Rate Momentum Strategy

def calculate_funding_metrics(asset, timestamp):
    funding_rates = {}
    for exchange in EXCHANGES:
        funding_rates[exchange] = get_funding_rate(exchange, asset, timestamp)
    
    # Calculate cross-exchange statistics
    rates_list = list(funding_rates.values())
    median_rate = np.median(rates_list)
    std_rate = np.std(rates_list)
    
    # Find most divergent exchange
    max_divergence = 0
    target_exchange = None
    for exchange, rate in funding_rates.items():
        divergence = abs(rate - median_rate)
        if divergence > max_divergence:
            max_divergence = divergence
            target_exchange = exchange
    
    # Calculate z-score and trend
    target_rate = funding_rates[target_exchange]
    zscore = (target_rate - median_rate) / std_rate if std_rate > 0 else 0
    
    # Calculate 8-hour trend
    historical_zscores = get_historical_zscores(asset, target_exchange, 8)
    trend_8h = np.polyfit(range(len(historical_zscores)), historical_zscores, 1)[0]
    
    return zscore, trend_8h, target_exchange, funding_rates

def check_entry_conditions(asset, timestamp):
    zscore, trend_8h, target_exchange, funding_rates = calculate_funding_metrics(asset, timestamp)
    
    # Check liquidity on normal funding exchange
    normal_exchange = find_normal_funding_exchange(funding_rates)
    liquidity = get_orderbook_depth(normal_exchange, asset)
    
    if liquidity < min_liquidity_threshold:
        return None
    
    # Long signal
    if (zscore > divergence_threshold and 
        trend_8h > trend_threshold):
        return {
            'direction': 'long',
            'entry_exchange': normal_exchange,
            'target_exchange': target_exchange,
            'signal_strength': zscore
        }
    
    # Short signal  
    if (zscore < -divergence_threshold and 
        trend_8h < -trend_threshold):
        return {
            'direction': 'short',
            'entry_exchange': normal_exchange,
            'target_exchange': target_exchange,
            'signal_strength': abs(zscore)
        }
    
    return None

def calculate_position_size(asset, signal_strength, portfolio_value):
    volatility = calculate_volatility(asset, volatility_lookback_days)
    base_size = (target_risk_per_trade_pct / 100) * portfolio_value
    vol_adjusted_size = base_size / (volatility * np.sqrt(252))
    
    # Scale by signal strength
    final_size = vol_adjusted_size * min(signal_strength / 2.0, 1.5)
    
    return min(final_size, max_position_size_pct / 100 * portfolio_value)

def check_exit_conditions(position):
    current_zscore, _, _, _ = calculate_funding_metrics(position.asset, current_time)
    
    # Convergence exit
    if abs(current_zscore) < exit_convergence_threshold:
        return 'convergence_exit'
    
    # Time exit
    if position.age_hours >= max_hold_hours:
        return 'time_exit'
    
    # PnL exits
    pnl_pct = position.unrealized_pnl_pct
    if pnl_pct <= -stop_loss_pct:
        return 'stop_loss'
    if pnl_pct >= take_profit_pct:
        return 'take_profit'
    
    return None

def main_strategy_loop():
    for timestamp in trading_hours:
        # Check kill switches
        if any_kill_switch_triggered():
            close_all_positions()
            continue
        
        # Process each asset
        for asset in UNIVERSE:
            # Skip if in cooldown
            if in_cooldown(asset, timestamp):
                continue
            
            # Check for new entries
            if not has_position(asset):
                signal = check_entry_conditions(asset, timestamp)
                if signal:
                    size = calculate_position_size(asset, signal['signal_strength'], portfolio_value)
                    enter_position(asset, signal['direction'], size, signal['entry_exchange'])
            
            # Check exits for existing positions
            else:
                position = get_position(asset)
                exit_reason = check_exit_conditions(position)
                if exit_reason:
                    close_position(position, exit_reason)
```

## 4. Required Data
- funding_rates_multi_exchange: ccxt/binance,bybit,okx,deribit,ftx_historical @ 1h
- perpetual_ohlcv_multi_exchange: ccxt/binance,bybit,okx,deribit @ 1h
- orderbook_snapshots_multi_exchange: ccxt/binance,bybit,okx,deribit @ 1h
- exchange_status_monitoring: custom/exchange_apis @ 5min
- perpetual_contract_specs: custom/exchange_apis @ daily

## 5. Feature Set
- **funding_divergence_zscore** [funding_basis]: Extreme funding rate divergence signals localized demand imbalances that precede directional moves as arbitrage is constrained by capital and risk limits
- **funding_divergence_trend_8h** [funding_basis]: Increasing divergence trend indicates accelerating imbalance that hasn't been arbitraged, suggesting momentum continuation
- **cross_exchange_funding_correlation_7d** [funding_basis]: Low correlation indicates market fragmentation and arbitrage inefficiency, creating opportunities for divergence-based strategies
- **funding_rate_volatility_24h** [funding_basis]: High funding rate volatility indicates unstable positioning and increased likelihood of extreme divergences
- **target_exchange_liquidity_depth** [microstructure]: Sufficient liquidity on normal funding exchange is required for execution without significant slippage
- **cross_exchange_basis_spread** [funding_basis]: Wide basis spreads indicate arbitrage constraints and potential for funding divergence persistence
- **funding_rate_regime_indicator** [regime_indicators]: High regime indicator suggests persistent directional funding pressure, increasing divergence probability
- **exchange_relative_volume_1h** [volume]: Concentrated volume on one exchange may drive localized funding pressure before spreading to other venues
- **funding_payment_proximity** [funding_basis]: Funding divergence effects may be stronger near payment times as traders adjust positions to avoid extreme rates
- **price_momentum_1h** [price_momentum]: Price momentum may amplify funding divergence as directional pressure concentrates on specific exchanges
- **volatility_adjusted_divergence** [funding_basis]: Volatility-adjusted divergence accounts for market conditions - same divergence is more significant in low vol environments
- **exchange_downtime_indicator** [microstructure]: Exchange technical issues can create artificial funding divergence that should be filtered out

## 6. Backtest Design
Train/Val/Test: 0.5/0.25/0.25
Costs: 12.0bps commission + 8.0bps slippage

## 7. Risk Controls
**Overall Risk:** high
Daily Loss Limit: 1.5%
Max Leverage: 1.5

## 8. Validation Plan
**Confidence:** low
**P(Random):** 1.0
**Recommendation:** reject

## 9. Failure Modes (Audit)
**Audit Result:** fail
**Overall Confidence:** 0.05
- [CRITICAL] NO BACKTEST EXECUTION - Strategy is purely theoretical blueprint with zero empirical validation
- [CRITICAL] Extreme implementation complexity with 12+ features, multi-exchange coordination, and 4+ optimizable parameters
- [HIGH] Assumes ability to execute cross-exchange arbitrage with 95% fill rates and 250ms latency during funding divergences
- [HIGH] Strategy completely dependent on funding rate volatility regime with no validation across different market conditions
- [HIGH] FTX collapse creates survivorship bias in cross-exchange analysis from November 2022 onwards
- [MEDIUM] 4+ hyperparameters (divergence_threshold, trend_threshold, max_hold_hours, exit_convergence_threshold) with no robustness testing
- [MEDIUM] Potential lookahead bias in funding rate trend calculations and cross-exchange synchronization
- [MEDIUM] No comparison to realistic benchmarks - proposed benchmarks include theoretical 'cross_exchange_arbitrage' upper bound
- [LOW] Strategy requires proprietary multi-exchange infrastructure that most practitioners cannot replicate

## 10. Decision
**Decision:** reject
**Reasoning:** This submission is a theoretical blueprint with zero empirical validation masquerading as a tested strategy. The audit reveals critical flaws: no actual backtest was executed (status: 'blueprint_generated'), making all performance claims purely speculative. The strategy exhibits extreme complexity requiring real-time coordination across 4+ exchanges with 18+ technical requirements, yet assumes unrealistic 95% fill rates during funding stress periods when liquidity typically deteriorates. The FTX collapse creates survivorship bias in cross-exchange calculations from Nov 2022 onwards, undermining the core premise. With 4+ optimizable parameters and no robustness testing, overfitting risk is severe. The economic logic depends entirely on funding rate volatility regimes with no validation across market conditions. This represents exactly the type of over-engineered, under-validated strategy that destroys capital.
**Confidence:** high
