"""Shell ↔ Python CLI contract tests (Phase 6.8 Commit 11 §3.8, post-4.3.4).

Validates that ``sdsc_submission_scripts/run_one_iteration.py`` (the chain
runner) and ``sdsc_submission_scripts/_chain_common.sh`` (the shell entry)
agree on the §3.2 flag set: every contract flag has matching name,
default, and type/shape across both layers. Additionally,
``run_chain.sh --dry-run`` is exercised end-to-end as a side-effect-free
smoke.

Historical note: pre-4.3.4 this file asserted three-way parity across the
legacy in-process runner, the chain runner, and the shell entry. Commit
4.3.4 retired the legacy runner; the surviving contract is shell ↔ chain.
The §3.2 / §3.8 references in-line below remain authoritative.
"""

from __future__ import annotations

import re
import subprocess as _subprocess
from pathlib import Path as _Path

import pytest

from sdsc_submission_scripts.run_one_iteration import (
    build_parser as _roi_build_parser,
)

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


def _get_roi_flags():
    """Get flags from run_one_iteration.py's build_parser()."""
    return _extract_flags(_roi_build_parser())


# ---------------------------------------------------------------------------
# TestShellDefaults — pure shell-side checks against _chain_common.sh
# ---------------------------------------------------------------------------


class TestShellDefaults:
    """Verify _chain_common.sh variable defaults match the chain runner."""

    SHELL_PATH = "sdsc_submission_scripts/_chain_common.sh"

    def _read_shell(self):
        with open(self.SHELL_PATH) as f:
            return f.read()

    def test_max_rounds_default(self):
        content = self._read_shell()
        assert re.search(r"^MAX_ROUNDS=3\b", content, re.MULTILINE), (
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
# Shell ↔ Python CLI contract (Phase 6.8 Commit 13.E, post-4.3.4)
# ---------------------------------------------------------------------------
# For each §3.2 contract flag, asserts:
#   1. Name parity: the long-form flag exists as a `case` arm in
#      parse_chain_args.
#   2. Default parity: the top-of-file `VAR_NAME=value` default, when
#      normalized, matches the chain runner's argparse default.
#   3. Type parity: the case-arm handler shape (scalar / boolean / list)
#      matches the Python action's nargs/action contract.
# Drift on any single property fails the test with a human-readable
# multi-line diff naming the source of disagreement.

# §3.2 contract subset — flags that the chain shell wrapper must mirror.
# Excludes Python-only flags like --force_formal_round (per-iter planner
# concern, not per-chain).
CONTRACT_FLAGS = [
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
    # Stage 3 / Commit 4.5 — pseudo-mode flags
    "is_pseudo_llm",
    "is_pseudo_training",
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
    # Top-level scalar/array assignments only — not inside functions.
    # Stop at the first function definition.
    head = re.split(r"^\s*\w+\(\)\s*\{", content, maxsplit=1, flags=re.MULTILINE)[0]
    for line in head.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([A-Z_][A-Z0-9_]*)=(.*)$", line)
        if not m:
            continue
        name, raw = m.group(1), m.group(2)
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
    m = re.search(
        r"parse_chain_args\(\)\s*\{(.*?)^\}",
        content,
        re.MULTILINE | re.DOTALL,
    )
    if not m:
        return {}
    body = m.group(1)

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
    inner = raw
    if (inner.startswith('"') and inner.endswith('"')) or (
        inner.startswith("'") and inner.endswith("'")
    ):
        inner = inner[1:-1]
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
        if action.nargs == "?":
            return "scalar"
        return "list"
    return "scalar"


class TestShellPythonConsistency:
    """§3.2 contract enforced across the chain runner's argparse and the
    shell entry's parse_chain_args. Each test produces an aggregated
    multi-line diff if any flag drifts on any property."""

    def _gather(self):
        roi = _get_roi_flags()
        shell_content = _read_shell()
        shell_defaults = _parse_shell_defaults(shell_content)
        shell_arms = _parse_shell_case_arms(shell_content)
        return roi, shell_defaults, shell_arms

    def test_shell_arms_exist_for_every_contract_flag(self):
        """Every §3.2 flag has a `--<flag>)` arm in parse_chain_args."""
        _, _, shell_arms = self._gather()
        missing = [f for f in CONTRACT_FLAGS if f not in shell_arms]
        assert not missing, "Missing parse_chain_args arms in _chain_common.sh:\n" + "\n".join(
            f"  --{f}" for f in missing
        )

    def test_shell_default_block_contains_every_var(self):
        """Every §3.2 flag has a top-of-file VAR default declaration."""
        _, shell_defaults, _ = self._gather()
        missing = [f for f in CONTRACT_FLAGS if _shell_var_name(f) not in shell_defaults]
        assert not missing, "Missing top-of-file defaults in _chain_common.sh:\n" + "\n".join(
            f"  {_shell_var_name(f)}=  (for --{f})" for f in missing
        )

    def test_shell_python_default_parity(self):
        """Every §3.2 flag has matching default across chain runner and shell."""
        roi, shell_defaults, shell_arms = self._gather()
        diffs = []
        for flag in CONTRACT_FLAGS:
            python_default = roi.get(flag, {}).get("default", "<MISSING>")
            shell_var = _shell_var_name(flag)
            shell_raw = shell_defaults.get(shell_var, "<MISSING>")
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
            shape = shell_arms.get(flag)
            if shape == "boolean" and isinstance(shell_norm, int):
                shell_norm = bool(shell_norm)
            if shell_norm != python_default:
                diffs.append(
                    f"--{flag}: python={python_default!r}  shell={shell_norm!r} (raw={shell_raw!r})"
                )
        assert not diffs, "Default-value drift between chain runner and shell:\n" + "\n".join(
            f"  {d}" for d in diffs
        )

    def test_shell_python_type_parity(self):
        """Every §3.2 flag's shell handler shape matches the python action shape."""
        _, _, shell_arms = self._gather()
        diffs = []
        roi_parser = _roi_build_parser()
        roi_actions = {
            s.lstrip("-"): a
            for a in roi_parser._actions
            for s in a.option_strings
            if s.startswith("--")
        }
        for flag in CONTRACT_FLAGS:
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
        assert not diffs, "Type/shape drift between chain runner and shell:\n" + "\n".join(
            f"  {d}" for d in diffs
        )


# ---------------------------------------------------------------------------
# TestDryRunSmoke — run_chain.sh --dry-run end-to-end
# ---------------------------------------------------------------------------
# `run_chain.sh --dry-run` walks the full per-iter loop without any side
# effects (no mkdir, no python, no sbatch). This pytest invokes it via
# subprocess, parses stdout for the per-iter command blocks, and asserts:
#   - exit code 0
#   - exactly N iter blocks emitted, each with the matching --start_iteration
#   - sdsc mode wires --dependency=afterany:DRYRUN_iter_NNN for iter >= 2
#   - workspace dir stays untouched (does not exist after dry-run)


_RUN_CHAIN_SH = _Path(__file__).resolve().parents[3] / "sdsc_submission_scripts" / "run_chain.sh"


def _run_dry(mode: str, workspace: _Path, num_iters: int, seed_path: _Path):
    """Invoke run_chain.sh in dry-run mode and return (rc, stdout, stderr)."""
    cmd = [
        "bash",
        str(_RUN_CHAIN_SH),
        "--mode",
        mode,
        "--dry-run",
        "--workspace",
        str(workspace),
        "--run_name",
        "dryrun_test_chain",
        "--num_iterations",
        str(num_iters),
        "--seed_paths",
        str(seed_path),
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

    def test_lilab_three_iters_emits_correct_start_iteration(self, workspace, seed_path):
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
        assert stdout.count("[DRY-RUN] would exec") == 3, (
            "--mode lilab should emit 3 'would exec' markers, "
            f"got {stdout.count('[DRY-RUN] would exec')}. stdout=\n{stdout}"
        )

    def test_lilab_dry_run_leaves_workspace_untouched(self, workspace, seed_path):
        assert not workspace.exists(), "fixture invariant: workspace pre-exists"
        rc, _, _ = _run_dry("lilab", workspace, 2, seed_path)
        assert rc == 0
        assert not workspace.exists(), (
            f"--dry-run leaked workspace dir {workspace} — side-effect-free "
            f"contract violated. Contents: "
            f"{list(workspace.iterdir()) if workspace.exists() else None}"
        )

    def test_sdsc_emits_afterany_dependency_for_iter_two_and_three(self, workspace, seed_path):
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
            f"iter 2 should depend on DRYRUN_iter_001 placeholder. stdout=\n{stdout}"
        )
        assert "--dependency=afterany:DRYRUN_iter_002" in stdout, (
            f"iter 3 should depend on DRYRUN_iter_002 placeholder. stdout=\n{stdout}"
        )
        # Iter 1 must NOT carry a --dependency on the first sbatch line.
        first_submit = stdout.split("[DRY-RUN] would submit:")[1].split("[DRY-RUN] would submit:")[
            0
        ]
        assert "--dependency" not in first_submit, (
            f"iter 1 should not carry any --dependency flag. first_submit_block=\n{first_submit}"
        )

    def test_sdsc_dry_run_leaves_workspace_untouched(self, workspace, seed_path):
        assert not workspace.exists(), "fixture invariant: workspace pre-exists"
        rc, _, _ = _run_dry("sdsc", workspace, 2, seed_path)
        assert rc == 0
        assert not workspace.exists(), f"--dry-run --mode sdsc leaked workspace dir {workspace}"
