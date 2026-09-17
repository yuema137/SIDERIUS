"""Cleanup deletes its declared scope, never a neighbour's artifacts.

Replaces Step-05c's scientific-filename filesystem oracles. The two REAL
cleanup sites intentionally differ: watchdog cleanup is attempt-qualified;
the tuner retires only an exact attempt's declared outputs. Only expensive execution is stubbed.
Both deleted and surviving file sets are asserted against explicit literals.
"""

import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest

import core.sandbox_executor as sandbox_module
from core.sandbox_executor import TidmadSandbox
from execute_tools.deliverable_spec import DeliverableNaming
from execute_tools.task_data_path import EvaluationReadRequest, TaskOutputArtifactInventory

execution = importlib.import_module("nodes.ml_hyperparameter_tune_agent.execution")

NAMING = DeliverableNaming(prefix="prediction", extension=".npz", index_width=3)
ATTEMPT_FILES = {"prediction_model_run_exp_000.npz", "prediction_model_run_exp_007.npz"}
SAME_EXPERIMENT = {"prediction_other_other_exp_002.npz"}
UNRELATED = {
    "prediction_model_run_otherexp_000.npz",
    "prediction_model_run_exp_000.txt",
    "alternate_model_run_exp_000.npz",
    "raw_input.npz",
    "checkpoint.pth",
}
ALL_FILES = ATTEMPT_FILES | SAME_EXPERIMENT | UNRELATED


def _seed(root: Path) -> None:
    for name in ALL_FILES:
        (root / name).write_bytes(b"retained evidence")


def _assert_cleanup(root: Path, deleted: set[str], *, receipts: bool = False) -> None:
    survivors = {p.name for p in root.iterdir() if p.is_file()}
    expected = ALL_FILES - deleted
    if receipts:
        expected = expected | {"model_output_retention_receipts.jsonl"}
    assert survivors == expected
    assert ALL_FILES - survivors == deleted


@pytest.mark.usefixtures("synthetic_run_authorities", "synthetic_physical_data_root")
@pytest.mark.parametrize("naming", [NAMING, None], ids=["declared", "task-owned-lifecycle"])
def test_watchdog_cleanup_is_attempt_qualified(tmp_path, monkeypatch, naming):
    _seed(tmp_path)
    sandbox = TidmadSandbox(
        run_name="run",
        workspace=str(tmp_path),
        progress_bar=False,
        deliverable_naming=naming,
    )
    # This suite concerns cleanup after an observed kill, not subprocess
    # execution or model validation. Preserve the real argv/kill branch.
    monkeypatch.setattr(sandbox, "_validate_model_and_loss", lambda *args: ({}, {}))
    result = SimpleNamespace(returncode=-9, stdout="", stderr="")
    kill = {"elapsed_s": 12.0, "deadline_s": 10.0, "estimate_source": "fixture"}
    monkeypatch.setattr(sandbox_module, "_run_observed_subprocess", lambda *a, **k: (result, kill))
    outcome = sandbox.execute_inference(
        "exp",
        "run",
        "model",
        {},
        {},
        inference_batch=1,
        sample_set={"0": [0]},
        runtime_policy={"watchdog": {"enabled": True}},
    )
    assert outcome["status"] == "wall_clock_timeout", outcome
    _assert_cleanup(tmp_path, ATTEMPT_FILES if naming is not None else set())


class _InferenceFailure(RuntimeError):
    pass


class _TaskOutputInventory:
    def enumerate_output_artifacts(
        self, request: EvaluationReadRequest
    ) -> TaskOutputArtifactInventory:
        return TaskOutputArtifactInventory(
            run_name=request.run_name,
            exp_id=request.exp_id,
            model_type=request.model_type,
            relative_paths=tuple(sorted(ATTEMPT_FILES)),
        )


@pytest.mark.parametrize(
    "retain,naming,task,deleted",
    [
        (False, NAMING, None, ATTEMPT_FILES),
        (True, NAMING, None, set()),
        (False, None, _TaskOutputInventory(), ATTEMPT_FILES),
    ],
    ids=["legacy-attempt", "retained", "task-owned-attempt"],
)
def test_tuner_finally_cleanup_preserves_other_experiments(
    tmp_path, monkeypatch, retain, naming, task, deleted
):
    _seed(tmp_path)
    # Only fields read before inference are needed: the deliberate failure
    # happens at the first skill call. The actual production finally runs.
    bindings = SimpleNamespace(
        agent_input=SimpleNamespace(retain_model_outputs=retain),
        anchor_map_data=None,
        expert_advice_str="",
        file_index=0,
        reference_scores=None,
        run_deliverable_naming=naming,
        run_task_data_path=task,
        run_metric=None,
        run_secondary_metrics=(),
        run_name="run",
        run_profile=None,
        sandbox=SimpleNamespace(base_dir=str(tmp_path)),
        workspace=str(tmp_path),
    )
    prepared = SimpleNamespace(
        active_params={},
        eval_sample_set=None,
        exp_id="exp",
        hypothesis="fixture",
        model_type="model",
        plan=None,
        record_params={},
    )

    def fail_inference(*args, **kwargs):
        raise _InferenceFailure("synthetic failure after artifact creation")

    monkeypatch.setattr(execution._runtime, "_run_skill", fail_inference)
    with pytest.raises(_InferenceFailure, match="synthetic failure"):
        execution.run_inference_scoring_health(
            bindings,
            prepared,
            SimpleNamespace(attempt_in_round=1, round_index=1),
            SimpleNamespace(name="training"),
            train_time=0,
            training_results={},
        )
    _assert_cleanup(tmp_path, deleted, receipts=True)
