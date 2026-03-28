"""
Live Backtest Runner v0.4 — Full pipeline with all features.

Features:
- Auto-classifies strategy family from name + quant spec
- Multi-asset support (runs on multiple symbols, picks best)
- Funding rate data for funding-based strategies
- Benchmark comparison (buy-and-hold)
- Walk-forward validation with subperiod details
- Chart generation (matplotlib) with benchmark overlay
- Text description of charts for AI agents
"""

import json
from datetime import datetime, timezone, timedelta
from loguru import logger

from src.data import MarketDataFetcher
from src.backtesting import BacktestEngine
from src.backtesting.robustness import RobustnessTester
from src.backtesting.signal_generator import SignalGenerator
from src.backtesting.benchmark import compute_benchmarks
from src.backtesting.walk_forward import run_walk_forward

try:
    from src.backtesting.charts import generate_report_charts, generate_chart_description
    HAS_CHARTS = True
except ImportError:
    HAS_CHARTS = False

try:
    from src.backtesting.funding_data import fetch_funding_rates, compute_funding_features
    HAS_FUNDING = True
except ImportError:
    HAS_FUNDING = False


# Default universe for multi-asset runs
DEFAULT_UNIVERSE = ["BTC/USDT", "ETH/USDT"]
EXTENDED_UNIVERSE = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT"]


class LiveBacktestRunner:
    """Full backtest pipeline with all v0.4 features."""

    def __init__(self):
        self.data_fetcher = MarketDataFetcher()
        self.backtest_engine = BacktestEngine()
        self.robustness_tester = RobustnessTester()
        self.signal_generator = SignalGenerator()

    def run(self, quant_spec: dict, backtest_design: dict,
            strategy_name: str = "unknown") -> dict:
        """
        Full live backtest pipeline.

        Returns comprehensive dict with all results for downstream agents.
        """
        config = self._extract_config(quant_spec, backtest_design)

        logger.info(
            f"Config: symbol={config['symbol']}, tf={config['timeframe']}, "
            f"type={config['strategy_type']}, "
            f"period={config['start']}→{config['end']}"
        )

        # ── 1. Fetch OHLCV ──
        logger.info(f"Fetching OHLCV: {config['symbol']} {config['timeframe']}...")
        prices = self.data_fetcher.fetch_ohlcv_full(
            symbol=config["symbol"],
            timeframe=config["timeframe"],
            start=config["start"],
            end=config["end"],
        )

        if prices is None or len(prices) < 100:
            n_bars = len(prices) if prices is not None else 0
            logger.error(f"Insufficient data: got {n_bars} bars")
            return {"error": "insufficient_data", "bars": n_bars}

        logger.info(f"Got {len(prices)} bars: {prices.index[0]} → {prices.index[-1]}")

        # ── 2. Fetch funding rates (optional) ──
        funding_features = None
        if HAS_FUNDING and config["strategy_type"] in ("momentum", "mean_reversion"):
            try:
                logger.info("Fetching funding rate data...")
                fr = fetch_funding_rates(
                    symbol=config["symbol"], start=config["start"]
                )
                if fr is not None and len(fr) > 10:
                    logger.info(f"Got {len(fr)} funding rate records")
                    # Store for report but don't block on failures
                    funding_features = fr
            except Exception as e:
                logger.warning(f"Funding rate fetch failed (non-fatal): {e}")

        # ── 3. Generate signals ──
        logger.info(f"Generating signals: {config['strategy_type']}...")
        signals = self.signal_generator.generate(
            prices,
            strategy_type=config["strategy_type"],
            params=config.get("signal_params", {}),
        )

        # ── 4. Run backtest ──
        logger.info("Running backtest with realistic costs...")
        bt_result = self.backtest_engine.run_backtest(prices, signals)

        # ── 5. Robustness tests ──
        logger.info("Running robustness suite (7 tests)...")
        rob_report = self.robustness_tester.run_full_suite(prices, signals, bt_result)

        # ── 6. Benchmark comparison ──
        logger.info("Computing benchmarks...")
        benchmarks = compute_benchmarks(prices)

        # ── 7. Walk-forward validation ──
        logger.info("Running walk-forward validation (8 periods)...")
        wf_result = None
        try:
            wf_result = run_walk_forward(
                prices, signals, self.backtest_engine, n_periods=8
            )
        except Exception as e:
            logger.warning(f"Walk-forward failed (non-fatal): {e}")

        # ── 8. Multi-asset check (secondary symbol) ──
        secondary_results = {}
        if config.get("run_multi_asset", False):
            secondary_results = self._run_secondary_assets(
                config, prices, signals
            )

        # ── 9. Generate charts ──
        charts = {}
        chart_description = ""
        if HAS_CHARTS:
            logger.info("Generating report charts...")
            try:
                charts = generate_report_charts(
                    prices=prices, signals=signals,
                    backtest_result=bt_result, strategy_name=strategy_name,
                    benchmarks=benchmarks, walk_forward=wf_result,
                )
            except Exception as e:
                logger.warning(f"Chart generation failed: {e}")

            # Text description for agents
            try:
                chart_description = generate_chart_description(
                    bt_result, benchmarks, wf_result, signals
                )
            except Exception as e:
                logger.warning(f"Chart description failed: {e}")

        # ── 10. Log summary ──
        is_sharpe = bt_result['in_sample'].sharpe
        is_trades = bt_result['in_sample'].total_trades
        oos_sharpe = bt_result['out_of_sample'].sharpe if bt_result.get('out_of_sample') else 0
        rob_score = rob_report.overall_score
        bh_sharpe = benchmarks["buy_and_hold"].sharpe if benchmarks else 0
        wf_consistency = wf_result.consistency_ratio if wf_result else 0

        logger.info(
            f"Backtest complete: IS Sharpe={is_sharpe:.3f}, "
            f"OOS Sharpe={oos_sharpe:.3f}, "
            f"Trades={is_trades}, "
            f"Robustness={rob_score:.1%}, "
            f"B&H Sharpe={bh_sharpe:.3f}, "
            f"WF Consistency={wf_consistency:.0%}"
        )

        # ── Package results ──
        result = self._package_results(
            bt_result, rob_report, config, prices, signals,
            benchmarks, wf_result, chart_description, funding_features,
            secondary_results,
        )
        result["charts"] = charts
        return result

    def _run_secondary_assets(self, config, primary_prices, primary_signals):
        """Run same strategy on secondary assets for cross-validation."""
        secondary = {}
        symbols = [s for s in DEFAULT_UNIVERSE if s != config["symbol"]]

        for symbol in symbols[:2]:  # max 2 secondary
            try:
                logger.info(f"Cross-validating on {symbol}...")
                prices = self.data_fetcher.fetch_ohlcv_full(
                    symbol=symbol, timeframe=config["timeframe"],
                    start=config["start"], end=config["end"],
                )
                if prices is None or len(prices) < 100:
                    continue

                signals = self.signal_generator.generate(
                    prices, strategy_type=config["strategy_type"],
                    params=config.get("signal_params", {}),
                )
                bt = self.backtest_engine.run_backtest(prices, signals)
                is_r = bt["in_sample"]
                secondary[symbol] = {
                    "sharpe": round(is_r.sharpe, 3),
                    "total_return": round(is_r.return_after_costs_pct / 100, 4),
                    "max_drawdown": round(is_r.max_drawdown_pct / 100, 4),
                    "total_trades": is_r.total_trades,
                }
                logger.info(f"  {symbol}: Sharpe={is_r.sharpe:.3f}")
            except Exception as e:
                logger.warning(f"  {symbol} failed: {e}")

        return secondary

    def _extract_config(self, quant_spec: dict, backtest_design: dict) -> dict:
        """Extract backtest config from agent outputs."""
        # Symbol
        symbol = "BTC/USDT"
        for spec in [backtest_design, quant_spec]:
            for key in ["symbol", "instrument", "pair", "ticker"]:
                if key in spec:
                    symbol = spec[key]
                    break

        # Timeframe
        timeframe = "1h"
        for key in ["timeframe", "interval", "bar_size", "frequency"]:
            if key in backtest_design:
                timeframe = backtest_design[key]
                break

        # Strategy type — auto-classify
        strategy_desc = json.dumps(quant_spec, default=str) if quant_spec else ""
        strategy_name = quant_spec.get("strategy_name", "")
        strategy_type = self.signal_generator.classify_strategy(strategy_name, strategy_desc)

        for key in ["strategy_type", "signal_type", "type"]:
            if key in backtest_design:
                candidate = backtest_design[key].lower()
                if candidate in SignalGenerator.STRATEGY_MAP:
                    strategy_type = candidate
                    break

        # Signal parameters
        signal_params = {}
        if quant_spec:
            params = quant_spec.get("parameters", quant_spec.get("params", {}))
            if isinstance(params, dict):
                signal_params = params
            elif isinstance(params, list):
                for p in params:
                    if isinstance(p, dict) and "name" in p:
                        signal_params[p["name"]] = p.get("default", p.get("value", 0))

        # Multi-asset flag
        run_multi = False
        universe = quant_spec.get("universe", quant_spec.get("assets", []))
        if isinstance(universe, list) and len(universe) > 1:
            run_multi = True

        # Time period
        end = datetime.now(timezone.utc)
        lookback_days = 365
        for key in ["lookback_days", "history_days", "data_period_days"]:
            if key in backtest_design:
                try:
                    lookback_days = int(backtest_design[key])
                except (ValueError, TypeError):
                    pass
                break
        start = end - timedelta(days=lookback_days)

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "strategy_type": strategy_type,
            "signal_params": signal_params,
            "start": start,
            "end": end,
            "run_multi_asset": run_multi,
        }

    def _package_results(self, bt_result, rob_report, config, prices, signals,
                         benchmarks, wf_result, chart_description,
                         funding_features, secondary_results) -> dict:
        """Package all results for downstream agents."""
        is_r = bt_result["in_sample"]
        oos_r = bt_result.get("out_of_sample")

        def _m(metrics, field, scale=1):
            """Safely get metric field."""
            if metrics is None: return None
            val = getattr(metrics, field, None)
            if val is None: return None
            return round(val * scale, 4) if scale != 1 else round(val, 4)

        summary = {
            "config": {
                "symbol": config["symbol"],
                "timeframe": config["timeframe"],
                "strategy_type": config["strategy_type"],
                "bars": len(prices),
                "period": f"{prices.index[0]} → {prices.index[-1]}",
            },
            "in_sample": {
                "sharpe": _m(is_r, "sharpe"),
                "total_return": _m(is_r, "return_after_costs_pct", 0.01),
                "cagr": _m(is_r, "cagr_pct", 0.01),
                "max_drawdown": _m(is_r, "max_drawdown_pct", 0.01),
                "total_trades": getattr(is_r, "total_trades", 0),
                "win_rate": _m(is_r, "hit_rate"),
                "profit_factor": _m(is_r, "profit_factor"),
                "volatility": _m(is_r, "annualized_return_pct", 0.01),
                "calmar": _m(is_r, "calmar"),
            },
            "out_of_sample": None,
            "robustness": {
                "overall_score": round(rob_report.overall_score, 3),
                "tests_passed": sum(1 for c in rob_report.checks if c.passed),
                "total_tests": len(rob_report.checks),
                "details": {c.name: {"passed": c.passed, "detail": c.details} for c in rob_report.checks},
                "critical_failures": rob_report.critical_failures,
            },
            "signal_stats": {
                "long_bars": int((signals == 1).sum()),
                "short_bars": int((signals == -1).sum()),
                "flat_bars": int((signals == 0).sum()),
                "transitions": int((signals != signals.shift(1)).sum()),
            },
        }

        if oos_r:
            summary["out_of_sample"] = {
                "sharpe": _m(oos_r, "sharpe"),
                "total_return": _m(oos_r, "return_after_costs_pct", 0.01),
                "max_drawdown": _m(oos_r, "max_drawdown_pct", 0.01),
                "total_trades": getattr(oos_r, "total_trades", 0),
            }

        # Benchmarks
        if benchmarks:
            summary["benchmarks"] = {}
            for name, bm in benchmarks.items():
                summary["benchmarks"][name] = {
                    "total_return": round(bm.total_return, 4),
                    "sharpe": round(bm.sharpe, 3),
                    "max_drawdown": round(bm.max_drawdown, 4),
                    "volatility": round(bm.volatility, 4),
                }

        # Walk-forward
        if wf_result:
            summary["walk_forward"] = {
                "n_periods": wf_result.n_periods,
                "positive_periods": wf_result.positive_periods,
                "negative_periods": wf_result.negative_periods,
                "consistency_ratio": round(wf_result.consistency_ratio, 3),
                "avg_sharpe": round(wf_result.avg_sharpe, 3),
                "sharpe_std": round(wf_result.sharpe_std, 3),
                "worst_period": wf_result.worst_period,
                "best_period": wf_result.best_period,
                "subperiods": [
                    {
                        "period": p.period_num,
                        "dates": f"{p.start_date}→{p.end_date}",
                        "sharpe": p.sharpe,
                        "return": p.total_return,
                        "max_dd": p.max_drawdown,
                        "trades": p.total_trades,
                        "passed": p.passed,
                    }
                    for p in wf_result.periods
                ],
            }

        # Chart description (text for agents)
        if chart_description:
            summary["chart_analysis"] = chart_description

        # Funding data summary
        if funding_features is not None and len(funding_features) > 0:
            summary["funding_data"] = {
                "records": len(funding_features),
                "available": True,
            }

        # Multi-asset results
        if secondary_results:
            summary["multi_asset"] = secondary_results

        return summary
