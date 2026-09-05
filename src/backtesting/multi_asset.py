"""
Multi-Asset Portfolio Runner v0.8

Runs the same signal generation logic across multiple assets,
then combines with correlation-aware portfolio weighting.

Features:
- Parallel data fetch for 4 assets
- Per-asset signal generation + backtest
- Correlation matrix between assets
- Equal-weight, inverse-vol, and risk-parity portfolios
- Combined portfolio equity curve + metrics
"""

import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from loguru import logger

from src.data import MarketDataFetcher
from src.backtesting import BacktestEngine
from src.backtesting.signal_generator import SignalGenerator
from src.backtesting.signal_sandbox import SignalSandbox, extract_signal_code
from src.backtesting.benchmark import compute_benchmarks

try:
    from src.backtesting.iterative_signals import generate_signals_iterative
    HAS_ITERATIVE = True
except ImportError:
    HAS_ITERATIVE = False


DEFAULT_UNIVERSE = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT"]

COST_PER_TRADE = 0.0017  # 17bps round-trip


@dataclass
class AssetResult:
    symbol: str
    sharpe: float = 0.0
    holdout_sharpe: float = 0.0
    total_return: float = 0.0
    max_drawdown: float = 0.0
    n_trades: int = 0
    n_long: int = 0
    n_short: int = 0
    equity: list = field(default_factory=list)
    returns: list = field(default_factory=list)


@dataclass
class PortfolioResult:
    method: str  # equal_weight, inverse_vol, risk_parity
    sharpe: float = 0.0
    total_return: float = 0.0
    max_drawdown: float = 0.0
    cagr: float = 0.0
    volatility: float = 0.0
    calmar: float = 0.0
    weights: dict = field(default_factory=dict)
    equity: list = field(default_factory=list)
    n_assets: int = 0


def run_multi_asset(
    strategy_name: str,
    quant_spec: dict,
    backtest_design: dict,
    universe: list | None = None,
    lookback_days: int = 730,  # 2 years default
    agent_code: str | None = None,
    holdout_pct: float = 0.30,
) -> dict:
    """
    Run strategy across multiple assets and build portfolio.

    Returns dict with per-asset results + portfolio results.
    """
    universe = universe or DEFAULT_UNIVERSE
    fetcher = MarketDataFetcher()
    engine = BacktestEngine()
    sig_gen = SignalGenerator()
    sandbox = SignalSandbox()

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=lookback_days)

    logger.info(f"🌐 Multi-asset run: {len(universe)} assets, {lookback_days} days")

    # 1. Fetch all data
    all_prices = {}
    for symbol in universe:
        logger.info(f"  Fetching {symbol}...")
        try:
            prices = fetcher.fetch_ohlcv_full(
                symbol=symbol, timeframe="1h", start=start, end=end,
            )
            if prices is not None and len(prices) > 500:
                all_prices[symbol] = prices
                logger.info(f"  ✅ {symbol}: {len(prices)} bars")
            else:
                logger.warning(f"  ⚠️ {symbol}: insufficient data")
        except Exception as e:
            logger.warning(f"  ❌ {symbol} failed: {e}")

    if len(all_prices) < 2:
        logger.error("Need at least 2 assets for portfolio")
        return {"error": "insufficient_assets", "fetched": len(all_prices)}

    # 2. Use the FROZEN code from the iterative loop (v1.0). Before, this
    #    pulled a different draft from quant_spec, so the portfolio tables
    #    described a different strategy than the headline result.
    if not agent_code:
        agent_code = extract_signal_code(quant_spec) if isinstance(quant_spec, dict) else None

    # 3. Classify strategy
    strategy_type = sig_gen.classify_strategy(strategy_name, str(quant_spec)[:500])

    # 4. Generate signals + backtest per asset
    asset_results = {}
    all_returns = {}

    for symbol, prices in all_prices.items():
        logger.info(f"  📊 Processing {symbol}...")

        # Try agent code first
        signals = None
        if agent_code:
            signals = sandbox.execute(agent_code, prices)

        # Try iterative generation for primary asset only
        if signals is None and HAS_ITERATIVE and symbol == universe[0]:
            try:
                signals, _, _ = generate_signals_iterative(
                    prices, strategy_name, quant_spec, max_iterations=3,
                )
            except Exception:
                pass

        # Fallback to built-in
        if signals is None:
            signals = sig_gen.generate(prices, strategy_type=strategy_type)

        # Compute returns (flip long->short charged as two trades)
        price_returns = prices["close"].pct_change().fillna(0)
        position = signals.shift(1).fillna(0)
        turnover = position.diff().abs().fillna(0)
        strat_returns = price_returns * position - turnover * COST_PER_TRADE
        trades = (turnover > 0).astype(float)

        equity = (1 + strat_returns).cumprod()
        total_ret = float(equity.iloc[-1] - 1)
        vol = float(strat_returns.std() * np.sqrt(8760))
        sharpe = float(strat_returns.mean() * 8760 / vol) if vol > 0 else 0
        peak = equity.cummax()
        dd = ((equity - peak) / peak).min()

        ho = int(len(strat_returns) * (1 - holdout_pct))
        ho_r = strat_returns.iloc[ho:]
        ho_sharpe = float(ho_r.mean() / ho_r.std() * np.sqrt(8760)) if ho_r.std() > 0 else 0.0

        ar = AssetResult(
            symbol=symbol,
            holdout_sharpe=round(ho_sharpe, 3),
            sharpe=round(sharpe, 3),
            total_return=round(total_ret, 4),
            max_drawdown=round(float(dd), 4),
            n_trades=int(trades.sum()),
            n_long=int((signals == 1).sum()),
            n_short=int((signals == -1).sum()),
            equity=equity.tolist(),
            returns=strat_returns.tolist(),
        )
        asset_results[symbol] = ar
        all_returns[symbol] = strat_returns

        logger.info(
            f"    {symbol}: Sharpe={sharpe:.3f}, Return={total_ret:.2%}, "
            f"Trades={int(trades.sum())}"
        )

    # 5. Build portfolios
    returns_df = pd.DataFrame(all_returns)
    # Align to shortest
    returns_df = returns_df.dropna()

    portfolios = {}

    # Equal weight
    eq = _build_portfolio(returns_df, "equal_weight",
                          {s: 1.0/len(returns_df.columns) for s in returns_df.columns})
    portfolios["equal_weight"] = eq

    # Inverse volatility — weights from the development window only
    dev_end = int(len(returns_df) * (1 - holdout_pct))
    vols = returns_df.iloc[:dev_end].std()
    inv_vol = 1.0 / vols.replace(0, 1e-10)
    inv_vol_w = inv_vol / inv_vol.sum()
    iv = _build_portfolio(returns_df, "inverse_vol", inv_vol_w.to_dict())
    portfolios["inverse_vol"] = iv

    # Momentum-weighted: weights from the DEVELOPMENT window only (v1.0).
    # Using the last 30 days of the full history chose weights with
    # knowledge of the outcome — look-ahead.
    recent = returns_df.iloc[max(0, dev_end - 720):dev_end]
    recent_sharpe = recent.mean() / recent.std().replace(0, 1e-10)
    # Only positive Sharpe assets get weight
    mom_w = recent_sharpe.clip(lower=0)
    if mom_w.sum() > 0:
        mom_w = mom_w / mom_w.sum()
    else:
        mom_w = pd.Series(1.0/len(returns_df.columns), index=returns_df.columns)
    mw = _build_portfolio(returns_df, "momentum_weighted", mom_w.to_dict())
    portfolios["momentum_weighted"] = mw

    # Correlation
    corr = returns_df.corr()

    # Log summary
    best = max(portfolios.values(), key=lambda p: p.sharpe)
    logger.info(
        f"🏆 Best portfolio: {best.method} "
        f"(Sharpe={best.sharpe:.3f}, Return={best.total_return:.2%})"
    )

    # 6. Benchmark
    benchmarks = {}
    primary_prices = all_prices.get(universe[0])
    if primary_prices is not None:
        try:
            benchmarks = compute_benchmarks(primary_prices)
        except Exception:
            pass

    return {
        "universe": list(all_prices.keys()),
        "lookback_days": lookback_days,
        "n_assets": len(all_prices),
        "asset_results": {
            s: {
                "sharpe": r.sharpe, "holdout_sharpe": r.holdout_sharpe,
                "total_return": r.total_return,
                "max_drawdown": r.max_drawdown, "n_trades": r.n_trades,
                "n_long": r.n_long, "n_short": r.n_short,
                "equity": r.equity,
            }
            for s, r in asset_results.items()
        },
        "portfolios": {
            name: {
                "sharpe": p.sharpe, "total_return": p.total_return,
                "max_drawdown": p.max_drawdown, "cagr": p.cagr,
                "volatility": p.volatility, "calmar": p.calmar,
                "weights": p.weights, "n_assets": p.n_assets,
            }
            for name, p in portfolios.items()
        },
        "best_portfolio": {
            "method": best.method, "sharpe": best.sharpe,
            "total_return": best.total_return,
        },
        "correlation_matrix": corr.round(3).to_dict(),
        "benchmarks": {
            name: {"total_return": round(b.total_return, 4), "sharpe": round(b.sharpe, 3)}
            for name, b in benchmarks.items()
        } if benchmarks else {},
    }


def _build_portfolio(returns_df: pd.DataFrame, method: str,
                     weights: dict) -> PortfolioResult:
    """Build portfolio from asset returns and weights."""
    w = pd.Series(weights)
    port_returns = (returns_df * w).sum(axis=1)

    equity = (1 + port_returns).cumprod()
    total_ret = float(equity.iloc[-1] - 1)
    vol = float(port_returns.std() * np.sqrt(8760))
    sharpe = float(port_returns.mean() * 8760 / vol) if vol > 0 else 0

    peak = equity.cummax()
    dd = float(((equity - peak) / peak).min())

    years = len(port_returns) / 8760
    cagr = float((1 + total_ret) ** (1 / max(years, 0.01)) - 1) if total_ret > -1 else -1
    calmar = cagr / abs(dd) if abs(dd) > 0.001 else 0

    return PortfolioResult(
        method=method,
        sharpe=round(sharpe, 3),
        total_return=round(total_ret, 4),
        max_drawdown=round(dd, 4),
        cagr=round(cagr, 4),
        volatility=round(vol, 4),
        calmar=round(calmar, 3),
        weights={k: round(v, 3) for k, v in weights.items()},
        equity=equity.tolist(),
        n_assets=len(weights),
    )
