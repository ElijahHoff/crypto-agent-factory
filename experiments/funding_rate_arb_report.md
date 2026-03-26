# Strategy R&D Experiment Report
Generated: 2026-03-26T18:30:08.370574

## 1. Strategy Thesis
**Name:** Cross-Asset Volatility Regime Momentum
**Idea:** Trade crypto momentum based on volatility regime transitions identified through cross-asset volatility clustering patterns.
**Type:** momentum
**Timeframe:** 1d


## 2. Market Logic
**Structural Validity:** moderate
**Counterparty:** The counterparty identification is partially correct but oversimplified. Retail traders reacting to crypto-specific news are indeed one counterparty, but the more significant counterparty is likely crypto-native market makers and systematic funds using single-asset volatility models. However, the hypothesis underestimates sophisticated institutional participants who already monitor cross-asset regime shifts. The real edge may be against momentum algorithms that use backward-looking volatility measures rather than forward-looking regime indicators.
**Crowding Risk:** medium

## 3. Formal Rules
**Position Sizing:** volatility_adjusted_kelly: position_size = (expected_return / variance) * kelly_fraction * portfolio_value, capped at max_position_size_pct
**Complexity:** high
```
# Daily execution at market close

# 1. Calculate traditional market volatility regime
vix_current = get_vix_close()
bond_vol = calculate_rolling_vol(bond_prices, bond_vol_lookback)
commodity_vol = calculate_rolling_vol(commodity_prices, bond_vol_lookback)
traditional_vol_composite = 0.5 * normalize(vix_current) + 0.3 * normalize(bond_vol) + 0.2 * normalize(commodity_vol)

# 2. Determine traditional regime with smoothing
if traditional_vol_composite > vix_regime_threshold_high:
    raw_traditional_regime = 'high'
elif traditional_vol_composite < vix_regime_threshold_low:
    raw_traditional_regime = 'low'
else:
    raw_traditional_regime = 'medium'

traditional_vol_regime = ema_smooth(raw_traditional_regime, regime_smoothing_alpha)

# 3. Calculate crypto volatility regime for each asset
for asset in ['BTC', 'ETH', 'SOL', 'AVAX']:
    crypto_realized_vol = calculate_rolling_vol(asset_returns, crypto_vol_lookback)
    crypto_vol_percentile = percentile_rank(crypto_realized_vol, lookback_days)
    
    if crypto_vol_percentile > 70:
        crypto_vol_regime[asset] = 'high'
    elif crypto_vol_percentile < 30:
        crypto_vol_regime[asset] = 'low'
    else:
        crypto_vol_regime[asset] = 'medium'

# 4. Calculate cross-asset correlations
for asset in crypto_assets:
    correlation_matrix[asset] = {
        'spy': rolling_correlation(asset_returns, spy_returns, correlation_lookback),
        'tlt': rolling_correlation(asset_returns, tlt_returns, correlation_lookback),
        'dji': rolling_correlation(asset_returns, dji_returns, correlation_lookback)
    }
    cross_asset_correlation[asset] = mean(correlation_matrix[asset].values())

# 5. Generate signals
for asset in crypto_assets:
    # Long signal: traditional high vol, crypto low vol, low correlation
    if (traditional_vol_regime == 'high' and 
        crypto_vol_regime[asset] == 'low' and 
        cross_asset_correlation[asset] < correlation_threshold and
        regime_confidence > min_confidence and
        asset not in current_positions and
        bars_since_last_trade[asset] >= cooldown_bars):
        
        signal[asset] = 'long'
        expected_return[asset] = estimate_momentum_return(asset, 'long')
    
    # Short signal: traditional low vol, crypto high vol, low correlation
    elif (traditional_vol_regime == 'low' and 
          crypto_vol_regime[asset] == 'high' and 
          cross_asset_correlation[asset] < correlation_threshold and
          regime_confidence > min_confidence and
          asset not in current_positions and
          bars_since_last_trade[asset] >= cooldown_bars):
        
        signal[asset] = 'short'
        expected_return[asset] = estimate_momentum_return(asset, 'short')

# 6. Position sizing
for asset in signal.keys():
    asset_variance = calculate_rolling_variance(asset_returns, 30)
    kelly_size = (expected_return[asset] / asset_variance) * kelly_fraction
    position_size[asset] = min(kelly_size * portfolio_value, 
                              max_position_size_pct * portfolio_value / 100)

# 7. Exit logic
for asset in current_positions:
    if (crypto_vol_regime[asset] == traditional_vol_regime or
        cross_asset_correlation[asset] > correlation_exit_threshold or
        position_age[asset] > max_holding_days or
        unrealized_pnl_pct[asset] < -stop_loss_pct):
        
        exit_signal[asset] = True

# 8. Execute trades
execute_entry_orders(signal, position_size)
execute_exit_orders(exit_signal)
```

## 4. Required Data
- crypto_ohlcv: ccxt/binance @ 1d
- vix_data: yahoo_finance/CBOE @ 1d
- bond_volatility_proxy: yahoo_finance @ 1d
- commodity_volatility_proxy: yahoo_finance @ 1d
- equity_market_proxy: yahoo_finance @ 1d

## 5. Feature Set
- **vix_regime_state** [regime_indicator]: VIX regime states predict crypto momentum as institutional flows respond to traditional market volatility with lag
- **traditional_vol_composite** [volatility]: Composite traditional market volatility captures broader regime shifts that crypto markets lag in recognizing
- **crypto_realized_vol_14d** [volatility]: Short-term crypto volatility captures current regime state for comparison with traditional markets
- **crypto_vol_regime_state** [regime_indicator]: Crypto volatility regime classification enables detection of regime divergence with traditional markets
- **regime_divergence_score** [cross_sectional]: Large divergence between traditional and crypto volatility regimes indicates momentum opportunity
- **cross_asset_correlation_60d** [cross_sectional]: Low cross-asset correlation indicates crypto hasn't participated in traditional market regime shift
- **correlation_regime_threshold** [cross_sectional]: Dynamic correlation threshold adapts to changing market structure over time
- **bond_volatility_20d** [volatility]: Bond volatility captures fixed income regime shifts that affect institutional crypto allocation
- **commodity_volatility_20d** [volatility]: Commodity volatility represents inflation/macro regime shifts affecting crypto as alternative asset
- **regime_confidence_score** [regime_indicator]: Regime confidence prevents trading during uncertain regime transitions
- **crypto_momentum_5d** [price_momentum]: Short-term momentum captures initial response to regime shifts before full adaptation
- **volatility_clustering_strength** [microstructure]: Strong volatility clustering indicates regime persistence, weak clustering suggests regime change
- **traditional_momentum_5d** [price_momentum]: Traditional asset momentum indicates direction of regime shift affecting institutional flows
- **vol_of_vol_crypto** [volatility]: Volatility of volatility captures regime transition dynamics and uncertainty
- **regime_persistence_score** [regime_indicator]: Regime persistence indicates strength of regime shift and likelihood of continuation

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
**Overall Confidence:** 0.05
- [CRITICAL] Strategy assumes 95% fill rates during high volatility regime transitions when spreads widen dramatically
- [CRITICAL] Catastrophic parameter sensitivity - strategy completely breaks with minor changes
- [CRITICAL] Strategy only works in 25% of time periods - extreme regime dependency
- [HIGH] High probability of backtest overfitting with complex multi-parameter regime model
- [HIGH] Strategy shows massive volatility (200%+) making Sharpe comparisons meaningless
- [MEDIUM] Potential lookahead bias in regime confidence scoring and correlation thresholds
- [MEDIUM] SOL and AVAX selection creates survivorship bias - only successful crypto assets included
- [HIGH] Excessive complexity with 15 features, regime models, and cross-asset dependencies
- [CRITICAL] Strategy exhibits institutional-grade risk management failures

## 10. Decision
**Decision:** reject
**Reasoning:** This strategy exhibits catastrophic risk characteristics that make it unsuitable for any institutional deployment. The 62% maximum drawdown with 8,594 days underwater represents institutional suicide-level risk. More critically, the strategy fails in 75% of time periods (6/8 walk-forward periods show negative Sharpe), indicating the edge is either non-existent or extremely fragile. The strategy's complete breakdown under realistic transaction costs (Sharpe drops to -2.249 with 2x fees) and execution delays (Sharpe becomes -0.703 with 1-bar delay) strongly suggests backtest overfitting rather than a genuine edge. With only 166 trades across a complex multi-parameter regime model, the probability of false discovery is extremely high (~85% PBO). The economic logic assumes crypto consistently lags traditional market regime shifts, but this relationship clearly breaks down regularly, making the strategy fundamentally unreliable.
**Confidence:** high
