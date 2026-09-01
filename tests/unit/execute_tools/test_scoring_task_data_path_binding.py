"""The task-owned scoring call keeps its resolved data implementation active."""

from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace


def test_metric_executes_under_the_resolved_task_data_path(monkeypatch, tmp_path) -> None:
    """Defect caught: an isolated metric importing its experiment package.

    A file-bound metric and its task data path belong to one composition, but
    the scoring child used to unwind the task binding before invoking metric
    arithmetic.  A metric that reused a task-owned decoding capability then
    had to import the external repository through ambient ``PYTHONPATH``.
    This test fails when the binding covers scope decoding only instead of the
    primary and secondary evaluation calls as well.
    """
    from execute_tools import denoising_score_single as scoring
    from execute_tools.task_data_path import require_bound_task_data_path

    class DataPath:
        task_data_path_id = "synthetic_scoring_binding"

        def read_evaluation_payload(self, request):
            return {"sample": 1}

    data_path = DataPath()
    observed: list[object] = []

    class Metric:
        def evaluate(self, deliverables, **compute_kwargs):
            observed.append(require_bound_task_data_path())
            return object()

    args = SimpleNamespace(
        task_eval_scope_ref=str(tmp_path / "scope.json"),
        task_eval_scope_digest="digest",
        data_dir=str(tmp_path),
        raw_data_dir=str(tmp_path),
        exp_id="experiment",
        run_name="run",
        denoising_model="model",
    )

    monkeypatch.setattr(scoring, "_resolve_child_data_path", lambda _args: data_path)
    monkeypatch.setattr(
        "execute_tools.scope_artifact.load_transported_scope",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        "execute_tools.deliverable_spec.declared_naming_binding",
        lambda _naming: nullcontext(),
    )
    monkeypatch.setattr(
        "execute_tools.task_data_path.task_declared_deliverable_name",
        lambda _data_path, _request: "prediction.bin",
    )
    monkeypatch.setattr(scoring, "_evaluate_task_owned_secondaries", lambda *_args: {})
    monkeypatch.setattr(scoring, "_emit_outcome", lambda *_args, **_kwargs: None)

    scoring._emit_task_owned_score(args, object(), Metric(), declared_naming=None)

    assert observed == [data_path]
