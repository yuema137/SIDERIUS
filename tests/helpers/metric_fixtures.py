"""Shared golden-metric fixtures for direction-axis tests.

Promoted from ``tests/unit/execute_tools/test_step06_c6_stage_b_direction_rung.py``
by Step 07 PR 07b (design §3.11): 07b's strict ordering rung (B-07b-1), its
policy-semantics rung (B-07b-1s) and its rendering rung (B-07b-2) all need the
same one-axis ``lower`` handle Step 06 already built, and a second private copy
would be a second fixture that could silently drift from the shipped spec.

The Step-06 module keeps its own names and imports them from here, so its rung
still tests exactly what it tested before.
"""

from __future__ import annotations

from execute_tools.evaluation_metric import (
    EvaluationMetric,
    MetricSpec,
    PresenceScoreabilityContract,
)

#: The one-axis ``lower`` variant of the shipped TIDMAD spec (Step 06 C6a).
DIRECTION_ONLY_ID = "step06_tidmad_denoising_score_lower"

#: A materially different metric: scalar-only, ``lower``, presence contract.
CONTRAST_ID = "step06_mean_abs_amplitude"


def shipped_spec(profile=None) -> MetricSpec:
    """A stable higher-is-better fixture with no scientific task dependency."""
    del profile
    return MetricSpec(
        id="tidmad_denoising_score",
        direction="higher",
        aggregation="fixture_aggregate",
        transform="log",
        transform_params={"log_base": 5.27},
        references=("fixture_reference",),
        scoreability=PresenceScoreabilityContract(),
    )


def direction_only_spec(profile=None) -> MetricSpec:
    """The shipped TIDMAD spec with ONLY ``direction`` (and the id) changed.

    Everything else — scoreability contract, references, transform,
    aggregation — is the shipped instance's, by construction from
    ``model_copy``. That is what makes a test built on it a ONE-AXIS rung: a
    difference in behaviour cannot be attributed to anything but the declared
    direction.
    """
    return shipped_spec(profile).model_copy(update={"id": DIRECTION_ONLY_ID, "direction": "lower"})


class _FixtureMetric(EvaluationMetric):
    def _compute(self, deliverables, /, **compute_kwargs):
        del deliverables, compute_kwargs
        return 0.0, None, ()


def direction_only_metric(profile=None) -> EvaluationMetric:
    """:func:`direction_only_spec` bound to inert fixture arithmetic."""
    return _FixtureMetric(direction_only_spec(profile))


def accuracy_like_spec(metric_id: str = "fixture_accuracy") -> MetricSpec:
    """A ``higher``-is-better metric on [0, 1] — an accuracy-shaped scale.

    Deliberately NOT TIDMAD-shaped: its values live where a TIDMAD-tuned
    default (a ``-1.0`` dB margin, a raw ``best - 0.05`` band) is obviously
    wrong, which is what makes it usable as a scale-axis fixture.
    """
    return MetricSpec(
        id=metric_id,
        direction="higher",
        aggregation="mean_over_deliverables",
        scoreability=PresenceScoreabilityContract(),
    )


def accuracy_like_metric(metric_id: str = "fixture_accuracy") -> EvaluationMetric:
    """An inert metric handle for run-binding tests on a neutral scale."""
    return _FixtureMetric(accuracy_like_spec(metric_id))


def error_like_spec(metric_id: str = "fixture_mse") -> MetricSpec:
    """A ``lower``-is-better metric near 0 — an MSE-shaped scale."""
    return MetricSpec(
        id=metric_id,
        direction="lower",
        aggregation="mean_over_deliverables",
        scoreability=PresenceScoreabilityContract(),
    )
