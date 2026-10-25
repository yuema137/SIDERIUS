"""Read stored chain identity and host supervision without fresh admission."""

import hashlib
import os
from pathlib import Path

from tools.native_chain.observation import (
    CURRENT_OBSERVATION_POLICY,
    NativeChainEvidence,
    ObservationBounds,
    ObservationPolicy,
    observe_native_chain,
)

from .files import encode, read_bytes
from .models import Completion, OperationRecord, OperationSnapshot, ProcessObservation
from .native_chain_models import NativeChainObservation, NativeChainTerminal
from .store import now


def chain_evidence(
    record: OperationRecord, *, policy: ObservationPolicy = CURRENT_OBSERVATION_POLICY
) -> NativeChainEvidence:
    assert record.submission.kind == "native_chain" and record.native_chain_admission is not None
    request = record.submission.request
    admission = record.native_chain_admission
    return observe_native_chain(
        Path(admission.workspace),
        admission.run_name,
        ObservationBounds(
            final_iteration=admission.final_iteration,
            input_max_bytes=request.input_max_bytes,
            max_observation_bytes=request.max_observation_bytes,
        ),
        policy=policy,
    )


def read_native_chain_operation(
    record: OperationRecord,
    process: ProcessObservation,
    completion: Completion | None,
) -> OperationSnapshot:
    admission = record.native_chain_admission
    assert record.submission.kind == "native_chain" and admission is not None
    state = "active" if process.status == "alive" else "unknown"
    reason = "observed_wrapper" if process.status == "alive" else "outcome_unresolved"
    terminal = None
    path = Path(record.config.state_root) / "operations" / str(record.submission.request_id)
    if completion is not None:
        state = "unknown"
        reason = completion.reason
        if completion.outcome == "pre_dispatch_failure":
            if os.path.lexists(path / "native-chain-terminal.json"):
                raise ValueError("pre-dispatch failure contradicts chain terminal")
            state = "operation_failed"
        elif completion.outcome == "native_chain":
            payload = read_bytes(path / "native-chain-terminal.json", private_file=True)
            terminal = NativeChainTerminal.model_validate_json(payload)
            if (
                hashlib.sha256(payload).hexdigest() != completion.terminal_digest
                or terminal.operation_id != record.submission.request_id
                or terminal.request_digest != record.request_digest
                or terminal.capture_sha256 != admission.capture_sha256
                or terminal.workspace != admission.workspace
                or terminal.envelope != record.submission.request.envelope
                or terminal.runtime_digest != hashlib.sha256(encode(record.runtime)).hexdigest()
            ):
                raise ValueError("chain terminal identity mismatch")
            if (
                terminal.supervision.direct_child_reaped
                and terminal.supervision.cleanup.final.status == "absent"
            ):
                state = "completed"
            else:
                reason = "native_chain_cleanup_unresolved"
    policy = terminal.observation_policy if terminal is not None else CURRENT_OBSERVATION_POLICY
    evidence = chain_evidence(record, policy=policy)
    if terminal is not None and evidence != terminal.evidence:
        evidence = NativeChainEvidence(
            availability="integrity_failure", anomalies=("changed_after_terminal",)
        )
    elif policy != CURRENT_OBSERVATION_POLICY:
        evidence = chain_evidence(record)
    return OperationSnapshot(
        operation_id=record.submission.request_id,
        kind="native_chain",
        request_digest=record.request_digest,
        observed_at=now(),
        state=state,
        process=process,
        reason=reason,
        finishing=state == "completed" and process.status == "alive",
        native_chain=NativeChainObservation(
            admission=admission, terminal=terminal, evidence=evidence
        ),
    )
