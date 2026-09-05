import numpy as np, pandas as pd, itertools
n=17520
def sharpe_of(close, sig):
    r = np.r_[0, np.diff(close)/close[:-1]]; pos = np.r_[0, sig[:-1]]
    tr = np.abs(np.diff(np.r_[0,pos])); s = pos*r - tr*0.0017
    return s.mean()/s.std()*np.sqrt(8760) if s.std()>0 else 0
def strat(c, k, thr, fast, slow):
    roc = c.pct_change(k).fillna(0).values
    ef, es = c.ewm(span=fast).mean().values, c.ewm(span=slow).mean().values
    raw = np.where(roc>thr,1,np.where(roc<-thr,-1,0))
    sig = pd.Series(raw).replace(0,np.nan).ffill().fillna(0).values
    sig = np.where((ef>es)&(sig<0),0,sig); sig = np.where((ef<es)&(sig>0),0,sig)
    return sig
grid=list(itertools.product([24,48,96,168,336,720],[0.03,0.05,0.08,0.12,0.2,0.3],[20,50,100],[200,400,800]))
bests=[]
for seed in range(20):
    rng=np.random.default_rng(seed); close=100*np.exp(np.cumsum(rng.normal(0,0.006,n))); c=pd.Series(close)
    sh=[sharpe_of(close,strat(c,*g)) for g in grid]
    bests.append(max(sh))
b=np.array(bests)
print(f"{len(grid)} combos x 20 independent random-walk paths: best-in-grid Sharpe  mean {b.mean():+.2f}, median {np.median(b):+.2f}, min {b.min():+.2f}, max {b.max():+.2f}")
print("share of paths where best-in-grid > +0.5:", (b>0.5).mean(), " > +1.0:", (b>1.0).mean())
