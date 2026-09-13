"""The public modular manifest shares task types across actual family owners."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from core.local_code import LocalCodeError
from core.local_code.child import prepare_child
from core.run_invariants import (
    RunInvariantsViolation,
    ensure_run_invariants,
    validate_run_invariants,
)
from core.subprocess_env import subprocess_env
from execute_tools.health_checks import runner
from execute_tools.health_checks.config import materialize_effective_config
from execute_tools.health_checks.schemas import HealthCheckContext
from execute_tools.task_data_path import ScopeBuildRequest
from execute_tools.task_registration_scope import run_registration_scope
from ml_models.loss_models_sandbox import register_loss_in_memory
from ml_models.plugin_loader import register_model_in_memory
from tests.unit.core.test_local_code_transport import bind_workspace
from tests.unit.core.test_step11_c8_invariants_resume import _invariants
from tests.unit.examples.test_synthetic_masked_regression_pack import _restore_health_plugin_globals
from tests.unit.ml_models.test_loss_functions import _l6c_clear_loss_registry
from tests.unit.ml_models.test_step12_pr12d_dp_plugin_binding import _clean_registries
from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings

PACK = Path(__file__).resolve().parents[3] / "examples/synthetic_masked_regression"
pytestmark = pytest.mark.usefixtures(
    "_restore_health_plugin_globals", "_clean_registries", "_l6c_clear_loss_registry"
)


@pytest.fixture(autouse=True)
def restore_loss_reductions():
    from ml_models.loss_plugin_loader import LOSS_REDUCTION_REGISTRY

    saved = dict(LOSS_REDUCTION_REGISTRY)
    yield
    LOSS_REDUCTION_REGISTRY.clear()
    LOSS_REDUCTION_REGISTRY.update(saved)


def test_public_modular_manifest_runs_metric_health_and_independent_model_loss_acquisition(
    tmp_path, monkeypatch
):
    bind_workspace(tmp_path, monkeypatch)
    pack = tmp_path / "consumer"
    shutil.copytree(PACK, pack)
    artifact = tmp_path / "payload.json"
    payload = {
        "a": {"prediction": 0.0, "target": 1.0, "valid": True},
        "b": {"prediction": 2.0, "target": 1.0, "valid": True},
        "c": {"prediction": 999.0, "target": 0.0, "valid": False},
    }
    artifact.write_text(json.dumps(payload))
    with run_registration_scope():
        composition = compose_run_task_bindings(str(pack / "modular/composition.yaml"))
        with bind_run_task_composition(composition, physical_data_root=str(tmp_path)):
            scope = composition.task_data_path.build_eval_scope(
                ScopeBuildRequest(
                    round_kind="formal", selection_strategy="snapshot", portion=1.0, max_samples=2
                )
            )
            result = composition.metric.evaluate(
                {0: str(artifact)}, evaluation_payload=payload, task_scope=scope
            )
            assert result.scalar == 1.0
            with pytest.raises(TypeError, match="shared MaskedScope"):
                composition.metric.evaluate(
                    {0: str(artifact)}, evaluation_payload=payload, task_scope=object()
                )
            assert not composition.metric.check_scoreability(
                {0: str(tmp_path / "absent")}
            ).scoreable
            assert type(composition.metric.spec.scoreability).__module__.endswith(
                ".modular._metrics"
            )

            from ml_models.loss_models_sandbox import LOSS_REGISTRY
            from ml_models.models_format_sandbox import PLUGIN_CONFIG_REGISTRY
            from ml_models.models_sandbox import MODEL_REGISTRY

            # Independently reach file-family registration, not merely objective resolution.
            MODEL_REGISTRY.pop("masked_reference_mlp")
            LOSS_REGISTRY.pop("synthetic_masked_mse", None)
            assert (
                register_model_in_memory(str(pack / "plugins/masked_reference_mlp.py"))
                == "masked_reference_mlp"
            )
            assert (
                register_loss_in_memory(str(pack / "plugins/masked_mse_loss.py"))
                == "synthetic_masked_mse"
            )
            assert (
                MODEL_REGISTRY["masked_reference_mlp"].__module__.split(".")[0]
                == type(scope).__module__.split(".")[0]
            )
            assert (
                LOSS_REGISTRY["synthetic_masked_mse"].__module__.split(".")[0]
                == type(scope).__module__.split(".")[0]
            )
            model = MODEL_REGISTRY["masked_reference_mlp"](
                PLUGIN_CONFIG_REGISTRY["masked_reference_mlp"]()
            )
            assert composition.observables.static[0].implementation.compute(model) == 41.0
            effective, _ = materialize_effective_config(
                None,
                None,
                str(tmp_path / "workspace"),
                task_health_binding=composition.task_health_binding,
            )
            result = runner.evaluate_gate(
                "synthetic_masked_prediction_dispersion",
                HealthCheckContext(
                    model_name="fixture",
                    run_name="modular",
                    round_index=1,
                    evaluation_payload_fn=lambda: json.loads(artifact.read_text()),
                ),
                config_path=effective,
            )
            assert result.passed
            assert result.check_results[0].check_name == "modular_prediction_dispersion"
            assert result.check_results[0].metrics["dispersion"] == 1.0


def test_public_package_relocation_preserves_identity_and_helper_edit_refuses_resume(
    tmp_path, monkeypatch
):
    bind_workspace(tmp_path, monkeypatch)
    compositions = []
    for directory in (tmp_path / "first", tmp_path / "unrelated/second"):
        shutil.copytree(PACK, directory)
        with run_registration_scope():
            compositions.append(
                compose_run_task_bindings(str(directory / "modular/composition.yaml"))
            )
    first, second = compositions
    assert first.semantic_fingerprint == second.semantic_fingerprint
    request = ScopeBuildRequest(
        round_kind="formal", selection_strategy="snapshot", portion=1.0, max_samples=2
    )
    scope_a = first.task_data_path.build_eval_scope(request)
    scope_b = second.task_data_path.build_eval_scope(request)
    assert type(scope_a) is not type(scope_b)
    assert first.task_data_path.serialize_scope(scope_a) == second.task_data_path.serialize_scope(
        scope_b
    )
    artifact = tmp_path / "artifact.json"
    artifact.write_text("{}")
    payload = {"row": {"prediction": 2.0, "target": 1.0, "valid": True}}
    assert (
        second.metric.evaluate(
            {0: str(artifact)}, evaluation_payload=payload, task_scope=scope_b
        ).scalar
        == 1.0
    )
    with pytest.raises(TypeError, match="shared MaskedScope"):
        second.metric.evaluate({0: str(artifact)}, evaluation_payload=payload, task_scope=scope_a)
    workspace = str(tmp_path / "resume")
    ensure_run_invariants(
        workspace, _invariants(task_composition_fingerprint=first.semantic_fingerprint)
    )
    validate_run_invariants(
        workspace, _invariants(task_composition_fingerprint=second.semantic_fingerprint)
    )
    helper = tmp_path / "unrelated/second/modular/_shared.py"
    original = helper.read_bytes()
    try:
        helper.write_bytes(original + b"\n# intentional helper edit\n")
        with run_registration_scope():
            changed = compose_run_task_bindings(str(helper.parent / "composition.yaml"))
        assert changed.semantic_fingerprint != first.semantic_fingerprint
        with pytest.raises(RunInvariantsViolation, match="task_composition_fingerprint"):
            validate_run_invariants(
                workspace, _invariants(task_composition_fingerprint=changed.semantic_fingerprint)
            )
    finally:
        helper.write_bytes(original)


_CHILD = """\
import json, sys
from pathlib import Path
Path(sys.argv[2]).touch()
from ml_models.models_sandbox import MODEL_REGISTRY
from ml_models.loss_models_sandbox import _load_custom_loss
assert MODEL_REGISTRY["masked_reference_mlp"].__module__.startswith("_siderius_task_")
loss = _load_custom_loss("synthetic_masked_mse")
assert type(loss).__module__.startswith("_siderius_task_")
from execute_tools.task_data_path import ScopeBuildRequest
from workflows.task_composition import compose_run_task_bindings, bind_run_task_composition
composition = compose_run_task_bindings(sys.argv[1])
with bind_run_task_composition(composition, physical_data_root=sys.argv[3]):
    scope = composition.task_data_path.build_eval_scope(ScopeBuildRequest(
        round_kind="formal", selection_strategy="snapshot", portion=1.0, max_samples=2))
    result = composition.metric.evaluate({0: sys.argv[2]}, task_scope=scope,
        evaluation_payload={"row": {"prediction": 2., "target": 1., "valid": True}})
    assert result.scalar == 1.0
print("RECEIPT=" + json.dumps({"fingerprint": composition.semantic_fingerprint, "scalar": result.scalar}))
"""


@pytest.mark.parametrize("tampered", [False, True])
def test_public_composition_reaches_cold_family_loaders_and_refuses_helper_tamper(
    tmp_path, monkeypatch, tampered
):
    bind_workspace(tmp_path, monkeypatch)
    pack = tmp_path / "consumer"
    shutil.copytree(PACK, pack)
    manifest = pack / "modular/composition.yaml"
    script = tmp_path / "child.py"
    script.write_text(_CHILD)
    marker = tmp_path / "target-entered"
    helper = pack / "modular/_shared.py"
    original = helper.read_bytes()
    with run_registration_scope():
        composition = compose_run_task_bindings(str(manifest))
        with bind_run_task_composition(composition, physical_data_root=str(tmp_path)):
            invocation = prepare_child(
                [sys.executable, str(script), str(manifest), str(marker), str(tmp_path)],
                subprocess_env(),
            )
            if tampered:
                helper.write_bytes(
                    original + b"\nraise AssertionError('changed member executed')\n"
                )
            started = time.monotonic()
            try:
                result = subprocess.run(
                    invocation.argv,
                    env=invocation.env,
                    cwd=tmp_path,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                print(f"cold public example tampered={tampered}: {time.monotonic() - started:.3f}s")
                if tampered:
                    with pytest.raises(LocalCodeError, match="mismatch"):
                        invocation.check(result.returncode)
                    assert not marker.exists()
                else:
                    invocation.check(result.returncode)
                    assert result.returncode == 0, result.stdout + result.stderr
                    receipt = json.loads(
                        next(
                            line[8:]
                            for line in result.stdout.splitlines()
                            if line.startswith("RECEIPT=")
                        )
                    )
                    assert receipt == {
                        "fingerprint": composition.semantic_fingerprint,
                        "scalar": 1.0,
                    }
            finally:
                helper.write_bytes(original)
