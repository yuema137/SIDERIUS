"""Regression tests for task-valid samples at VRAM admission."""

from __future__ import annotations

from importlib import import_module
from types import SimpleNamespace

probe_data = import_module("nodes.ml_hyperparameter_tune_agent.probe_data")


class _ScopeCapability:
    def serialize_scope(self, scope: object) -> str:
        assert scope == {"networks": ["a"]}
        return '{"kind":"synthetic","networks":["a"]}'

    def max_inference_batch_size(self) -> int:
        return 1


def test_composed_training_scope_becomes_a_typed_worker_reference(monkeypatch):
    """Dropping this projection recreates the all-zero semantic target."""
    capability = _ScopeCapability()
    monkeypatch.setattr(probe_data, "active_task_manifest_path", lambda: "/task/composition.yaml")
    monkeypatch.setattr(probe_data, "require_bound_task_data_path", lambda: capability)
    monkeypatch.setattr(probe_data, "resolve_task_scope_capability", lambda value: value)

    result = probe_data.build_task_probe_data(
        task_composition_ref=SimpleNamespace(semantic_fingerprint="abc123"),
        task_scopes=SimpleNamespace(training={"networks": ["a"]}),
        data_dir="/task/data",
        epoch_seed=17,
        train_portion=0.25,
        max_samples=8,
    )

    assert result is not None
    assert result.manifest_path == "/task/composition.yaml"
    assert result.semantic_fingerprint == "abc123"
    assert result.training_scope_payload == '{"kind":"synthetic","networks":["a"]}'
    assert result.max_inference_batch_size == 1
    assert result.sampling.model_dump() == {
        "data_dir": "/task/data",
        "epoch_seed": 17,
        "train_portion": 0.25,
        "max_samples": 8,
    }


def test_uncomposed_attempt_retains_the_legacy_synthetic_probe():
    result = probe_data.build_task_probe_data(
        task_composition_ref=None,
        task_scopes=SimpleNamespace(training=None),
        data_dir=None,
        epoch_seed=None,
        train_portion=None,
        max_samples=None,
    )
    assert result is None
