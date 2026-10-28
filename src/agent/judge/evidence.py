"""Readback of judge call evidence. Never imports or calls an LLM provider.

The outcome of a recorded call is its verified :class:`JudgeCallEvidence`:
the file is anchored by a digest held by the referencing record, the request
and prompt are re-derived from the caller's verified inputs, and the payload is
re-validated against the template's response schema.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from agent.judge.template import JudgeTemplate
from agent.schemas.data_analysis.common import canonical_json_bytes, canonical_sha256
from agent.schemas.judge import CallRequest, JudgeCallEvidence, JudgeRoute


class JudgeEvidenceError(ValueError):
    """Recorded judge evidence does not reproduce from its verified inputs."""


def evidence_sha256(evidence: JudgeCallEvidence) -> str:
    """Digest of the canonical evidence bytes, as published."""
    return canonical_sha256(evidence)


def chain_prior_turns(earlier: Sequence[JudgeCallEvidence]) -> tuple[str, ...]:
    """``CallRequest.prior_turns`` for the call that follows ``earlier``."""
    return tuple(evidence_sha256(item) for item in earlier)


def read_call_evidence(path: Path, *, expected_sha256: str) -> JudgeCallEvidence:
    """Load evidence whose canonical bytes hash to ``expected_sha256``."""
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise JudgeEvidenceError(f"judge evidence digest mismatch: {path}")
    try:
        evidence = JudgeCallEvidence.model_validate_json(data)
    except ValidationError as exc:
        raise JudgeEvidenceError(f"judge evidence is malformed: {path}") from exc
    if canonical_json_bytes(evidence) != data:
        raise JudgeEvidenceError(f"judge evidence is not canonical: {path}")
    return evidence


def verify_call_evidence(
    path: Path,
    *,
    expected_sha256: str,
    request: CallRequest,
    template: JudgeTemplate,
    route: JudgeRoute,
) -> JudgeCallEvidence:
    """Replay one call from evidence: same request, prompt, schema and route."""
    evidence = read_call_evidence(path, expected_sha256=expected_sha256)
    if evidence.request != request:
        raise JudgeEvidenceError("judge evidence request differs from the re-projected request")
    if evidence.prompt != template.identity(request):
        raise JudgeEvidenceError("judge evidence prompt or response schema identity differs")
    if evidence.route != route:
        raise JudgeEvidenceError("judge evidence route differs from the configured route")
    if evidence.usage_label != template.usage_label:
        raise JudgeEvidenceError("judge evidence usage label differs from the template")
    payload = evidence.payload
    if payload is not None and not isinstance(payload, template.response_model):
        raise JudgeEvidenceError("judge evidence payload is not the template's response type")
    check = template.check_payload
    if payload is not None and check is not None and check(request, payload) is not None:
        raise JudgeEvidenceError("judge evidence payload is inadmissible for its request")
    return evidence


def verify_call_chain(evidences: Sequence[JudgeCallEvidence]) -> None:
    """Require one invocation's calls in recorded order, each covering all earlier ones."""
    if not evidences:
        return
    first = evidences[0].request
    for index, evidence in enumerate(evidences):
        request = evidence.request
        if request.invocation_sha256 != first.invocation_sha256:
            raise JudgeEvidenceError("judge call chain mixes invocations")
        if request.content.kind != first.content.kind:
            raise JudgeEvidenceError("judge call chain mixes request content kinds")
        if request.call_index != index:
            raise JudgeEvidenceError(f"judge call {index} records call_index {request.call_index}")
        if request.prior_turns != chain_prior_turns(evidences[:index]):
            raise JudgeEvidenceError(f"judge call {index} does not cover the earlier calls")
