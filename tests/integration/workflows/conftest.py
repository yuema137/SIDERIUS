"""Opt-in task binding for workflow orchestration tests."""

from pathlib import Path

import pytest

from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings


@pytest.fixture
def offline_workflow(monkeypatch):
    """Refuse external effects and provide declared CPU hardware facts."""
    from datetime import UTC, datetime

    from core.hardware_context import HardwareContext
    from tests.helpers.tuner_composed_effects import _install_effect_backstop

    _install_effect_backstop(monkeypatch)
    hardware = HardwareContext(
        device_name="cpu",
        total_memory_bytes=0,
        compute_capability=(0, 0),
        multiprocessor_count=0,
        torch_version="fixture",
        hostname="workflow-fixture",
        device_available=False,
        discovered_at=datetime(2000, 1, 1, tzinfo=UTC),
    )
    monkeypatch.setattr(
        "workflows.model_exploration.get_or_create_hardware_context",
        lambda *args, **kwargs: hardware,
    )


@pytest.fixture
def workflow_composition(tmp_path, offline_workflow):
    """Bind an explicit lightweight task; callers must still pass its identity."""
    root = Path(__file__).resolve().parents[3]
    composition = compose_run_task_bindings(root / "configs/task_composition/quickstart.yaml")
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    with bind_run_task_composition(composition, physical_data_root=str(data_dir)):
        yield composition
