"""
Live Backtest Runner v0.7 — Iterative agent-generated signals.

1. Analyze market context (bear/bull/sideways)
2. Claude writes signal code adapted to market regime
3. If Sharpe < 0 → Claude rewrites with feedback (up to 3 attempts)
4. Best result goes through full backtest + robustness + charts
"""

import json
from datetime import datetime, timezone, timedelta
from loguru import logger

from src.data import MarketDataFetcher
from src.backtesting import BacktestEngine
from src.backtesting.robustness import RobustnessTester
from src.backtesting.signal_generator import SignalGenerator
from src.backtesting.iterative_signals import generate_signals_iterative
from src.backtesting.benchmark import compute_benchmarks
from src.backtesting.walk_forward import run_walk_forward

try:
    from src.backtesting.charts import generate_report_charts, generate_chart_description
    HAS_CHARTS = True
except ImportError:
    HAS_CHARTS = False


class LiveBacktestRunner:
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

        # 1. Fetch data
        logger.info(f"Fetching OHLCV: {config['symbol']} {config['timeframe']}...")
        prices = self.data_fetcher.fetch_ohlcv_full(
            symbol=config["symbol"], timeframe=config["timeframe"],
            start=config["start"], end=config["end"],
        )
        if prices is None or len(prices) < 100:
            return {"error": "insufficient_data", "bars": len(prices) if prices is not None else 0}

        logger.info(f"Got {len(prices)} bars: {prices.index[0]} → {prices.index[-1]}")

        # 2. Generate signals — ITERATIVE with Claude
        signal_source = "built_in"
        signals = None
        iteration_log = {}
        agent_code = ""

        logger.info("🧠 Starting iterative signal generation (up to 3 attempts)...")
        try:
            signals, agent_code, iteration_log = generate_signals_iterative(
                prices=prices,
                strategy_name=strategy_name,
                quant_spec=quant_spec if isinstance(quant_spec, dict) else {},
                max_iterations=3,
            )
            if signals is not None:
                signal_source = "agent_iterated"
                logger.info(f"✅ Agent signals accepted after {iteration_log.get('total_attempts', 0)} iterations")
        except Exception as e:
            logger.warning(f"Iterative generation failed: {e}")

        # Fallback to built-in
        if signals is None:
            logger.info(f"Using built-in signals: {config['strategy_type']}...")
            signals = self.signal_generator.generate(
                prices, strategy_type=config["strategy_type"],
                params=config.get("signal_params", {}),
            )
            signal_source = "built_in"

        # 3. Full backtest
        logger.info("Running backtest with realistic costs...")
        bt_result = self.backtest_engine.run_backtest(prices, signals)

        # 4. Robustness
        logger.info("Running robustness suite...")
        rob_report = None
        try:
            rob_report = self.robustness_tester.run_full_suite(prices, signals, bt_result)
        except Exception as e:
            logger.warning(f"Robustness failed: {e}")

        # 5. Benchmarks
        logger.info("Computing benchmarks...")
        benchmarks = {}
        try:
            benchmarks = compute_benchmarks(prices)
        except Exception as e:
            logger.warning(f"Benchmarks failed: {e}")

        # 6. Walk-forward
        logger.info("Running walk-forward...")
        wf_result = None
        try:
            wf_result = run_walk_forward(prices, signals, self.backtest_engine, n_periods=8)
        except Exception as e:
            logger.warning(f"Walk-forward failed: {e}")

        # 7. Charts
        charts = {}
        chart_desc = ""
        if HAS_CHARTS:
            try:
                charts = generate_report_charts(
                    prices=prices, signals=signals,
                    backtest_result=bt_result, strategy_name=strategy_name,
                    benchmarks=benchmarks, walk_forward=wf_result,
                )
            except Exception as e:
                logger.warning(f"Charts failed: {e}")
            try:
                chart_desc = generate_chart_description(bt_result, benchmarks, wf_result, signals)
            except Exception as e:
                logger.warning(f"Chart desc failed: {e}")

        # 8. Log
        is_m = bt_result.get("in_sample")
        oos_m = bt_result.get("out_of_sample")
        is_sharpe = _safe(is_m, "sharpe", 0)
        is_trades = _safe(is_m, "total_trades", 0)
        oos_sharpe = _safe(oos_m, "sharpe", 0)
        rob_score = rob_report.overall_score if rob_report else 0
        bh_sharpe = benchmarks.get("buy_and_hold").sharpe if benchmarks.get("buy_and_hold") else 0
        wf_cons = wf_result.consistency_ratio if wf_result else 0

        logger.info(
            f"Backtest [{signal_source}]: IS Sharpe={is_sharpe:.3f}, "
            f"OOS={oos_sharpe:.3f}, Trades={is_trades}, Rob={rob_score:.1%}, "
            f"B&H={bh_sharpe:.3f}, WF={wf_cons:.0%}"
        )

        result = self._package(
            bt_result, rob_report, config, prices, signals,
            benchmarks, wf_result, chart_desc, signal_source,
            agent_code, iteration_log,
        )
        result["charts"] = charts
        return result

    def _extract_config(self, quant_spec, backtest_design, strategy_name):
        symbol = "BTC/USDT"
        for spec in [backtest_design, quant_spec]:
            if not isinstance(spec, dict): continue
            for k in ["symbol", "instrument", "pair"]:
                if k in spec: symbol = spec[k]; break

        timeframe = "1h"
        if isinstance(backtest_design, dict):
            for k in ["timeframe", "interval"]:
                if k in backtest_design: timeframe = backtest_design[k]; break

        strategy_type = self.signal_generator.classify_strategy(
            strategy_name,
            json.dumps(quant_spec, default=str) if isinstance(quant_spec, dict) else "",
        )

        signal_params = {}
        if isinstance(quant_spec, dict):
            params = quant_spec.get("parameters", quant_spec.get("params", {}))
            if isinstance(params, dict): signal_params = params

        end = datetime.now(timezone.utc)
        lookback = 365
        if isinstance(backtest_design, dict):
            for k in ["lookback_days", "history_days"]:
                if k in backtest_design:
                    try: lookback = int(backtest_design[k])
                    except: pass
                    break

        return {"symbol": symbol, "timeframe": timeframe, "strategy_type": strategy_type,
                "signal_params": signal_params,
                "start": end - timedelta(days=lookback), "end": end}

    def _package(self, bt_result, rob_report, config, prices, signals,
                 benchmarks, wf_result, chart_desc, signal_source,
                 agent_code, iteration_log) -> dict:
        is_r = bt_result.get("in_sample")
        oos_r = bt_result.get("out_of_sample")

        summary = {
            "config": {
                "symbol": config["symbol"], "timeframe": config["timeframe"],
                "strategy_type": config["strategy_type"],
                "signal_source": signal_source,
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
            },
            "out_of_sample": None,
            "robustness": _pack_rob(rob_report),
            "signal_stats": {
                "long_bars": int((signals == 1).sum()),
                "short_bars": int((signals == -1).sum()),
                "flat_bars": int((signals == 0).sum()),
                "transitions": int((signals != signals.shift(1)).sum()),
                "source": signal_source,
            },
            "iteration_log": iteration_log,
        }

        if oos_r:
            summary["out_of_sample"] = {
                "sharpe": _safe(oos_r, "sharpe"),
                "total_return": _safe_pct(oos_r, "return_after_costs_pct"),
                "max_drawdown": _safe_pct(oos_r, "max_drawdown_pct"),
                "total_trades": _safe(oos_r, "total_trades", 0),
            }

        if benchmarks:
            summary["benchmarks"] = {
                n: {"total_return": round(b.total_return, 4), "sharpe": round(b.sharpe, 3),
                    "max_drawdown": round(b.max_drawdown, 4)}
                for n, b in benchmarks.items()
            }

        if wf_result:
            summary["walk_forward"] = {
                "n_periods": wf_result.n_periods,
                "positive_periods": wf_result.positive_periods,
                "consistency_ratio": round(wf_result.consistency_ratio, 3),
                "avg_sharpe": round(wf_result.avg_sharpe, 3),
                "sharpe_std": round(wf_result.sharpe_std, 3),
                "subperiods": [
                    {"period": p.period_num, "dates": f"{p.start_date}→{p.end_date}",
                     "sharpe": p.sharpe, "return": p.total_return,
                     "trades": p.total_trades, "passed": p.passed}
                    for p in wf_result.periods
                ],
            }

        if chart_desc:
            summary["chart_analysis"] = chart_desc
        if agent_code:
            summary["agent_signal_code"] = agent_code[:3000]

        return summary


def _safe(obj, field, default=None):
    if obj is None: return default
    v = getattr(obj, field, default)
    try: return round(float(v), 4) if v is not None else default
    except: return v

def _safe_pct(obj, field, default=None):
    if obj is None: return default
    v = getattr(obj, field, None)
    try: return round(float(v) / 100, 4) if v is not None else default
    except: return default

def _pack_rob(r):
    if r is None: return {"overall_score": 0, "tests_passed": 0, "total_tests": 0, "details": {}}
    return {
        "overall_score": round(r.overall_score, 3),
        "tests_passed": sum(1 for c in r.checks if c.passed),
        "total_tests": len(r.checks),
        "details": {c.name: {"passed": c.passed, "detail": c.details} for c in r.checks},
        "critical_failures": r.critical_failures,
    }
