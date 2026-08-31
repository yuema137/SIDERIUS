"""Generic chain transport compatibility after campaign extraction."""

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CHAIN_COMMON = REPO_ROOT / "sdsc_submission_scripts" / "_chain_common.sh"


def _build(*args: str) -> list[str]:
    env = dict(os.environ)
    env.pop("CUDA_VISIBLE_DEVICES", None)
    command = (
        f"source '{CHAIN_COMMON}'; parse_chain_args "
        + " ".join(args)
        + '; build_app_args 1; printf "%s\\n" "${APP_ARGS[@]}"'
    )
    result = subprocess.run(
        ["bash", "-c", command],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.splitlines()


def test_bypass_ceiling_is_typed_and_omitted_when_absent() -> None:
    base = ("--workspace", "/tmp/workspace", "--run_name", "test")
    typed = _build(*base, "--bypass_formal_time_budget_minutes", "200")
    assert typed[typed.index("--bypass_formal_time_budget_minutes") + 1] == "200"
    assert "--bypass_formal_time_budget_minutes" not in _build(*base)


def test_optional_llm_config_is_not_emitted_as_an_empty_flag() -> None:
    tokens = _build("--workspace", "/tmp/workspace", "--run_name", "test")
    assert "--llm_config" not in tokens


def test_retention_suppresses_cleanup_without_leaking_a_chain_only_flag() -> None:
    tokens = _build(
        "--workspace",
        "/tmp/workspace",
        "--run_name",
        "test",
        "--no-cleanup_denoised",
    )
    assert "--cleanup_denoised" not in tokens
    assert "--no-cleanup_denoised" not in tokens
