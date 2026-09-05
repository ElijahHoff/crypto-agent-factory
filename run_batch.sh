#!/bin/bash
STRATEGIES=(
  simple_roc_trend_v2
  ema_slow_trend
  donchian_atr_v2
  bollinger_squeeze_v2
  rsi_divergence_vol
  adaptive_regime_switch
  momentum_roc_filtered
  mean_reversion_ranging
  breakout_volume_confirm
  triple_ema_adx
  vwap_deviation_trade
  atr_channel_follow
  obv_trend_confirm
  macd_histogram_flip
  keltner_squeeze_v2
)

round=1
while true; do
  echo "━━━ Round $round ━━━"
  for s in "${STRATEGIES[@]}"; do
    echo "▶ $(date '+%H:%M') Running: ${s}_r${round}"
    agentfactory run -s "${s}_r${round}" --verbose 2>&1 | grep -E "Attempt|Sweep|Result|Best portfolio|Decision:"
    if [ $? -ne 0 ]; then
      echo "❌ Failed — stopping."
      exit 1
    fi
    echo ""
  done

  echo "━━━ LEADERBOARD after round $round ━━━"
  cat experiments/memory.json | python3 -c "
import json,sys
data=json.load(sys.stdin)
def ho(e): return e.get('holdout_sharpe') if e.get('holdout_sharpe') is not None else -99
data.sort(key=ho, reverse=True)
print('  holdout  PSR   WFE   dev     name                                 holdout_trades')
for e in data[:10]:
    print(f\"  {ho(e):+.3f}  {e.get('psr',0):.2f}  {e.get('wf_efficiency',0):.2f}  {e.get('dev_sharpe') or e['sharpe']:+.3f}  {e['strategy_name']:35s}  {e.get('holdout_trades',0)}  {e.get('key_failure','')}\")
print(f'  Total: {len(data)} experiments')
"

  git add -A && git commit -m "batch round $round" && git push -f origin main 2>/dev/null
  round=$((round + 1))
done
