"""
core/inference_defaults.py

Single source of truth for the inference batch size used by
``sandbox_executor.execute_inference`` and by the per-phase estimators in
``agent/skills/inference_skill/estimator.py``.

Colocating both callers on one function means the VRAM/time forecast for
the inference phase cannot drift from what actually runs: changing an
inference batch size for any model type means editing exactly one table.

Three callers, two tiers of tolerance for unknown ``model_type``:

- ``inference_batch_for`` — used by ``sandbox_executor.execute_inference``
  at **runtime**. Falls back silently to ``_DEFAULT_INFERENCE_BATCH``
  (25), matching pre-K.2.5 ``.get(model_type, 25)`` behaviour so plugin
  models that never registered a custom batch keep running.

- ``is_inference_batch_registered`` — used by the planning-time
  estimator in ``inference_skill/estimator.py`` (post-K.2.5-8).
  Returns ``bool`` so the estimator can call ``inference_batch_for``
  unconditionally (matching runtime) and surface the substitution as
  an ``inference_batch_uncalibrated`` flag through the gate breakdown.
  See docs/resource_estimator_implement.md §10.14 K.2.5-8 for the
  rationale (the original loud-assert path crashed every gate that ran
  on a proposer-invented model_type).

- ``assert_inference_batch_registered`` — kept for callers that still
  want the loud-fail semantics (no in-tree caller uses it post-K.2.5-8;
  retained for downstream plugins or future re-use). Raises
  ``ValueError`` on unknown model types.

See docs/resource_estimator_implement.md §10.5 (Phase K.2.5) +
§10.14 K.2.5-8 (soft fallback for unregistered model_type).
"""

# Inference batch sizes chosen to keep single-process GPU memory under ~2 GB
# per model on the original TIDMAD evaluation setup. transformer=1 because of
# O(T²) attention memory; rnn=10 because LSTM hidden states compound across
# the sequence.
_INFERENCE_BATCH_SIZES: dict[str, int] = {
    "punet": 25,
    "wavenet": 25,
    "fcnet": 25,
    "rnn": 10,
    "transformer": 1,
    # V7 calibrated 2026-04-30 from VRAM-gate runtime choices on ligroup.
    # Source: per-arch chosen_inference_batch in successful formal-round
    # records under exploration_{explore_novel,exploit_cnn}_v7_0429/.
    "lite_dualpath_spectral_tcn": 16,
    "calibrated_spectral_gated_tcn": 32,
    "joint_calibrated_spectral_tcn": 32,
    "gated_context_dualpath_tcn": 16,
    "spectral_skip_dilated_cnn": 32,
    "fft_fused_cyclic_tcn": 64,
    "gated_skip_spectral_tcn": 64,
    "subband_calibrated_skip_tcn": 64,
}

_DEFAULT_INFERENCE_BATCH: int = 25


def inference_batch_for(model_type: str) -> int:
    """Return the inference batch size for ``model_type``.

    Unknown model types fall back to ``_DEFAULT_INFERENCE_BATCH`` (25),
    matching the silent fallback used by sandbox_executor pre-K.2.5.
    Estimator callers should call ``assert_inference_batch_registered``
    first so a missing plugin entry surfaces as a loud gate error rather
    than a silent forecast against a guessed batch.
    """
    return _INFERENCE_BATCH_SIZES.get(model_type, _DEFAULT_INFERENCE_BATCH)


def is_inference_batch_registered(model_type: str) -> bool:
    """Return ``True`` iff ``model_type`` has a registered inference batch.

    Soft companion to ``assert_inference_batch_registered``. Used by the
    planning-time estimator (K.2.5-8) so it can call
    ``inference_batch_for`` unconditionally — matching runtime behaviour
    — and surface the substitution to callers via an
    ``inference_batch_uncalibrated`` breakdown flag, rather than
    crashing the gate on every proposer-invented model_type.
    """
    return model_type in _INFERENCE_BATCH_SIZES


def assert_inference_batch_registered(model_type: str) -> None:
    """Raise ``ValueError`` if ``model_type`` has no registered inference batch.

    Called by planning-time estimators before forecasting VRAM / wall-time
    for the inference phase. Forecasting against the silent 25-fallback
    would let a plugin author's unregistered model silently pass the gate
    with a wrong number.
    """
    if model_type not in _INFERENCE_BATCH_SIZES:
        raise ValueError(
            f"Model type {model_type!r} has no registered inference batch size "
            f"in core/inference_defaults.py. Add it to _INFERENCE_BATCH_SIZES "
            f"before the inference-phase estimator can forecast VRAM/time."
        )
