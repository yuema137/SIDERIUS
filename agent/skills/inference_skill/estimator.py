"""
agent/skills/inference_skill/estimator.py

Per-phase VRAM and wall-time estimator for the INFERENCE phase. Called
by the resource aggregators (K.2.5). Inference is a *dependent* phase:
same architecture, same ``model_config`` as training. The only
dedicated lever — ``inference_batch`` — is hard-coded in
``core/inference_defaults.py``, so the planner cannot move this phase
independently of the training-side config it already adjusted.

Key differences from training VRAM:
  * weights only (×4 B) — no grads, no Adam m/v.
  * activations ≈ 1× output logits (no backward storage).
  * no focal one_hot — loss is not computed at inference.
  * batch = ``inference_batch_for(model_type)`` (NOT ``train.batch_size``).

Key differences from training wall time:
  * total_steps = ``ceil(n_segments / inference_batch)``; no epochs,
    no train_portion (we run once over the eval set).
  * Phase F's ``k(gpu, model_type)`` correction is NOT applied —
    inference ms/step was never calibrated.
  * Static fallback: training-static formula scaled down by
    ``_INFERENCE_VS_TRAINING_RATIO`` to reflect "no backward pass".

Contract (K.2.5 Commit 3, revised by K.2.5-8 on 2026-04-18). Both
entry points used to call ``assert_inference_batch_registered`` first
to crash loudly on unregistered model types. K.8.1 surfaced that this
crashed every gate the proposer triggered on an invented model_type
(`pe_wavenet_delta`), bypassing K.7's gate-exhaustion feedback loop.

K.2.5-8 replaces the hard-fail with a soft fallback that matches the
runtime behaviour: ``inference_batch_for(model_type)`` is called
unconditionally (silent fallback to 25 for unknown model types), and
the substitution is surfaced as an ``inference_batch_uncalibrated:
bool`` flag in the returned ``breakdown`` dict. Callers
(``evaluate_vram_skill`` / ``evaluate_time_skill`` wrappers) emit a
prominent warning when the flag is set and propagate it into
``ExperimentMemory`` for post-hoc audit. The architecture-level
activation estimate remains uncalibrated for novel models — that
limitation is documented in §10.14 K.2.5-8 ("Limitations").

See docs/resource_estimator_implement.md §10.5 + §10.14 Commit 3 +
§10.14 K.2.5-8.
"""

from __future__ import annotations

import math
from typing import Any

from core.inference_defaults import (
    inference_batch_for,
    is_inference_batch_registered,
)
from execute_tools.dataset_config import SEGMENT_LENGTH as PSD_SEGMENT_LENGTH

_BYTES_F32 = 4

# Inference has no backward pass; training ms/step includes bwd (~2×
# fwd) + optimizer step + loss overhead. 1/3 is the rough working ratio
# used by the static fallback and by the aggregator when it derives an
# inference ms/step from a training-warmup measurement.
# Recalibrated 2026-04-30: Spectral TCN architectures exhibit heavy
# inference overhead (non-linear FFT/Memory-bound) exceeding training
# ms/step. Data-driven median across V7 formal-success records:
#
#   arch                          params    train_ms  inf_ms  ratio
#   fft_fused_cyclic_tcn          22 K        10.4    15.0    1.45
#   gated_context_dualpath_tcn   902 K        19.7    53.6    2.72
#                                                            -------
#                                                     median  2.72
#
# 2.7 matches the empirical median; the gate will under-predict for
# archs with ratio > 2.7 and over-predict for those below, by at most
# ~2× in either direction across the observed range. This is a blunt
# constant — a per-arch ms/step model would be the structurally correct
# fix, but N=2 datapoints don't justify one yet. Pending more formal
# successes to widen the calibration set. Tracked in docs/memories/.
_INFERENCE_VS_TRAINING_RATIO: float = 2.7

# Same 6e-10 ms/flop baseline as the training static formula. Scaled
# down by the training-vs-inference ratio below to approximate the
# missing backward pass.
_STATIC_MS_PER_FLOP: float = 6e-10


# ── VRAM ─────────────────────────────────────────────────────────────────────


def resolve_forecast_batch(explicit: int | None, model_type: str) -> int:
    """The batch the wall-time forecast prices at.

    An explicit override when the caller supplies one, else the registry
    default (``inference_batch_for`` — the K.2.5-8 silent fallback to 25 for
    unregistered model types).

    V21 PR G — the forecast prices at the batch the runtime will ACTUALLY
    run: the probe-derived value in ``active_params["inference_batch"]``,
    which the tuner's time gate has always forwarded wholesale
    (``_run_time_preflight`` splats ``**active_params``) and the time-skill
    wrapper now consumes and passes down here — restoring forecast==runtime
    coherence on the ``training_warmup_x2.7`` path. With ``explicit is
    None`` (every no-hint caller: baselines, legacy scripts, proposer
    advisory) the result is byte-identical to pre-G1 behaviour. An invalid
    override is rejected loudly — never silently clamped or fallen back
    (fail-closed).
    """
    if explicit is None:
        return inference_batch_for(model_type)
    # bool is an int subclass; a True/False batch is a caller bug, not 1/0.
    if isinstance(explicit, bool) or not isinstance(explicit, int) or explicit <= 0:
        raise ValueError(f"inference_batch override must be a positive int; got {explicit!r}.")
    return explicit


def estimate_peak_bytes(
    model_type: str,
    model_config: dict[str, Any],
    num_params: int,
) -> dict[str, Any]:
    """Estimate peak inference-phase VRAM.

    NOTE (V21 PR G): this VRAM entry point takes NO explicit-batch override.
    It is production-dead on the forecast path — the live VRAM gate probes
    the batch directly (``evaluate_vram_skill``) rather than pricing it from
    this formula (§0.R.2) — so the G1 seam is added only to the wall-time
    entry point below. It still reports ``inference_batch`` for audit.

    Worst-case float32 inference memory:
      * weights:           ``num_params × 4 B`` (no grads / Adam)
      * output logits:     ``inf_batch × 256 × T × 4``
      * activations (fwd): ``1 × output_logits``  (no backward storage)
      * transformer attn:  ``inf_batch × nhead × T² × 4 × num_layers``

    Args:
        model_type:   Model architecture key.
        model_config: Model configuration dict (``segmentation_size``,
                      optional ``nhead`` / ``num_layers`` for transformer).
        num_params:   Exact parameter count from a prior CPU instantiation.

    Returns:
        ``{"phase": "inference", "total_bytes": int, "breakdown": {...}}``.
        ``breakdown.inference_batch_uncalibrated`` is ``True`` when
        ``model_type`` has no entry in ``_INFERENCE_BATCH_SIZES`` and
        the runtime fallback (25) was substituted (K.2.5-8). Callers
        should surface this flag prominently — the per-sample
        activation model is uncalibrated for the novel architecture.
    """
    inference_batch_uncalibrated = not is_inference_batch_registered(model_type)
    inf_batch = inference_batch_for(model_type)

    # V21 PR B1 — resolved against the model's declaration; the margin is
    # the memory-conservative direction. See the training estimator.
    from agent.skills.training_skill.estimator import resolve_model_field

    seg_size = resolve_model_field(
        model_type, model_config, "segmentation_size", safety_margin=40000
    )

    weights = num_params * _BYTES_F32
    output_logits = inf_batch * 256 * seg_size * _BYTES_F32
    activations = output_logits  # 1× at inference (no backward storage)

    # V21 PR C3 — was ``if model_type == "transformer"``. The term models
    # attention matrices, which exist iff the architecture HAS attention, so
    # the truthful predicate is whether the model's own config declares
    # attention parameters. Byte-identical for the six built-ins
    # (``transformer`` is the only one declaring ``nhead``), and strictly
    # MORE conservative for a generated attention model, which previously
    # received a zero attention term purely for not being named
    # "transformer" — an optimistic estimate that could admit a candidate
    # which then OOMs. See the training estimator for the same change.
    from agent.skills.training_skill.estimator import attention_shape

    transformer_attn = 0
    _attn = attention_shape(model_type, model_config)
    if _attn is not None:
        nhead, num_layers = _attn
        transformer_attn = inf_batch * nhead * seg_size * seg_size * _BYTES_F32 * num_layers

    total = weights + output_logits + activations + transformer_attn

    return {
        "phase": "inference",
        "total_bytes": total,
        "breakdown": {
            "weights_bytes": weights,
            "output_logits_bytes": output_logits,
            "activations_bytes": activations,
            "transformer_attn_bytes": transformer_attn,
            "inference_batch": inf_batch,
            "inference_batch_uncalibrated": inference_batch_uncalibrated,
        },
    }


# ── Wall time ────────────────────────────────────────────────────────────────


def _total_inference_steps(
    sample_set: dict[str, list[int]],
    seg_size: int,
    inf_batch: int,
) -> int:
    """Total forward-only step count to score the whole eval ``sample_set``."""
    n_psd = sum(len(v) for v in sample_set.values())
    ml_per_psd = PSD_SEGMENT_LENGTH // seg_size
    total_ml = n_psd * ml_per_psd
    return math.ceil(total_ml / max(inf_batch, 1))


def _static_inference_ms_per_step(
    num_params: int,
    seg_size: int,
    inf_batch: int,
) -> float:
    """Static ms/step fallback. Training-side formula scaled by the
    no-backward-pass ratio."""
    return num_params * seg_size * inf_batch * _STATIC_MS_PER_FLOP * _INFERENCE_VS_TRAINING_RATIO


def _count_params(model_type: str, model_config: dict) -> int:
    """Instantiate the model on CPU. Module-level for monkeypatching."""
    from ml_models.models_format_sandbox import get_config_class

    config_cls = get_config_class(model_type)
    if config_cls is None:
        raise ValueError(
            f"_count_params: unknown model_type={model_type!r} — "
            f"get_config_class returned None (no plugin or built-in config registered)."
        )
    config_obj = config_cls(**model_config)
    # V21 PR C3 — was ``if model_type == "fcnet"``. Some model classes take
    # ``loss_type`` at construction because their head shape depends on it;
    # that is a real constructor API difference, detected by introspecting
    # the signature rather than by matching a name. ``num_params`` is
    # invariant under the choice, so the safe default is still passed.
    from agent.skills.training_skill.estimator import _instantiate_for_param_count

    model = _instantiate_for_param_count(model_type, config_obj, "ce")
    return sum(p.numel() for p in model.parameters())


def estimate_wall_time_seconds(
    model_type: str,
    model_config: dict[str, Any],
    sample_set: dict[str, list[int]],
    *,
    inference_ms_per_step: float | None = None,
    num_params: int | None = None,
    inference_batch: int | None = None,
) -> dict[str, Any]:
    """Estimate inference wall-time in seconds.

    ``total_steps × inference_ms_per_step / 1000``. Phase F's
    ``k(gpu, model_type)`` is NOT applied — inference ms/step wasn't
    calibrated.

    Args:
        inference_ms_per_step: ms per forward-only step. The aggregator
            is expected to pass ``training_ms_per_step × 1/3`` when it
            has a warmup measurement. ``None`` → internal static fallback.
        num_params: Only needed by the static fallback. If absent, the
            model is instantiated internally via ``_count_params``.
        inference_batch: V21 PR G — an explicit batch to price the
            forecast at, overriding the registry default. Supplied on the
            live agent path by the evaluate_time_skill wrapper (the probed
            batch from ``active_params``); ``None`` (baselines, legacy
            scripts, proposer advisory) → byte-identical pre-G1 behaviour.
            When supplied it must be a positive int, else a ``ValueError``
            is raised (no silent clamp). It does NOT change
            ``inference_batch_uncalibrated``, which keeps its registration
            meaning ("is this model_type in the table"), not "was a batch
            supplied".

    Returns:
        ``{"phase": "inference", "seconds": float, "breakdown": {...}}``.
        ``breakdown.inference_batch_uncalibrated`` is ``True`` when
        the runtime fallback (25) was substituted for an unregistered
        ``model_type`` (K.2.5-8).
    """
    inference_batch_uncalibrated = not is_inference_batch_registered(model_type)
    inf_batch = resolve_forecast_batch(inference_batch, model_type)

    # V21 PR B1 — see the training estimator; the margin is the
    # time-conservative direction (smaller `seg` means more steps).
    from agent.skills.training_skill.estimator import resolve_model_field

    seg_size = resolve_model_field(
        model_type, model_config, "segmentation_size", safety_margin=1000
    )

    total_steps = _total_inference_steps(sample_set, seg_size, inf_batch)

    if inference_ms_per_step is not None and inference_ms_per_step > 0:
        ms_per_step = inference_ms_per_step
        ms_source = "derived_from_training_warmup"
    else:
        if num_params is None:
            num_params = _count_params(model_type, model_config)
        ms_per_step = _static_inference_ms_per_step(num_params, seg_size, inf_batch)
        ms_source = "static_formula"

    seconds = total_steps * ms_per_step / 1000.0

    return {
        "phase": "inference",
        "seconds": seconds,
        "breakdown": {
            "total_inference_steps": total_steps,
            "inference_batch": inf_batch,
            "ms_per_step": round(ms_per_step, 6),
            "ms_source": ms_source,
            "inference_batch_uncalibrated": inference_batch_uncalibrated,
        },
    }
