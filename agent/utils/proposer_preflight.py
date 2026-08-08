"""Proposer-side pre-flight wall-time check (Fix 2, Commit 5).

Purpose
-------
Surface a LOW-CONFIDENCE runtime risk signal for a draft proposal
**before** the implementor runs, by asking the static formula from
``evaluate_time_skill`` what the draft config would cost.

C1 authority contract (docs/design/runtime_estimation_and_calibration.md
§8.1, 2026-07-30): this estimate is ``static_uncalibrated`` provenance
and is ADVISORY ONLY. It must never trigger proposal rejection or
revision — the V19 wave-1 incident showed the static formula rejecting
an 18.4M-parameter draft at a fabricated 84.64× factor and locking a
"<400K parameters" constraint into trajectory context. Blocking runtime
authority belongs exclusively to measured evidence (bounded live probe,
in-process verification) via the shared decision policy (C4/C8).

The ``provenance`` / ``advisory_only`` keys returned here are an
INTERIM BRIDGE: they are producer-derived constants of this static
path, not caller-settable policy. C3/C4 replace this dictionary
authority with canonical typed provenance and policy-derived decisions
(``runtime_decision_policy.decide(estimate, budget, mode)``).

Why not call ``evaluate_time_skill.run_skill`` directly
-------------------------------------------------------
``run_skill`` unconditionally calls ``_count_params`` → ``MODEL_REGISTRY
[model_type](config_obj)``. At pre-flight time the draft model class is
not yet implemented, so the lookup ``KeyError``s. We sidestep this by
invoking the three per-phase estimators directly with a caller-supplied
``num_params`` and ``ms_per_step=None`` — every estimator falls through
to its static formula without touching ``MODEL_REGISTRY``.

Contract
--------
``estimate_proposal_time`` is pure and CPU-only:

* No GPU / CUDA required (``ms_per_step=None`` → static fallback,
  ``gpu_name=None`` → Phase F k=1.0).
* No disk I/O (``sample_set`` is synthesised in memory when absent; no
  HDF5 reads, no data_dir).
* No model instantiation (``num_params`` is caller-supplied; the
  unregistered novel architecture is fine).

See ``docs/reliable_resource_proposer.md`` §7 Decision 3 + §9 Commit 5.
"""

from __future__ import annotations

from typing import Any

from agent.skills.denoising_score_skill import estimator as _scoring_est
from agent.skills.inference_skill import estimator as _inference_est
from agent.skills.training_skill import estimator as _training_est
from execute_tools.dataset_config import DataScope
from execute_tools.sample_set_builder import build_sample_set

# The synthesised default ``sample_set`` mirrors the tuner's trial-mode
# snapshot at ``trial_portion=0.1`` — the most common active scope. Seed
# is fixed so the estimate is deterministic across proposer runs.
_DEFAULT_TRIAL_PORTION: float = 0.1
_DEFAULT_TRAIN_PORTION: float = 0.1
_DEFAULT_SAMPLING_SEED: int = 0


def _synthesise_default_sample_set(
    *,
    trial_portion: float = _DEFAULT_TRIAL_PORTION,
    seed: int = _DEFAULT_SAMPLING_SEED,
    scope: DataScope | None = None,
) -> dict[int, list[int]]:
    """Build a representative sample_set without touching disk.

    Every in-scope file × ceil(trial_portion × 200) segments each. Matches
    what the tuner would build in trial/snapshot mode — under a partial
    DataScope (DS7b) the synthetic set covers exactly the scope files, so
    the wall-time estimate reflects what the tuner will actually run.
    """
    return build_sample_set(
        is_trial=True,
        trial_strategy="snapshot",
        trial_portion=trial_portion,
        seed=seed,
        scope=scope,
    )


def _verdict_phrase(feasible: bool, estimated_min: float, budget_min: float) -> str:
    label = "FITS" if feasible else "OVER BUDGET"
    return f"{label} — pre-flight estimate {estimated_min:.1f} min vs budget {budget_min:.1f} min"


def estimate_proposal_time(
    *,
    model_type: str,
    model_config: dict[str, Any],
    train_config: dict[str, Any],
    loss_config: dict[str, Any],
    num_params: int,
    time_budget_minutes: float,
    sample_set: dict[Any, list[int]] | None = None,
    train_portion: float = _DEFAULT_TRAIN_PORTION,
    trial_portion: float = _DEFAULT_TRIAL_PORTION,
    data_scope: DataScope | None = None,
) -> dict[str, Any]:
    """Estimate wall-time for a draft proposal, CPU-only.

    Args:
        model_type: Draft architecture key (e.g. ``"gated_fourier_tcn"``).
                    Only forwarded to the per-phase estimators for the
                    inference-batch soft-fallback; not used to look up
                    ``MODEL_REGISTRY``.
        model_config / train_config / loss_config: The draft's raw config
                    dicts. Must at least contain ``segmentation_size`` /
                    ``batch_size`` / ``epochs`` / ``loss_type`` — missing
                    keys fall back to the per-phase estimator defaults
                    (which are safe but may produce low-fidelity numbers).
        num_params: Exact or estimated parameter count of the draft. The
                    static formula is ``num_params × seg × bs × 6e-10`` so
                    order-of-magnitude accuracy is sufficient for gate-
                    level decisions (e.g. iter 2's 18,772× overshoot reads
                    as ``≫ 1.0`` under any plausible num_params).
        time_budget_minutes: The active-mode budget the draft is checked
                    against. Usually ``ProposalInput.trial_time_budget_minutes``
                    in trial mode.
        sample_set: ``{file_index: [segment_indices]}``. None → a sample_set
                    is synthesised at ``trial_portion`` so the estimate
                    reflects the caller's active scope without disk I/O.
        train_portion: Per-epoch subsample fraction applied to
                    ``sample_set``. Default 0.1 mirrors
                    ``HyperparamTuningInput.train_portion``.
        trial_portion: Fraction of segments per file when synthesising the
                    default sample_set. Mirrors
                    ``HyperparamTuningInput.trial_portion`` /
                    ``ProposalInput.trial_portion``. Ignored if the caller
                    passes an explicit ``sample_set``. Without this kwarg
                    the gate would assume snapshot@0.1 regardless of the
                    caller's actual scope, producing 5× over-projection
                    when callers set ``trial_portion=0.02``.

    Returns:
        ``{"estimated_minutes": float, "factor": float, "verdict": str,
           "feasible": bool, "provenance": "static_uncalibrated",
           "advisory_only": True}``. ``factor = estimated_minutes /
        time_budget_minutes``. ``provenance`` and ``advisory_only`` are
        constants of this static producer (see the module docstring):
        callers must treat the result as advisory evidence and must not
        derive blocking behavior from it.

    Raises:
        ValueError: ``num_params`` ≤ 0 or ``time_budget_minutes`` ≤ 0.
                    Silent fail-open to ``factor=0.0`` would defeat the
                    whole gate.
    """
    if num_params <= 0:
        raise ValueError(
            f"num_params must be positive; got {num_params!r}. "
            "The pre-flight static formula cannot yield a meaningful "
            "estimate without a parameter count — if unavailable, the "
            "caller should skip the gate rather than invoke it with 0."
        )
    if time_budget_minutes <= 0:
        raise ValueError(f"time_budget_minutes must be positive; got {time_budget_minutes!r}.")

    if sample_set is None:
        sample_set = _synthesise_default_sample_set(trial_portion=trial_portion, scope=data_scope)

    loss_type = _training_est.resolve_loss_type(loss_config)

    # All three estimators run in static-formula mode: ms_per_step=None
    # + gpu_name=None → training estimator skips MODEL_REGISTRY.
    training = _training_est.estimate_wall_time_seconds(
        model_type,
        model_config,
        train_config,
        sample_set,
        train_portion=train_portion,
        ms_per_step=None,
        gpu_name=None,
        num_params=num_params,
        loss_type=loss_type,
    )
    inference = _inference_est.estimate_wall_time_seconds(
        model_type,
        model_config,
        sample_set,
        inference_ms_per_step=None,
        num_params=num_params,
    )
    scoring = _scoring_est.estimate_wall_time_seconds(sample_set)

    total_sec = training["seconds"] + inference["seconds"] + scoring["seconds"]
    total_min = total_sec / 60.0
    factor = total_min / time_budget_minutes
    feasible = total_min <= time_budget_minutes

    return {
        "estimated_minutes": round(total_min, 2),
        "factor": round(factor, 3),
        "verdict": _verdict_phrase(feasible, total_min, time_budget_minutes),
        "feasible": feasible,
        # Producer-derived constants of the static path — NOT caller-settable
        # policy (interim bridge until C3/C4 typed provenance; see module
        # docstring).
        "provenance": "static_uncalibrated",
        "advisory_only": True,
    }
