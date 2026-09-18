"""A real validation sample must reach the production input boundary before training."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
import torch

from agent.skills.evaluate_vram_skill import wrapper
from execute_tools.inference_forward import InferenceInputError, forward_inference_batch
from execute_tools.task_data_path import EpochSamplingParams, TaskProbeDataSpec
from execute_tools.task_probe_batch import load_task_inference_probe_input
from tests.fixtures.integer_input_inference_task import IntegerInputTaskDataPath
from tests.helpers.composed_manifest import write_complete_manifest
from tests.helpers.step04a_fixtures import regressor_model_io
from tests.unit.agent.evaluate_vram_skill.test_wrapper_contract import _cpu_ctx
from workflows.task_composition import compose_run_task_bindings

ROOT = Path(__file__).resolve().parents[3]


def test_probe_reads_validation_scope_not_training_and_checks_fingerprint(tmp_path, monkeypatch):
    """Training data are float32 in this fixture; validation data are int16."""
    impl = IntegerInputTaskDataPath()
    manifest = write_complete_manifest(
        tmp_path,
        task_data_path={
            "file": str(ROOT / "tests/fixtures/integer_input_inference_task.py"),
            "symbol": "IntegerInputTaskDataPath",
            "id": impl.task_data_path_id,
        },
    )
    composition = compose_run_task_bindings(str(manifest))
    ref = TaskProbeDataSpec(
        manifest_path=str(manifest),
        semantic_fingerprint=composition.semantic_fingerprint,
        training_scope_payload="unused training scope",
        evaluation_scope_payload=impl.serialize_scope(impl.build_eval_scope(None)),
        sampling=EpochSamplingParams(data_dir=str(tmp_path)),
        segmentation_applicability="not_applicable",
    )
    sample = load_task_inference_probe_input(ref)
    assert sample.dtype == torch.int16
    assert sample.tolist() == [[-6, -5, -4, -3]]
    # Exercise the worker's actual JSON boundary. A standalone loader test
    # would stay green if the worker dropped the validation sample again.
    from agent.skills.evaluate_vram_skill import preflight_worker_main
    from agent.skills.evaluate_vram_skill.isolated_probe import HardwareSnapshot, IsolatedProbeSpec

    captured = {}

    def capture(_sandbox, **kwargs):
        captured.update(kwargs)
        return {"status": "success", "feasible": True}

    monkeypatch.setattr(wrapper, "run_skill", capture)
    spec = IsolatedProbeSpec(
        label="input-check",
        model_type="fixture",
        task_probe_data=ref,
        hardware=HardwareSnapshot(
            usable_cap_bytes=1024**3,
            usable_cap_gb=1.0,
            total_memory_bytes=1024**3,
            total_memory_gb=1.0,
            device_name="cpu",
            device_available=False,
            hardware_fingerprint="cpu-fixture",
        ),
        result_path=str(tmp_path / "result.json"),
        worker_memory_limit_bytes=1024**3,
    )
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(spec.model_dump_json())
    assert preflight_worker_main.main([str(spec_path)]) == 0
    assert torch.equal(captured["inference_probe_input"], sample)
    with pytest.raises(ValueError, match="fingerprint mismatch"):
        load_task_inference_probe_input(ref.model_copy(update={"semantic_fingerprint": "wrong"}))
    with pytest.raises(ValueError, match="contains no samples"):
        load_task_inference_probe_input(
            ref.model_copy(
                update={
                    "evaluation_scope_payload": json.dumps(
                        {"kind": impl.build_eval_scope(None).KIND, "rows": 0}
                    )
                }
            )
        )


def test_forward_type_error_carries_both_dtypes_and_phase():
    """The final traceback must explain the boundary, not just blame the plugin."""

    class RejectsInput(torch.nn.Module):
        def forward(self, x):
            raise TypeError("plugin rejects input")

    with pytest.raises(InferenceInputError) as caught:
        forward_inference_batch(
            RejectsInput(),
            torch.zeros(1, 4, dtype=torch.int16),
            device=torch.device("cpu"),
            input_dtype=torch.int64,
            stage="test inference",
        )
    message = str(caught.value)
    for detail in (
        "test inference",
        "RejectsInput",
        "storage_dtype=torch.int16",
        "resolved_input_dtype=torch.int64",
        "actual_input_dtype=torch.int64",
        "shape=(1, 4)",
    ):
        assert detail in message
    assert isinstance(caught.value.__cause__, TypeError)


@pytest.mark.parametrize("reject", [False, True])
def test_worker_wrapper_rejects_bad_validation_forward_before_training_probe(reject):
    """A CPU no-VRAM shortcut must not report success for an invalid eval boundary."""

    seen = []

    class StrictModel(torch.nn.Module):
        def forward(self, x):
            assert x.dtype == torch.int64
            assert not self.training
            seen.append(x.dtype)
            if reject:
                raise TypeError("deliberately incompatible validation input")
            return x.float()

    model = StrictModel()
    with (
        patch.object(wrapper, "_build_model", return_value=model),
        patch.object(wrapper, "get_criterion", return_value=torch.nn.MSELoss()),
        patch.object(wrapper, "probe_activation_footprint") as training_probe,
    ):
        outcome = wrapper.run_skill(
            None,
            model_type="strict_fixture",
            model_config={"segmentation_size": 4},
            train_config={"batch_size": 1},
            loss_config={"loss_type": "smooth_l1"},
            model_io_contract=regressor_model_io(),
            hardware_context=_cpu_ctx(),
            inference_probe_input=torch.zeros(1, 4, dtype=torch.int16),
        )
    assert seen == [torch.int64]
    if reject:
        assert outcome["status"] == "error"
        assert "pre-training inference check" in outcome["message"]
        assert "deliberately incompatible validation input" in outcome["message"]
    else:
        assert outcome["status"] == "success"
    training_probe.assert_not_called()
    assert model.training
