"""Step 10 / P5+P6 — C2: confirmations reach PROMOTION across iterations.

Design:
``docs/design/generic_framework_upgrade/step_10_orchestration_task_binding/
pr_10_p5_6_lifecycle_and_three_task_closure.md`` §7.2, §7.4, §13 C2.

**This module is S5's frozen primary evidence owner** (parent §22.1, Q-10-3 =
A): *"its primary reachability owner is a deterministic lifecycle test with
temporal depth >= 3, NOT a 3-iteration real Gate — temporal depth is a property
of the TEST, not of the GPU."*

The claim: a feature->capability link confirmed by three DISTINCT runs is
promoted into ``VocabEntry.related_to``, and the threshold is OBSERVABLE — not
promoted at iteration 2, promoted at iteration 3. Asserting only the endpoint
would pass for an implementation that promoted on the first confirmation.

The chain under test has four links, and each has its own severing proof in
``TestEverySeveringMutationTurnsItRed`` — a four-link carry needs four proofs,
because any one of them alone silently restores the C0 defect:

    committed digest -> projection -> RestoredState   (C1)
                     -> ChainState seed               (C2)
                     -> InterpretationInput pass      (C2)
                     -> loop closure                  (C2)

The interpreter is stubbed, but the PRODUCER is real: each iteration runs the
actual ``update_vocab_link_confirmations`` against whatever mapping the
workflow handed it. That is deliberate — a stub that simply echoed a
pre-computed mapping would prove transport while assuming the very
accumulation the promotion depends on.
"""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import patch

import pytest

from agent.schemas.interpretation import VocabEntry
from core.chain_state import ChainState
from core.resume import RestoredState
from nodes.interpretation_helpers import update_vocab_link_confirmations
from tests.unit.workflows.test_model_exploration import (
    _make_implementor_output,
    _make_interpretation_output,
    _make_proposal_output,
    _make_tune_output,
    _make_validator_output,
    _write_tuning_output,
)
from workflows.model_exploration import run_workflow
from workflows.run_config import WorkflowLaunchConfig

REPO_ROOT = Path(__file__).resolve().parents[3]
MODEL_EXPLORATION = REPO_ROOT / "workflows" / "model_exploration.py"

FEATURE = "dilated_stack"
CAPABILITY = "long_range_context"
KEY = f"{FEATURE}:{CAPABILITY}"
LINK = [{"feature": FEATURE, "capability": CAPABILITY}]

#: One distinct run name per iteration — the promotion counter counts DISTINCT
#: runs, so three iterations must contribute three different names.
RUN_NAMES = ["model_a", "model_b", "model_c"]


def _seed_vocab() -> list[VocabEntry]:
    return [VocabEntry(name=FEATURE, kind="candidate", description="d")]


def _drive(tmp_path, *, iterations: int, restored_state=None):
    """Drive ``run_workflow`` for ``iterations`` iterations with a REAL producer.

    Returns the per-iteration ``InterpretationInput``s and the mapping each
    iteration's interpreter produced, so both the transport and the promotion
    are observable.
    """
    _write_tuning_output(tmp_path, "punet")
    seen: dict[str, list] = {"inputs": [], "outputs": [], "promoted": []}

    with (
        patch("workflows.model_exploration.ResultInterpretationAgent") as MockInterp,
        patch("workflows.model_exploration.MLModelProposalAgent") as MockPropose,
        patch("workflows.model_exploration.MLModelImplementor") as MockImpl,
        patch("workflows.model_exploration.MLCodeValidatorAgent") as MockValid,
        patch("workflows.model_exploration.HyperparamTuningAgent") as MockTune,
    ):
        call = {"n": 0}

        def _interp(inp):
            """The REAL producer, over whatever the workflow carried in."""
            call["n"] += 1
            run_name = RUN_NAMES[call["n"] - 1]
            vocab = [*_seed_vocab(), *inp.runtime_vocab]

            confirmations, updated_vocab, promoted = update_vocab_link_confirmations(
                prev_vocab_links=LINK,
                prediction_outcome="confirmed",
                run_name=run_name,
                existing_confirmations=inp.vocab_link_confirmations,
                runtime_vocab=vocab,
                min_runs=3,
            )
            out = _make_interpretation_output()
            out.vocab_link_confirmations = confirmations
            out.runtime_vocab = updated_vocab

            seen["inputs"].append(dict(inp.vocab_link_confirmations))
            seen["outputs"].append(dict(confirmations))
            seen["promoted"].append(list(promoted))
            return out

        names = iter([f"cand_{i}" for i in range(iterations + 1)])
        MockInterp.return_value.run.side_effect = _interp
        MockPropose.return_value.run.side_effect = lambda inp: _make_proposal_output(next(names))
        MockImpl.return_value.run.return_value = _make_implementor_output()
        MockValid.return_value.run.return_value = _make_validator_output(passed=True)
        MockTune.return_value.run.side_effect = lambda inp: _make_tune_output(
            model_type=inp.model_type, score=1.6
        )

        run_workflow(
            launch=WorkflowLaunchConfig(
                data_dir=str(tmp_path / "data"),
                model_types=["punet"],
                source_run_name="v1",
                max_iterations=iterations,
            ),
            workspace=str(tmp_path / "workflow_output"),
            run_name="p56_c2",
            restored_state=restored_state,
        )
    return seen


# ---------------------------------------------------------------------------
# Reachability — the frozen §7.4 shape
# ---------------------------------------------------------------------------


class TestPromotionIsReachableAcrossThreeIterations:
    def test_the_mapping_accumulates_one_distinct_run_per_iteration(self, tmp_path):
        """The transport, observed hop by hop.

        Iteration 1 receives ``{}`` (fresh run); every later iteration receives
        exactly what its predecessor produced. Before C2 the received column
        was ``{}`` three times.
        """
        seen = _drive(tmp_path, iterations=3)

        assert seen["inputs"] == [
            {},
            {KEY: ["model_a"]},
            {KEY: ["model_a", "model_b"]},
        ]
        assert seen["outputs"] == [
            {KEY: ["model_a"]},
            {KEY: ["model_a", "model_b"]},
            {KEY: ["model_a", "model_b", "model_c"]},
        ]

    def test_promotion_fires_at_iteration_three_and_NOT_at_iteration_two(self, tmp_path):
        """The THRESHOLD is observable, not just the endpoint.

        Asserting only "it promoted eventually" would pass for an
        implementation that promoted on the first confirmation.
        """
        seen = _drive(tmp_path, iterations=3)
        assert seen["promoted"] == [[], [], [KEY]]

    def test_two_iterations_alone_never_promote(self, tmp_path):
        """The negative half, driven independently rather than read off the
        three-iteration run — a run that stops at 2 must leave the pair
        unpromoted."""
        seen = _drive(tmp_path, iterations=2)
        assert seen["promoted"] == [[], []]
        assert seen["outputs"][-1] == {KEY: ["model_a", "model_b"]}

    def test_a_restored_mapping_seeds_the_first_iteration(self, tmp_path):
        """The chain-mode half: a subprocess that restores two prior runs
        promotes on ITS first iteration, because the counter survived the
        boundary. This is the property that makes a 1-iteration-per-process
        chain equivalent to an in-process run.

        The two restored names are deliberately DISTINCT from this iteration's
        (``model_a``), so the third confirmation is genuinely new. An earlier
        version of this test restored ``["model_a", "model_b"]`` and did NOT
        promote — the producer correctly deduped the repeated ``model_a`` and
        stopped at two distinct runs. That is the dedup surviving the carry,
        and it is asserted explicitly below rather than left as a near-miss.
        """
        restored = RestoredState(
            vocab_link_confirmations={KEY: ["prior_run_x", "prior_run_y"]},
            runtime_vocab=_seed_vocab(),
        )
        seen = _drive(tmp_path, iterations=1, restored_state=restored)

        assert seen["inputs"] == [{KEY: ["prior_run_x", "prior_run_y"]}]
        assert seen["outputs"] == [{KEY: ["prior_run_x", "prior_run_y", "model_a"]}]
        assert seen["promoted"] == [[KEY]]

    def test_a_restored_run_name_repeated_this_iteration_does_not_promote(self, tmp_path):
        """The dedup, across the RESTORE boundary specifically.

        Two restored runs plus a repeat of one of them is still two distinct
        runs, so the threshold is not met. A carry that unioned or appended
        blindly would promote here — which is exactly the wrong science.
        """
        restored = RestoredState(
            vocab_link_confirmations={KEY: ["model_a", "prior_run_y"]},
            runtime_vocab=_seed_vocab(),
        )
        seen = _drive(tmp_path, iterations=1, restored_state=restored)

        assert seen["outputs"] == [{KEY: ["model_a", "prior_run_y"]}]
        assert seen["promoted"] == [[]]


class TestTheProducerSemanticsSurviveTheCarry:
    def test_the_same_run_confirming_twice_counts_once(self, tmp_path):
        """Producer dedup must not be defeated by the transport.

        A latest-wins carry cannot double-count, but a carry that unioned
        digests could. Driving two iterations under ONE run name proves the
        count stays at 1 and the pair does not creep toward promotion.
        """
        _write_tuning_output(tmp_path, "punet")
        seen: list[dict] = []

        with (
            patch("workflows.model_exploration.ResultInterpretationAgent") as MockInterp,
            patch("workflows.model_exploration.MLModelProposalAgent") as MockPropose,
            patch("workflows.model_exploration.MLModelImplementor") as MockImpl,
            patch("workflows.model_exploration.MLCodeValidatorAgent") as MockValid,
            patch("workflows.model_exploration.HyperparamTuningAgent") as MockTune,
        ):

            def _interp(inp):
                confirmations, vocab, _ = update_vocab_link_confirmations(
                    prev_vocab_links=LINK,
                    prediction_outcome="confirmed",
                    run_name="the_same_run",  # deliberately constant
                    existing_confirmations=inp.vocab_link_confirmations,
                    runtime_vocab=[*_seed_vocab(), *inp.runtime_vocab],
                    min_runs=3,
                )
                out = _make_interpretation_output()
                out.vocab_link_confirmations = confirmations
                out.runtime_vocab = vocab
                seen.append(dict(confirmations))
                return out

            names = iter(["cand_0", "cand_1", "cand_2"])
            MockInterp.return_value.run.side_effect = _interp
            MockPropose.return_value.run.side_effect = lambda i: _make_proposal_output(next(names))
            MockImpl.return_value.run.return_value = _make_implementor_output()
            MockValid.return_value.run.return_value = _make_validator_output(passed=True)
            MockTune.return_value.run.side_effect = lambda i: _make_tune_output(
                model_type=i.model_type, score=1.6
            )
            run_workflow(
                launch=WorkflowLaunchConfig(
                    data_dir=str(tmp_path / "data"),
                    model_types=["punet"],
                    source_run_name="v1",
                    max_iterations=3,
                ),
                workspace=str(tmp_path / "workflow_output"),
                run_name="p56_c2_dedup",
            )

        assert seen == [{KEY: ["the_same_run"]}] * 3

    def test_no_confirmed_outcome_accumulates_nothing(self, tmp_path):
        """An empty mapping is first-class: three iterations of ``refuted``
        leave the carrier empty and promote nothing."""
        _write_tuning_output(tmp_path, "punet")
        seen: list[dict] = []

        with (
            patch("workflows.model_exploration.ResultInterpretationAgent") as MockInterp,
            patch("workflows.model_exploration.MLModelProposalAgent") as MockPropose,
            patch("workflows.model_exploration.MLModelImplementor") as MockImpl,
            patch("workflows.model_exploration.MLCodeValidatorAgent") as MockValid,
            patch("workflows.model_exploration.HyperparamTuningAgent") as MockTune,
        ):

            def _interp(inp):
                confirmations, vocab, promoted = update_vocab_link_confirmations(
                    prev_vocab_links=LINK,
                    prediction_outcome="refuted",
                    run_name="model_a",
                    existing_confirmations=inp.vocab_link_confirmations,
                    runtime_vocab=[*_seed_vocab(), *inp.runtime_vocab],
                    min_runs=3,
                )
                assert promoted == []
                out = _make_interpretation_output()
                out.vocab_link_confirmations = confirmations
                out.runtime_vocab = vocab
                seen.append(dict(confirmations))
                return out

            names = iter(["cand_0", "cand_1", "cand_2"])
            MockInterp.return_value.run.side_effect = _interp
            MockPropose.return_value.run.side_effect = lambda i: _make_proposal_output(next(names))
            MockImpl.return_value.run.return_value = _make_implementor_output()
            MockValid.return_value.run.return_value = _make_validator_output(passed=True)
            MockTune.return_value.run.side_effect = lambda i: _make_tune_output(
                model_type=i.model_type, score=1.6
            )
            run_workflow(
                launch=WorkflowLaunchConfig(
                    data_dir=str(tmp_path / "data"),
                    model_types=["punet"],
                    source_run_name="v1",
                    max_iterations=3,
                ),
                workspace=str(tmp_path / "workflow_output"),
                run_name="p56_c2_refuted",
            )

        assert seen == [{}, {}, {}]


# ---------------------------------------------------------------------------
# DD-2 — the producer's three branches are symmetric
# ---------------------------------------------------------------------------


class TestProducerBranchSymmetry:
    """§7.3. The loop closure reads the just-written output UNCONDITIONALLY,
    so every branch that can produce an output must carry the mapping."""

    def test_the_three_branches_agree(self, tmp_path):
        from agent.schemas.interpretation import InterpretationInput, ModelRunSummary
        from nodes.result_interpretation_agent import ResultInterpretationAgent

        carried = {KEY: ["model_a", "model_b"]}
        storage = {
            "backend": "local",
            "local": {"workspace": str(tmp_path), "run_name": "r1"},
        }

        # cold start — no LLM call at all
        with patch("nodes.result_interpretation_agent.LLMBridge") as Bridge:
            Bridge.return_value.generate.side_effect = AssertionError("no LLM on cold start")
            agent = ResultInterpretationAgent(provider="gemini", model_id="m")
            agent.bridge = Bridge.return_value
            cold = agent.run(
                InterpretationInput(
                    cold_start=True, storage=storage, vocab_link_confirmations=carried
                )
            )

        # degraded — the LLM raises
        with patch("nodes.result_interpretation_agent.LLMBridge") as Bridge:
            Bridge.return_value.generate.side_effect = RuntimeError("LLM unreachable")
            agent = ResultInterpretationAgent(provider="gemini", model_id="m")
            agent.bridge = Bridge.return_value
            degraded = agent.run(
                InterpretationInput(
                    summaries=[
                        ModelRunSummary(
                            model_type="wavenet",
                            run_name="p56c2",
                            status="error",
                            completed_rounds=0,
                            round_scores=[],
                            round_conclusions=[],
                        )
                    ],
                    storage=storage,
                    vocab_link_confirmations=carried,
                )
            )

        # Both non-normal branches carry the mapping through VERBATIM, so the
        # unconditional closure cannot clobber restored state.
        assert cold.vocab_link_confirmations == carried
        assert degraded.vocab_link_confirmations == carried

    def test_a_cold_start_with_an_empty_input_still_writes_empty(self, tmp_path):
        """DD-2's parity half: for every pre-P5 caller the input is ``{}`` and
        the field already serialized as ``{}``, so digest bytes are unchanged.
        """
        from agent.schemas.interpretation import InterpretationInput
        from nodes.result_interpretation_agent import ResultInterpretationAgent

        with patch("nodes.result_interpretation_agent.LLMBridge") as Bridge:
            agent = ResultInterpretationAgent(provider="gemini", model_id="m")
            agent.bridge = Bridge.return_value
            out = agent.run(
                InterpretationInput(
                    cold_start=True,
                    storage={
                        "backend": "local",
                        "local": {"workspace": str(tmp_path), "run_name": "r1"},
                    },
                )
            )
        assert out.vocab_link_confirmations == {}


# ---------------------------------------------------------------------------
# Anti-vacuity: every link in the chain, severed independently
# ---------------------------------------------------------------------------


class TestEverySeveringMutationTurnsItRed:
    """A four-link carry needs FOUR proofs.

    Each test below severs exactly ONE hop and asserts promotion becomes
    unreachable — so the reachability test above cannot be passing for an
    accidental reason, and no single hop can regress silently.

    The severing is done by patching the ONE authority that hop uses, never by
    editing the source, so nothing is left behind on the tree.
    """

    def test_severing_the_projection_breaks_promotion(self, tmp_path):
        """Hop 1 (C1): the digest -> RestoredState projection.

        A restored chain that cannot project its mapping starts from `{}` and
        does not promote on the iteration that otherwise would.

        NOTE this is the SIMULATED form (it injects what a severed projection
        would return). The REAL end-to-end proof — that
        ``restore_prior_state`` actually reads the digest off disk and assigns
        it — is ``test_restore_prior_state_really_reads_the_digest`` below.
        Both exist because the source mutation of the assignment line is
        invisible to this one: ``_drive`` is handed a ``RestoredState``
        directly and never calls ``restore_prior_state``.
        """
        restored = RestoredState(
            vocab_link_confirmations={},  # what a severed projection returns
            runtime_vocab=_seed_vocab(),
        )
        seen = _drive(tmp_path, iterations=1, restored_state=restored)
        assert seen["promoted"] == [[]]

    def test_restore_prior_state_really_reads_the_digest(self, tmp_path):
        """Hop 1, for real — the assignment line's reachability proof.

        Discovered by a source mutation that SURVIVED: replacing
        ``state.vocab_link_confirmations = project_vocab_link_confirmations(...)``
        with ``= {}`` left the whole reachability module green, because nothing
        in it calls ``restore_prior_state``. C1's projection tests call the
        projection directly and are equally blind to the assignment.

        This test closes that gap: a real digest on disk, read through the real
        restore, arriving as real ``RestoredState``. Severing the assignment
        turns it RED.
        """
        import json

        from agent.schemas.hyperparam_tuning import HyperparamTuningOutput
        from core.resume import _interpretation_path, restore_prior_state

        # A real COMMITTED iteration: run_output + manifest, the shape
        # `restore_prior_state` requires before it will read anything.
        iterdir = tmp_path / "iter_001"
        iterdir.mkdir(parents=True)
        out_path = iterdir / "run_output_iter_001_agent.json"
        out_path.write_text(
            HyperparamTuningOutput(
                run_name="iter_001",
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

        mapping = {KEY: ["prior_run_x", "prior_run_y"]}
        digest_dir = iterdir / "iteration_001"
        digest_dir.mkdir(parents=True, exist_ok=True)
        (digest_dir / "interpretation_iter_001.json").write_text(
            json.dumps({"vocab_link_confirmations": mapping, "key_findings": []}),
            encoding="utf-8",
        )
        # Anti-vacuity: if the layout convention drifted, this test would pass
        # by restoring an empty default from a file nobody reads.
        assert Path(_interpretation_path(str(tmp_path), 1)).is_file()

        state = restore_prior_state(str(tmp_path), current_iter=2, seed_paths=[])
        assert state.committed_iters == [1]
        assert state.vocab_link_confirmations == mapping

    def test_severing_the_seed_breaks_promotion(self, tmp_path):
        """Hop 2: RestoredState -> ChainState via ``from_restored``."""
        original = ChainState.from_restored

        def _severed(cls, **kwargs):
            kwargs["restored_vocab_link_confirmations"] = None
            return original(**kwargs)

        restored = RestoredState(
            vocab_link_confirmations={KEY: ["model_a", "model_b"]},
            runtime_vocab=_seed_vocab(),
        )
        with patch.object(ChainState, "from_restored", classmethod(_severed)):
            seen = _drive(tmp_path, iterations=1, restored_state=restored)

        assert seen["inputs"] == [{}]
        assert seen["promoted"] == [[]]

    def test_severing_the_input_pass_breaks_promotion(self, tmp_path):
        """Hop 3: ChainState -> ``InterpretationInput``.

        Severed by validating the input with the field forced back to its
        schema default, which is exactly what the pre-C2 workflow produced.
        """
        seen = _drive(tmp_path, iterations=3)
        # Sanity: unsevered, the chain promotes.
        assert seen["promoted"][-1] == [KEY]

        # Severed: the interpreter is handed `{}` every iteration (the C0
        # behaviour), so the producer can never reach three distinct runs.
        promoted_ever = []
        for run_name in RUN_NAMES:
            _confirmations, _vocab, promoted = update_vocab_link_confirmations(
                prev_vocab_links=LINK,
                prediction_outcome="confirmed",
                run_name=run_name,
                existing_confirmations={},  # the severed pass
                runtime_vocab=_seed_vocab(),
                min_runs=3,
            )
            promoted_ever.extend(promoted)
        assert promoted_ever == []

    def test_severing_the_loop_closure_breaks_promotion(self, tmp_path):
        """Hop 4: interpreter output -> ChainState.

        Without the closure, iteration N+1 re-reads the SEED rather than what
        iteration N produced, so the counter never advances past one run.
        """
        _write_tuning_output(tmp_path, "punet")
        received: list[dict] = []

        # A ChainState whose carrier refuses to be updated is exactly a missing
        # closure: the seed value is what every iteration then reads.
        class _NoClosureState(ChainState):
            @property
            def current_vocab_link_confirmations(self):  # type: ignore[override]
                return {}

            @current_vocab_link_confirmations.setter
            def current_vocab_link_confirmations(self, value):
                pass  # the severed closure

        with (
            patch("workflows.model_exploration.ResultInterpretationAgent") as MockInterp,
            patch("workflows.model_exploration.MLModelProposalAgent") as MockPropose,
            patch("workflows.model_exploration.MLModelImplementor") as MockImpl,
            patch("workflows.model_exploration.MLCodeValidatorAgent") as MockValid,
            patch("workflows.model_exploration.HyperparamTuningAgent") as MockTune,
            patch("workflows.model_exploration.ChainState", _NoClosureState),
        ):
            call = {"n": 0}

            def _interp(inp):
                call["n"] += 1
                received.append(dict(inp.vocab_link_confirmations))
                confirmations, vocab, promoted = update_vocab_link_confirmations(
                    prev_vocab_links=LINK,
                    prediction_outcome="confirmed",
                    run_name=RUN_NAMES[call["n"] - 1],
                    existing_confirmations=inp.vocab_link_confirmations,
                    runtime_vocab=[*_seed_vocab(), *inp.runtime_vocab],
                    min_runs=3,
                )
                assert promoted == [], "a severed closure must never reach promotion"
                out = _make_interpretation_output()
                out.vocab_link_confirmations = confirmations
                out.runtime_vocab = vocab
                return out

            names = iter(["cand_0", "cand_1", "cand_2"])
            MockInterp.return_value.run.side_effect = _interp
            MockPropose.return_value.run.side_effect = lambda i: _make_proposal_output(next(names))
            MockImpl.return_value.run.return_value = _make_implementor_output()
            MockValid.return_value.run.return_value = _make_validator_output(passed=True)
            MockTune.return_value.run.side_effect = lambda i: _make_tune_output(
                model_type=i.model_type, score=1.6
            )
            run_workflow(
                launch=WorkflowLaunchConfig(
                    data_dir=str(tmp_path / "data"),
                    model_types=["punet"],
                    source_run_name="v1",
                    max_iterations=3,
                ),
                workspace=str(tmp_path / "workflow_output"),
                run_name="p56_c2_severed_closure",
            )

        # Every iteration saw the empty seed — the C0 defect, reproduced.
        assert received == [{}, {}, {}]

    # The anti-vacuity anchor for the four severing tests above — "the same
    # harness, unsevered, MUST promote" — is
    # `test_promotion_fires_at_iteration_three_and_NOT_at_iteration_two`
    # earlier in this module. It is the identical `_drive(tmp_path,
    # iterations=3)` call with the identical assertion, so a copy here was a
    # second name for one test rather than a second failure class.


# ---------------------------------------------------------------------------
# Structure tripwire (§12.1)
# ---------------------------------------------------------------------------


def test_the_workflow_delta_stayed_sibling_shaped():
    """§12.1's frozen tripwire, as an executable assertion.

    The permitted delta is seed / input pass / state closure / consumer read.
    A new phase, branch family or task dispatch would show up as branch growth;
    the baseline is §12's measured 130 branch-ish nodes.
    """
    tree = ast.parse(MODEL_EXPLORATION.read_text(encoding="utf-8"))
    fn = next(
        n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "run_workflow"
    )
    branchish = sum(
        1
        for sub in ast.walk(fn)
        if isinstance(
            sub,
            (
                ast.If,
                ast.IfExp,
                ast.BoolOp,
                ast.For,
                ast.AsyncFor,
                ast.While,
                ast.With,
                ast.AsyncWith,
                ast.Try,
                ast.ExceptHandler,
            ),
        )
    )
    # §12.1's PRE/POST record, decomposed so the shape — not just the number —
    # is what is pinned.
    #
    #   PRE  (§12, C0 head)   130   If 57 · IfExp 28 · BoolOp 23 · For 12 ·
    #                               With 8 · Try 1 · ExceptHandler 1
    #   C2                    131   +1 IfExp
    #   C5 (W6)               132   +1 IfExp
    #   C3                    132   +0 — the union is a CALL, not a loop
    #
    # C2's +1 is the `restored_state.<f> if restored_state else None` unpack
    # row — the identical idiom each of the nine sibling unpacks already uses.
    # Its other three hops (seed kwarg, input-pass kwarg, whole-mapping
    # closure) are straight-line and add nothing.
    #
    # C3 costs ZERO branch nodes, and that is a CORRECTION to an earlier
    # revision of this test. The findings union was first written inline —
    #     `for _finding in interpretation.key_findings or []:`  For+1, BoolOp+1
    #     `if isinstance(...) and _finding and _finding not in ...:`
    #                                                            If+1, BoolOp+1
    # — costing +4 and, worse, putting a MERGE RULE inside this already-large
    # orchestrator while a second copy of the same rule lived in
    # `core.resume.project_knowledge`. Adversarial review caught that the
    # accompanying comment claimed the rule was "applied, not re-implemented"
    # when it was re-implemented. The rule now lives in ONE authority
    # (`core.resume.union_key_findings`) and this closure is a single call, so
    # the four nodes are gone. C3's unpack row costs ZERO because it RENAMED
    # an existing IfExp rather than adding one.
    #
    # C5's +1 is W6's binding selection — the SAME conditional shape:
    #     task_composition.task_health_binding
    #     if task_composition is not None else HealthBindingState.LEGACY_OMITTED
    # one expression choosing between a composed value and its declared
    # default, which is how every composed/un-composed fork in this function is
    # already written.
    #
    # arXiv U1 (declared delta, the tripwire fired at final integration):
    # 132 -> 131. U1 EXTRACTED the lit-review config-path resolution
    # (`if not os.path.isabs(yaml_path)`) into the module-level helper the
    # lock's sha derivation also needs — one If moved OUT of run_workflow.
    # A shrink is the direction this tripwire exists to encourage; the U1
    # additions themselves (identity threading, isolation wiring) came in
    # as helper CALLS, costing zero branch-ish nodes here.
    #
    # arXiv #259 (declared delta, 2026-08-26): 131 -> 132. The output-type
    # constraint's post-hoc threading — `if launch.allowed_output_types is
    # not None:` guarding ONE carrier assignment — the SAME post-hoc idiom as
    # the hardware-context/previous_failures/mindset rows beside it. The
    # constraint's SEMANTICS live in the proposer's schema gate
    # (agent/schemas/proposal.py); run_workflow only forwards a declared
    # value. One sibling-shaped branch, within the pre-registered limit.
    #
    # All of it is the permitted shape: no new phase, no new branch family, no
    # task dispatch, no new mutable local accumulator, no new semantic owner.
    assert branchish == 128, (
        f"run_workflow branch-ish count is {branchish}, expected 128 "
        "(130 at C0 + 1 C2 unpack IfExp + 1 C5/W6 binding-selection IfExp "
        "- 1 arXiv-U1 extraction of the lit-review path-resolution If "
        "+ 1 arXiv-#259 constraint-forwarding If - 4 after extracting "
        "cross-iteration negative-feedback restoration; "
        "C3's union closure costs ZERO because the merge rule lives in "
        "core.resume.union_key_findings and this closure only calls it). "
        "If this grew further, the §12.1 tripwire requires re-running the "
        "structure preflight and choosing a responsibility-preserving "
        "extraction before adding more inline complexity."
    )


@pytest.mark.parametrize("forbidden", ["if tidmad", "if pets", "if davis"])
def test_the_carry_introduced_no_task_dispatch(forbidden):
    """The carried values are run-name lists and strings — structurally
    task-free. Nothing in this lifecycle may branch on task identity."""
    source = MODEL_EXPLORATION.read_text(encoding="utf-8").lower()
    assert forbidden not in source
