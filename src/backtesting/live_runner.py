"""
Live Backtest Runner v0.9 — Memory + Parameter Sweep + Multi-Timeframe.

Full pipeline:
1. Load experiment memory (what worked/failed before)
2. Fetch 1h + 4h data
3. Claude generates signals with full context (memory + trend + market)
4. Parameter sweep on best code (50 combos)
5. Apply 4h trend filter
6. Full backtest + robustness + walk-forward + multi-asset
7. Save results to memory for next run
"""

import json
from datetime import datetime, timezone, timedelta
from loguru import logger

from src.data import MarketDataFetcher
from src.backtesting import BacktestEngine
from src.backtesting.robustness import RobustnessTester
from src.backtesting.signal_generator import SignalGenerator
from src.backtesting.iterative_signals import generate_signals_iterative
from src.backtesting.experiment_memory import save_experiment
from src.backtesting.multi_timeframe import (
    fetch_higher_timeframe, compute_trend_filter,
    apply_trend_filter, get_trend_context,
)
from src.backtesting.benchmark import compute_benchmarks
from src.backtesting.walk_forward import run_walk_forward

try:
    from src.backtesting.multi_asset import run_multi_asset
    HAS_MULTI = True
except ImportError:
    HAS_MULTI = False

try:
    from src.backtesting.charts import generate_report_charts, generate_chart_description
    HAS_CHARTS = True
except ImportError:
    HAS_CHARTS = False

try:
    from src.backtesting.portfolio_charts import generate_portfolio_charts
    HAS_PORT_CHARTS = True
except ImportError:
    HAS_PORT_CHARTS = False


class LiveBacktestRunner:
    def __init__(self):
        self.data_fetcher = MarketDataFetcher()
        self.backtest_engine = BacktestEngine()
        self.robustness_tester = RobustnessTester()
        self.signal_generator = SignalGenerator()

    def run(self, quant_spec: dict, backtest_design: dict,
            strategy_name: str = "unknown") -> dict:
        config = self._extract_config(quant_spec, backtest_design, strategy_name)

        logger.info(f"Config: {config['symbol']} {config['timeframe']}, "
                     f"type={config['strategy_type']}, lookback={config['lookback_days']}d")

        # 1. Fetch 1h data
        prices = self.data_fetcher.fetch_ohlcv_full(
            symbol=config["symbol"], timeframe=config["timeframe"],
            start=config["start"], end=config["end"],
        )
        if prices is None or len(prices) < 100:
            return {"error": "insufficient_data"}

        logger.info(f"Got {len(prices)} 1h bars")

        # 2. Fetch 4h data for trend filter
        trend_context = {}
        higher_prices = fetch_higher_timeframe(
            self.data_fetcher, config["symbol"], config["start"], config["end"],
        )
        if higher_prices is not None:
            trend_context = get_trend_context(higher_prices)
            logger.info(f"4h trend: {trend_context.get('current_4h_trend', '?')}")

        # 3. Iterative signal generation (with memory + trend context)
        signal_source = "built_in"
        signals = None
        iteration_log = {}
        agent_code = ""

        logger.info("🧠 Iterative signal generation...")
        try:
            signals, agent_code, iteration_log = generate_signals_iterative(
                prices, strategy_name,
                quant_spec if isinstance(quant_spec, dict) else {},
                max_iterations=5, trend_context=trend_context,
            )
            if signals is not None:
                signal_source = "agent_iterated"
                logger.info(f"✅ Agent signals (best Sharpe={iteration_log.get('best_sharpe', '?')})")
        except Exception as e:
            logger.warning(f"Iterative failed: {e}")

        # Fallback
        if signals is None:
            signals = self.signal_generator.generate(
                prices, strategy_type=config["strategy_type"],
                params=config.get("signal_params", {}),
            )

        # 4. Apply 4h trend filter
        if higher_prices is not None and len(higher_prices) > 200:
            trend = compute_trend_filter(higher_prices)
            signals = apply_trend_filter(signals, trend, prices)

        # 5. Backtest
        logger.info("Running backtest...")
        bt_result = self.backtest_engine.run_backtest(prices, signals)

        # 6. Robustness
        rob_report = None
        try:
            rob_report = self.robustness_tester.run_full_suite(prices, signals, bt_result)
        except Exception as e:
            logger.warning(f"Robustness: {e}")

        # 7. Benchmarks
        benchmarks = {}
        try:
            benchmarks = compute_benchmarks(prices)
        except Exception as e:
            logger.warning(f"Benchmarks: {e}")

        # 8. Walk-forward
        wf_result = None
        try:
            wf_result = run_walk_forward(prices, signals, self.backtest_engine, n_periods=8)
        except Exception as e:
            logger.warning(f"Walk-forward: {e}")

        # 9. Multi-asset
        multi_result = {}
        if HAS_MULTI:
            try:
                multi_result = run_multi_asset(
                    strategy_name, quant_spec or {}, backtest_design or {},
                    lookback_days=config["lookback_days"],
                )
            except Exception as e:
                logger.warning(f"Multi-asset: {e}")

        # 10. Charts
        charts = {}
        chart_desc = ""
        if HAS_CHARTS:
            try:
                charts = generate_report_charts(
                    prices, signals, bt_result, strategy_name,
                    benchmarks, wf_result,
                )
            except Exception: pass
            try:
                chart_desc = generate_chart_description(bt_result, benchmarks, wf_result, signals)
            except Exception: pass
        if HAS_PORT_CHARTS and multi_result.get("portfolios"):
            try:
                charts.update(generate_portfolio_charts(multi_result, strategy_name))
            except Exception: pass

        # 11. Summary
        is_m = bt_result.get("in_sample")
        oos_m = bt_result.get("out_of_sample")
        is_sharpe = _safe(is_m, "sharpe", 0)
        is_ret = _safe_pct(is_m, "return_after_costs_pct", 0)
        is_trades = _safe(is_m, "total_trades", 0)
        oos_sharpe = _safe(oos_m, "sharpe", 0)
        rob_score = rob_report.overall_score if rob_report else 0
        bh_sharpe = benchmarks.get("buy_and_hold").sharpe if benchmarks.get("buy_and_hold") else 0
        wf_cons = wf_result.consistency_ratio if wf_result else 0

        logger.info(
            f"Result [{signal_source}]: IS={is_sharpe:.3f}, OOS={oos_sharpe:.3f}, "
            f"Trades={is_trades}, Rob={rob_score:.1%}, B&H={bh_sharpe:.3f}, WF={wf_cons:.0%}"
        )

        # 12. Save to memory
        try:
            decision_hint = "positive" if is_sharpe > 0 else "negative"
            key_failure = ""
            if is_sharpe < -3:
                key_failure = "extreme negative Sharpe"
            elif is_trades < 20:
                key_failure = "too few trades"
            elif wf_cons < 0.25:
                key_failure = "poor walk-forward consistency"
            save_experiment(
                strategy_name=strategy_name,
                strategy_type=config["strategy_type"],
                sharpe=is_sharpe,
                total_return=is_ret or 0,
                n_trades=int(is_trades or 0),
                signal_source=signal_source,
                decision=decision_hint,
                key_failure=key_failure,
                code_snippet=agent_code[:300] if agent_code else "",
            )
        except Exception as e:
            logger.debug(f"Memory save failed: {e}")

        result = self._package(
            bt_result, rob_report, config, prices, signals,
            benchmarks, wf_result, chart_desc, signal_source,
            agent_code, iteration_log, multi_result, trend_context,
        )
        result["charts"] = charts
        # Strip large arrays before passing to review agents (token limit)
        if "multi_asset" in result:
            ma = result["multi_asset"]
            for sym in ma.get("asset_results", {}):
                ma["asset_results"][sym].pop("equity", None)
                ma["asset_results"][sym].pop("returns", None)
            for method in ma.get("portfolios", {}):
                if isinstance(ma["portfolios"][method], dict):
                    ma["portfolios"][method].pop("equity", None)
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
        lookback = 730
        if isinstance(backtest_design, dict):
            for k in ["lookback_days", "history_days"]:
                if k in backtest_design:
                    try: lookback = int(backtest_design[k])
                    except: pass
                    break

        return {"symbol": symbol, "timeframe": timeframe, "strategy_type": strategy_type,
                "signal_params": signal_params, "lookback_days": lookback,
                "start": end - timedelta(days=lookback), "end": end}

    def _package(self, bt_result, rob_report, config, prices, signals,
                 benchmarks, wf_result, chart_desc, signal_source,
                 agent_code, iteration_log, multi_result, trend_ctx) -> dict:
        is_r = bt_result.get("in_sample")
        oos_r = bt_result.get("out_of_sample")

        s = {
            "config": {
                "symbol": config["symbol"], "timeframe": config["timeframe"],
                "strategy_type": config["strategy_type"],
                "signal_source": signal_source,
                "lookback_days": config["lookback_days"],
                "bars": len(prices),
                "period": f"{prices.index[0]} → {prices.index[-1]}",
                "trend_4h": trend_ctx.get("current_4h_trend", "unknown"),
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
                "source": signal_source,
            },
            "iteration_log": iteration_log,
        }

        if oos_r:
            s["out_of_sample"] = {
                "sharpe": _safe(oos_r, "sharpe"),
                "total_return": _safe_pct(oos_r, "return_after_costs_pct"),
                "max_drawdown": _safe_pct(oos_r, "max_drawdown_pct"),
                "total_trades": _safe(oos_r, "total_trades", 0),
            }

        if benchmarks:
            s["benchmarks"] = {n: {"total_return": round(b.total_return, 4),
                                    "sharpe": round(b.sharpe, 3),
                                    "max_drawdown": round(b.max_drawdown, 4)}
                               for n, b in benchmarks.items()}
        if wf_result:
            s["walk_forward"] = {
                "n_periods": wf_result.n_periods,
                "positive_periods": wf_result.positive_periods,
                "consistency_ratio": round(wf_result.consistency_ratio, 3),
                "avg_sharpe": round(wf_result.avg_sharpe, 3),
                "subperiods": [{"period": p.period_num, "sharpe": p.sharpe, "passed": p.passed}
                               for p in wf_result.periods],
            }
        if multi_result and "portfolios" in multi_result:
            s["multi_asset"] = multi_result
        if chart_desc:
            s["chart_analysis"] = chart_desc
        if agent_code:
            s["agent_signal_code"] = agent_code[:3000]
        return s


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
