"""Lane F / F5 (fresh-user witness, 2026-08-26) — source-tree authority.

``resolve_py_cmd`` selects an interpreter; with an editable install the
venv's ``.pth`` finder ALSO selects which checkout's framework source
executes. The repair: ``run_chain.sh`` pins framework source to the
invoking checkout via PYTHONPATH, verifies the pin with the neutral-cwd
import probe (``--tree-only``), and REFUSES the launch when the pin does
not hold. Each test names the defect only it catches; the negative
control is operator-mandated ("a probe that only succeeds on the good
environment without FAILING on the bad one is incomplete").

Portability: no developer checkout path is hardcoded — the foreign/fake
trees are built in ``tmp_path`` and the repo root is derived from this
file's location, per CLAUDE.md's portability rules.

Environment coupling (review C7, stated rather than discovered): the
foreign-resolution tests need ``sys.executable`` to resolve the framework
from ITS OWN environment (site-packages / an editable install) when the
pin points elsewhere — that is what makes "intended != resolved" reachable.
Under a bare interpreter with no framework installed, the probe returns 3
(DEPS-UNAVAILABLE) instead of 4 (FOREIGN) and the hole-closure test goes
RED for an environmental reason, not a code one. CI's interpreter installs
the package, so CI is safe; a bare local venv is the case this note exists
for.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PROBE = REPO_ROOT / "sdsc_submission_scripts" / "_import_resolution_probe.py"
RUN_CHAIN = REPO_ROOT / "sdsc_submission_scripts" / "run_chain.sh"


def _make_fake_framework_tree(root: Path) -> Path:
    """A minimal importable skeleton of the probe's target package."""
    pkg = root / "agent" / "schemas"
    pkg.mkdir(parents=True)
    (root / "agent" / "__init__.py").write_text("")
    (pkg / "__init__.py").write_text("")
    (pkg / "hyperparam_tuning.py").write_text("# fake tree for F5 witness\n")
    return root


def _run_probe(neutral_cwd: Path, intended: Path, *, pythonpath: str | None) -> tuple[int, str]:
    probe_copy = neutral_cwd / "probe.py"
    probe_copy.write_bytes(PROBE.read_bytes())
    env = {"PATH": "/usr/bin:/bin", "HOME": str(neutral_cwd)}
    if pythonpath is not None:
        env["PYTHONPATH"] = pythonpath
    proc = subprocess.run(
        [sys.executable, "probe.py", str(intended), "--tree-only"],
        cwd=str(neutral_cwd),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return proc.returncode, proc.stdout + proc.stderr


def test_pythonpath_pin_outranks_the_interpreter_environment(tmp_path):
    """The repair's load-bearing property — the defect only this catches:
    the pin losing to the venv's editable ``.pth`` finder (or any other
    resolution source), which would make the run_chain guard's PASS a lie.
    Mechanism: a fake framework tree, PYTHONPATH pinned to it, intended =
    the fake tree; the SAME interpreter whose own environment resolves the
    real checkout must import the FAKE module. Fails by: probe exit != 0."""
    fake = _make_fake_framework_tree(tmp_path / "fake_checkout")
    neutral = tmp_path / "neutral"
    neutral.mkdir()
    rc, out = _run_probe(neutral, fake, pythonpath=str(fake))
    assert rc == 0, out
    assert "PASS (tree-only)" in out


def test_probe_fails_on_foreign_resolution_the_negative_control(tmp_path):
    """The operator-mandated NEGATIVE CONTROL — the defect only this
    catches: the probe going blind (succeeding on a bad environment), which
    is how a wrong-checkout launch stays green. Mechanism: intended = a
    fake tree, NO pin to it — the interpreter resolves the real checkout's
    module, which is OUTSIDE the intended tree. Fails by: probe exit == 0,
    or the message not naming the actually-resolved foreign path."""
    fake = _make_fake_framework_tree(tmp_path / "fake_checkout")
    neutral = tmp_path / "neutral"
    neutral.mkdir()
    # Pin to the REAL repo so resolution succeeds somewhere definite even
    # under a non-editable interpreter — the point is intended != resolved.
    rc, out = _run_probe(neutral, fake, pythonpath=str(REPO_ROOT))
    assert rc == 4, out  # the probe's FOREIGN contract code, not a generic 1
    assert "resolves OUTSIDE the intended tree" in out
    assert str(REPO_ROOT) in out, "the refusal must NAME the foreign path it resolved"


def _extract_guard(tmp_path: Path) -> Path:
    """The guard's OWN bytes from run_chain.sh — testing a transcription
    would prove nothing (the test-captures-what-production-recomputes
    lesson, inverted)."""
    text = RUN_CHAIN.read_text()
    start = text.index("enforce_source_tree_authority() {")
    end = text.index("\n}", start) + 2
    guard = tmp_path / "guard.sh"
    guard.write_text(text[start:end])
    return guard


_HARNESS = """#!/bin/bash
set -u
GUARD_FILE="$1"; PROJECT_DIR="$2"; SCRIPT_DIR="$3"
PY_CMD=("$4"); PY_SOURCE="harness"; PY_VENV_ROOT="${5:-}"
source "$GUARD_FILE"
enforce_source_tree_authority
echo "GUARD_RC=0"
"""


def _run_guard(
    tmp_path: Path,
    project_dir: Path,
    *,
    dry_run: bool = False,
    script_dir: Path | None = None,
) -> tuple[int, str]:
    guard = _extract_guard(tmp_path)
    harness = tmp_path / "harness.sh"
    harness.write_text(_HARNESS)
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}
    if dry_run:
        env["DRY_RUN"] = "1"
    proc = subprocess.run(
        [
            "bash",
            str(harness),
            str(guard),
            str(project_dir),
            str(script_dir if script_dir is not None else REPO_ROOT / "sdsc_submission_scripts"),
            sys.executable,
            "",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return proc.returncode, proc.stdout + proc.stderr


def test_guard_passes_and_verifies_on_the_invoking_checkout(tmp_path):
    """The defect only this catches: the guard refusing the LEGITIMATE
    launch (its own checkout, any interpreter) — which would block every
    real chain start. Fails by: exit != 0 or the verified banner absent."""
    rc, out = _run_guard(tmp_path, REPO_ROOT)
    assert rc == 0, out
    assert "PYTHONPATH-pinned, probe-verified" in out
    assert "GUARD_RC=0" in out


def test_guard_refuses_when_the_pin_cannot_hold(tmp_path):
    """THE refusal leg — the defect only this catches: the guard degrading
    to a warning (silent foreign source, the F5 witness's exact exposure)
    when the probe reports the pin did not hold. Mechanism: PROJECT_DIR =
    an empty tree with no framework, so the pin has nothing to serve and
    resolution lands outside it. Fails by: exit == 0, or the refusal text
    missing."""
    empty = tmp_path / "frameworkless_checkout"
    (empty / "sdsc_submission_scripts").mkdir(parents=True)
    rc, out = _run_guard(tmp_path, empty)
    assert rc == 1, out
    assert "SOURCE-TREE AUTHORITY REFUSED" in out
    assert "GUARD_RC=0" not in out, "the guard must exit before the launch proceeds"


def test_run_chain_calls_the_guard_after_env_passthrough():
    """Wiring census — the defect only this catches: the guard existing but
    never running (defined-yet-uncalled, the decoration failure mode).
    Fails by: the call vanishing from the launch sequence or moving before
    the passthrough whose env the probe must see."""
    text = RUN_CHAIN.read_text()
    seq = [
        text.index("resolve_py_cmd\n"),
        text.index("enforce_py_version_guard\n"),
        text.index("setup_py_env_passthrough\n"),
        text.index("enforce_source_tree_authority\n"),
    ]
    assert seq == sorted(seq), "launch sequence out of order"


def _make_depless_tree(root: Path) -> Path:
    """A tree whose framework module exists but cannot import its deps —
    the bare-interpreter quickstart environment, simulated portably."""
    pkg = root / "agent" / "schemas"
    pkg.mkdir(parents=True)
    (root / "agent" / "__init__.py").write_text("")
    (pkg / "__init__.py").write_text("")
    (pkg / "hyperparam_tuning.py").write_text(
        "raise ModuleNotFoundError(\"No module named 'pydantic'\")\n"
    )
    return root


def test_dry_run_allows_only_the_missing_deps_class(tmp_path):
    """The regression the first CI run caught, RE-SCOPED after the
    supervisor's stress-test — the defect only this catches: the guard
    gating the quickstart's published pre-venv DRY-RUN flow (a
    dependency-less interpreter), which cannot execute anything silently:
    a framework call in that env fails loudly. Fails by: exit != 0, or the
    deferred-verification notice absent."""
    depless = _make_depless_tree(tmp_path / "depless_checkout")
    rc, out = _run_guard(tmp_path, depless, dry_run=True)
    assert rc == 0, out
    assert "interpreter lacks framework deps" in out
    assert "GUARD_RC=0" in out


def test_dry_run_still_refuses_foreign_resolution_the_hole_closure(tmp_path):
    """THE hole-closure witness (supervisor stress-test, 2026-08-26): the
    original premise "a dry-run executes no framework source" is FALSE —
    resolve_start_iter runs inspect_run_state.py through PY_CMD whenever
    auto-resume meets an existing workspace, dry-run included. The defect
    only this catches: DRY_RUN=1 becoming a one-flag bypass of the
    foreign-source refusal, letting a dry-run silently execute a foreign
    checkout's inspector. Mechanism: a frameworkless PROJECT_DIR under
    DRY_RUN=1 — resolution lands outside it via the interpreter's own
    environment. Fails by: exit == 0 (the hole reopened)."""
    empty = tmp_path / "frameworkless_checkout"
    (empty / "sdsc_submission_scripts").mkdir(parents=True)
    rc, out = _run_guard(tmp_path, empty, dry_run=True)
    assert rc == 1, out
    assert "SOURCE-TREE AUTHORITY REFUSED" in out
    assert "GUARD_RC=0" not in out


def test_missing_dependencies_refuse_with_the_accurate_cause(tmp_path):
    """The defect only this catches: a dependency-less interpreter (bare
    uv/system python) being refused with the FOREIGN-SOURCE message — the
    wrong diagnosis sends the user chasing checkouts instead of creating a
    venv. Mechanism: a fake tree whose framework module raises
    ModuleNotFoundError, so the probe fails WITHOUT 'resolves OUTSIDE'.
    Fails by: the foreign-source text appearing, or the environment
    refusal missing."""
    fake = tmp_path / "depless_checkout"
    pkg = fake / "agent" / "schemas"
    pkg.mkdir(parents=True)
    (fake / "agent" / "__init__.py").write_text("")
    (pkg / "__init__.py").write_text("")
    (pkg / "hyperparam_tuning.py").write_text(
        "raise ModuleNotFoundError(\"No module named 'pydantic'\")\n"
    )
    rc, out = _run_guard(tmp_path, fake)
    assert rc == 1, out
    assert "LAUNCH ENVIRONMENT REFUSED" in out
    assert "SOURCE-TREE AUTHORITY REFUSED" not in out


def test_probe_classifies_deps_unavailable_as_exit_3(tmp_path):
    """The strict-keying contract's third leg — the defect only this
    catches: the probe collapsing a missing-dependencies failure into a
    generic crash exit, which would make the guard's dry-run relaxation
    unreachable (every pre-venv quickstart dry-run would fail closed).
    Fails by: exit != 3, or the class line absent."""
    depless = _make_depless_tree(tmp_path / "depless_checkout")
    neutral = tmp_path / "neutral"
    neutral.mkdir()
    rc, out = _run_probe(neutral, depless, pythonpath=str(depless))
    assert rc == 3, out
    assert "DEPS-UNAVAILABLE" in out


def test_unclassified_probe_failure_fails_closed_even_on_dry_run(tmp_path):
    """The reviewer's exact check (supervisor, 2026-08-26): is the DRY_RUN
    relaxation keyed STRICTLY on the missing-dependencies cause, or one
    notch wider? The defect only this catches: the relaxation admitting
    the complement-of-foreign — an UNCLASSIFIED probe failure (here: a
    probe that crashes outright) slipping through the dry-run door.
    'Not provably foreign' is not 'provably safe'. Fails by: exit == 0
    under dry-run with a crashing probe."""
    crashing_dir = tmp_path / "script_dir"
    crashing_dir.mkdir()
    (crashing_dir / "_import_resolution_probe.py").write_text(
        "raise RuntimeError('unclassified crash')\n"
    )
    rc, out = _run_guard(
        tmp_path,
        REPO_ROOT,
        dry_run=True,
        script_dir=crashing_dir,
    )
    assert rc == 1, out
    assert "UNCLASSIFIED" in out
    assert "GUARD_RC=0" not in out
