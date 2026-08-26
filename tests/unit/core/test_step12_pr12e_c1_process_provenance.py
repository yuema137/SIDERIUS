"""PR-12e C1 — process provenance is REAL, and an in-process shortcut fails it.

Design §K, the restore contract. `G-12e` is 2x1 rather than 1x1 because the
graduation claim includes *"iteration 2 ran in a genuinely FRESH process"*, and
the contract says in as many words that **the CLI's iteration counter is not
evidence**.

Every test here names a defect that would let a NON-restart be reported as a
restart. That failure mode is not hypothetical: today
``scripts/step12_pr12a_gate2_evaluate.py::check_a1`` infers the restart
circumstantially, and
``tests/unit/workflows/test_step10_p56_c4_resume_equality.py`` makes two
IN-PROCESS ``run_workflow`` calls while describing a defect class that "appears
only across a process boundary". Both are honest; neither is a witness. The
assertions below are written so that either of those shapes FAILS them.

What is NOT claimed here: nothing in this module proves that a real chain
restored real state. That is `G-12e`'s, and `G-12e` has not run.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from tests.helpers.step12_pr12e_restore_harness import (
    PROVENANCE_BASENAME,
    CheckOutcome,
    ProcessIdentity,
    ProcessLedgerEntry,
    RestoreEvidenceError,
    assert_fresh_process,
    evaluate_restore_contract,
    interpreter_nonce,
    provenance_path,
    read_process_ledger,
    read_restore_evidence,
    record_iteration_process,
    same_interpreter,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
HARNESS_SOURCE = REPO_ROOT / "tests" / "helpers" / "step12_pr12e_restore_harness.py"


def _child(script: str, *, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    """Run a short script in a genuinely fresh interpreter of THIS checkout."""
    body = f"import sys; sys.path.insert(0, {str(REPO_ROOT)!r})\n" + textwrap.dedent(script)
    return subprocess.run(
        [sys.executable, "-c", body],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=timeout,
    )


# ======================================================================
# The discriminator itself
# ======================================================================


class TestTheNonceIsPerInterpreterNotPerImport:
    def test_a_second_import_under_a_new_name_reuses_the_nonce(self):
        """Defect: a module-level ``uuid4()`` is per-IMPORT, not per-process.

        One interpreter that imports the harness twice — a package rename, a
        ``runpy`` execution, a plugin loader's ``spec_from_file_location`` —
        would then hand out two nonces, and an in-process "iteration 2" would
        report itself FRESH. §K's central check would pass on the exact
        shortcut it exists to catch.

        Fails when the nonce moves back to module scope: the second import
        produces a different nonce and ``same_interpreter`` returns False.
        """
        spec = importlib.util.spec_from_file_location(
            "step12_pr12e_restore_harness__second_copy", HARNESS_SOURCE
        )
        assert spec is not None and spec.loader is not None
        second = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = second
        try:
            spec.loader.exec_module(second)
            assert second is not sys.modules["tests.helpers.step12_pr12e_restore_harness"]
            assert second.interpreter_nonce() == interpreter_nonce()
            assert same_interpreter(ProcessIdentity.current(), second.ProcessIdentity.current())
        finally:
            sys.modules.pop(spec.name, None)

    def test_a_fresh_interpreter_gets_a_different_nonce(self):
        """Defect: a nonce derived from anything a child inherits — an
        environment variable, the hostname, the executable path — makes two
        genuinely separate processes indistinguishable, and every real restore
        would be reported as an in-process continuation.

        Fails when the nonce becomes inheritable: the child prints the parent's
        value and the inequality assertion trips.
        """
        proc = _child("""
            from tests.helpers.step12_pr12e_restore_harness import interpreter_nonce
            print("NONCE", interpreter_nonce())
        """)
        assert proc.returncode == 0, proc.stderr[-3000:]
        child_nonce = proc.stdout.strip().splitlines()[-1].split()[1]
        assert child_nonce != interpreter_nonce()


class TestSameInterpreterDecides:
    @pytest.mark.filterwarnings("ignore:This process .* is multi-threaded")
    def test_a_fork_is_a_continuation_even_though_its_pid_differs(self):
        """Defect: a freshness rule keyed on ``(pid, start_time)`` alone accepts
        a FORK — and a forked "iteration 2" inherits the parent's entire heap,
        so it never re-read the committed state that §K requires it to consume.
        A `multiprocessing`-based "restart" is exactly this shape.

        Fails when the nonce criterion is dropped from ``same_interpreter``:
        the fork's pid and start ticks differ, so the remaining triple says
        "distinct" and this assertion trips.
        """
        read_fd, write_fd = os.pipe()
        pid = os.fork()
        if pid == 0:  # pragma: no cover - the child never reports to pytest
            try:
                os.close(read_fd)
                payload = ProcessIdentity.current().model_dump_json().encode("utf-8")
                os.write(write_fd, payload)
                os.close(write_fd)
            finally:
                os._exit(0)
        os.close(write_fd)
        chunks: list[bytes] = []
        while True:
            block = os.read(read_fd, 4096)
            if not block:
                break
            chunks.append(block)
        os.close(read_fd)
        os.waitpid(pid, 0)

        forked = ProcessIdentity.model_validate_json(b"".join(chunks).decode("utf-8"))
        mine = ProcessIdentity.current()
        assert forked.pid != mine.pid
        assert same_interpreter(mine, forked) is True
        with pytest.raises(RestoreEvidenceError, match="interpreter nonce"):
            assert_fresh_process(mine, forked)

    def test_two_real_processes_are_accepted(self):
        """Defect: a freshness rule so strict that no real chain can satisfy it
        (comparing hostnames, executables, or wall-clock times) turns every
        honest restore into a FAIL, and the Gate gets retried instead of read.

        Fails if ``same_interpreter`` starts returning True for two separately
        launched interpreters.
        """
        identities = []
        for _ in range(2):
            proc = _child("""
                from tests.helpers.step12_pr12e_restore_harness import ProcessIdentity
                print(ProcessIdentity.current().model_dump_json())
            """)
            assert proc.returncode == 0, proc.stderr[-3000:]
            identities.append(
                ProcessIdentity.model_validate_json(proc.stdout.strip().splitlines()[-1])
            )
        assert same_interpreter(*identities) is False
        assert_fresh_process(*identities)  # must not raise

    def test_the_refusal_names_which_criterion_matched(self):
        """Defect: one undifferentiated "not fresh" message. An in-process
        continuation and a literally-identical process call for different
        operator actions (fix the launch vs. you evaluated the same run twice),
        and a message that cannot tell them apart sends the operator to the
        wrong place.

        Fails when the two branches of ``assert_fresh_process`` collapse into
        one message.
        """
        mine = ProcessIdentity.current()
        with pytest.raises(RestoreEvidenceError) as same_process:
            assert_fresh_process(mine, mine)
        assert "literally the same process" in str(same_process.value)

        # Same nonce, different pid: the fork shape, without forking.
        forked = mine.model_copy(update={"pid": mine.pid + 1, "start_ticks": None})
        with pytest.raises(RestoreEvidenceError) as continuation:
            assert_fresh_process(mine, forked)
        assert "interpreter nonce" in str(continuation.value)


# ======================================================================
# The recorder
# ======================================================================


class TestTheRecorderObservesRatherThanAccepts:
    def test_no_caller_can_supply_the_identity(self):
        """Defect: provenance a caller passes in is provenance a caller can
        forge, and the evidence set becomes a restatement of what the launcher
        believed rather than of what executed. This is the discipline
        ``core/runtime_control/session.py`` already follows for
        ``owning_process_pid``.

        Fails the moment an ``identity=`` (or ``pid=``) parameter appears on
        either the recorder or ``ProcessIdentity.current``.
        """
        recorder = inspect.signature(record_iteration_process).parameters
        assert set(recorder) == {"workspace", "iteration", "role"}
        assert list(inspect.signature(ProcessIdentity.current).parameters) == []

    def test_the_recorded_identity_is_this_process(self, tmp_path):
        """Defect: a recorder that stamped the wrong pid — a parent's, a
        subprocess's — would attribute the iteration to a process that did not
        run it, and two iterations could then share one recorded identity.

        Fails when the recorder stops reading ``os.getpid()`` here and now.
        """
        entry = record_iteration_process(tmp_path, 1)
        assert entry.identity.pid == os.getpid()
        assert entry.identity.interpreter_nonce == interpreter_nonce()

    def test_the_ledger_is_append_only_so_a_shortcut_leaves_both_entries(self, tmp_path):
        """Defect: a last-writer-wins provenance file. One interpreter writing
        both iterations would overwrite its own first entry, the reader would
        see exactly one identity per iteration, and the in-process shortcut
        would be invisible — the file having destroyed the evidence against it.

        Fails when the recorder opens the ledger in any mode but append: the
        second read returns one entry and the length assertion trips.
        """
        record_iteration_process(tmp_path, 1)
        record_iteration_process(tmp_path, 2)
        entries = read_process_ledger(tmp_path)
        assert [entry.iteration for entry in entries] == [1, 2]
        assert entries[0].identity.interpreter_nonce == entries[1].identity.interpreter_nonce

    def test_a_corrupt_ledger_is_an_error_not_an_empty_one(self, tmp_path):
        """Defect: swallowing an unparseable line collapses "the recorder never
        ran" and "the recorder wrote garbage" into one passable answer.

        Fails when the reader starts skipping malformed lines.
        """
        Path(provenance_path(tmp_path)).write_text("{not json\n", encoding="utf-8")
        with pytest.raises(RestoreEvidenceError, match=PROVENANCE_BASENAME):
            read_process_ledger(tmp_path)


# ======================================================================
# The §K verdict over a workspace
# ======================================================================


def _workspace(
    tmp_path: Path,
    *,
    fingerprint: str | None = "f" * 64,
    stamped: str | None = "f" * 64,
    iterations: tuple[int, ...] = (1, 2),
    status: str = "completed",
) -> Path:
    """A workspace shaped like a finished chain, with no provenance yet."""
    root = tmp_path / "ws"
    root.mkdir(parents=True, exist_ok=True)
    lock: dict[str, object] = {
        "resolved_data_scope": [0, 1],
        "health_gate_enabled": False,
        "health_config_sha256": None,
        "runtime_estimator_identity": "est-1",
        "runtime_policy_identity": "pol-1",
    }
    if fingerprint is not None:
        lock["task_composition_fingerprint"] = fingerprint
    (root / "run_invariants_lock.json").write_text(json.dumps(lock), encoding="utf-8")
    for index in iterations:
        iter_dir = root / f"iter_{index:03d}"
        iter_dir.mkdir(parents=True, exist_ok=True)
        output = iter_dir / "run_output.json"
        payload: dict[str, object] = {"model_type": "eventseq_ref", "best_denoising_score": -1.0}
        if stamped is not None:
            payload["task_composition_fingerprint"] = stamped
        output.write_text(json.dumps(payload), encoding="utf-8")
        (iter_dir / "manifest.json").write_text(
            json.dumps({"status": status, "output_path": str(output)}), encoding="utf-8"
        )
    return root


def _ledger(root: Path, entries: list[ProcessLedgerEntry]) -> None:
    with open(provenance_path(root), "a", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry.model_dump(mode="json"), sort_keys=True) + "\n")


def _identity(nonce: str, pid: int) -> ProcessIdentity:
    return ProcessIdentity(
        pid=pid, boot_id="boot", start_ticks=pid, interpreter_nonce=nonce, hostname="h"
    )


class TestASimulatedRestartCannotPass:
    def test_one_interpreter_writing_both_iterations_fails_K2(self, tmp_path):
        """THE headline assertion of this workstream. Defect: an evidence set
        that accepts two iterations recorded by ONE interpreter — the shape of
        every in-process "resume" test in the repository, and the shape a
        wrapper that spawned instead of ``runpy``'d would produce.

        Fails (i.e. K2 would wrongly PASS) if ``_check_fresh_process`` stops
        comparing identities pairwise, or if ``same_interpreter`` loses the
        nonce criterion.
        """
        root = _workspace(tmp_path)
        one = _identity("same-nonce", 100)
        _ledger(
            root,
            [
                ProcessLedgerEntry(iteration=1, role="iteration", identity=one),
                ProcessLedgerEntry(
                    iteration=2, role="iteration", identity=_identity("same-nonce", 200)
                ),
            ],
        )
        verdict = evaluate_restore_contract(read_restore_evidence(root))
        assert verdict.named("K2_fresh_process_provenance").outcome is CheckOutcome.FAIL
        assert verdict.passed is False

    def test_two_interpreters_pass_K2(self, tmp_path):
        """The positive control for the test above: without it, a K2 that
        always FAILED would look identical and would be equally green.
        """
        root = _workspace(tmp_path)
        _ledger(
            root,
            [
                ProcessLedgerEntry(iteration=1, role="iteration", identity=_identity("n1", 100)),
                ProcessLedgerEntry(iteration=2, role="iteration", identity=_identity("n2", 200)),
            ],
        )
        verdict = evaluate_restore_contract(read_restore_evidence(root))
        assert verdict.named("K2_fresh_process_provenance").outcome is CheckOutcome.PASS
        assert verdict.passed is True

    def test_absent_provenance_FAILS_rather_than_going_unproven(self, tmp_path):
        """Defect: reporting missing provenance as UNPROVEN and letting the
        verdict pass anyway. §K makes the evidence REQUIRED, so a workspace
        that never recorded it must not be accepted — otherwise the Gate is
        back to inferring the restart from the iteration counter.

        Fails when ``_check_fresh_process`` downgrades the missing case.
        """
        root = _workspace(tmp_path)
        verdict = evaluate_restore_contract(read_restore_evidence(root))
        check = verdict.named("K2_fresh_process_provenance")
        assert check.outcome is CheckOutcome.FAIL
        assert "step12_pr12e_gate_iteration.py" in check.detail
        assert verdict.passed is False


class TestTheVerdictIsNotVacuous:
    def test_zero_stamped_artifacts_fails_K3(self, tmp_path):
        """Defect: "every artifact carrying the stamp carries the right value"
        is trivially true over zero artifacts. This is the anti-vacuity branch
        ``step12_pr12a_gate2_evaluate.py::check_a3`` already carries, and the
        reason it carries it.

        Fails when the ``if not stamped`` branch is removed: the loop over an
        empty list finds no drift and the check PASSes on nothing.
        """
        root = _workspace(tmp_path, stamped=None)
        _ledger(
            root,
            [
                ProcessLedgerEntry(iteration=1, role="iteration", identity=_identity("n1", 100)),
                ProcessLedgerEntry(iteration=2, role="iteration", identity=_identity("n2", 200)),
            ],
        )
        verdict = evaluate_restore_contract(read_restore_evidence(root))
        check = verdict.named("K3_identity_same_value_across_boundary")
        assert check.outcome is CheckOutcome.FAIL
        assert "compares nothing" in check.detail

    def test_a_drifted_stamp_fails_K3(self, tmp_path):
        """Defect: the committed record naming a DIFFERENT composition than the
        lock — the record and the lock disagreeing about which package ran, the
        F-11-C10-a shape one layer out.

        Fails if the comparison is dropped or made non-strict.
        """
        root = _workspace(tmp_path, fingerprint="a" * 64, stamped="b" * 64)
        verdict = evaluate_restore_contract(read_restore_evidence(root))
        assert verdict.named("K3_identity_same_value_across_boundary").outcome is CheckOutcome.FAIL

    def test_an_uncomposed_lock_fails_K1(self, tmp_path):
        """Defect: accepting a run whose lock pins no composition. Such a run
        bound no external package at all, so 'the package identity is the same
        across the boundary' has no subject — and would pass by vacuity.

        Fails when ``_check_committed_state`` stops requiring the fingerprint.
        """
        root = _workspace(tmp_path, fingerprint=None)
        verdict = evaluate_restore_contract(read_restore_evidence(root))
        check = verdict.named("K1_committed_restorable_state")
        assert check.outcome is CheckOutcome.FAIL
        assert "not composed" in check.detail

    def test_an_iteration_that_committed_nothing_fails_K1(self, tmp_path):
        """Defect: treating a ``no_records`` iteration 1 as restorable state.
        Iteration 2 would then have restored nothing while the CLI counter
        still said "2" — precisely the inference §K forbids.

        Fails when the status requirement widens back to the chainable set.
        """
        root = _workspace(tmp_path, status="no_records")
        verdict = evaluate_restore_contract(read_restore_evidence(root))
        assert verdict.named("K1_committed_restorable_state").outcome is CheckOutcome.FAIL

    def test_unproven_never_counts_as_passed(self, tmp_path):
        """Defect: ``passed`` computed as "no FAIL", so a verdict made entirely
        of un-collected evidence reports PASS. Absence of a claim is not a
        satisfied claim — the rule ``validate_stamped_invariants`` follows for
        an unstamped record.

        Fails if ``RestoreVerdict.passed`` is rewritten as ``not any(FAIL)``.
        """
        root = _workspace(tmp_path)
        _ledger(
            root,
            [
                ProcessLedgerEntry(iteration=1, role="iteration", identity=_identity("n1", 100)),
                ProcessLedgerEntry(iteration=2, role="iteration", identity=_identity("n2", 200)),
            ],
        )
        verdict = evaluate_restore_contract(read_restore_evidence(root))
        unproven = [c.name for c in verdict.checks if c.outcome is CheckOutcome.UNPROVEN]
        assert unproven, "the optional seams should report UNPROVEN when unsupplied"
        assert all(not c.required for c in verdict.checks if c.outcome is CheckOutcome.UNPROVEN)
        assert verdict.passed is True  # required checks only

        stripped = verdict.model_copy(
            update={
                "checks": tuple(c.model_copy(update={"required": True}) for c in verdict.checks)
            }
        )
        assert stripped.passed is False


class TestTheSeamWorkstreamBSupplies:
    def test_supplied_identifiers_are_searched_in_the_committed_output(self, tmp_path):
        """Defect: a restore witness that never checks the restored state
        belongs to the DECLARED package. Iteration 1 could have committed a
        TIDMAD run and iteration 2 restored it, and every fingerprint check
        would still agree with itself.

        C consumes workstream B's identifier extraction read-only (design §G.3)
        and implements no copy of it; this is the parameter that seam feeds.

        Fails when the search stops reading iteration 1's committed text.
        """
        root = _workspace(tmp_path)
        evidence = read_restore_evidence(root)
        hit = evaluate_restore_contract(evidence, package_identifiers=["eventseq_ref"])
        assert (
            hit.named("K3b_declared_package_named_in_committed_state").outcome is CheckOutcome.PASS
        )

        miss = evaluate_restore_contract(evidence, package_identifiers=["some_other_task"])
        assert (
            miss.named("K3b_declared_package_named_in_committed_state").outcome is CheckOutcome.FAIL
        )

    def test_an_empty_identifier_set_is_refused_not_satisfied(self, tmp_path):
        """Defect: an extraction helper that returned ``[]`` would make the
        check match every run. An empty set is a broken input, not a satisfied
        condition — the same reasoning as the K3 anti-vacuity branch.

        Fails if the empty case is folded into the "not supplied" branch.
        """
        verdict = evaluate_restore_contract(
            read_restore_evidence(_workspace(tmp_path)), package_identifiers=[]
        )
        check = verdict.named("K3b_declared_package_named_in_committed_state")
        assert check.outcome is CheckOutcome.FAIL
        assert "EMPTY" in check.detail
