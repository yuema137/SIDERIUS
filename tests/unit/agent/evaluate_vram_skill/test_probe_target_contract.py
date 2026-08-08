"""The VRAM probe's target shape must follow the DECLARED output contract.

V21 PR A, found by **Gate 2R on real hardware** — not by any deterministic
test that existed at the time.

``_build_probe_tensors`` derived the target SHAPE from the target DTYPE:

    long  -> [B, T]
    float -> [B, 256, T]

That is correct for ``fcnet`` (``hybrid``), which emits ``[B, 256, T]`` and
broadcasts a float target against its logits. It is wrong for a ``regressor``,
which emits ``[B, T]``. A generated regressor + ``smooth_l1`` therefore died in
the VRAM pre-flight with

    RuntimeError: The size of tensor a (4) must match the size of tensor b (256)
                  at non-singleton dimension 1

before any capacity question was reached — a contract defect wearing a
resource-error costume.

Shape and dtype are independent questions:

    dtype  <- the loss      (PLUGIN_LOSS_TARGET_DTYPE)
    shape  <- the model's declared output contract

MUTATION TARGET: revert the shape to dtype-derived and
``test_regressor_target_is_2d`` fails while the hybrid and classifier cases
stay green — i.e. the old behaviour is preserved for exactly the cases it was
written for.
"""

from __future__ import annotations

import pytest
import torch

from agent.skills.evaluate_vram_skill.wrapper import _build_probe_tensors
from ml_models import plugin_loader

BATCH, SEG = 4, 128


@pytest.fixture
def declared(monkeypatch):
    def _set(model_type: str, output_type: str) -> str:
        monkeypatch.setitem(plugin_loader.PLUGIN_OUTPUT_TYPE_REGISTRY, model_type, output_type)
        return model_type

    return _set


class TestProbeTargetFollowsOutputContract:
    def test_classifier_target_is_2d_long(self, declared):
        """Class indices — unchanged by PR A."""
        mt = declared("probe_classifier", "classifier")
        _inp, tgt = _build_probe_tensors(BATCH, SEG, "focal", None, model_type=mt)
        assert tgt.shape == (BATCH, SEG)
        assert tgt.dtype == torch.long

    def test_regressor_target_is_2d_float(self, declared):
        """THE regression: a regressor's float target must be [B, T], so it is
        comparable with the [B, T] the model actually emits."""
        mt = declared("probe_regressor", "regressor")
        _inp, tgt = _build_probe_tensors(BATCH, SEG, "smooth_l1", None, model_type=mt)
        assert tgt.shape == (BATCH, SEG), (
            "a regressor target must match its [B, T] output; [B, 256, T] "
            "reproduces the Gate 2R pre-flight failure"
        )
        assert tgt.dtype != torch.long

    def test_hybrid_target_keeps_the_broadcast_shape(self, declared):
        """fcnet is `hybrid`: it emits [B, 256, T] and broadcasts a float
        target against its logits. PR A must not change that."""
        mt = declared("probe_hybrid", "hybrid")
        _inp, tgt = _build_probe_tensors(BATCH, SEG, "smooth_l1", None, model_type=mt)
        assert tgt.shape == (BATCH, 256, SEG)

    def test_unknown_model_keeps_legacy_shape(self):
        """`model_type=None` is the pre-contract caller shape and must be
        untouched, so historical callers behave identically."""
        _inp, tgt = _build_probe_tensors(BATCH, SEG, "smooth_l1", None)
        assert tgt.shape == (BATCH, 256, SEG)

    def test_input_is_always_class_indices(self, declared):
        """The INPUT contract is fixed at [B, T] int64 for both output types."""
        for mt, ot, loss in (
            (declared("probe_in_c", "classifier"), "classifier", "focal"),
            (declared("probe_in_r", "regressor"), "regressor", "smooth_l1"),
        ):
            inp, _tgt = _build_probe_tensors(BATCH, SEG, loss, None, model_type=mt)
            assert inp.shape == (BATCH, SEG) and inp.dtype == torch.long, ot


class TestProbeTargetIsLossCompatible:
    """The point of the probe is that loss(pred, target) actually runs."""

    @pytest.mark.parametrize(
        ("output_type", "loss_type", "pred_shape"),
        [
            ("regressor", "smooth_l1", (BATCH, SEG)),
            ("hybrid", "smooth_l1", (BATCH, 256, SEG)),
        ],
    )
    def test_smooth_l1_accepts_the_probe_target(self, declared, output_type, loss_type, pred_shape):
        mt = declared(f"probe_loss_{output_type}", output_type)
        _inp, tgt = _build_probe_tensors(BATCH, SEG, loss_type, None, model_type=mt)
        pred = torch.zeros(pred_shape, requires_grad=True)
        # Would raise on the pre-PR-A shape for the regressor case.
        loss = torch.nn.functional.smooth_l1_loss(pred, tgt.float())
        loss.backward()
        assert pred.grad is not None
