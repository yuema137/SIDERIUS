"""Step 09a — C5: the interpreter's prediction memory is production-reachable.

Design: ``docs/design/generic_framework_upgrade/step_09_interpretation_task_blocks/
pr_09a_interpreter_evidence_ordering.md`` §4.6; parent §0.3 erratum E2, §8;
operator ruling Q-09a-1 = A (NARROW).

The defect this file owns
-------------------------
At the pre-09a anchor NO production path carried or restored
``prediction_outcomes_history`` or ``cumulative_information_gain``. The
workflow's inline ``InterpretationInput(...)`` passed neither, the in-process
loop carried only cache / vocab / fingerprints / proposal, and ``core.resume``
contained neither name. Every production digest's pool therefore held exactly
ONE outcome, and the proposer's "Prediction Track Record" always rendered
``N=1`` — a research-accounting feature that had been silently inert since it
was written.

C4 added the versioned pools. Without C5 they would be dead schema in the same
way: present in the record, never accumulated. So the property under test is
REACHABILITY — that the state actually survives both hops — plus the negative
that C5 stayed inside its ruling.

Scope, verbatim from the ruling: ONLY the four interpreter-owned fields, ONLY
through the EXISTING canonical path. No second store, no second restore path,
no change to latest-wins, chain-incumbent restoration or any other restored
field.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent.schemas.interpretation import PredictionMemory
from core.resume import RestoredState, load_latest_prediction_memory

V2 = "metric_order_signsafe_v2"


def _digest(workspace: Path, iter_idx: int, payload: dict) -> None:
    """Write an interpretation digest exactly where resume looks for it.

    The chain-mode convention is
    ``{workspace}/iter_NNN/iteration_NNN/interpretation_iter_NNN.json``
    (``core/resume.py::_interpretation_path``) — reproduced rather than
    imported so a silent change to the convention fails HERE rather than
    making these tests read a file nobody writes.
    """
    d = workspace / f"iter_{iter_idx:03d}" / f"iteration_{iter_idx:03d}"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"interpretation_iter_{iter_idx:03d}.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def test_the_fixture_writes_where_resume_actually_looks(tmp_path):
    """Anti-vacuity for every test below: if the layout drifted, they would
    all pass by restoring the empty default from a file that was never read."""
    from core.resume import _interpretation_path

    _digest(tmp_path, 1, {})
    assert Path(_interpretation_path(str(tmp_path), 1)).is_file()


def _payload(*, legacy=None, v2=None, legacy_gain=0.0, v2_gain=None) -> dict:
    return {
        "prediction_outcomes_history": legacy or {},
        "prediction_outcomes_by_semantics": {V2: v2} if v2 else {},
        "cumulative_information_gain": legacy_gain,
        "cumulative_information_gain_by_semantics": {V2: v2_gain} if v2_gain else {},
    }


class TestTheRestoreReadsTheCanonicalDigest:
    def test_it_restores_the_four_fields(self, tmp_path):
        _digest(
            tmp_path,
            1,
            _payload(
                legacy={"confirmed": 1, "partial": 0, "refuted": 1},
                v2={"confirmed": 2, "partial": 1, "refuted": 0},
                legacy_gain=0.30,
                v2_gain=0.45,
            ),
        )
        memory = load_latest_prediction_memory(str(tmp_path), current_iter=2, committed_iters=[1])
        assert memory.prediction_outcomes_history == {"confirmed": 1, "partial": 0, "refuted": 1}
        assert memory.prediction_outcomes_by_semantics == {
            V2: {"confirmed": 2, "partial": 1, "refuted": 0}
        }
        assert memory.cumulative_information_gain == 0.30
        assert memory.cumulative_information_gain_by_semantics == {V2: 0.45}

    def test_latest_wins_rather_than_accumulating(self, tmp_path):
        """Each digest already holds the pool AFTER its iteration, so summing
        across iterations would double-count every outcome — the same reason
        the fingerprint-history loader overwrites.

        EVERY carried field is checked, not just the versioned ones. Mutation
        C5-3 (accumulate instead of overwrite) initially survived because this
        case exercised only the v2 pool: a loader that summed the LEGACY dict
        would have restored a fabricated history with no test to catch it.
        """
        _digest(
            tmp_path,
            1,
            _payload(legacy={"confirmed": 1}, v2={"confirmed": 1}, legacy_gain=0.10, v2_gain=0.10),
        )
        _digest(
            tmp_path,
            2,
            _payload(legacy={"confirmed": 2}, v2={"confirmed": 3}, legacy_gain=0.35, v2_gain=0.55),
        )
        memory = load_latest_prediction_memory(
            str(tmp_path), current_iter=3, committed_iters=[1, 2]
        )
        assert memory.prediction_outcomes_history == {"confirmed": 2}, (
            "the legacy pool must be the LATEST digest's value, not the sum (3)"
        )
        assert memory.prediction_outcomes_by_semantics == {V2: {"confirmed": 3}}
        assert memory.cumulative_information_gain == 0.35
        assert memory.cumulative_information_gain_by_semantics == {V2: 0.55}

    def test_a_legacy_digest_restores_v1_only_and_invents_no_v2(self, tmp_path):
        """A digest written before Step 09a has a v1 history and NO v2 history.
        Back-filling one would claim outcomes were produced by a rule that did
        not exist when they were recorded."""
        _digest(
            tmp_path,
            1,
            {
                "prediction_outcomes_history": {"confirmed": 2, "partial": 1, "refuted": 0},
                "cumulative_information_gain": 1.25,
            },
        )
        memory = load_latest_prediction_memory(str(tmp_path), current_iter=2, committed_iters=[1])
        assert memory.prediction_outcomes_history == {"confirmed": 2, "partial": 1, "refuted": 0}
        assert memory.cumulative_information_gain == 1.25
        assert memory.prediction_outcomes_by_semantics == {}
        assert memory.cumulative_information_gain_by_semantics == {}

    def test_a_first_iteration_restores_the_empty_default(self, tmp_path):
        assert (
            load_latest_prediction_memory(str(tmp_path), current_iter=1, committed_iters=[])
            == PredictionMemory()
        )

    def test_a_missing_digest_warns_and_skips(self, tmp_path):
        """FILE-level soft-fail, exactly like every sibling loader:
        availability is best-effort."""
        with pytest.warns(UserWarning, match="prediction-memory carry-over"):
            memory = load_latest_prediction_memory(
                str(tmp_path), current_iter=2, committed_iters=[1]
            )
        assert memory == PredictionMemory()

    def test_an_unreadable_digest_warns_and_skips(self, tmp_path):
        d = tmp_path / "iter_001" / "iteration_001"
        d.mkdir(parents=True)
        (d / "interpretation_iter_001.json").write_text("{not json", encoding="utf-8")
        with pytest.warns(UserWarning, match="cannot read interpretation"):
            assert (
                load_latest_prediction_memory(str(tmp_path), current_iter=2, committed_iters=[1])
                == PredictionMemory()
            )

    def test_a_corrupt_pool_refuses_rather_than_restoring_half_of_it(self, tmp_path):
        """DATA-level refusal, the same split the fingerprint loader makes.

        A partially-restored pool produces an accuracy statistic over an
        unknown denominator — worse than having none, because it still looks
        like a number.
        """
        _digest(tmp_path, 1, {"prediction_outcomes_history": {"confirmed": "not-an-int"}})
        with pytest.raises(ValueError, match="corrupted prediction memory"):
            load_latest_prediction_memory(str(tmp_path), current_iter=2, committed_iters=[1])


class TestTheChainSubprocessForwardsIt:
    """Mutation C5-2 exposed that this hop had NO test at all.

    Deleting `restored_prediction_memory=state.prediction_memory` from
    `run_one_iteration.py` leaves the restore loading state that nothing
    consumes: every core/ test still passes, every workflow test still passes,
    and the carry silently stops at the process boundary — which is precisely
    the pre-09a defect this commit exists to fix.

    Asserted by parsing the call rather than scanning for a substring: a
    substring can be satisfied by a comment (see ledger F-09a-14).
    """

    def _run_workflow_keywords(self) -> dict[str, str]:
        import ast

        source = (
            Path(__file__).resolve().parents[3] / "sdsc_submission_scripts/run_one_iteration.py"
        ).read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(source)):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "run_workflow"
            ):
                return {kw.arg: ast.unparse(kw.value) for kw in node.keywords if kw.arg}
        raise AssertionError("no run_workflow(...) call found in run_one_iteration.py")

    def test_the_restored_memory_is_passed_to_run_workflow(self):
        keywords = self._run_workflow_keywords()
        assert keywords.get("restored_prediction_memory") == "state.prediction_memory"

    def test_it_is_forwarded_beside_its_sibling(self):
        """Anti-vacuity: proves the parse found the REAL call, by checking the
        hop this one was modelled on is in the same dict."""
        keywords = self._run_workflow_keywords()
        assert (
            keywords.get("restored_collapse_fingerprint_history")
            == "state.collapse_fingerprint_history"
        )

    def test_run_workflow_accepts_the_keyword(self):
        """The other half: a forwarded kwarg the callee does not declare is a
        TypeError at runtime, not a silent no-op."""
        import inspect

        from workflows.model_exploration import run_workflow

        assert "restored_prediction_memory" in inspect.signature(run_workflow).parameters


class TestTheScopeStayedNarrow:
    """Q-09a-1's verbatim must-not list, made checkable."""

    def test_exactly_one_new_restored_field(self):
        """MUTATION TARGET: adding a second restored value 'while we're here'.

        The ruling permits ONE. The count is pinned rather than described so
        that widening it is a test failure rather than a review question.
        """
        import dataclasses

        names = {f.name for f in dataclasses.fields(RestoredState)}
        assert "prediction_memory" in names
        # The four carried VALUES live inside the one carrier, not as four
        # separate restored fields.
        assert not names & {
            "prediction_outcomes_history",
            "prediction_outcomes_by_semantics",
            "cumulative_information_gain",
            "cumulative_information_gain_by_semantics",
        }

    def test_the_carrier_holds_exactly_the_four_ruled_fields(self):
        assert set(PredictionMemory.model_fields) == {
            "prediction_outcomes_history",
            "prediction_outcomes_by_semantics",
            "cumulative_information_gain",
            "cumulative_information_gain_by_semantics",
        }

    def test_there_is_exactly_one_prediction_memory_loader(self):
        """No second restore path (the ruling's words). A loader is the shape a
        second path would take."""
        import re

        source = (Path(__file__).resolve().parents[3] / "core/resume.py").read_text(
            encoding="utf-8"
        )
        loaders = re.findall(r"^def (load_[a-z_]*prediction[a-z_]*)\(", source, re.M)
        assert loaders == ["load_latest_prediction_memory"], loaders

    def test_the_digest_remains_the_only_store(self):
        """The carrier is a shape, not a persistence layer: it must not know
        how to write itself anywhere."""
        assert not hasattr(PredictionMemory, "save")
        assert not hasattr(PredictionMemory, "persist")
        source = (Path(__file__).resolve().parents[3] / "core/resume.py").read_text(
            encoding="utf-8"
        )
        loader = source[source.index("def load_latest_prediction_memory") :]
        loader = loader[: loader.index("\ndef ")]
        assert "open(" in loader and 'w"' not in loader, "the loader must only READ"

    def test_the_carrier_is_frozen(self):
        """Restored state that a caller can mutate is a second source of truth
        for the same numbers."""
        memory = PredictionMemory(cumulative_information_gain=1.0)
        with pytest.raises(ValidationError):
            memory.cumulative_information_gain = 2.0
