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


# ── Analytical: weight-proportional scaling ─────────────────────────────────


@pytest.mark.parametrize(
    ("optimizer", "multiple"),
    [
        ("adam", 3),  # grads (1xP) + m,v (2xP)
        ("adamw", 3),  # same state shape -- decoupled decay adds no buffers
        ("sgd", 1),  # no momentum state; overhead is exactly the grads
    ],
)
def test_training_overhead_is_the_grads_plus_the_optimizer_state(optimizer, multiple):
    """`grad_bytes + multiplier * params_bytes`, checked per optimizer and
    across the full magnitude range.

    Three families used to do this in 13 cases: an adam scaling test, an
    `adamw == adam` relative test, and an `sgd == params_bytes` test. The
    relative one could not fail if both sides moved together, and the other
    two duplicated the multiplier assertions in
    `test_multiplier_table_has_expected_keys`.

    Stated as an absolute multiple per optimizer, this covers what the
    literal table cannot: that `training_overhead_bytes` actually READS the
    table for each key, and that the grads term is a full 1xP on top of it.
    """
    for params_bytes in [0, 1024, 10 * 1024**2, 1 * 1024**3, 50 * 1024**3]:
        assert training_overhead_bytes(params_bytes, optimizer) == multiple * params_bytes


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


# `test_phase_overhead_inference_accepts_none_optimizer` lived here. It
# called `phase_overhead_bytes(1024, "inference", optimizer=None)`, and
# `optimizer` DEFAULTS to None, so it was the same call the test above
# already makes with `params_bytes=1024`.


def test_phase_overhead_training_sums_three_terms():
    """Training = analytical(params, opt) + cuda_context + cudnn_backward,
    and is strictly greater than inference.

    `test_phase_overhead_training_strictly_exceeds_inference` asserted
    `tr - inf == training_overhead + cudnn`. Since `inf` IS the cuda
    context, that is this test's equation rearranged -- no mutation could
    fail one without the other. Its `tr > inf` sanity claim (the Appendix
    A.5 discovery that training is not merely inference plus rounding) is
    kept here.
    """
    params = 100 * 1024**2  # 100 MB of params
    expected = (
        training_overhead_bytes(params, "adamw")
        + _CUDA_CONTEXT_BYTES
        + _CUDNN_BACKWARD_WORKSPACE_BYTES
    )
    assert phase_overhead_bytes(params, "training", optimizer="adamw") == expected
    assert expected > phase_overhead_bytes(params, "inference")


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
