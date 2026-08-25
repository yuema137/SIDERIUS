"""Step 12 / PR-12d — F-12d-24: the VRAM probe's INPUT and class-INDEX target.

Design: ``docs/design/generic_framework_upgrade/step_12_external_extensibility_graduation/
pr_12d_contrast_subprocess_closure.md`` §Q (F-12d-24).

Step 05b C2 (``test_step05b_c2_contract_aware_probe.py``) made the VRAM
capacity gate a real consumer of the Step-04 contract-realization authority
for its FLOAT target — explicitly, honestly, "without... any production
caller supplying a contract yet" (its own docstring). PR-12d is the first PR
to make a real caller supply one (a composed Pets/DAVIS launch), and doing so
found that C2's own scope never reached two things a real launch needs:

1. **The probe's INPUT tensor** — four sites (``wrapper._build_probe_tensors``,
   the inline inference-breakdown probe in ``run_skill``,
   ``_render_inference_killer``'s re-probe, and
   ``batch_resolver._build_probe_input``) all built a hardcoded
   ``torch.zeros((B, T), dtype=torch.long)`` regardless of any bound
   contract — correct for TIDMAD's ``[B, T] int`` input, silently wrong for
   Pets' ``[B, 3, 144, 144] float32`` image input and DAVIS' ``[B, 3, 8, 128,
   224] float32`` video input: ``RuntimeError: Input type (long int) and
   bias type (float) should be the same``, reproduced by a real Track 2
   launch before any training step.
2. **The classification loss's class-INDEX target** — the "classifier ->
   [B, T]" branch NEVER consulted the contract at all (by design, per its own
   docstring: "no contract-owned extent — so it returns before any contract
   is consulted"), correct for TIDMAD (per-timestep classification: output
   carries both a class axis, dropped, and a temporal axis, kept, so the
   target genuinely is ``[B, T]``) and wrong for Pets (single global label
   per image: output carries ONLY a class axis, so the target must be
   ``[B]``, not ``[B, 144]``) — ``RuntimeError: 0D or 1D target tensor
   expected, multi-target not supported`` from ``CrossEntropyLoss``,
   reproduced here against the REAL ``pets_reference_cnn`` on CPU before any
   fix, in the same run that proves the fix closes it.

Both closed the same way C2 closed the float target: derive from the ONE
Step-04 recipe authority (``model_io_probe_skill``) at the candidate's real
batch/segmentation size, via ``build_model_input`` (input) and the newly
extracted ``output_without_class_axis`` (class-index target) — never a
second form table, never a second dtype mapping, and the legacy
``model_io_contract=None`` path byte-identical to every call before this fix.
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest
import torch

from agent.schemas.model_io_contract import ModelIOContract
from agent.skills.evaluate_vram_skill.batch_resolver import _build_probe_input
from agent.skills.evaluate_vram_skill.wrapper import (
    _build_probe_tensors,
    _class_index_target_tensor,
    _probe_input_tensor,
)
from agent.skills.model_io_probe_skill import output_without_class_axis
from tests.helpers.step04a_fixtures import regressor_model_io, tidmad_model_io

REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
PETS_CONTRACT = ModelIOContract(
    **json.loads(
        (
            REPO_ROOT / "examples" / "oxford_iiit_pet" / "declared" / "model_io_contract.json"
        ).read_text(encoding="utf-8")
    )
)
DAVIS_CONTRACT = ModelIOContract(
    **json.loads(
        (
            REPO_ROOT
            / "examples"
            / "davis_future_prediction"
            / "declared"
            / "model_io_contract.json"
        ).read_text(encoding="utf-8")
    )
)

BATCH, SEG = 4, 128


# ======================================================================
# Legacy path: model_io_contract=None is byte-identical to before this fix
# ======================================================================


class TestLegacyPathUnchanged:
    def test_probe_input_tensor_is_the_old_hardcoded_tensor(self):
        t = _probe_input_tensor(BATCH, SEG, None)
        assert t.shape == (BATCH, SEG)
        assert t.dtype == torch.long
        assert torch.equal(t, torch.zeros((BATCH, SEG), dtype=torch.long))

    def test_class_index_target_tensor_is_the_old_hardcoded_tensor(self):
        t = _class_index_target_tensor(BATCH, SEG, None)
        assert t.shape == (BATCH, SEG)
        assert t.dtype == torch.long
        assert torch.equal(t, torch.zeros((BATCH, SEG), dtype=torch.long))

    def test_batch_resolver_probe_input_is_the_old_hardcoded_tensor(self):
        t = _build_probe_input(BATCH, SEG, None)
        assert t.shape == (BATCH, SEG)
        assert t.dtype == torch.long

    def test_build_probe_tensors_shipped_tidmad_shape_unchanged(self):
        inp, tgt = _build_probe_tensors(
            BATCH, SEG, "focal", None, model_type="wavenet", model_io_contract=None
        )
        assert inp.shape == (BATCH, SEG) and inp.dtype == torch.long
        assert tgt.shape == (BATCH, SEG) and tgt.dtype == torch.long


# ======================================================================
# F-12d-24 part 1: the probe INPUT is contract-shaped and contract-dtyped
# ======================================================================


class TestProbeInputIsContractAware:
    def test_pets_input_is_float32_image_shaped_not_int64(self):
        t = _probe_input_tensor(BATCH, SEG, PETS_CONTRACT)
        assert t.shape == (BATCH, 3, 144, 144)
        assert t.dtype == torch.float32

    def test_davis_input_is_float32_video_shaped_not_int64(self):
        t = _probe_input_tensor(BATCH, SEG, DAVIS_CONTRACT)
        assert t.shape == (BATCH, 3, 8, 128, 224)
        assert t.dtype == torch.float32

    def test_tidmad_shaped_contract_input_matches_the_legacy_shape_and_dtype(self):
        """The shipped contract must not change a live admission decision:
        under a TIDMAD-shaped contract, the realized input is the same
        shape and dtype the legacy hardcoded tensor was. Not byte-identical
        VALUES — ``build_model_input`` draws random indices
        (``torch.randint``), unlike the legacy zeros literal; that
        difference is deliberate (Step 04's shape/gradient-flow probe was
        never a zeros probe) and orthogonal to this defect."""
        t = _probe_input_tensor(BATCH, SEG, tidmad_model_io())
        assert t.shape == (BATCH, SEG)
        assert t.dtype == torch.long

    def test_batch_resolver_probe_input_is_also_contract_aware(self):
        """The search's own input-builder — a separate call site — gets the
        identical fix, not a parallel one that could drift from it."""
        t = _build_probe_input(BATCH, SEG, PETS_CONTRACT)
        assert t.shape == (BATCH, 3, 144, 144)
        assert t.dtype == torch.float32


# ======================================================================
# F-12d-24 part 2: the class-INDEX target drops the class axis, not the
# whole contract-awareness
# ======================================================================


class TestClassIndexTargetDropsOnlyTheClassAxis:
    def test_pets_shaped_contract_yields_a_1d_per_sample_target(self):
        """Pets: output carries ONLY a class axis (no temporal axis) — drop
        it and nothing remains but batch, so the target is [B], one label
        per sample. [B, T] here is exactly F-12d-24's second defect."""
        t = _class_index_target_tensor(BATCH, SEG, PETS_CONTRACT)
        assert t.shape == (BATCH,)
        assert t.dtype == torch.long

    def test_tidmad_shaped_contract_still_yields_b_t_matching_the_legacy_literal(self):
        """TIDMAD: output carries a class axis (dropped) AND a temporal axis
        (kept) — so the realized target is exactly [B, T], byte-identical to
        the legacy hardcoded tensor. This is why the classifier branch could
        stay unchanged for TIDMAD for as long as it did: it was accidentally
        already correct for a contract that happens to keep a temporal axis."""
        t = _class_index_target_tensor(BATCH, SEG, tidmad_model_io())
        assert t.shape == (BATCH, SEG)
        assert t.dtype == torch.long
        assert torch.equal(t, torch.zeros((BATCH, SEG), dtype=torch.long))

    def test_output_without_class_axis_matches_declared_output_tensors_regressor_branch(self):
        """No second form table: the extracted helper and
        declared_output_tensor's own regressor branch must derive the exact
        same tensor for the exact same contract."""
        from agent.skills.model_io_probe_skill import declared_output_tensor

        assert output_without_class_axis(PETS_CONTRACT) == declared_output_tensor(
            PETS_CONTRACT, "regressor"
        )

    def test_a_contract_with_no_class_axis_returns_the_output_unchanged(self):
        assert output_without_class_axis(regressor_model_io()) == regressor_model_io().output


# ======================================================================
# F-12d-24 part 3: end-to-end, a REAL forward + backward pass on CPU
# ======================================================================


class TestRealModelForwardAndBackwardSucceed:
    """The exact two crashes G-12d Track 2 hit, reproduced and closed here
    without any GPU: a real nn.Module forward+backward against the probe
    tensors this module actually builds. If either defect reappeared, THIS
    is where it would raise — the identical RuntimeError a real launch did."""

    def test_pets_reference_cnn_forward_and_backward(self):
        plugins_dir = str(REPO_ROOT / "examples" / "oxford_iiit_pet" / "plugins")
        if plugins_dir not in sys.path:
            sys.path.insert(0, plugins_dir)
        import pets_reference_cnn as prc

        model = prc.PLUGIN_MODEL_CLASS(prc.PLUGIN_CONFIG_CLASS())
        loss_fn = torch.nn.CrossEntropyLoss()

        inp, tgt = _build_probe_tensors(
            32,
            144,
            "focal",
            None,
            model_type="pets_reference_cnn",
            model_io_contract=PETS_CONTRACT,
        )
        assert inp.shape == (32, 3, 144, 144) and inp.dtype == torch.float32
        assert tgt.shape == (32,) and tgt.dtype == torch.long

        out = model(inp)
        assert out.shape == (32, 37)
        loss_val = loss_fn(out, tgt)
        loss_val.backward()  # raises if any grad-path shape/dtype is wrong

    def test_davis_reference_predictor_forward_and_backward(self, monkeypatch):
        plugins_dir = str(REPO_ROOT / "examples" / "davis_future_prediction" / "plugins")
        if plugins_dir not in sys.path:
            sys.path.insert(0, plugins_dir)
        import davis_reference_predictor as drp

        from ml_models import plugin_loader

        # The float-target branch calls get_output_type(model_type), which
        # this test's sys.path import never registers — unlike the classifier
        # (long-target) branch Pets exercises above, which returns before
        # that lookup. Register it the same way the sibling Step 05b C2
        # tests do (test_step05b_c2_contract_aware_probe.py's `declared`
        # fixture), rather than importing the whole real plugin-loader path.
        monkeypatch.setitem(
            plugin_loader.PLUGIN_OUTPUT_TYPE_REGISTRY, "davis_reference_predictor", "regressor"
        )

        model = drp.PLUGIN_MODEL_CLASS(drp.PLUGIN_CONFIG_CLASS())
        loss_fn = torch.nn.SmoothL1Loss()

        inp, tgt = _build_probe_tensors(
            4,
            128,
            "smooth_l1",
            None,
            model_type="davis_reference_predictor",
            model_io_contract=DAVIS_CONTRACT,
        )
        assert inp.shape == (4, 3, 8, 128, 224) and inp.dtype == torch.float32
        assert tgt.shape == (4, 3, 4, 128, 224) and tgt.dtype == torch.float32

        out = model(inp)
        assert out.shape == (4, 3, 4, 128, 224)
        loss_val = loss_fn(out, tgt)
        loss_val.backward()


# ======================================================================
# F-12d-24 part 4: the two failure-path call sites also take the contract
# ======================================================================


class TestFailurePathSitesAcceptTheContract:
    """_render_inference_killer / _render_killer / resolve_inference_batch
    are only reached on an infeasible verdict or a search failure — not the
    happy path a passing candidate takes — but they build the identical
    hardcoded input, so a Pets/DAVIS candidate that genuinely exceeds the
    VRAM cap would hit the SAME crash while the gate tries to explain why.
    Signature-level reachability: real diagnostic rendering needs a real
    OOM-scale model, out of scope for a CPU unit test."""

    def test_resolve_inference_batch_accepts_model_io_contract_kwarg(self):
        import inspect

        from agent.skills.evaluate_vram_skill.batch_resolver import resolve_inference_batch

        assert "model_io_contract" in inspect.signature(resolve_inference_batch).parameters

    def test_render_inference_killer_accepts_model_io_contract_kwarg(self):
        import inspect

        from agent.skills.evaluate_vram_skill.wrapper import _render_inference_killer

        assert "model_io_contract" in inspect.signature(_render_inference_killer).parameters

    def test_render_killer_accepts_model_io_contract_kwarg(self):
        import inspect

        from agent.skills.evaluate_vram_skill.wrapper import _render_killer

        assert "model_io_contract" in inspect.signature(_render_killer).parameters


# ======================================================================
# F-12d-24 part 5: no silent fallback on a genuine contract failure
# ======================================================================


class TestContractFailurePropagatesNeverFallsBackToTheLiteral:
    def test_build_model_input_raises_not_falls_back_when_dtype_is_unsatisfiable(self):
        from agent.schemas.model_io_contract import DtypeAdmissibility, TensorAxis, TensorContract
        from agent.skills.model_io_probe_skill import ProbeConstructionError, build_model_input

        unsatisfiable = ModelIOContract(
            input=TensorContract(
                axes=(TensorAxis(role="batch", dimension={"symbolic": "B"}),),
                dtype=DtypeAdmissibility(admissible=("complex64",)),
            ),
            output=PETS_CONTRACT.output,
        )
        with pytest.raises(ProbeConstructionError):
            build_model_input(unsatisfiable, batch=BATCH, symbolic=SEG)
