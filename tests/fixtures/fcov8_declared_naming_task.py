"""A composed task that CONSUMES the framework's declared deliverable naming.

F-COV-8. This is the one shape no shipped in-tree pack has, and the reason the
defect reached a live composed run untouched by any Gate: TIDMAD
(``execute_tools/tidmad_data_path.py``), Pets and DAVIS all HAND-ROLL their
deliverable filenames, so the framework's ``deliverable:`` declaration — a
documented, transported, composable capability — had **zero** production
consumers. Its transport to the inference child was therefore never exercised.

This fixture consumes it the way the documentation says a task may: its
module-level ``deliverable_name`` resolves through
:func:`~execute_tools.deliverable_spec.resolve_deliverable_naming` instead of
formatting a filename itself.

Loaded by ``file:`` ref, the out-of-tree form, exactly as
``tests/fixtures/step10_p1/fourth_task/`` is — so the composition path these
tests drive is the one an external task actually takes. Nothing here is
registered at import: the child resolves it by COMPOSING the transported
manifest, which is the row-3 path of ``resolve_child_task_data_path``.
"""

from __future__ import annotations

import json
import os
from typing import Any

import torch
from torch.utils.data import Dataset

from execute_tools.evaluation_metric import EvaluationMetric

TASK_ID = "fcov8_declared_naming_task"

#: Rows in this task's only scope. Small on purpose — the assertion is about
#: the deliverable's NAME, and nothing here is a model-quality claim.
_ROWS = 3


class _PairDataset(Dataset):
    """``(model_input, supervision_target)``, the shape the generic route reads."""

    def __init__(self, rows: int) -> None:
        self._rows = rows

    def __len__(self) -> int:
        return self._rows

    def __getitem__(self, index: int) -> tuple[torch.Tensor, torch.Tensor]:
        return (
            torch.full((4,), float(index), dtype=torch.float32),
            torch.zeros(1, dtype=torch.float32),
        )


class FcovScope:
    """This task's OPAQUE scope. The framework never interprets it."""

    KIND = "fcov8_declared_naming_scope_v1"

    def __init__(self, rows: int) -> None:
        self.rows = rows


class DeclaredNamingTaskDataPath:
    """Four frozen ``TaskDataPath`` methods plus the optional scope capability."""

    task_data_path_id = TASK_ID

    # --- the four FROZEN methods ---------------------------------------
    def training_dataset(self, scope: Any, params: Any) -> Dataset:
        return _PairDataset(scope.rows)

    def validation_dataset(self, scope: Any, params: Any) -> Dataset:
        return _PairDataset(scope.rows)

    def write_deliverable(self, outputs: Any, request: Any) -> None:
        """Persist ONE JSON artifact under THIS TASK'S DECLARED name.

        The name comes from ``deliverable_name`` below — i.e. from the
        framework's naming authority — which is precisely what fails when the
        child never bound the run's declaration.
        """
        os.makedirs(request.output_dir, exist_ok=True)
        path = os.path.join(request.output_dir, deliverable_name(request))
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"samples": len(list(outputs))}, handle)

    def read_evaluation_payload(self, request: Any) -> object:
        path = os.path.join(request.deliverable_dir, deliverable_name(request))
        if not os.path.exists(path):
            return {}
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)

    # --- the OPTIONAL sibling scope capability (CAP-SCOPE) --------------
    def build_training_scope(self, request: Any) -> object:
        return FcovScope(rows=_ROWS)

    def build_eval_scope(self, request: Any) -> object:
        return FcovScope(rows=_ROWS)

    def serialize_scope(self, scope: Any) -> str:
        return json.dumps({"kind": FcovScope.KIND, "rows": scope.rows})

    def deserialize_scope(self, payload: str) -> object:
        raw = json.loads(payload)
        if raw.get("kind") != FcovScope.KIND:
            raise ValueError(
                f"scope payload declares kind {raw.get('kind')!r}, not {FcovScope.KIND!r} "
                "— the binding and the scope object must come from the same task."
            )
        return FcovScope(rows=int(raw["rows"]))


class DeclaredNamingScanMetric(EvaluationMetric):
    """Scores the payload the SCAN produced, and refuses an empty one.

    The scoring child's ``read_evaluation_payload`` is the run's
    deliverable-resolution authority. When the naming binding is missing that
    scan looks for the SHIPPED template, finds nothing, and hands back ``{}``
    — which a metric that tolerated emptiness would silently score as zero.

    Raising here is what turns *"the scan disagreed with the spec"* from a
    silent condition into an observable one, so the F-COV-8 scoring witness
    asserts on the scan's OUTPUT rather than merely on the absence of a crash.
    """

    def _compute(
        self,
        deliverables: Any,
        /,
        *,
        evaluation_payload: Any = None,
        **_unused: Any,
    ) -> tuple[float, list[float | None] | None, tuple[str, ...]]:
        payload = evaluation_payload or {}
        if not payload:
            raise ValueError(
                "the deliverable SCAN returned an empty payload: "
                "read_evaluation_payload did not resolve this task's artifact "
                "under its DECLARED naming template."
            )
        return float(payload["samples"]), None, ()


def deliverable_name(request: Any) -> str:
    """THE CONSUMER — the module-level namer the framework looks for.

    ``task_declared_deliverable_name`` (``task_data_path.py:999``) and
    ``_task_names_its_own_deliverables`` (``deliverable_spec.py:458``) both
    key on the PRESENCE of this module-level symbol. Declaring it says *"this
    task owns its artifact names"*; resolving through the naming authority
    says *"and it owns them by the framework's declared indexed template"*.

    That combination is legal, documented and — until F-COV-8 — unreachable
    in the inference child.
    """
    from execute_tools.deliverable_spec import resolve_deliverable_naming

    return resolve_deliverable_naming().name(
        model_type=request.model_type,
        run_name=request.run_name,
        exp_id=request.exp_id,
        input_identity=0,
    )
