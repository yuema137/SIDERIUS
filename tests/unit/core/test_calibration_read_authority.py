"""Layer-2 matrix: a matching bucket is NOT applicability.

V20 PR C1 / C-C5a.

WHAT THIS FILE EXISTS TO PROVE. `as_estimate` used to grant measured,
blocking-eligible authority on `validated bucket + local environment` alone.
It never received the candidate the estimate was for, so it could not check
whether the evidence covered that candidate even in principle. Every row
below is a way that assumption produces a confidently wrong number, and each
row names the dimension it isolates.

The four reuse boundaries the operator froze -- cross-task, cross-device,
cross-phase, cross-measurement-kind -- are exact-match identity dimensions.
The applicability rows are bounded-range. The two kinds of failure are not
interchangeable, which is why identity and envelope are separate models and
why collapsing them would silently restore the defect.

WHY THE MATRIX RATHER THAN ONE TEST PER FUNCTION. A per-function test cannot
express "the same measurement is authoritative here and not there" -- that is
a statement about pairs. Every row shares one measured observation and varies
exactly one dimension of the request, so a row that goes green when it should
be red names the dimension that stopped being checked.
"""

from __future__ import annotations

import pytest

from core.runtime_control.calibration_policy import ApplicabilityEnvelope
from core.runtime_control.calibration_read import (
    NO_CANDIDATE,
    AuthorityDecision,
    CandidateRequest,
    evaluate_candidate_authority,
)
from core.runtime_control.registry_schemas import (
    UNKNOWN_MODEL_FAMILY,
    CalibrationObservation,
    MeasurementIdentity,
)

BASE_IDENTITY = dict(
    measurement_kind="duration",
    task_identity="tidmad_denoising",
    data_shape_class="tidmad_int8_1d",
    model_family="wavenet",
    candidate_config_hash="cfg-abc",
    phase="training",
    hardware_uuid="GPU-1111",
    runtime_stack_identity="stack-1",
)

MEASURED = MeasurementIdentity(**BASE_IDENTITY)

#: What the bucket actually observed. Deliberately a real span rather than a
#: point, so "inside" and "outside" are both expressible.
ENVELOPE = ApplicabilityEnvelope(
    ranges={"batch_size": (2.0, 8.0), "segment_length": (10_000.0, 40_000.0)},
    sample_count=3,
)

INSIDE = {"batch_size": 4, "segment_length": 20_000}


def _observation(**over) -> CalibrationObservation:
    base = dict(
        operation="training",
        measurement_unit="optimizer_step",
        measured_value_ms=21.4,
        workload={"batch_size": 4, "segment_length": 20_000},
        realized_model={"parameter_count": 156_320},
        hardware_compatibility_id="sha256:" + "a" * 64,
        execution_environment_id="sha256:" + "b" * 64,
        concurrency_identity="single_candidate_idle",
        software_stack={"torch": "2.7.0"},
        producer_identity="runtime_probe@0.0.0+test",
        provenance="bounded_live_probe",
        validation_status="unvalidated",
        timestamp_metadata="2026-08-02T12:00:00Z",
        identity=MEASURED,
    )
    base.update(over)
    return CalibrationObservation(**base)


def _decide(request: CandidateRequest | None, *, envelope=ENVELOPE) -> AuthorityDecision:
    return evaluate_candidate_authority(_observation(), request, envelope=envelope)


class TestTheApplicableCaseIsGranted:
    """The positive control. Without it, a matrix of refusals could pass by
    refusing everything -- which is safe and useless."""

    def test_matching_identity_and_in_range_candidate_is_authoritative(self):
        decision = _decide(CandidateRequest(identity=MEASURED, dimensions=INSIDE))
        assert decision.granted is True
        assert decision.applicability == "interpolation"


#: One row per frozen reuse boundary. Each varies EXACTLY one identity
#: dimension from the measurement, so a green row names what stopped being
#: compared.
IDENTITY_ROWS = [
    pytest.param("task_identity", "other_task", id="cross-task"),
    pytest.param("hardware_uuid", "GPU-9999", id="cross-device-uuid"),
    pytest.param("phase", "inference", id="cross-phase"),
    pytest.param("measurement_kind", "gpu_requirement", id="cross-measurement-kind"),
    pytest.param("model_family", "punet", id="cross-family"),
    pytest.param("candidate_config_hash", "cfg-zzz", id="cross-candidate-config"),
    pytest.param("data_shape_class", "other_shape", id="cross-data-shape"),
    pytest.param("runtime_stack_identity", "stack-2", id="cross-stack"),
]


class TestIdentityMismatchIsNeverAuthoritative:
    """Exact-match dimensions. These are the frozen non-reuse rules: the
    measurement is about something else, so no amount of validation or
    range-checking can make it speak for this candidate."""

    @pytest.mark.parametrize("field,other", IDENTITY_ROWS)
    def test_a_single_differing_dimension_refuses(self, field, other):
        requested = MeasurementIdentity(**{**BASE_IDENTITY, field: other})
        decision = _decide(CandidateRequest(identity=requested, dimensions=INSIDE))

        assert decision.granted is False, (
            f"{field} differs between the measurement and the request, yet the "
            "evidence was still treated as authoritative"
        )
        # The reason must name the dimension, or an operator cannot tell which
        # reuse rule refused.
        assert any(field in reason for reason in decision.reasons)

    def test_the_candidate_is_in_range_in_every_identity_row(self):
        """Proves the rows above isolate IDENTITY. If the dimensions were
        out of range too, each row would pass for the wrong reason and the
        matrix would not distinguish the two kinds of failure at all."""
        label, _ = ENVELOPE.classify(INSIDE)
        assert label == "interpolation"


class TestApplicabilityIsCheckedEvenOnAnExactIdentityMatch:
    """The frozen invariant itself: a bucket match is not applicability."""

    @pytest.mark.parametrize(
        "dimensions,id_",
        [
            ({"batch_size": 64, "segment_length": 20_000}, "batch-above-range"),
            ({"batch_size": 1, "segment_length": 20_000}, "batch-below-range"),
            ({"batch_size": 4, "segment_length": 4_000_000}, "segment-above-range"),
        ],
    )
    def test_out_of_range_candidate_is_refused_despite_identical_identity(self, dimensions, id_):
        decision = _decide(CandidateRequest(identity=MEASURED, dimensions=dimensions))
        assert decision.granted is False
        assert decision.applicability == "unsupported_extrapolation"
        assert any("outside measured range" in r for r in decision.reasons)

    def test_a_dimension_with_no_measured_evidence_fails_closed(self):
        """Absent evidence is never supporting evidence."""
        decision = _decide(
            CandidateRequest(identity=MEASURED, dimensions={"batch_size": 4, "unmeasured": 3})
        )
        assert decision.granted is False
        assert decision.applicability == "not_applicable"
        assert any("no measured evidence" in r for r in decision.reasons)


class TestFailClosedWhenApplicabilityCannotBeEvaluated:
    def test_no_candidate_request_is_refused(self):
        """The specific hole C-C5a closes: the old seam had no candidate at
        all and granted authority anyway."""
        assert _decide(None) == NO_CANDIDATE
        assert NO_CANDIDATE.granted is False

    def test_an_observation_without_identity_is_refused(self):
        """A pre-C-C2 record cannot be shown to match anything, so it can
        never be authoritative -- it is evidence, not authority."""
        decision = evaluate_candidate_authority(
            _observation(identity=None),
            CandidateRequest(identity=MEASURED, dimensions=INSIDE),
            envelope=ENVELOPE,
        )
        assert decision.granted is False
        assert any("no measurement identity" in r for r in decision.reasons)

    def test_a_bucket_with_no_envelope_is_refused(self):
        decision = _decide(CandidateRequest(identity=MEASURED, dimensions=INSIDE), envelope=None)
        assert decision.granted is False
        assert any("no applicability envelope" in r for r in decision.reasons)

    def test_an_unknown_model_family_is_never_authoritative(self):
        """Frozen §8.A. The record is legitimate evidence and is kept; what
        is forbidden is letting it decide."""
        unknown = {**BASE_IDENTITY, "model_family": UNKNOWN_MODEL_FAMILY}
        decision = evaluate_candidate_authority(
            _observation(identity=MeasurementIdentity(**unknown)),
            CandidateRequest(identity=MeasurementIdentity(**unknown), dimensions=INSIDE),
            envelope=ENVELOPE,
        )
        assert decision.granted is False
        assert any("family" in r for r in decision.reasons)

    def test_an_empty_request_does_not_grant_authority(self):
        """No dimensions means nothing was checked. `applicability_for_request`
        already refuses this; asserted here because the authority seam is
        where being wrong is expensive."""
        decision = _decide(CandidateRequest(identity=MEASURED, dimensions={}))
        assert decision.granted is False
        assert decision.applicability == "not_applicable"


class TestTheSeamIsReachedFromTheRegistry:
    """The boundary is worthless if `as_estimate` keeps its own copy of the
    rule, or stops calling it. C-C4 shipped an evaluator that production
    never called; this is the same failure mode one layer up."""

    def test_as_estimate_calls_the_authority_boundary(self):
        import ast
        from pathlib import Path

        import core.runtime_control.calibration_registry as reg

        tree = ast.parse(Path(reg.__file__).read_text())
        method = next(
            n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "as_estimate"
        )
        called = {
            getattr(c.func, "id", getattr(c.func, "attr", None))
            for c in ast.walk(method)
            if isinstance(c, ast.Call)
        }
        assert "evaluate_candidate_authority" in called, (
            "as_estimate no longer consults the authority boundary, so a "
            "validated bucket can again grant measured authority to a "
            "candidate nobody checked"
        )

    def test_measured_authority_is_returned_only_inside_the_granted_branch(self):
        """`make_estimate(provenance=obs.provenance, ...)` -- the measured
        path -- must be unreachable unless the decision granted it. A second
        measured return outside that guard would restore the defect while
        every unit test above still passed."""
        import ast
        import re
        from pathlib import Path

        import core.runtime_control.calibration_registry as reg

        # AST-delimited, not string-sliced: `as_estimate` is the last method
        # in its class, so slicing to the next "\n    def " found nothing and
        # the test errored instead of asserting.
        source = Path(reg.__file__).read_text()
        tree = ast.parse(source)
        method = next(
            n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "as_estimate"
        )
        body = ast.get_source_segment(source, method) or ""
        measured_returns = len(re.findall(r"provenance=obs\.provenance", body))
        assert measured_returns == 1, (
            f"expected exactly one measured-provenance return in as_estimate, "
            f"found {measured_returns}"
        )
        assert body.index("if authority.granted:") < body.index("provenance=obs.provenance")
