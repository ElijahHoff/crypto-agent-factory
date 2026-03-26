"""Experiment Registry: persistent tracking of all strategy experiments."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import orjson
from loguru import logger

from src.config import settings
from src.models import DecisionMemo, ExperimentRecord, PipelineStage


class ExperimentRegistry:
    """File-based experiment registry (upgradeable to DB later)."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or settings.experiment_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.base_dir / "registry_index.json"
        self._index: list[dict[str, Any]] = self._load_index()

    # ── CRUD ─────────────────────────────────────────────────────────────

    def create(self, record: ExperimentRecord) -> str:
        """Register a new experiment and save to disk."""
        exp_dir = self.base_dir / record.experiment_id
        exp_dir.mkdir(exist_ok=True)

        # Save full record
        data = record.model_dump(mode="json")
        (exp_dir / "experiment.json").write_bytes(orjson.dumps(data, option=orjson.OPT_INDENT_2))

        # Update index
        self._index.append({
            "experiment_id": record.experiment_id,
            "strategy_name": record.strategy_name,
            "stage": record.stage.value,
            "tags": record.tags,
            "created_at": record.created_at.isoformat(),
            "updated_at": record.updated_at.isoformat(),
        })
        self._save_index()
        logger.info(f"Registered experiment: {record.experiment_id} ({record.strategy_name})")
        return record.experiment_id

    def update(self, experiment_id: str, **fields: Any) -> None:
        """Update fields of an existing experiment."""
        exp_dir = self.base_dir / experiment_id
        exp_path = exp_dir / "experiment.json"
        if not exp_path.exists():
            raise FileNotFoundError(f"Experiment {experiment_id} not found")

        data = orjson.loads(exp_path.read_bytes())
        data.update(fields)
        data["updated_at"] = datetime.utcnow().isoformat()
        exp_path.write_bytes(orjson.dumps(data, option=orjson.OPT_INDENT_2))

        # Update index entry
        for entry in self._index:
            if entry["experiment_id"] == experiment_id:
                entry["updated_at"] = data["updated_at"]
                if "stage" in fields:
                    entry["stage"] = fields["stage"]
                break
        self._save_index()

    def get(self, experiment_id: str) -> ExperimentRecord:
        """Load a full experiment record."""
        exp_path = self.base_dir / experiment_id / "experiment.json"
        if not exp_path.exists():
            raise FileNotFoundError(f"Experiment {experiment_id} not found")
        data = orjson.loads(exp_path.read_bytes())
        return ExperimentRecord(**data)

    def list_all(self, stage: PipelineStage | None = None, tag: str | None = None) -> list[dict[str, Any]]:
        """List experiments with optional filtering."""
        results = self._index
        if stage:
            results = [r for r in results if r["stage"] == stage.value]
        if tag:
            results = [r for r in results if tag in r.get("tags", [])]
        return sorted(results, key=lambda x: x["updated_at"], reverse=True)

    def save_artifact(self, experiment_id: str, name: str, data: Any) -> Path:
        """Save an arbitrary artifact (chart, report, etc.) to experiment dir."""
        exp_dir = self.base_dir / experiment_id
        exp_dir.mkdir(exist_ok=True)
        path = exp_dir / name
        if isinstance(data, (dict, list)):
            path = path.with_suffix(".json")
            path.write_bytes(orjson.dumps(data, option=orjson.OPT_INDENT_2))
        elif isinstance(data, str):
            path.write_text(data)
        elif isinstance(data, bytes):
            path.write_bytes(data)
        else:
            path = path.with_suffix(".json")
            path.write_bytes(orjson.dumps(data, option=orjson.OPT_INDENT_2))
        logger.info(f"Saved artifact: {path}")
        return path

    # ── Decision Memo ────────────────────────────────────────────────────

    def record_decision(self, experiment_id: str, memo: DecisionMemo) -> None:
        """Record a decision memo and update experiment stage."""
        self.save_artifact(experiment_id, "decision_memo", memo.model_dump(mode="json"))
        self.update(
            experiment_id,
            stage=PipelineStage.DECISION.value,
            decision=memo.model_dump(mode="json"),
        )
        logger.info(f"Decision recorded: {experiment_id} → {memo.decision.value}")

    # ── Summary ──────────────────────────────────────────────────────────

    def summary(self) -> dict[str, Any]:
        """Get a summary of all experiments."""
        total = len(self._index)
        by_stage = {}
        for entry in self._index:
            stage = entry["stage"]
            by_stage[stage] = by_stage.get(stage, 0) + 1
        return {
            "total_experiments": total,
            "by_stage": by_stage,
            "latest": self._index[:5] if self._index else [],
        }

    # ── Internal ─────────────────────────────────────────────────────────

    def _load_index(self) -> list[dict[str, Any]]:
        if self.index_path.exists():
            return orjson.loads(self.index_path.read_bytes())
        return []

    def _save_index(self) -> None:
        self.index_path.write_bytes(orjson.dumps(self._index, option=orjson.OPT_INDENT_2))
