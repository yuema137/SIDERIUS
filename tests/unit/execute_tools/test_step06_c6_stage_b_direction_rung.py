"""Step 06 — C6: Stage-B rung — the metric-DIRECTION axis through the handle.

Design: ``docs/design/generic_framework_upgrade/step_06_metric_interface.md``
§11 (Stage B), §19 C6; roadmap §10.5, §21.4 (an ATOMIC fixture on the
learning-objective dimension at TIDMAD's topology).

Two rungs, kept apart after the adversarial review (ledger §20.11):

**C6a — the STRICT one-axis direction flip.** The TIDMAD instance itself —
same ``TidmadDenoisingMetric`` arithmetic, same ``TidmadScoreabilityContract``,
same references, same per-sample evidence, same aggregation id — with ONLY
``direction`` flipped ``higher → lower`` (and the id renamed so the record can
tell the two apart). Same deliverable in, same scalar and ``file_vector`` out;
only the declared direction differs on the ``MetricResult`` and the record.
That is the roadmap §10.5 / §21.4 atomic learning-objective fixture at
TIDMAD's topology.

**C6b — the broader different-metric rung.** ``MeanAbsAmplitudeMetric``: a
scalar-only, ``direction="lower"``, presence-contract metric with different
arithmetic — proving the seam, the loop and the record carry a MATERIALLY
different metric end to end (scalar-only + different computation + weak
contract). It varies several axes at once and is deliberately NOT the
one-axis evidence.

Both run through the REAL ``TidmadSandbox.evaluate_metric`` seam on the C0
deliverable and through the PRODUCTION loop (Step-00 pseudo harness) with
the run-scope derivation swapped ONLY on the first (binding) call; the
negative shows an unpatched run carries TIDMAD / ``higher`` and nothing else.

Deliberately NOT here: incumbent selection under the contrast (Step 07a),
image / spatiotemporal topology (§21.3 — Step 06 attaches the cheapest grade),
task-level declaration (Step 12).
"""

from __future__ import annotations

import importlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import h5py
import numpy as np

from core.sandbox_executor import TidmadSandbox
from execute_tools.dataset_config import TIDMAD_PROFILE, bind_dataset_profile
from execute_tools.evaluation_metric import (
    TIDMAD_METRIC_ID,
    EvaluationMetric,
    MetricResult,
    MetricSpec,
    PresenceScoreabilityContract,
    TidmadDenoisingMetric,
    TidmadScoreabilityContract,
    derive_tidmad_metric,
    derive_tidmad_metric_spec,
)
from tests.helpers.metric_fixtures import (
    CONTRAST_ID,
    DIRECTION_ONLY_ID,
    direction_only_metric,
)
from tests.helpers.step00_pseudo_iteration import run_bounded_pseudo_iteration
from tests.unit.core.test_step06_c0_two_route_oracle import (
    FILE_INDEX,
    RUN_NAME,
    oracle_fixture,
)

_TUNER = importlib.import_module("nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent")
_PREFLIGHT_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "agent"
    / "tune_ml_hyperparam_agent"
    / "fixtures"
    / "step00_preflight_results.json"
)

# Step 07 PR 07b promoted both the ids and the C6a factory to
# ``tests/helpers/metric_fixtures.py`` so its own direction rungs bind the SAME
# one-axis handle. The names below stay this module's vocabulary.
_direction_only_metric = direction_only_metric


class MeanAbsAmplitudeMetric(EvaluationMetric):
    """A scalar-only, LOWER-is-better metric on the same deliverable.

    Reads the denoised channel and returns the mean absolute int8 amplitude —
    a global statistic (no per-sample vector) where smaller is better. Not
    a scientific claim: an atomic direction fixture (roadmap §21.4).
    """

    def _compute(
        self, deliverables: Mapping[int, str], /, **_kwargs: Any
    ) -> tuple[float, list[float | None] | None, tuple[str, ...]]:
        values = []
        for path in deliverables.values():
            with h5py.File(path, "r") as handle:
                data = handle["timeseries/channel0001/timeseries"][:1_000_000]
                values.append(float(np.mean(np.abs(np.asarray(data, dtype=np.float64)))))
        return float(np.mean(values)), None, ()


def _contrast_metric() -> MeanAbsAmplitudeMetric:
    return MeanAbsAmplitudeMetric(
        MetricSpec(
            id=CONTRAST_ID,
            direction="lower",
            aggregation="mean_over_deliverables",
            scoreability=PresenceScoreabilityContract(),
        )
    )


# ---------------------------------------------------------------------------
# C6a — the STRICT one-axis direction flip
# ---------------------------------------------------------------------------


def test_c6a_only_the_direction_differs_from_the_shipped_spec():
    """By construction AND asserted: every MetricSpec field except ``id`` and
    ``direction`` is identical to the shipped TIDMAD instance — same
    aggregation id, transform (+params), references and the SAME scoreability
    contract (``TidmadScoreabilityContract`` with equal requirements)."""
    shipped = derive_tidmad_metric_spec(TIDMAD_PROFILE)
    flipped = _direction_only_metric().spec
    assert (shipped.direction, flipped.direction) == ("higher", "lower")
    assert (shipped.id, flipped.id) == (TIDMAD_METRIC_ID, DIRECTION_ONLY_ID)
    for field in ("aggregation", "transform", "transform_params", "references"):
        assert getattr(flipped, field) == getattr(shipped, field), field
    assert isinstance(flipped.scoreability, TidmadScoreabilityContract)
    assert flipped.scoreability == shipped.scoreability


def test_c6a_same_deliverable_same_values_only_the_direction_flips(oracle_fixture):
    """Through the REAL seam on the C0 deliverable: the flipped instance
    returns the SAME scalar and the SAME per-file vector as the shipped
    instance (same arithmetic reached through the same contract) — only
    ``direction`` (and the id) differ on the result."""
    from tests.unit.core.test_step06_c0_two_route_oracle import (
        EXPECTED_FILE0,
        EXPECTED_SCALAR,
        _anchor_inputs,
    )

    anchors, s_max = _anchor_inputs()
    with bind_dataset_profile(oracle_fixture["profile"]):
        sandbox = TidmadSandbox(
            run_name=RUN_NAME, workspace=str(oracle_fixture["workspace"]), file_index=FILE_INDEX
        )
        kwargs = dict(
            sample_set={FILE_INDEX: [0]},
            anchor_map=anchors,
            s_max=s_max,
            denoised_filename_fn=lambda _fi: oracle_fixture["deliverable_path"],
        )
        shipped = sandbox.evaluate_metric(derive_tidmad_metric(oracle_fixture["profile"]), **kwargs)
        flipped = sandbox.evaluate_metric(
            _direction_only_metric(oracle_fixture["profile"]), **kwargs
        )
    assert isinstance(shipped, MetricResult) and isinstance(flipped, MetricResult)
    assert flipped.scalar == shipped.scalar == EXPECTED_SCALAR
    assert flipped.per_sample == shipped.per_sample
    assert flipped.per_sample is not None and flipped.per_sample[FILE_INDEX] == EXPECTED_FILE0
    assert flipped.references_used == shipped.references_used == ("anchor_map",)
    assert (shipped.direction, flipped.direction) == ("higher", "lower")
    assert (shipped.metric_id, flipped.metric_id) == (TIDMAD_METRIC_ID, DIRECTION_ONLY_ID)


def test_c6a_the_flipped_direction_enters_the_record_through_the_live_route(tmp_path, monkeypatch):
    """Production loop (Step-00 pseudo harness): with the run-scope binding
    swapped for the direction-only instance, every success record's payload
    carries ``direction="lower"`` and the flipped id, with ``scalar ==
    denoising_score`` — the same record mechanics, one axis moved."""
    # Step 12 / PR-12d seam B: the run-scope resolution moved into
    # `evaluation_metric.resolve_run_metric` (the spec became optional at
    # B11 and `run()` is branch-capped). The stub follows the resolution
    # to its new owner; the question this test asks is unchanged.
    shipped_derivation = _TUNER.resolve_run_metric
    derivations: list[int] = []

    def _bind_once(*args, **kwargs):
        derivations.append(1)
        return (
            _direction_only_metric(*args[:1])
            if len(derivations) == 1
            else shipped_derivation(*args, **kwargs)
        )

    monkeypatch.setattr(_TUNER, "resolve_run_metric", _bind_once)
    output, _bridge, _sandbox, _ws = run_bounded_pseudo_iteration(
        tmp_path, monkeypatch, preflight_results=_preflight()
    )
    successes = [r for r in output.all_records if r.status == "success"]
    assert successes
    for record in successes:
        assert record.metric_result is not None
        assert (record.metric_result.metric_id, record.metric_result.direction) == (
            DIRECTION_ONLY_ID,
            "lower",
        )
        assert record.metric_result.scalar == record.denoising_score
    assert len(derivations) == 1


# ---------------------------------------------------------------------------
# C6b — the broader different-metric rung, through the REAL seam
# ---------------------------------------------------------------------------


def test_a_lower_is_better_scalar_only_metric_runs_through_the_real_seam(oracle_fixture):
    with bind_dataset_profile(oracle_fixture["profile"]):
        sandbox = TidmadSandbox(
            run_name=RUN_NAME, workspace=str(oracle_fixture["workspace"]), file_index=FILE_INDEX
        )
        result = sandbox.evaluate_metric(
            _contrast_metric(),
            sample_set={FILE_INDEX: [0]},
            anchor_map={},
            s_max=1.0,
            denoised_filename_fn=lambda _fi: oracle_fixture["deliverable_path"],
        )
    assert isinstance(result, MetricResult)
    assert (result.metric_id, result.direction) == (CONTRAST_ID, "lower")
    assert result.per_sample is None and result.references_used == ()
    assert 0.0 < result.scalar < 127.0  # a mean |int8| amplitude, finite and in range
    # The shipped instance is untouched in the same process (one axis moved).
    shipped = derive_tidmad_metric(TIDMAD_PROFILE).spec
    assert (shipped.id, shipped.direction) == (TIDMAD_METRIC_ID, "higher")


# ---------------------------------------------------------------------------
# 2. Through the PRODUCTION loop — the record payload carries the contrast
# ---------------------------------------------------------------------------


def _preflight():
    return json.loads(_PREFLIGHT_FIXTURE.read_text(encoding="utf-8"))["results"]


def test_the_contrast_enters_the_record_through_the_live_route(tmp_path, monkeypatch):
    # Step 12 / PR-12d seam B: the run-scope resolution moved into
    # `evaluation_metric.resolve_run_metric` (the spec became optional at
    # B11 and `run()` is branch-capped). The stub follows the resolution
    # to its new owner; the question this test asks is unchanged.
    shipped_derivation = _TUNER.resolve_run_metric
    derivations: list[int] = []

    def _bind_once(*args, **kwargs):  # contrast at run scope only (see C2 binding test)
        derivations.append(1)
        return _contrast_metric() if len(derivations) == 1 else shipped_derivation(*args, **kwargs)

    monkeypatch.setattr(_TUNER, "resolve_run_metric", _bind_once)
    output, _bridge, _sandbox, _ws = run_bounded_pseudo_iteration(
        tmp_path, monkeypatch, preflight_results=_preflight()
    )
    successes = [r for r in output.all_records if r.status == "success"]
    assert successes
    for record in successes:
        assert record.metric_result is not None
        assert (record.metric_result.metric_id, record.metric_result.direction) == (
            CONTRAST_ID,
            "lower",
        )
        assert record.metric_result.scalar == record.denoising_score
    assert len(derivations) == 1
    # Same process, shipped DERIVATION: still TIDMAD / higher. Asked of
    # `derive_tidmad_metric` rather than of `shipped_derivation`, because
    # PR-12d seam B made the latter the RESOLVER — which takes the run's
    # deliverable spec as well. The claim is about the derivation being
    # untouched by the run-scope swap, and that is what this asks.
    shipped = derive_tidmad_metric(TIDMAD_PROFILE).spec
    assert (shipped.id, shipped.direction) == (TIDMAD_METRIC_ID, "higher")


def test_the_rung_does_not_fire_on_the_shipped_instance(tmp_path, monkeypatch):
    """Negative: an unpatched run carries TIDMAD / higher on every scored
    record and no contrast identity anywhere — so the positive above cannot
    pass because a seam returns the contrast unconditionally."""
    output, _bridge, sandbox, _ws = run_bounded_pseudo_iteration(
        tmp_path, monkeypatch, preflight_results=_preflight()
    )
    payloads = [r.metric_result for r in output.all_records if r.metric_result is not None]
    assert payloads
    assert {(p.metric_id, p.direction) for p in payloads} == {(TIDMAD_METRIC_ID, "higher")}
    assert not [c for c in sandbox.calls if c and c[0] == "evaluate_metric" and c[1] == CONTRAST_ID]
