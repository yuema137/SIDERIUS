"""V21 PR C3b — absence from the inference-batch table must stay harmless.

Operator decision **O-C-2** split `core/inference_defaults.py` by *causal
responsibility* rather than by file:

    PR C   any use of ``is_inference_batch_registered`` that changes
           calibration, admission or reachability
    PR G   ``inference_batch_for`` when it only chooses the actual
           inference batch, i.e. throughput

C3b audited the consumers first, as instructed, and the finding is
**negative**: the invariant PR C was asked to establish is already true.

    generated model has no hand-maintained name-table entry
         !=  uncalibrated or degraded admission semantics

Two measured facts make it true, and each is one edit away from becoming
false — which is why this module exists. Nothing here changes production
code; it pins a property that currently holds.

1. **The planning estimate and the runtime execution call the same
   function**, so an unregistered model is forecast with exactly the batch
   it will actually run with. The forecast is *unhand-tuned*, not *wrong*.
   If someone gave the estimator its own fallback, the forecast would
   diverge from reality and the flag's name would finally be accurate — as
   an admission defect.

2. **The ``inference_batch_uncalibrated`` flag reaches only observability
   surfaces.** It becomes a ``RuntimeEstimate.warnings`` entry and a record
   field. Every use of ``warnings`` in the runtime-control package is a
   *producer*; none is a predicate. If a gate ever started reading it, an
   unregistered name would begin deciding admission.

See the PR C design doc §C3b.
"""

from __future__ import annotations

import pytest

from agent.skills.inference_skill import estimator as inference_estimator
from core.inference_defaults import inference_batch_for, is_inference_batch_registered
from execute_tools.dataset_config import TIDMAD_PROFILE

_UNREGISTERED = "c3b_generated_model_with_no_batch_entry"


def test_planning_and_runtime_agree_on_the_batch_for_an_unregistered_model():
    """The forecast must describe the run that will actually happen.

    ``sandbox_executor.execute_inference`` falls back to
    ``inference_batch_for(model_type)`` (``:1543``) and the planning
    estimator calls the same function, so the two cannot drift while this
    holds.

    Fails if: the estimator grows its own fallback constant, or the runtime
    fallback changes without the estimator following. Either turns a
    harmless "nobody tuned a batch for this model" into a real
    forecast-vs-reality mismatch feeding admission.
    """
    runtime_batch = inference_batch_for(_UNREGISTERED)
    estimate = inference_estimator.estimate_peak_bytes(
        _UNREGISTERED, {"segmentation_size": 4000}, 1000
    )
    assert estimate["breakdown"]["inference_batch"] == runtime_batch


def test_planning_and_runtime_agree_on_the_batch_for_a_hinted_model():
    """V21 PR G G2 extension of the pin above (PR G doc §0.D).

    The original test pins the NO-HINT pair (both sides call
    ``inference_batch_for``). On the live agent path both sides now
    prefer the probed hint: ``sandbox_executor.execute_inference``
    treats a non-None ``inference_batch`` as the authoritative runtime
    batch (``:1543``), and the wall-time forecast prices at the same
    explicit value via ``resolve_forecast_batch``. This test pins the
    forecast side's hint-preference and its fallback being the SAME
    function the executor falls back to — so the two resolution rules
    cannot drift in either regime. End-to-end transport equality (the
    same ``active_params`` value reaching both skills in one attempt)
    is pinned by
    ``tests/integration/workflows/test_g2_forecast_runtime_batch_pseudo.py``
    and the delete-the-hop test in
    ``tests/unit/agent/tune_ml_hyperparam_agent/test_g2_time_gate_probed_batch.py``.

    Fails if: the forecast resolver stops preferring the hint, or its
    no-hint fallback stops matching the executor's fallback function.
    """
    hint = 64  # unlike the fallback (25) and every builtin entry
    assert inference_estimator.resolve_forecast_batch(hint, _UNREGISTERED) == hint
    forecast = inference_estimator.estimate_wall_time_seconds(
        _UNREGISTERED,
        {"segmentation_size": 4000},
        {"0": [0]},
        inference_ms_per_step=1.0,
        inference_batch=hint,
        dataset_profile=TIDMAD_PROFILE,
    )
    assert forecast["breakdown"]["inference_batch"] == hint

    # No-hint regime: forecast fallback == runtime fallback, same function.
    assert inference_estimator.resolve_forecast_batch(None, _UNREGISTERED) == inference_batch_for(
        _UNREGISTERED
    )


def test_the_uncalibrated_flag_is_raised_but_changes_nothing_in_the_estimate():
    """The flag reports; it must not price.

    An unregistered and a registered model given the *same* batch must
    produce the *same* numbers — the flag is metadata beside the estimate,
    not an input to it. A "safety" multiplier applied to uncalibrated
    models would be a name-keyed admission penalty wearing a different hat.

    Fails if: anything starts scaling the estimate by the flag.
    """
    unregistered = inference_estimator.estimate_peak_bytes(
        _UNREGISTERED, {"segmentation_size": 4000}, 1000
    )
    assert unregistered["breakdown"]["inference_batch_uncalibrated"] is True
    assert is_inference_batch_registered(_UNREGISTERED) is False

    # A registered model that happens to share the same batch size.
    registered = inference_estimator.estimate_peak_bytes("punet", {"segmentation_size": 4000}, 1000)
    assert registered["breakdown"]["inference_batch_uncalibrated"] is False

    if registered["breakdown"]["inference_batch"] == unregistered["breakdown"]["inference_batch"]:
        assert registered["total_bytes"] == unregistered["total_bytes"], (
            "same batch, same params, same shape — the only difference is the "
            "calibration FLAG, so the estimates must be identical. A divergence "
            "means the flag has become a pricing input."
        )


def test_the_flag_reaches_warnings_and_nothing_reads_warnings_to_decide():
    """Pins the observability boundary that keeps O-C-2's split valid.

    ``from_time_eval_result`` folds the flag into
    ``RuntimeEstimate.warnings``. Warnings are carried and appended to
    across the runtime-control package but never branched on, which is the
    entire reason this is PR G's module and not PR C's.

    Asserted structurally: the flag lands in ``warnings`` and leaves the
    decision-bearing fields untouched.
    """
    from core.runtime_control.estimate_types import from_time_eval_result

    base = {
        "status": "success",
        "feasible": True,
        "estimated_minutes": 10.0,
        "breakdown": {"source": "real_dataset_warmup"},
        "phase_breakdown": {
            "training": {"seconds": 400.0},
            "inference": {"seconds": 200.0},
        },
    }

    quiet = from_time_eval_result({**base, "inference_batch_uncalibrated": False})
    noisy = from_time_eval_result(
        {**base, "inference_batch_uncalibrated": "inference_batch_uncalibrated: fallback 25"}
    )

    # The flag shows up where humans read it...
    assert quiet.warnings == ()
    assert len(noisy.warnings) == 1
    assert "fallback 25" in noisy.warnings[0]

    # ...and nowhere that prices or gates the candidate.
    for field in ("provenance", "confidence", "expected_seconds"):
        assert getattr(quiet, field) == getattr(noisy, field), (
            f"{field} differs between a calibrated and an uncalibrated estimate — "
            "the flag has stopped being observability-only, and an unregistered "
            "model name now influences admission (PR C scope, per O-C-2)."
        )


@pytest.mark.parametrize("model_type", ["punet", "wavenet", "fcnet", "rnn", "transformer"])
def test_registered_builtins_are_still_reported_as_calibrated(model_type):
    """Guards the lazy over-fix of deleting the table to silence the flag.

    Deleting ``_INFERENCE_BATCH_SIZES`` would make every model "calibrated"
    by making none of them calibrated, and would silently change the actual
    batch used for five built-ins — including ``transformer``, whose entry
    is 1 rather than 25 for a real memory reason.
    """
    assert is_inference_batch_registered(model_type) is True
