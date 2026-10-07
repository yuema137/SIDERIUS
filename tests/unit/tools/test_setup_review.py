"""Declaration reports reuse production configuration owners without executing them."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from core.layout import checkout_root
from tools.setup_review.__main__ import main
from tools.setup_review.inspection import inspect_declaration
from tools.setup_review.models import SetupReviewRequest
from tools.setup_review.render import render_html
from workflows.standard_cli import build_parser, normalize_args


@pytest.fixture
def request_for(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "task.yaml").write_text("plugin: must_not_be_imported\n")

    def make(*extra: str) -> SetupReviewRequest:
        return SetupReviewRequest(
            working_directory=str(tmp_path),
            argv=[
                "--workspace",
                "runs",
                "--run_name",
                "synthetic",
                "--start_iteration",
                "1",
                "--task_composition",
                "task.yaml",
                "--data_dir",
                "data",
                *extra,
            ],
        )

    return make


def test_real_defaults_normalization_and_original_argv(request_for, tmp_path):
    request = request_for("--max_rou=5", "--data_scope", "3,1", "--plan_overrides", '{"epochs":2}')
    report = inspect_declaration(request, tmp_path / "report")
    actual = normalize_args(build_parser().parse_args(request.argv))
    defaults = vars(build_parser().parse_args(request_for().argv))
    rows = {row.name: row for row in report.parameters}
    assert rows["max_rounds"].cli_default == defaults["max_rounds"] == 3
    assert rows["max_rounds"].declared_value == actual.max_rounds == 5
    assert rows["is_trial"].cli_default is True
    assert rows["data_scope"].declared_value == actual.data_scope.model_dump(mode="json")
    assert rows["plan_overrides"].declared_value == {"epochs": 2}
    assert rows["workspace"].required
    assert rows["runtime_watchdog"].declared_value is None
    assert "effective watchdog" in " ".join(report.unresolved)
    assert report.launch_argv == [
        sys.executable,
        "-m",
        "workflows.run_one_iteration",
        *request.argv,
    ]
    assert report.request.working_directory == str(tmp_path)
    assert not (tmp_path / "runs").exists()
    assert not (tmp_path / "report").exists()
    assert set(rows) == set(defaults) - {"help"} | {"human_advice_mindset"}


def test_alias_advice_precedence_and_fresh_identity(request_for, tmp_path):
    advice = tmp_path / "advice.json"
    advice.write_text(json.dumps({"propose": "file advice", "mindset": "first"}))
    request = request_for("--advice", "advice.json", "--human_advice_propose", "CLI advice")
    request.argv[request.argv.index("--start_iteration")] = "--iteration"
    with pytest.warns(DeprecationWarning):
        first = inspect_declaration(request, tmp_path / "report")
    rows = {row.name: row for row in first.parameters}
    assert rows["iteration_legacy"].normalized_name == "start_iteration"
    assert rows["iteration_legacy"].declared_value == 1
    assert rows["human_advice_propose"].declared_value == "CLI advice"
    assert rows["human_advice_mindset"].declared_value == "first"
    advice.write_text(json.dumps({"propose": "changed", "mindset": "second"}))
    with pytest.warns(DeprecationWarning):
        second = inspect_declaration(request, tmp_path / "report")
    assert first.launch_identity["advice_sha256"] != second.launch_identity["advice_sha256"]
    assert {row.name: row.declared_value for row in second.parameters}[
        "human_advice_mindset"
    ] == "second"


def test_missing_and_explicit_llm_blocks_are_not_effective_defaults(request_for, tmp_path):
    config = tmp_path / "llm.json"
    config.write_text('{"implement": {}}')
    report = inspect_declaration(request_for("--llm_config", "llm.json"), tmp_path / "report")
    assert report.declared_llm_config["interpret"] is None
    assert isinstance(report.declared_llm_config["implement"], dict)
    assert report.declared_llm_config["implement"]["provider"] == "gemini"
    assert report.llm_review == "not_performed"
    assert "Static LLM routes" in " ".join(report.unresolved)


@pytest.mark.parametrize(
    "extra",
    [
        ["--start_iteration", "2"],
        ["--seed_paths", "old.json"],
        ["--auto_resume"],
        ["--replace_iteration_manifest"],
        ["--replacement_reason", "repeat"],
        ["--validation_fixed_candidate_plan", "old.json"],
        ["--print_resolved_launch_config"],
        ["--help"],
        ["--does-not-exist"],
    ],
)
def test_unsupported_or_nonlaunch_arguments_refuse(request_for, tmp_path, extra):
    with pytest.raises(ValueError):
        inspect_declaration(request_for(*extra), tmp_path / "report")
    assert not (tmp_path / "report").exists()


def test_cwd_and_fresh_workspace_checks(request_for, tmp_path):
    request = request_for()
    request = request.model_copy(update={"working_directory": str(tmp_path / "other")})
    with pytest.raises(ValueError, match="working_directory"):
        inspect_declaration(request, tmp_path / "report")
    run = tmp_path / "runs"
    run.mkdir()
    (run / "record.json").write_text("{}")
    with pytest.raises(ValueError, match="empty directory"):
        inspect_declaration(request_for(), tmp_path / "report")
    (run / "record.json").unlink()
    assert inspect_declaration(request_for(), tmp_path / "report").workspace == str(run)


def test_output_collisions_overlaps_and_symlink_aliases(request_for, tmp_path):
    output = tmp_path / "report"
    output.mkdir()
    (output / "keep").write_text("unchanged")
    with pytest.raises(ValueError, match="already exists"):
        inspect_declaration(request_for(), output)
    assert (output / "keep").read_text() == "unchanged"
    with pytest.raises(ValueError, match="non-nested"):
        inspect_declaration(request_for(), tmp_path / "runs" / "report")
    root = checkout_root()
    assert root is not None
    alias = tmp_path / "framework"
    alias.symlink_to(root, target_is_directory=True)
    with pytest.raises(ValueError, match="outside the framework"):
        inspect_declaration(request_for(), alias / "new-report")
    with pytest.raises(ValueError, match="outside the framework"):
        inspect_declaration(
            request_for("--workspace", str(alias / "new-run")), tmp_path / "new-report"
        )
    broken = tmp_path / "broken-report"
    broken.symlink_to(tmp_path / "absent")
    with pytest.raises(ValueError, match="already exists"):
        inspect_declaration(request_for(), broken)


def test_html_escapes_content_and_keeps_exact_venv_path(request_for, tmp_path, monkeypatch):
    malicious = '<script>alert("x")</script> & $(touch forbidden)'
    request = request_for("--human_advice_propose", malicious)
    venv_python = str(tmp_path / "virtual env" / "bin" / "python")
    monkeypatch.setattr(sys, "executable", venv_python)
    report = inspect_declaration(request, tmp_path / "report")
    rendered = render_html(report)
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered
    assert "&amp;" in rendered
    assert "&quot;" in rendered
    assert report.launch_argv[0] == venv_python
    assert malicious in report.request.argv
    assert "Settings read; launch readiness is not verified" in rendered
    assert " &amp;&amp;\n" in rendered
    assert "CLI help" in rendered
    assert not (tmp_path / "forbidden").exists()


def test_partial_publication_never_removes_existing_data(
    request_for, tmp_path, monkeypatch, capsys
):
    from tools.setup_review import __main__ as cli

    request_path = tmp_path / "request.json"
    request_path.write_text(request_for().model_dump_json())
    output = tmp_path / "report"
    publish = cli.publish_bytes_write_once

    def fail_second(path, payload):
        if Path(path).name == "index.html":
            (output / "index.html").write_text("concurrent writer")
            raise FileExistsError(path)
        publish(path, payload)

    monkeypatch.setattr(cli, "publish_bytes_write_once", fail_second)
    assert main(["--request", str(request_path), "--output", str(output)]) == 2
    assert (output / "index.html").read_text() == "concurrent writer"
    assert (output / "report.json").is_file()
    assert "Declaration report:" not in capsys.readouterr().out


@pytest.mark.parametrize(
    "payload",
    [
        {"working_directory": "relative", "argv": []},
        {"working_directory": "/tmp", "argv": [42]},
        {"working_directory": "/tmp", "argv": [], "command": "untrusted"},
        {"working_directory": "/tmp", "argv": ["null\0argument"]},
    ],
)
def test_request_boundary_rejects_ambiguous_inputs(payload):
    with pytest.raises(ValueError):
        SetupReviewRequest.model_validate(payload)


@pytest.mark.parametrize(
    "extra",
    [
        ["--formal_time_budget_minutes", "nan"],
        ["--trial_vram_budget_gb", "inf"],
        ["--plan_overrides", '{"nested": {"value": NaN}}'],
    ],
)
def test_nonfinite_declarations_cannot_turn_into_json_null(request_for, tmp_path, extra):
    with pytest.raises(ValueError, match="finite number"):
        inspect_declaration(request_for(*extra), tmp_path / "report")
