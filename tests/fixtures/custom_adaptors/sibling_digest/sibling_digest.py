"""Synthetic custom COMBINE: merge literature findings into one expert-context value.

Protected fields (``source``) stay empty; the framework stamps adaptor provenance.
"""

from pydantic import BaseModel, ConfigDict, Field

from agent.schemas.proposal import ExpertContextItem

from .ranking import by_confidence


class Params(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    max_items: int = Field(default=5, ge=1, le=32)


def adapt(inputs, params, ctx):
    findings = [finding for item in inputs["reviews"] for finding in item.value.findings]
    findings.sort(key=by_confidence)
    ctx.log(f"{len(findings)} findings")
    return [
        [
            ExpertContextItem(
                source="",
                kind="literature",
                content=finding.content,
                source_ref=f"sd{index}",
                confidence=finding.confidence,
            )
            for index, finding in enumerate(findings[: params.max_items])
        ]
    ]
