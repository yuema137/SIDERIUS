"""Unit tests for agent/skills/evaluate_vram_skill/overhead.py.

Phase 6.6 §3.3 hybrid design: analytical weight-proportional + calibrated
fixed residuals. All tests are pure-Python arithmetic — no torch, no CUDA,
no filesystem. The module's entire surface is bytes + optimizer names.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.skills.evaluate_vram_skill import overhead
from agent.skills.evaluate_vram_skill.overhead import (
    _CUDA_CONTEXT_BYTES,
    _CUDNN_BACKWARD_WORKSPACE_BYTES,
    _OPTIMIZER_STATE_MULTIPLIER,
    cuda_context_bytes,
    cudnn_backward_workspace_bytes,
    phase_overhead_bytes,
    training_overhead_bytes,
)

# ── Calibrated constants (regression: Appendix A.5 numbers are load-bearing) ─


def test_cuda_context_bytes_matches_appendix_a5():
    """185 MB — the inference residual measured on RTX 5090 / torch 2.10.0."""
    assert _CUDA_CONTEXT_BYTES == 185 * 1024**2
    assert cuda_context_bytes() == 185 * 1024**2


def test_cudnn_backward_workspace_matches_appendix_a5():
    """50 MB — the training-minus-inference delta on the same stack."""
    assert _CUDNN_BACKWARD_WORKSPACE_BYTES == 50 * 1024**2
    assert cudnn_backward_workspace_bytes() == 50 * 1024**2


def test_cuda_context_bytes_is_deterministic():
    """Pure function — multiple calls must return identical bytes."""
    assert cuda_context_bytes() == cuda_context_bytes()


# ── Analytical: weight-proportional scaling ─────────────────────────────────


@pytest.mark.parametrize("params_bytes", [0, 1024, 10 * 1024**2, 1 * 1024**3, 50 * 1024**3])
def test_training_overhead_scales_linearly_with_params_adam(params_bytes):
    """Adam: grads (1×P) + m,v (2×P) = 3 × params_bytes."""
    assert training_overhead_bytes(params_bytes, "adam") == 3 * params_bytes


@pytest.mark.parametrize("params_bytes", [0, 1024, 10 * 1024**2, 1 * 1024**3])
def test_training_overhead_adamw_matches_adam(params_bytes):
    """AdamW has the same state shape as Adam — decoupled weight decay does
    not add new buffers."""
    assert training_overhead_bytes(params_bytes, "adamw") == training_overhead_bytes(
        params_bytes, "adam"
    )


@pytest.mark.parametrize("params_bytes", [0, 1024, 10 * 1024**2, 1 * 1024**3])
def test_training_overhead_sgd_is_grads_only(params_bytes):
    """Plain SGD has no momentum state — overhead is exactly the grads."""
    assert training_overhead_bytes(params_bytes, "sgd") == params_bytes


def test_training_overhead_case_insensitive():
    """'Adam', 'ADAM', 'adam' must all resolve to the same multiplier."""
    p = 10 * 1024**2
    for name in ["adam", "Adam", "ADAM", "AdAm"]:
        assert training_overhead_bytes(p, name) == 3 * p


# ── Exception handling: no guessing ─────────────────────────────────────────


def test_training_overhead_unknown_optimizer_raises():
    with pytest.raises(ValueError, match="Unknown optimizer"):
        training_overhead_bytes(1024, "lion")


def test_training_overhead_empty_string_raises():
    with pytest.raises(ValueError, match="Unknown optimizer"):
        training_overhead_bytes(1024, "")


def test_training_overhead_error_message_lists_known_optimizers():
    """The error must surface the valid options so the caller can self-correct."""
    with pytest.raises(ValueError) as exc_info:
        training_overhead_bytes(1024, "rmsprop")
    msg = str(exc_info.value)
    assert "adam" in msg and "adamw" in msg and "sgd" in msg


def test_multiplier_table_has_expected_keys():
    """Regression: the set of known optimizers is a contract with the
    Proposer's config schema. If this test breaks, sync the Proposer too."""
    assert set(_OPTIMIZER_STATE_MULTIPLIER.keys()) == {"adam", "adamw", "sgd"}
    assert _OPTIMIZER_STATE_MULTIPLIER["adam"] == 2
    assert _OPTIMIZER_STATE_MULTIPLIER["adamw"] == 2
    assert _OPTIMIZER_STATE_MULTIPLIER["sgd"] == 0


# ── Mode-switching: per-phase total overhead ────────────────────────────────


def test_phase_overhead_inference_ignores_params_and_optimizer():
    """Inference overhead is just the CUDA context — independent of model size."""
    for params_bytes in [0, 1024, 1 * 1024**3]:
        assert phase_overhead_bytes(params_bytes, "inference") == _CUDA_CONTEXT_BYTES


def test_phase_overhead_inference_accepts_none_optimizer():
    """Inference does not need an optimizer — optimizer=None must not raise."""
    result = phase_overhead_bytes(1024, "inference", optimizer=None)
    assert result == _CUDA_CONTEXT_BYTES


def test_phase_overhead_training_sums_three_terms():
    """Training = analytical(params, opt) + cuda_context + cudnn_backward."""
    params = 100 * 1024**2  # 100 MB of params
    expected = (
        training_overhead_bytes(params, "adamw")
        + _CUDA_CONTEXT_BYTES
        + _CUDNN_BACKWARD_WORKSPACE_BYTES
    )
    assert phase_overhead_bytes(params, "training", optimizer="adamw") == expected


def test_phase_overhead_training_strictly_exceeds_inference():
    """Physical sanity (Appendix A.5 discovery): training overhead must be
    strictly greater than inference for any non-trivial params_bytes."""
    params = 10 * 1024**2
    tr = phase_overhead_bytes(params, "training", optimizer="adam")
    inf = phase_overhead_bytes(params, "inference")
    assert tr > inf
    # And the difference equals exactly (analytical + backward workspace):
    assert tr - inf == training_overhead_bytes(params, "adam") + _CUDNN_BACKWARD_WORKSPACE_BYTES


def test_phase_overhead_training_requires_optimizer():
    """Training peak is not defined without knowing the optimizer."""
    with pytest.raises(ValueError, match="training mode requires an optimizer"):
        phase_overhead_bytes(1024, "training", optimizer=None)


def test_phase_overhead_training_propagates_unknown_optimizer_error():
    with pytest.raises(ValueError, match="Unknown optimizer"):
        phase_overhead_bytes(1024, "training", optimizer="adafactor")


def test_phase_overhead_rejects_unknown_mode():
    with pytest.raises(ValueError, match="Unknown mode"):
        phase_overhead_bytes(1024, "eval", optimizer="adam")


# ── Principle 2: no architecture names anywhere in the module source ────────


def test_module_source_has_no_architecture_names():
    """Principle 2 spot-check on this module specifically. The full
    guardrail test (A.12) covers the whole tree; this one documents the
    invariant inline so a future edit to overhead.py that sneaks in a
    model-family branch fails close to the edit."""
    source = Path(overhead.__file__).read_text().lower()
    for banned in ["wavenet", "punet", "fcnet", "transformer", "rnn"]:
        # "transformer" and "rnn" are common English words — guard against
        # them appearing as identifier tokens (e.g. ``model_type == "transformer"``).
        assert f'"{banned}"' not in source, f"architecture literal {banned!r} found"
        assert f"'{banned}'" not in source, f"architecture literal {banned!r} found"
