"""Tiny task-owned scope adapter used only by tuner pseudo integration tests."""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Annotated, Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from execute_tools.task_data_path import (
    EvaluationReadRequest,
    HealthCoverageRequest,
    HealthCoverageResult,
    ScopeBuildRequest,
    TaskOutputArtifactInventory,
)

Partition = Annotated[int, Field(strict=True, ge=0, lt=20)]
RowIndex = Annotated[int, Field(strict=True, ge=0, lt=8)]


class _EvaluationScope(BaseModel):
    """The fixture's symbolic evaluation identity, including transported JSON rows."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["tuner_rows"]
    leg: Literal["eval"]
    partitions: list[Partition] = Field(min_length=1)
    rows: list[tuple[Literal["eval"], Partition, RowIndex]] = Field(min_length=1)
    seed: int

    @model_validator(mode="after")
    def check_row_identity(self) -> _EvaluationScope:
        if len(set(self.rows)) != len(self.rows):
            raise ValueError("fixture evaluation rows must be unique")
        if self.partitions != sorted({partition for _, partition, _ in self.rows}):
            raise ValueError("fixture partitions must exactly describe the evaluation rows")
        return self


class TunerComposedTask:
    task_data_path_id: ClassVar[str] = "tuner_composed_rows"

    def _scope(self, request: ScopeBuildRequest, leg: str) -> dict[str, Any]:
        """Select bounded symbolic identities; no dataset is ever materialized."""
        domain = tuple(range(20))
        if request.subset_ref:
            try:
                allowed = {int(part) for part in request.subset_ref.split(",")}
            except ValueError as exc:
                raise ValueError("fixture subset_ref must be comma-separated integers") from exc
            domain = tuple(part for part in domain if part in allowed)
        if request.selection_strategy == "target":
            selected = tuple(request.target_partitions)
        elif request.selection_strategy == "anchors":
            selected = (4, 7, 9)
        else:
            selected = domain
        selected = tuple(part for part in selected if part in domain)
        if not selected:
            raise ValueError("fixture scope selection is empty")
        rows_per_partition = 8
        rows_each = max(1, round(rows_per_partition * request.portion))
        seed = 0 if request.seed is None else request.seed
        rng = random.Random(seed)
        rows = [
            (leg, part, row)
            for part in selected
            for row in sorted(rng.sample(range(rows_per_partition), rows_each))
        ]
        if request.max_samples is not None:
            rows = rows[: request.max_samples]
        if not rows:
            raise ValueError("fixture scope selection is empty")
        return {
            "kind": "tuner_rows",
            "leg": leg,
            "partitions": sorted({row[1] for row in rows}),
            "rows": rows,
            "seed": seed,
        }

    def build_training_scope(self, request: ScopeBuildRequest) -> object:
        return self._scope(request, "train")

    def build_eval_scope(self, request: ScopeBuildRequest) -> object:
        return self._scope(request, "eval")

    def validate_health_coverage(self, request: HealthCoverageRequest) -> HealthCoverageResult:
        """Cover the fixture's categorical check over sampled evaluation rows.

        The supplied-outcome fixture checks the selected population, not every
        row in a partition. An explicit monitored-partition override additionally
        requires at least one actual evaluation row from each requested partition.
        This certifies scope coverage only; the supplied Health verdict is separate.
        """
        scope = _EvaluationScope.model_validate(request.evaluation_scope)
        required = set(request.health_gate_files or ())
        missing = sorted(required - set(scope.partitions))
        return HealthCoverageResult(
            applicable=True,
            covered=not missing,
            reason=(
                f"fixture evaluation rows omit monitored partitions {missing}"
                if missing
                else "fixture evaluation rows cover the sampled categorical Health population"
            ),
        )

    def serialize_scope(self, scope: object) -> str:
        if not isinstance(scope, dict) or scope.get("kind") != "tuner_rows":
            raise ValueError("tuner scope must be a tuner_rows mapping")
        return json.dumps(scope, sort_keys=True, separators=(",", ":"))

    def deserialize_scope(self, payload: str) -> object:
        decoded = json.loads(payload)
        if not isinstance(decoded, dict) or decoded.get("kind") != "tuner_rows":
            raise ValueError("foreign tuner scope")
        return decoded

    def training_dataset(self, scope: object, params: Any) -> Any:
        raise AssertionError("pseudo tuner fixture must not materialize training data")

    def validation_dataset(self, scope: object, params: Any) -> Any:
        raise AssertionError("pseudo tuner fixture must not materialize evaluation data")

    def write_deliverable(self, outputs: Any, request: Any) -> None:
        raise AssertionError("pseudo tuner fixture must not write deliverables")

    def read_evaluation_payload(self, request: Any) -> object:
        raise AssertionError("pseudo tuner fixture must not read deliverables")

    def enumerate_output_artifacts(
        self, request: EvaluationReadRequest
    ) -> TaskOutputArtifactInventory:
        """RecordingSandbox supplies outcomes without writing prediction files.

        Refuse unexpected fixture predictions rather than silently omitting them.
        The deliverable root also holds unrelated configuration and record files.
        """
        directory = Path(request.deliverable_dir)
        if any(directory.glob("tuner_fixture_predictions_*.json")):
            raise ValueError("pseudo tuner fixture must not contain inference outputs")
        return TaskOutputArtifactInventory(
            run_name=request.run_name,
            exp_id=request.exp_id,
            model_type=request.model_type,
        )
