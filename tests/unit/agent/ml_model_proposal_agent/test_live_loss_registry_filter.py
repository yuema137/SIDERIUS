"""Regression coverage for issue #112's phantom Branch-B loss inventory."""

from dataclasses import dataclass

import pytest
from pydantic import ValidationError

from agent.prompt_templates import proposal as proposal_prompts
from agent.prompt_templates.proposal import (
    _LOSS_REGISTRY_EMPTY_FALLBACK,
    live_loss_registry_names,
    render_available_losses,
)
from agent.schemas.proposal import CustomLossSpec, ProposalOutput


@dataclass
class _StubMeta:
    name: str
    file_path: str
    description: str = "test loss"
    created_at: str = "2026-07-17T00:00:00+00:00"
    source_iteration: str | None = "iter_001"
    mathematical_definition: str = "loss = mean(inputs)"


class _StubRegistry:
    def __init__(self, metas: list[_StubMeta]) -> None:
        self._metas = metas

    def list(self, capability_type: str | None = None):
        return list(self._metas) if capability_type in {None, "loss"} else []


def test_workspace_only_loss_is_not_advertised_or_valid_for_branch_b(tmp_path, monkeypatch):
    global_dir = tmp_path / "agent_generated" / "losses"
    global_dir.mkdir(parents=True)
    workspace_dir = tmp_path / "old_run" / "losses"
    workspace_dir.mkdir(parents=True)
    stale_file = workspace_dir / "ordinal_transition_uncertainty_loss.py"
    stale_file.write_text("# still exists, but fresh subprocesses do not scan this directory\n")
    monkeypatch.setattr(proposal_prompts, "_GLOBAL_LOSS_DIR", str(global_dir))

    registry = _StubRegistry([_StubMeta("ordinal_transition_uncertainty_loss", str(stale_file))])

    assert live_loss_registry_names(registry) == []
    assert render_available_losses(registry) == _LOSS_REGISTRY_EMPTY_FALLBACK


def test_global_loss_is_advertised_and_valid_for_branch_b(tmp_path, monkeypatch):
    global_dir = tmp_path / "agent_generated" / "losses"
    global_dir.mkdir(parents=True)
    plugin = global_dir / "ordinal_transition_uncertainty_loss.py"
    plugin.write_text("# loadable plugin\n")
    monkeypatch.setattr(proposal_prompts, "_GLOBAL_LOSS_DIR", str(global_dir))
    registry = _StubRegistry([_StubMeta("ordinal_transition_uncertainty_loss", str(plugin))])

    assert live_loss_registry_names(registry) == ["ordinal_transition_uncertainty_loss"]
    assert "### `ordinal_transition_uncertainty_loss`" in render_available_losses(registry)


def test_resolved_library_loss_is_advertised_and_valid_for_branch_b(tmp_path, monkeypatch):
    """arXiv P1 — promotions land in the resolved generated-library losses
    dir now, and training subprocesses scan it (union member 2). Defect
    caught: ``live_loss_metadata`` still keying membership on the legacy
    checkout dir alone, which would silently empty the proposer's AND the
    tuner's AVAILABLE CUSTOM LOSSES inventory for every post-migration
    promotion — the loss library would look permanently empty."""
    lib_losses = tmp_path / "lib" / "losses"
    lib_losses.mkdir(parents=True)
    monkeypatch.setenv("SIDERIUS_GENERATED_LIBRARY_DIR", str(tmp_path / "lib"))
    # Legacy member pointed elsewhere so the resolved membership is what passes.
    monkeypatch.setattr(proposal_prompts, "_GLOBAL_LOSS_DIR", str(tmp_path / "legacy_losses"))
    plugin = lib_losses / "ordinal_transition_uncertainty_loss.py"
    plugin.write_text("# loadable plugin promoted post-migration\n")
    registry = _StubRegistry([_StubMeta("ordinal_transition_uncertainty_loss", str(plugin))])

    assert live_loss_registry_names(registry) == ["ordinal_transition_uncertainty_loss"]
    assert "### `ordinal_transition_uncertainty_loss`" in render_available_losses(registry)


def test_missing_global_file_is_filtered(tmp_path, monkeypatch):
    global_dir = tmp_path / "agent_generated" / "losses"
    global_dir.mkdir(parents=True)
    monkeypatch.setattr(proposal_prompts, "_GLOBAL_LOSS_DIR", str(global_dir))
    registry = _StubRegistry([_StubMeta("missing_loss", str(global_dir / "missing_loss.py"))])

    assert live_loss_registry_names(registry) == []


def _proposal_payload(*, custom_loss_spec=None):
    return {
        "model_name": "candidate_model",
        "model_description": "candidate",
        "mathematical_definition": "y = model(x)",
        "motivation": "test the custom-loss contract",
        "expert_advice": {
            "focus_areas": ["loss"],
            "constraints": ["loadable plugin"],
            "known_failures": ["phantom Branch B"],
            "suggested_directions": ["Option C"],
            "rationale": "exercise issue 112",
        },
        "baseline_config": {
            "model_config": {},
            "train_config": {},
            "loss_config": {
                "loss_type": "custom",
                "loss_name": "ordinal_transition_uncertainty_loss",
            },
        },
        "custom_loss_spec": custom_loss_spec,
    }


def test_filtered_stale_name_rejects_phantom_branch_b():
    with pytest.raises(ValidationError, match="Phantom Branch B detected"):
        ProposalOutput.model_validate(
            _proposal_payload(),
            context={"loss_registry_names": []},
        )


def test_option_c_remains_valid_when_no_reusable_loss_exists():
    spec = CustomLossSpec(
        loss_name="ordinal_transition_uncertainty_loss",
        description="Ordinal transition-aware objective.",
        mathematical_definition="loss = mean(abs(expected_class - target))",
    )
    output = ProposalOutput.model_validate(
        _proposal_payload(custom_loss_spec=spec),
        context={"loss_registry_names": []},
    )
    assert output.custom_loss_spec == spec


def test_prompt_and_validator_accept_the_same_live_branch_b_loss(tmp_path, monkeypatch):
    global_dir = tmp_path / "agent_generated" / "losses"
    global_dir.mkdir(parents=True)
    plugin = global_dir / "ordinal_transition_uncertainty_loss.py"
    plugin.write_text("# loadable plugin\n")
    monkeypatch.setattr(proposal_prompts, "_GLOBAL_LOSS_DIR", str(global_dir))
    registry = _StubRegistry([_StubMeta("ordinal_transition_uncertainty_loss", str(plugin))])

    reusable_names = live_loss_registry_names(registry)
    rendered = render_available_losses(registry)
    output = ProposalOutput.model_validate(
        _proposal_payload(),
        context={"loss_registry_names": reusable_names},
    )

    assert reusable_names == ["ordinal_transition_uncertainty_loss"]
    assert "### `ordinal_transition_uncertainty_loss`" in rendered
    assert output.custom_loss_spec is None


def test_incomplete_option_c_spec_is_rejected():
    incomplete_spec = {
        "loss_name": "ordinal_transition_uncertainty_loss",
        "description": "missing mathematical definition",
    }
    with pytest.raises(ValidationError, match="mathematical_definition"):
        ProposalOutput.model_validate(
            _proposal_payload(custom_loss_spec=incomplete_spec),
            context={"loss_registry_names": []},
        )
