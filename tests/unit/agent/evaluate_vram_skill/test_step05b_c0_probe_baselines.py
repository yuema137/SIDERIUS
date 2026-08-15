"""Step 05b CHECKPOINT 0 — the probe-tensor compatibility surface, pre-edit.

Design:
``docs/design/generic_framework_upgrade/step_05b_tuner_resource_time.md``
§6 (Stage-A compatibility surfaces), C0 (pre-edit baselines).

Captured BEFORE any 05b production edit, against byte-unchanged production
code, so that C2's *"with no contract supplied, the built tensors are
identical"* claim is an equality against a literal written here rather than
a value re-derived from the code under test.

**What this module deliberately does NOT restate.**
``test_probe_target_contract.py`` already pins the four reachable target
SHAPES as hardcoded literals — classifier ``[B, T]``, regressor ``[B, T]``,
hybrid ``[B, 256, T]``, ``model_type=None`` ``[B, 256, T]`` — plus the
``[B, T]`` int64 input. Restating them here would buy nothing. The three
failure classes below are the ones no existing oracle covers, and each is a
migration that C2 could plausibly perform while every shape assertion in the
repository stayed green:

1. **dtype ownership silently moves to the contract.** Today the target dtype
   comes from the LOSS (``get_target_torch_dtype``, ``wrapper.py:214``) and
   the contract supplies shape only. The existing module asserts
   ``dtype == torch.long`` for the classifier branch and merely
   ``dtype != torch.long`` for the regressor — so a migration that sourced
   the float dtype from ``contract.output.dtype`` would pass it. These are
   hardcoded ``torch.float32`` / ``torch.int64`` pins.

2. **the class-index branch stops being reachable for an unregistered model.**
   ``_build_probe_tensors`` returns at ``wrapper.py:217`` for a long target
   *before* ``model_type`` is ever consulted, so a long-target loss never
   reaches ``get_output_type``. A C2 that derived the target from the
   contract *above* that early return would start refusing an unregistered
   model that runs fine today.

3. **the unknown-output-contract refusal stops firing.** ``wrapper.py:230-240``
   converts ``UnknownOutputContractError`` into a ``ValueError`` precisely so
   an unregistered regressor is never probed against the ``[B, 256, T]``
   classifier shape. Nothing in the repository exercises that conversion from
   this call site; a C2 that fell back to the literal on a contract failure
   would be invisible.
"""

from __future__ import annotations

import pytest
import torch

from agent.skills.evaluate_vram_skill.wrapper import _build_probe_tensors
from ml_models import plugin_loader

BATCH, SEG = 4, 128

#: A ``model_type`` deliberately absent from every registry, so
#: ``get_output_type`` raises rather than answering.
UNREGISTERED = "step05b_c0_unregistered_model"


@pytest.fixture
def declared(monkeypatch):
    """Register one ``model_type -> declared output form`` for a test."""

    def _set(model_type: str, output_type: str) -> str:
        monkeypatch.setitem(plugin_loader.PLUGIN_OUTPUT_TYPE_REGISTRY, model_type, output_type)
        return model_type

    return _set


class TestTargetDtypeComesFromTheLoss:
    """Class 1 — hardcoded dtype baselines for every reachable branch.

    The values are written as literals on purpose. Comparing against
    ``get_target_torch_dtype(...)`` would compare the code under test with
    itself and pass for any dtype it happened to return.
    """

    @pytest.mark.parametrize(
        ("output_type", "loss_type", "expected_dtype"),
        [
            ("classifier", "ce", torch.int64),
            ("classifier", "focal", torch.int64),
            ("regressor", "smooth_l1", torch.float32),
            ("hybrid", "smooth_l1", torch.float32),
        ],
    )
    def test_target_dtype_baseline(self, declared, output_type, loss_type, expected_dtype):
        mt = declared(f"step05b_c0_{output_type}_{loss_type}", output_type)
        _inp, tgt = _build_probe_tensors(BATCH, SEG, loss_type, None, model_type=mt)
        assert tgt.dtype == expected_dtype

    def test_legacy_no_model_type_target_dtype_baseline(self):
        """The ``model_type=None`` caller shape, unchanged since before the
        output contract existed."""
        _inp, tgt = _build_probe_tensors(BATCH, SEG, "smooth_l1", None)
        assert tgt.dtype == torch.float32

    def test_input_dtype_baseline(self, declared):
        """The probe INPUT is int64 class indices regardless of the loss."""
        mt = declared("step05b_c0_input_dtype", "classifier")
        for loss_type in ("ce", "smooth_l1"):
            inp, _tgt = _build_probe_tensors(BATCH, SEG, loss_type, None, model_type=mt)
            assert inp.dtype == torch.int64, loss_type


class TestClassIndexBranchNeverConsultsTheRegistry:
    """Class 2 — a long-target loss short-circuits before ``get_output_type``.

    Reachable today: an unregistered ``model_type`` with ``ce`` builds its
    ``[B, T]`` int64 class-index target and never raises. If a later change
    moved contract/registry resolution above the dtype early return, this run
    would start failing — a refusal for a model that has always been probed
    successfully.
    """

    def test_unregistered_model_with_a_long_target_loss_still_builds(self):
        inp, tgt = _build_probe_tensors(BATCH, SEG, "ce", None, model_type=UNREGISTERED)
        assert (inp.shape, inp.dtype) == ((BATCH, SEG), torch.int64)
        assert (tgt.shape, tgt.dtype) == ((BATCH, SEG), torch.int64)


class TestUnknownOutputContractRefusal:
    """Class 3 — the float branch REFUSES an unregistered model.

    Falling through with ``output_type = None`` would build the
    ``[B, 256, T]`` classifier target, so an unregistered regressor's VRAM
    forecast would silently describe a different model. The refusal is the
    guard; this is the only test that exercises it from this call site.
    """

    def test_unregistered_model_with_a_float_target_loss_refuses(self):
        with pytest.raises(ValueError) as exc:
            _build_probe_tensors(BATCH, SEG, "smooth_l1", None, model_type=UNREGISTERED)
        assert "Cannot build a probe target" in str(exc.value)

    def test_the_refusal_names_the_unregistered_model(self):
        """The diagnostic must identify the candidate, not just the failure —
        a bare ``ValueError`` here reads as a resource problem."""
        with pytest.raises(ValueError) as exc:
            _build_probe_tensors(BATCH, SEG, "smooth_l1", None, model_type=UNREGISTERED)
        assert UNREGISTERED in str(exc.value)
