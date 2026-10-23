"""Fixed native terminal evidence, readable without importing task/plugin runtime."""

import hashlib
from pathlib import Path

from pydantic import BaseModel

from core.generated_artifact_name import validate_generated_artifact_name
from execute_tools.impl_attempts import impl_attempt_dir

from .layout import candidate_proposal_dir
from .models import CandidateRunReceipt, TrainingOutputEvidence


class NativeOutputIdentity(BaseModel):
    """Read-only projection of the native output; native schema owns all other data."""

    run_name: str
    model_type: str
    candidate_id: str | None = None
    task_composition_fingerprint: str | None = None
    termination_reason: str | None = None


def capture_training_evidence(receipt: CandidateRunReceipt, model_name: str) -> CandidateRunReceipt:
    evidence = TrainingOutputEvidence(
        model_name=model_name,
        output_sha256=hashlib.sha256(
            Path(receipt.native_output_paths[-1]).read_bytes()
        ).hexdigest(),
    )
    terminal = receipt.model_copy(update={"training_output": evidence})
    verify_training_evidence(terminal)
    return terminal


def verify_training_evidence(receipt: CandidateRunReceipt) -> None:
    """Reject removal/replacement or identity drift at both reconcile and later read."""
    evidence = receipt.training_output
    if evidence is None:
        raise ValueError("native training output digest is missing from terminal receipt")
    validate_generated_artifact_name(evidence.model_name, field="model_name")
    directory = (
        candidate_proposal_dir(Path(receipt.workspace), receipt.run_name).parent
        / evidence.model_name
    )
    expected = directory / f"run_output_{receipt.run_name}.json"
    if len(receipt.native_output_paths) != 4 or receipt.native_output_paths[-1] != str(expected):
        raise ValueError("native training output path disagrees with managed layout")
    if not expected.resolve().is_relative_to(Path(receipt.workspace).resolve()):
        raise ValueError("native training output escapes workspace")
    proposal_dir = candidate_proposal_dir(Path(receipt.workspace), receipt.run_name)
    implementation_dir = Path(impl_attempt_dir(str(proposal_dir), 1))
    records = (
        proposal_dir / f"proposal_{receipt.run_name}.json",
        implementation_dir / f"implementor_{receipt.run_name}.json",
        implementation_dir / f"validation_{receipt.run_name}.json",
    )
    if receipt.native_output_paths[:3] != tuple(map(str, records)):
        raise ValueError("native candidate records disagree with managed layout")
    if receipt.proposal_storage != str(proposal_dir) or receipt.implementation_storage != str(
        implementation_dir
    ):
        raise ValueError("native candidate storage disagrees with managed layout")
    for record in records:
        if not record.is_file() or not record.resolve().is_relative_to(
            Path(receipt.workspace).resolve()
        ):
            raise ValueError("native candidate record missing or outside workspace")
    payload = expected.read_bytes()
    output = NativeOutputIdentity.model_validate_json(payload)
    if (
        hashlib.sha256(payload).hexdigest() != evidence.output_sha256
        or output.run_name != receipt.run_name
        or output.model_type != evidence.model_name
        or output.candidate_id != receipt.candidate_id
        or output.task_composition_fingerprint != receipt.composition_fingerprint
        or receipt.validation_passed is not True
        or receipt.status
        != ("failed" if output.termination_reason == "infrastructure_abort" else "completed")
    ):
        raise ValueError("native training output integrity mismatch")
