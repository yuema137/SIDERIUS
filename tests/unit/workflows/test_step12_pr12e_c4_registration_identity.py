"""PR-12e C4 — which identity actually crosses which boundary.

Design §K bullet 4: *"The identity that crosses is the one CAPTURED at
registration, never a fresh read of the plugin file — the F-12bc-7 lesson. A
test that holds the digest as a string across the boundary would certify
nothing; the assertion must go through the production path."*

12bc already pinned the parent-side invariance
(``tests/unit/workflows/test_step12_pr12bc_c2_identity.py::TestThePinIsCapturedNotReRead``)
and this module does not repeat it. Two things it does not say are load-bearing
for 12e, and both are here:

1. **Invariance is not identity.** ``transport_argv`` emitting the same string
   before and after an edit is satisfied by a *constant* — by the qualname-only
   fallback ``content_identity`` returns when it cannot read a source, by an
   empty digest, by any value that simply never moves. ``TestThePinIsCapturedNotReRead``
   cannot see that, because both sides of its comparison are production's own
   output; degrading ``content_identity`` to return the bare qualname leaves all
   four of its cases GREEN (verified by mutation). The assertion below computes
   ``sha256`` of the ORIGINAL bytes in the test and requires production to have
   emitted THAT, and the same mutation turns every case in this module red.

   Stated precisely, because the claim is a narrow one: that mutation is not
   invisible repo-wide — ``TestTheThreeDivergenceCases::test_edited_plugin_BYTES_diverge``
   catches it from the divergence side. What has no guard is the **emission
   site**: nothing else asserts that the value the parent transports is the
   digest of the bytes that were actually loaded.

2. **The registration capture does not cross a process restart.** It lives in
   ``_CONTENT``, which dies with the interpreter, so iteration 2's capture is a
   fresh read of whatever is on disk when iteration 2 registers. §K's two
   boundaries therefore have two different carriers, and confusing them is the
   F-12bc-7 mistake one boundary out: a restore check keyed on the
   registration capture compares two fresh reads and stays green through the
   very edit it exists to catch. The only value that carries iteration 1's
   package identity into iteration 2 is the workspace lock's
   ``task_composition_fingerprint`` (which C3 exercises end to end).
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_PACKAGE = REPO_ROOT / "tests" / "fixtures" / "step10_p1" / "fourth_task"
FIXTURE_ID = "spectro_segmentation_v0"
PLUGIN_MEMBER = "plugins/spectro_data_path.py"


@pytest.fixture
def clean_registry():
    """Retire whatever this test registers, so the roster is unchanged after.

    Uses the overlay's one public mutation path rather than reaching into
    ``_REGISTRY``. Note (design §C.2) that ``run_registration_scope`` has zero
    PRODUCTION callers — this is test hygiene and proves nothing about
    production isolation, which comes structurally from one process per
    iteration.
    """
    from execute_tools import task_data_path as tdp
    from execute_tools.task_registration_scope import retire_registrations

    baseline = frozenset(tdp._REGISTRY)
    yield
    retire_registrations(baseline)


@pytest.fixture
def composed(tmp_path, clean_registry):
    """A composed out-of-tree package, plus the plugin's ORIGINAL bytes."""
    from workflows.task_composition import compose_run_task_bindings

    root = tmp_path / "pkg"
    shutil.copytree(FIXTURE_PACKAGE, root)
    plugin = root / PLUGIN_MEMBER
    original = plugin.read_bytes()
    composition = compose_run_task_bindings(str(root / "composition.yaml"))
    return composition, plugin, original


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class TestInvarianceIsNotEnoughTheVALUEMustBeRight:
    def test_the_emitted_identity_is_the_digest_of_the_ORIGINAL_bytes(self, composed):
        """Defect: an identity that survives an edit because it never says
        anything. ``content_identity`` deliberately falls back to the qualname
        alone when it cannot read a source, and that fallback is invariant
        under every possible edit — so a regression into it passes 12bc's
        invariance test while pinning nothing at all.

        The expectation here is computed by the TEST from bytes the test wrote,
        and the value under assertion comes out of the production emitter. That
        is the shape F-12bc-7 requires: never a captured production value
        standing in for a production call.

        Fails when the emitted identity stops carrying the original file's
        content digest — including the silent degradation to a bare qualname.
        """
        from execute_tools.task_data_path import transport_argv

        composition, plugin, original = composed
        plugin.write_bytes(original + b"\n# EDITED AFTER THE PARENT PINNED\n")

        emitted = transport_argv(composition.task_data_path)[3]
        assert f"@{_sha(original)}" in emitted, (
            f"the transported identity {emitted!r} does not carry the digest of "
            "the bytes that were actually loaded"
        )
        assert _sha(plugin.read_bytes()) not in emitted, (
            "the transported identity carries the EDITED file's digest — it is "
            "a re-read, so the pin follows the edit it exists to catch (F-12bc-7)"
        )

    def test_a_re_read_really_would_have_emitted_the_edited_digest(self, composed):
        """The control that keeps the test above from being vacuous.

        Defect: an edit that never landed — a copy that shared inodes, a
        digest computed over a path the composition never read, a fixture whose
        plugin is bound by ``module:`` and therefore has no content digest at
        all. In any of those the assertion above would pass while proving
        nothing, because the two digests were equal to begin with.

        This asserts that production's RE-READING function
        (``content_identity``) does move, so the F-12bc-7 window is genuinely
        open and the emitter is genuinely declining to walk into it.

        Fails if the two digests coincide, i.e. if the scenario is not what it
        claims to be.
        """
        from execute_tools.task_data_path import content_identity

        composition, plugin, original = composed
        plugin.write_bytes(original + b"\n# EDITED AFTER THE PARENT PINNED\n")

        re_read = content_identity(composition.task_data_path)
        assert f"@{_sha(plugin.read_bytes())}" in re_read
        assert _sha(original) not in re_read

    def test_the_child_side_check_refuses_a_parent_that_re_read(self, composed):
        """Defect: verification that compares the child's FRESH read against
        the parent's pin. Both sides would then describe the edited file and
        agree, which is exactly how `G-12bc-C`'s first launch loaded and
        consumed a tampered plugin.

        Stated from the other direction than 12bc's structural check: a parent
        that HAD re-read would have transported the edited digest, and this
        child must refuse it.

        Fails if ``verify_transported_identity`` starts computing a fresh read
        for the comparison.
        """
        from execute_tools.task_data_path import (
            TaskDataPathIdentityError,
            content_identity,
            verify_transported_identity,
        )

        composition, plugin, original = composed
        plugin.write_bytes(original + b"\n# EDITED AFTER THE PARENT PINNED\n")
        impl = composition.task_data_path

        with pytest.raises(TaskDataPathIdentityError) as refusal:
            verify_transported_identity(impl, content_identity(impl))
        message = str(refusal.value)
        assert _sha(original) in message and _sha(plugin.read_bytes()) in message


class TestTheTwoBoundariesHaveTwoDifferentCarriers:
    def test_the_registration_capture_dies_with_the_interpreter(self, tmp_path):
        """Defect: reading the registration capture as the RESTORE-boundary pin.

        ``_CONTENT`` is process state. Iteration 2 registers from disk, so its
        capture describes iteration 2's bytes — an edit between iterations moves
        BOTH sides of any comparison drawn from it, and the check is green
        through the tampering. That is F-12bc-7 exactly, one boundary out, and
        it is a live hazard because a Gate evaluator asking "did the two
        iterations agree on the package identity?" would naturally reach for it.

        Runs each composition in a fresh interpreter, which is also the only way
        to run it: the two-phase rule refuses to re-register an edited package
        in one process.

        Fails if the capture ever became process-independent, at which point
        §K's two boundaries would need re-describing rather than this test
        adjusting.
        """
        import subprocess
        import sys
        import textwrap

        root = tmp_path / "pkg"
        shutil.copytree(FIXTURE_PACKAGE, root)

        def capture() -> str:
            script = textwrap.dedent(f"""
                import sys
                sys.path.insert(0, {str(REPO_ROOT)!r})
                from execute_tools.task_data_path import registered_content_identity
                from workflows.task_composition import compose_run_task_bindings

                print("BEFORE", registered_content_identity({FIXTURE_ID!r}))
                compose_run_task_bindings({str(root / "composition.yaml")!r})
                print("AFTER", registered_content_identity({FIXTURE_ID!r}))
            """)
            proc = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True,
                text=True,
                cwd=str(REPO_ROOT),
                timeout=300,
            )
            assert proc.returncode == 0, proc.stderr[-3000:]
            lines = dict(line.split(" ", 1) for line in proc.stdout.splitlines() if " " in line)
            assert lines["BEFORE"] == "None", (
                "a fresh interpreter already knew this package — nothing from "
                "iteration 1 may be visible to iteration 2 except what is on disk"
            )
            return lines["AFTER"]

        first = capture()
        plugin = root / PLUGIN_MEMBER
        plugin.write_bytes(plugin.read_bytes() + b"\n# EDITED BETWEEN ITERATIONS\n")
        second = capture()

        assert first != second, (
            "the registration capture is identical across a restart and an "
            "edit; if that ever becomes true, §K bullet 4 needs re-describing"
        )
        assert _sha(plugin.read_bytes()) in second, (
            "iteration 2's capture does not describe the bytes iteration 2 "
            "loaded — the capture is neither a pin nor an honest read"
        )
