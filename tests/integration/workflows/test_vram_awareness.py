"""Two-iteration pseudo witness for generic physical-rejection feedback.

The workflow owns the cross-node property: a typed rejection emitted by the
first tuner result reaches the second proposal as both failure evidence and
hardware context. All agents are finite recording doubles; this module does
not select a scientific task, provider, GPU, dataset, or machine path.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from agent.schemas.hyperparam_tuning import HyperparamTuningOutput, PhysicalRejection
from agent.schemas.proposal import ProposalInput, ProposalOutput
from core.hardware_context import HardwareContext
from execute_tools.evaluation_metric import MetricSpec
from nodes.ml_model_proposal_agent import _build_reasoning_prompt
from tests.unit.workflows.test_model_exploration import (
    _make_implementor_output,
    _make_interpretation_output,
    _make_proposal_output,
    _make_tuning_output,
    _make_validator_output,
    _write_tuning_output,
)
from workflows.llm_config import NodeLLMConfig, ProposalLLMConfig, TunerLLMConfig, WorkflowLLMConfig
from workflows.model_exploration import run_workflow
from workflows.run_config import WorkflowLaunchConfig
from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings

ROOT = Path(__file__).resolve().parents[3]
QUICKSTART = ROOT / "configs" / "task_composition" / "quickstart.yaml"
BUDGET_GIB = 10.0
REJECTED_WIDTH = 1024
REVISED_WIDTH = 256


def _hardware() -> HardwareContext:
    return HardwareContext(
        device_name="synthetic-device",
        total_memory_bytes=32 * 1024**3,
        compute_capability=(9, 0),
        multiprocessor_count=1,
        cuda_runtime_version=None,
        torch_version="fixture-not-discovered",
        hostname="pytest",
        device_available=True,
        discovered_at=datetime(2000, 1, 1, tzinfo=UTC),
    )


def _rejected_tuning(
    composition_fingerprint: str,
    metric_spec: MetricSpec,
) -> HyperparamTuningOutput:
    rejection = PhysicalRejection(
        attempt_config={"model_type": "wide_fixture", "hidden_dim": REJECTED_WIDTH},
        binding_cap="vram",
        dominant_layer="encoder.block",
        dominant_layer_gb=13.4,
        dominant_fraction=0.46,
        budget_gb=BUDGET_GIB,
        estimated_gb=29.1,
        suggestion="Reduce hidden width.",
    )
    return HyperparamTuningOutput(
        task_composition_fingerprint=composition_fingerprint,
        run_name="iter_001",
        model_type="wide_fixture",
        file_index=0,
        status="failed",
        completed_rounds=0,
        total_attempts=1,
        best_exp_id=None,
        best_denoising_score=None,
        best_config=None,
        all_records=[],
        physical_rejections=[rejection],
        metric_spec=metric_spec,
        started_at="2000-01-01T00:00:00Z",
        finished_at="2000-01-01T00:00:01Z",
    )


def _llm_config() -> WorkflowLLMConfig:
    node = NodeLLMConfig(provider="openai", model_id="recording-only")
    return WorkflowLLMConfig(
        interpret=node,
        propose=ProposalLLMConfig(),
        implement=node,
        validate_model=node,
        tune=TunerLLMConfig(planner=node, reflector=node),
    )


def test_physical_rejection_and_hardware_context_reach_next_proposal(tmp_path):
    composition = compose_run_task_bindings(str(QUICKSTART))
    seed_root = tmp_path / "seed"
    _write_tuning_output(
        seed_root,
        model_type="punet",
        run="seed",
        score=0.5,
        fingerprint=composition.semantic_fingerprint,
        metric_spec=composition.metric.spec,
    )

    first_tuning = _rejected_tuning(
        composition.semantic_fingerprint,
        composition.metric.spec,
    )
    second_tuning = _make_tuning_output(
        model_type="narrow_fixture",
        run_name="iter_002",
        score=0.6,
        fingerprint=composition.semantic_fingerprint,
        metric_spec=composition.metric.spec,
    )
    captured_proposal_inputs: list[ProposalInput] = []
    emitted_proposals: list[ProposalOutput] = []
    proposed_widths = iter((REJECTED_WIDTH, REVISED_WIDTH))
    proposal_names = iter(("wide_fixture", "narrow_fixture"))

    def propose(inp: ProposalInput) -> ProposalOutput:
        captured_proposal_inputs.append(inp)
        width = next(proposed_widths)
        output = _make_proposal_output(next(proposal_names))
        output.baseline_config["model_config"] = {"hidden_dim": width}
        emitted_proposals.append(output)
        return output

    with (
        patch(
            "workflows.model_exploration.get_or_create_hardware_context",
            return_value=_hardware(),
        ),
        patch("workflows.model_exploration.ResultInterpretationAgent") as interpreter,
        patch("workflows.model_exploration.MLModelProposalAgent") as proposer,
        patch("workflows.model_exploration.MLModelImplementor") as implementor,
        patch("workflows.model_exploration.MLCodeValidatorAgent") as validator,
        patch("workflows.model_exploration.HyperparamTuningAgent") as tuner,
    ):
        interpreter.return_value.run.return_value = _make_interpretation_output()
        proposer.return_value.run.side_effect = propose
        implementor.return_value.run.return_value = _make_implementor_output()
        validator.return_value.run.return_value = _make_validator_output(passed=True)
        tuner.return_value.run.side_effect = [first_tuning, second_tuning]

        with bind_run_task_composition(
            composition,
            physical_data_root=str(seed_root / "data"),
        ):
            results = run_workflow(
                launch=WorkflowLaunchConfig(
                    data_dir=str(seed_root / "data"),
                    model_types=["punet"],
                    source_run_name="seed",
                    max_iterations=2,
                    max_rounds=1,
                    trial_vram_budget_gb=BUDGET_GIB,
                    formal_vram_budget_gb=BUDGET_GIB,
                ),
                workspace=str(tmp_path / "workspace"),
                run_name="vram_feedback",
                llm_config=_llm_config(),
                task_composition=composition,
            )

    assert len(results) == 2
    assert len(captured_proposal_inputs) == 2
    second_input = captured_proposal_inputs[1]
    rejection_lines = [
        line for line in second_input.previous_failures if "[PHYSICAL REJECTION]" in line
    ]
    assert len(rejection_lines) == 1
    assert "wide_fixture" in rejection_lines[0]
    assert "encoder.block" in rejection_lines[0]
    assert "29.10 GB" in rejection_lines[0]
    assert second_input.hardware_context is not None
    assert second_input.hardware_context.device_name == "synthetic-device"
    assert second_input.vram_budget_gb == BUDGET_GIB

    rendered = _build_reasoning_prompt(second_input)
    assert "[HARDWARE CONTEXT]" in rendered
    assert "[PHYSICAL REJECTION]" in rendered
    assert f"{BUDGET_GIB:.2f} GB" in rendered
    rejected_width = first_tuning.physical_rejections[0].attempt_config["hidden_dim"]
    revised_width = emitted_proposals[1].baseline_config["model_config"]["hidden_dim"]
    assert revised_width == REVISED_WIDTH
    assert revised_width < rejected_width
