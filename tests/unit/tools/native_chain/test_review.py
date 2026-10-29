"""Transport witnesses: no human-output parsing or control override."""

from pathlib import Path

import pytest

from core.layout import checkout_root
from tools.native_chain.models import PROTECTED, NativeChainDeclaration, NativeChainRunBinding
from tools.native_chain.review import export_argv
from workflows.standard_cli import build_parser


def declaration(tmp_path, *args):
    return NativeChainDeclaration(
        working_directory=checkout_root(),
        run=NativeChainRunBinding(
            workspace=tmp_path / "run", run_name="Unicode α space", final_iteration=2
        ),
        chain_args=(
            "--task_composition",
            "configs/task_composition/quickstart.yaml",
            "--data_dir",
            str(tmp_path),
            *args,
        ),
    )


def test_real_shell_export_preserves_values_and_owner_defaults(tmp_path):
    args = export_argv(
        declaration(tmp_path, "--analysis_source_prompt", "α with space", "--max_epochs", "0"),
        2,
        1048576,
    )
    assert args[args.index("--start_iteration") + 1] == "2"
    assert args[args.index("--run_name") + 1] == "Unicode α space"
    assert args[args.index("--analysis_source_prompt") + 1] == "α with space"
    assert args[args.index("--max_epochs") + 1] == "0"
    assert "--seed_paths" not in args
    assert "--no_auto_resume" not in args


@pytest.mark.parametrize(
    "flag",
    [
        "--mode=sdsc",
        "--seed-paths",
        "--dry-run",
        "--start_iter",
        "--chain_export_fd",
        "--validation_fixed_candidate_plan",
    ],
)
def test_controls_cannot_override_dedicated_recipe(tmp_path, flag):
    with pytest.raises(ValueError, match="protected_chain_control"):
        declaration(tmp_path, flag)


@pytest.mark.parametrize(
    ("option", "value", "control"),
    [
        ("--seed_pat", "X", "--seed_paths"),
        ("--run_se", "3", "--run_seed"),
        ("--chai", "3", "--chain_capture_input_max_bytes"),
        ("--chain_export_f", "3", "--chain_export_fd"),
        ("--seed-pat=X", None, "--seed_paths"),
        ("--run_se=3", None, "--run_seed"),
    ],
)
def test_abbreviated_controls_are_refused(tmp_path, option, value, control):
    # Removing the prefix check admits overrides before review/export can run.
    args = (option,) if value is None else (option, value)
    with pytest.raises(ValueError, match="protected_chain_control") as error:
        declaration(tmp_path, *args)
    assert f"{option.split('=', 1)[0]} expands to {control}" in str(error.value)


def test_nonprotected_abbreviation_remains_accepted(tmp_path):
    parser = build_parser()
    item = declaration(tmp_path, "--max_ep", "2")
    args = parser.parse_args(["--workspace", str(tmp_path), "--run_name", "test", *item.chain_args])
    assert args.max_epochs == 2
    assert item.chain_args[-2:] == ("--max_ep", "2")


@pytest.mark.parametrize(
    "option",
    [
        option
        for option in build_parser()._option_string_actions
        if option.lstrip("-").replace("-", "_") not in PROTECTED
        and not option.lstrip("-").replace("-", "_").startswith("chain_")
    ],
)
def test_full_nonprotected_options_remain_accepted(tmp_path, option):
    # The declaration checks ownership, leaving option values to the parser.
    assert declaration(tmp_path, option).chain_args[-1] == option


def test_external_cwd_refuses_before_shell(tmp_path, monkeypatch):
    item = declaration(tmp_path)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="working_directory_changed"):
        export_argv(item, 1, 1048576)


def test_export_limit_and_index_are_enforced(tmp_path):
    item = declaration(tmp_path)
    with pytest.raises(ValueError, match="invalid_shell_transport"):
        export_argv(item, 1, 2)
    with pytest.raises(ValueError, match="iteration_out_of_range"):
        export_argv(item, 3, 1048576)


def test_parser_values_are_not_exposed(tmp_path, capsys):
    from tools.native_chain.models import NativeChainReviewRequest
    from tools.native_chain.review import review
    from tools.setup_review.composition_models import TaskCheckSettings

    source = tmp_path / "source.json"
    source.write_text(declaration(tmp_path, "--max_epochs", "PRIVATE_SENTINEL").model_dump_json())
    request = NativeChainReviewRequest(
        source=source,
        output=tmp_path / "report",
        read_only=(),
        task_check=TaskCheckSettings(timeout_seconds=10),
        input_max_bytes=1048576,
    )
    with pytest.raises(ValueError, match="standard_arguments_refused"):
        review(request)
    assert "PRIVATE_SENTINEL" not in capsys.readouterr().err
    assert not request.output.exists()


def test_workspace_cannot_be_under_data_root(tmp_path):
    from tools.native_chain.models import NativeChainReviewRequest
    from tools.native_chain.review import review
    from tools.setup_review.composition_models import TaskCheckSettings

    source = tmp_path / "source.json"
    source.write_text(declaration(tmp_path).model_dump_json())
    request = NativeChainReviewRequest(
        source=source,
        output=tmp_path / "report",
        read_only=(),
        task_check=TaskCheckSettings(timeout_seconds=10),
        input_max_bytes=1048576,
    )
    with pytest.raises(ValueError, match="workspace_overlap"):
        review(request)
    assert not request.output.exists()
