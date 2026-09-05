"""Robustness checks: stress tests, parameter perturbation, signal degradation.

v1.0: thresholds are RELATIVE to the baseline Sharpe (a stressed run must keep
>= 50% of it and stay > 0) instead of absolute 0.3/0.5 cut-offs that every
strategy with baseline Sharpe 0.4 failed by construction. The noise test is
seeded (reproducible) and averaged over several draws. A stressed run that
*improves* on the baseline (e.g. delayed entry) is flagged as suspicious —
it usually means the signal is anti-correlated with the next bar, i.e. noise.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from loguru import logger

from src.backtesting import BacktestEngine, CostModel
from src.models import BacktestDesign, RobustnessCheck, RobustnessReport


class RobustnessTester:
    """Runs a comprehensive battery of robustness checks on a strategy."""

    def __init__(self, engine: BacktestEngine | None = None) -> None:
        self.engine = engine or BacktestEngine()

    def run_full_suite(
        self,
        prices: pd.DataFrame,
        signals: pd.Series,
        base_result: dict,
        design: BacktestDesign | None = None,
    ) -> RobustnessReport:
        """Run all robustness checks and produce a report."""
        checks: list[RobustnessCheck] = []
        self._base_sharpe = float(getattr(base_result.get("in_sample"), "sharpe", 0.0) or 0.0)

        checks.append(self._check_fee_sensitivity(prices, signals, design))
        checks.append(self._check_slippage_sensitivity(prices, signals, design))
        checks.append(self._check_delayed_entry(prices, signals, design))
        checks.append(self._check_spread_widening(prices, signals, design))
        checks.append(self._check_top_trades_removal(base_result))
        checks.append(self._check_subperiod_stability(prices, signals, design))
        checks.append(self._check_signal_degradation(prices, signals, design))

        critical = [c for c in checks if c.severity == "critical" and not c.passed]
        high = [c for c in checks if c.severity == "high" and not c.passed]
        n_passed = sum(1 for c in checks if c.passed)
        score = n_passed / len(checks) if checks else 0.0

        return RobustnessReport(
            checks=checks,
            overall_score=round(score, 3),
            critical_failures=[c.name for c in critical],
        )

    # ── Individual Checks ────────────────────────────────────────────────

    _base_sharpe: float = 0.0

    def _relative_pass(self, sharpe: float, keep: float = 0.5) -> tuple[bool, str]:
        """Pass if stressed Sharpe > 0 and keeps >= `keep` of the baseline."""
        base = self._base_sharpe
        if base <= 0:
            return False, f"baseline Sharpe {base:.3f} <= 0"
        ok = sharpe > 0 and sharpe >= keep * base
        note = f"retained {sharpe / base:.0%} of baseline {base:.3f}"
        if sharpe > base * 1.15:
            note += " — SUSPICIOUS: stress improved results"
        return ok, note

    def _check_fee_sensitivity(
        self, prices: pd.DataFrame, signals: pd.Series, design: BacktestDesign | None
    ) -> RobustnessCheck:
        """Does strategy survive with 2x fees?"""
        logger.info("Robustness: 2x fee test")
        engine_2x = BacktestEngine(
            cost_model=CostModel(commission_bps=self.engine.cost_model.commission_bps * 2)
        )
        result = engine_2x.run_backtest(prices, signals, design)
        sharpe = result["in_sample"].sharpe

        passed, note = self._relative_pass(sharpe)
        return RobustnessCheck(
            name="fee_sensitivity_2x",
            description="Strategy performance with 2x commission",
            passed=passed,
            details=f"Sharpe with 2x fees: {sharpe:.3f} ({note})",
            severity="high",
        )

    def _check_slippage_sensitivity(
        self, prices: pd.DataFrame, signals: pd.Series, design: BacktestDesign | None
    ) -> RobustnessCheck:
        """Does strategy survive with 3x slippage?"""
        logger.info("Robustness: 3x slippage test")
        engine_3x = BacktestEngine(
            cost_model=CostModel(slippage_bps=self.engine.cost_model.slippage_bps * 3)
        )
        result = engine_3x.run_backtest(prices, signals, design)
        sharpe = result["in_sample"].sharpe

        passed, note = self._relative_pass(sharpe)
        return RobustnessCheck(
            name="slippage_sensitivity_3x",
            description="Strategy performance with 3x slippage",
            passed=passed,
            details=f"Sharpe with 3x slippage: {sharpe:.3f} ({note})",
            severity="high",
        )

    def _check_delayed_entry(
        self, prices: pd.DataFrame, signals: pd.Series, design: BacktestDesign | None
    ) -> RobustnessCheck:
        """Does strategy survive 1-bar delayed entry?"""
        logger.info("Robustness: delayed entry test")
        delayed_signals = signals.shift(1).fillna(0)
        result = self.engine.run_backtest(prices, delayed_signals, design)
        sharpe = result["in_sample"].sharpe

        passed, note = self._relative_pass(sharpe)
        return RobustnessCheck(
            name="delayed_entry_1bar",
            description="Strategy with 1-bar delayed entry (latency test)",
            passed=passed,
            details=f"Sharpe with 1-bar delay: {sharpe:.3f} ({note})",
            severity="medium",
        )

    def _check_spread_widening(
        self, prices: pd.DataFrame, signals: pd.Series, design: BacktestDesign | None
    ) -> RobustnessCheck:
        """Does strategy survive 5x spread?"""
        logger.info("Robustness: spread widening test")
        engine_wide = BacktestEngine(
            cost_model=CostModel(spread_bps=self.engine.cost_model.spread_bps * 5)
        )
        result = engine_wide.run_backtest(prices, signals, design)
        sharpe = result["in_sample"].sharpe

        passed, note = self._relative_pass(sharpe)
        return RobustnessCheck(
            name="spread_widening_5x",
            description="Strategy with 5x spread (illiquid conditions)",
            passed=passed,
            details=f"Sharpe with 5x spread: {sharpe:.3f} ({note})",
            severity="medium",
        )

    def _check_top_trades_removal(self, base_result: dict) -> RobustnessCheck:
        """Is strategy dependent on a few outlier trades?"""
        logger.info("Robustness: top trades removal")
        trades = base_result.get("trades", [])
        if len(trades) < 10:
            return RobustnessCheck(
                name="top_trades_removal",
                description="Remove top 5% winning trades",
                passed=False,
                details="Too few trades to perform this check",
                severity="critical",
            )

        pnls = sorted([t.pnl_net for t in trades], reverse=True)
        n_remove = max(1, int(len(pnls) * 0.05))
        remaining_pnl = sum(pnls[n_remove:])
        total_pnl = sum(pnls)

        ratio = remaining_pnl / total_pnl if total_pnl != 0 else 0
        passed = ratio > 0.5  # Still profitable after removing top 5%

        return RobustnessCheck(
            name="top_trades_removal",
            description="Profitability after removing top 5% winning trades",
            passed=passed,
            details=f"PnL ratio after removal: {ratio:.2f} (kept {ratio*100:.0f}% of profits)",
            severity="high",
        )

    def _check_subperiod_stability(
        self, prices: pd.DataFrame, signals: pd.Series, design: BacktestDesign | None
    ) -> RobustnessCheck:
        """Is the strategy profitable across multiple sub-periods?"""
        logger.info("Robustness: subperiod stability")
        n = len(prices)
        n_periods = 4
        chunk = n // n_periods
        positive_periods = 0

        for i in range(n_periods):
            start = i * chunk
            end = min((i + 1) * chunk, n)
            sub_prices = prices.iloc[start:end]
            sub_signals = signals.iloc[start:end]
            result = self.engine.run_backtest(sub_prices, sub_signals, design)
            if result["in_sample"].sharpe > 0:
                positive_periods += 1

        ratio = positive_periods / n_periods
        passed = ratio >= 0.75  # At least 3/4 periods positive

        return RobustnessCheck(
            name="subperiod_stability",
            description=f"Positive Sharpe in {positive_periods}/{n_periods} sub-periods",
            passed=passed,
            details=f"{positive_periods}/{n_periods} periods with positive Sharpe ({ratio:.0%})",
            severity="critical",
        )

    def _check_signal_degradation(
        self, prices: pd.DataFrame, signals: pd.Series, design: BacktestDesign | None
    ) -> RobustnessCheck:
        """How does performance degrade with noise added to signals?"""
        logger.info("Robustness: trade dropout (10% of positions removed, 5 seeded draws)")
        # v1.0: drop whole POSITIONS, not random bars. Zeroing 10% of bars
        # inside a held position created ~2 extra round-trips per hit and
        # tested transaction costs, not signal quality.
        rng = np.random.default_rng(42)
        sig = signals.reindex(prices.index).fillna(0)
        seg_id = (sig != sig.shift(1)).cumsum()
        active_ids = seg_id[sig != 0].unique()
        sharpes = []
        for _ in range(5):
            noisy = sig.copy()
            if len(active_ids) > 0:
                drop = rng.random(len(active_ids)) < 0.10
                noisy[seg_id.isin(active_ids[drop])] = 0
            result = self.engine.run_backtest(prices, noisy, design)
            sharpes.append(result["in_sample"].sharpe)
        sharpe = float(np.mean(sharpes))

        passed, note = self._relative_pass(sharpe)
        return RobustnessCheck(
            name="signal_degradation_10pct",
            description="Strategy with 10% of positions randomly dropped (mean of 5 draws)",
            passed=passed,
            details=f"Sharpe with 10% signal noise: {sharpe:.3f} ({note})",
            severity="medium",
        )
