"""Tiny task-owned scope adapter used only by tuner pseudo integration tests."""

from __future__ import annotations

import json
import random
from typing import Any, ClassVar

from execute_tools.task_data_path import ScopeBuildRequest


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
