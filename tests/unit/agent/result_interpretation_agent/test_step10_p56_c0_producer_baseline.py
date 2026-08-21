"""Step 10 / P5+P6 — C0 baselines for the ``vocab_link_confirmations`` PRODUCER.

Design:
``docs/design/generic_framework_upgrade/step_10_orchestration_task_binding/
pr_10_p5_6_lifecycle_and_three_task_closure.md`` §13 C0.

C0 makes the current defects executable BEFORE anything is fixed, so C1-C6 are
diffs against evidence rather than belief. This module owns two of them.

**1. The producer's ACCUMULATION TRAJECTORY (the golden).**
``test_vocab_feedback.py`` (E.7, lines 965-1160) already covers the producer's
per-call semantics thoroughly: confirmed increments, partial/refuted/None do
not, the same run cannot confirm twice, distinct runs accumulate, promotion
fires at the threshold, a feature absent from the vocabulary is skipped, and the
caller's mapping is never mutated. Every one of those tests makes exactly ONE
call.

The defect class those tests cannot catch, and this golden can: **whether each
call returns the FULL CUMULATIVE mapping when its own output is fed back in as
the next call's ``existing_confirmations``.** That is not a restatement of the
single-call tests — it is the load-bearing premise of the whole P5 transport
design (§2.1: "accumulation happens INSIDE the producer — each normal digest
already carries the full cumulative mapping. Therefore the cross-iteration
projection is LATEST-WINS on the whole dict"). If the producer ever returned a
DELTA instead of the cumulative map, every single-call test above would still
pass while latest-wins projection silently lost history, and a workflow-side
re-merge would become necessary — the second accumulation authority §10 rule 4
forbids. This golden fails the moment that premise breaks.

**2. The cold-start clobber (DD-2's before-picture).**
§7.3 / §2.1's new finding: the interpreter's cold-start early return builds an
``InterpretationOutput`` WITHOUT ``vocab_link_confirmations``, so the schema
default ``{}`` wins. Harmless today (the input is always ``{}`` because nothing
carries the value), but once C2's loop closure reads the just-written output
unconditionally, a cold-start iteration in a workspace whose restored mapping is
non-empty would clobber it. This test pins the DROP as it behaves today; C2
flips it to the carry-through expectation.
"""

from __future__ import annotations

from unittest.mock import patch

from agent.schemas.interpretation import InterpretationInput, ModelRunSummary, VocabEntry
from nodes.interpretation_helpers import update_vocab_link_confirmations
from nodes.result_interpretation_agent import ResultInterpretationAgent

# ---------------------------------------------------------------------------
# Fixtures — fixed, hand-written, no value read back from the code under test
# ---------------------------------------------------------------------------

#: One proposed link, reused across the whole trajectory so the only variable is
#: the outcome and the run name.
LINK = [{"feature": "dilated_stack", "capability": "long_range_context"}]
KEY = "dilated_stack:long_range_context"

#: A second, independent link introduced mid-trajectory.
OTHER_LINK = [{"feature": "gated_activation", "capability": "sharp_transients"}]
OTHER_KEY = "gated_activation:sharp_transients"


def _vocab() -> list[VocabEntry]:
    """Runtime vocabulary containing both features, neither yet related."""
    return [
        VocabEntry(name="dilated_stack", kind="candidate", description="d"),
        VocabEntry(name="gated_activation", kind="candidate", description="g"),
    ]


def _storage(tmp_path) -> dict:
    return {"backend": "local", "local": {"workspace": str(tmp_path), "run_name": "r1"}}


def _scoreless_summary(model_type: str = "wavenet") -> ModelRunSummary:
    """A summary that carries no ordering evidence, so the input needs no
    ``metric_spec`` (Step 09a C2's named absence) — the cheapest way to reach
    the degraded branch."""
    return ModelRunSummary(
        model_type=model_type,
        run_name="p56c0",
        status="error",
        completed_rounds=0,
        round_scores=[],
        round_conclusions=[],
    )


def _cold_start_agent() -> ResultInterpretationAgent:
    """An agent whose LLM would explode if called — the cold-start branch
    returns before any call, which is itself part of the contract."""
    with patch("nodes.result_interpretation_agent.LLMBridge") as MockBridge:
        MockBridge.return_value.generate.side_effect = AssertionError(
            "the cold-start branch must not reach the LLM"
        )
        agent = ResultInterpretationAgent(provider="gemini", model_id="test-model")
        agent.bridge = MockBridge.return_value
        return agent


# ---------------------------------------------------------------------------
# 1. The accumulation-trajectory golden
# ---------------------------------------------------------------------------


class TestProducerAccumulationTrajectory:
    """Feed each call's output back in as the next call's input, exactly as the
    activated lifecycle will, and pin the mapping at EVERY step."""

    def test_the_fixed_outcome_sequence_accumulates_cumulatively(self):
        """The C0 golden: a fixed 6-step sequence, every step's mapping pinned.

        Hardcoded expectations throughout — nothing is compared against a value
        the producer itself computed elsewhere.
        """
        vocab = _vocab()
        confs: dict[str, list[str]] = {}
        trajectory: list[dict[str, list[str]]] = []
        promotions: list[list[str]] = []

        # (links, outcome, run_name) — fixed, deliberately mixed.
        sequence = [
            (LINK, "confirmed", "wavenet"),  # 1: first confirmation
            (LINK, "partial", "punet"),  # 2: partial must change nothing
            (LINK, "confirmed", "punet"),  # 3: second DISTINCT run
            (LINK, "confirmed", "punet"),  # 4: repeat run — must not double count
            (LINK, "refuted", "fcnet"),  # 5: refuted must change nothing
            (LINK, "confirmed", "fcnet"),  # 6: third DISTINCT run -> promotion
        ]
        for links, outcome, run in sequence:
            confs, vocab, promoted = update_vocab_link_confirmations(
                prev_vocab_links=links,
                prediction_outcome=outcome,
                run_name=run,
                existing_confirmations=confs,
                runtime_vocab=vocab,
                min_runs=3,
            )
            trajectory.append({k: list(v) for k, v in confs.items()})
            promotions.append(list(promoted))

        assert trajectory == [
            {KEY: ["wavenet"]},
            {KEY: ["wavenet"]},
            {KEY: ["wavenet", "punet"]},
            {KEY: ["wavenet", "punet"]},
            {KEY: ["wavenet", "punet"]},
            {KEY: ["wavenet", "punet", "fcnet"]},
        ]
        # Promotion fires EXACTLY once, at the step that reaches three distinct
        # runs — not before, and not again afterwards.
        assert promotions == [[], [], [], [], [], [KEY]]

    def test_a_second_link_accumulates_beside_the_first_without_disturbing_it(self):
        """Cumulative means the WHOLE map, not just the key being touched.

        This is the specific shape that would break latest-wins projection: a
        producer returning only the pair it just touched would still satisfy
        every single-call test in ``test_vocab_feedback.py``.
        """
        vocab = _vocab()
        confs: dict[str, list[str]] = {}

        for links, run in [(LINK, "wavenet"), (OTHER_LINK, "punet"), (LINK, "fcnet")]:
            confs, vocab, _ = update_vocab_link_confirmations(
                prev_vocab_links=links,
                prediction_outcome="confirmed",
                run_name=run,
                existing_confirmations=confs,
                runtime_vocab=vocab,
                min_runs=3,
            )

        assert confs == {
            KEY: ["wavenet", "fcnet"],
            OTHER_KEY: ["punet"],
        }

    def test_promotion_at_step_three_is_observable_as_related_to(self):
        """The threshold's OBSERVABLE consequence, not just the return flag."""
        vocab = _vocab()
        confs: dict[str, list[str]] = {}
        related_after_each_step: list[list[str]] = []

        for run in ["wavenet", "punet", "fcnet"]:
            confs, vocab, _ = update_vocab_link_confirmations(
                prev_vocab_links=LINK,
                prediction_outcome="confirmed",
                run_name=run,
                existing_confirmations=confs,
                runtime_vocab=vocab,
                min_runs=3,
            )
            entry = next(v for v in vocab if v.name == "dilated_stack")
            related_after_each_step.append(list(entry.related_to))

        assert related_after_each_step == [[], [], ["long_range_context"]]

    def test_an_old_key_promotes_later_once_its_feature_appears(self):
        """§2.1: the promotion loop re-scans the WHOLE map every call.

        A pair can reach three confirmations while its feature is absent from
        the vocabulary, and promote on a LATER call once the feature appears.
        The carried mapping is what makes that reachable; a delta-returning
        producer would have discarded the history.
        """
        confs: dict[str, list[str]] = {}
        vocab_without_feature: list[VocabEntry] = [
            VocabEntry(name="unrelated", kind="candidate", description="u")
        ]

        for run in ["wavenet", "punet", "fcnet"]:
            confs, _, promoted = update_vocab_link_confirmations(
                prev_vocab_links=LINK,
                prediction_outcome="confirmed",
                run_name=run,
                existing_confirmations=confs,
                runtime_vocab=vocab_without_feature,
                min_runs=3,
            )
            assert promoted == []

        assert confs == {KEY: ["wavenet", "punet", "fcnet"]}

        # The feature now exists; a call that confirms NOTHING new still
        # promotes, because the loop re-scans the accumulated map.
        _confs, vocab, promoted = update_vocab_link_confirmations(
            prev_vocab_links=[],
            prediction_outcome=None,
            run_name="",
            existing_confirmations=confs,
            runtime_vocab=_vocab(),
            min_runs=3,
        )
        assert promoted == [KEY]
        entry = next(v for v in vocab if v.name == "dilated_stack")
        assert entry.related_to == ["long_range_context"]


# ---------------------------------------------------------------------------
# 2. The cold-start drop (DD-2's before-picture)
# ---------------------------------------------------------------------------


class TestColdStartDropsTheCarriedMapping:
    """**FLIPPED BY C2 (DD-2)** — the §7.3 defect, closed at the source."""

    def test_cold_start_now_carries_the_mapping_through(self, tmp_path):
        """WAS: ``output.vocab_link_confirmations == {}`` — the cold-start
        early return constructed ``InterpretationOutput`` without the field, so
        the schema default won and a restored mapping would be clobbered.

        Harmless before C2 (nothing carried the value in, so it was always
        ``{}``); once the loop closure reads the output UNCONDITIONALLY it
        became a live clobber whose reachability depended on a distant workflow
        condition. DD-2 makes the branch symmetric with the degraded branch, so
        the closure is safe by LOCAL construction rather than by a fragile
        invariant holding at a distance.
        """
        carried = {KEY: ["wavenet", "punet"]}
        inp = InterpretationInput(
            cold_start=True,
            storage=_storage(tmp_path),
            vocab_link_confirmations=carried,
        )
        assert inp.vocab_link_confirmations == carried

        output = _cold_start_agent().run(inp)

        assert output.vocab_link_confirmations == carried
        assert output.cold_start is True

    def test_the_carry_through_is_a_copy_not_an_alias(self, tmp_path):
        """The degraded branch's idiom is ``dict(inp...)``; DD-2 matches it, so
        mutating the output cannot reach back into the caller's mapping."""
        carried = {KEY: ["wavenet"]}
        output = _cold_start_agent().run(
            InterpretationInput(
                cold_start=True,
                storage=_storage(tmp_path),
                vocab_link_confirmations=carried,
            )
        )
        output.vocab_link_confirmations["injected"] = ["x"]
        assert carried == {KEY: ["wavenet"]}

    def test_the_degraded_branch_already_carries_it_through(self, tmp_path):
        """The asymmetry, made explicit: the degraded branch at :1125 does
        exactly what DD-2 gives the cold-start branch."""
        carried = {KEY: ["wavenet"]}
        inp = InterpretationInput(
            summaries=[_scoreless_summary()],
            storage=_storage(tmp_path),
            vocab_link_confirmations=carried,
        )
        with patch("nodes.result_interpretation_agent.LLMBridge") as MockBridge:
            MockBridge.return_value.generate.side_effect = RuntimeError("LLM unreachable")
            agent = ResultInterpretationAgent(provider="gemini", model_id="test-model")
            agent.bridge = MockBridge.return_value
            output = agent.run(inp)

        assert output.vocab_link_confirmations == carried
