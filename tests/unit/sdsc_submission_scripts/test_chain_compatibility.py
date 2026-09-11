"""Generic chain transport compatibility after campaign extraction."""

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CHAIN_COMMON = REPO_ROOT / "scripts" / "launch" / "_chain_common.sh"


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


def test_time_admission_authorities_are_independent_chain_arguments() -> None:
    tokens = _build(
        "--workspace",
        "/tmp/workspace",
        "--run_name",
        "test",
        "--trial_time_admission_source",
        "forecast",
        "--formal_time_admission_source",
        "measured",
    )
    assert tokens[tokens.index("--trial_time_admission_source") + 1] == "forecast"
    assert tokens[tokens.index("--formal_time_admission_source") + 1] == "measured"


def test_optional_llm_config_is_not_emitted_as_an_empty_flag() -> None:
    tokens = _build("--workspace", "/tmp/workspace", "--run_name", "test")
    assert "--llm_config" not in tokens


def test_vram_preflight_watchdogs_reach_each_iteration() -> None:
    """A chain-level override must not stop at the shell wrapper."""
    tokens = _build(
        "--workspace",
        "/tmp/workspace",
        "--run_name",
        "test",
        "--vram_probe_step_timeout_seconds",
        "321",
        "--vram_preflight_total_timeout_seconds",
        "987",
        "--vram_preflight_host_memory_limit_gb",
        "42.5",
    )

    assert tokens[tokens.index("--vram_probe_step_timeout_seconds") + 1] == "321"
    assert tokens[tokens.index("--vram_preflight_total_timeout_seconds") + 1] == "987"
    assert tokens[tokens.index("--vram_preflight_host_memory_limit_gb") + 1] == "42.5"


def test_runtime_verification_window_reaches_each_iteration() -> None:
    """A slow-step workload must receive its explicit verifier window."""
    tokens = _build(
        "--workspace",
        "/tmp/workspace",
        "--run_name",
        "test",
        "--runtime_verification_max_wall_seconds",
        "420",
    )

    index = tokens.index("--runtime_verification_max_wall_seconds")
    assert tokens[index + 1] == "420"

    defaults = _build("--workspace", "/tmp/workspace", "--run_name", "test")
    assert "--runtime_verification_max_wall_seconds" not in defaults


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
