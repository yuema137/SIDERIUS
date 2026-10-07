"""Step 10 / P5+P6 — C4: uninterrupted ≡ resumed, and one writer per value.

Design:
``docs/design/generic_framework_upgrade/step_10_orchestration_task_binding/
pr_10_p5_6_lifecycle_and_three_task_closure.md`` §8.1, §13 C4.

C4 proves the whole point of the lifecycle: **an in-process multi-iteration
trajectory and a stop/restore/continue trajectory produce EQUAL carried state.**

That equality is the reason C2's closure reads the just-written output and C3's
closure applies the projection's own rule instead of re-implementing it. Both
were designed so the two paths agree BY CONSTRUCTION; this module is where that
stops being a design intention and becomes evidence.

The defect class only this module catches: a divergence that appears **only**
across a process boundary. Every other test in this PR drives one trajectory.
A closure that carried state correctly in-process while the projection restored
something subtly different — a different dedup, a different order, a lost
mapping — would pass all of them and still make a real chain disagree with
itself, silently, in a way that changes when a scientific relationship
graduates.

The two trajectories are driven through the SAME production entry point
(``run_workflow``), differing only in how they are cut up:

    A   one call, max_iterations=3
    B   three calls, max_iterations=1, each preceded by a real
        `restore_prior_state` over the digests its predecessors committed
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from agent.schemas.hyperparam_tuning import HyperparamTuningOutput
from core.resume import restore_prior_state
from tests.unit.workflows.test_model_exploration import (
    _make_implementor_output,
    _make_interpretation_output,
    _make_proposal_output,
    _make_tune_output,
    _make_validator_output,
    _write_tuning_output,
)
from tests.unit.workflows.test_step09_5a_c4_single_writer import (
    _bare_local_writes as _real_bare_local_writes,
)
from workflows.llm_config import TunerLLMConfig, WorkflowLLMConfig
from workflows.model_exploration import run_workflow
from workflows.run_config import WorkflowLaunchConfig
from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / "src/workflows" / "model_exploration.py"
RESUME = REPO_ROOT / "src/core" / "resume.py"
QUICKSTART = REPO_ROOT / "configs" / "task_composition" / "quickstart.yaml"

KEY = "dilated_stack:long_range_context"

#: What each iteration's interpreter produces. The confirmations mapping is
#: CUMULATIVE (the producer's real shape); the findings are per-iteration.
PER_ITER = {
    1: {"findings": ["f1"], "confirmations": {KEY: ["run_a"]}},
    2: {"findings": ["f2"], "confirmations": {KEY: ["run_a", "run_b"]}},
    3: {"findings": ["f3"], "confirmations": {KEY: ["run_a", "run_b", "run_c"]}},
}


def _write_manifest(workspace: Path, iter_idx: int) -> None:
    """Commit an iteration the way the CHAIN RUNNER does.

    ``run_workflow`` does not write iteration manifests — ``run_one_iteration``
    does — so a faithful chain trajectory writes them here. Same shape as
    ``tests/unit/core/test_cold_start_resume.py::_commit_iter1``.
    """
    iterdir = workspace / f"iter_{iter_idx:03d}"
    iterdir.mkdir(parents=True, exist_ok=True)
    out_path = iterdir / f"run_output_iter_{iter_idx:03d}_agent.json"
    out_path.write_text(
        HyperparamTuningOutput(
            run_name=f"iter_{iter_idx:03d}",
            model_type="wavenet",
            file_index=6,
            status="completed",
            completed_rounds=1,
            total_attempts=1,
            started_at="2026-01-01T00:00:00Z",
            finished_at="2026-01-01T00:10:00Z",
        ).model_dump_json()
    )
    (iterdir / "manifest.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "iteration_dir": str(iterdir),
                "output_path": str(out_path),
                "model_name": "wavenet",
                "best_score": 0.5,
            }
        )
    )


def _observe(tmp_path, *, iterations, start_iteration, run_name, restored_state, write_digest):
    """One ``run_workflow`` call with the five agent classes stubbed.

    ``write_digest`` makes the interpreter stub persist its output through the
    storage the WORKFLOW handed it — the same path the real interpreter writes,
    resolved from production config rather than hardcoded here.
    """
    observed = {"interp_in": [], "propose_ctx": []}
    composition = compose_run_task_bindings(str(QUICKSTART))

    with (
        patch("workflows.model_exploration.ResultInterpretationAgent") as MockInterp,
        patch("workflows.model_exploration.MLModelProposalAgent") as MockPropose,
        patch("workflows.model_exploration.MLModelImplementor") as MockImpl,
        patch("workflows.model_exploration.MLCodeValidatorAgent") as MockValid,
        patch("workflows.model_exploration.HyperparamTuningAgent") as MockTune,
    ):
        call = {"n": start_iteration - 1}

        def _interp(inp):
            call["n"] += 1
            spec = PER_ITER[call["n"]]
            out = _make_interpretation_output()
            out.key_findings = list(spec["findings"])
            out.vocab_link_confirmations = dict(spec["confirmations"])
            observed["interp_in"].append(
                {
                    "confirmations": dict(inp.vocab_link_confirmations),
                }
            )
            if write_digest:
                # Persist through the storage the WORKFLOW handed us, so the
                # path is resolved from production config rather than
                # hardcoded — this is what the real interpreter node does.
                local = inp.storage.local
                digest_dir = Path(local.workspace)
                digest_dir.mkdir(parents=True, exist_ok=True)
                (digest_dir / f"interpretation_{local.run_name}.json").write_text(
                    out.model_dump_json(), encoding="utf-8"
                )
            return out

        names = iter(
            [f"cand_{i}" for i in range(start_iteration, start_iteration + iterations + 1)]
        )

        def _propose(inp):
            observed["propose_ctx"].append(
                [i.content for i in inp.expert_context if i.kind == "findings"]
            )
            return _make_proposal_output(next(names))

        MockInterp.return_value.run.side_effect = _interp
        MockPropose.return_value.run.side_effect = _propose
        MockImpl.return_value.run.return_value = _make_implementor_output()
        MockValid.return_value.run.return_value = _make_validator_output(passed=True)
        MockTune.return_value.run.side_effect = lambda inp: _make_tune_output(
            model_type=inp.model_type,
            score=1.6,
            fingerprint=composition.semantic_fingerprint,
            metric_spec=composition.metric.spec,
        )

        with bind_run_task_composition(composition, physical_data_root=str(tmp_path / "data")):
            run_workflow(
                llm_config=WorkflowLLMConfig(
                    tune=TunerLLMConfig(planner_strategy="native-timing-v1")
                ),
                launch=WorkflowLaunchConfig(
                    data_dir=str(tmp_path / "data"),
                    model_types=["punet"],
                    source_run_name="v1",
                    max_iterations=iterations,
                    start_iteration=start_iteration,
                ),
                workspace=str(tmp_path / "ws"),
                run_name=run_name,
                restored_state=restored_state,
                task_composition=composition,
            )
    return observed


def _trajectory_uninterrupted(tmp_path):
    """A — one process, three iterations."""
    composition = compose_run_task_bindings(str(QUICKSTART))
    _write_tuning_output(
        tmp_path,
        "punet",
        fingerprint=composition.semantic_fingerprint,
        metric_spec=composition.metric.spec,
    )
    return _observe(
        tmp_path,
        iterations=3,
        start_iteration=1,
        run_name="p56_c4a",
        restored_state=None,
        write_digest=False,
    )


def _trajectory_resumed(tmp_path):
    """B — three processes, each restoring from what its predecessors committed."""
    composition = compose_run_task_bindings(str(QUICKSTART))
    _write_tuning_output(
        tmp_path,
        "punet",
        fingerprint=composition.semantic_fingerprint,
        metric_spec=composition.metric.spec,
    )
    workspace = tmp_path / "ws"
    merged = {"interp_in": [], "propose_ctx": []}

    for n in (1, 2, 3):
        restored = (
            restore_prior_state(str(workspace), current_iter=n, seed_paths=[]) if n > 1 else None
        )
        step = _observe(
            tmp_path,
            iterations=1,
            start_iteration=n,
            run_name=f"iter_{n:03d}",
            restored_state=restored,
            write_digest=True,
        )
        merged["interp_in"].extend(step["interp_in"])
        merged["propose_ctx"].extend(step["propose_ctx"])
        _write_manifest(workspace, n)

    return merged


# ---------------------------------------------------------------------------
# The equality
# ---------------------------------------------------------------------------


class TestUninterruptedEqualsResumed:
    def test_the_carried_confirmations_are_deep_equal(self, tmp_path):
        a = _trajectory_uninterrupted(tmp_path / "a")
        b = _trajectory_resumed(tmp_path / "b")

        assert [x["confirmations"] for x in a["interp_in"]] == [
            x["confirmations"] for x in b["interp_in"]
        ]

    def test_the_carried_findings_are_deep_equal(self, tmp_path):
        a = _trajectory_uninterrupted(tmp_path / "a")
        b = _trajectory_resumed(tmp_path / "b")

        assert a["propose_ctx"] == b["propose_ctx"]

    def test_the_equality_is_not_vacuous(self, tmp_path):
        """Both trajectories must actually have CARRIED something.

        Two runs that each forgot everything would be trivially equal — which
        is exactly the state this PR started from, and exactly what this
        assertion refuses to accept as proof.
        """
        b = _trajectory_resumed(tmp_path / "b")

        # Confirmations really grew across the process boundary.
        assert [x["confirmations"] for x in b["interp_in"]] == [
            {},
            {KEY: ["run_a"]},
            {KEY: ["run_a", "run_b"]},
        ]
        # Findings really accumulated across it.
        assert b["propose_ctx"][0] == []
        assert "- f1" in b["propose_ctx"][1][0]
        assert "- f1" in b["propose_ctx"][2][0] and "- f2" in b["propose_ctx"][2][0]

    def test_the_resumed_trajectory_really_used_the_restore_path(self, tmp_path):
        """Anti-vacuity for the harness itself: iteration 3 of trajectory B
        must have restored state written to DISK by iterations 1 and 2, not
        carried in memory."""
        _trajectory_resumed(tmp_path / "b")
        workspace = tmp_path / "b" / "ws"

        digest = workspace / "iter_002" / "iteration_002" / "interpretation_iter_002.json"
        assert digest.is_file()

        restored = restore_prior_state(str(workspace), current_iter=3, seed_paths=[])
        assert restored.vocab_link_confirmations == {KEY: ["run_a", "run_b"]}
        assert restored.accumulated_key_findings == ["f1", "f2"]


# ---------------------------------------------------------------------------
# Legacy and corrupted restores, end to end
# ---------------------------------------------------------------------------


class TestLegacyAndCorruptedRestores:
    @staticmethod
    def _commit(workspace: Path, iter_idx: int, digest: dict | str) -> None:
        _write_manifest(workspace, iter_idx)
        d = workspace / f"iter_{iter_idx:03d}" / f"iteration_{iter_idx:03d}"
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"interpretation_iter_{iter_idx:03d}.json"
        path.write_text(digest if isinstance(digest, str) else json.dumps(digest), encoding="utf-8")

    def test_a_pre_activation_digest_set_restores_cleanly(self, tmp_path, recwarn):
        """Every digest written before this lifecycle existed lacks the
        confirmations key. Restoring must yield ``{}`` with no fabrication and
        no warning noise, while the findings union — which predates this PR —
        keeps working unchanged."""
        ws = tmp_path / "ws"
        self._commit(ws, 1, {"key_findings": ["legacy one"]})
        self._commit(ws, 2, {"key_findings": ["legacy two"]})

        state = restore_prior_state(str(ws), current_iter=3, seed_paths=[])

        assert state.vocab_link_confirmations == {}
        assert state.accumulated_key_findings == ["legacy one", "legacy two"]
        assert [w for w in recwarn if "vocab-link-confirmations" in str(w.message)] == []

    def test_a_corrupted_confirmations_value_surfaces_through_restore(self, tmp_path):
        """§8.2's raise is not a projection-local detail — it must reach the
        caller through ``restore_prior_state``'s wrapper, exactly as
        ``prediction_memory``'s does. Asserted end-to-end because a wrapper
        that swallowed it would leave the projection's own tests green.
        """
        ws = tmp_path / "ws"
        self._commit(ws, 1, {"vocab_link_confirmations": {KEY: ["run_a"]}})
        self._commit(ws, 2, {"vocab_link_confirmations": "corrupted"})

        with pytest.raises(ValueError) as excinfo:
            restore_prior_state(str(ws), current_iter=3, seed_paths=[])
        assert "promotion state" in str(excinfo.value)

    def test_an_unreadable_digest_does_not_sink_the_restore(self, tmp_path):
        """The other half of the policy: a corrupt FILE is warn-and-skip, so
        one bad artifact does not make a chain unresumable."""
        ws = tmp_path / "ws"
        self._commit(ws, 1, {"vocab_link_confirmations": {KEY: ["run_a"]}})
        self._commit(ws, 2, "{ not json")

        with pytest.warns(UserWarning):
            state = restore_prior_state(str(ws), current_iter=3, seed_paths=[])
        assert state.vocab_link_confirmations == {KEY: ["run_a"]}

    def test_a_resume_re_unioning_the_same_findings_is_idempotent(self, tmp_path):
        """First-occurrence-wins is what makes restoring twice safe."""
        ws = tmp_path / "ws"
        self._commit(ws, 1, {"key_findings": ["shared", "one"]})
        self._commit(ws, 2, {"key_findings": ["shared", "two"]})

        state = restore_prior_state(str(ws), current_iter=3, seed_paths=[])
        assert state.accumulated_key_findings == ["shared", "one", "two"]


# ---------------------------------------------------------------------------
# Single writer / single reader — the planted-offender censuses
# ---------------------------------------------------------------------------


def _bare_local_writes(source: str, names: set[str]) -> dict[str, list[int]]:
    """Plant-friendly wrapper around the REAL Step-09.5a detector.

    An earlier revision reproduced the detector's body here, justified as
    "reproduced rather than imported so that planting an offender into a COPY
    of the function proves the detector bites". That justification does not
    hold: the real detector already takes a parsed `ast.FunctionDef` and never
    touches disk, so planting works fine against it. A second copy only
    creates a body that can drift from the census actually guarding the
    repository — and drift would make these plants pass while the real census
    was broken.

    `names` is honoured by filtering the real detector's output, so a plant can
    still target one specific field.
    """
    fn = next(
        n
        for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.FunctionDef) and n.name == "run_workflow"
    )
    return {name: lines for name, lines in _real_bare_local_writes(fn).items() if name in names}


class TestPlantedOffendersAreCaught:
    """§10 rule 4 for the two NEW values, proven by planting.

    The generic census asserts an absence over the real file; an absence
    passes just as well when the detector is broken. These plant the exact
    offending shape into a copy and require it to be found.
    """

    @pytest.mark.parametrize(
        "field", ["current_vocab_link_confirmations", "accumulated_key_findings"]
    )
    def test_a_second_bare_local_writer_is_detected(self, field):
        planted = (
            "def run_workflow():\n"
            "    state = None\n"
            f"    {field} = []\n"
            f"    state.{field} = {field}\n"
        )
        assert _bare_local_writes(planted, {field}) == {field: [3]}

    @pytest.mark.parametrize(
        "field", ["current_vocab_link_confirmations", "accumulated_key_findings"]
    )
    def test_the_real_workflow_has_no_such_writer(self, field):
        assert _bare_local_writes(WORKFLOW.read_text(encoding="utf-8"), {field}) == {}

    def test_a_second_digest_key_reader_outside_the_projection_is_detected(self):
        """The single-READER half: only ``project_vocab_link_confirmations``
        may pull the key out of a digest payload.

        Planted into a copy of ``core/resume.py``'s source so the detector is
        shown to bite; the real file is asserted clean by
        ``test_step10_p56_c0_broken_lifecycle.py``.
        """
        from tests.unit.workflows.test_step10_p56_c0_broken_lifecycle import (
            _digest_payload_reads,
        )

        clean = RESUME.read_text(encoding="utf-8")
        assert _digest_payload_reads(ast.parse(clean)) == ["project_vocab_link_confirmations"]

        planted = clean + (
            "\n\ndef _a_second_reader(read):\n"
            '    return (read.payload or {}).get("vocab_link_confirmations")\n'
        )
        assert _digest_payload_reads(ast.parse(planted)) == [
            "_a_second_reader",
            "project_vocab_link_confirmations",
        ]
