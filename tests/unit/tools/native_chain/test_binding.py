"""Exact native substitutions and refusal type/lifecycle witnesses."""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.resume import RestoredState
from workflows.launch_projection import json_launch_values
from workflows.native_chain_binding import NativeChainCaptureRefusal, NativeChainLaunchContext
from workflows.reviewed_launch import ReviewedLaunchContext
from workflows.reviewed_launch_binding import InstallationPin, LaunchInputBinding, file_pin
from workflows.run_config import WorkflowLaunchConfig


@pytest.fixture
def context(tmp_path, monkeypatch):
    pin = InstallationPin(
        source_root=str(tmp_path),
        source_head="a" * 40,
        interpreter="/python",
        prefix="/venv",
        python_version="3.12",
    )
    monkeypatch.setattr("workflows.reviewed_launch_binding.installation_pin", lambda: pin)
    source = tmp_path / "source.json"
    source.write_text("{}")
    return NativeChainLaunchContext(
        binding=LaunchInputBinding(installation=pin, files=(), file_max_bytes=1024),
        working_directory=str(Path.cwd()),
        manifest=str(tmp_path / "task.json"),
        workspace=str(tmp_path / "run"),
        manifest_sha256="a" * 64,
        composition_fingerprint="b" * 64,
        code_package_identity=None,
        planner_identity={},
        health_config_sha256=None,
        llm_config={},
        launch_identity={},
        launch_settings=json_launch_values(WorkflowLaunchConfig(source_paths=[])),
        hardware={},
        watchdog={},
        aggregate_ceiling=None,
        iteration=2,
        final_iteration=2,
        run_name="native",
        source_pin=file_pin(str(source), 1024),
    )


def test_only_actual_restored_paths_and_dispatched_index_can_change(context):
    state = RestoredState(
        resolved_source_paths=["/native/iter_001/run_output.json"], committed_iters=[1]
    )
    launch = WorkflowLaunchConfig(start_iteration=2, source_paths=state.resolved_source_paths)
    context.check_launch(launch, state)
    with pytest.raises(NativeChainCaptureRefusal, match="restoration_paths_changed"):
        context.check_launch(replace(launch, source_paths=["/external/injected.json"]), state)
    with pytest.raises(NativeChainCaptureRefusal, match="native_recipe_changed"):
        context.check_launch(replace(launch, start_iteration=1), state)
    with pytest.raises(NativeChainCaptureRefusal, match="launch_settings_changed"):
        context.check_launch(replace(launch, max_rounds=99), state)
    missing = dict(context.launch_settings)
    del missing["max_rounds"]
    with pytest.raises(NativeChainCaptureRefusal, match="launch_settings_changed"):
        context.model_copy(update={"launch_settings": missing}).check_launch(launch, state)


def test_shared_refusal_translates_but_unrelated_value_error_does_not(context, monkeypatch):
    with pytest.raises(NativeChainCaptureRefusal, match="task_identity_changed"):
        context.check_composition(SimpleNamespace(semantic_fingerprint="c" * 64))

    def scientific_failure(*args):
        raise ValueError("scientific failure")

    monkeypatch.setattr(
        "workflows.launch_expectations.LaunchExpectations.check_composition", scientific_failure
    )
    with pytest.raises(ValueError, match="scientific failure") as error:
        context.check_composition(None)
    assert not isinstance(error.value, NativeChainCaptureRefusal)


def test_setup_context_serialized_fields_are_preserved(context):
    values = context.model_dump(exclude={"iteration", "final_iteration", "run_name", "source_pin"})
    setup = ReviewedLaunchContext(**values, receipt_path="/receipt", receipt_fields={})
    assert set(setup.model_dump()) == {
        "binding",
        "working_directory",
        "manifest",
        "workspace",
        "manifest_sha256",
        "composition_fingerprint",
        "code_package_identity",
        "planner_identity",
        "health_config_sha256",
        "llm_config",
        "launch_identity",
        "launch_settings",
        "hardware",
        "watchdog",
        "aggregate_ceiling",
        "receipt_path",
        "receipt_fields",
    }


def test_wrapper_does_not_convert_native_scientific_errors(context, monkeypatch):
    from tools.native_chain import iteration
    from tools.native_chain.models import NativeChainCaptureReference

    reference = NativeChainCaptureReference(
        path=Path("/capture"), sha256="a" * 64, input_max_bytes=1024
    )
    monkeypatch.setattr(
        iteration,
        "parse_check",
        lambda: (SimpleNamespace(command="dispatch", iteration=2), reference, ()),
    )
    monkeypatch.setattr(iteration, "verify_dispatch", lambda dispatch: None)
    monkeypatch.setattr(iteration, "launch_context", lambda *args: context)

    def refuse(*args, **kwargs):
        raise NativeChainCaptureRefusal("task_identity_changed")

    monkeypatch.setattr("workflows.run_one_iteration.main", refuse)
    assert iteration.main() == 78

    def scientific(*args, **kwargs):
        raise ValueError("scientific failure")

    monkeypatch.setattr("workflows.run_one_iteration.main", scientific)
    with pytest.raises(ValueError, match="scientific failure"):
        iteration.main()


def test_missing_pinned_source_is_capture_refusal(context):
    Path(context.source_pin.path).unlink()
    with pytest.raises(NativeChainCaptureRefusal, match="input_verification_unavailable"):
        context.check_launch(
            WorkflowLaunchConfig(start_iteration=2, source_paths=[]), RestoredState()
        )


def test_git_inspection_failure_is_capture_refusal(context, monkeypatch):
    import subprocess

    def unavailable():
        raise subprocess.CalledProcessError(128, ["git"])

    monkeypatch.setattr("workflows.reviewed_launch_binding.installation_pin", unavailable)
    with pytest.raises(NativeChainCaptureRefusal, match="input_verification_unavailable"):
        context.check_launch(
            WorkflowLaunchConfig(start_iteration=2, source_paths=[]), RestoredState()
        )
