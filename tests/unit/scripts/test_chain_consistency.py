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
    "formal_round_strategy",
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
        assert re.search(r'^MAX_ROUNDS=3\b', content, re.MULTILINE), (
            "MAX_ROUNDS default in _chain_common.sh should be 3"
        )

    def test_exploration_mode_default(self):
        content = self._read_shell()
        assert re.search(r'^EXPLORATION_MODE="auto"', content, re.MULTILINE), (
            "EXPLORATION_MODE default should be 'auto'"
        )

    def test_minimum_boldness_default(self):
        content = self._read_shell()
        assert re.search(r'^MINIMUM_BOLDNESS="0\.05"', content, re.MULTILINE), (
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


# ---------------------------------------------------------------------------
# Gate A — Three-way Python ↔ Python ↔ shell parity (Phase 6.8 Commit 13.E)
# ---------------------------------------------------------------------------
# Extends the Python-Python parity tests above with shell-side assertions
# parsed directly from _chain_common.sh. For each §3.2 flag, asserts that:
#   1. Name parity: the long-form flag exists as a `case` arm in
#      parse_chain_args.
#   2. Default parity: the top-of-file `VAR_NAME=value` default, when
#      normalized, matches both Python entries' argparse default.
#   3. Type parity: the case-arm handler shape (scalar / boolean / list)
#      matches the Python action's nargs/action contract.
# Drift on any single property fails the test with a human-readable
# multi-line diff naming the source of disagreement.

# §3.2 contract subset — flags that the chain shell wrapper must mirror.
# Excludes Python-only flags like --force_formal_round (per-iter planner
# concern, not per-chain) and layer-specific flags from EXCLUDED_FLAGS.
THREE_WAY_FLAGS = [
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
    "formal_round_strategy",
    "attempts_per_round",
    "attempts_per_formal_round",
    "max_fail_rounds",
    "exploration_mode",
    "minimum_boldness",
    "debug_dump_prompts",
    "llm_config",
]

# Flags whose shell default intentionally diverges from Python's argparse
# default. Each entry documents why.
SHELL_DEFAULT_OVERRIDES = {
    # 13.C directive — pre-filled with the canonical lilab data path so the
    # chain runbook works without an explicit --data_dir flag on lilab.
    # Python argparse default is None; shell pre-fills /home/klz/Data/TIDMAD/.
    "data_dir": "/home/klz/Data/TIDMAD/",
}

# Flag → shell variable name. Convention: uppercase-snake of the flag.
def _shell_var_name(flag: str) -> str:
    return flag.upper()


def _read_shell() -> str:
    with open("sdsc_submission_scripts/_chain_common.sh") as f:
        return f.read()


def _parse_shell_defaults(content: str) -> dict[str, str]:
    """Return {VAR_NAME: raw_default_value} from top-of-file assignments.

    Handles four shapes:
        VAR=value
        VAR="quoted value"
        VAR=()              (empty array)
        VAR=value           # trailing comment
    Strips trailing comments; preserves the surrounding quotes/parens
    so callers can tell '' apart from () apart from "literal".
    """
    out: dict[str, str] = {}
    # We only care about top-level scalar/array assignments — not
    # inside functions. Stop at the first function definition.
    head = re.split(r"^\s*\w+\(\)\s*\{", content, maxsplit=1, flags=re.MULTILINE)[0]
    for line in head.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([A-Z_][A-Z0-9_]*)=(.*)$", line)
        if not m:
            continue
        name, raw = m.group(1), m.group(2)
        # Strip trailing comment (everything after a ` #`).
        if " #" in raw:
            raw = raw.split(" #", 1)[0]
        raw = raw.rstrip()
        out[name] = raw
    return out


def _parse_shell_case_arms(content: str) -> dict[str, str]:
    """Return {flag_name: handler_shape} for parse_chain_args case arms.

    handler_shape is one of:
        "scalar"    — `VAR="$2"; shift 2 ;;`
        "boolean"   — `VAR=1; shift ;;`
        "list"      — multi-line `while` loop with `VAR+=("$1")`
    """
    # Extract the parse_chain_args function body.
    m = re.search(
        r"parse_chain_args\(\)\s*\{(.*?)^\}",
        content,
        re.MULTILINE | re.DOTALL,
    )
    if not m:
        return {}
    body = m.group(1)

    # Walk arms by anchoring on the `--flag)` token. We capture from the
    # arm marker to the next `;;` (or to the end of the case block).
    arms: dict[str, str] = {}
    arm_re = re.compile(
        r"^\s*--([a-z][a-z0-9_]*)\)(.*?);;",
        re.MULTILINE | re.DOTALL,
    )
    for am in arm_re.finditer(body):
        flag = am.group(1)
        handler = am.group(2)
        if "+=(" in handler and "while" in handler:
            shape = "list"
        elif '"$2"' in handler and "shift 2" in handler:
            shape = "scalar"
        elif re.search(r"=\d+\s*;\s*shift\b", handler) and '"$2"' not in handler:
            shape = "boolean"
        else:
            shape = f"unknown:{handler.strip()[:80]!r}"
        arms[flag] = shape
    return arms


def _normalize_shell_default(raw: str):
    """Map a shell raw default ('"foo"' / '()' / '0.1' / '0' / '""') to a
    canonical Python value comparable against argparse defaults.

    Returns:
        - "" → None         (mirrors Python's None for absent-by-default)
        - () → None         (empty array → None for nargs='+' flags)
        - 0  → False        (boolean store_true unset)
        - 1  → True         (boolean store_true set)
        - "literal" → str   (quotes stripped)
        - 0.1 → float
        - 3 → int
        - bareword → str
    """
    if raw == "" or raw == '""':
        return None
    if raw == "()":
        return None
    # Strip surrounding quotes first so '"0.05"' and '0.05' both parse
    # as float; bash conventionally quotes float literals to keep them
    # safe under word-splitting when interpolated.
    inner = raw
    if (inner.startswith('"') and inner.endswith('"')) or \
       (inner.startswith("'") and inner.endswith("'")):
        inner = inner[1:-1]
    # Try int / float on the unquoted inner.
    try:
        return int(inner)
    except ValueError:
        pass
    try:
        return float(inner)
    except ValueError:
        pass
    return inner


def _python_action_shape(action) -> str:
    """Map an argparse action to one of {'scalar', 'boolean', 'list'}."""
    cls_name = action.__class__.__name__
    if cls_name in ("_StoreTrueAction", "_StoreFalseAction"):
        return "boolean"
    if cls_name == "BooleanOptionalAction":
        return "boolean"
    if action.nargs in ("+", "*") or action.nargs == "?":
        # nargs='?' is rare in our codebase; treat as scalar if used
        if action.nargs == "?":
            return "scalar"
        return "list"
    return "scalar"


class TestThreeWayConsistency:
    """Single source of truth: §3.2 contract enforced across all three layers.

    Each test produces an aggregated multi-line diff if any flag drifts on
    any property. The failure message names the source of disagreement
    (adaptive / one-iter / shell) so operators can locate the regression.
    """

    def _gather(self):
        adaptive = _get_adaptive_flags()
        roi = _get_roi_flags()
        shell_content = _read_shell()
        shell_defaults = _parse_shell_defaults(shell_content)
        shell_arms = _parse_shell_case_arms(shell_content)
        return adaptive, roi, shell_defaults, shell_arms

    def test_shell_arms_exist_for_every_three_way_flag(self):
        """Every §3.2 flag has a `--<flag>)` arm in parse_chain_args."""
        _, _, _, shell_arms = self._gather()
        missing = [f for f in THREE_WAY_FLAGS if f not in shell_arms]
        assert not missing, (
            "Missing parse_chain_args arms in _chain_common.sh:\n"
            + "\n".join(f"  --{f}" for f in missing)
        )

    def test_shell_default_block_contains_every_var(self):
        """Every §3.2 flag has a top-of-file VAR default declaration."""
        _, _, shell_defaults, _ = self._gather()
        missing = [
            f for f in THREE_WAY_FLAGS
            if _shell_var_name(f) not in shell_defaults
        ]
        assert not missing, (
            "Missing top-of-file defaults in _chain_common.sh:\n"
            + "\n".join(f"  {_shell_var_name(f)}=  (for --{f})" for f in missing)
        )

    def test_three_way_default_parity(self):
        """Every §3.2 flag has matching default across adaptive / one-iter / shell."""
        adaptive, roi, shell_defaults, shell_arms = self._gather()
        diffs = []
        for flag in THREE_WAY_FLAGS:
            a_default = adaptive.get(flag, {}).get("default", "<MISSING>")
            r_default = roi.get(flag, {}).get("default", "<MISSING>")
            if a_default != r_default:
                # Already caught by TestDefaultParity above; skip to keep
                # this test focused on three-way (Python-Python parity is
                # a precondition).
                continue
            python_default = a_default
            shell_var = _shell_var_name(flag)
            shell_raw = shell_defaults.get(shell_var, "<MISSING>")
            # Documented intentional override?
            if flag in SHELL_DEFAULT_OVERRIDES:
                expected = SHELL_DEFAULT_OVERRIDES[flag]
                actual = _normalize_shell_default(shell_raw)
                if actual != expected:
                    diffs.append(
                        f"--{flag}: documented shell override expected "
                        f"{expected!r} but shell has {actual!r} (raw={shell_raw!r})"
                    )
                continue
            shell_norm = _normalize_shell_default(shell_raw)
            # Boolean-shaped flags compare 0/1 → False/True.
            shape = shell_arms.get(flag)
            if shape == "boolean" and isinstance(shell_norm, int):
                shell_norm = bool(shell_norm)
            if shell_norm != python_default:
                diffs.append(
                    f"--{flag}: python={python_default!r}  "
                    f"shell={shell_norm!r} (raw={shell_raw!r})"
                )
        assert not diffs, (
            "Three-way default-value drift between python entries and shell:\n"
            + "\n".join(f"  {d}" for d in diffs)
        )

    def test_three_way_type_parity(self):
        """Every §3.2 flag's shell handler shape matches the python action shape."""
        _, roi, _, shell_arms = self._gather()
        diffs = []
        roi_parser = _roi_build_parser()
        roi_actions = {
            s.lstrip("-"): a
            for a in roi_parser._actions
            for s in a.option_strings
            if s.startswith("--")
        }
        for flag in THREE_WAY_FLAGS:
            python_action = roi_actions.get(flag)
            if python_action is None:
                diffs.append(f"--{flag}: missing from run_one_iteration.py argparse")
                continue
            python_shape = _python_action_shape(python_action)
            shell_shape = shell_arms.get(flag, "<MISSING>")
            if python_shape != shell_shape:
                diffs.append(
                    f"--{flag}: python={python_shape}  shell={shell_shape}  "
                    f"(python action={python_action.__class__.__name__}, "
                    f"nargs={python_action.nargs!r})"
                )
        assert not diffs, (
            "Three-way type/shape drift between python entries and shell:\n"
            + "\n".join(f"  {d}" for d in diffs)
        )


# ---------------------------------------------------------------------------
# Gate B — Kwargs Snapshot Parity (Phase 6.8 Commit 13.E)
# ---------------------------------------------------------------------------
# With the same CLI flag set on both adaptive and one-iter, the kwargs that
# end up in `run_workflow(**kwargs)` must be identical, modulo a documented
# set of layer-specific divergences (see EXEMPT_KEYS below). Drift on any
# non-exempt key indicates one entry was changed without the other and is a
# §3.8 contract violation.
#
# Implementation: monkey-patch each module's imported `run_workflow` symbol
# with a capturing stub that records kwargs and raises a sentinel exception
# to short-circuit any post-call side effects. Both entries are then driven
# with matching argv, and the two captured dicts are compared.

import json as _json
import os as _os
import sys as _sys
from pathlib import Path as _Path

import pytest


class _CapturedRunWorkflow(BaseException):
    """Sentinel raised by the capturing stub to abort the entry-point's main
    flow once kwargs have been recorded. Inherits from BaseException (not
    Exception) so it bypasses the broad ``except Exception:`` handlers that
    both entries wrap their run_workflow() calls in — those handlers would
    otherwise swallow the sentinel and trigger their failure paths."""


def _capture_adaptive_kwargs(monkeypatch, workspace, advice_path, seed_path, common_argv):
    """Drive run_exploration_adaptive._run_one_iter and capture run_workflow kwargs.

    Calling _run_one_iter directly (rather than main) skips the workspace
    validation, advice loading, and outer chain loop; those are not what
    Gate B is verifying. Gate B's contract is the CLI→kwargs *mapping* — and
    that mapping is encoded inside _run_one_iter for adaptive.
    """
    import run_exploration_adaptive as adaptive_mod
    captured: dict = {}

    def _capture(**kwargs):
        captured.update(kwargs)
        raise _CapturedRunWorkflow()

    monkeypatch.setattr(adaptive_mod, "run_workflow", _capture)

    argv = [
        "run_exploration_adaptive.py",
        "--run_name", "test_run",
        "--workspace", workspace,
        "--advice", str(advice_path),
        "--seed_paths", str(seed_path),
        "--max_iterations", "1",
        "--start_iteration", "1",
    ] + list(common_argv)
    monkeypatch.setattr(_sys, "argv", argv)
    args = adaptive_mod.parse_args()

    # Normalize seed_paths (argparse already returns a list); construct the
    # rest of _run_one_iter's positional inputs to mirror what main() would
    # pass on the first iteration.
    from workflows.llm_config import WorkflowLLMConfig
    llm_config = WorkflowLLMConfig.uniform("gemini", "gemini-3.1-pro-preview")
    advice_dict = _json.loads(_Path(advice_path).read_text())
    advice_dict = {
        k: ("\n".join(v) if isinstance(v, list) else v)
        for k, v in advice_dict.items()
    }
    try:
        adaptive_mod._run_one_iter(
            args=args,
            workspace=workspace,
            llm_config=llm_config,
            advice=advice_dict,
            source_paths=[str(seed_path)],
            iteration=1,
        )
    except _CapturedRunWorkflow:
        pass
    return captured


def _capture_one_iter_kwargs(monkeypatch, workspace, seed_path, common_argv):
    """Drive sdsc_submission_scripts.run_one_iteration.main and capture kwargs.

    one-iter's run_workflow call is embedded in main(); we monkey-patch
    run_workflow + restore_prior_state (a no-op at start_iteration=1 anyway,
    but we patch it to avoid filesystem coupling) and let the main flow
    proceed up to the run_workflow call.
    """
    import sdsc_submission_scripts.run_one_iteration as one_iter_mod
    from core.resume import RestoredState
    captured: dict = {}

    def _capture(**kwargs):
        captured.update(kwargs)
        raise _CapturedRunWorkflow()

    def _stub_restore(workspace, current_iter, seed_paths):
        return RestoredState(
            resolved_source_paths=list(seed_paths),
            restored_plugins=[],
            committed_iters=[],
        )

    monkeypatch.setattr(one_iter_mod, "run_workflow", _capture)
    monkeypatch.setattr(one_iter_mod, "restore_prior_state", _stub_restore)

    argv = [
        "run_one_iteration.py",
        "--workspace", workspace,
        "--seed_paths", str(seed_path),
        "--start_iteration", "1",
    ] + list(common_argv)
    monkeypatch.setattr(_sys, "argv", argv)
    try:
        one_iter_mod.main()
    except _CapturedRunWorkflow:
        pass
    return captured


# Common §3.2 flag set fed to both entries verbatim. Every value here is a
# §3.2 contract value at its argparse default (so the test cleanly asserts
# default-flow equivalence). To exercise non-default values, extend this
# list — drift will surface either way.
_COMMON_ARGV = [
    "--max_rounds", "3",
    "--max_proposal_attempts", "3",
    "--max_impl_attempts", "3",
    "--trial_strategy", "snapshot",
    "--trial_portion", "0.1",
    "--train_portion", "0.1",
    "--eval_portion", "0.1",
    "--max_epochs", "1",
    "--formal_strategy", "snapshot",
    "--formal_portion", "0.1",
    "--formal_train_portion", "1.0",
    "--formal_round_strategy", "full_clone",
    "--attempts_per_round", "3",
    "--attempts_per_formal_round", "5",
    "--max_fail_rounds", "3",
    "--exploration_mode", "auto",
    "--minimum_boldness", "0.05",
]


class TestKwargsSnapshotParity:
    """Both entries' run_workflow(**kwargs) must agree on the §3.2 contract.

    Logical exceptions (documented in EXEMPT_KEYS) are subtracted before
    comparison; everything else must be byte-for-byte equal.
    """

    # Layer-specific divergences in the source code. Each entry documents
    # *why* the divergence is logical (not drift) — if any of these stop
    # being acceptable in a future commit, the corresponding caller should
    # be hardened, not the exemption broadened.
    EXEMPT_KEYS = frozenset({
        # Both entries pass max_iterations=1 in the chain-in-process loop,
        # so these match today; the design doc still calls this out as the
        # canonical exception in case adaptive's *non-chain* path (top-level
        # main loop) ever feeds a different value.
        "max_iterations",
        # Both synthesise iter_{N:03d}, but adaptive uses the loop index
        # and one-iter uses --start_iteration; values match when inputs do.
        "run_name",
        # adaptive: literal True; one-iter: `args.is_trial or True`. Same
        # resolved value when --is_trial is unset.
        "is_trial",
        # adaptive: literal True; one-iter: from --cleanup_denoised
        # store_true (default False). Source-level divergence; values
        # diverge unless --cleanup_denoised is also passed.
        "cleanup_denoised",
        # adaptive: constructs {"is_trial": True, "trial_portion": ...} on
        # the fly to forward §3.2 values into the planner override channel;
        # one-iter passes args.plan_overrides through verbatim (None default).
        "plan_overrides",
        # adaptive omits these kwargs entirely (lets run_workflow's
        # signature default apply); one-iter passes args values explicitly.
        # They are §3.2-irrelevant (interpret/validate are agent advice
        # channels, not chain-shape inputs).
        "human_advice_interpret",
        "human_advice_validate",
        # adaptive's main() builds a uniform WorkflowLLMConfig from
        # ("gemini", "gemini-3.1-pro-preview"); one-iter's main() applies a
        # reflector-specific default of "gemini-2.5-flash" when neither
        # --reflect_model_id nor --reflect_provider is set. The values
        # diverge by construction in the no-config-file path. Threading is
        # still asserted by test_every_three_way_flag_is_in_kwargs below.
        "llm_config",
    })

    @pytest.fixture
    def workspace(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        return str(ws)

    @pytest.fixture
    def advice_file(self, tmp_path):
        path = tmp_path / "advice.json"
        path.write_text("{}")
        return path

    @pytest.fixture
    def seed_file(self, tmp_path):
        # Direct-path mode (resolve_source_paths just returns the entry).
        # Contents do not matter for Gate B because run_workflow is stubbed
        # before any record parsing happens.
        path = tmp_path / "seed.json"
        path.write_text(_json.dumps({"records": []}))
        return path

    def test_kwargs_match_modulo_documented_exemptions(
        self, monkeypatch, workspace, advice_file, seed_file
    ):
        adaptive_kwargs = _capture_adaptive_kwargs(
            monkeypatch, workspace, advice_file, seed_file, _COMMON_ARGV,
        )
        one_iter_kwargs = _capture_one_iter_kwargs(
            monkeypatch, workspace, seed_file, _COMMON_ARGV,
        )

        # Both entries should have actually invoked the stub; an empty dict
        # means the entry bailed out before reaching run_workflow.
        assert adaptive_kwargs, "adaptive entry never reached run_workflow"
        assert one_iter_kwargs, "one-iter entry never reached run_workflow"

        a_keys = set(adaptive_kwargs) - self.EXEMPT_KEYS
        o_keys = set(one_iter_kwargs) - self.EXEMPT_KEYS

        diffs = []
        for key in sorted(a_keys | o_keys):
            if key not in adaptive_kwargs:
                diffs.append(
                    f"  {key}: ADAPTIVE missing, one-iter={one_iter_kwargs[key]!r}"
                )
            elif key not in one_iter_kwargs:
                diffs.append(
                    f"  {key}: ONE-ITER missing, adaptive={adaptive_kwargs[key]!r}"
                )
            elif adaptive_kwargs[key] != one_iter_kwargs[key]:
                diffs.append(
                    f"  {key}: adaptive={adaptive_kwargs[key]!r}  "
                    f"one-iter={one_iter_kwargs[key]!r}"
                )
        assert not diffs, (
            "Kwargs drift between adaptive and one-iter (non-exempt keys):\n"
            + "\n".join(diffs)
        )

    def test_every_three_way_flag_is_in_kwargs(
        self, monkeypatch, workspace, advice_file, seed_file
    ):
        """Flags listed in §3.2 must reach run_workflow on both entries.

        Catches the "I added a CLI flag but forgot to thread it" regression
        directly, without requiring a value-mismatch to surface."""
        adaptive_kwargs = _capture_adaptive_kwargs(
            monkeypatch, workspace, advice_file, seed_file, _COMMON_ARGV,
        )
        one_iter_kwargs = _capture_one_iter_kwargs(
            monkeypatch, workspace, seed_file, _COMMON_ARGV,
        )

        # §3.2 flags whose CLI name maps directly to a run_workflow kwarg
        # of the same name. seed_paths → source_paths, llm_config and
        # data_dir/_*_budget_* are conditional emissions, debug_dump_prompts
        # is a store_true that flows directly through.
        EXPECTED_KWARG_NAMES = [
            "max_rounds", "max_proposal_attempts", "max_impl_attempts",
            "trial_strategy", "trial_portion", "train_portion", "eval_portion",
            "max_epochs",
            "formal_strategy", "formal_portion", "formal_train_portion",
            "formal_round_strategy",
            "attempts_per_round", "attempts_per_formal_round", "max_fail_rounds",
            "exploration_mode", "minimum_boldness",
            "debug_dump_prompts",
            "trial_time_budget_minutes", "formal_time_budget_minutes",
            "data_dir",
            "trial_vram_budget_gb", "formal_vram_budget_gb",
            "force_formal_round",
            "target_files", "sampling_seed",
            "llm_config",
        ]
        missing_adaptive = [k for k in EXPECTED_KWARG_NAMES if k not in adaptive_kwargs]
        missing_one_iter = [k for k in EXPECTED_KWARG_NAMES if k not in one_iter_kwargs]
        problems = []
        if missing_adaptive:
            problems.append(
                f"  ADAPTIVE missing kwargs: {sorted(missing_adaptive)}"
            )
        if missing_one_iter:
            problems.append(
                f"  ONE-ITER missing kwargs: {sorted(missing_one_iter)}"
            )
        assert not problems, (
            "§3.2 flag → run_workflow kwarg coverage gap:\n"
            + "\n".join(problems)
        )


# ---------------------------------------------------------------------------
# Gate C — Programmatic Dry-Run Smoke (Phase 6.8 Commit 13.E)
# ---------------------------------------------------------------------------
# `run_chain.sh --dry-run` walks the full per-iter loop without any side
# effects (no mkdir, no python, no sbatch). This pytest invokes it via
# subprocess, parses stdout for the per-iter command blocks, and asserts:
#   - exit code 0
#   - exactly N iter blocks emitted, each with the matching --start_iteration
#   - sdsc mode wires --dependency=afterany:DRYRUN_iter_NNN for iter >= 2
#   - workspace dir stays untouched (does not exist after dry-run)

import subprocess as _subprocess


_RUN_CHAIN_SH = _Path(__file__).resolve().parents[3] / "sdsc_submission_scripts" / "run_chain.sh"


def _run_dry(mode: str, workspace: _Path, num_iters: int, seed_path: _Path):
    """Invoke run_chain.sh in dry-run mode and return (rc, stdout, stderr)."""
    cmd = [
        "bash", str(_RUN_CHAIN_SH),
        "--mode", mode,
        "--dry-run",
        "--workspace", str(workspace),
        "--run_name", "dryrun_test_chain",
        "--num_iterations", str(num_iters),
        "--seed_paths", str(seed_path),
    ]
    proc = _subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    return proc.returncode, proc.stdout, proc.stderr


class TestDryRunSmoke:
    """run_chain.sh --dry-run is the side-effect-free contract: it walks
    the loop, prints the would-be commands, and exits 0 without ever
    touching the workspace or invoking python/sbatch."""

    @pytest.fixture
    def seed_path(self, tmp_path):
        # Any existing file is fine — dry-run does not parse seed contents.
        path = tmp_path / "seed.json"
        path.write_text("{}")
        return path

    @pytest.fixture
    def workspace(self, tmp_path):
        # Deliberately do NOT create the dir — the dry-run side-effect
        # contract is that it stays absent.
        return tmp_path / "dryrun_ws"

    def test_lilab_three_iters_emits_correct_start_iteration(
        self, workspace, seed_path
    ):
        rc, stdout, stderr = _run_dry("lilab", workspace, 3, seed_path)
        assert rc == 0, f"non-zero exit: stdout={stdout!r}\nstderr={stderr!r}"

        # Each iter block should contain the `[DRY-RUN] would exec` marker
        # followed by a command line carrying --start_iteration N.
        for n in (1, 2, 3):
            marker = f"--start_iteration {n} "
            assert marker in stdout, (
                f"--mode lilab dry-run missing iter {n} command line "
                f"({marker!r} not found). stdout=\n{stdout}"
            )
        # The "would exec" header should appear exactly once per iter.
        assert stdout.count("[DRY-RUN] would exec") == 3, (
            "--mode lilab should emit 3 'would exec' markers, "
            f"got {stdout.count('[DRY-RUN] would exec')}. stdout=\n{stdout}"
        )

    def test_lilab_dry_run_leaves_workspace_untouched(
        self, workspace, seed_path
    ):
        assert not workspace.exists(), "fixture invariant: workspace pre-exists"
        rc, _, _ = _run_dry("lilab", workspace, 2, seed_path)
        assert rc == 0
        assert not workspace.exists(), (
            f"--dry-run leaked workspace dir {workspace} — side-effect-free "
            f"contract violated. Contents: "
            f"{list(workspace.iterdir()) if workspace.exists() else None}"
        )

    def test_sdsc_emits_afterany_dependency_for_iter_two_and_three(
        self, workspace, seed_path
    ):
        rc, stdout, stderr = _run_dry("sdsc", workspace, 3, seed_path)
        assert rc == 0, f"non-zero exit: stdout={stdout!r}\nstderr={stderr!r}"

        # Iter 1: no dependency.
        # Iter 2: --dependency=afterany:DRYRUN_iter_001.
        # Iter 3: --dependency=afterany:DRYRUN_iter_002.
        for n in (1, 2, 3):
            assert f"--start_iteration {n} " in stdout, (
                f"--mode sdsc dry-run missing iter {n}. stdout=\n{stdout}"
            )

        assert "--dependency=afterany:DRYRUN_iter_001" in stdout, (
            "iter 2 should depend on DRYRUN_iter_001 placeholder. "
            f"stdout=\n{stdout}"
        )
        assert "--dependency=afterany:DRYRUN_iter_002" in stdout, (
            "iter 3 should depend on DRYRUN_iter_002 placeholder. "
            f"stdout=\n{stdout}"
        )
        # Iter 1 must NOT carry a --dependency on the first sbatch line.
        first_submit = stdout.split("[DRY-RUN] would submit:")[1].split(
            "[DRY-RUN] would submit:"
        )[0]
        assert "--dependency" not in first_submit, (
            "iter 1 should not carry any --dependency flag. "
            f"first_submit_block=\n{first_submit}"
        )

    def test_sdsc_dry_run_leaves_workspace_untouched(
        self, workspace, seed_path
    ):
        assert not workspace.exists(), "fixture invariant: workspace pre-exists"
        rc, _, _ = _run_dry("sdsc", workspace, 2, seed_path)
        assert rc == 0
        assert not workspace.exists(), (
            f"--dry-run --mode sdsc leaked workspace dir {workspace}"
        )
