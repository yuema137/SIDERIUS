"""F-SCANE-1 — the exclusion must reach somebody, and must not delete a warning.

Historical regression boundary retained after campaign evidence moved to external ownership.
("14 of 15 digests concluded there was no authoritative result and nobody was
told" · "and the exclusion SUPPRESSES the warning that would have flagged it").

The defects only this file catches
----------------------------------
1. ``AggregationScope.provenance_lines()`` — named as THE renderer by
   ``InterpretationOutput.scientific_aggregation``'s own field description —
   had ZERO production callers. The all-excluded sentence existed, was
   reachable only from inside that method, and nothing in production called
   the method. Deleting the print in ``run()`` turns
   ``test_the_all_excluded_conclusion_is_printed_to_the_operator`` red.

2. The authority filter EMPTIES ``per_model_formal``, and the synthesis
   renderer gates its "best_score above may be from a trial round" caveat on
   that dict being non-empty. So the run whose formal evidence is entirely
   unusable was exactly the run that rendered a trial-mixed best score with
   the warning REMOVED. Reverting either half of the fix (the pre-filter
   capture in ``ordering.precompute_evidence`` or the render in
   ``_build_synthesis_prompt``) turns
   ``test_a_withheld_formal_score_is_a_named_absence_in_the_prompt`` red.

3. The named absence must name a WITHHOLDING, not every absence. A model that
   never produced a formal score is excluded from the aggregate too, but it
   had nothing withheld — reporting it as withheld would be a second
   fabrication.
   ``test_a_model_that_never_had_a_formal_score_is_not_reported_as_withheld``
   turns red if the reason map is keyed off the exclusion list alone.

The defects only the N-2 / N-3 sections catch
---------------------------------------------
4. **N-2 — the exclusion verdict ranged over the WRONG SET.** The corpus in
   sections 1-3 is the FIRST-iteration shape: every model arrives as a fresh
   ``ModelRunSummary``. From the second iteration of a chain onward,
   ``model_exploration.run_workflow`` passes exactly ONE new summary and every
   other model arrives through ``model_knowledge_cache``. ``per_model_formal``
   is filled from BOTH, but the authority partition read only ``summaries`` —
   so for N-1 of N models the formal score was deleted and NO withheld line was
   rendered: the exact silence F-SCANE-1 exists to close, reproduced by the
   fix's own blind spot. ``TestALaterIterationCorpus`` drives that shape and
   turns red if the partition narrows back to ``summaries``, or if the cache
   stops carrying the verdict beside the score it judges.

5. **N-3 — a campaign-scoped conclusion from an iteration-scoped partition.**
   The all-excluded sentence used to read *"this campaign produced no
   scientifically authoritative result"*, printed once per iteration from a
   partition that has never seen another iteration.
   ``TestTheConclusionDoesNotOutScopeItsEvidence`` turns red if the sentence
   regains a scope its evidence cannot support.

Every assertion here drives the REAL ``ResultInterpretationAgent.run()``; none
constructs a prompt or a scope by hand.
"""

from __future__ import annotations

from unittest.mock import patch

from agent.schemas.interpretation import InterpretationInput, ModelRunSummary
from nodes.result_interpretation_agent import ResultInterpretationAgent
from tests.unit.agent.result_interpretation_agent.test_interpretation_agent import (
    _llm_dispatch,
    shipped_spec,
)

#: The exact sentence `provenance_lines` renders and that nothing printed.
#: N-3 — the scope is the interpreter's own iteration, never "this campaign":
#: a partition over one iteration's evidence cannot speak for the others.
ALL_EXCLUDED_SENTENCE = (
    "EVERY result was excluded — no scientifically authoritative "
    "result is available in iteration 1."
)


def _verdict(mode: str, authority: str, validity: str) -> dict:
    from core.scientific_authority import ScientificAuthority

    return ScientificAuthority.from_context(
        healthgate_mode=mode,
        declared_result_authority=authority,
        formal_validity=validity,
    ).model_dump()


def _summary(
    model_type: str,
    *,
    best: float | None,
    formal: float | None,
    verdict: dict | None,
) -> ModelRunSummary:
    return ModelRunSummary(
        model_type=model_type,
        run_name="v1",
        status="completed",
        completed_rounds=1,
        best_denoising_score=best,
        worst_denoising_score=best,
        formal_score=formal,
        scientific_authority=verdict,
        round_scores=[best],
        round_conclusions=["c"],
    )


def _run(workspace, summaries, *, cache=None, iteration=1) -> tuple[object, list[str]]:
    """Run the REAL agent; return (output, captured user prompts).

    ``cache`` / ``iteration`` reach the LATER-iteration shape (N-2): after the
    first iteration a chain subprocess hands the interpreter exactly one new
    summary and carries every other model in ``model_knowledge_cache``.
    """
    captured: list[str] = []

    def _capture(system_prompt: str, user_prompt: str, **kwargs):
        captured.append(user_prompt)
        return _llm_dispatch(system_prompt, user_prompt, **kwargs)

    with patch("nodes.result_interpretation_agent.LLMBridge") as MockBridge:
        MockBridge.return_value.generate.side_effect = _capture
        agent = ResultInterpretationAgent(provider="gemini", model_id="test-model")
        agent.bridge = MockBridge.return_value
        out = agent.run(
            InterpretationInput(
                metric_spec=shipped_spec(),
                summaries=summaries,
                model_knowledge_cache=cache or {},
                iteration=iteration,
                storage={
                    "backend": "local",
                    "local": {"workspace": str(workspace), "run_name": "r1"},
                },
            )
        )
    return out, captured


def _cached(model_type: str, *, best: float, formal: float | None, verdict: dict | None) -> dict:
    """A ``model_knowledge_cache`` entry in the shape the interpreter writes.

    Deliberately the PRODUCTION key names (``_stats`` with ``formal_score`` and
    ``scientific_authority``): the point of the N-2 tests is that the cached
    half of the evidence reaches the same authority partition the fresh half
    does, so a hand-invented cache shape would prove nothing.
    """
    return {
        "key_findings": ["cached finding"],
        "bottlenecks": [],
        "best_config_analysis": "cached analysis",
        "score_trend": "flat",
        "_stats": {
            "best_denoising_score": best,
            "worst_denoising_score": best,
            "formal_score": formal,
            "completed_rounds": 1,
            "scientific_authority": verdict,
        },
    }


def _synthesis(prompts: list[str]) -> str:
    """The ONE cross-model synthesis prompt out of the captured sequence.

    Identified by the header only that renderer emits. Joining every captured
    prompt instead would mix in the per-model prompts, whose ``## Model:``
    headers make a per-model block indistinguishable from a synthesis block —
    which is exactly how a per-model assertion can pass while the synthesis
    block it claims to be reading says something else.
    """
    matches = [p for p in prompts if p.lstrip().startswith("## Overall Performance")]
    assert len(matches) == 1, (
        f"expected exactly one cross-model synthesis prompt, captured {len(matches)}"
    )
    return matches[0]


#: Two models whose formal results are BOTH non-authoritative (declared
#: diagnostic), with `best != formal` so the caveat line is renderable at all.
#: `all_excluded` is therefore True and `per_model_formal` is emptied — the
#: exact state in which the pre-fix prompt lost its warning.
def _all_excluded_corpus() -> list[ModelRunSummary]:
    return [
        _summary(
            "punet",
            best=0.5,
            formal=1.0,
            verdict=_verdict("blocking", "diagnostic", "valid"),
        ),
        _summary(
            "fcnet",
            best=50.0,
            formal=99.0,
            verdict=_verdict("blocking", "diagnostic", "valid"),
        ),
    ]


class TestTheOperatorIsTold:
    def test_the_all_excluded_conclusion_is_printed_to_the_operator(self, tmp_path, capsys):
        out, _ = _run(tmp_path, _all_excluded_corpus())

        # The population is NON-VACUOUS: the run really did exclude
        # everything. Without this the stdout assertion below could pass on a
        # corpus that never reached the all-excluded state.
        assert out.scientific_aggregation is not None
        assert out.scientific_aggregation["all_excluded"] is True
        assert out.scientific_aggregation["excluded_count"] == 2

        printed = capsys.readouterr().out
        assert ALL_EXCLUDED_SENTENCE in printed, (
            "the campaign concluded it produced no scientifically authoritative "
            "result and told nobody — `AggregationScope.provenance_lines()` "
            "still has no production caller"
        )
        # The counts line rides with it: an operator needs the WHY, not only
        # the verdict.
        assert "2 non-authoritative results excluded:" in printed
        assert "declared_diagnostic" in printed

    def test_the_provenance_is_printed_before_any_llm_call(self, tmp_path, capsys):
        """An interpreter LLM failure must not be able to swallow the
        conclusion — the same structural rule the exclusion itself follows."""
        events: list[str] = []

        def _recording(system_prompt: str, user_prompt: str, **kwargs):
            events.append("llm")
            print("<<<LLM>>>")
            return _llm_dispatch(system_prompt, user_prompt, **kwargs)

        with patch("nodes.result_interpretation_agent.LLMBridge") as MockBridge:
            MockBridge.return_value.generate.side_effect = _recording
            agent = ResultInterpretationAgent(provider="gemini", model_id="test-model")
            agent.bridge = MockBridge.return_value
            agent.run(
                InterpretationInput(
                    metric_spec=shipped_spec(),
                    summaries=_all_excluded_corpus(),
                    storage={
                        "backend": "local",
                        "local": {"workspace": str(tmp_path), "run_name": "r1"},
                    },
                )
            )

        printed = capsys.readouterr().out
        assert events, "no LLM call was observed, so 'before any LLM call' is vacuous"
        assert ALL_EXCLUDED_SENTENCE in printed
        assert printed.index(ALL_EXCLUDED_SENTENCE) < printed.index("<<<LLM>>>")


class TestTheWarningSurvivesTheExclusion:
    def test_a_withheld_formal_score_is_a_named_absence_in_the_prompt(self, tmp_path):
        out, captured = _run(tmp_path, _all_excluded_corpus())
        synthesis = _synthesis(captured)

        # Non-vacuity: this is the state where the pre-fix caveat vanished.
        assert out.scientific_aggregation["all_excluded"] is True

        # The exclusion still holds — no non-authoritative number is offered
        # as a formal score.
        assert "Formal score: 1.0" not in synthesis
        assert "Formal score: 99.0" not in synthesis

        # ...and BOTH models say so, by name, with the typed reason.
        assert synthesis.count("Formal score: WITHHELD") == 2
        assert "excluded from the scientific aggregate (declared_diagnostic)" in synthesis
        assert "NOT a scientifically authoritative result" in synthesis

    def test_an_authoritative_formal_score_still_renders_its_own_caveat(self, tmp_path):
        """The fix must not replace the ordinary caveat with the withheld one."""
        good = _summary(
            "punet", best=0.5, formal=1.0, verdict=_verdict("blocking", "scientific", "valid")
        )
        diag = _summary(
            "fcnet", best=50.0, formal=99.0, verdict=_verdict("blocking", "diagnostic", "valid")
        )
        _, captured = _run(tmp_path, [good, diag])
        synthesis = _synthesis(captured)

        assert "Formal score: 1.0  (best_score above may be from a trial round)" in synthesis
        assert "Formal score: 99.0" not in synthesis
        assert synthesis.count("Formal score: WITHHELD") == 1

    def test_a_model_that_never_had_a_formal_score_is_not_reported_as_withheld(self, tmp_path):
        """An absence is not a withholding.

        ``no_formal`` carries no verdict at all, so the authority resolver
        excludes it (``unreconstructable_legacy``) exactly like a withheld
        result. It had no formal score to withhold, and saying otherwise
        would be a second fabrication — the one this row exists to stop.
        """
        withheld = _summary(
            "punet", best=0.5, formal=1.0, verdict=_verdict("blocking", "diagnostic", "valid")
        )
        no_formal = _summary("fcnet", best=50.0, formal=None, verdict=None)
        out, captured = _run(tmp_path, [withheld, no_formal])
        synthesis = _synthesis(captured)

        # Non-vacuity: `fcnet` really is in the excluded list.
        excluded_ids = {e["record_id"] for e in out.scientific_aggregation["excluded"]}
        assert excluded_ids == {"punet", "fcnet"}

        assert synthesis.count("Formal score: WITHHELD") == 1
        punet_block = synthesis.split("## Model: punet", 1)[1]
        assert "Formal score: WITHHELD" in punet_block.split("## Model:", 1)[0]
        fcnet_block = synthesis.split("## Model: fcnet", 1)[1]
        assert "Formal score:" not in fcnet_block.split("## Model:", 1)[0]


class TestNothingIsSaidWhenNothingWasExcluded:
    def test_a_fully_authoritative_run_renders_no_withheld_line_and_says_so(self, tmp_path, capsys):
        """The complement, so the two assertions above cannot both pass by
        the renderer emitting the line unconditionally."""
        good = _summary(
            "punet", best=0.5, formal=1.0, verdict=_verdict("blocking", "scientific", "valid")
        )
        other = _summary(
            "wavenet", best=0.4, formal=0.9, verdict=_verdict("blocking", "scientific", "valid")
        )
        out, captured = _run(tmp_path, [good, other])

        assert out.scientific_aggregation["excluded"] == []
        assert "WITHHELD" not in _synthesis(captured)
        printed = capsys.readouterr().out
        assert "Scientific aggregation used 2 authoritative results." in printed
        assert ALL_EXCLUDED_SENTENCE not in printed


class TestALaterIterationCorpus:
    """N-2 — the shape every iteration after the first actually has.

    ``model_exploration.run_workflow`` fixes ``summaries`` at exactly ONE
    ``ModelRunSummary`` from iteration 2 on; the rest of the campaign's models
    arrive through ``model_knowledge_cache``. The classes above all use the
    FIRST-iteration shape, where every model is a fresh summary — which is why
    the partition-over-``summaries``-only defect survived them.
    """

    def test_a_cached_models_withheld_formal_score_is_named_not_silently_dropped(self, tmp_path):
        """The whole of N-2, at the boundary it lives on.

        ``fcnet`` is cached and non-authoritative. Its formal score 99.0 must
        NOT reach the prompt (the exclusion still holds) and its withholding
        must be NAMED. Before the fix it was neither: the score was deleted by
        a filter the model was never partitioned into, and no reason existed
        to report — ``excluded_count`` was 0 and no WITHHELD line was rendered.
        """
        fresh = _summary(
            "punet", best=0.5, formal=1.0, verdict=_verdict("blocking", "scientific", "valid")
        )
        cache = {
            "fcnet": _cached(
                "fcnet",
                best=50.0,
                formal=99.0,
                verdict=_verdict("blocking", "diagnostic", "valid"),
            )
        }
        out, captured = _run(tmp_path, [fresh], cache=cache, iteration=4)
        synthesis = _synthesis(captured)

        # Non-vacuity: the cached model really did reach the synthesis prompt,
        # so "its score is absent" is a statement about a rendered block.
        assert "## Model: fcnet" in synthesis

        assert out.scientific_aggregation["included"] == ["punet"]
        assert [e["record_id"] for e in out.scientific_aggregation["excluded"]] == ["fcnet"]
        assert out.scientific_aggregation["excluded"][0]["reason"] == "declared_diagnostic"

        assert "99.0" not in synthesis
        assert synthesis.count("Formal score: WITHHELD") == 1
        assert "excluded from the scientific aggregate (declared_diagnostic)" in synthesis

    def test_a_cached_authoritative_formal_score_survives_the_cache_round_trip(self, tmp_path):
        """The complement, and the reason the fix is not "exclude every cached
        model".

        A verdict that WAS established must still be established after the
        model goes quiet for an iteration. Caching the score without its
        verdict would make every cached model read as
        ``unreconstructable_legacy`` — a true-sounding reason that is false
        about a model whose authority this very run recorded.
        """
        fresh = _summary(
            "punet", best=0.5, formal=1.0, verdict=_verdict("blocking", "scientific", "valid")
        )
        cache = {
            "fcnet": _cached(
                "fcnet",
                best=50.0,
                formal=99.0,
                verdict=_verdict("blocking", "scientific", "valid"),
            )
        }
        out, captured = _run(tmp_path, [fresh], cache=cache, iteration=4)
        synthesis = _synthesis(captured)

        assert out.scientific_aggregation["excluded"] == []
        assert set(out.scientific_aggregation["included"]) == {"punet", "fcnet"}
        assert "WITHHELD" not in synthesis
        assert "Formal score: 99.0" in synthesis

    def test_a_cache_entry_written_before_the_verdict_travelled_fails_closed(self, tmp_path):
        """A ``_stats`` block with a formal score and no verdict.

        Fail-closed is the frozen rule for anything missing the authority
        contract — but the exclusion must be REPORTED, which is the half that
        was missing. Silence here is indistinguishable from "nothing was
        withheld".
        """
        fresh = _summary(
            "punet", best=0.5, formal=1.0, verdict=_verdict("blocking", "scientific", "valid")
        )
        cache = {"fcnet": _cached("fcnet", best=50.0, formal=99.0, verdict=None)}
        out, captured = _run(tmp_path, [fresh], cache=cache, iteration=4)
        synthesis = _synthesis(captured)

        assert out.scientific_aggregation["excluded"][0] == {
            "record_id": "fcnet",
            "reason": "unreconstructable_legacy",
            "basis": "unreconstructable_legacy",
        }
        assert synthesis.count("Formal score: WITHHELD") == 1
        assert "excluded from the scientific aggregate (unreconstructable_legacy)" in synthesis

    def test_a_cached_model_that_never_had_a_formal_score_is_not_reported_as_withheld(
        self, tmp_path
    ):
        """The absence-is-not-a-withholding rule, on the cached half.

        Widening the partition must not widen the WITHHELD line: this model is
        excluded (no verdict) but had nothing to withhold.
        """
        fresh = _summary(
            "punet", best=0.5, formal=1.0, verdict=_verdict("blocking", "scientific", "valid")
        )
        cache = {"fcnet": _cached("fcnet", best=50.0, formal=None, verdict=None)}
        out, captured = _run(tmp_path, [fresh], cache=cache, iteration=4)
        synthesis = _synthesis(captured)

        # Non-vacuity: it really is excluded, so the absent line is a choice.
        assert [e["record_id"] for e in out.scientific_aggregation["excluded"]] == ["fcnet"]
        assert "WITHHELD" not in synthesis

    def test_the_verdict_is_cached_beside_the_score_it_judges(self, tmp_path):
        """The transport, at the write side.

        Reading the produced cache rather than a prompt: the next iteration's
        partition can only be as honest as what this iteration persisted, and
        ``formal_score`` used to be cached while ``scientific_authority`` was
        not.
        """
        verdict = _verdict("blocking", "scientific", "valid")
        fresh = _summary("punet", best=0.5, formal=1.0, verdict=verdict)
        out, _ = _run(tmp_path, [fresh])

        stats = out.model_knowledge_cache["punet"]["_stats"]
        assert stats["formal_score"] == 1.0
        assert stats["scientific_authority"] == verdict


class TestTheConclusionDoesNotOutScopeItsEvidence:
    """N-3 — an iteration-scoped partition may not conclude about a campaign."""

    def test_the_printed_conclusion_names_the_iteration_it_was_computed_from(
        self, tmp_path, capsys
    ):
        _run(tmp_path, _all_excluded_corpus(), iteration=7)
        printed = capsys.readouterr().out

        assert (
            "EVERY result was excluded — no scientifically authoritative "
            "result is available in iteration 7." in printed
        ), "the all-excluded conclusion does not say which iteration produced it"
        # The overclaim itself, in every spelling that would restore it.
        assert "this campaign produced no" not in printed
        assert "campaign" not in printed

    def test_the_warning_still_fires_it_is_only_re_scoped(self, tmp_path, capsys):
        """The repair is the SCOPE, never the warning: a caveat must not
        disappear exactly when the evidence becomes unusable."""
        out, _ = _run(tmp_path, _all_excluded_corpus(), iteration=7)
        assert out.scientific_aggregation["all_excluded"] is True
        printed = capsys.readouterr().out
        assert "EVERY result was excluded" in printed
        assert "2 non-authoritative results excluded:" in printed
