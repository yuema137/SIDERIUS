"""Boundary witnesses for immutable custom-loss contract transport."""

import hashlib
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from agent.schemas.custom_loss_contract import (
    EqualShapeApplicability,
    TaskOwnedCustomLoss,
    build_custom_loss_contract_snapshot,
    merge_task_owned_custom_loss,
    parse_custom_loss_contract_snapshot,
    resolve_custom_loss_inventory,
)
from agent.schemas.model_io_contract import Dimension, ModelIOContract, TensorAxis, TensorContract
from agent.schemas.task_config import ForwardContract
from core.capability_registry import (
    CapabilityContractSnapshot,
    CapabilityMetadata,
    CapabilityRegistry,
)
from ml_models.models_format_sandbox import DtypeAdmissibility


def _tensor(*dims: int | str) -> TensorContract:
    return TensorContract(
        axes=tuple(
            TensorAxis(
                dimension=Dimension(fixed=dim) if isinstance(dim, int) else Dimension(symbolic=dim)
            )
            for dim in dims
        ),
        dtype=DtypeAdmissibility(admissible=("float32",)),
    )


def _snapshot() -> CapabilityContractSnapshot:
    tensor = _tensor("B", 1)
    return build_custom_loss_contract_snapshot(
        tensor,
        tensor,
        EqualShapeApplicability(dtype=DtypeAdmissibility(admissible=("float32",)), rank=2),
    )


def test_snapshot_is_canonical_immutable_and_semantically_parseable():
    snapshot = _snapshot()
    assert parse_custom_loss_contract_snapshot(snapshot).prediction == _tensor("B", 1)
    with pytest.raises(ValidationError, match="frozen"):
        snapshot.sha256 = "0" * 64
    raw = snapshot.model_dump()
    raw["canonical_payload"] = json.dumps(json.loads(raw["canonical_payload"]), indent=2)
    with pytest.raises(ValidationError, match="canonical JSON"):
        CapabilityContractSnapshot.model_validate(raw)


def test_registry_register_replace_round_trip_preserves_exact_snapshot(tmp_path):
    registry = CapabilityRegistry(index_path=str(tmp_path / "index.json"))
    snapshot = _snapshot()
    metadata = CapabilityMetadata(
        name="bounded_loss",
        capability_type="loss",
        file_path="/first.py",
        created_at="2026-09-13T00:00:00Z",
        contract_snapshot=snapshot,
    )
    registry.register(metadata)
    registry.replace(metadata.model_copy(update={"file_path": "/promoted.py"}))
    restored = CapabilityRegistry(index_path=str(tmp_path / "index.json")).list()[0]
    assert restored.file_path == "/promoted.py"
    assert restored.contract_snapshot == snapshot


def test_task_composition_projection_round_trips_contract_and_preserves_segmentation():
    from workflows.task_composition import build_task_composition_ref

    tensor = _tensor("B", 1)
    declaration = EqualShapeApplicability(dtype=DtypeAdmissibility(admissible=("float32",)), rank=2)
    forward = ForwardContract(
        model_io=ModelIOContract(input=_tensor("B", 4), output=tensor),
        supervision_target=tensor,
        custom_loss_applicability=declaration,
        segmentation_applicability="not_applicable",
    )

    class _Path:
        task_data_path_id = "fixture"

    composition = SimpleNamespace(
        semantic_fingerprint="fingerprint",
        task_data_path=_Path(),
        task_health_binding="none",
        forward_contract=forward,
        objective=None,
        parameter_rules=None,
    )
    projected = build_task_composition_ref(composition)
    assert projected is not None
    restored = type(projected).model_validate_json(projected.model_dump_json())
    assert restored.supervision_target == tensor
    assert restored.custom_loss_applicability == declaration
    assert restored.segmentation_applicability == "not_applicable"
    assert build_task_composition_ref(None) is None


def test_task_owned_loss_projection_reaches_inventory_without_registry_write(tmp_path):
    """A selected local objective is offered even when durable inventory is empty.

    MUTATION TARGET: removing the run-scoped merge makes this composed inventory
    empty and causes the proposer/implementor/tuner boundary to refuse before
    their first LLM call; the registry spy also catches accidental persistence.
    """
    snapshot = _snapshot()
    implementation = tmp_path / "task_loss.py"
    implementation.write_text("PLUGIN_LOSS_TYPE = 'task_loss'\n", encoding="utf-8")
    task_loss = TaskOwnedCustomLoss(
        name="task_loss",
        file_path=str(implementation),
        content_sha256=hashlib.sha256(implementation.read_bytes()).hexdigest(),
        contract_snapshot=snapshot,
    )
    ref = SimpleNamespace(
        supervision_target=_tensor("B", 1),
        custom_loss_applicability=parse_custom_loss_contract_snapshot(snapshot).applicability,
        objective=SimpleNamespace(loss_type="custom", loss_name="task_loss"),
        task_owned_custom_loss=task_loss,
    )

    class _EmptyRegistry:
        def list(self, *, capability_type):
            return []

        def register(self, metadata):
            raise AssertionError("task-owned projection must not register globally")

    inventory = resolve_custom_loss_inventory(
        _EmptyRegistry().list(capability_type="loss"), snapshot, ref
    )
    assert inventory.names == ("task_loss",)


@pytest.mark.parametrize("kind", ["missing", "digest"])
def test_task_owned_loss_inventory_refuses_unpinned_file(tmp_path, kind):
    """Inventory refuses a missing or edited implementation before execution.

    MUTATION TARGET: dropping filesystem/digest validation would let a stale
    composition select code different from the pinned objective.
    """
    path = tmp_path / "task_loss.py"
    if kind == "digest":
        path.write_text("changed", encoding="utf-8")
    loss = TaskOwnedCustomLoss(
        name="task_loss",
        file_path=str(path),
        content_sha256="a" * 64,
        contract_snapshot=_snapshot(),
    )
    with pytest.raises(ValueError, match="task_loss"):
        merge_task_owned_custom_loss((), loss)


def test_custom_loss_spec_json_and_protocol_preserve_framework_snapshot(tmp_path):
    from agent.schemas.hyperparam_tuning import TaskCompositionRef
    from agent.schemas.proposal import CustomLossSpec, ProposalOutput
    from agent.schemas.protocols.ml_model_propose_to_ml_model_impl import local_full_spec
    from agent.schemas.storage import LocalStorageConfig, StorageConfig

    snapshot = _snapshot()
    spec = CustomLossSpec(
        loss_name="bounded_loss",
        description="bounded",
        mathematical_definition="mean((x-y)^2)",
        contract_snapshot=snapshot,
    )
    restored_spec = CustomLossSpec.model_validate_json(spec.model_dump_json())
    assert restored_spec.contract_snapshot == snapshot
    proposal = ProposalOutput(
        model_name="transport_model",
        model_description="model",
        mathematical_definition="f(x)",
        motivation="transport",
        expert_advice={},
        baseline_config={
            "model_config": {},
            "train_config": {},
            "loss_config": {"loss_type": "custom", "loss_name": "bounded_loss"},
        },
        custom_loss_spec=restored_spec,
    )
    composition_ref = TaskCompositionRef(
        semantic_fingerprint="fixture-fingerprint",
        task_data_path_id="fixture-path",
        task_health_binding="none",
        supervision_target=_tensor("B", 1),
        custom_loss_applicability=EqualShapeApplicability(
            dtype=DtypeAdmissibility(admissible=("float32",)),
            rank=2,
        ),
    )
    implementor_input = local_full_spec(
        proposal,
        StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path), run_name="transport"),
        ),
        task_composition_ref=composition_ref,
    )
    assert implementor_input.custom_loss_spec.contract_snapshot == snapshot
    assert implementor_input.task_composition_ref == composition_ref


def test_proposal_protocol_validates_task_composition_ref_during_input_construction(
    tmp_path,
):
    """A malformed typed-hop payload must fail at the protocol boundary.

    MUTATION TARGET: assigning ``task_composition_ref`` after constructing
    ``ImplementorInput`` bypasses Pydantic validation and makes this call
    return instead of raising.
    """
    from agent.schemas.proposal import ProposalOutput
    from agent.schemas.protocols.ml_model_propose_to_ml_model_impl import local_full_spec
    from agent.schemas.storage import LocalStorageConfig, StorageConfig

    proposal = ProposalOutput(
        model_name="transport_model",
        model_description="model",
        mathematical_definition="f(x)",
        motivation="transport",
        expert_advice={},
        baseline_config={"model_config": {}, "train_config": {}, "loss_config": {}},
    )
    with pytest.raises(ValidationError, match="semantic_fingerprint"):
        local_full_spec(
            proposal,
            StorageConfig(
                backend="local",
                local=LocalStorageConfig(workspace=str(tmp_path), run_name="transport"),
            ),
            task_composition_ref={"task_data_path_id": "missing-fields"},  # type: ignore[arg-type]
        )


def test_proposer_replaces_llm_contract_metadata_with_task_projection():
    from agent.schemas.proposal import CustomLossSpec, ProposalOutput
    from nodes.ml_model_proposal_agent.ml_model_proposal_agent import (
        _attach_custom_loss_contract,
    )

    output_tensor = _tensor("B", 1)
    declaration = EqualShapeApplicability(dtype=DtypeAdmissibility(admissible=("float32",)), rank=2)
    forward = ForwardContract(
        model_io=ModelIOContract(input=_tensor("B", 4), output=output_tensor),
        supervision_target=output_tensor,
        custom_loss_applicability=declaration,
    )
    wrong = build_custom_loss_contract_snapshot(
        _tensor("B", 2),
        _tensor("B", 2),
        declaration,
    )
    proposal = ProposalOutput(
        model_name="transport_model",
        model_description="model",
        mathematical_definition="f(x)",
        motivation="transport",
        expert_advice={},
        baseline_config={
            "model_config": {},
            "train_config": {},
            "loss_config": {"loss_type": "custom", "loss_name": "bounded_loss"},
        },
        custom_loss_spec=CustomLossSpec(
            loss_name="bounded_loss",
            description="bounded",
            mathematical_definition="mean((x-y)^2)",
            contract_snapshot=wrong,
        ),
    )
    attached = _attach_custom_loss_contract(proposal, forward)
    assert attached.custom_loss_spec.contract_snapshot == build_custom_loss_contract_snapshot(
        output_tensor, output_tensor, declaration
    )
