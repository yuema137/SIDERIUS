"""The adaptor's own provenance record: which input reached which output.

Built purely from a decided ``AdaptorOutcome``; publication (path, write-once)
belongs to the executor.
"""

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, Field

from execute_tools.evaluation_metric import MetricDirection
from workflows.definition.adaptor_strategies import (
    DeterministicCombine,
    DistributeStrategy,
    SelectStrategy,
)

from .combine import Ranking, Role
from .items import AdaptorInputRef, AdaptorModel, Digest, ItemAdmission
from .run import AdaptorOutcome, AdaptorReason

PORT = "result"


class AdaptorContribution(AdaptorModel):
    output_port: str
    output_index: int | None
    inputs: tuple[AdaptorInputRef, ...] = Field(min_length=1)
    role: Role


class OutputDigest(AdaptorModel):
    port: str
    index: int | None
    status: Literal["emitted", "skipped"]
    sha256: Digest | None


class AdaptorRecord(AdaptorModel):
    schema_version: Literal["siderius.adaptor-record/v1"] = "siderius.adaptor-record/v1"
    adaptor_id: str = Field(min_length=1)
    iteration: int = Field(gt=0)
    strategies: tuple[str, str, str]  # combine, select, distribute kinds (versioned)
    parameters_sha256: Digest
    status: Literal["succeeded", "rejected", "failed"]
    reason: AdaptorReason | None
    admissible: tuple[ItemAdmission, ...]
    ranking: Ranking | None
    metric_id: str | None
    direction: MetricDirection | None
    contributions: tuple[AdaptorContribution, ...]
    outputs: tuple[OutputDigest, ...]
    fallback: str | None = None  # Fallback.combine kind actually run (B2 status "fallback")


def canonical_sha256(value: object) -> str:
    """SHA-256 of canonical JSON (sorted keys, compact) of a model or JSON value.

    No package-neutral canonical-JSON owner exists; this matches the encoding of
    ``WorkflowDefinition.declaration_digest`` (sorted keys, compact, ASCII).
    """
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def build_adaptor_record(
    *,
    adaptor_id: str,
    iteration: int,
    combine: DeterministicCombine,
    select: SelectStrategy,
    distribute: DistributeStrategy,
    outcome: AdaptorOutcome,
    fallback: str | None = None,
) -> AdaptorRecord:
    parameters = {
        "combine": combine.model_dump(mode="json"),
        "select": select.model_dump(mode="json"),
        "distribute": distribute.model_dump(mode="json"),
    }
    ranking = outcome.ranking
    return AdaptorRecord(
        adaptor_id=adaptor_id,
        iteration=iteration,
        strategies=(combine.kind, select.kind, distribute.kind),
        parameters_sha256=canonical_sha256(parameters),
        status=outcome.status,
        reason=outcome.reason,
        admissible=outcome.admissions,
        ranking=ranking,
        metric_id=ranking.metric_id if ranking else None,
        direction=ranking.direction if ranking else None,
        contributions=tuple(
            AdaptorContribution(
                output_port=PORT, output_index=output.index, inputs=output.inputs, role=output.role
            )
            for output in outcome.outputs
            if output.role is not None
        ),
        outputs=tuple(
            OutputDigest(
                port=PORT,
                index=output.index,
                status=output.status,
                sha256=canonical_sha256(output.value) if output.value is not None else None,
            )
            for output in outcome.outputs
        ),
        fallback=fallback,
    )
