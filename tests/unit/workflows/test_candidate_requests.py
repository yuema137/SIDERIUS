"""Candidate enrichment must preserve information at the live workflow seam."""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from agent.schemas.implementor import ImplementorTaskBlocks
from agent.schemas.model_probe import ModelProbeContext
from agent.schemas.proposal import CustomLossSpec, InheritedComponent
from agent.schemas.protocols.ml_model_impl_to_ml_model_valid import local_all_fields
from agent.schemas.protocols.ml_model_propose_to_ml_model_impl import local_full_spec
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from agent.schemas.task_config import ForwardContract
from core.hardware_context import HardwareContext
from tests.helpers.step04a_fixtures import regressor_model_io, tidmad_model_io
from tests.unit.workflows.test_model_exploration import (
    _make_implementor_output,
    _make_proposal_output,
)
from tests.unit.workflows.test_u6_impl_attempt_layout import _run_with_forced_retries
from workflows.candidate_requests import enrich_implementation_request, enrich_validation_request
from workflows.llm_config import NodeLLMConfig, TunerLLMConfig, WorkflowLLMConfig


def _custom_proposal():
    proposal = _make_proposal_output()
    loss = CustomLossSpec(
        loss_name="request_parity_loss",
        description="A task-owned loss.",
        mathematical_definition="mean(abs(prediction - target))",
    )
    return proposal.model_copy(
        update={
            "candidate_id": "cand_request_parity",
            "custom_loss_spec": loss,
            "baseline_config": {
                **proposal.baseline_config,
                "loss_config": {
                    "loss_type": "custom",
                    "loss_name": loss.loss_name,
                },
            },
            "inherited_components": [
                InheritedComponent(
                    component="local_context",
                    source_type="experiment",
                    source_id="punet",
                    contribution_evidence="Reference architecture for the current proposal.",
                )
            ],
        }
    )


def _enriched_retry_run(tmp_path):
    proposal = _custom_proposal()
    constructors = {}
    blocks = ImplementorTaskBlocks(science_domain="synthetic scalar estimation")
    with (
        patch("nodes.proposal_helpers.load_model_source", return_value="class Reference: pass"),
        patch("workflows.model_exploration.resolve_run_implementor_blocks", return_value=blocks),
    ):
        result = _run_with_forced_retries(
            tmp_path,
            (False, True),
            proposal_override=proposal,
            launch_overrides={
                "human_advice_implement": "",
                "human_advice_validate": "Check lineage",
                "trial_vram_budget_gb": 5.5,
            },
            llm_config=WorkflowLLMConfig(
                implement=NodeLLMConfig(
                    provider="openai", model_id="test-implement", max_retries=None
                ),
                validate=NodeLLMConfig(provider="deepseek", model_id="test-validate"),
                tune=TunerLLMConfig(planner_strategy="native-timing-v1"),
            ),
            constructor_calls=constructors,
        )
    return result, proposal, constructors


def test_live_retries_preserve_enrichment_and_routing(tmp_path):
    """Dropping caller enrichment loses advice/lineage/feedback despite valid schemas."""
    result, proposal, constructors = _enriched_retry_run(tmp_path)
    impl_inputs, valid_inputs = result[2:4]
    for impl, valid in zip(impl_inputs, valid_inputs, strict=True):
        assert impl.candidate_id == valid.candidate_id == "cand_request_parity"
        assert impl.custom_loss_spec == proposal.custom_loss_spec
        assert impl.baseline_config == proposal.baseline_config
        assert impl.task_composition_ref is not None
        assert impl.forward_contract is not None
        assert impl.task_description
        assert impl.implementor_blocks.science_domain == "synthetic scalar estimation"
        assert impl.hardware_context is not None
        assert impl.vram_budget_gb == 5.5
        assert impl.human_advice == ""
        assert impl.reference_code == {"punet": "class Reference: pass"}
        assert valid.human_advice == "Check lineage"
        assert valid.inherited_components == proposal.inherited_components
        assert valid.llm_provider == "deepseek"
        assert valid.llm_model_id == "test-validate"
    assert impl_inputs[0].previous_validation_failure is None
    assert impl_inputs[1].previous_validation_failure == "pytest failed: shape mismatch"
    assert impl_inputs[0].storage.local.workspace != impl_inputs[1].storage.local.workspace
    for call in constructors["implement"]:
        assert call.kwargs["model_id"] == "test-implement"
        assert "max_retries" not in call.kwargs
    for call in constructors["validate"]:
        assert call.kwargs["provider"] == valid_inputs[0].llm_provider
        assert call.kwargs["model_id"] == valid_inputs[0].llm_model_id
        assert "max_retries" not in call.kwargs


def test_protocol_failure_precedes_task_resolution(tmp_path, capsys):
    """Eager task resolution would mask the original storage/protocol error."""
    import workflows.model_exploration as workflow

    original = workflow.load_task_config
    preparing_candidate = False
    original_storage = workflow.impl_attempt_storage

    def storage(*args, **kwargs):
        nonlocal preparing_candidate
        result = original_storage(*args, **kwargs)
        preparing_candidate = True
        return result

    def resolve():
        if preparing_candidate:
            raise AssertionError("task resolved before native protocol completed")
        return original()

    def invalid_storage(*args, **kwargs):
        raise ValueError("native storage rejected")

    with (
        patch.object(workflow, "load_task_config", side_effect=resolve),
        patch.object(workflow, "local_full_spec", side_effect=invalid_storage),
        patch.object(workflow, "impl_attempt_storage", side_effect=storage),
    ):
        _run_with_forced_retries(tmp_path, (True,))

    output = capsys.readouterr().out
    assert "ValueError: native storage rejected" in output
    assert "task resolved before native protocol completed" not in output


@pytest.mark.parametrize(
    "advice,failure,references",
    [
        (None, None, {}),
        ("", "", {}),
        ("New advice", "New failure", {"new": "code"}),
    ],
)
def test_optional_enrichment_preserves_absence_and_explicit_empty(
    tmp_path,
    advice,
    failure,
    references,
):
    """Truthiness must not collapse empty advice/failure into absence or clear references."""
    storage = StorageConfig(
        backend="local",
        local=LocalStorageConfig(
            workspace=str(tmp_path),
            run_name="conditional",
        ),
    )
    proposal = _custom_proposal()
    request = local_full_spec(proposal, storage)
    request.human_advice = "Previous advice"
    request.previous_validation_failure = "Previous failure"
    request.reference_code = {"old": "old code"}
    request.implementor_blocks = ImplementorTaskBlocks(science_domain="previous task")
    request.vram_budget_gb = 9.0
    request.hardware_context = HardwareContext(
        device_name="synthetic",
        total_memory_bytes=1024,
        compute_capability=(0, 0),
        multiprocessor_count=1,
        torch_version="synthetic",
        hostname="fixture",
        device_available=False,
        discovered_at=datetime(2020, 1, 1, tzinfo=UTC),
    )
    before = request.model_dump(mode="json")
    forward = ForwardContract(input_shape="[B, F]", output_shape="[B, 1]")
    enrich_implementation_request(
        request,
        task_description="Scalar estimation",
        forward_contract=forward,
        implementor_blocks=None,
        hardware_context=None,
        vram_budget_gb=None,
        human_advice=advice,
        reference_code=references,
        previous_validation_failure=failure,
    )
    expected = {
        **before,
        "task_description": "Scalar estimation",
        "implementor_blocks": None,
        "vram_budget_gb": None,
        "hardware_context": None,
        "forward_contract": forward.model_dump(),
        "human_advice": "Previous advice" if advice is None else advice,
        "previous_validation_failure": "Previous failure" if failure is None else failure,
        "reference_code": references or {"old": "old code"},
    }
    assert request.model_dump(mode="json") == expected
    assert proposal.custom_loss_spec == request.custom_loss_spec


@pytest.mark.parametrize("contract", [None, regressor_model_io(), tidmad_model_io()])
def test_validation_enrichment_keeps_native_probe_and_identity(tmp_path, contract):
    """Enrichment cannot overwrite native identity, model geometry or probe authority."""
    storage = StorageConfig(
        backend="local",
        local=LocalStorageConfig(
            workspace=str(tmp_path),
            run_name="validation",
        ),
    )
    probe = ModelProbeContext(
        manifest_path=str(tmp_path / "task.yaml"),
        semantic_fingerprint="a" * 64,
        task_data_path_id="synthetic",
    )
    output = _make_implementor_output().model_copy(
        update={
            "candidate_id": "candidate_from_implementor",
            "model_io_contract": contract,
            "model_probe_context": probe,
        }
    )
    request = local_all_fields(
        output, storage, llm_provider="deepseek", llm_model_id="test-validator"
    )
    before = request.model_dump(mode="json")
    lineage = _custom_proposal().inherited_components
    enrich_validation_request(request, human_advice="", inherited_components=lineage)
    expected = {
        **before,
        "human_advice": "",
        "inherited_components": [c.model_dump() for c in lineage],
    }
    assert request.model_dump(mode="json") == expected
    enrich_validation_request(request, human_advice=None, inherited_components=[])
    assert request.model_dump(mode="json") == expected
