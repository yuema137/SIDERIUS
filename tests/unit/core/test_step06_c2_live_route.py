"""Step 06 — C2: the LIVE in-process route runs THROUGH the metric handle.

Design: ``docs/design/generic_framework_upgrade/step_06_metric_interface.md``
§9, §12, §19 C2.

What this module proves at the sandbox seam (the tuner-side binding and
reachability are in ``tests/unit/agent/tune_ml_hyperparam_agent/
test_step06_c2_tuner_metric_binding.py``):

* ``TidmadSandbox.evaluate_metric(run_metric, …)`` reproduces the C0
  route-(i) literal EXACTLY — same fixture, same bytes, now through the
  handle;
* ``TidmadSandbox.score_vector`` (the pre-Step-06 2-tuple seam) is unchanged
  for callers that predate the handle — Regime A resolves TIDMAD;
* an unscoreable deliverable set raises the structured ``NotScoreableError``
  BEFORE ``scoring_utils.score_vector`` is reached (asserted with a spy that
  fails the test if the arithmetic runs);
* ``StubSandbox`` mirrors the seam: same synthetic values as its
  ``score_vector``, under the run's real identity/direction.

The C0 fixture is imported, not re-declared: one oracle, one set of literals.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import execute_tools.scoring_utils as su
from core.sandbox_executor import StubSandbox, TidmadSandbox
from execute_tools.dataset_config import bind_dataset_profile, resolve_dataset_profile
from execute_tools.evaluation_metric import (
    TIDMAD_METRIC_ID,
    MetricResult,
    MetricSpec,
    NotScoreableError,
    PresenceScoreabilityContract,
    derive_tidmad_metric,
)
from tests.unit.core.test_step06_c0_two_route_oracle import (
    EXPECTED_FILE0,
    EXPECTED_SCALAR,
    EXPECTED_VECTOR_LENGTH,
    FILE_INDEX,
    RUN_NAME,
    _anchor_inputs,
    oracle_fixture,
)


def _sandbox(fx) -> TidmadSandbox:
    return TidmadSandbox(run_name=RUN_NAME, workspace=str(fx["workspace"]), file_index=FILE_INDEX)


def test_the_live_route_reproduces_the_c0_literal_through_the_handle(oracle_fixture):
    """``evaluate_metric(run_metric, …)`` — the exact call the tuner now makes —
    yields the C0 route-(i) values bit-for-bit, under the TIDMAD identity."""
    anchors, s_max = _anchor_inputs()
    with bind_dataset_profile(oracle_fixture["profile"]):
        run_metric = derive_tidmad_metric(resolve_dataset_profile())
        result = _sandbox(oracle_fixture).evaluate_metric(
            run_metric,
            sample_set={FILE_INDEX: [0]},
            anchor_map=anchors,
            s_max=s_max,
            denoised_filename_fn=lambda _fi: oracle_fixture["deliverable_path"],
        )
    assert isinstance(result, MetricResult)
    assert (result.metric_id, result.direction) == (TIDMAD_METRIC_ID, "higher")
    assert result.scalar == EXPECTED_SCALAR
    assert result.per_sample is not None and len(result.per_sample) == EXPECTED_VECTOR_LENGTH
    assert result.per_sample[FILE_INDEX] == EXPECTED_FILE0
    assert result.references_used == ("anchor_map",)


def test_the_legacy_two_tuple_seam_is_unchanged_under_regime_a(oracle_fixture):
    """A caller that predates the handle (``score_vector`` with no ``metric``)
    gets exactly the values it always got — resolved THROUGH the handle now,
    but observably identical (design §12 "regime A deep-equal")."""
    anchors, s_max = _anchor_inputs()
    with bind_dataset_profile(oracle_fixture["profile"]):
        file_vector, scalar = _sandbox(oracle_fixture).score_vector(
            sample_set={FILE_INDEX: [0]},
            anchor_map=anchors,
            s_max=s_max,
            denoised_filename_fn=lambda _fi: oracle_fixture["deliverable_path"],
        )
    assert scalar == EXPECTED_SCALAR
    assert file_vector[FILE_INDEX] == EXPECTED_FILE0
    assert len(file_vector) == EXPECTED_VECTOR_LENGTH


def test_an_unscoreable_deliverable_short_circuits_before_the_arithmetic(
    oracle_fixture, monkeypatch, tmp_path
):
    """The scoreability contract runs FIRST: a missing deliverable raises the
    structured ``NotScoreableError`` and ``scoring_utils.score_vector`` is
    NEVER entered. The spy raises if it is — so this test cannot pass with
    the check moved after (or into) the arithmetic."""

    def _must_not_run(**_kwargs):
        raise AssertionError("score_vector was reached on an unscoreable deliverable set")

    monkeypatch.setattr(su, "score_vector", _must_not_run)
    anchors, s_max = _anchor_inputs()
    with bind_dataset_profile(oracle_fixture["profile"]):
        run_metric = derive_tidmad_metric(resolve_dataset_profile())
        with pytest.raises(NotScoreableError) as excinfo:
            _sandbox(oracle_fixture).evaluate_metric(
                run_metric,
                sample_set={FILE_INDEX: [0]},
                anchor_map=anchors,
                s_max=s_max,
                denoised_filename_fn=lambda _fi: str(tmp_path / "never_written.h5"),
            )
    result = excinfo.value.result
    assert (result.metric_id, result.direction) == (TIDMAD_METRIC_ID, "higher")
    assert result.verdict.contract_id == "tidmad_denoised_h5"
    assert [f.requirement for f in result.verdict.failures] == ["completeness"]
    assert result.verdict.failures[0].input_identity == FILE_INDEX
    assert "never_written.h5" in str(excinfo.value)


def test_scope_validation_still_precedes_scoreability(oracle_fixture):
    """The DataScope boundary invariant is unchanged and still first: an
    out-of-range file index is a ``ValueError`` from ``validate_sample_set``,
    not a scoreability verdict."""
    anchors, s_max = _anchor_inputs()
    with bind_dataset_profile(oracle_fixture["profile"]):
        run_metric = derive_tidmad_metric(resolve_dataset_profile())
        with pytest.raises(ValueError, match="out of range"):
            _sandbox(oracle_fixture).evaluate_metric(
                run_metric,
                sample_set={99: [0]},
                anchor_map=anchors,
                s_max=s_max,
                denoised_filename_fn=lambda _fi: oracle_fixture["deliverable_path"],
            )


def test_stub_sandbox_mirrors_the_seam_under_the_handles_identity(tmp_path):
    """Pseudo mode: ``evaluate_metric`` returns the same synthetic stream
    ``score_vector`` produces (one draw, same RNG), carrying the run's REAL
    identity and direction — TIDMAD or a contrast handle alike."""
    contrast = MetricSpec(
        id="step06_contrast",
        direction="lower",
        aggregation="single_value",
        scoreability=PresenceScoreabilityContract(),
    )

    class _Contrast:
        spec = contrast

    a = StubSandbox(run_name="s6", workspace=str(tmp_path / "a"), file_index=6)
    b = StubSandbox(run_name="s6", workspace=str(tmp_path / "b"), file_index=6)
    a.set_run_context("run-x")
    b.set_run_context("run-x")
    tuple_result = a.score_vector({6: [0]}, {}, 1.0, lambda _fi: "x.h5")
    handle_result = b.evaluate_metric(_Contrast(), {6: [0]}, {}, 1.0, lambda _fi: "x.h5")
    assert isinstance(handle_result, MetricResult)
    assert (handle_result.metric_id, handle_result.direction) == ("step06_contrast", "lower")
    assert (handle_result.per_sample, handle_result.scalar) == tuple_result
    assert len(tuple_result[0]) == 9  # the pseudo contract, unchanged (C0 reference)


# ---------------------------------------------------------------------------
# Who holds this authority — the inverted C1 inertness assertion
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[3]

# Production sites that CONSUME the metric interface. Extended as C3/C4 land;
# a site dropping out of this list means the seam went dead.
MIGRATED_CONSUMERS = (
    "core/sandbox_executor.py",
    "nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py",
    "execute_tools/denoising_score_single.py",  # C3 — the subprocess route
)

# Sites that must NEVER import it. The frozen arithmetic (the handle wraps
# it, it does not know about the handle); the crash-resume reuse guard
# (design §12: NOT the scoreability mechanism); and the direction consumers
# Step 06 explicitly does not reach (§16-Q6 — D1 debt, enumerated at C5).
FORBIDDEN_CONSUMERS = (
    "execute_tools/scoring_utils.py",
    "execute_tools/inference_single.py",
    "workflows/model_exploration.py",
    "core/resume.py",
    "dashboard/data_sources/local_json.py",
    "dashboard/data_sources/base.py",
)


def test_only_the_censused_sites_consume_the_metric_interface():
    """The migrated sites hold the authority; the boundary sites never do.

    Two failure classes: a DEAD SEAM (a consumer reverting to the direct
    scorer call while the handle-level tests keep passing) and a SCOPE
    BREACH (the arithmetic, the reuse guard or a D1 consumer acquiring the
    interface "in passing").
    """
    for relative in MIGRATED_CONSUMERS:
        assert "evaluation_metric" in (REPO_ROOT / relative).read_text(), (
            f"{relative} no longer consumes the metric interface — the seam is dead"
        )
    for relative in FORBIDDEN_CONSUMERS:
        path = REPO_ROOT / relative
        if not path.exists():  # pragma: no cover - the census is current, not eternal
            continue
        assert "evaluation_metric" not in path.read_text(), (
            f"{relative} is outside Step 06's reach and must not consume the metric interface"
        )
