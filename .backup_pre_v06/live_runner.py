"""
Live Backtest Runner v0.5 — Fully compatible with existing BacktestEngine API.

Fixes from v0.4:
- Uses correct field names: return_after_costs_pct, max_drawdown_pct, hit_rate, cagr_pct
- Uses run_backtest() not run()
- Uses run_full_suite(prices, signals, base_result) with correct args
- Retry on API 529 errors (handled upstream in base agent)
- Safe getattr everywhere — never crashes on missing fields
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


class LiveBacktestRunner:
    """Full backtest pipeline — compatible with existing BacktestEngine."""

    def __init__(self):
        self.data_fetcher = MarketDataFetcher()
        self.backtest_engine = BacktestEngine()
        self.robustness_tester = RobustnessTester()
        self.signal_generator = SignalGenerator()

    def run(self, quant_spec: dict, backtest_design: dict,
            strategy_name: str = "unknown") -> dict:
        config = self._extract_config(quant_spec, backtest_design, strategy_name)

        logger.info(
            f"Config: symbol={config['symbol']}, tf={config['timeframe']}, "
            f"type={config['strategy_type']}, "
            f"period={config['start']}→{config['end']}"
        )

        # 1. Fetch OHLCV
        logger.info(f"Fetching OHLCV: {config['symbol']} {config['timeframe']}...")
        prices = self.data_fetcher.fetch_ohlcv_full(
            symbol=config["symbol"],
            timeframe=config["timeframe"],
            start=config["start"],
            end=config["end"],
        )
        if prices is None or len(prices) < 100:
            n = len(prices) if prices is not None else 0
            logger.error(f"Insufficient data: {n} bars")
            return {"error": "insufficient_data", "bars": n}

        logger.info(f"Got {len(prices)} bars: {prices.index[0]} → {prices.index[-1]}")

        # 2. Generate signals
        logger.info(f"Generating signals: {config['strategy_type']}...")
        signals = self.signal_generator.generate(
            prices, strategy_type=config["strategy_type"],
            params=config.get("signal_params", {}),
        )

        # 3. Backtest
        logger.info("Running backtest with realistic costs...")
        bt_result = self.backtest_engine.run_backtest(prices, signals)

        # 4. Robustness
        logger.info("Running robustness suite (7 tests)...")
        try:
            rob_report = self.robustness_tester.run_full_suite(prices, signals, bt_result)
        except Exception as e:
            logger.warning(f"Robustness failed (non-fatal): {e}")
            rob_report = None

        # 5. Benchmarks
        logger.info("Computing benchmarks...")
        try:
            benchmarks = compute_benchmarks(prices)
        except Exception as e:
            logger.warning(f"Benchmarks failed: {e}")
            benchmarks = {}

        # 6. Walk-forward
        logger.info("Running walk-forward validation (8 periods)...")
        wf_result = None
        try:
            wf_result = run_walk_forward(prices, signals, self.backtest_engine, n_periods=8)
        except Exception as e:
            logger.warning(f"Walk-forward failed: {e}")

        # 7. Charts
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
            try:
                chart_description = generate_chart_description(
                    bt_result, benchmarks, wf_result, signals
                )
            except Exception as e:
                logger.warning(f"Chart description failed: {e}")

        # 8. Package
        is_metrics = bt_result.get("in_sample")
        oos_metrics = bt_result.get("out_of_sample")

        is_sharpe = _safe(is_metrics, "sharpe", 0)
        is_trades = _safe(is_metrics, "total_trades", 0)
        oos_sharpe = _safe(oos_metrics, "sharpe", 0)
        rob_score = rob_report.overall_score if rob_report else 0
        bh_sharpe = benchmarks.get("buy_and_hold").sharpe if benchmarks.get("buy_and_hold") else 0
        wf_cons = wf_result.consistency_ratio if wf_result else 0

        logger.info(
            f"Backtest complete: IS Sharpe={is_sharpe:.3f}, "
            f"OOS Sharpe={oos_sharpe:.3f}, "
            f"Trades={is_trades}, "
            f"Robustness={rob_score:.1%}, "
            f"B&H Sharpe={bh_sharpe:.3f}, "
            f"WF Consistency={wf_cons:.0%}"
        )

        result = self._package(
            bt_result, rob_report, config, prices, signals,
            benchmarks, wf_result, chart_description,
        )
        result["charts"] = charts
        return result

    def _extract_config(self, quant_spec: dict, backtest_design: dict,
                        strategy_name: str) -> dict:
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

        # Strategy type — classify from NAME first, then spec
        strategy_type = self.signal_generator.classify_strategy(
            strategy_name,
            json.dumps(quant_spec, default=str) if quant_spec else "",
        )
        # Override if explicitly set
        for key in ["strategy_type", "signal_type", "type"]:
            if key in backtest_design:
                candidate = str(backtest_design[key]).lower()
                if candidate in SignalGenerator.STRATEGY_MAP:
                    strategy_type = candidate
                    break

        # Signal params
        signal_params = {}
        if quant_spec:
            params = quant_spec.get("parameters", quant_spec.get("params", {}))
            if isinstance(params, dict):
                signal_params = params
            elif isinstance(params, list):
                for p in params:
                    if isinstance(p, dict) and "name" in p:
                        signal_params[p["name"]] = p.get("default", p.get("value", 0))

        # Period
        end = datetime.now(timezone.utc)
        lookback = 365
        for key in ["lookback_days", "history_days", "data_period_days"]:
            if key in backtest_design:
                try:
                    lookback = int(backtest_design[key])
                except (ValueError, TypeError):
                    pass
                break

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "strategy_type": strategy_type,
            "signal_params": signal_params,
            "start": end - timedelta(days=lookback),
            "end": end,
        }

    def _package(self, bt_result, rob_report, config, prices, signals,
                 benchmarks, wf_result, chart_description) -> dict:
        is_r = bt_result.get("in_sample")
        oos_r = bt_result.get("out_of_sample")

        summary = {
            "config": {
                "symbol": config["symbol"],
                "timeframe": config["timeframe"],
                "strategy_type": config["strategy_type"],
                "bars": len(prices),
                "period": f"{prices.index[0]} → {prices.index[-1]}",
            },
            "in_sample": {
                "sharpe": _safe(is_r, "sharpe"),
                "total_return": _safe_pct(is_r, "return_after_costs_pct"),
                "cagr": _safe_pct(is_r, "cagr_pct"),
                "max_drawdown": _safe_pct(is_r, "max_drawdown_pct"),
                "total_trades": _safe(is_r, "total_trades", 0),
                "win_rate": _safe(is_r, "hit_rate"),
                "profit_factor": _safe(is_r, "profit_factor"),
                "calmar": _safe(is_r, "calmar"),
                "sortino": _safe(is_r, "sortino"),
                "volatility": _safe_pct(is_r, "annualized_return_pct"),
            },
            "out_of_sample": None,
            "robustness": self._pack_robustness(rob_report),
            "signal_stats": {
                "long_bars": int((signals == 1).sum()),
                "short_bars": int((signals == -1).sum()),
                "flat_bars": int((signals == 0).sum()),
                "transitions": int((signals != signals.shift(1)).sum()),
            },
        }

        if oos_r:
            summary["out_of_sample"] = {
                "sharpe": _safe(oos_r, "sharpe"),
                "total_return": _safe_pct(oos_r, "return_after_costs_pct"),
                "max_drawdown": _safe_pct(oos_r, "max_drawdown_pct"),
                "total_trades": _safe(oos_r, "total_trades", 0),
            }

        # Benchmarks
        if benchmarks:
            summary["benchmarks"] = {}
            for name, bm in benchmarks.items():
                summary["benchmarks"][name] = {
                    "total_return": round(bm.total_return, 4),
                    "sharpe": round(bm.sharpe, 3),
                    "max_drawdown": round(bm.max_drawdown, 4),
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

        if chart_description:
            summary["chart_analysis"] = chart_description

        return summary

    def _pack_robustness(self, rob_report) -> dict:
        if rob_report is None:
            return {"overall_score": 0, "tests_passed": 0, "total_tests": 0, "details": {}}
        return {
            "overall_score": round(rob_report.overall_score, 3),
            "tests_passed": sum(1 for c in rob_report.checks if c.passed),
            "total_tests": len(rob_report.checks),
            "details": {c.name: {"passed": c.passed, "detail": c.details} for c in rob_report.checks},
            "critical_failures": rob_report.critical_failures,
        }


# ─── Safe field access helpers ───

def _safe(obj, field: str, default=None):
    """Safely get field from Pydantic model or object."""
    if obj is None:
        return default
    val = getattr(obj, field, default)
    if val is None:
        return default
    try:
        return round(float(val), 4)
    except (ValueError, TypeError):
        return val

def _safe_pct(obj, field: str, default=None):
    """Get percentage field and convert to decimal (e.g. 5.0 → 0.05)."""
    if obj is None:
        return default
    val = getattr(obj, field, None)
    if val is None:
        return default
    try:
        return round(float(val) / 100, 4)
    except (ValueError, TypeError):
        return default
