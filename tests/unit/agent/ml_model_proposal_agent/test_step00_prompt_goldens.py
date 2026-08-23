"""Step-00 PB-3 (pipeline proposer) + PB-4 (legacy commit) prompt goldens.

Design: ``docs/design/generic_framework_upgrade/step_00_golden_baseline_harness.md``
§13.1 / §10.4 / §15.1 (roadmap steps 01/04 A-surfaces).

PB-3 captures the PRODUCTION proposer path — the 2-stage pipeline
(comparison, causal_reasoning) plus the implicit proposing stage — through
the real ``run()`` with a canned schema-valid boundary bridge, under a
FULLY PINNED environment:

- ``nodes.proposal_helpers._SIDERIUS_ROOT`` → a tmp tree holding a
  TEST-OWNED plugin source (design §13.1: no production source text in
  goldens; unpatched, builtin candidates would embed
  ``ml_models/models_sandbox.py`` class bodies verbatim);
- ``agent.prompt_templates.proposal._GLOBAL_LOSS_DIR`` → a tmp loss dir
  (the loss-liveness filter is import-time absolute);
- ``ml_models.models_sandbox.MODEL_REGISTRY`` → an explicit stub dict
  (the phantom filter would otherwise drop fixture names / vary by
  machine-local generated plugins);
- ``capability_index_path`` → a tmp index with pinned ``created_at`` sort
  keys (NEVER the live gitignored ``agent_generated/_capability_index.json``).

The exploration mode affects SYSTEM prompts only; the user prompts are
asserted mode-invariant (a free strong pin). The exploit variant reuses
the explore user goldens.

PB-4: the legacy commit prompt — a plain module constant (system) and a
two-input render (user); nothing environment-coupled.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent.prompt_templates.proposal.task_blocks import load_proposal_task_blocks
from agent.schemas.proposal import (
    AgentCard,
    ExpertContextItem,
    ModelSelectionStrategy,
    ProposalInput,
    ReasoningPipelineConfig,
    ReasoningStage,
    ResearchPolicy,
    VocabEntry,
)
from agent.schemas.proposer_evidence import build_proposer_evidence
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from agent.schemas.task_config import ForwardContract
from core.hardware_context import HardwareContext
from nodes.ml_model_proposal_agent import MLModelProposalAgent
from nodes.ml_model_proposal_agent.ml_model_proposal_agent import (
    PROPOSAL_COMMIT_PROMPT,
    _build_commit_prompt,
    _render_commit_system_prompt,
)
from workflows.task_config import load_task_config


def _shipped_forward_contract() -> ForwardContract:
    """The SHIPPED declaration — the profile PB-4's golden was captured under."""
    return ForwardContract(**load_task_config()["forward_contract"])


from tests.helpers.golden import assert_golden
from tests.helpers.llm_boundary_recorder import BoundaryRecorderBridge

GOLDENS = Path(__file__).parent / "goldens"

_FIXTURE_MODEL_SOURCE = (
    "# test-owned frozen plugin source; NOT production code (design §13.1)\n"
    'PLUGIN_MODEL_TYPE = "step00_alpha_net"\n'
    "class Step00AlphaNet:\n"
    "    def __init__(self, hidden_dim: int = 32) -> None:\n"
    "        self.hidden_dim = hidden_dim\n"
)

_SCORE_TABLE_MD = "| file | score |\n|---|---|\n| 0 | **-2.9100** |\n"


def fixture_score_table() -> dict:
    """A COMPLETE, production-shaped ``ScoreComparisonTable`` dump.

    Step 10 / P3 C2 (fixture rot, triaged per the Step-00 §19.3 ladder). This
    fixture used to carry ``{"rendered_markdown": ...}`` alone. That shape is
    not one the producer can emit — ``ScoreComparisonTable`` requires ``rows``
    (exactly one per file in the declared topology), ``aggregate``,
    ``s_max_global`` and ``reference_source`` — and it survived only because
    the proposer mined the raw dump with ``.get()`` and read
    ``rendered_markdown`` alone.

    P3's typed projection validates the table, so the abbreviated shape now
    fails closed at the boundary. That is the declared fail-closed upgrade
    working, and the fixture is what was wrong: a golden captured through a
    shape production cannot produce pins bytes nobody will ever see.

    Completing it does NOT move any golden. The rendered bytes depend on
    ``rendered_markdown`` (via ``build_candidate_markdown_block``), while
    ``per_model_score_tables`` is dropped from the JSON region by
    ``_render_stage_user_prompt`` and ``score_table`` is stripped from
    candidates by ``strip_heavy_fields_for_json``. The PB-3 goldens are
    asserted UNCHANGED across this fixture repair, which is the evidence that
    the repair is a repair and not a re-baseline.

    ``linear_weight`` is deliberately omitted: the Sigma-weight validator skips
    when no sampled row declares one, so the fixture stays minimal.
    """
    from execute_tools.dataset_config import resolve_dataset_profile

    return {
        "rows": [
            {
                "file_index": i,
                "raw_baseline": -3.2,
                "ground_truth": 0.0,
                "model": -2.91,
                "gain_vs_raw": 0.29,
                "headroom_vs_gt": 2.91,
            }
            for i in range(resolve_dataset_profile().dataset.num_files)
        ],
        "aggregate": {
            "raw_baseline_scalar": -3.2,
            "ground_truth_scalar": 0.0,
            "model_scalar": -2.91,
            "percent_of_ceiling_log": 9.06,
            "num_sampled_files": 1,
        },
        "s_max_global": 3.2,
        "reference_source": "step00_fixture",
        "rendered_markdown": _SCORE_TABLE_MD,
    }


def pin_environment(tmp_path, monkeypatch) -> str:
    """Pin every environment-coupled render input; return the index path."""
    import agent.prompt_templates.proposal as ptp
    import ml_models.models_sandbox as sandbox
    import nodes.proposal_helpers as ph

    root = tmp_path / "root"
    model_dir = root / "agent_generated" / "models" / "step00_alpha_net"
    model_dir.mkdir(parents=True)
    (model_dir / "step00_alpha_net.py").write_text(_FIXTURE_MODEL_SOURCE, encoding="utf-8")
    monkeypatch.setattr(ph, "_SIDERIUS_ROOT", str(root))

    loss_dir = tmp_path / "losses"
    loss_dir.mkdir()
    loss_file = loss_dir / "step00_band_mse.py"
    loss_file.write_text("PLUGIN_LOSS_TYPE = 'step00_band_mse'\n", encoding="utf-8")
    monkeypatch.setattr(ptp, "_GLOBAL_LOSS_DIR", str(loss_dir))

    index = tmp_path / "_capability_index.json"
    index.write_text(
        json.dumps(
            [
                {
                    "name": "step00_band_mse",
                    "capability_type": "loss",
                    "file_path": str(loss_file),
                    "created_at": "2026-01-02T00:00:00+00:00",
                    "source_iteration": "iter_002",
                    "description": "Band-weighted MSE fixture loss.",
                    "mathematical_definition": "L = mean(w_b * (y - yhat)^2)",
                },
                {
                    "name": "step00_alpha_net",
                    "capability_type": "model",
                    "file_path": str(model_dir / "step00_alpha_net.py"),
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "source_iteration": "iter_001",
                    "description": "Fixture 1-D denoiser.",
                    "mathematical_definition": "y = Head(Conv(x))",
                },
            ],
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(sandbox, "MODEL_REGISTRY", {"step00_alpha_net": object()}, raising=True)
    return str(index)


@pytest.fixture
def pinned_env(tmp_path, monkeypatch) -> str:
    return pin_environment(tmp_path, monkeypatch)


def fixture_interpretation() -> dict:
    return {
        "model_types": ["step00_alpha_net", "step00_beta_net"],
        "model_descriptions": {
            "step00_alpha_net": "Fixture alpha.",
            "step00_beta_net": "Fixture beta.",
        },
        "total_experiments": 3,
        "best_denoising_score": -2.55,
        "worst_denoising_score": -3.10,
        "key_findings": ["alpha beats beta at low frequency."],
        "bottlenecks": ["Low-frequency recovery is the binding limit."],
        "take_home_message": "Target low-frequency recovery next.",
        "per_model_best": {"step00_alpha_net": -2.55, "step00_beta_net": -3.10},
        # candidate selection reads per_model_best_valid (proposal_helpers:52);
        # without it every best_score is None and top_n selects NOTHING —
        # the candidate/source-embedding block would silently vanish from
        # the goldens (caught at first capture: "Candidates: []").
        "per_model_best_valid": {"step00_alpha_net": -2.55, "step00_beta_net": -3.10},
        "per_model_worst": {"step00_alpha_net": -2.91, "step00_beta_net": -3.40},
        "per_model_score_tables": {"step00_alpha_net": fixture_score_table()},
    }


def fixture_proposal_input(tmp_path, *, mode: str) -> ProposalInput:
    return ProposalInput(
        interpretation_evidence=build_proposer_evidence(fixture_interpretation()),
        # Step 12 / PR-12a C7-3 — supplied because PRODUCTION supplies it:
        # `run_workflow` resolves the run's proposer blocks on every
        # iteration. A fixture that omitted them would be baselining a prompt
        # no run produces, and the goldens below stay byte-identical BECAUSE
        # the blocks carry TIDMAD's prose verbatim (D-12a-6 is a relocation).
        proposal_blocks=load_proposal_task_blocks(),
        existing_model_types=["step00_alpha_net", "step00_beta_net"],
        cold_start=False,
        task_description="Step-00 fixture task: denoise a synthetic 1-D int8 series.",
        # S1-A0 (PR 01a): a COMPLETE, self-consistent TEST-OWNED contract.
        # Before this commit num_classes/task_type were left at their
        # defaults, so `render_forward_contract` emitted no task-type
        # descriptor and the fixture could not exercise the class-count
        # token at all — which made the later extraction commits'
        # byte-parity claims vacuous for those fields (design §8.1a).
        # The class count is deliberately 192, NOT the shipped 256: a
        # test-owned value makes an accidentally-hardcoded production
        # literal visible instead of silently agreeing with the fixture.
        forward_contract=ForwardContract(
            input_shape="[B, T] int64",
            input_description="per-timestep ADC class indices",
            output_shape="[B, 192, T] float32",
            output_description="per-timestep logits over 192 classes",
            num_classes=192,
            task_type="classification",
        ),
        constraints=["VRAM < 10 GB", "params < 50M"],
        hardware_context=HardwareContext(
            device_name="NVIDIA RTX 3090",
            total_memory_bytes=24 * 1024**3,
            compute_capability=(8, 6),
            multiprocessor_count=82,
            cuda_runtime_version="12.1",
            torch_version="2.1.0",
            hostname="step00-fixture-host",
            device_available=True,
            discovered_at=datetime(2026, 1, 1, tzinfo=UTC),
        ),
        vram_budget_gb=None,
        agent_cards=[
            AgentCard(
                agent_name="ml_literature_review",
                role="Surface ML denoising literature.",
                expertise_domain="ML denoising architectures.",
                coverage="arXiv/S2.",
                limitations="Cannot run experiments.",
                trust_level="soft_prior",
                trust_guidance="Treat findings as inspirational priors.",
            )
        ],
        expert_context=[
            ExpertContextItem(
                source="ml_literature_review",
                kind="literature",
                content="A frequency-aware composite loss may widen spectral coverage.",
                source_ref="arxiv:0000.00000",
                confidence=0.85,
            )
        ],
        vocab_seed=[
            VocabEntry(
                name="dilated_causal_conv",
                kind="feature",
                description="Exponential receptive field growth.",
            )
        ],
        previous_failures=["step00_gamma_net: diverged at lr=1e-3."],
        recent_gate_exhaustions=[],
        recent_trial_validity=[],
        enable_structured_health_feedback=False,
        mindset=None,
        reasoning_pipeline=ReasoningPipelineConfig(
            stages=[
                ReasoningStage(name="comparison", system_prompt_key="COMPARATIVE_ANALYSIS"),
                ReasoningStage(name="causal_reasoning", system_prompt_key="CAUSAL_REASONING"),
            ],
            model_selection=ModelSelectionStrategy(),
            exploration_mode=mode,
            policy=ResearchPolicy(minimum_boldness=0.05),
        ),
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path / "ws"), run_name="step00"),
        ),
    )


class _CannedProposerBridge(BoundaryRecorderBridge):
    """Records at the true boundary; returns canned schema-valid stage JSON
    so the pipeline completes with exactly 3 calls (no retry/correction)."""

    def _chat_json(
        self,
        client,
        model_name,
        system_prompt,
        user_prompt,
        *,
        label="unlabeled",
        provider=None,
        components=None,
    ) -> dict:
        self.captures.append(("_chat_json", label, system_prompt, user_prompt))
        self._log_components(label, components)
        if label == "proposer.comparison":
            return {
                "comparisons": [],
                "proposed_vocab_links": [],
                "proposed_vocab_candidates": [],
                "sota_model_type": "step00_alpha_net",
                "sota_score": -2.55,
                "sota_mechanism": "Fixture mechanism.",
            }
        if label.startswith("proposer.causal_reasoning"):
            return {
                "proposed_change": "Fixture change.",
                "causal_hypothesis": "Fixture hypothesis.",
                "falsifiable_prediction": {
                    "metric": "mean(file_vector[0:3])",
                    "current_value": 0.5,
                    "predicted_value": 1.5,
                    "threshold_for_refutation": 0.7,
                    "rationale": "Fixture.",
                },
                "predicted_failure_modes": [],
                "inherited_components": [],
            }
        return {
            "model_name": "step00_delta_net",
            "output_type": "classifier",
            "model_description": "Fixture.",
            "mathematical_definition": "Fixture.",
            "motivation": "Fixture.",
            "expert_advice": {
                "focus_areas": ["low-freq"],
                "constraints": ["VRAM < 10 GB"],
                "known_failures": [],
                "suggested_directions": ["start small"],
                "rationale": "Fixture.",
            },
            "baseline_config": {
                "model_config": {},
                "train_config": {"lr": 1e-4, "epochs": 1},
                "loss_config": {"loss_type": "focal"},
            },
            "parameter_count_estimate": 1_000_000,
        }


def run_pipeline(tmp_path, index_path: str, mode: str):
    inp = fixture_proposal_input(tmp_path, mode=mode)
    agent = MLModelProposalAgent(
        provider="openai",
        model_id="step00-capture",
        bridge_factory=_CannedProposerBridge,
        capability_index_path=index_path,
    )
    agent.run(inp)
    run_pipeline._last_components_log = list(agent.bridge.components_log)
    return agent.bridge.captures


class TestPB3PipelineProposer:
    def test_explore_mode(self, tmp_path, pinned_env):
        caps = run_pipeline(tmp_path, pinned_env, "explore")
        assert [c[1] for c in caps] == [
            "proposer.comparison",
            "proposer.causal_reasoning",
            "proposer.proposing",
        ], "exact label sequence — a retry/correction call means the canned fixture drifted"
        for (_m, label, system, user), stem in zip(
            caps, ["comparison", "causal", "proposing"], strict=True
        ):
            assert_golden(
                system,
                GOLDENS / f"pb3_{stem}_explore_system.txt",
                surface=f"PB-3 {label} system prompt (explore)",
            )
            assert_golden(
                user, GOLDENS / f"pb3_{stem}_user.txt", surface=f"PB-3 {label} user prompt"
            )

    def test_exploit_mode_systems_and_mode_invariant_users(self, tmp_path, pinned_env):
        caps = run_pipeline(tmp_path, pinned_env, "exploit")
        assert [c[1] for c in caps] == [
            "proposer.comparison",
            "proposer.causal_reasoning",
            "proposer.proposing",
        ]
        for (_m, label, system, user), stem in zip(
            caps, ["comparison", "causal", "proposing"], strict=True
        ):
            assert_golden(
                system,
                GOLDENS / f"pb3_{stem}_exploit_system.txt",
                surface=f"PB-3 {label} system prompt (exploit)",
            )
            # User prompts are mode-invariant — same goldens as explore.
            assert_golden(
                user,
                GOLDENS / f"pb3_{stem}_user.txt",
                surface=f"PB-3 {label} user prompt (mode-invariance)",
            )


class TestWF3ComponentsInventory:
    def test_pipeline_components_key_sets(self, tmp_path, pinned_env):
        """WF-3 second half (closure-audit F1): the ``components``
        char-count breakdown crossing ``generate`` at every pipeline
        stage. Production wires ``_audit_proposer_components`` output
        into each stage call (`ml_model_proposal_agent.py:1688,1696,
        1979`); deleting that wiring makes ``components=None`` reach the
        boundary and this golden goes red. Key sets only — the values
        are char counts that legitimately move with any fixture edit."""
        from tests.helpers.golden import assert_json_golden

        caps = run_pipeline(tmp_path, pinned_env, "explore")
        assert len(caps) == 3
        bridge_log = run_pipeline._last_components_log
        assert [label for label, _keys in bridge_log] == [
            "proposer.comparison",
            "proposer.causal_reasoning",
            "proposer.proposing",
        ]
        assert all(keys is not None for _label, keys in bridge_log), (
            "components=None reached the boundary — the "
            "_audit_proposer_components wiring is disconnected"
        )
        assert_json_golden(
            [{"label": label, "component_keys": keys} for label, keys in bridge_log],
            GOLDENS / "wf3_proposer_components_key_sets.json",
            surface="WF-3 proposer components inventory",
        )


_FIXTURE_REASONING = (
    "Step-00 fixture reasoning.\n\n"
    "1. The bottleneck is low-frequency recovery.\n"
    "2. A dilated causal stack widens the receptive field.\n"
)


class _LegacyCommitRecorder(BoundaryRecorderBridge):
    """Captures the legacy path's two boundary calls.

    ``generate_text`` (the reasoning stage) returns canned text so the
    run reaches the commit call; ``_chat_json`` returns a schema-valid
    proposal so ``run()`` completes normally.
    """

    def generate_text(self, *a, **k):
        super().generate_text(*a, **k)
        return _FIXTURE_REASONING

    def _chat_json(self, *a, **k):
        super()._chat_json(*a, **k)
        return {
            "model_name": "step00_delta_net",
            "output_type": "classifier",
            "model_description": "Fixture.",
            "mathematical_definition": "Fixture.",
            "motivation": "Fixture.",
            "expert_advice": {
                "focus_areas": ["low-freq"],
                "constraints": ["VRAM < 10 GB"],
                "known_failures": [],
                "suggested_directions": ["start small"],
                "rationale": "Fixture.",
            },
            "baseline_config": {
                "model_config": {},
                "train_config": {"lr": 1e-4, "epochs": 1},
                "loss_config": {"loss_type": "focal"},
            },
            "parameter_count_estimate": 1_000_000,
        }


def _run_legacy_capture(tmp_path, pinned_env, **input_overrides):
    """Drive the LEGACY path end-to-end and return the recorder."""
    inp = fixture_proposal_input(tmp_path, mode="explore")
    # empty stage list => legacy dispatch (ml_model_proposal_agent.py:1432-1434)
    inp = inp.model_copy(
        update={"reasoning_pipeline": ReasoningPipelineConfig(stages=[]), **input_overrides}
    )
    agent = MLModelProposalAgent(
        provider="openai",
        model_id="step01a-capture",
        bridge_factory=_LegacyCommitRecorder,
        capability_index_path=pinned_env,
    )
    agent.run(inp)
    return agent.bridge


class TestPB4LegacyCommit:
    def test_commit_system_rendered_at_the_llm_boundary(self, tmp_path, pinned_env):
        """PB-4 re-target (PR 01a; 2nd-review R2-4).

        The assert target moved from the raw module constant to the
        RENDERED system prompt captured at the real LLM boundary through
        the legacy ``run()`` path. Capturing at the boundary — rather
        than calling the renderer directly — is what makes deleting the
        render call at the production call site observable (mutation
        M-1b). The golden FILE is byte-identical: that IS the extraction
        parity claim.
        """
        # PB-4's golden pins the SHIPPED TIDMAD render, so the capture must
        # run under the shipped declaration — not the test-owned PB-3 fixture
        # profile (which declares 192 classes). Discovered by this very
        # boundary capture on its first run: a direct-helper assert would
        # have hidden the profile mismatch.
        bridge = _run_legacy_capture(
            tmp_path, pinned_env, forward_contract=_shipped_forward_contract()
        )
        commit = [c for c in bridge.captures if c[1] == "proposer.legacy_commit"]
        assert len(commit) == 1, "the legacy commit call must reach the boundary exactly once"
        _method, _label, system, _user = commit[0]
        assert_golden(
            system,
            GOLDENS / "pb4_legacy_commit_system.txt",
            surface="PB-4 legacy commit system prompt (rendered, at the boundary)",
        )

    def test_raw_template_is_no_longer_the_golden(self):
        """Differential (design §8.2): the template now carries live
        placeholders, so the CONSTANT must NOT equal the golden while the
        RENDER does. If both matched, the placeholders would be dead."""
        golden = (GOLDENS / "pb4_legacy_commit_system.txt").read_text(encoding="utf-8")
        assert PROPOSAL_COMMIT_PROMPT != golden
        assert "{INPUT_SHAPE}" in PROPOSAL_COMMIT_PROMPT
        assert (
            _render_commit_system_prompt(_shipped_forward_contract(), load_proposal_task_blocks())
            == golden
        )

    def test_commit_user_render(self):
        user = _build_commit_prompt(_FIXTURE_REASONING, ["step00_alpha_net", "step00_beta_net"])
        assert_golden(
            user, GOLDENS / "pb4_legacy_commit_user.txt", surface="PB-4 legacy commit user prompt"
        )
