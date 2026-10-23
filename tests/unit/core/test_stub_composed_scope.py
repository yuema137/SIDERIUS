"""Issue 837: actual skill calls must reach scope-aware synthetic execution.

Deleting either stub parameter recreates the wrapper TypeError. Bypassing the
scope owner loses artifacts and accepts foreign/unbound scopes. These are
runtime caller/opaque-codec properties, not schema declaration tests.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.skills.denoising_score_skill.wrapper import run_skill as score
from agent.skills.inference_skill.wrapper import run_skill as infer
from core.sandbox_executor import StubSandbox
from execute_tools.scope_artifact import EVAL_SCOPE_STEM, TRAINING_SCOPE_STEM, scope_artifact_path
from execute_tools.task_data_path import ScopeBuildRequest
from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings

pytestmark = pytest.mark.usefixtures("synthetic_dataset_profile", "synthetic_physical_data_root")

MANIFEST = Path(__file__).resolve().parents[3] / "configs/task_composition/quickstart.yaml"
PARAMS = {
    "exp_id": "scope_attempt",
    "run_name": "scope_run",
    "model_type": "synthetic_model",
    "model_config": {},
    "train_config": {},
    "loss_config": {"loss_type": "ce"},
}


@pytest.fixture
def composed(tmp_path):
    composition = compose_run_task_bindings(str(MANIFEST))
    task = composition.task_data_path
    request = ScopeBuildRequest(
        round_kind="formal", selection_strategy="snapshot", portion=1.0, seed=0, max_samples=2
    )
    scopes = SimpleNamespace(
        training=task.build_training_scope(request), evaluation=task.build_eval_scope(request)
    )
    with bind_run_task_composition(composition, physical_data_root=str(tmp_path)):
        yield scopes, task


def test_composed_wrappers_preserve_synthetic_results_and_transport(
    tmp_path, composed, monkeypatch
):
    """Real wrapper kwargs reach both overrides, task codec, and cached results.

    Hardcoded timings and persisted pseudo marker prevent claiming real output;
    equal seeded scoring results pin RNG consumption against the legacy path.
    """
    scopes, task = composed
    sandbox = StubSandbox(workspace=str(tmp_path / "composed"), run_id="same_stream")
    legacy = StubSandbox(workspace=str(tmp_path / "legacy"), run_id="same_stream")

    def forbidden(*args, **kwargs):
        pytest.fail("pseudo scope transport must never execute a child")

    monkeypatch.setattr("core.sandbox_executor.subprocess.run", forbidden)
    monkeypatch.setattr("core.sandbox_executor.subprocess.Popen", forbidden)
    training = []
    for box in (sandbox, legacy):
        training.append(
            box.execute_training(
                "scope_attempt", "scope_run", "synthetic_model", {}, {}, PARAMS["loss_config"]
            )
        )

    inference = infer(sandbox, **PARAMS, task_scopes=scopes)
    assert inference == infer(legacy, **PARAMS)
    assert inference["message"] == "stub_inference_ok"
    assert inference["process_startup_ms"] == inference["subprocess_wall_ms"] == 10.0
    assert inference["runtime_verification"] is None
    # Pin the inference hop before scoring can write the same artifacts.
    for stem, scope in (
        (TRAINING_SCOPE_STEM, scopes.training),
        (EVAL_SCOPE_STEM, scopes.evaluation),
    ):
        path = Path(scope_artifact_path(sandbox.dirs["configs"], stem, "scope_attempt"))
        assert path.read_text() == task.serialize_scope(scope)
        path.unlink()

    scoring = score(sandbox, **PARAMS, task_scopes=scopes)
    assert scoring == score(legacy, **PARAMS)
    assert scoring["results"]["final_loss"] == training[0]["results"]["final_loss"]
    assert -3.0 <= scoring["results"]["denoising_score"] <= -2.0
    for stem, scope in (
        (TRAINING_SCOPE_STEM, scopes.training),
        (EVAL_SCOPE_STEM, scopes.evaluation),
    ):
        path = Path(scope_artifact_path(sandbox.dirs["configs"], stem, "scope_attempt"))
        assert path.read_text() == task.serialize_scope(scope)
    sandbox.save_record({"exp_id": "scope_attempt", "status": "success"})
    assert sandbox.saved_records[-1]["_pseudo_origin"] == "stub_sandbox"
    assert not list(Path(legacy.dirs["configs"]).glob("*scope*"))


@pytest.mark.parametrize("wrapper", [infer, score], ids=["inference", "scoring"])
@pytest.mark.parametrize("leg", ["training", "evaluation"])
def test_wrapper_rejects_scope_owned_by_another_task(tmp_path, composed, wrapper, leg):
    """Dropping either scope leg must fail this real task codec witness."""
    scopes, _ = composed
    setattr(scopes, leg, object())
    sandbox = StubSandbox(workspace=str(tmp_path))
    with pytest.raises(ValueError, match="quickstart received a scope"):
        wrapper(sandbox, **PARAMS, task_scopes=scopes)


@pytest.mark.parametrize("wrapper", [infer, score], ids=["inference", "scoring"])
def test_wrapper_refuses_unbound_scopes(tmp_path, wrapper):
    """A present training scope requires its producer binding, even in pseudo."""
    sandbox = StubSandbox(workspace=str(tmp_path))
    with pytest.raises(ValueError, match="no task data path is bound"):
        wrapper(sandbox, **PARAMS, task_scopes=SimpleNamespace(training=object()))


@pytest.mark.parametrize("wrapper", [infer, score], ids=["inference", "scoring"])
def test_composed_scope_artifact_refuses_traversal_before_effects(tmp_path, composed, wrapper):
    """New pseudo artifact writes must not turn an attempt id into a path."""
    scopes, _ = composed
    sandbox = StubSandbox(workspace=str(tmp_path))
    params = {**PARAMS, "exp_id": "../../../escape"}
    paths_before = set(tmp_path.rglob("*"))
    rng_before = sandbox._rng.getstate()
    with pytest.raises(ValueError, match=r"exp_id.*filesystem component"):
        wrapper(sandbox, **params, task_scopes=scopes)
    assert set(tmp_path.rglob("*")) == paths_before
    assert sandbox._rng.getstate() == rng_before
    # Legacy pseudo calls did not derive paths from exp_id; retain that API.
    assert wrapper(sandbox, **params)["status"] == "success"


def test_legacy_sample_scope_refusal_precedes_composed_artifact_writes(tmp_path, composed):
    """Adding transport must preserve inference's no-I/O SampleSet refusal."""
    from execute_tools.dataset_config import DataScope

    scopes, _ = composed
    sandbox = StubSandbox(workspace=str(tmp_path), data_scope=DataScope(file_indices=[0]))
    before = set(tmp_path.rglob("*"))
    result = infer(sandbox, **PARAMS, task_scopes=scopes, eval_sample_set={2: [0]})
    assert result["status"] == "error"
    assert result["error_type"] == "scope_violation"
    assert result["process_startup_ms"] is None
    assert set(tmp_path.rglob("*")) == before
