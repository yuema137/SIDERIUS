"""The adaptor's own provenance record: which input reached which output.

Built purely from a decided ``AdaptorOutcome``; publication (path, write-once)
belongs to the executor.
"""

from typing import Literal

from pydantic import Field

from core.canonical_json import canonical_sha256
from execute_tools.evaluation_metric import MetricDirection
from workflows.definition.adaptor_strategies import DistributeStrategy, SelectStrategy
from workflows.definition.llm_strategies import AdaptorCombine

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


class StrategyEvidenceRef(AdaptorModel):
    """Anchor of an LLM COMBINE invocation's ``strategy.json`` (B2 ``StrategyResult``).

    ``path`` is relative to the adaptor directory, so the record is host-independent;
    ``sha256`` is the digest readback passes to ``replay_llm_strategy``.
    """

    path: str = Field(min_length=1)
    sha256: Digest


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
    # LLM COMBINE kinds only; omitted otherwise so deterministic records keep their bytes.
    strategy_evidence: StrategyEvidenceRef | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


def build_adaptor_record(
    *,
    adaptor_id: str,
    iteration: int,
    combine: AdaptorCombine,
    select: SelectStrategy,
    distribute: DistributeStrategy,
    outcome: AdaptorOutcome,
    fallback: str | None = None,
    strategy_evidence: StrategyEvidenceRef | None = None,
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
        strategy_evidence=strategy_evidence,
    )
