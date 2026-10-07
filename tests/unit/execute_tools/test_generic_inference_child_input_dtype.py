"""2026-09-18 NoPrior incident: the real inference child omitted input_dtype.

The lower-level iterator already accepted a dtype, so testing that iterator
alone would not catch the production omission. Exercise main, transported
scope and ModelIO JSON, a strict model, and the task's actual writer on CPU.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import torch
import yaml

from execute_tools import inference_single
from tests.fixtures.integer_input_inference_task import IntegerInputTaskDataPath
from tests.helpers.composed_manifest import write_complete_manifest
from workflows.task_composition import compose_run_task_bindings

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize(
    ("admissible", "expected"),
    [
        (["int64", "int32"], torch.int64),
        (["int32", "int64"], torch.int32),
        (["float32"], torch.float32),
        (["complex64"], None),
        (None, torch.int16),
    ],
)
def test_child_converts_storage_input_using_transported_contract(
    tmp_path, monkeypatch, admissible, expected
):
    """Fails before the fix for every declared dtype; absent contract preserves storage."""
    seen = []

    class StrictModel(torch.nn.Module):
        def __init__(self, config=None):
            super().__init__()
            self.weight = torch.nn.Parameter(torch.ones(()))

        def forward(self, x):
            assert x.dtype == expected, f"expected {expected}, got {x.dtype}"
            seen.append(x.detach().clone())
            return x.float() * self.weight

    class Config:
        segmentation_size = 4

        def __init__(self, **kwargs):
            pass

    impl = IntegerInputTaskDataPath()
    manifest = write_complete_manifest(
        tmp_path,
        task_data_path={
            "file": str(ROOT / "tests/fixtures/integer_input_inference_task.py"),
            "symbol": "IntegerInputTaskDataPath",
            "id": impl.task_data_path_id,
        },
        deliverable={"prefix": "pred", "extension": ".json", "index_width": 3},
    )
    composition = compose_run_task_bindings(str(manifest))
    profile = tmp_path / "profile.json"
    profile.write_text(composition.dataset_profile.model_dump_json())
    raw = impl.serialize_scope(impl.build_eval_scope(None)).encode()
    scope = tmp_path / "scope.json"
    scope.write_bytes(raw)
    checkpoint = tmp_path / "model.pth"
    torch.save(StrictModel().state_dict(), checkpoint)
    (tmp_path / "_OK_exp").write_text("ok")
    model_config = tmp_path / "model.json"
    model_config.write_text(json.dumps({"segmentation_size": 4}))
    loss_config = tmp_path / "loss.json"
    loss_config.write_text(json.dumps({"loss_type": "smooth_l1"}))
    output = tmp_path / "out"
    argv = [
        "inference_single.py", "--mode", "agent",
        "--denoising_model", "strict_input_fixture",
        "--model_cfg", str(model_config), "--loss_cfg", str(loss_config),
        "--model_path", str(checkpoint), "--exp_id", "exp", "--run_name", "run",
        "--output_dir", str(output), "--data_dir", str(tmp_path),
        "--dataset_profile_json", str(profile), "--task_manifest", str(manifest),
        "--task_data_path_id", impl.task_data_path_id,
        "--task_eval_scope_ref", str(scope),
        "--task_eval_scope_digest", hashlib.sha256(raw).hexdigest(),
        "--inference_batch_size", "2",
        "--runtime_observation_out", str(tmp_path / "runtime.json"),
    ]  # fmt: skip
    if admissible is not None:
        # Use the framework synthetic pack's valid contract, changing only
        # the model input representation. No external scientific task needed.
        contract = yaml.safe_load(
            (ROOT / "examples/quickstart/declared/task_config.yaml").read_text()
        )["forward_contract"]["model_io"]
        contract["input"]["dtype"]["admissible"] = admissible
        contract_file = tmp_path / "model_io.json"
        contract_file.write_text(json.dumps(contract))
        argv += ["--model_io_json", str(contract_file)]
    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(inference_single, "DEVICE", torch.device("cpu"))
    from ml_models.models_sandbox import MODEL_REGISTRY

    monkeypatch.setitem(MODEL_REGISTRY, "strict_input_fixture", StrictModel)
    monkeypatch.setattr("ml_models.models_format_sandbox.get_config_class", lambda _: Config)
    if expected is None:
        from execute_tools.model_input_dtype import UnsupportedModelInputDtypeError

        with pytest.raises(UnsupportedModelInputDtypeError, match="runtime-supported"):
            inference_single.main()
        assert not seen
        assert not output.exists()
        return
    inference_single.main()

    assert torch.cat(seen).tolist() == [list(range(-6, -2)), list(range(-2, 2)), list(range(2, 6))]
    assert json.loads((output / "pred_strict_input_fixture_run_exp_000.json").read_text()) == {
        "samples": 3
    }

    # The composed route must persist evidence even when a short scope cannot
    # establish steady state. Previously it returned before session creation.
    observation = json.loads((tmp_path / "runtime.json").read_text())
    component = observation["components"]["inference"]
    assert component["actual_seconds"] > 0
    assert component["workload"]["unit_count"] == 3
    assert component["measurement"] is not None
