"""Opt-in task binding for workflow orchestration tests."""

import json
from pathlib import Path

import pytest
import yaml

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


@pytest.fixture
def supplied_outcome_composition(tmp_path, offline_workflow):
    """Bind 20 indexed partitions and a neutral metric for supplied scalar outcomes.

    The 1.25 incumbent and ordering witnesses are not measured accuracy. Compose
    their declared metric through the real manifest so persistence and replay
    compare the same identity as startup.
    """
    from tests.helpers.metric_fixtures import shipped_spec
    from tests.helpers.tuner_composed_fixture import (
        _isolated_registrations,
        make_tuner_composition,
    )
    from tests.helpers.two_family_profile import make_two_family_profile

    pack = tmp_path / "supplied_outcome_task"
    pack.mkdir()
    with _isolated_registrations():
        initial = make_tuner_composition(pack)
        Path(initial.provenance.source_paths["dataset_profile"]).write_text(
            json.dumps(make_two_family_profile(num_files=20).to_wire()), encoding="utf-8"
        )
        manifest = Path(initial.provenance.manifest_path)
        declaration = pack / "supplied_metric.json"
        declaration.write_text(shipped_spec().model_dump_json(), encoding="utf-8")
        payload = yaml.safe_load(manifest.read_text(encoding="utf-8"))
        payload["metric"] = {
            "declaration": "../../supplied_metric.json",
            "implementation": {
                "module": "tests.helpers.metric_fixtures",
                "symbol": "_FixtureMetric",
            },
        }
        manifest.write_text(yaml.safe_dump(payload), encoding="utf-8")
        composition = compose_run_task_bindings(manifest)
        data_root = tmp_path / "supplied_outcome_data"
        data_root.mkdir()
        with bind_run_task_composition(composition, physical_data_root=str(data_root)):
            yield composition
