"""Observe cumulative chain usage without reopening scientific result payloads."""

import os
from pathlib import Path

from tools.candidate_worker.token_models import CandidateTokenSnapshot
from tools.candidate_worker.tokens import canonical, now, read_ledger_snapshot
from tools.native_chain.observation import NativeChainEvidence
from tools.native_chain.review import read_bytes
from tools.native_chain.token_identity import parse_token_identity

from .models import OperationFailure, OperationRecord
from .native_chain_read import chain_context
from .native_resume_lineage import ControlBudget, load_node, read_lineage, verify_root_fence

NOTE = (
    "Observed provider reports for the whole native run, including continuations. "
    "Scientific result files were not reverified. Missing or unrecorded usage may exist."
)


def retained_anchor(evidence: NativeChainEvidence) -> tuple[str, str] | None:
    if (
        evidence.availability == "integrity_failure"
        or evidence.anomalies
        or any(row.integrity == "invalid" for row in evidence.checkpoints)
    ):
        raise ValueError("retained native evidence has an integrity failure")
    identity, digest = evidence.token_run_id, evidence.token_sidecar_sha256
    if (identity is None) != (digest is None):
        raise ValueError("incomplete retained token identity")
    return (identity, digest) if identity is not None and digest is not None else None


def _anchors(record: OperationRecord, workspace: Path) -> set[tuple[str, str]] | None:
    request, _ = chain_context(record)
    fence = Path(request.envelope) / ".native-chain-operation/binding.json"
    writer_state = workspace.parent / f".{workspace.name}.siderius-writer"
    if not os.path.lexists(fence) or not os.path.lexists(writer_state):
        budget = ControlBudget()
        node = load_node(record.config, record.submission.request_id, budget, record=record)
        if record.submission.kind == "native_chain_resume":
            raise ValueError("native continuation control disappeared")
        if os.path.lexists(fence):
            verify_root_fence(node, budget)
        if node.terminal is not None or any(
            os.path.lexists(workspace / name) for name in (".token_run_id", "token_usage.jsonl")
        ):
            raise ValueError("native usage without an operation fence")
        return None
    lineage = read_lineage(record, allow_unlinked=True)
    if lineage.selected.id not in {node.id for node in lineage.nodes}:
        selected = lineage.selected
        if selected.terminal is not None or (
            selected.completion is not None
            and selected.completion.outcome != "pre_dispatch_failure"
        ):
            raise ValueError("unlinked native continuation outcome")
        return None
    anchors = set()
    for node in lineage.nodes:
        evidence = []
        if node.terminal is not None:
            evidence.append(node.terminal.evidence)
        if node.record.native_resume_admission is not None:
            evidence.append(node.record.native_resume_admission.evidence)
        for item in evidence:
            anchor = retained_anchor(item)
            if anchor is not None:
                anchors.add(anchor)
    return anchors


def read_native_tokens(record: OperationRecord) -> CandidateTokenSnapshot:
    request, admission = chain_context(record)
    observed_at = now()
    unavailable = CandidateTokenSnapshot(
        run_name=admission.run_name,
        observed_at=observed_at,
        availability="unavailable",
        reason="native_evidence_unavailable",
        scope="chain_cumulative",
        coverage_note=NOTE,
    )
    try:
        workspace = canonical(admission.workspace)
        canonical(request.envelope)
        anchors = _anchors(record, workspace)
        if anchors is None:
            return unavailable
        try:
            identity = parse_token_identity(
                read_bytes(workspace / ".token_run_id", 256), admission.run_name
            )
        except FileNotFoundError:
            if anchors:
                raise ValueError("retained native token identity disappeared") from None
            return unavailable
        if anchors and anchors != {identity}:
            raise ValueError("native token identity changed")
        snapshot = read_ledger_snapshot(workspace, identity[0], admission.run_name, observed_at)
        return snapshot.model_copy(
            update={
                "scope": "chain_cumulative",
                "coverage_note": NOTE,
                "identity_basis": "retained_sidecar" if anchors else "observed_sidecar",
            }
        )
    except (OSError, ValueError, RuntimeError) as error:
        raise OperationFailure(
            "integrity", "native token evidence could not be verified"
        ) from error
