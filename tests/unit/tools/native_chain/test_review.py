"""Transport witnesses: no human-output parsing or control override."""

from pathlib import Path

import pytest

from core.layout import checkout_root
from tools.native_chain.models import NativeChainDeclaration, NativeChainRunBinding
from tools.native_chain.review import export_argv


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
