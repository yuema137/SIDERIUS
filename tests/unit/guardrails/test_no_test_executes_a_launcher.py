"""No test may be capable of starting a real SIDERIUS chain.

On 2026-07-31 a test executed `v19_gate0_pair_runner.sh` directly to
prove that its `main` runs on direct execution. The Gate runner takes no
arguments, so the "proof" performed a real launch: two chains started,
reached lit-review, and made real API calls before being killed.

A PreToolUse hook cannot catch this — it sees the commands Claude runs,
not processes a running pytest spawns. The protection therefore has to be
static, which is what this is.

Scope, stated precisely so nobody trusts it further than it goes: the
scan looks at string content that reaches a SUBPROCESS call, and flags
two things — a launcher path being executed, and a shell fragment that
runs an interpolated path (`bash '{...}'`), which is the exact form the
incident took. It cannot follow a path through arbitrary indirection,
so it is a second line of defence; the first is the source-safe entry
guard in the launchers themselves.

Reading a launcher is fine and necessary: the parity and stop-semantics
suites read these files, source them for their definitions, and check
them with `bash -n`. Only execution is forbidden.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
TESTS_ROOT = REPO_ROOT / "tests"

#: Executing any of these starts real work.
LAUNCHERS = (
    "v19_queue_runner.sh",
    "v19_gate0_pair_runner.sh",
    "v18r_queue_runner.sh",
    "launch_v18_wave1.sh",
    "run_chain.sh",
    "run_one_iteration.py",
    "run_comparison.py",
)

#: Ways a test may legitimately touch a launcher without running it.
SAFE_PREFIXES = (
    "source ",  # load definitions only (guarded by the source-safe entry)
    ". ",
    "bash -n ",  # syntax check
    "cat ",
    "head ",
    "tail ",
    "grep ",
    "sed ",
    "awk ",
    "wc ",
    "sha256sum ",
    "shellcheck ",
)


def _test_files() -> list[Path]:
    return sorted(TESTS_ROOT.rglob("test_*.py"))


#: Anything that hands a command to the OS.
_SPAWNERS = ("run", "Popen", "call", "check_call", "check_output", "system", "getoutput")


def _spawn_calls(tree: ast.AST) -> list[ast.Call]:
    """Calls that execute something, plus the local helpers wrapping them.

    A test that merely MENTIONS a launcher path — to read it, hash it, or
    locate a heredoc with `.index()` — is not executing anything, and a
    guardrail that cannot tell those apart is one that gets switched off.
    """
    calls = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name in _SPAWNERS or name.endswith("_bash") or name == "_bash":
            calls.append(node)
    return calls


def _executed_strings(path: Path) -> list[str]:
    """String content that reaches a spawn call.

    f-strings keep their interpolated EXPRESSIONS rather than a blank
    placeholder, because the expression is what distinguishes the two
    cases: `bash '{LAUNCHERS[name]}'` runs a production launcher, while
    `bash '{script}'` runs a throwaway fixture. A blank `{}` would make
    those identical and the rule useless.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:  # pragma: no cover - a broken test file fails elsewhere
        return []
    out: list[str] = []
    for call in _spawn_calls(tree):
        for node in ast.walk(call):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                out.append(node.value)
            elif isinstance(node, ast.JoinedStr):
                out.append(
                    "".join(
                        part.value
                        if isinstance(part, ast.Constant)
                        else "{" + ast.unparse(part.value) + "}"
                        for part in node.values
                    )
                )
    return out


#: Leading `VAR=value` assignments, which precede the real command.
_ENV_PREFIX = re.compile(r"^(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)+")


def _executes_a_launcher(text: str) -> str | None:
    """The launcher this string would EXECUTE, or None.

    Precision matters more than reach here. A bare mention of a launcher
    filename is NOT execution — tests legitimately name these files to
    read them, hash them, or build a path. Only an explicit execution
    context counts: an interpreter or `./` immediately followed by the
    path. A guardrail that fires on mentions would be turned off within a
    week, and then it protects nothing.
    """
    for launcher in LAUNCHERS:
        if launcher not in text:
            continue
        for fragment in re.split(r"[;&|\n]|&&|\|\|", text):
            if launcher not in fragment:
                continue
            stripped = _ENV_PREFIX.sub("", fragment.strip())
            if any(stripped.startswith(p) for p in SAFE_PREFIXES):
                continue
            # An interpreter or ./ IMMEDIATELY before the path — no
            # intervening token, so `bash -n <launcher>` does not match.
            if re.search(
                r"(?:^|[\s'\"({])(?:bash|sh|python[\d.]*|uv run)\s+['\"]?[^\s'\"]*"
                + re.escape(launcher),
                stripped,
            ) or re.search(r"(?:^|[\s'\"({])\./[^\s'\"]*" + re.escape(launcher), stripped):
                return launcher
    return None


#: `bash '{expr}'` — an interpreter running a computed path. The
#: expression is captured so a launcher variable can be told apart from a
#: fixture path.
_EXECUTES_DYNAMIC = re.compile(
    r"(?:^|[\s'\"({])(?:bash|sh|python[\d.]*|uv run)\s+['\"]?\{([^}]*)\}"
)
#: Names that denote a production launcher.
_LAUNCHER_NAME = re.compile(r"launcher|runner|chain|LAUNCHERS|RUNNER", re.IGNORECASE)


def _executes_a_dynamic_path(text: str) -> bool:
    """The 2026-07-31 form: an interpreter running a LAUNCHER variable.

    `bash '{script}'` against a tmp fixture is fine and common; only a
    path whose expression names a launcher is refused.
    """
    for fragment in re.split(r"[;&|\n]|&&|\|\|", text):
        stripped = _ENV_PREFIX.sub("", fragment.strip())
        if any(stripped.startswith(p) for p in SAFE_PREFIXES):
            continue
        if stripped.startswith("bash -c") or stripped.startswith("bash -n"):
            continue
        match = _EXECUTES_DYNAMIC.search(stripped)
        if match and _LAUNCHER_NAME.search(match.group(1)):
            return True
    return False


#: This module quotes execution forms as TEST DATA; scanning itself would
#: be self-defeating.
SELF = Path(__file__).resolve()


@pytest.mark.parametrize("path", _test_files(), ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_no_test_file_executes_a_production_launcher(path: Path):
    if path.resolve() == SELF:
        pytest.skip("this module quotes execution forms as test data")
    offenders = []
    for literal in _executed_strings(path):
        launcher = _executes_a_launcher(literal)
        if launcher:
            offenders.append((launcher, literal.strip()[:160]))
        elif _executes_a_dynamic_path(literal):
            offenders.append(("<interpolated path>", literal.strip()[:160]))
    assert not offenders, (
        f"{path.relative_to(REPO_ROOT)} would EXECUTE a production launcher, "
        "which can start a real chain and make real API calls. Use mocks, a "
        "dry-run mode, a test-only hook, an extracted pure function, or an "
        f"isolated fake command instead. Found: {offenders}"
    )


class TestTheDetectorItself:
    """A guardrail that cannot detect the thing it guards is worse than
    none, so the detector is tested against both directions."""

    @pytest.mark.parametrize(
        "command",
        [
            "bash sdsc_submission_scripts/v19_gate0_pair_runner.sh",
            "bash '{RUNNER}' --unknown-argument",  # the exact 2026-07-31 form
            "./sdsc_submission_scripts/v19_queue_runner.sh",
            "cd /repo && bash sdsc_submission_scripts/run_chain.sh --mode lilab",
            "python sdsc_submission_scripts/run_one_iteration.py",
            "screen -dmS x bash -c 'bash sdsc_submission_scripts/v19_queue_runner.sh'",
        ],
    )
    def test_it_catches_execution(self, command):
        assert _executes_a_launcher(command.replace("{RUNNER}", LAUNCHERS[1]))

    @pytest.mark.parametrize(
        "command",
        [
            "V19_GATE0_NO_MAIN=1 source sdsc_submission_scripts/v19_gate0_pair_runner.sh",
            "source '/repo/sdsc_submission_scripts/v19_queue_runner.sh'; gate_chain_args arch",
            "bash -n sdsc_submission_scripts/run_chain.sh",
            "grep -n vram sdsc_submission_scripts/v19_queue_runner.sh",
            "sha256sum sdsc_submission_scripts/run_chain.sh",
        ],
    )
    def test_it_permits_reading_and_sourcing(self, command):
        assert _executes_a_launcher(command) is None

    @pytest.mark.parametrize(
        "command",
        [
            "bash '{LAUNCHERS[name]}' --unknown-argument",  # the incident, exactly
            "bash {RUNNER}",
            "sh '{self.RUNNER}'",
            "bash '{GATE_RUNNER}'",
        ],
    )
    def test_it_catches_an_interpolated_path(self, command):
        assert _executes_a_dynamic_path(command)

    @pytest.mark.parametrize(
        "command",
        [
            "source '{LAUNCHERS[name]}'; echo SOURCED_OK",
            "V19_GATE0_NO_MAIN=1 source '{RUNNER}'; gate_chain_args arch",
            "bash -n '{RUNNER}'",
            "bash -c 'echo hello'",
            "bash '{script}' '{tmp_path}'",  # a throwaway fixture, not a launcher
        ],
    )
    def test_it_permits_sourcing_an_interpolated_path(self, command):
        assert not _executes_a_dynamic_path(command)

    def test_a_mention_is_not_an_execution(self):
        """`.index("bash .../run_chain.sh")` locates a heredoc; it runs
        nothing, and flagging it would train everyone to ignore this."""
        from pathlib import Path as _P

        parity = REPO_ROOT / "tests/unit/sdsc_submission_scripts/test_c14_gate_v19_parity.py"
        assert "bash sdsc_submission_scripts/run_chain.sh" in _P(parity).read_text()
        assert not [s for s in _executed_strings(parity) if _executes_a_launcher(s)]

    def test_it_scanned_a_meaningful_number_of_files(self):
        assert len(_test_files()) > 100
