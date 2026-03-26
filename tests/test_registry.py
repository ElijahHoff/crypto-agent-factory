"""Tests for the experiment registry."""

from pathlib import Path

import pytest

from src.models import ExperimentRecord, PipelineStage, Decision, DecisionMemo
from src.utils.registry import ExperimentRegistry


@pytest.fixture
def tmp_registry(tmp_path: Path) -> ExperimentRegistry:
    return ExperimentRegistry(base_dir=tmp_path / "experiments")


class TestExperimentRegistry:
    def test_create_and_get(self, tmp_registry: ExperimentRegistry):
        record = ExperimentRecord(strategy_name="test_strat", stage=PipelineStage.HYPOTHESIS)
        exp_id = tmp_registry.create(record)

        loaded = tmp_registry.get(exp_id)
        assert loaded.strategy_name == "test_strat"
        assert loaded.experiment_id == exp_id

    def test_list_all(self, tmp_registry: ExperimentRegistry):
        for name in ["alpha", "beta", "gamma"]:
            r = ExperimentRecord(strategy_name=name, stage=PipelineStage.HYPOTHESIS)
            tmp_registry.create(r)

        all_exp = tmp_registry.list_all()
        assert len(all_exp) == 3

    def test_list_by_stage(self, tmp_registry: ExperimentRegistry):
        r1 = ExperimentRecord(strategy_name="a", stage=PipelineStage.HYPOTHESIS)
        r2 = ExperimentRecord(strategy_name="b", stage=PipelineStage.DECISION)
        tmp_registry.create(r1)
        tmp_registry.create(r2)

        hyp_only = tmp_registry.list_all(stage=PipelineStage.HYPOTHESIS)
        assert len(hyp_only) == 1

    def test_update(self, tmp_registry: ExperimentRegistry):
        r = ExperimentRecord(strategy_name="updatable", stage=PipelineStage.HYPOTHESIS)
        exp_id = tmp_registry.create(r)

        tmp_registry.update(exp_id, stage=PipelineStage.BACKTEST_RUN.value)
        loaded = tmp_registry.get(exp_id)
        assert loaded.stage == PipelineStage.BACKTEST_RUN

    def test_save_artifact(self, tmp_registry: ExperimentRegistry):
        r = ExperimentRecord(strategy_name="artifact_test", stage=PipelineStage.HYPOTHESIS)
        exp_id = tmp_registry.create(r)

        path = tmp_registry.save_artifact(exp_id, "test_data", {"key": "value"})
        assert path.exists()

    def test_summary(self, tmp_registry: ExperimentRegistry):
        r = ExperimentRecord(strategy_name="s", stage=PipelineStage.HYPOTHESIS)
        tmp_registry.create(r)

        summary = tmp_registry.summary()
        assert summary["total_experiments"] == 1

    def test_record_decision(self, tmp_registry: ExperimentRegistry):
        r = ExperimentRecord(strategy_name="decided", stage=PipelineStage.VALIDATION)
        exp_id = tmp_registry.create(r)

        memo = DecisionMemo(
            strategy_id=exp_id,
            strategy_name="decided",
            decision=Decision.REJECT,
            reasoning="Insufficient trades",
            key_risks=["sample size"],
        )
        tmp_registry.record_decision(exp_id, memo)

        loaded = tmp_registry.get(exp_id)
        assert loaded.stage == PipelineStage.DECISION
