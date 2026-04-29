"""Consistency contract tests (Phase 6.8 Commit 11 §3.8).

Validates that every shared flag has identical name and default across:
  1. run_exploration_adaptive.py (parse_args)
  2. sdsc_submission_scripts/run_one_iteration.py (build_parser)

The shell entry (_chain_common.sh) is tested by grep-based assertions
on the variable defaults and case arms.

Flags that are layer-specific (per §3.8 "Allowed exceptions") are
excluded from the parity check.
"""
from __future__ import annotations

import re

from run_exploration_adaptive import parse_args as _adaptive_parse_args
from sdsc_submission_scripts.run_one_iteration import build_parser as _roi_build_parser


# ---------------------------------------------------------------------------
# Helpers — extract (name, default, type, nargs) from ArgumentParser
# ---------------------------------------------------------------------------

def _extract_flags(parser):
    """Return {flag_name: {default, type, nargs}} for every optional action."""
    result = {}
    for action in parser._actions:
        if not action.option_strings:
            continue
        long_names = [s for s in action.option_strings if s.startswith("--")]
        if not long_names:
            continue
        name = long_names[0].lstrip("-")
        result[name] = {
            "default": action.default,
            "type": action.type,
            "nargs": action.nargs,
        }
    return result


def _get_adaptive_flags():
    """Get flags from run_exploration_adaptive.py."""
    import argparse
    import sys
    original_parse = argparse.ArgumentParser.parse_args

    class _CapturingParser(argparse.ArgumentParser):
        def parse_args(self, args=None, namespace=None):
            raise SystemExit("captured")

    parser = argparse.ArgumentParser.__new__(argparse.ArgumentParser)
    # We need to build the parser without actually calling parse_args.
    # The adaptive script's parse_args() calls parser.parse_args() at the end,
    # so we import the module and reconstruct.
    import importlib
    import run_exploration_adaptive as mod
    importlib.reload(mod)  # ensure fresh

    # Build a parser by calling the function with sys.argv stubbed
    saved_argv = sys.argv
    try:
        sys.argv = ["run_exploration_adaptive.py", "--run_name", "dummy"]
        try:
            ns = mod.parse_args()
        except SystemExit:
            ns = None
    finally:
        sys.argv = saved_argv

    # We can't easily get the parser object from parse_args(), so we'll
    # inspect the function source. Better approach: reconstruct the parser
    # by reading the source. Actually, since parse_args returns
    # parser.parse_args(), we can monkey-patch to capture the parser.
    captured_parser = [None]
    original_method = argparse.ArgumentParser.parse_args

    def _capture(self, *a, **kw):
        captured_parser[0] = self
        return original_method(self, *a, **kw)

    argparse.ArgumentParser.parse_args = _capture
    saved_argv = sys.argv
    try:
        sys.argv = ["run_exploration_adaptive.py", "--run_name", "dummy"]
        try:
            mod.parse_args()
        except SystemExit:
            pass
    finally:
        sys.argv = saved_argv
        argparse.ArgumentParser.parse_args = original_method

    return _extract_flags(captured_parser[0])


def _get_roi_flags():
    """Get flags from run_one_iteration.py's build_parser()."""
    return _extract_flags(_roi_build_parser())


# ---------------------------------------------------------------------------
# Flags that must match across both Python entries (§3.8)
# ---------------------------------------------------------------------------

# Layer-specific exclusions (from §3.8 "Allowed exceptions"):
# - run_name: adaptive=required, roi=synthesised from iter index (Option β)
# - workspace: adaptive=optional default, roi=required (Option β)
# - max_iterations: adaptive-only (chain length)
# - iteration_legacy: roi-only deprecated alias (Commit 8)
# - start_iteration: roi=None default (requires one of two aliases), adaptive=1 default
# - source_paths_legacy: roi/adaptive both have it, but it is the deprecated
#     alias of --seed_paths (Commit 11) — parity is enforced on --seed_paths
# - is_trial: roi-only (adaptive always passes True)
# - reflect_provider, reflect_model_id: roi-only legacy plumbing
# - gpu_memory_limit_gb: roi-only legacy
# - cleanup_denoised: roi=store_true, adaptive passes True unconditionally
# - human_advice_file and per-agent human_advice_*: roi-only legacy schema
# - plan_overrides: roi=str→dict, adaptive passes dict directly
# - llm_model: roi-only legacy uniform-model flag (adaptive uses --llm_config exclusively)
EXCLUDED_FLAGS = frozenset({
    "run_name",
    "workspace",
    "max_iterations",
    "iteration_legacy",
    "start_iteration",
    "source_paths_legacy",
    "is_trial",
    "reflect_provider",
    "reflect_model_id",
    "gpu_memory_limit_gb",
    "cleanup_denoised",
    "human_advice_file",
    "human_advice_interpret",
    "human_advice_propose",
    "human_advice_implement",
    "human_advice_validate",
    "human_advice_tune",
    "plan_overrides",
    "llm_model",
    "advice",
    "help",
})

# Flags that must have identical name + default
SHARED_FLAGS = [
    "seed_paths",
    "max_rounds",
    "max_proposal_attempts",
    "max_impl_attempts",
    "trial_strategy",
    "trial_portion",
    "train_portion",
    "eval_portion",
    "max_epochs",
    "target_files",
    "sampling_seed",
    "trial_time_budget_minutes",
    "formal_time_budget_minutes",
    "data_dir",
    "trial_vram_budget_gb",
    "formal_vram_budget_gb",
    "formal_strategy",
    "formal_portion",
    "formal_train_portion",
    "force_formal_round",
    "attempts_per_round",
    "attempts_per_formal_round",
    "max_fail_rounds",
    "exploration_mode",
    "minimum_boldness",
    "debug_dump_prompts",
    "llm_config",
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestFlagNameParity:
    """Every shared flag exists in both entries with the same long-form name."""

    def test_shared_flags_exist_in_adaptive(self):
        flags = _get_adaptive_flags()
        for name in SHARED_FLAGS:
            assert name in flags, (
                f"Flag --{name} missing from run_exploration_adaptive.py"
            )

    def test_shared_flags_exist_in_roi(self):
        flags = _get_roi_flags()
        for name in SHARED_FLAGS:
            assert name in flags, (
                f"Flag --{name} missing from run_one_iteration.py"
            )


class TestDefaultParity:
    """Every shared flag has the same default in both entries."""

    def test_defaults_match(self):
        adaptive = _get_adaptive_flags()
        roi = _get_roi_flags()
        mismatches = []
        for name in SHARED_FLAGS:
            a_default = adaptive.get(name, {}).get("default")
            r_default = roi.get(name, {}).get("default")
            if a_default != r_default:
                mismatches.append(
                    f"--{name}: adaptive={a_default!r}, roi={r_default!r}"
                )
        assert not mismatches, (
            "Default-value mismatches between entries:\n"
            + "\n".join(f"  {m}" for m in mismatches)
        )


class TestTypeParity:
    """Every shared flag has the same type/nargs in both entries."""

    def test_types_match(self):
        adaptive = _get_adaptive_flags()
        roi = _get_roi_flags()
        mismatches = []
        for name in SHARED_FLAGS:
            a_info = adaptive.get(name, {})
            r_info = roi.get(name, {})
            a_type = a_info.get("type")
            r_type = r_info.get("type")
            # Custom argparse type validators (e.g. _positive_int) are
            # defined per-module; compare callable names to allow each
            # entry to keep its own copy of the helper.
            if callable(a_type) and callable(r_type):
                a_key = getattr(a_type, "__name__", repr(a_type))
                r_key = getattr(r_type, "__name__", repr(r_type))
                if a_key != r_key:
                    mismatches.append(
                        f"--{name} type: adaptive={a_key}, roi={r_key}"
                    )
            elif a_type != r_type:
                mismatches.append(
                    f"--{name} type: adaptive={a_type}, roi={r_type}"
                )
            if a_info.get("nargs") != r_info.get("nargs"):
                mismatches.append(
                    f"--{name} nargs: adaptive={a_info.get('nargs')}, "
                    f"roi={r_info.get('nargs')}"
                )
        assert not mismatches, (
            "Type/nargs mismatches:\n"
            + "\n".join(f"  {m}" for m in mismatches)
        )


class TestShellDefaults:
    """Verify _chain_common.sh variable defaults match the Python entries."""

    SHELL_PATH = "sdsc_submission_scripts/_chain_common.sh"

    def _read_shell(self):
        with open(self.SHELL_PATH) as f:
            return f.read()

    def test_max_rounds_default(self):
        content = self._read_shell()
        assert re.search(r'^MAX_ROUNDS=3$', content, re.MULTILINE), (
            "MAX_ROUNDS default in _chain_common.sh should be 3"
        )

    def test_exploration_mode_default(self):
        content = self._read_shell()
        assert re.search(r'^EXPLORATION_MODE="auto"$', content, re.MULTILINE), (
            "EXPLORATION_MODE default should be 'auto'"
        )

    def test_minimum_boldness_default(self):
        content = self._read_shell()
        assert re.search(r'^MINIMUM_BOLDNESS="0\.05"$', content, re.MULTILINE), (
            "MINIMUM_BOLDNESS default should be '0.05'"
        )

    def test_data_dir_present(self):
        content = self._read_shell()
        assert "DATA_DIR=" in content, "DATA_DIR variable missing from shell"

    def test_build_app_args_uses_start_iteration(self):
        content = self._read_shell()
        assert "--start_iteration" in content, (
            "build_app_args should pass --start_iteration (not --iteration)"
        )

    def test_budget_variables_present(self):
        content = self._read_shell()
        for var in [
            "TRIAL_TIME_BUDGET_MINUTES",
            "FORMAL_TIME_BUDGET_MINUTES",
            "TRIAL_VRAM_BUDGET_GB",
            "FORMAL_VRAM_BUDGET_GB",
        ]:
            assert f'{var}=""' in content or f"{var}=" in content, (
                f"{var} variable missing from shell defaults"
            )
