"""
Schema-level tests for model Branch B reuse.

The model surface gains a symmetric Branch A / B / C decision rule mirroring
the loss surface added in L5a. This file pins down the three legal shapes
plus the phantom-Branch-B detector at ``ProposalOutput.model_validate``.

Covers acceptance criteria from the V16 plan:

  1. Branch B shape (``baseline_config.model_config.model_name`` set to a
     name in the registry) validates without error.
  6. Loss and model registry entries are structurally symmetric
     (``render_available_models`` mirrors ``render_available_losses``).
  7. Phantom Branch B (``model_name`` set but NOT in the registry) raises
     a ``ValidationError`` when the proposer passes ``model_registry_names``
     in context.

See ``docs/design/symmetric_model_registry.md`` for the full design.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent.prompt_templates.proposal import (
    _MODEL_REGISTRY_EMPTY_FALLBACK,
    render_available_losses,
    render_available_models,
)
from agent.schemas.proposal import ExpertAdvice, ProposalOutput


@pytest.fixture
def valid_expert_advice() -> ExpertAdvice:
    return ExpertAdvice(
        focus_areas=["a"],
        constraints=["VRAM <= 8 GB", "params <= 200k"],
        known_failures=["NaN"],
        suggested_directions=["start at lr=1e-4"],
        rationale="r",
    )


@pytest.fixture
def base_payload(valid_expert_advice):
    return dict(
        model_name="m",
        model_description="x",
        mathematical_definition="x",
        motivation="x",
        expert_advice=valid_expert_advice,
    )


# ---------------------------------------------------------------------------
# Criterion 1 + 7 — Branch B happy path + phantom guard
# ---------------------------------------------------------------------------


class TestModelBranchB:
    """Schema-level validation of the model Branch B shape and its
    phantom-detection guard."""

    def test_branch_b_with_name_in_registry_validates(self, base_payload):
        """Branch B is legal: ``model_config.model_name`` set to a name
        the caller-supplied registry contains."""
        out = ProposalOutput.model_validate(
            {
                **base_payload,
                "baseline_config": {
                    "model_config": {"model_name": "wavenet_baseline_v16"},
                    "train_config": {},
                    "loss_config": {"loss_type": "focal", "gamma": 2.0},
                },
            },
            context={
                "model_registry_names": ["wavenet_baseline_v16", "fcnet_x"],
            },
        )
        baseline_model_cfg = out.baseline_config["model_config"]
        assert baseline_model_cfg["model_name"] == "wavenet_baseline_v16"

    def test_phantom_branch_b_raises_when_name_not_in_registry(self, base_payload):
        """Phantom Branch B: ``model_name`` set but NOT in the registry —
        the validator must raise with a diagnostic message that names the
        missing key and the registry contents."""
        with pytest.raises(ValidationError, match=r"Phantom Branch B detected \(model surface\)"):
            ProposalOutput.model_validate(
                {
                    **base_payload,
                    "baseline_config": {
                        "model_config": {"model_name": "ghost_arch"},
                        "train_config": {},
                        "loss_config": {"loss_type": "focal", "gamma": 2.0},
                    },
                },
                context={
                    "model_registry_names": ["wavenet_baseline_v16"],
                },
            )

    def test_phantom_branch_b_raises_when_registry_empty(self, base_payload):
        """Phantom Branch B against an empty registry — the message must
        say 'no models registered yet' rather than printing an empty list."""
        with pytest.raises(ValidationError, match=r"no models registered yet"):
            ProposalOutput.model_validate(
                {
                    **base_payload,
                    "baseline_config": {
                        "model_config": {"model_name": "ghost_arch"},
                        "train_config": {},
                        "loss_config": {"loss_type": "focal", "gamma": 2.0},
                    },
                },
                context={"model_registry_names": []},
            )

    def test_branch_c_no_model_name_is_noop(self, base_payload):
        """Branch C / Branch A: ``model_name`` unset — registry-membership
        check is a no-op regardless of context contents."""
        out = ProposalOutput.model_validate(
            {
                **base_payload,
                "baseline_config": {
                    "model_config": {},
                    "train_config": {},
                    "loss_config": {"loss_type": "focal", "gamma": 2.0},
                },
            },
            context={"model_registry_names": ["wavenet_baseline_v16"]},
        )
        assert "model_name" not in (out.baseline_config["model_config"] or {})

    def test_no_context_is_back_compat_no_op(self, base_payload):
        """Existing fixtures build ProposalOutput without context — the
        new model validator must remain a no-op so legacy tests don't
        break (mirror of the loss-side back-compat shim)."""
        out = ProposalOutput(
            **base_payload,
            baseline_config={
                "model_config": {"model_name": "anything_at_all"},
                "train_config": {},
                "loss_config": {"loss_type": "focal", "gamma": 2.0},
            },
        )
        assert out.baseline_config["model_config"]["model_name"] == "anything_at_all"


# ---------------------------------------------------------------------------
# Criterion 6 — symmetric render helpers (loss vs model)
# ---------------------------------------------------------------------------


class _StubMeta:
    """Minimal duck-typed CapabilityMetadata stand-in. Avoids depending
    on the real index-file storage layer for these prompt-render tests."""

    def __init__(
        self,
        name,
        capability_type,
        description="",
        math="",
        created_at="2026-06-25T00:00:00+00:00",
        source="iter_001",
    ):
        self.name = name
        self.capability_type = capability_type
        self.description = description
        self.mathematical_definition = math
        self.created_at = created_at
        self.source_iteration = source


class _StubRegistry:
    def __init__(self, metas):
        self._metas = list(metas)

    def list(self, capability_type=None):
        if capability_type is None:
            return list(self._metas)
        return [m for m in self._metas if m.capability_type == capability_type]


class TestRenderSymmetry:
    def test_render_available_models_empty_uses_documented_fallback(self):
        """An empty registry must render the documented fallback (so the
        proposer's prompt explicitly says 'no models registered yet' —
        the in-prompt instruction Branch B forbids reuse against this)."""
        block = render_available_models(_StubRegistry([]))
        assert block == _MODEL_REGISTRY_EMPTY_FALLBACK
        assert "No custom models registered yet" in block

    def test_render_available_models_renders_one_block_per_entry(self):
        """A registry with two model entries renders two ``###`` blocks,
        each carrying the description and the architecture formula."""
        block = render_available_models(
            _StubRegistry(
                [
                    _StubMeta(
                        name="wavenet_baseline_v16",
                        capability_type="model",
                        description="8-block dilated WaveNet baseline.",
                        math="y = sum_l tanh(W_f * x) * sigmoid(W_g * x)",
                        source="iter_001",
                    ),
                    _StubMeta(
                        name="mamba_v1",
                        capability_type="model",
                        description="Selective SSM, linear in T.",
                        math="dh/dt = A(x) h + B(x) u",
                        source="iter_004",
                    ),
                ]
            )
        )
        assert "### `wavenet_baseline_v16`" in block
        assert "### `mamba_v1`" in block
        assert "8-block dilated WaveNet baseline." in block
        assert "y = sum_l tanh" in block

    def test_render_helpers_share_shape_and_emit_distinct_blocks(self):
        """Render the same registry through both helpers — each picks
        the right capability_type and emits the matching block header."""
        registry = _StubRegistry(
            [
                _StubMeta(name="snr_mse", capability_type="loss", description="d", math="x"),
                _StubMeta(name="wavenet_v16", capability_type="model", description="d", math="y"),
            ]
        )
        loss_block = render_available_losses(registry)
        model_block = render_available_models(registry)
        assert "Available custom losses" in loss_block
        assert "Available custom models" in model_block
        # Each helper filters by capability_type — no cross-contamination.
        assert "wavenet_v16" not in loss_block
        assert "snr_mse" not in model_block
