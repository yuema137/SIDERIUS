"""Owner-backed task settings and lossless standard-argument transport."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.layout import package_root
from execute_tools.dataset_config import DataScope, DatasetProfile
from execute_tools.health_checks._composition import HealthBindingState
from execute_tools.health_checks.config import (
    load_health_gates_config,
    materialize_effective_config,
)
from execute_tools.health_checks.launch_policy import FormalLaunchPolicyError
from tests.helpers.two_family_profile import make_two_family_profile
from tools.setup_review.composition_models import CompositionJob, TaskCheckSettings
from tools.setup_review.inspection import inspect_parsed_declaration
from tools.setup_review.models import SetupReviewRequest
from tools.setup_review.render import render_html
from tools.setup_review.task_settings_child import resolve_task_settings
from tools.setup_review.task_settings_inputs import project_task_settings
from workflows.llm_config import WorkflowLLMConfig


def _inputs(tmp_path, monkeypatch, *extra):
    monkeypatch.chdir(tmp_path)
    manifest = tmp_path / "task.yaml"
    manifest.write_text("unexecuted: task declaration\n")
    request = SetupReviewRequest(
        working_directory=str(tmp_path),
        argv=[
            "--workspace",
            "future-run",
            "--run_name",
            "synthetic",
            "--start_iteration",
            "1",
            "--task_composition",
            str(manifest),
            "--data_dir",
            "unread-data",
            "--healthgate_mode",
            "observe_only",
            "--result_authority",
            "diagnostic",
            *extra,
        ],
    )
    report, args = inspect_parsed_declaration(request, tmp_path / "report")
    inputs = project_task_settings(
        args, report, WorkflowLLMConfig.model_validate(report.declared_llm_config)
    )
    job = CompositionJob(
        manifest=str(manifest),
        manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
        planner_strategy="native-timing-v1",
        scratch=str(tmp_path),
        settings=TaskCheckSettings(timeout_seconds=5),
        task_settings=inputs,
    )
    return report, CompositionJob.model_validate_json(job.model_dump_json())


def _composition(count=4, *, analysis=None, legacy=False, health=HealthBindingState.EXPLICIT_NONE):
    profile = (
        make_two_family_profile(num_files=count)
        if legacy
        else DatasetProfile(
            partition_count=count,
            topology={"kind": "synthetic"},
            anchor_selection_files=[0],
            health_peek_files=[0],
        )
    )
    return SimpleNamespace(
        dataset_profile=profile, data_analysis=analysis, task_health_binding=health
    )


@pytest.mark.parametrize("field", ["skip_formal_min_delta", "bypass_formal_time_budget_min_delta"])
def test_unused_nonfinite_delta_survives_real_parse_report_job_and_policy(
    tmp_path, monkeypatch, field
):
    digests = set()
    for value in ("nan", "+inf", "-inf"):
        report, job = _inputs(
            tmp_path, monkeypatch, f"--{field}={value}", "--no-health_gate_enabled"
        )
        payload = json.loads(report.model_dump_json())
        row = next(row for row in payload["parameters"] if row["name"] == field)
        assert row["declared_value"] == value
        assert "nonfinite numeric declaration" in render_html(report)
        assert getattr(job.task_settings, field) == value
        digests.add(job.digest)
        assert (
            resolve_task_settings(job.task_settings, _composition(), str(tmp_path)).formal_policy
            == "passed"
        )
        enabled = job.task_settings.model_copy(update={"enable_chain_incumbent_formal_gates": True})
        with pytest.raises(FormalLaunchPolicyError, match="not finite"):
            resolve_task_settings(enabled, _composition(), str(tmp_path))
    assert len(digests) == 3
    assert not (tmp_path / "future-run").exists()


@pytest.mark.parametrize("count", [1, 4, 11])
def test_actual_partition_count_and_disabled_health_do_not_materialize(
    tmp_path, monkeypatch, count
):
    _, job = _inputs(tmp_path, monkeypatch, "--no-health_gate_enabled")
    result = resolve_task_settings(job.task_settings, _composition(count), str(tmp_path))
    assert result.resolved_data_scope == list(range(count))
    assert result.health_config is result.health_config_sha256 is None
    assert result.scope_is_partial is False
    assert not (tmp_path / "task-settings").exists()


@pytest.mark.parametrize("binding", [False, True])
@pytest.mark.parametrize("treatment", [None, False, True])
def test_analysis_treatment_uses_task_binding(tmp_path, monkeypatch, binding, treatment):
    extra = (
        []
        if treatment is None
        else ["--data_analysis_enabled" if treatment else "--no-data_analysis_enabled"]
    )
    _, job = _inputs(tmp_path, monkeypatch, "--no-health_gate_enabled", *extra)
    composition = _composition(analysis=object() if binding else None)
    if treatment is True and not binding:
        with pytest.raises(ValueError, match="requires a task-composed"):
            resolve_task_settings(job.task_settings, composition, str(tmp_path))
    else:
        result = resolve_task_settings(job.task_settings, composition, str(tmp_path))
        assert result.analysis_enabled is (binding and treatment is not False)
        route = next(route for route in result.llm_routes if route.name == "data_analysis")
        assert route.applicability == ("conditional" if result.analysis_enabled else "disabled")


@pytest.mark.parametrize(
    "extra,legacy,match",
    [
        (["--data_scope", "4"], True, "out of range"),
        (["--data_scope", "0", "--formal_strategy", "anchors"], True, "formal_strategy"),
        (["--data_scope", "0"], False, "FILE INDICES"),
        (["--data_scope", "0"], True, "health_gate_files"),
    ],
)
def test_scope_checks_refuse_before_materializing(tmp_path, monkeypatch, extra, legacy, match):
    _, job = _inputs(tmp_path, monkeypatch, *extra)
    with pytest.raises(ValueError, match=match):
        resolve_task_settings(job.task_settings, _composition(legacy=legacy), str(tmp_path))
    assert not (tmp_path / "task-settings").exists()


def test_legal_partial_scope_and_monitored_override_use_actual_health_owner(tmp_path, monkeypatch):
    _, job = _inputs(tmp_path, monkeypatch, "--data_scope", "0-1", "--health_gate_files", "0")
    composition = _composition(legacy=True)
    result = resolve_task_settings(job.task_settings, composition, str(tmp_path))
    expected = tmp_path / "expected"
    expected.mkdir()
    path, digest = materialize_effective_config(
        None,
        [0],
        str(expected),
        resolved_scope=[0, 1],
        task_health_binding=HealthBindingState.EXPLICIT_NONE,
        dataset_partition_count=4,
    )
    assert result.resolved_data_scope == [0, 1] and result.scope_is_partial
    assert result.health_config_sha256 == digest
    assert (
        result.health_config["health_gates"]
        == load_health_gates_config(path).model_dump(mode="json")["health_gates"]
    )
    assert result.health_config["task_health_binding"] == "explicit_none"
    assert result.health_config["resolved_plugins"] == []


def test_current_startup_forwards_scope_to_shared_owner(tmp_path, monkeypatch):
    """The workflow's extracted startup path reaches the shared scope owner."""
    from workflows import task_settings, training_startup
    from workflows.run_config import WorkflowLaunchConfig

    profile = DatasetProfile(
        partition_count=4,
        topology={"kind": "synthetic"},
        anchor_selection_files=[0],
        health_peek_files=[0],
    )
    monkeypatch.setattr(training_startup, "resolve_dataset_profile", lambda: profile)
    monkeypatch.setattr(training_startup, "workflow_lock_identity", lambda *_args: object())
    monkeypatch.setattr(
        training_startup, "build_run_invariants", lambda **_kwargs: (object(), None)
    )

    observed = []
    validate_scope_settings = task_settings.validate_scope_settings

    def inspect_owner_call(**kwargs):
        observed.append(kwargs)
        return validate_scope_settings(**kwargs)

    monkeypatch.setattr(training_startup, "validate_scope_settings", inspect_owner_call)
    with pytest.raises(ValueError, match="partial data_scope requires formal_strategy='snapshot'"):
        training_startup.prepare_training_run(
            launch=WorkflowLaunchConfig(formal_strategy="anchors"),
            workspace=str(tmp_path),
            llm_config=None,
            task_composition=None,
            data_scope=DataScope.from_cli("0-1"),
            health_gate_enabled=False,
            health_gate_files=[1],
            health_checks_config=None,
            order_strategy_override=None,
            file_order_override=None,
            enable_structured_health_feedback=False,
        )

    assert observed == [
        {
            "scope_is_partial": True,
            "formal_strategy": "anchors",
            "task_composition": None,
            "health_gate_enabled": False,
            "health_gate_files": [1],
        }
    ]


def test_extracted_decisions_remain_inside_estimator_source_identity(monkeypatch):
    from core.preflight_estimation import estimation_assembly_digest

    original = Path.read_bytes
    target = package_root() / "workflows/task_settings.py"
    before = estimation_assembly_digest()

    def changed(path):
        data = original(path)
        return data + b"\n# synthetic owner change\n" if path == target else data

    monkeypatch.setattr(Path, "read_bytes", changed)
    assert estimation_assembly_digest() != before
