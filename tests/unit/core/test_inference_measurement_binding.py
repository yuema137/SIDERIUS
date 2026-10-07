"""A measurement must identify the candidate actually inspected and dispatched."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.runtime_control.inference_measurement_binding import (
    inference_measurement_binding,
    measurement_sources,
    verify_measurement_sources,
)
from tests.unit.core.test_gpu_measurement_runner import DEVICE, _run, _spec


@pytest.fixture
def source_environment(tmp_path, monkeypatch):
    """Keep discovery inside this test's workspace, including loss fallbacks."""
    model_dir = tmp_path / "models"
    loss_dir = tmp_path / "losses"
    model_dir.mkdir()
    loss_dir.mkdir()
    environment = {
        "SIDERIUS_PLUGIN_DIRS": str(model_dir),
        "SIDERIUS_LOSS_DIRS": str(loss_dir),
        "SIDERIUS_GENERATED_LIBRARY_DIR": str(tmp_path / "library"),
        "SIDERIUS_CHAIN_WORKSPACE": str(tmp_path),
    }
    if "CUDA_VISIBLE_DEVICES" in os.environ:
        environment["CUDA_VISIBLE_DEVICES"] = os.environ["CUDA_VISIBLE_DEVICES"]
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    return environment


@pytest.mark.parametrize("family", ["PLUGIN", "LOSS"])
def test_editing_a_discovered_plugin_invalidates_the_pinned_sources(source_environment, family):
    """Fails if discovery hashes paths alone or drops either plugin family."""
    root = Path(source_environment[f"SIDERIUS_{family}_DIRS"])
    plugin = root / "candidate.py"
    plugin.write_text("raise AssertionError('source inspection must not import plugins')\n")
    pinned = measurement_sources(environ=source_environment)
    plugin.write_text(plugin.read_text() + "# changed implementation\n")

    changed = measurement_sources(environ=source_environment)
    assert changed.plugin_sources_sha256 != pinned.plugin_sources_sha256
    assert changed.assembly_sha256 == pinned.assembly_sha256
    with pytest.raises(ValueError, match="sources changed"):
        verify_measurement_sources(pinned)


def test_builtin_model_bytes_participate_in_the_source_closure(source_environment, monkeypatch):
    """A built-in edit must invalidate the pin even with unchanged plugin roots."""
    import core.preflight_estimation as estimation

    builtin = Path(estimation.__file__).resolve().parents[1] / "ml_models/models_sandbox.py"
    pinned = measurement_sources(environ=source_environment)
    read_bytes = Path.read_bytes

    def edited_bytes(path):
        original = read_bytes(path)
        return original + b"\n# changed built-in implementation\n" if path == builtin else original

    monkeypatch.setattr(Path, "read_bytes", edited_bytes)
    changed = measurement_sources(environ=source_environment)
    assert changed.assembly_sha256 != pinned.assembly_sha256
    assert changed.plugin_sources_sha256 == pinned.plugin_sources_sha256


@pytest.mark.parametrize(
    "changes",
    [
        {"model_config_payload": {"width": 17}},
        {"train_config": {"batch_size": 7}},
        {"loss_config": {"loss_type": "mse"}},
        {"inference_batch_size": 13},
        {"inference_batches": 2},
        {"data_dir": "/different-explicit-data-root"},
    ],
)
def test_request_binding_changes_with_execution_inputs(tmp_path, source_environment, changes):
    """A source-only or planned-identity-only pin misses these execution inputs."""
    spec = _spec(tmp_path)
    original = inference_measurement_binding(spec, environ=source_environment)
    changed = inference_measurement_binding(
        spec.model_copy(update=changes), environ=source_environment
    )
    assert changed.request_sha256 != original.request_sha256
    assert changed.assembly_sha256 == original.assembly_sha256
    # Attaching the proof must not change the request that proof identifies.
    assert (
        inference_measurement_binding(
            spec.model_copy(update={"inference_binding": original}), environ=source_environment
        )
        == original
    )


def test_source_inspection_remains_torch_free_in_a_clean_parent(tmp_path, source_environment):
    """A transitive torch import would recreate the long-lived parent CUDA risk."""
    script = """
import importlib.abc
import sys
class RefuseTorch(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'torch' or fullname.startswith('torch.'):
            raise AssertionError('parent attempted to import torch')
sys.meta_path.insert(0, RefuseTorch())
from core.runtime_control.inference_measurement_binding import measurement_sources
from core.runtime_control.inference_refusal_verification import eligible_inference_refusal
from agent.skills.evaluate_vram_skill.preflight_adapter import run_production_preflight
measurement_sources()
assert 'torch' not in sys.modules
"""
    environment = dict(os.environ, **source_environment)
    environment.pop("PYTHONPATH", None)
    subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )


@pytest.mark.parametrize("mutation", ["unchanged", "before_inspection", "during_inspection"])
def test_static_worker_checks_sources_on_both_sides_of_inspection(
    tmp_path, source_environment, monkeypatch, mutation
):
    """Removing either worker check must let its corresponding mutation escape."""
    from agent.skills.evaluate_vram_skill.isolated_probe import IsolatedProbeSpec
    from agent.skills.evaluate_vram_skill.preflight_worker_main import main
    from tests.unit.agent.evaluate_vram_skill.test_static_preflight_evidence_transport import (
        structural_result,
    )

    plugin = Path(source_environment["SIDERIUS_PLUGIN_DIRS"]) / "candidate.py"
    plugin.write_text("# original candidate\n")
    pinned = measurement_sources(environ=source_environment)
    spec = IsolatedProbeSpec(
        label="source-continuity",
        model_type="synthetic_candidate",
        candidate_sources=pinned,
        result_path=str(tmp_path / "result.json"),
        worker_memory_limit_bytes=1024**3,
    )
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(spec.model_dump_json())
    inspected = []

    def run_skill(*args, **kwargs):
        inspected.append(True)
        if mutation == "during_inspection":
            plugin.write_text("# candidate changed during inspection\n")
        return structural_result("vram")

    monkeypatch.setitem(
        sys.modules,
        "agent.skills.evaluate_vram_skill.wrapper",
        SimpleNamespace(run_skill=run_skill),
    )
    if mutation == "before_inspection":
        plugin.write_text("# candidate changed before inspection\n")
    returncode = main([str(spec_path)])
    report = json.loads(Path(spec.result_path).read_text())
    assert bool(inspected) is (mutation != "before_inspection")
    if mutation == "unchanged":
        assert returncode == 0
        assert report["outcome"] == "STATIC_PREFLIGHT_REFUSAL"
        assert report["candidate_sources"] == pinned.model_dump(mode="json")
    else:
        assert returncode == 1
        assert report["outcome"] == "PROBE_INFRASTRUCTURE_FAILURE"
        assert "sources changed" in report["detail"]
        assert "candidate_sources" not in report


@pytest.mark.parametrize("reply", ["matched", "missing", "changed_request", "changed_sources"])
def test_worker_reply_must_carry_the_dispatched_binding(tmp_path, source_environment, reply):
    """Real JSON/process transport must reject a missing, stale, or foreign proof."""
    request = _spec(tmp_path).request.model_copy(update={"phase": "inference"})
    spec = _spec(tmp_path, request=request, inference_batch_size=4)
    binding = inference_measurement_binding(spec, environ=source_environment)
    body = f"""
binding = spec['inference_binding']
request = spec['request']
if {reply!r} == 'missing':
    binding = None
elif {reply!r} == 'changed_request':
    request['request_id'] = 'foreign-request'
elif {reply!r} == 'changed_sources':
    binding['plugin_sources_sha256'] = '0' * 64
report({{
    'label': spec['label'], 'request': request,
    'status': 'COMPLETED', 'device': spec['device'],
    'observed_device_uuid': {DEVICE.uuid!r}, 'worker_pid': os.getpid(),
    'inference_binding': binding,
    'phases': [{{
        'phase': 'inference', 'status': 'COMPLETED',
        'started_at': time.time(), 'ended_at': time.time(), 'elapsed_seconds': 0.0,
        'units_executed': 1, 'units_requested': 1,
    }}],
}})
"""
    run = _run(
        tmp_path,
        body,
        [100],
        spec={"request": request, "inference_binding": binding, "inference_batch_size": 4},
    )
    assert run.process.exit_code == 0
    assert run.process.orphans_remaining is False
    if reply == "matched":
        assert run.worker_status == "COMPLETED"
        assert run.inference_binding == binding
    else:
        assert run.worker_status == "WORKER_FAILURE"
        assert run.inference_binding is None
        assert "does not match" in run.detail
