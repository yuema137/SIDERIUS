"""
core/inference_defaults.py

Single source of truth for the inference batch size used by
``sandbox_executor.execute_inference`` and by the per-phase estimators in
``agent/skills/inference_skill/estimator.py``.

Colocating both callers on one function means the VRAM/time forecast for
the inference phase cannot drift from what actually runs: changing an
inference batch size for any model type means editing exactly one table.

Two callers, asymmetric tolerance for unknown ``model_type``:

- ``inference_batch_for`` — used by ``sandbox_executor.execute_inference``
  at **runtime**. Falls back silently to ``_DEFAULT_INFERENCE_BATCH``
  (25), matching pre-K.2.5 ``.get(model_type, 25)`` behaviour so plugin
  models that never registered a custom batch keep running.

- ``assert_inference_batch_registered`` — used by the planning-time
  estimator in ``inference_skill/estimator.py`` **before** calling
  ``inference_batch_for``. Raises ``ValueError`` on unknown model types
  so the VRAM/time gate refuses to silently forecast against a guessed
  batch size (a wrong number there would poison the planner's decision).

See docs/resource_estimator_implement.md §10.5 (Phase K.2.5).
"""

from typing import Dict


# Inference batch sizes chosen to keep single-process GPU memory under ~2 GB
# per model on the original TIDMAD evaluation setup. transformer=1 because of
# O(T²) attention memory; rnn=10 because LSTM hidden states compound across
# the sequence.
_INFERENCE_BATCH_SIZES: Dict[str, int] = {
    "punet":       25,
    "wavenet":     25,
    "fcnet":       25,
    "rnn":         10,
    "transformer": 1,
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
