"""Cold-start CLI + shell parsing (PR: seedless chain cold start). No LLM, no GPU.

CLI: omitting --seed_paths yields an empty (cold-start) list; a bare
--seed_paths with no values is still an argparse error; supplied seeds are
preserved. Shell: build_app_args omits --seed_paths when the seed list is empty
and emits it (with values) when seeds are supplied.
"""

import importlib.util
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
_ROI = _REPO / "sdsc_submission_scripts" / "run_one_iteration.py"
_CHAIN_COMMON = _REPO / "sdsc_submission_scripts" / "_chain_common.sh"

_BASE_ARGV = ["--workspace", "/tmp/x", "--run_name", "y", "--start_iteration", "1"]


def _load_roi():
    spec = importlib.util.spec_from_file_location("run_one_iteration_mod", _ROI)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestColdStartCLI:
    def test_omitting_seed_paths_yields_empty_cold_start_list(self):
        mod = _load_roi()
        args = mod.normalize_args(mod.build_parser().parse_args(_BASE_ARGV))
        assert args.seed_paths == []

    def test_bare_seed_paths_flag_is_argparse_error(self):
        mod = _load_roi()
        with pytest.raises(SystemExit):
            mod.build_parser().parse_args([*_BASE_ARGV, "--seed_paths"])

    def test_supplied_seed_paths_are_preserved(self):
        mod = _load_roi()
        args = mod.normalize_args(
            mod.build_parser().parse_args([*_BASE_ARGV, "--seed_paths", "a.json", "b.json"])
        )
        assert args.seed_paths == ["a.json", "b.json"]


def _build_app_args(seed_assignment: str) -> str:
    """Source _chain_common.sh, set SEED_PATHS, call build_app_args, echo APP_ARGS."""
    script = f"""
    set +e
    source "{_CHAIN_COMMON}"
    WORKSPACE=/tmp/ws
    RUN_NAME=cs
    {seed_assignment}
    build_app_args 1
    printf '%s\\n' "${{APP_ARGS[@]}}"
    """
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


class TestColdStartShellEmit:
    def test_no_seed_paths_flag_when_empty(self):
        out = _build_app_args("SEED_PATHS=()")
        assert "--seed_paths" not in out.splitlines()

    def test_seed_paths_flag_and_values_when_supplied(self):
        out = _build_app_args("SEED_PATHS=(/a.json /b.json)")
        lines = out.splitlines()
        assert "--seed_paths" in lines
        assert "/a.json" in lines and "/b.json" in lines
