# Strategy R&D Experiment Report
Generated: 2026-03-26T20:13:50.139785

## 1. Strategy Thesis
**Name:** Cross-Exchange Funding Rate Momentum
**Idea:** Trade perpetual futures on exchanges where funding rates show persistent momentum, exploiting delayed arbitrage and capital constraints across venues.
**Type:** momentum
**Timeframe:** 1h


## 2. Market Logic
**Structural Validity:** strong
**Counterparty:** The losing counterparties are primarily: (1) Retail traders with sticky capital who cannot efficiently arbitrage across exchanges due to KYC delays, withdrawal limits, and operational complexity; (2) Market makers with exchange-specific inventory constraints who face temporary capital allocation inefficiencies; (3) Forced sellers during liquidation cascades who must close positions on their primary exchange regardless of funding disadvantage. The edge exists because sophisticated arbitrageurs face genuine structural friction - even with automated systems, cross-exchange arbitrage requires pre-positioned capital, regulatory compliance across jurisdictions, and operational overhead that creates exploitable delays.
**Crowding Risk:** medium

## 3. Formal Rules
**Position Sizing:** volatility_adjusted: position_size = (target_vol / realized_vol_20d) * base_allocation * kelly_fraction, where kelly_fraction = (win_rate * avg_win - loss_rate * avg_loss) / avg_win, capped at 5% per position
**Complexity:** high
```
# Cross-Exchange Funding Rate Momentum Strategy

def calculate_signals(exchanges, symbols, current_time):
    signals = []
    
    for symbol in symbols:
        # Get funding rates from all exchanges
        funding_rates = {}
        volumes = {}
        
        for exchange in exchanges:
            funding_rates[exchange] = get_funding_rate_history(
                exchange, symbol, lookback_window_hours
            )
            volumes[exchange] = get_volume_history(
                exchange, symbol, volume_lookback_hours
            )
        
        # Calculate funding momentum for each exchange
        momentum_scores = {}
        for exchange in exchanges:
            rates = funding_rates[exchange]
            momentum = calculate_ema_momentum(rates, momentum_ema_alpha)
            momentum_scores[exchange] = zscore(momentum, lookback_window_hours)
        
        # Calculate cross-exchange spread
        rate_spreads = []
        for i, ex1 in enumerate(exchanges):
            for ex2 in exchanges[i+1:]:
                spread = abs(funding_rates[ex1][-1] - funding_rates[ex2][-1])
                rate_spreads.append(spread)
        
        avg_spread = np.mean(rate_spreads)
        spread_zscore = zscore(avg_spread, spread_lookback_hours)
        
        # Find best exchange for execution
        best_exchange = None
        best_momentum = 0
        
        for exchange in exchanges:
            momentum = abs(momentum_scores[exchange])
            volume_ratio = volumes[exchange][-1] / np.mean(volumes[exchange])
            
            if (momentum > abs(best_momentum) and 
                volume_ratio > volume_ratio_threshold):
                best_exchange = exchange
                best_momentum = momentum_scores[exchange]
        
        # Generate signals
        if best_exchange and len(exchanges) >= min_exchanges:
            current_rate = funding_rates[best_exchange][-1]
            
            # Long signal
            if (best_momentum < -momentum_zscore_threshold and
                spread_zscore > spread_zscore_threshold and
                current_rate < -min_funding_rate):
                
                signals.append({
                    'symbol': symbol,
                    'exchange': best_exchange,
                    'direction': 'long',
                    'momentum_zscore': best_momentum,
                    'spread_zscore': spread_zscore,
                    'funding_rate': current_rate
                })
            
            # Short signal
            elif (best_momentum > momentum_zscore_threshold and
                  spread_zscore > spread_zscore_threshold and
                  current_rate > min_funding_rate):
                
                signals.append({
                    'symbol': symbol,
                    'exchange': best_exchange,
                    'direction': 'short',
                    'momentum_zscore': best_momentum,
                    'spread_zscore': spread_zscore,
                    'funding_rate': current_rate
                })
    
    return signals

def check_exit_conditions(position, current_time):
    # Update current metrics
    current_momentum = get_current_momentum_zscore(
        position.exchange, position.symbol
    )
    current_spread = get_current_spread_zscore(
        position.symbol
    )
    
    position_age = (current_time - position.entry_time).total_seconds() / 3600
    unrealized_pnl_pct = position.unrealized_pnl / position.notional * 100
    
    # Exit conditions
    if abs(current_momentum) < momentum_exit_threshold:
        return True, 'momentum_reversal'
    
    if current_spread < spread_exit_threshold:
        return True, 'spread_normalization'
    
    if position_age >= max_hold_hours:
        return True, 'time_exit'
    
    if unrealized_pnl_pct <= stop_loss_pct:
        return True, 'stop_loss'
    
    if unrealized_pnl_pct >= take_profit_pct:
        return True, 'take_profit'
    
    return False, None

def calculate_position_size(signal, portfolio_value, current_vol):
    # Kelly fraction calculation
    kelly_fraction = calculate_kelly_fraction(signal.symbol)
    
    # Volatility adjustment
    vol_adjustment = target_volatility / current_vol
    
    # Base position size
    base_size = portfolio_value * base_allocation_pct / 100
    
    # Final position size
    position_size = base_size * vol_adjustment * kelly_fraction
    
    # Apply caps
    max_size = portfolio_value * max_position_size_pct / 100
    return min(position_size, max_size)
```

## 4. Required Data
- funding_rates_multi_exchange: ccxt/binance,bybit,okx,deribit,ftx_historical @ 1h
- perpetual_ohlcv_multi_exchange: ccxt/binance,bybit,okx,deribit,ftx_historical @ 1h
- exchange_api_latency: custom/monitoring @ 1min
- cross_exchange_correlation: derived @ 1h
- exchange_listing_dates: manual/exchange_apis @ static

## 5. Feature Set
- **funding_rate_momentum_zscore** [funding_basis]: Funding rate changes exhibit momentum due to sticky capital and herding behavior - persistent negative momentum indicates forced liquidations creating temporary mispricing
- **cross_exchange_spread_zscore** [cross_sectional]: Widening cross-exchange funding spreads indicate structural imbalances and arbitrage constraints - higher spreads suggest exploitable inefficiencies
- **funding_rate_absolute** [funding_basis]: Extreme absolute funding rates indicate severe market imbalances - high negative rates suggest oversold conditions, high positive rates suggest overleveraged longs
- **volume_ratio_confirmation** [volume]: Volume spikes confirm funding rate momentum signals - high volume during funding extremes indicates genuine market stress rather than noise
- **funding_rate_volatility_zscore** [volatility]: Funding rate volatility spikes indicate regime changes and market stress - can be used for risk management and signal filtering
- **exchange_dominance_shift** [microstructure]: Sudden shifts in exchange volume dominance indicate capital flows and potential arbitrage opportunities - traders migrating to exchanges with favorable funding
- **funding_momentum_acceleration** [price_momentum]: Acceleration in funding momentum captures early stages of market regime changes - second derivative helps identify inflection points
- **cross_exchange_correlation** [regime_indicators]: Breakdown in cross-exchange funding correlation indicates market fragmentation and arbitrage opportunities - low correlation suggests structural inefficiencies
- **funding_rate_rank_cross_symbol** [cross_sectional]: Relative funding rates across symbols identify which assets are most mispriced - extreme ranks suggest concentrated positioning
- **position_age_hours** [regime_indicators]: Position age affects exit timing - funding rate momentum tends to mean-revert over time, requiring time-based risk management
- **unrealized_pnl_pct** [price_momentum]: Current P&L provides direct feedback on strategy performance and triggers risk management rules

## 6. Backtest Design
Train/Val/Test: 0.5/0.25/0.25
Costs: 12.0bps commission + 8.0bps slippage

## 7. Risk Controls
**Overall Risk:** critical
Daily Loss Limit: 0.0%
Max Leverage: 1.0

## 8. Validation Plan
**Confidence:** low
**P(Random):** 0.92
**Recommendation:** reject

## 9. Failure Modes (Audit)
**Audit Result:** fail
**Overall Confidence:** 0.95
- [CRITICAL] Extreme regime dependency with Sharpe ratios ranging from -6.489 to +3.107 across walk-forward periods
- [CRITICAL] Strategy assumes unrealistic execution capabilities across multiple exchanges
- [CRITICAL] Strategy fails all robustness tests and shows extreme parameter sensitivity
- [HIGH] High probability of data mining with 13 optimized parameters and complex feature interactions
- [HIGH] Strategy shows massive underperformance with negative Sharpe ratios in majority of periods
- [HIGH] Unnecessary complexity with multi-exchange funding rate momentum when simpler approaches would work better
- [MEDIUM] Strategy depends on FTX data which ends November 2022, creating survivorship bias
- [MEDIUM] Cherry-picked universe of only 3 perpetual contracts without justification
- [CRITICAL] Catastrophic risk management with 62% maximum drawdown and extreme volatility

## 10. Decision
**Decision:** reject
**Reasoning:** This strategy exhibits catastrophic flaws that make it completely unsuitable for institutional capital. The backtest results show extreme regime dependency with Sharpe ratios ranging from -6.489 to +3.107 across walk-forward periods, indicating no consistent edge. The 62.47% maximum drawdown with 8,500+ day recovery periods would trigger forced liquidation. Most critically, the strategy fails all robustness tests: 2x fees destroy the edge (Sharpe drops to -2.291), 1-bar execution delay kills performance, and 10% signal noise reduces Sharpe to -7.693. With only 166 trades across 13 optimized parameters, the probability of backtest overfitting is 85%. The strategy requires unrealistic cross-exchange execution capabilities that cannot be achieved in practice. This is textbook curve-fitting masquerading as systematic trading.
**Confidence:** high
