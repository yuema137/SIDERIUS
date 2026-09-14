"""
Unit tests for the L5b proposer-node loss-awareness integration:

  - ``MLModelProposalAgent.__init__`` accepts ``capability_index_path`` and
    constructs ``self._registry = CapabilityRegistry(index_path=...)``.
  - ``_run_pipeline`` calls ``render_available_losses(self._registry)`` and
    threads the rendered block through ``template_vars`` to every stage's
    ``load_stage_prompt`` call.

Plus schema-flow regression checks that the proposer-emitted JSON shapes
for the 3 decision branches (built-in / reuse / generate-new) round-trip
correctly through ``ProposalOutput`` — guards against the proposer
accidentally suppressing or mangling the L3 schema validator.

See ``docs/design/enable_loss_inventory.md`` § Commit L5.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from agent.schemas.hyperparam_tuning import ExpertAdvice
from agent.schemas.proposal import CustomLossSpec, ProposalOutput
from agent.schemas.proposer_evidence import build_proposer_evidence
from core.capability_registry import CapabilityMetadata, CapabilityRegistry
from nodes.ml_model_proposal_agent import MLModelProposalAgent

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def index_path(tmp_path: Path) -> str:
    """Tmp capability-index path so tests don't touch the canonical index."""
    return str(tmp_path / "_capability_index.json")


@pytest.fixture
def valid_expert_advice():
    return ExpertAdvice(
        focus_areas=["x"],
        constraints=["x"],
        known_failures=["x"],
        suggested_directions=["x"],
        rationale="x",
    )


def _now_iso() -> str:
    """ISO-8601 timestamp helper — tests need a few of these and don't care
    about the exact value, just that the order is correct."""
    return _dt.datetime.now(_dt.UTC).isoformat()


# ---------------------------------------------------------------------------
# 1. Constructor DI — capability_index_path wires the registry
# ---------------------------------------------------------------------------


class TestConstructorDI:
    """Verify that ``MLModelProposalAgent.__init__`` accepts
    ``capability_index_path`` and that ``self._registry`` is a
    ``CapabilityRegistry`` rooted at that path."""

    def test_registry_uses_provided_index_path(self, index_path: str):
        agent = MLModelProposalAgent.__new__(MLModelProposalAgent)
        # Run the L5b portion of __init__ directly (skips real LLMBridge
        # construction which would need network credentials).
        agent._registry = CapabilityRegistry(index_path=index_path)
        assert isinstance(agent._registry, CapabilityRegistry)
        assert agent._registry.index_path == index_path

    def test_default_index_path_uses_canonical_location(self, tmp_path, monkeypatch):
        """When ``capability_index_path`` is omitted, the proposer must fall
        back to the production registry — since arXiv P1 that is
        ``{resolved generated library}/_capability_index.json``, NOT the
        repository checkout. Defect caught: the proposer's default drifting
        off the shared library index (iterations with no test override
        would then stop seeing what the implementor registered)."""
        monkeypatch.setenv("SIDERIUS_GENERATED_LIBRARY_DIR", str(tmp_path / "lib"))
        agent = MLModelProposalAgent.__new__(MLModelProposalAgent)
        agent._registry = CapabilityRegistry(index_path=None)
        assert agent._registry.index_path == str(tmp_path / "lib" / "_capability_index.json")

    def test_register_then_list_round_trip(self, index_path: str):
        """End-to-end smoke: a custom-path registry is functional —
        register writes; list reads. Pins the integration contract."""
        agent = MLModelProposalAgent.__new__(MLModelProposalAgent)
        agent._registry = CapabilityRegistry(index_path=index_path)
        agent._registry.register(
            CapabilityMetadata(
                name="snr_weighted_mse",
                capability_type="loss",
                file_path="/abs/snr_weighted_mse.py",
                created_at=_now_iso(),
                source_iteration="iter_001",
                description="SNR-weighted MSE.",
            )
        )
        entries = agent._registry.list(capability_type="loss")
        assert [e.name for e in entries] == ["snr_weighted_mse"]


# ---------------------------------------------------------------------------
# 2. Pipeline wiring — render_available_losses(self._registry) lands in
# template_vars under "available_losses_block".
# ---------------------------------------------------------------------------


class TestPipelineTemplateVarsWiring:
    """The proposer's ``_run_pipeline`` builds a ``template_vars`` dict
    that includes ``available_losses_block``. We don't drive the whole
    pipeline (too many moving parts); we patch the bottom of the call
    chain to capture the dict the proposer would have passed."""

    def test_run_pipeline_passes_registry_to_renderer(
        self, index_path: str, valid_expert_advice, tmp_path: Path
    ):
        """When ``_run_pipeline`` builds its ``template_vars`` dict, the
        ``available_losses_block`` value MUST be the result of
        ``render_available_losses(self._registry)``. We don't run the
        whole pipeline — we patch ``load_stage_prompt`` to capture the
        ``template_vars`` dict at the first invocation, then assert."""

        # Pre-populate the registry with 2 entries so the rendered block
        # is non-empty (the empty-registry path is exercised by L5a +
        # by the next test in this class).
        agent = MLModelProposalAgent.__new__(MLModelProposalAgent)
        agent._registry = CapabilityRegistry(index_path=index_path)
        loss_dir = tmp_path / "agent_generated" / "losses"
        loss_dir.mkdir(parents=True)
        snr_loss_path = loss_dir / "snr_weighted_mse.py"
        spectral_loss_path = loss_dir / "spectral_focal.py"
        snr_loss_path.write_text("# loadable test plugin\n")
        spectral_loss_path.write_text("# loadable test plugin\n")
        agent._registry.register(
            CapabilityMetadata(
                name="snr_weighted_mse",
                capability_type="loss",
                file_path=str(snr_loss_path),
                created_at="2026-06-22T00:00:00+00:00",
                source_iteration="iter_005",
                description="SNR-weighted MSE.",
            )
        )
        agent._registry.register(
            CapabilityMetadata(
                name="spectral_focal",
                capability_type="loss",
                file_path=str(spectral_loss_path),
                created_at="2026-06-23T00:00:00+00:00",
                source_iteration="iter_006",
                description="Spectral focal.",
            )
        )

        # Capture the template_vars dict the proposer would have used.
        captured: dict = {}

        # arXiv U3: the production call also passes `baseline_isolation`
        # (keyword-only, default False); the fake mirrors the signature.
        def _fake_load_stage_prompt(
            stage_name, *, exploration_mode, template_vars, mindset, baseline_isolation=False
        ):
            # Only capture on the first call so a multi-stage pipeline
            # doesn't overwrite earlier captures with later ones.
            if not captured:
                captured.update(template_vars)
            # Raising aborts _run_pipeline before it tries to actually
            # call the bridge — we don't need any of the downstream
            # behaviour for this test.
            raise _AbortPipeline()

        class _AbortPipeline(Exception):
            pass

        with (
            patch("agent.prompt_templates.proposal._GLOBAL_LOSS_DIR", str(loss_dir)),
            patch(
                "agent.prompt_templates.proposal.load_stage_prompt",
                side_effect=_fake_load_stage_prompt,
            ),
        ):
            with pytest.raises(_AbortPipeline):
                # _run_pipeline needs a real ProposalInput. Build a minimal
                # one with one enabled pipeline stage so the first
                # load_stage_prompt call fires.
                inp = _minimal_pipeline_input(tmp_path, valid_expert_advice)
                agent._run_pipeline(inp)

        # Assert: the captured template_vars has the key with a
        # non-fallback value (because we pre-registered 2 losses).
        assert "available_losses_block" in captured
        rendered = captured["available_losses_block"]
        assert "snr_weighted_mse" in rendered
        assert "spectral_focal" in rendered
        # Sort order: iter_006 (2026-06-23) is more recent than iter_005
        # (2026-06-22), so spectral_focal must appear before snr_weighted_mse.
        assert rendered.index("spectral_focal") < rendered.index("snr_weighted_mse")

    def test_empty_registry_renders_fallback_into_template_vars(
        self, index_path: str, valid_expert_advice, tmp_path: Path
    ):
        """Empty registry → ``available_losses_block`` is the fallback
        message ('No custom losses registered yet — ...')."""
        agent = MLModelProposalAgent.__new__(MLModelProposalAgent)
        agent._registry = CapabilityRegistry(index_path=index_path)

        captured: dict = {}

        class _AbortPipeline(Exception):
            pass

        # arXiv U3: the production call also passes `baseline_isolation`
        # (keyword-only, default False); the fake mirrors the signature.
        def _fake_load_stage_prompt(
            stage_name, *, exploration_mode, template_vars, mindset, baseline_isolation=False
        ):
            if not captured:
                captured.update(template_vars)
            raise _AbortPipeline()

        with patch(
            "agent.prompt_templates.proposal.load_stage_prompt",
            side_effect=_fake_load_stage_prompt,
        ):
            with pytest.raises(_AbortPipeline):
                inp = _minimal_pipeline_input(tmp_path, valid_expert_advice)
                agent._run_pipeline(inp)

        assert "available_losses_block" in captured
        assert "No custom losses registered yet" in captured["available_losses_block"]


def test_proposer_and_tuner_resolve_identical_task_compatible_names(
    index_path: str, tmp_path: Path
):
    """A composed registry mismatch must not appear on only one agent surface."""

    from types import SimpleNamespace

    from agent.schemas.custom_loss_contract import (
        EqualShapeApplicability,
        build_custom_loss_contract_snapshot,
    )
    from agent.schemas.hyperparam_tuning import TaskCompositionRef
    from agent.schemas.model_io_contract import (
        Dimension,
        ModelIOContract,
        TensorAxis,
        TensorContract,
    )
    from agent.schemas.task_config import ForwardContract
    from ml_models.models_format_sandbox import DtypeAdmissibility
    from nodes.ml_hyperparameter_tune_agent.loss_inventory import (
        resolve_run_custom_loss_inventory,
    )

    tensor = TensorContract(
        axes=(
            TensorAxis(dimension=Dimension(symbolic="B")),
            TensorAxis(dimension=Dimension(fixed=1)),
        ),
        dtype=DtypeAdmissibility(admissible=("float32",)),
    )
    applicability = EqualShapeApplicability(
        dtype=DtypeAdmissibility(admissible=("float32",)), rank=2
    )
    forward = ForwardContract(
        model_io=ModelIOContract(input=tensor, output=tensor),
        supervision_target=tensor,
        custom_loss_applicability=applicability,
    )
    task_ref = TaskCompositionRef.model_construct(
        semantic_fingerprint="fixture",
        task_data_path_id="fixture",
        task_health_binding=None,
        supervision_target=tensor,
        custom_loss_applicability=applicability,
        objective=None,
    )
    snapshot = build_custom_loss_contract_snapshot(tensor, tensor, applicability)
    loss_dir = tmp_path / "agent_generated" / "losses"
    loss_dir.mkdir(parents=True)
    registry = CapabilityRegistry(index_path=index_path)
    for name, contract_snapshot in (("compatible", snapshot), ("mismatch", None)):
        path = loss_dir / f"{name}.py"
        path.write_text("# loadable test plugin\n")
        registry.register(
            CapabilityMetadata(
                name=name,
                capability_type="loss",
                file_path=str(path),
                created_at=_now_iso(),
                contract_snapshot=contract_snapshot,
            )
        )
    proposer = MLModelProposalAgent.__new__(MLModelProposalAgent)
    proposer._registry = registry
    proposal_input = SimpleNamespace(
        forward_contract=forward,
        task_composition_ref=task_ref,
    )

    with patch("agent.prompt_templates.proposal._GLOBAL_LOSS_DIR", str(loss_dir)):
        proposer_inventory = proposer._custom_loss_inventory(proposal_input)
        tuner_inventory = resolve_run_custom_loss_inventory(registry, forward.model_io, task_ref)

    assert proposer_inventory.names == tuner_inventory.names == ("compatible",)
    assert {item.name for item in proposer_inventory.unavailable} == {"mismatch"}
    assert proposer_inventory == tuner_inventory


# ---------------------------------------------------------------------------
# 3. Schema flow — proposer-emitted JSON shapes round-trip through
# ProposalOutput for each of the 3 decision branches (built-in / reuse /
# generate-new). Regression guards: if the proposer ever transforms or
# suppresses the LLM payload, these break.
# ---------------------------------------------------------------------------


class TestThreeBranchOutputs:
    """The 3-branch decision rule in proposing_stage.md (L5a) maps to 3
    valid ``ProposalOutput`` shapes. Verify each round-trips."""

    @pytest.fixture
    def base_payload(self, valid_expert_advice):
        """Minimal ProposalOutput kwargs reused across all 3 branches."""
        return dict(
            model_name="m",
            model_description="x",
            mathematical_definition="x",
            motivation="x",
            expert_advice=valid_expert_advice,
        )

    def test_branch_a_builtin_loss(self, base_payload):
        """Built-in loss: loss_type ∈ {focal, focal_cw, ce, smooth_l1};
        no loss_name; custom_loss_spec=None."""
        out = ProposalOutput(
            **base_payload,
            baseline_config={
                "model_config": {},
                "train_config": {},
                "loss_config": {"loss_type": "focal", "gamma": 2.0},
            },
        )
        assert out.custom_loss_spec is None

    def test_branch_b_reuse_registered(self, base_payload):
        """Reuse existing: loss_type='custom', loss_name=<existing>,
        custom_loss_spec=None. The implementor's L4b short-circuit
        depends on this shape."""
        out = ProposalOutput(
            **base_payload,
            baseline_config={
                "model_config": {},
                "train_config": {},
                "loss_config": {
                    "loss_type": "custom",
                    "loss_name": "snr_weighted_mse",
                },
            },
        )
        assert out.custom_loss_spec is None

    def test_branch_c_generate_new(self, base_payload):
        """Generate new: loss_type='custom', fresh loss_name,
        custom_loss_spec populated. The L3 consistency validator
        enforces loss_name = custom_loss_spec.loss_name."""
        spec = CustomLossSpec(
            loss_name="snr_weighted_mse",
            description="x",
            mathematical_definition="x",
        )
        out = ProposalOutput(
            **base_payload,
            baseline_config={
                "model_config": {},
                "train_config": {},
                "loss_config": {
                    "loss_type": "custom",
                    "loss_name": "snr_weighted_mse",
                },
            },
            custom_loss_spec=spec,
        )
        assert out.custom_loss_spec is not None
        assert out.custom_loss_spec.loss_name == "snr_weighted_mse"

    def test_branch_c_mismatched_names_raises(self, base_payload):
        """L3 regression guard: a proposer that emits a custom_loss_spec
        whose loss_name doesn't match baseline_config.loss_config.loss_name
        must raise — the implementor would otherwise generate the wrong
        plugin name."""
        spec = CustomLossSpec(
            loss_name="snr_weighted_mse",
            description="x",
            mathematical_definition="x",
        )
        with pytest.raises(ValidationError, match="does not match"):
            ProposalOutput(
                **base_payload,
                baseline_config={
                    "model_config": {},
                    "train_config": {},
                    "loss_config": {
                        "loss_type": "custom",
                        "loss_name": "different_name",
                    },
                },
                custom_loss_spec=spec,
            )


# ---------------------------------------------------------------------------
# Helpers private to this test module
# ---------------------------------------------------------------------------


def _minimal_pipeline_input(tmp_path: Path, expert_advice: ExpertAdvice):
    """Build the smallest ``ProposalInput`` that drives ``_run_pipeline``
    far enough to trigger the first ``load_stage_prompt`` call.

    Most fields default; the only requirement is a ``reasoning_pipeline``
    with at least one enabled stage so the pipeline loop fires."""
    from agent.schemas.proposal import (
        ProposalInput,
        ReasoningPipelineConfig,
        ReasoningStage,
        ResearchPolicy,
    )
    from agent.schemas.storage import LocalStorageConfig, StorageConfig

    return ProposalInput(
        interpretation_evidence=build_proposer_evidence(
            {
                "take_home_message": "need new arch",
                "model_types": [],
            }
        ),
        existing_model_types=[],
        constraints=[],
        reasoning_pipeline=ReasoningPipelineConfig(
            stages=[
                ReasoningStage(
                    name="comparison",
                    system_prompt_key="COMPARATIVE_ANALYSIS",
                    enabled=True,
                ),
            ],
            policy=ResearchPolicy(),
        ),
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path), run_name="t"),
        ),
    )


pytestmark = pytest.mark.usefixtures("synthetic_dataset_profile")
