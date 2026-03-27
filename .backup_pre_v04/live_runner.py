"""Live Backtest Runner: fetches real market data, generates signals, runs backtest + robustness."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd
from loguru import logger

from src.backtesting import BacktestEngine, CostModel
from src.backtesting.robustness import RobustnessTester
from src.backtesting.signal_generator import (
    SignalGenerator,
    detect_strategy_type,
    extract_parameters,
)
from src.data import MarketDataFetcher
from src.models import BacktestDesign


class LiveBacktestRunner:
    """Orchestrates the full backtest: data → signals → engine → robustness."""

    def __init__(
        self,
        exchange_id: str = "binance",
        cost_model: CostModel | None = None,
    ) -> None:
        self.fetcher = MarketDataFetcher(exchange_id)
        self.cost_model = cost_model or CostModel()
        self.engine = BacktestEngine(cost_model=self.cost_model)
        self.robustness = RobustnessTester(engine=self.engine)
        self.signal_gen = SignalGenerator()

    def run(
        self,
        agent_outputs: dict[str, Any],
        design: BacktestDesign | None = None,
    ) -> dict[str, Any]:
        """
        Full backtest pipeline:
        1. Determine symbol, timeframe, strategy type from agent outputs
        2. Fetch real OHLCV data from exchange
        3. Generate signals using strategy rules
        4. Run BacktestEngine with realistic costs
        5. Run robustness tests
        6. Package results for review agents

        Args:
            agent_outputs: Dictionary of all prior agent outputs (hypothesis, formalization, etc.)
            design: Optional backtest design; will be extracted from agent outputs if not provided.

        Returns:
            Dictionary with backtest_result, robustness, equity_curve, trade_stats.
        """
        try:
            # ── 1. Extract strategy configuration ────────────────────
            config = self._extract_config(agent_outputs)
            logger.info(
                f"Config: symbol={config['symbol']}, tf={config['timeframe']}, "
                f"type={config['strategy_type']}, period={config['start']}→{config['end']}"
            )

            # ── 2. Fetch real data ───────────────────────────────────
            logger.info(f"Fetching OHLCV: {config['symbol']} {config['timeframe']}...")
            prices = self.fetcher.fetch_ohlcv_full(
                symbol=config["symbol"],
                timeframe=config["timeframe"],
                start=config["start"],
                end=config["end"],
            )

            if prices.empty or len(prices) < 200:
                return self._error_result(
                    f"Insufficient data: got {len(prices)} bars, need 200+. "
                    f"Symbol={config['symbol']}, timeframe={config['timeframe']}"
                )

            logger.info(f"Got {len(prices)} bars: {prices.index[0]} → {prices.index[-1]}")

            # ── 3. Generate signals ──────────────────────────────────
            logger.info(f"Generating signals: {config['strategy_type']}...")
            signals = self.signal_gen.generate(
                prices=prices,
                strategy_type=config["strategy_type"],
                parameters=config["parameters"],
            )

            # Check we have enough trades
            trades_approx = signals.diff().abs().sum() / 2
            if trades_approx < 10:
                logger.warning(f"Very few trades (~{trades_approx:.0f}), results may be unreliable")

            # ── 4. Run backtest ──────────────────────────────────────
            if design is None:
                design = self._extract_design(agent_outputs)

            logger.info("Running backtest with realistic costs...")
            bt_result = self.engine.run_backtest(prices, signals, design)

            # ── 5. Run robustness tests ──────────────────────────────
            logger.info("Running robustness suite (7 tests)...")
            rob_report = self.robustness.run_full_suite(prices, signals, bt_result, design)

            # ── 6. Package results ───────────────────────────────────
            result = self._package_results(bt_result, rob_report, config, prices, signals)
            is_sharpe = bt_result['in_sample'].sharpe
            is_trades = bt_result['in_sample'].total_trades
            oos_sharpe = bt_result['out_of_sample'].sharpe if bt_result.get('out_of_sample') else 0
            rob_score = rob_report.overall_score
            logger.info(
                f"Backtest complete: IS Sharpe={is_sharpe:.3f}, "
                f"OOS Sharpe={oos_sharpe:.3f}, "
                f"Trades={is_trades}, "
                f"Robustness={rob_score:.1%}"
            )

            return result

        except Exception as e:
            logger.exception(f"Backtest failed: {e}")
            return self._error_result(str(e))

    # ── Config Extraction ────────────────────────────────────────────────

    def _extract_config(self, agent_outputs: dict) -> dict:
        """Extract symbol, timeframe, dates, strategy type, parameters from agent outputs."""
        hypothesis = agent_outputs.get("hypothesis", {})
        formalization = agent_outputs.get("formalization", {})
        data_spec = agent_outputs.get("data_spec", {})
        backtest_design = agent_outputs.get("backtest_design", {})

        # Strategy type
        strategy_type = detect_strategy_type(hypothesis)
        if strategy_type == "momentum":
            strategy_type = detect_strategy_type(formalization) or strategy_type

        # Symbol: try to find from universe or default
        symbol = "BTC/USDT"
        for source in [hypothesis, formalization, data_spec]:
            if isinstance(source, dict):
                universe = source.get("universe", [])
                if isinstance(universe, list) and universe:
                    first = universe[0]
                    if isinstance(first, str) and "/" in first:
                        symbol = first
                        break

        # Timeframe
        timeframe = "1h"
        for source in [hypothesis, formalization]:
            if isinstance(source, dict):
                tf = source.get("timeframe", "")
                if tf in ("1m", "5m", "15m", "1h", "4h", "1d"):
                    timeframe = tf
                    break

        # Date range
        end = datetime.now(timezone.utc)
        # Scale data period to timeframe
        tf_days = {"1m": 30, "5m": 60, "15m": 180, "1h": 365, "4h": 730, "1d": 1460}
        days = tf_days.get(timeframe, 365)
        start = end - timedelta(days=days)

        # Parameters
        parameters = extract_parameters(formalization)

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "strategy_type": strategy_type,
            "start": start,
            "end": end,
            "parameters": parameters,
        }

    def _extract_design(self, agent_outputs: dict) -> BacktestDesign:
        """Extract or create BacktestDesign from agent outputs."""
        bt_design = agent_outputs.get("backtest_design", {})

        if isinstance(bt_design, dict):
            config = bt_design.get("backtest_config", bt_design)
            if isinstance(config, dict):
                split = config.get("data_split", {})
                cost = config.get("cost_model", {})
                rejection = config.get("rejection_criteria", bt_design.get("rejection_criteria", {}))

                return BacktestDesign(
                    train_pct=split.get("train_pct", 0.5),
                    validation_pct=split.get("validation_pct", 0.25),
                    test_pct=split.get("test_pct", 0.25),
                    walk_forward_windows=split.get("walk_forward_windows", 5),
                    commission_bps=cost.get("commission_bps", 10.0),
                    slippage_bps=cost.get("slippage_bps", 5.0),
                    funding_bps=cost.get("funding_bps", 1.0),
                    rejection_criteria=rejection if isinstance(rejection, dict) else {},
                )

        return BacktestDesign()

    # ── Results Packaging ────────────────────────────────────────────────

    def _package_results(
        self,
        bt_result: dict,
        rob_report: Any,
        config: dict,
        prices: pd.DataFrame,
        signals: pd.Series,
    ) -> dict:
        """Package everything into a structured result for the review agents."""

        is_metrics = bt_result["in_sample"]
        val_metrics = bt_result.get("validation")
        oos_metrics = bt_result.get("out_of_sample")

        # Compute yearly Sharpe breakdown
        equity = bt_result["equity_net"]
        returns = equity.pct_change().fillna(0)
        sharpe_by_year = {}
        for year, group in returns.groupby(returns.index.year):
            if len(group) > 20:
                ann = group.mean() / group.std() * (365 * 24) ** 0.5 if group.std() > 0 else 0
                sharpe_by_year[str(year)] = round(float(ann), 3)

        # Trade summary
        trades = bt_result.get("trades", [])
        winning = [t for t in trades if t.pnl_net > 0]
        losing = [t for t in trades if t.pnl_net <= 0]

        return {
            "status": "completed",
            "config": {
                "symbol": config["symbol"],
                "timeframe": config["timeframe"],
                "strategy_type": config["strategy_type"],
                "data_bars": len(prices),
                "date_range": f"{prices.index[0]} → {prices.index[-1]}",
                "parameters_used": config["parameters"],
            },
            "in_sample": is_metrics.model_dump(),
            "validation": val_metrics.model_dump() if val_metrics else None,
            "out_of_sample": oos_metrics.model_dump() if oos_metrics else None,
            "walk_forward": [wf.model_dump() for wf in bt_result.get("walk_forward", [])],
            "trade_summary": {
                "total_trades": len(trades),
                "winning_trades": len(winning),
                "losing_trades": len(losing),
                "avg_win_pct": round(
                    float(sum(t.pnl_net for t in winning) / len(winning) * 100), 4
                ) if winning else 0,
                "avg_loss_pct": round(
                    float(sum(t.pnl_net for t in losing) / len(losing) * 100), 4
                ) if losing else 0,
                "best_trade_pct": round(
                    float(max(t.pnl_net for t in trades) * 100), 4
                ) if trades else 0,
                "worst_trade_pct": round(
                    float(min(t.pnl_net for t in trades) * 100), 4
                ) if trades else 0,
            },
            "sharpe_by_year": sharpe_by_year,
            "robustness": {
                "overall_score": rob_report.overall_score,
                "checks": [
                    {
                        "name": c.name,
                        "passed": c.passed,
                        "details": c.details,
                        "severity": c.severity,
                    }
                    for c in rob_report.checks
                ],
                "critical_failures": rob_report.critical_failures,
            },
            "total_costs_pct": bt_result.get("total_costs_pct", 0),
            "oos_vs_is_sharpe_ratio": round(
                oos_metrics.sharpe / is_metrics.sharpe, 3
            ) if oos_metrics and is_metrics.sharpe != 0 else None,
        }

    def _error_result(self, error_msg: str) -> dict:
        """Return a structured error result."""
        return {
            "status": "error",
            "error": error_msg,
            "in_sample": None,
            "out_of_sample": None,
            "robustness": None,
        }
