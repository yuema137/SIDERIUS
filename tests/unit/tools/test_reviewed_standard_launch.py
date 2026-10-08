"""Optional review snapshots and launch refusal through actual existing owners."""

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tests.unit.tools.test_setup_environment import hardware, runtime
from tests.unit.tools.test_setup_environment import setup as setup
from tools.setup_review.environment_settings import inspect_environment
from tools.setup_review.launch import launch_reviewed, prepare_reviewed_launch
from tools.setup_review.launch_models import FindingDisposition, ReviewedLaunchRequest
from tools.setup_review.semantic_models import SemanticReviewRequest, SetupFinding, SetupJudgement
from tools.setup_review.semantic_packet import build_packet
from tools.setup_review.semantic_review import review_snapshot
from workflows.reviewed_launch_binding import (
    InstallationPin,
    ReviewedLaunchRefusal,
    file_pin,
    verify_binding,
)


def install_pin(monkeypatch):
    pin = InstallationPin(
        source_root="/qualified",
        source_head="1" * 40,
        interpreter="/qualified/.venv/bin/python",
        prefix="/qualified/.venv",
        python_version="3.12",
    )
    monkeypatch.setattr("workflows.reviewed_launch_binding.installation_pin", lambda: pin)
    return pin


def reviewed(setup, tmp_path, monkeypatch, *, bind=True):
    prepare, _ = setup
    operation, args = prepare("--no-runtime_watchdog")
    # Supply the finite declaration locator a real composition producer emits.
    config = tmp_path / "task-config.yaml"
    config.write_text("synthetic declaration bytes")
    saved = json.loads(operation.report.read_bytes())
    saved["result"]["task"]["source_paths"]["task_config"] = str(config)
    operation.report.write_text(json.dumps(saved))
    operation = operation.model_copy(
        update={"expected_sha256": hashlib.sha256(operation.report.read_bytes()).hexdigest()}
    )
    install_pin(monkeypatch)
    report = inspect_environment(operation.model_copy(update={"bind_launch": bind}))
    source = operation.output / "report.json"
    semantic = SemanticReviewRequest.model_validate(
        {
            "operation": {
                "kind": "skip",
                "report": str(source),
                "expected_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "output": str(tmp_path / "semantic"),
                "input_max_bytes": 1048576,
                "reason": "I will check the remaining requirements myself.",
            }
        }
    )
    receipt = review_snapshot(semantic)
    path = tmp_path / "semantic/receipt.json"
    request = ReviewedLaunchRequest(
        report=source,
        expected_sha256=semantic.operation.expected_sha256,
        output=tmp_path / "launch-check",
        input_max_bytes=1048576,
        receipt=path,
        receipt_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )
    return report, receipt, request, args


def test_environment_skip_is_inert_and_excludes_open_maps(setup, tmp_path, monkeypatch):
    report, receipt, request, _ = reviewed(setup, tmp_path, monkeypatch)
    assert receipt.prompt_version == "setup-review/v3"
    packet = build_packet(
        report.model_copy(
            update={
                "launch_settings": {
                    **report.launch_settings,
                    "SECRET_EXTRA": "not-for-provider",
                }
            }
        )
    )
    assert "not-for-provider" not in json.dumps(packet)
    assert (
        packet["environment"]["aggregate_gpu_ceiling_gib"]
        != packet["environment"]["per_candidate_usable_cap_bytes"]
    )
    (tmp_path / "task.yaml").unlink()
    monkeypatch.setattr(
        "core.hardware_context.inspect_gpu_runtime", lambda: pytest.fail("hardware")
    )
    monkeypatch.setattr(
        "workflows.reviewed_launch_binding.installation_pin", lambda: pytest.fail("git")
    )
    operation = SemanticReviewRequest.model_validate(
        {
            "operation": {
                "kind": "skip",
                "report": str(request.report),
                "expected_sha256": request.expected_sha256,
                "input_max_bytes": request.input_max_bytes,
                "output": str(tmp_path / "second-skip"),
                "reason": "Explicitly skip this saved observation",
            }
        }
    )
    assert review_snapshot(operation).outcome == "skipped"


def test_advisory_environment_does_not_capture_or_require_clean_sources(
    setup, tmp_path, monkeypatch
):
    prepare, _ = setup
    operation, _ = prepare()
    monkeypatch.setattr(
        "workflows.reviewed_launch_binding.capture_binding", lambda *a: pytest.fail("pin")
    )
    report = inspect_environment(operation)
    assert "launch_binding" not in report.model_dump()
    assert "bind_launch" not in operation.model_dump()


def test_advisory_review_is_not_consuming_launch_authority(setup, tmp_path, monkeypatch):
    _, _, request, _ = reviewed(setup, tmp_path, monkeypatch, bind=False)
    with pytest.raises(ValueError, match="bind-launch"):
        prepare_reviewed_launch(request)


@pytest.mark.parametrize(
    "severity,acknowledge,accepted",
    [
        ("information", False, True),
        ("information", True, True),
        ("warning", False, False),
        ("error", False, False),
        ("warning", True, True),
    ],
)
def test_dispositions_only_require_errors_and_warnings(
    setup, tmp_path, monkeypatch, severity, acknowledge, accepted
):
    _, receipt, request, _ = reviewed(setup, tmp_path, monkeypatch)
    finding = SetupFinding(
        severity=severity,
        field="budget",
        explanation="Check the stated allowance",
        suggested_correction="Confirm it",
        uncertainty="Execution not measured",
    )
    route = dict(
        provider="openai",
        model_id="mock",
        base_url=None,
        reasoning_effort=None,
        max_retries=0,
        request_timeout=1,
        timeout_retries=0,
    )
    payload = {
        **receipt.model_dump(mode="json"),
        "outcome": "reviewed",
        "skip_reason": None,
        "reviewer": route,
        "judgement": SetupJudgement(
            summary="Mock review", findings=[finding], uncovered_checks=[]
        ).model_dump(mode="json"),
    }
    request.receipt.write_text(json.dumps(payload))
    updates = {"receipt_sha256": hashlib.sha256(request.receipt.read_bytes()).hexdigest()}
    if acknowledge:
        updates["dispositions"] = (
            FindingDisposition(
                index=0,
                finding_sha256=hashlib.sha256(finding.model_dump_json().encode()).hexdigest(),
                reason="Reviewed with the operator",
            ),
        )
    request = request.model_copy(update=updates)
    if accepted:
        context, _ = prepare_reviewed_launch(request)
        assert context.receipt_fields["finding_count"] == 1
    else:
        with pytest.raises(ValueError, match="error/warning"):
            prepare_reviewed_launch(request)


def test_changed_task_bytes_refuse_before_runner_import(setup, tmp_path, monkeypatch):
    _, _, request, _ = reviewed(setup, tmp_path, monkeypatch)
    (tmp_path / "task.yaml").write_text("changed task declaration")
    with patch("workflows.run_one_iteration.main", side_effect=AssertionError("must not launch")):
        with pytest.raises(ReviewedLaunchRefusal, match="input_file_changed"):
            launch_reviewed(request)
    assert json.loads((request.output / "launch-check.json").read_text())["outcome"] == "refused"


def test_current_composition_health_and_launch_values_are_checked(setup, tmp_path, monkeypatch):
    report, _, request, args = reviewed(setup, tmp_path, monkeypatch)
    context, _ = prepare_reviewed_launch(request)
    context.check_entry(args)
    with pytest.raises(ReviewedLaunchRefusal, match="task_identity_changed"):
        context.check_composition(SimpleNamespace(semantic_fingerprint="c" * 64))
    context.check_composition(SimpleNamespace(semantic_fingerprint="b" * 64, code_package=None))
    from workflows.launch_identity import resolve_launch_identity
    from workflows.llm_config import resolve_standard_llm_config
    from workflows.runtime_settings import resolve_watchdog_policy
    from workflows.standard_launch import build_standard_launch_config

    identity = resolve_launch_identity(args)
    config = resolve_standard_llm_config(args)
    invariants = SimpleNamespace(
        planner_strategy_identity=SimpleNamespace(model_dump=lambda **kw: {}),
        health_config_sha256="changed",
    )
    with pytest.raises(ReviewedLaunchRefusal, match="health_settings_changed"):
        context.check_invariants(invariants, config, identity)
    invariants.health_config_sha256 = None
    context.check_invariants(invariants, config, identity)
    resolve_watchdog_policy(args, device_name="synthetic device")
    launch = build_standard_launch_config(
        args, identity, resolved_paths=[], fixed_candidate_plan=None
    )
    changed = replace(launch, max_rounds=launch.max_rounds + 1)
    with pytest.raises(ReviewedLaunchRefusal, match="launch_settings_changed"):
        context.check_launch(changed)
    context.check_launch(launch)
    assert json.loads(Path(context.receipt_path).read_text())["outcome"] == "matched"
    assert report.launch_binding is not None


def test_file_pin_refuses_symlink_size_and_changed_bytes(tmp_path):
    target = tmp_path / "config.json"
    target.write_bytes(b"old")
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(OSError):
        file_pin(str(link), 10)
    with pytest.raises(ReviewedLaunchRefusal, match="too_large"):
        file_pin(str(target), 2)
    before = file_pin(str(target), 10)
    target.write_bytes(b"new")
    assert file_pin(str(target), 10) != before


def _exercise_real_standard_main(
    tmp_path, monkeypatch, change_task_config, *, gpu_policy=None, change_policy=False
):
    """Real Quickstart composition/Health/planner; no model, provider or dataset execution."""
    from tools.setup_review.composition_child import compose_in_child
    from tools.setup_review.composition_models import CompositionJob, TaskCheckSettings
    from tools.setup_review.composition_transport import manifest_digest
    from tools.setup_review.environment_models import EnvironmentPreviewRequest
    from tools.setup_review.inspection import inspect_parsed_declaration
    from tools.setup_review.models import SetupReviewRequest
    from tools.setup_review.semantic_models import SavedTaskCheckSnapshot
    from tools.setup_review.task_settings_inputs import project_task_settings
    from workflows import run_one_iteration
    from workflows.llm_config import WorkflowLLMConfig

    monkeypatch.chdir(tmp_path)
    repo = Path(__file__).resolve().parents[3]
    import yaml

    original = repo / "configs/task_composition/quickstart.yaml"
    body = yaml.safe_load(original.read_text())

    def absolute_refs(value):
        if isinstance(value, dict):
            return {
                key: str((original.parent / item).resolve())
                if key in {"config", "file", "dir", "declaration"} and isinstance(item, str)
                else absolute_refs(item)
                for key, item in value.items()
            }
        return value

    body = absolute_refs(body)
    task_config = tmp_path / "task-config.yaml"
    task_config.write_bytes(Path(body["task_config"]["config"]).read_bytes())
    body["task_config"]["config"] = str(task_config)
    manifest = tmp_path / "composed.yaml"
    manifest.write_text(yaml.safe_dump(body))
    routing = tmp_path / "routing.json"
    routing.write_text(json.dumps({"tune": {"planner_strategy": "native-timing-v1"}}))
    (tmp_path / "data").mkdir()
    request = SetupReviewRequest(
        working_directory=str(tmp_path),
        argv=[
            "--workspace",
            str(tmp_path / "run"),
            "--run_name",
            "checked",
            "--start_iteration",
            "1",
            "--task_composition",
            str(manifest),
            "--data_dir",
            str(tmp_path / "data"),
            "--llm_config",
            str(routing),
            "--healthgate_mode",
            "observe_only",
            "--result_authority",
            "diagnostic",
            "--no-runtime_watchdog",
        ],
    )
    policy_path = tmp_path / "gpu-policy.json"
    if gpu_policy is not None:
        policy_path.write_text(json.dumps(gpu_policy))
        request.argv.extend(["--gpu_execution_policy_json", str(policy_path)])
    declaration, args = inspect_parsed_declaration(request, tmp_path / "declaration")
    job = CompositionJob(
        manifest=str(manifest),
        manifest_sha256=manifest_digest(str(manifest)),
        planner_strategy="native-timing-v1",
        scratch=str(tmp_path / "scratch"),
        settings=TaskCheckSettings(timeout_seconds=10),
        task_settings=project_task_settings(
            args, declaration, WorkflowLLMConfig.model_validate(declaration.declared_llm_config)
        ),
    )
    Path(job.scratch).mkdir()
    result = compose_in_child(job)
    assert result.outcome == "passed", result.failure
    saved = SavedTaskCheckSnapshot(
        schema_version="siderius.task-composition-check/v1",
        declaration=declaration,
        result=result,
        limitations=("No task execution",),
    )
    source = tmp_path / "task-check.json"
    source.write_text(saved.model_dump_json())
    install_pin(monkeypatch)
    facts = runtime(hardware("cpu"), backend="none")
    monkeypatch.setattr(
        "tools.setup_review.environment_settings.inspect_gpu_runtime", lambda: facts
    )
    monkeypatch.setattr("core.hardware_context.inspect_gpu_runtime", lambda: facts)
    env = inspect_environment(
        EnvironmentPreviewRequest(
            report=source,
            expected_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
            output=tmp_path / "environment",
            input_max_bytes=1048576,
            bind_launch=True,
        )
    )
    env_path = tmp_path / "environment/report.json"
    if gpu_policy is not None:
        from tools.setup_review.semantic_packet import build_packet

        assert env.launch_settings["gpu_execution_policy"] == gpu_policy
        assert build_packet(env)["declared_gpu_execution_policy"] == gpu_policy
    review_snapshot(
        SemanticReviewRequest.model_validate(
            {
                "operation": {
                    "kind": "skip",
                    "report": str(env_path),
                    "expected_sha256": hashlib.sha256(env_path.read_bytes()).hexdigest(),
                    "output": str(tmp_path / "review"),
                    "input_max_bytes": 1048576,
                    "reason": "Operator inspected inputs",
                }
            }
        )
    )
    semantic_path = tmp_path / "review/receipt.json"
    launch_request = ReviewedLaunchRequest(
        report=env_path,
        expected_sha256=hashlib.sha256(env_path.read_bytes()).hexdigest(),
        output=tmp_path / "launch",
        input_max_bytes=1048576,
        receipt=semantic_path,
        receipt_sha256=hashlib.sha256(semantic_path.read_bytes()).hexdigest(),
    )
    if change_task_config or change_policy:
        if change_task_config:
            config = yaml.safe_load(task_config.read_text())
            config["task_description"] = "A changed scientific declaration after review"
            task_config.write_text(yaml.safe_dump(config))
        else:
            # Same resolved values, different reviewed file: this must exercise
            # the file pin, not merely the later effective-value comparison.
            policy_path.write_text(json.dumps(gpu_policy, indent=2))
        with patch(
            "workflows.model_exploration.run_workflow", side_effect=AssertionError("must not run")
        ) as workflow:
            with pytest.raises(ReviewedLaunchRefusal, match="input_file_changed"):
                launch_reviewed(launch_request)
        workflow.assert_not_called()
        assert (
            json.loads((launch_request.output / "launch-check.json").read_text())["reason"]
            == "input_file_changed"
        )
        return
    projected = []
    owner = run_one_iteration.build_standard_launch_config

    def capture(*args, **kwargs):
        value = owner(*args, **kwargs)
        projected.append(value)
        return value

    monkeypatch.setattr(run_one_iteration, "build_standard_launch_config", capture)
    invariant_calls = []
    invariant_owner = run_one_iteration.build_run_invariants

    def capture_invariants(*args, **kwargs):
        result = invariant_owner(*args, **kwargs)
        invariant_calls.append((kwargs["launch_identity"], result[0]))
        return result

    monkeypatch.setattr(run_one_iteration, "build_run_invariants", capture_invariants)
    with patch("workflows.model_exploration.run_workflow", side_effect=SystemExit(0)) as workflow:
        with pytest.raises(SystemExit) as stopped:
            launch_reviewed(launch_request)
    assert stopped.value.code == 0
    assert len(projected) == 1
    assert workflow.call_args.kwargs["launch"] is projected[0]
    assert projected[0].max_rounds == env.launch_settings["max_rounds"]
    if gpu_policy is not None:
        assert len(invariant_calls) == 1
        lock_identity, invariants = invariant_calls[0]
        selected = projected[0].gpu_execution_policy
        assert selected.model_dump(mode="json") == gpu_policy
        assert lock_identity.gpu_execution_policy is selected
        assert invariants.gpu_execution_policy is selected
    assert (
        json.loads((launch_request.output / "launch-check.json").read_text())["outcome"]
        == "matched"
    )


def test_real_cli_missing_report_has_actionable_safe_error_without_receipt(tmp_path):
    import subprocess
    import sys

    request = tmp_path / "request.json"
    request.write_text(
        json.dumps(
            {
                "report": str(tmp_path / "missing-report.json"),
                "expected_sha256": "0" * 64,
                "receipt": str(tmp_path / "missing-receipt.json"),
                "receipt_sha256": "0" * 64,
                "output": str(tmp_path / "output"),
                "input_max_bytes": 10000,
            }
        )
    )
    result = subprocess.run(
        [sys.executable, "-m", "tools.setup_review.launch", "--request", str(request)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 2
    assert "report/receipt paths" in result.stdout
    assert "Inspect the launch check" not in result.stdout
    assert not (tmp_path / "output").exists()


def test_safe_disposition_refusal_is_actionable_on_cli(setup, tmp_path, monkeypatch, capsys):
    from tools.setup_review.launch import main

    _, _, request, _ = reviewed(setup, tmp_path, monkeypatch)
    request = request.model_copy(
        update={
            "dispositions": (
                FindingDisposition(index=0, finding_sha256="0" * 64, reason="invalid"),
            )
        }
    )
    path = tmp_path / "launch-request.json"
    path.write_text(request.model_dump_json())
    assert main(["--request", str(path)]) == 2
    assert "Finding disposition does not match" in capsys.readouterr().out
    assert not request.output.exists()


def test_cli_preserves_native_failure_after_matched_receipt(setup, tmp_path, monkeypatch, capsys):
    from tools.setup_review.launch import main

    report, _, request, _ = reviewed(setup, tmp_path, monkeypatch)
    path = tmp_path / "launch-request.json"
    path.write_text(request.model_dump_json())
    monkeypatch.chdir(report.current_declaration.request.working_directory)
    failure = RuntimeError("native execution failure")

    def fail_after_authorization(argv, *, reviewed_setup):
        reviewed_setup.publish("matched")
        raise failure

    with patch("workflows.run_one_iteration.main", side_effect=fail_after_authorization):
        with pytest.raises(RuntimeError) as raised:
            main(["--request", str(path)])
    assert raised.value is failure
    assert json.loads((request.output / "launch-check.json").read_text())["outcome"] == "matched"
    assert "No reviewed launch was authorized" not in capsys.readouterr().out


def test_task_cache_evidence_uses_parsed_bytes_and_preserves_cache_identity(tmp_path, monkeypatch):
    from workflows import task_config

    path = tmp_path / "task.yaml"
    before = b"task_description: original\r\nforward_contract: {}\r\n"
    after = b"task_description: changed\nforward_contract: {}\n"
    path.write_bytes(before)
    original_parse = task_config.yaml.safe_load

    def replace_after_parse(stream):
        assert stream.name == str(path)
        parsed = original_parse(stream)
        path.write_bytes(after)
        return parsed

    monkeypatch.setattr(task_config.yaml, "safe_load", replace_after_parse)
    first = task_config.load_task_config(str(path))
    assert first["task_description"] == "original"
    assert task_config.load_task_config(str(path)) is first
    task_config.assert_cached_task_config_source(str(path), hashlib.sha256(before).hexdigest())
    with pytest.raises(ValueError, match="restart the process"):
        task_config.assert_cached_task_config_source(str(path), hashlib.sha256(after).hexdigest())


def test_missing_cache_evidence_never_grants_reviewed_permission(tmp_path, monkeypatch):
    from workflows import task_config

    path = tmp_path / "task.yaml"
    path.write_text("task_description: original\nforward_contract: {}\n")
    first = task_config.load_task_config(str(path))
    monkeypatch.delitem(task_config._CACHE_SOURCE_SHA256, str(path))
    assert task_config.load_task_config(str(path)) is first
    with pytest.raises(ValueError, match="missing source evidence"):
        task_config.assert_cached_task_config_source(str(path), file_pin(str(path), 1000).sha256)


def test_dataclass_projection_handles_nested_typed_policy_and_owned_omission():
    from dataclasses import dataclass, field

    from pydantic import BaseModel

    from workflows.launch_projection import json_launch_values

    class Policy(BaseModel):
        timeout: float

    @dataclass
    class Carrier:
        ordinary_none: str | None = None
        selected_policy: Policy | None = field(default=None, metadata={"omit_if_none": True})
        skip_formal_min_delta: float = float("nan")

    assert json_launch_values(Carrier()) == {"ordinary_none": None, "skip_formal_min_delta": "nan"}
    assert json_launch_values(Carrier(selected_policy=Policy(timeout=7)))["selected_policy"] == {
        "timeout": 7.0
    }


@pytest.mark.parametrize("change_task_config", [False, True])
def test_real_standard_main_consumes_checked_objects_without_running_workflow(
    tmp_path, change_task_config
):
    # A separate process preserves the production package/registration contract;
    # the absolute-reference synthetic manifest must not alter another test's IDs.
    import subprocess
    import sys

    script = """
import sys
from pathlib import Path
import pytest
from tests.unit.tools.test_reviewed_standard_launch import _exercise_real_standard_main
with pytest.MonkeyPatch.context() as patch:
    _exercise_real_standard_main(Path(sys.argv[1]), patch, sys.argv[2] == 'True')
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path), str(change_task_config)],
        cwd=Path(__file__).resolve().parents[3],
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("override", [{}, {"max_retries": None}, {"max_retries": 2}])
def test_reviewed_launch_preserves_retry_intent(setup, tmp_path, monkeypatch, override):
    from tools.setup_review.routes import standard_llm_routes
    from workflows.launch_identity import resolve_launch_identity
    from workflows.llm_config import WorkflowLLMConfig, resolve_standard_llm_config

    llm_file = tmp_path / "llm.json"
    llm_file.write_text(
        json.dumps(
            {
                "tune": {
                    "planner": {"provider": "openai", "max_retries": 1},
                    "reflector": {"provider": "openai", **override},
                }
            }
        )
    )
    prepare, calls = setup

    def configured(*extra):
        return prepare(*extra, "--llm_config", str(llm_file))

    _, _, request, args = reviewed((configured, calls), tmp_path, monkeypatch)
    context, _ = prepare_reviewed_launch(request)
    context.check_entry(args)
    original = resolve_standard_llm_config(args)
    # This is the saved declaration consumed by composition checks and launch.
    restored = WorkflowLLMConfig.model_validate(context.llm_config)
    restored_leaf = context.llm_config["tune"]["reflector"]
    assert ("max_retries" in restored_leaf) == ("max_retries" in override)
    assert "model_id" in restored_leaf and "reasoning_effort" in restored_leaf
    route_options = dict(literature_enabled=True, analysis_enabled=False, pseudo_llm=False)
    expected_routes = standard_llm_routes(original, **route_options)
    assert standard_llm_routes(restored, **route_options) == expected_routes
    reflector = next(route for route in expected_routes if route.name == "tune.reflector")
    assert reflector.transport.max_retries == override.get("max_retries", 1)
    identity = resolve_launch_identity(args)
    invariants = SimpleNamespace(
        planner_strategy_identity=SimpleNamespace(model_dump=lambda **kw: {}),
        health_config_sha256=None,
    )
    context.check_invariants(invariants, restored, identity)
    changed = restored.model_dump(mode="json", by_alias=True)
    leaf = changed["tune"]["reflector"]
    if "max_retries" in leaf:
        leaf.pop("max_retries")
    else:
        leaf["max_retries"] = None
    with pytest.raises(ReviewedLaunchRefusal, match="llm_settings_changed"):
        context.check_invariants(invariants, WorkflowLLMConfig.model_validate(changed), identity)
