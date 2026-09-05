import numpy as np, pandas as pd, sys
sys.path.insert(0, '.')
from src.backtesting.multi_timeframe import compute_trend_filter, apply_trend_filter

def synth(seed, n=17520):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    r = rng.normal(0, 0.006, n)          # zero drift random walk, ~55% ann vol
    close = 100*np.exp(np.cumsum(r))
    o = np.r_[close[0], close[:-1]]
    return pd.DataFrame({"open":o,"high":np.maximum(o,close)*1.001,"low":np.minimum(o,close)*0.999,"close":close,"volume":1.0}, index=idx)

def to4h(p):  # ccxt-style: label = bar OPEN time
    return p.resample("4h", label="left", closed="left").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"})

def sharpe(p, pos):
    r = p["close"].pct_change().fillna(0) * pos.shift(1).fillna(0)
    return r.mean()/r.std()*np.sqrt(8760) if r.std()>0 else 0

leak, fixed = [], []
for s in range(30):
    p = synth(s); h = to4h(p)
    trend = compute_trend_filter(h)
    # current code: ffill by open-time label -> 1h bars inside the 4h bar see its close
    pos_leak = trend.reindex(p.index, method="ffill").fillna(0)
    # fixed: shift label to bar CLOSE time before ffill
    t_fixed = trend.copy(); t_fixed.index = t_fixed.index + pd.Timedelta("4h")
    pos_fixed = t_fixed.reindex(p.index, method="ffill").fillna(0)
    leak.append(sharpe(p, pos_leak)); fixed.append(sharpe(p, pos_fixed))
print(f"Random walk, position = 4h trend sign (no costs), 30 seeds")
print(f"  as-is (ffill by open label): mean Sharpe {np.mean(leak):+.2f}  (min {np.min(leak):+.2f}, max {np.max(leak):+.2f})")
print(f"  fixed (lag by one 4h bar)  : mean Sharpe {np.mean(fixed):+.2f}  (min {np.min(fixed):+.2f}, max {np.max(fixed):+.2f})")
