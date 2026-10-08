"""Explicit observations reuse launch owners without executing a scientific task."""

import hashlib
import json
import subprocess
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent.llm_settings import KNOWN_PROVIDERS
from core.hardware_context import GpuRuntimeFacts, HardwareContext
from execute_tools.data_paths import DatasetDirectoryUnavailable
from tools.setup_review.composition_models import CompositionResult, TaskCompositionSummary
from tools.setup_review.environment_models import EnvironmentPreviewRequest
from tools.setup_review.environment_settings import inspect_environment
from tools.setup_review.inspection import inspect_parsed_declaration
from tools.setup_review.models import SetupReviewRequest
from tools.setup_review.semantic_models import SavedTaskCheckSnapshot, SnapshotInputError
from tools.setup_review.task_settings_models import TaskSettingsSummary
from workflows.launch_identity import resolve_launch_identity
from workflows.run_config import validate_launch_trial_overrides
from workflows.runtime_settings import resolve_watchdog_policy
from workflows.standard_launch import build_standard_launch_config


def hardware(name="synthetic device", **changes):
    return HardwareContext(
        **dict(
            device_name=name,
            total_memory_bytes=123456789,
            compute_capability=(0, 0),
            multiprocessor_count=1,
            torch_version="fixture",
            hostname="fixture-host",
            device_available=name != "cpu",
            discovered_at=datetime(2026, 1, 1, tzinfo=UTC),
            **changes,
        )
    )


def runtime(observed=None, backend="cuda"):
    return GpuRuntimeFacts(
        installed_backend=backend,
        runtime_version="synthetic-version",
        hardware=observed or hardware(),
        implemented_accounting_adapter="nvidia-smi" if backend == "cuda" else None,
        limitations=("Synthetic observation; hardware execution was not qualified",),
    )


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SIDERIUS_CALIBRATION_DIR", str(tmp_path / "no-profiles"))
    manifest = tmp_path / "task.yaml"
    manifest.write_text("unexecuted synthetic declaration")
    (tmp_path / "data").mkdir()
    calls = []

    def discover():
        calls.append("discover")
        return runtime()

    monkeypatch.setattr("tools.setup_review.environment_settings.inspect_gpu_runtime", discover)
    # A second observation hidden in watchdog resolution would break the one-view contract.
    monkeypatch.setattr("core.hardware_context.discover", lambda: pytest.fail("second discovery"))

    def prepare(*extra):
        request = SetupReviewRequest(
            working_directory=str(tmp_path),
            argv=[
                "--workspace",
                "run",
                "--run_name",
                "fixture",
                "--start_iteration",
                "1",
                "--task_composition",
                str(manifest),
                "--data_dir",
                "data",
                *extra,
            ],
        )
        declaration, args = inspect_parsed_declaration(request, tmp_path / "old-preview")
        snapshot = SavedTaskCheckSnapshot(
            schema_version="siderius.task-composition-check/v1",
            declaration=declaration,
            result=CompositionResult(
                request_sha256="a" * 64,
                manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
                outcome="passed",
                planner_strategy_identity={},
                task=TaskCompositionSummary(
                    semantic_fingerprint="b" * 64,
                    task_data_path_id="fixture",
                    task_config={"description": "<script>task</script>"},
                    dataset_profile={"partition_count": 5},
                    primary_metric={"id": "score", "direction": "maximize"},
                    secondary_metrics=[],
                    parameter_rules={},
                    inference_preflight={},
                    source_paths={"unvisited": "/deleted/old/source"},
                    plugins=[],
                    code_package_identity=None,
                    prompt_renderer_identity=None,
                    preflight_estimator_identity={},
                    data_analysis_identity=None,
                    task_health_declaration="disabled",
                ),
                task_settings=TaskSettingsSummary(
                    resolved_data_scope=[0, 1],
                    scope_is_partial=True,
                    analysis_enabled=False,
                    llm_routes=declaration.llm_routes,
                    formal_policy="passed",
                    health_gate_enabled=False,
                    health_config=None,
                    health_config_sha256=None,
                    unresolved=("Old hardware observation absent",),
                ),
            ),
            limitations=("Historical check only",),
        )
        payload = snapshot.model_dump_json().encode()
        source = tmp_path / "task-check.json"
        source.write_bytes(payload)
        operation = EnvironmentPreviewRequest(
            report=source,
            expected_sha256=hashlib.sha256(payload).hexdigest(),
            output=tmp_path / "environment-preview",
            input_max_bytes=1024 * 1024,
        )
        return operation, args

    return prepare, calls


def test_owner_projection_defaults_and_saved_task_current_environment_are_separate(setup, tmp_path):
    prepare, calls = setup
    operation, args = prepare("--max_rounds", "4", "--trial_portion", "0.03")
    expected_watchdog = resolve_watchdog_policy(args, device_name="synthetic device")
    expected = build_standard_launch_config(
        args, resolve_launch_identity(args), resolved_paths=[], fixed_candidate_plan=None
    )
    validate_launch_trial_overrides(expected)
    report = inspect_environment(operation)
    assert report.watchdog == expected_watchdog
    assert report.launch_settings == json.loads(json.dumps(asdict(expected)))
    assert calls == ["discover"]
    assert report.dataset_directory == str(tmp_path / "data")
    assert report.launch_settings["data_dir"] == "data"  # Preserve the actual owner's spelling.
    assert report.saved_task_check.result.task_settings.resolved_data_scope == [0, 1]
    assert not (tmp_path / "run").exists()
    page = (operation.output / "index.html").read_text()
    assert "Saved task settings" in page and "Hardware observed now" in page
    assert "launch readiness is not verified" in page
    assert "<script>task</script>" not in page and "&lt;script&gt;task&lt;/script&gt;" in page
    assert " &amp;&amp;\n" in page
    for name in report.launch_settings:
        assert name in page
    assert (
        json.loads((operation.output / "report.json").read_text())["gpu_runtime"]["hardware"][
            "device_name"
        ]
        == "synthetic device"
    )


@pytest.mark.parametrize("name", ["cpu", "unqualified alternate accelerator"])
def test_unknown_or_cpu_facts_never_borrow_profile_or_invent_identity(setup, monkeypatch, name):
    operation, _ = setup[0]()
    observed = hardware(name, collection_errors=["identity unavailable"])
    monkeypatch.setattr(
        "tools.setup_review.environment_settings.inspect_gpu_runtime", lambda: runtime(observed)
    )
    report = inspect_environment(operation)
    assert report.gpu_runtime.hardware == observed
    assert report.gpu_runtime.hardware.active_device_uuid is None
    assert report.watchdog.profile_calibrated is False
    assert report.watchdog.enabled is False
    assert "uncalibrated" in report.watchdog.provenance
    assert "missing accounting adapters" in " ".join(report.limitations)


@pytest.mark.parametrize("mutation", ["manifest", "advice", "missing_data", "collision", "digest"])
def test_changed_input_refused_before_hardware_or_output(setup, tmp_path, mutation):
    advice = tmp_path / "advice.json"
    advice.write_text('{"mindset": "first"}\n')
    extra = ["--human_advice_file", str(advice)] if mutation == "advice" else []
    operation, _ = setup[0](*extra)
    if mutation == "manifest":
        (tmp_path / "task.yaml").write_text("changed")
    elif mutation == "advice":
        advice.write_text('{"mindset": "second"}\n')
    elif mutation == "missing_data":
        (tmp_path / "data").rmdir()
    elif mutation == "collision":
        operation.output.mkdir()
        (operation.output / "keep").write_text("user file")
    else:
        operation = operation.model_copy(update={"expected_sha256": "0" * 64})
    with pytest.raises((ValueError, FileNotFoundError, DatasetDirectoryUnavailable)):
        inspect_environment(operation)
    assert setup[1] == []
    if mutation == "collision":
        assert (operation.output / "keep").read_text() == "user file"
    else:
        assert not operation.output.exists()


@pytest.mark.parametrize("value", ["nan", "+inf", "-inf"])
def test_unused_formal_delta_is_lossless_through_actual_projection(setup, value):
    operation, _ = setup[0](f"--skip_formal_min_delta={value}")
    report = inspect_environment(operation)
    assert report.launch_settings["skip_formal_min_delta"] == value
    raw = json.loads((operation.output / "report.json").read_text())
    assert raw["launch_settings"]["skip_formal_min_delta"] == value


def test_cli_watchdog_and_name_presence_no_credential_values(setup, monkeypatch):
    operation, _ = setup[0]("--runtime_watchdog", "--runtime_watchdog_safety_factor", "2.75")
    operation = operation.model_copy(update={"check_environment": True})
    for provider in KNOWN_PROVIDERS.values():
        monkeypatch.setenv(provider["api_key_env"], "PRIVATE_VALUE_123")
    report = inspect_environment(operation)
    assert report.watchdog.enabled is True
    assert report.watchdog.safety_factor == 2.75
    assert report.watchdog.provenance == "cli"
    assert setup[1] == ["discover"]
    for path in operation.output.iterdir():
        assert "PRIVATE_VALUE_123" not in path.read_text()
    assert any(item.status == "present_nonempty" for item in report.credentials)


def test_cold_operation_preserves_inert_preview_and_has_no_runner_provider(setup, tmp_path):
    operation, _ = setup[0]()
    code = """
import importlib.abc
import sys
class Reject(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        forbidden = ('agent.llm_bridge', 'dotenv', 'openai', 'workflows.task_composition',
                     'workflows.run_one_iteration', 'workflows.model_exploration')
        if any(fullname == name or fullname.startswith(name + '.') for name in forbidden):
            raise AssertionError('Unexpected effectful import: ' + fullname)
sys.meta_path.insert(0, Reject())
from tools.setup_review.inspection import inspect_declaration
assert 'core.hardware_context' not in sys.modules
import tools.setup_review.environment_settings as observer
from core.hardware_context import GpuRuntimeFacts
observer.inspect_gpu_runtime = lambda: GpuRuntimeFacts.model_validate_json(sys.argv[1])
from tools.setup_review.inspect_environment import main
raise SystemExit(main(sys.argv[2:]))
"""
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            code,
            runtime().model_dump_json(),
            "--report",
            str(operation.report),
            "--expected-sha256",
            operation.expected_sha256,
            "--output",
            str(operation.output),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert (operation.output / "index.html").is_file()
    assert not (tmp_path / "run").exists()


def test_profile_binding_uses_observed_device_and_refuses_changed_bytes(setup, tmp_path):
    from agent.skills.evaluate_time_skill.calibration import gpu_slug

    key = f"{gpu_slug('synthetic device')}/single"
    profile = tmp_path / "profile.json"
    profile.write_text(
        json.dumps(
            {
                "profiles": {
                    key: {
                        "watchdog_enabled": True,
                        "watchdog_safety_factor": 4.25,
                        "watchdog_floor_seconds": 12.5,
                    }
                }
            }
        )
    )
    operation, _ = setup[0](
        "--required_runtime_profile_path",
        str(profile),
        "--required_runtime_profile",
        key,
        "--required_runtime_profile_sha256",
        hashlib.sha256(profile.read_bytes()).hexdigest(),
    )
    first = inspect_environment(operation)
    assert first.watchdog.enabled and first.watchdog.safety_factor == 4.25
    assert first.watchdog.floor_seconds == 12.5
    profile.write_text(profile.read_text() + "\n")
    second = operation.model_copy(update={"output": tmp_path / "second-observation"})
    with pytest.raises(SystemExit, match="required_runtime_profile"):
        inspect_environment(second)
    assert not second.output.exists()


def test_watchdog_wrapper_omission_keeps_real_owner_call_shape(setup, monkeypatch):
    from core.runtime_control.watchdog_profile import ResolvedWatchdogSettings

    _, args = setup[0]()
    captured = []
    expected = ResolvedWatchdogSettings(
        enabled=False, safety_factor=None, floor_seconds=123.0, provenance="fixture"
    )

    def resolve(**kwargs):
        captured.append(kwargs)
        return expected

    monkeypatch.setattr("workflows.runtime_settings.resolve_watchdog_launch_settings", resolve)
    assert resolve_watchdog_policy(args) is expected
    assert "device_name" not in captured[0]
    assert resolve_watchdog_policy(args, device_name="different observation") is expected
    assert len(captured) == 1  # The actual owner's original cache behavior is preserved.


def test_failed_discovery_is_not_converted_to_a_cpu_success(setup, monkeypatch):
    operation, _ = setup[0]()

    def failed():
        raise RuntimeError("synthetic property discovery failure")

    monkeypatch.setattr("tools.setup_review.environment_settings.inspect_gpu_runtime", failed)
    with pytest.raises(RuntimeError, match="property discovery failure"):
        inspect_environment(operation)
    assert not operation.output.exists()


def test_without_task_settings_refuses_before_discovery(setup):
    operation, _ = setup[0]()
    payload = json.loads(operation.report.read_bytes())
    del payload["result"]["task_settings"]
    raw = json.dumps(payload).encode()
    operation.report.write_bytes(raw)
    operation = operation.model_copy(update={"expected_sha256": hashlib.sha256(raw).hexdigest()})
    with pytest.raises(SnapshotInputError, match="resolve-task-settings"):
        inspect_environment(operation)
    assert setup[1] == [] and not operation.output.exists()


def test_cli_outputs_exact_paths_and_actionable_directory_failure(setup, tmp_path, capsys):
    from tools.setup_review.inspect_environment import main

    operation, _ = setup[0]()
    argv = [
        "--report",
        str(operation.report),
        "--expected-sha256",
        operation.expected_sha256,
        "--output",
        str(operation.output),
    ]
    assert main(argv) == 0
    assert str(operation.output / "index.html") in capsys.readouterr().out
    (tmp_path / "data").rmdir()
    argv[-1] = str(tmp_path / "second-preview")
    assert main(argv) == 2
    assert "data directory" in capsys.readouterr().err


def test_default_operation_does_not_read_credentials(setup, monkeypatch):
    import os

    operation, _ = setup[0]()
    original = type(os.environ).__getitem__
    credential_names = {item["api_key_env"] for item in KNOWN_PROVIDERS.values()}

    def guarded(self, key):
        assert key not in credential_names, "Implicit credential access"
        return original(self, key)

    monkeypatch.setattr(type(os.environ), "__getitem__", guarded)
    report = inspect_environment(operation)
    assert not report.environment_check_requested
    assert all(item.status in {"not_checked", "not_required"} for item in report.credentials)


def test_real_trial_schedule_validator_refuses_discarded_overrides(setup):
    operation, _ = setup[0](
        "--is_trial", "--max_rounds", "1", "--plan_overrides", '{"trial_portion": 0.2}'
    )
    with pytest.raises(ValueError, match="apply to zero"):
        inspect_environment(operation)
    assert not operation.output.exists()


def test_aggregate_ceiling_uses_full_capacity_and_independent_quota(setup, monkeypatch):
    from core.runtime_control.pair_admission import (
        HOST_VRAM_QUOTA_MIB_ENV,
        PAIR_CEILING_GIB_ENV,
    )

    operation, _ = setup[0]("--gpu_pair_ceiling_gib", "1.5")
    observed = hardware().model_copy(update={"total_memory_bytes": 2 * 1024**3})
    monkeypatch.setattr(
        "tools.setup_review.environment_settings.inspect_gpu_runtime", lambda: runtime(observed)
    )
    monkeypatch.setenv(PAIR_CEILING_GIB_ENV, "0.25")  # Explicit caller overrides this one.
    monkeypatch.setenv(HOST_VRAM_QUOTA_MIB_ENV, "1024")  # Independent quota still applies.
    report = inspect_environment(operation)
    assert report.aggregate_gpu_ceiling.operator_source == "caller"
    assert report.aggregate_gpu_ceiling.operator_ceiling_gib == 1.5
    assert report.aggregate_gpu_ceiling.measured_capacity_gib == 2.0
    assert report.aggregate_gpu_ceiling.host_quota_gib == 1.0
    assert report.aggregate_gpu_ceiling_gib == 1.0
    assert report.per_candidate_usable_cap_bytes == observed.usable_cap_bytes
    assert report.per_candidate_usable_cap_bytes != 1024**3


def test_rocm_missing_adapter_is_separate_from_available_untested_hardware(setup, monkeypatch):
    operation, _ = setup[0]()
    facts = runtime(hardware("alternate accelerator"), backend="rocm").model_copy(
        update={
            "limitations": ("ROCm runtime untested", "Required accounting adapter unavailable"),
        }
    )
    monkeypatch.setattr(
        "tools.setup_review.environment_settings.inspect_gpu_runtime", lambda: facts
    )
    report = inspect_environment(operation)
    assert report.gpu_runtime.hardware.device_available
    assert report.gpu_runtime.implemented_accounting_adapter is None
    page = (operation.output / "index.html").read_text()
    assert "ROCm runtime untested" in page
    assert "Required accounting adapter unavailable" in page
    assert (
        report.aggregate_gpu_ceiling is not None
    )  # Arithmetic is vendor independent, not permission.


def test_cpu_has_no_invented_gpu_ceiling(setup, monkeypatch):
    operation, _ = setup[0]()
    monkeypatch.setattr(
        "tools.setup_review.environment_settings.inspect_gpu_runtime",
        lambda: runtime(hardware("cpu"), backend="none"),
    )
    report = inspect_environment(operation)
    assert report.aggregate_gpu_ceiling is None
    assert report.aggregate_gpu_ceiling_gib is None
    assert report.per_candidate_usable_cap_bytes is None
