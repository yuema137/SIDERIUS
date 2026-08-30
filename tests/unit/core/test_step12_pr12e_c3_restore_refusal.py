"""PR-12e C3 — N10: an incompatible package identity refuses the resume.

Design §J row N10, owned by workstream C: *"resume against an incompatible
package identity -> cross-task or edited-package resume -> refused at startup,
by the run-invariants lock, with the recorded mismatch named."*

**Why this is not covered by what already exists.** Both halves are pinned
today, and the joint between them is not:

* ``tests/unit/workflows/test_step10_p1_c1_composition.py`` proves an edited
  plugin moves the semantic fingerprint — in ONE interpreter, comparing two
  compositions this process performed.
* ``tests/unit/workflows/test_step10_p1_c2_consumption.py`` proves the lock
  refuses a changed fingerprint — using two hand-written strings,
  ``"fingerprint-A"`` and ``"fingerprint-B"``.

Neither asks the question N10 asks: does the value a **second, fresh process**
derives from the package on disk reach the lock, and does the lock then refuse?
Every defect on that path is invisible to both — and one of them has already
happened. Step 10 / P5+P6's **W7** was exactly this shape: the chain
pre-flight computed ``task_composition_fingerprint=None`` against a lock that
already held the fingerprint, and *"no test caught it because none drove the
real chain runner under a composition"*.

So each case here runs the composition and the lock call in a **real second
interpreter**, the way iteration 2 does. It is not a substitute for `G-12e`:
these are cheap deterministic witnesses over a fixture package, and the real
package's own witness runs only when the operator points at it.

Registry hygiene is structural rather than fixture-managed: composing an
out-of-tree package registers its id, and the two-phase rule refuses a
re-registration with different content, so an EDITED package cannot be
composed twice in one interpreter at all. Doing this work in subprocesses is
therefore the only honest way to do it — and it is also what production does.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from tests.helpers.step12_pr12e_restore_harness import (
    PACKAGE_ROOT_ENV,
    external_package_manifest,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

#: The in-repo stand-in. `spectro_segmentation_v0` is a COMPOSITION FIXTURE and
#: design §C.3 forbids using it as the graduation vehicle — its name is already
#: burned into the zero-core-edit census. Using it here is the use it was built
#: for: an out-of-tree-shaped package that binds its data path by `file:`, i.e.
#: the family that actually HAS a parent pin (§C.2). The graduation claim is
#: made against workstream A's package via PACKAGE_ROOT_ENV, never against this.
FIXTURE_PACKAGE = REPO_ROOT / "tests" / "fixtures" / "step10_p1" / "fourth_task"

#: The fixture profile declares five partitions; both children must resolve the
#: SAME scope or the lock would refuse over `resolved_data_scope` instead, and
#: the test would pass for the wrong reason.
SCOPE = [0, 1, 2, 3, 4]


def _preflight(manifest: Path, workspace: Path) -> subprocess.CompletedProcess[str]:
    """One iteration's composed pre-flight, in a genuinely fresh interpreter.

    This is the shape ``sdsc_submission_scripts/run_one_iteration.py`` runs
    before any LLM call or training: compose the manifest, build the run
    invariants from the composition, then create-or-validate the workspace lock.
    """
    script = textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {str(REPO_ROOT)!r})

        from core.run_invariants import (
            RunHealthMaterialization,
            RunInvariantsViolation,
            build_run_invariants,
            ensure_run_invariants,
        )
        from workflows.task_composition import compose_run_task_bindings

        composition = compose_run_task_bindings({str(manifest)!r})
        print("FINGERPRINT", composition.semantic_fingerprint)

        invariants, _ = build_run_invariants(
            resolved_data_scope={SCOPE!r},
            health_gate_enabled=False,
            health_gate_files=None,
            health_checks_config=None,
            workspace={str(workspace)!r},
            health_materialization=RunHealthMaterialization(
                task_health_binding=composition.task_health_binding,
            ),
            task_composition_fingerprint=composition.semantic_fingerprint,
        )
        try:
            print("OUTCOME", ensure_run_invariants({str(workspace)!r}, invariants))
        except RunInvariantsViolation as exc:
            print("REFUSED")
            print(exc)
            raise SystemExit(7) from None
    """)
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=300,
    )


def _fingerprint(proc: subprocess.CompletedProcess[str]) -> str:
    for line in proc.stdout.splitlines():
        if line.startswith("FINGERPRINT "):
            return line.split(" ", 1)[1].strip()
    raise AssertionError(
        f"child printed no fingerprint.\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr[-3000:]}"
    )


def _edit_the_data_path_plugin(package: Path) -> None:
    """A content edit to the plugin family that carries a parent pin (§C.2)."""
    plugin = package / "plugins" / "spectro_data_path.py"
    plugin.write_text(
        plugin.read_text(encoding="utf-8")
        + "\n# an edit a digest cannot distinguish from a behavioural one\n",
        encoding="utf-8",
    )


@pytest.fixture
def package(tmp_path: Path) -> Path:
    """A private copy of the fixture package, editable without side effects."""
    root = tmp_path / "pkg"
    shutil.copytree(FIXTURE_PACKAGE, root)
    return root


class TestN10TheLockRefusesAnIncompatiblePackageIdentity:
    def test_an_edited_package_refuses_the_second_iterations_preflight(self, package, tmp_path):
        """N10, end to end and across a real process boundary.

        Defect: iteration 2 composing an EDITED package and being allowed to
        continue iteration 1's workspace. Its records would then be compared
        against a history produced by different code, which is the whole reason
        the fingerprint is a CANONICAL lock field.

        Every link is exercised by production in the child: the composition
        derives the fingerprint from the package on disk, ``build_run_invariants``
        threads it, and ``ensure_run_invariants`` validates. The W7 defect —
        a pre-flight that computed ``None`` here — fails this because the
        refusal would then name a ``None`` on the right-hand side rather than
        the second fingerprint.

        Fails if the edit stops moving the fingerprint, if the pre-flight stops
        threading it, or if the lock stops comparing it.
        """
        workspace = tmp_path / "ws"
        first = _preflight(package / "composition.yaml", workspace)
        assert first.returncode == 0, first.stderr[-3000:]
        assert "OUTCOME created" in first.stdout
        before = _fingerprint(first)

        _edit_the_data_path_plugin(package)

        second = _preflight(package / "composition.yaml", workspace)
        assert second.returncode == 7, (
            "the second iteration's pre-flight was ACCEPTED against a lock "
            f"written before the package was edited.\nstdout:\n{second.stdout}"
        )
        after = _fingerprint(second)
        assert after != before, "the edited package composed to the same identity"

        assert "REFUSED" in second.stdout
        assert "task_composition_fingerprint" in second.stdout
        assert before in second.stdout and after in second.stdout, (
            "the refusal must name BOTH identities — an operator has to see which side moved"
        )

    def test_the_refusal_names_ONLY_the_field_that_drifted(self, package, tmp_path):
        """Defect: a refusal that lists every canonical field, or one that
        names the wrong one. N10's required evidence is *the recorded
        mismatch*; a message naming ``resolved_data_scope`` as well would mean
        the two children disagreed about something else and this whole test
        proved nothing about package identity.

        Fails if the drift computation stops being per-field, or if the two
        pre-flights stop agreeing on scope, ordering, health and runtime
        identities.
        """
        workspace = tmp_path / "ws"
        assert _preflight(package / "composition.yaml", workspace).returncode == 0
        _edit_the_data_path_plugin(package)
        refused = _preflight(package / "composition.yaml", workspace)

        assert refused.returncode == 7
        drifted = [
            line.strip().lstrip("- ").split(":", 1)[0]
            for line in refused.stdout.splitlines()
            if line.strip().startswith("- ")
        ]
        assert drifted == ["task_composition_fingerprint"], refused.stdout

    def test_an_unedited_package_resumes_cleanly(self, package, tmp_path):
        """The positive control, and it is not optional.

        Defect: a fingerprint that varied between two compositions of the SAME
        package — a hash over a dict without ``sort_keys``, a timestamp, an
        absolute path (Q-P1-2). Every honest iteration 2 would then be refused,
        and the test above would pass for exactly that wrong reason.

        Fails if two fresh interpreters composing identical bytes disagree.
        """
        workspace = tmp_path / "ws"
        first = _preflight(package / "composition.yaml", workspace)
        assert first.returncode == 0, first.stderr[-3000:]
        second = _preflight(package / "composition.yaml", workspace)
        assert second.returncode == 0, second.stdout + second.stderr[-3000:]
        assert "OUTCOME validated" in second.stdout
        assert _fingerprint(first) == _fingerprint(second)

    def test_a_DIFFERENT_task_cannot_resume_the_workspace(self, package, tmp_path):
        """The cross-TASK half of N10, distinct from the edited-package half.

        Defect: iteration 2 pointing at another task's manifest and inheriting
        iteration 1's history. Nothing about that is a code edit — the packages
        are both intact — so a refusal keyed on "did a file change" would miss
        it entirely. The lock refuses because the two compositions are not the
        same run.

        Fails if the fingerprint stops covering the task's declared identity.
        """
        workspace = tmp_path / "ws"
        assert _preflight(package / "composition.yaml", workspace).returncode == 0

        other = tmp_path / "other_pkg"
        shutil.copytree(FIXTURE_PACKAGE, other)
        config = other / "declared" / "task_config.yaml"
        config.write_text(
            config.read_text(encoding="utf-8").replace(
                "LOWER is better.", "LOWER is better. A different task entirely."
            ),
            encoding="utf-8",
        )
        refused = _preflight(other / "composition.yaml", workspace)
        assert refused.returncode == 7, refused.stdout
        assert "task_composition_fingerprint" in refused.stdout


class TestTheRealPackage:
    """Runs only when the operator points at workstream A's package.

    The deterministic cases above use the in-repo fixture, which is the honest
    stand-in for the MECHANISM. The graduation claim is about the real
    out-of-tree package, and this is the same N10 assertion aimed at it — still
    deterministic, still no training, still not `G-12e`.
    """

    def test_the_real_package_refuses_a_resume_after_an_edit(self, tmp_path):
        """Defect: the mechanism holding for the fixture but not for the real
        package — a declaration shape the fingerprint does not cover, a plugin
        bound by ``module:`` instead of ``file:`` (and therefore carrying no
        content digest at all), or a manifest whose refs resolve outside the
        copied tree so the edit lands somewhere the composition never reads.

        Fails when the real package's identity does not move on an edit to its
        DECLARED data-path plugin.

        **Why the edit target is read from the manifest.** An earlier version
        edited ``sorted(plugins/*.py)[0]`` and the fingerprint did not move —
        correctly, because that file is a helper the declared plugin IMPORTS
        and ``content_identity`` hashes only the DEFINING module's own source
        (see the finding recorded in the workstream report; not repaired here,
        it is neither this workstream's nor 12d's). Reading
        ``task_data_path.file`` aims the edit at the family §C.2 says actually
        carries a pin, so a pass means what it says.
        """
        import yaml

        manifest = external_package_manifest()
        if manifest is None:
            pytest.skip(
                f"no out-of-tree package configured. Set {PACKAGE_ROOT_ENV} to "
                "workstream A's package root (it lives OUTSIDE this repository "
                "by design, so nothing here may guess its location)."
            )
        source = manifest.parent
        package = tmp_path / "real_pkg"
        shutil.copytree(source, package)
        target = package / manifest.name

        declared = yaml.safe_load(target.read_text(encoding="utf-8"))["task_data_path"].get("file")
        assert declared, (
            f"{manifest} binds its data path by `module:`, which carries no "
            "content digest — the family this test exists for has no pin there"
        )
        plugin = package / declared

        workspace = tmp_path / "ws"
        first = _preflight(target, workspace)
        assert first.returncode == 0, first.stdout + first.stderr[-3000:]
        before = _fingerprint(first)

        plugin.write_text(
            plugin.read_text(encoding="utf-8") + "\n# 12e N10 edit\n", encoding="utf-8"
        )

        second = _preflight(target, workspace)
        assert second.returncode == 7, second.stdout + second.stderr[-3000:]
        assert _fingerprint(second) != before
        assert "task_composition_fingerprint" in second.stdout
