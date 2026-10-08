"""A resource probe must preserve the task's resolved training tail policy."""

from contextlib import nullcontext
from types import SimpleNamespace

import pytest
import torch
from torch.utils.data import TensorDataset

from execute_tools import task_probe_batch
from execute_tools.task_data_path import EpochSamplingParams, TaskProbeDataSpec


@pytest.fixture
def task_batch_source(monkeypatch, tmp_path):
    reference = TaskProbeDataSpec(
        manifest_path=str(tmp_path / "task.yaml"),
        semantic_fingerprint="a" * 64,
        training_scope_payload="opaque training scope",
        sampling=EpochSamplingParams(data_dir=str(tmp_path)),
        segmentation_applicability="not_applicable",
    )

    def install(rows):
        inputs = torch.arange(rows * 2, dtype=torch.float32).reshape(rows, 2)
        targets = torch.arange(rows, dtype=torch.int64)
        scope = object()

        def training_dataset(actual_scope, sampling):
            assert actual_scope is scope
            assert sampling == reference.sampling
            return TensorDataset(inputs, targets)

        data_path = SimpleNamespace(training_dataset=training_dataset)
        composition = SimpleNamespace(semantic_fingerprint="a" * 64, task_data_path=data_path)
        monkeypatch.setattr(task_probe_batch, "compose_run_task_bindings", lambda _: composition)
        monkeypatch.setattr(
            task_probe_batch, "bind_run_task_composition", lambda *a, **k: nullcontext()
        )
        monkeypatch.setattr(
            task_probe_batch,
            "resolve_task_scope_capability",
            lambda _: SimpleNamespace(deserialize_scope=lambda _: scope),
        )
        return reference, inputs, targets

    return install


@pytest.mark.parametrize("rows", [0, 1, 3, 4, 5])
@pytest.mark.parametrize("drop_last", [True, False])
def test_real_loader_retains_only_the_declared_tail(task_batch_source, rows, drop_last):
    reference, inputs, targets = task_batch_source(rows)
    if rows == 0 or (drop_last and rows < 4):
        message = "one full resource probe batch of size 4" if drop_last else "no training samples"
        with pytest.raises(ValueError, match=message):
            task_probe_batch.load_task_probe_batch(reference, 4, drop_last=drop_last)
        return
    actual = task_probe_batch.load_task_probe_batch(reference, 4, drop_last=drop_last)
    assert len(actual) == 2
    assert torch.equal(actual[0], inputs[:4])
    assert torch.equal(actual[1], targets[:4])


def test_omitted_policy_keeps_full_batch_refusal(task_batch_source):
    reference, _, _ = task_batch_source(1)
    with pytest.raises(ValueError, match="one full resource probe batch of size 4"):
        task_probe_batch.load_task_probe_batch(reference, 4)


@pytest.mark.parametrize("policy", [{}, {"drop_last": True}, {"drop_last": False}])
def test_structural_worker_passes_policy_to_real_loader(
    task_batch_source, tmp_path, monkeypatch, policy
):
    from agent.skills.evaluate_vram_skill import preflight_worker_main, wrapper
    from agent.skills.evaluate_vram_skill.isolated_probe import IsolatedProbeSpec

    reference, inputs, targets = task_batch_source(1)
    captured = {}

    def capture(_sandbox, **kwargs):
        captured.update(kwargs)
        return {"status": "success", "feasible": True}

    monkeypatch.setattr(wrapper, "run_skill", capture)
    spec = IsolatedProbeSpec(
        label="tail-policy",
        model_type="synthetic",
        train_config={"batch_size": 4, **policy},
        task_probe_data=reference,
        result_path=str(tmp_path / "result.json"),
        worker_memory_limit_bytes=1024**3,
    )
    path = tmp_path / "request.json"
    path.write_text(spec.model_dump_json())
    status = preflight_worker_main.main([str(path)])
    if policy.get("drop_last", True):
        assert status != 0
        assert not captured
        assert "one full resource probe batch" in (tmp_path / "result.json").read_text()
    else:
        assert status == 0
        assert torch.equal(captured["probe_input_sample"], inputs)
        assert torch.equal(captured["probe_target_sample"], targets)
        assert captured["train_config"]["batch_size"] == 4
