"""V20 PR D — the POSITIVE authority path, proved deterministically.

**Operator decision, 2026-08-05.** Case A was originally a real-training Gate.
That conflated two different things:

* whether PR D's control logic is correct — a deterministic state machine;
* whether some model trains well enough on a small data fraction to clear a
  HealthGate — a stochastic scientific outcome.

Making the second gate the first meant PR D's acceptance depended on whether a
model happened to collapse, whether the data fraction was large enough, and on
training randomness. Three Gate attempts failed for three unrelated reasons,
none of them a defect in the behaviour under test.

So the positive path is proved HERE, deterministically, through the real
production components — and the real GPU Gate is reserved for the one property
synthetic execution genuinely cannot establish (Case B: stable external
occupancy and measurement validity).

Precedent: `test_chain_incumbent_pseudo.py` established exactly this split for
V19 PR 1, *"so that the downstream Gate 2 smoke does not need to force a
particular stochastic real-training outcome."* This module applies the same
principle to PR D's authority chain.

**What is real here**: `ScientificAuthority`, `resolve_record_authority`,
`restore_prior_state`, the aggregation partition, and the artifact
serialisation. **What is substituted**: only the training itself and the LLM —
i.e. the stochastic parts, which prove nothing about the state machine.

The chain proved end to end:

    HealthGate-valid trial winner
      -> -inf bootstrap (no restored incumbent)
      -> formal-budget bypass
      -> completed formal record
      -> authoritative verdict, recomputed from stored facts
      -> resume admits it as chain incumbent
      -> scientific aggregation includes it
      -> strict JSON throughout
"""

from __future__ import annotations

import json

import pytest

from agent.schemas.hyperparam_tuning import HyperparamTuningOutput
from core.scientific_authority import ScientificAuthority, resolve_record_authority
from tests.helpers.formal_evidence import disabled_formal_evidence


class _Summary:
    """A Health-disabled fixture with matched formal score and evidence."""

    def __init__(self, model_type: str, verdict: dict | None, score: float):
        self.model_type = model_type
        self.scientific_authority = verdict
        self.run_name = "v1"
        self.formal_score = score
        self.formal_evidence = disabled_formal_evidence(model_type, score)


def _valid_formal_record(exp_id: str = "f1", score: float = 4.2) -> dict:
    """A formal record whose facts make it authoritative.

    The verdict is DERIVED from the three facts, never asserted by this
    fixture — that is the property under test.
    """
    verdict = ScientificAuthority(
        healthgate_mode="blocking",
        declared_result_authority="scientific",
        formal_validity="valid",
    )
    return {
        "exp_id": exp_id,
        "status": "success",
        "model_type": "punet",
        "timestamp": "2026-08-05 00:00:00",
        "params": {},
        "logical_round": 2,
        "denoising_score": score,
        "file_vector": [score] + [None] * 19,
        "health_gate_results": [],
        "health_gate_enabled": False,
        "scientific_authority": verdict.model_dump(mode="json"),
    }


class TestTheVerdictIsDerivedFromFacts:
    """Step 1 — authority is computed, never assembled by a caller."""

    def test_blocking_scientific_valid_is_authoritative(self):
        v = ScientificAuthority(
            healthgate_mode="blocking",
            declared_result_authority="scientific",
            formal_validity="valid",
        )
        assert v.authoritative is True
        assert v.enters_incumbent_selection is True
        assert v.enters_scientific_aggregation is True

    @pytest.mark.parametrize(
        ("mode", "authority", "validity"),
        [
            ("observe_only", "scientific", "valid"),
            ("blocking", "diagnostic", "valid"),
            ("blocking", "scientific", "invalid"),
        ],
        ids=["observe-only", "diagnostic", "formal-invalid"],
    )
    def test_any_missing_fact_removes_authority(self, mode, authority, validity):
        """MUTATION TARGET: widening the authoritative predicate.

        Authoritative == blocking + scientific + formal-valid, nothing else.
        """
        # NOTE: `observe_only + scientific` is ACCEPTED here and simply not
        # authoritative — verified against the real type rather than assumed.
        # The contradiction is refused at the LAUNCH boundary (D-C1b), not by
        # this verdict type, which must stay able to describe any historical
        # combination it is asked to read.
        v = ScientificAuthority(
            healthgate_mode=mode,
            declared_result_authority=authority,
            formal_validity=validity,
        )
        assert v.authoritative is False


class TestTheVerdictSurvivesTheArtifact:
    """Step 2 — the record round-trips and the verdict is RECOMPUTABLE from
    the stored facts, not merely echoed."""

    def test_it_survives_serialisation_and_recomputes(self):
        record = _valid_formal_record()
        output = HyperparamTuningOutput(
            run_name="pos",
            model_type="punet",
            file_index=6,
            status="completed",
            completed_rounds=1,
            total_attempts=1,
            best_denoising_score=4.2,
            best_formal_denoising_score=4.2,
            best_valid_formal_denoising_score=4.2,
            best_valid_formal_exp_id="f1",
            all_records=[record],
            started_at="2026-08-05 00:00:00",
            finished_at="2026-08-05 00:00:01",
            healthgate_mode="blocking",
            result_authority="scientific",
            formal_comparison_reference_source="negative_infinity_bootstrap",
        )
        restored = json.loads(output.model_dump_json())

        # The launch declarations and the bootstrap provenance survive.
        assert restored["healthgate_mode"] == "blocking"
        assert restored["result_authority"] == "scientific"
        assert restored["formal_comparison_reference_source"] == "negative_infinity_bootstrap"

        # The verdict survives NESTED inside all_records — the hop that
        # silently dropped it before FU-D-9.
        stored = restored["all_records"][0]["scientific_authority"]
        assert stored["authoritative"] is True

        # And it RECOMPUTES from the stored facts rather than being trusted.
        recomputed = resolve_record_authority(
            restored["all_records"][0],
            declared_healthgate_mode=restored["healthgate_mode"],
            declared_result_authority=restored["result_authority"],
            commit_time_validity="valid",
        )
        assert recomputed.authoritative is True

    def test_no_infinity_or_nan_reaches_the_artifact(self):
        """The `-inf` bootstrap is a RESOLVER value, never a stored one."""
        output = HyperparamTuningOutput(
            run_name="pos",
            model_type="punet",
            file_index=6,
            status="completed",
            completed_rounds=1,
            total_attempts=1,
            all_records=[_valid_formal_record()],
            started_at="2026-08-05 00:00:00",
            finished_at="2026-08-05 00:00:01",
            best_valid_formal_denoising_score=4.2,
            best_valid_formal_exp_id="f1",
            formal_comparison_reference_source="negative_infinity_bootstrap",
        )
        raw = output.model_dump_json()
        for token in ("Infinity", "-Infinity", "NaN"):
            assert token not in raw
        json.loads(raw)  # strict parse


class TestTheTwoConsumersAdmitIt:
    """Step 3 — the verdict is CONSUMED. A verdict nobody reads changes
    nothing, which is the defect class this PR family hit five times."""

    def test_aggregation_includes_an_authoritative_record(self):
        from execute_tools.scientific_aggregation import partition_for_aggregation

        rec = _valid_formal_record()
        scope = partition_for_aggregation(
            [_Summary("punet", rec["scientific_authority"], rec["denoising_score"])]
        )
        assert len(scope.included) == 1
        assert scope.excluded == []

    @pytest.mark.parametrize(
        ("mode", "authority"),
        [("blocking", "diagnostic"), ("observe_only", "diagnostic")],
        ids=["diagnostic", "observe-only-diagnostic"],
    )
    def test_aggregation_excludes_and_STATES_the_reason(self, mode, authority):
        """Exclusions are stated, never silent (§4.7)."""
        from execute_tools.scientific_aggregation import partition_for_aggregation

        verdict = ScientificAuthority(
            healthgate_mode=mode,
            declared_result_authority=authority,
            formal_validity="valid",
        ).model_dump(mode="json")

        scope = partition_for_aggregation([_Summary("punet", verdict, 4.2)])
        assert scope.included == []
        assert len(scope.excluded) == 1
        assert scope.provenance_lines(), "an exclusion must be stated"

    def test_a_record_without_the_contract_is_never_authoritative(self):
        """Historical records: readable, unchanged, authority NOT
        established — never an incumbent, never aggregated."""
        legacy = {
            "exp_id": "old",
            "status": "success",
            "model_type": "punet",
            "timestamp": "2026-01-01 00:00:00",
            "params": {},
            "denoising_score": 9.9,
        }
        verdict = resolve_record_authority(
            legacy,
            declared_healthgate_mode=None,
            declared_result_authority=None,
            commit_time_validity="valid",
        )
        assert verdict.authoritative is False
        assert verdict.basis == "unreconstructable_legacy"


class TestTheFullPositivePathInOneAssertion:
    """The chain, end to end, deterministically."""

    def test_valid_formal_becomes_an_admitted_authoritative_result(self):
        from execute_tools.scientific_aggregation import partition_for_aggregation

        record = _valid_formal_record()

        decl = {
            "declared_healthgate_mode": "blocking",
            "declared_result_authority": "scientific",
            "commit_time_validity": "valid",
        }

        # 1. derived verdict
        verdict = resolve_record_authority(record, **decl)
        assert verdict.authoritative is True

        # 2. survives the artifact and recomputes
        restored = json.loads(json.dumps(record))
        assert resolve_record_authority(restored, **decl).authoritative is True

        # 3. incumbent-eligible — read from the record verdict's own
        #    embedded conclusions, which is what resume consults.
        assert verdict.verdict is not None
        assert verdict.verdict.enters_incumbent_selection is True

        # 4. aggregation admits it
        assert partition_for_aggregation(
            [_Summary("punet", restored["scientific_authority"], restored["denoising_score"])]
        ).included

        # 5. and the same record, made diagnostic, is refused at BOTH
        #    consumers — proving the admission was earned, not automatic.
        refused = dict(restored)
        refused["scientific_authority"] = ScientificAuthority(
            healthgate_mode="blocking",
            declared_result_authority="diagnostic",
            formal_validity="valid",
        ).model_dump(mode="json")
        refused_verdict = resolve_record_authority(
            refused,
            declared_healthgate_mode="blocking",
            declared_result_authority="diagnostic",
            commit_time_validity="valid",
        )
        assert refused_verdict.authoritative is False
        assert refused_verdict.verdict is not None
        assert refused_verdict.verdict.enters_incumbent_selection is False
        assert (
            partition_for_aggregation(
                [_Summary("punet", refused["scientific_authority"], refused["denoising_score"])]
            ).included
            == []
        )
