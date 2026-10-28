"""The declared literature -> proposal edges: one protocol owner for worker and verifier.

``proposal_input`` applies the catalogued protocol of one proposal to its typed
literature value: the review result (``native-literature-candidate/v1``), the
``collect/v1`` collection (``literature-collection-to-proposal``) or one
``split-items/v1`` output (``literature-to-proposal``). Unit dispatch and
``verify_literature_evidence`` call it over the same typed values, so the
proposal input the proposer read and the one the verifier derives cannot drift.
"""

import hashlib
import json
from collections.abc import Iterable, Mapping
from pathlib import Path

from pydantic import BaseModel

from agent.schemas.literature_review import LiteratureReviewInput, LiteratureReviewOutput
from agent.schemas.proposal import ProposalInput
from agent.schemas.protocols.ml_literature_review_to_ml_model_propose import (
    NamedLiteratureReviewOutput,
    local_typed_evidence,
    local_typed_evidence_many,
)
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from core.file_identity import open_identity_file, regular_file_snapshot
from workflows.adaptors import AdaptorOutcome
from workflows.adaptors.combine import CollectedItems
from workflows.definition import AdaptorSource
from workflows.definition.fanout import ProposalFamilies, execution_families

from .adaptor_phase import adaptor_value
from .graph_evidence import read_graph_control
from .graph_models import GraphNodeEvidence, GraphTrace
from .inputs import require_storage
from .layout import candidate_control_dir, literature_input_path, proposal_input_path
from .models import CandidateRunReceipt, CandidateRunRequest

COLLECTION_PROTOCOL = "literature-collection-to-proposal"


def literature_collection(value: BaseModel) -> list[NamedLiteratureReviewOutput]:
    """The ``literature.collection`` value of a ``collect/v1`` output, in collected order.

    Each entry keeps its ``contribution_id`` (the source review node id), which the
    proposer prompt shows as that review's heading.
    """
    if not isinstance(value, CollectedItems):
        raise ValueError("literature collection requires a collect/v1 output")
    reviews = []
    for entry in value.entries:
        if entry.contract != "literature.output" or not isinstance(
            entry.value, LiteratureReviewOutput
        ):
            raise ValueError("literature collection requires collected literature.output values")
        reviews.append(
            NamedLiteratureReviewOutput(contribution_id=entry.contribution_id, output=entry.value)
        )
    return reviews


def proposal_input(
    shape: ProposalFamilies,
    node_id: str,
    seed: ProposalInput,
    reviews: Mapping[str, BaseModel],
    outcomes: Mapping[str, AdaptorOutcome],
) -> ProposalInput:
    """``seed`` with the literature evidence this proposal's declared edge delivers.

    ``reviews`` holds succeeded review results by node id; ``outcomes`` the decided
    adaptor outcomes. A proposal without a literature edge keeps its seed.
    """
    if shape.literature is not None:
        review = reviews[shape.literature.review]
        assert isinstance(review, LiteratureReviewOutput)
        return local_typed_evidence(review, proposal_input=seed)
    edges = shape.literature_adaptor
    if edges is None:
        return seed
    outcome = outcomes.get(edges.adaptor)
    if outcome is None:
        raise ValueError(f"proposal {node_id} reads adaptor {edges.adaptor} before its outcome")
    source = AdaptorSource(adaptor=edges.adaptor, index=edges.proposal(node_id).index)
    value = adaptor_value(outcome, source)
    if edges.protocol == COLLECTION_PROTOCOL:
        return local_typed_evidence_many(literature_collection(value), proposal_input=seed)
    if not isinstance(value, LiteratureReviewOutput):
        raise ValueError(f"adaptor {edges.adaptor} output is not a literature review")
    return local_typed_evidence(value, proposal_input=seed)


def verify_literature_evidence(
    request: CandidateRunRequest,
    initial: CandidateRunReceipt,
    trace: GraphTrace,
    *,
    iteration: int = 1,
    outcomes: Mapping[str, AdaptorOutcome] | None = None,
) -> None:
    """Reconstruct every typed review edge from captured source inputs, not child claims.

    Each succeeded review's managed input must equal its capture and agree with
    every fed proposal's seed on task and constraints; its record must be the
    traced bytes of this run. Each succeeded proposal's diagnostic input must equal
    ``proposal_input`` over the verified review records and adaptor ``outcomes``.
    """
    shape = execution_families(
        request.preview.document.definition, request.preview.execution_profile
    )
    nodes = {node.node_id: node for node in trace.nodes}
    workspace = Path(initial.workspace)
    captured = _CapturedInputs(request, workspace, iteration)
    if shape.literature is not None:
        edge = shape.literature
        review_bindings = {edge.review: edge.review_binding}
        seed_bindings = {edge.proposal: edge.seed_binding}
    else:
        edges = shape.literature_adaptor
        assert edges is not None
        review_bindings = {item.node: item.binding for item in edges.reviews}
        seed_bindings = {item.node: item.seed_binding for item in edges.proposals}
    succeeded = [review for review in review_bindings if nodes[review].state == "succeeded"]
    if not succeeded:
        return
    seeds = {
        proposal: _seed(captured.payload(binding), nodes[proposal], request.run_name)
        for proposal, binding in seed_bindings.items()
    }
    outputs: dict[str, BaseModel] = {
        review: _review_output(
            request, captured.payload(binding), nodes[review], seeds.values(), workspace, iteration
        )
        for review, binding in review_bindings.items()
        if review in succeeded
    }
    for proposal, seed in seeds.items():
        if nodes[proposal].state != "succeeded":
            continue
        actual = ProposalInput.model_validate_json(
            read_graph_control(
                proposal_input_path(
                    workspace, request.preview.execution_profile, proposal, iteration=iteration
                )
            )
        )
        if actual != proposal_input(shape, proposal, seed, outputs, outcomes or {}):
            raise ValueError("proposal input does not match the declared literature edge")


class _CapturedInputs:
    """Captured external bytes, each checked against its launch observation digest."""

    def __init__(self, request: CandidateRunRequest, workspace: Path, iteration: int) -> None:
        self.request, self.control = request, candidate_control_dir(workspace, iteration=iteration)

    def payload(self, binding: str) -> bytes:
        index, observation = next(
            (index, item)
            for index, item in enumerate(self.request.files)
            if item.reference == f"external.{binding}"
        )
        payload = read_graph_control(self.control / f"input_{index:03}.snapshot")
        if hashlib.sha256(payload).hexdigest() != observation.sha256:
            raise ValueError("literature captured input digest mismatch")
        return payload


def _managed(node: GraphNodeEvidence, run_name: str) -> StorageConfig:
    return StorageConfig(
        backend="local", local=LocalStorageConfig(workspace=node.storage, run_name=run_name)
    )


def _seed(payload: bytes, proposal: GraphNodeEvidence, run_name: str) -> ProposalInput:
    """The captured seed with its managed proposal storage, as materialization sets it."""
    storage = _managed(proposal, run_name)
    raw = json.loads(payload)
    raw.setdefault("storage", storage.model_dump(mode="json"))
    seed = ProposalInput.model_validate(raw)
    require_storage(seed.storage, storage)
    seed.storage = storage
    return seed


def _review_output(
    request: CandidateRunRequest,
    payload: bytes,
    review: GraphNodeEvidence,
    seeds: Iterable[ProposalInput],
    workspace: Path,
    iteration: int,
) -> LiteratureReviewOutput:
    """One succeeded review: input capture and task binding, then its traced record."""
    selected = LiteratureReviewInput.model_validate_json(payload)
    managed = _managed(review, request.run_name)
    require_storage(selected.storage, managed)
    selected.storage = managed
    actual = LiteratureReviewInput.model_validate_json(
        read_graph_control(literature_input_path(workspace, review.node_id, iteration=iteration))
    )
    if (
        actual != selected
        or selected.run_name != request.run_name
        or any(
            (selected.task_description, selected.constraint_context)
            != (seed.task_description, seed.constraint_context)
            for seed in seeds
        )
    ):
        raise ValueError("literature diagnostic/task binding mismatch")
    assert review.record_path is not None
    with open_identity_file(review.record_path, require_no_follow=True) as handle:
        before = regular_file_snapshot(handle)
        record = handle.read()
        if (
            regular_file_snapshot(handle) != before
            or hashlib.sha256(record).hexdigest() != review.record_sha256
        ):
            raise ValueError("literature native record changed while verifying")
    output = LiteratureReviewOutput.model_validate_json(record)
    if output.run_name != request.run_name:
        raise ValueError("literature native record run binding mismatch")
    return output
