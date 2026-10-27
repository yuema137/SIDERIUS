"""Non-executable binding edits; promotion retains the published validator.

An absent patch retains the base binding. An explicit null source disconnects
the socket; it never supplies a null value to a scientific input.
"""

import json
from typing import Literal, Self

from pydantic import ValidationError, model_validator

from .catalog import PROTOCOLS
from .models import (
    AuthoredWorkflowDocument,
    DeclarationModel,
    ExternalRequest,
    Identifier,
    Source,
)


class BindingPatch(DeclarationModel):
    node: Identifier
    argument: str | None
    source: Source | None


class WorkflowDraft(DeclarationModel):
    """A validated starting document with explicit, non-executable binding edits."""

    base_document: AuthoredWorkflowDocument
    bindings: tuple[BindingPatch, ...] = ()

    @model_validator(mode="after")
    def known_unique_targets(self) -> Self:
        nodes = {node.id: node for node in self.base_document.definition.nodes}
        seen: set[tuple[str, str | None]] = set()
        for patch in self.bindings:
            key = (patch.node, patch.argument)
            if key in seen:
                raise ValueError("Draft contains duplicate binding targets")
            seen.add(key)
            node = nodes.get(patch.node)
            if node is None:
                raise ValueError(f"Unknown draft node: {patch.node}")
            arguments = (
                {None}
                if isinstance(node.request, ExternalRequest)
                else {item.name for item in PROTOCOLS[node.request.protocol].arguments}
            )
            if patch.argument not in arguments:
                raise ValueError(f"Unknown draft socket: {patch.node}.{patch.argument}")
        return self


class DraftInspection(DeclarationModel):
    status: Literal["incomplete", "invalid", "complete"]
    document: AuthoredWorkflowDocument | None = None
    diagnostics: tuple[str, ...] = ()


def inspect_draft(draft: WorkflowDraft) -> DraftInspection:
    """Apply edits only to temporary data and invoke the native document validator.

    No source is rendered, published or executed. Invalid typed connections and
    cycles are diagnosed by the same validator used for ordinary source.
    """
    draft = WorkflowDraft.model_validate_json(draft.model_dump_json(warnings=False))
    payload = draft.base_document.model_dump(mode="json")
    nodes = {node["id"]: node for node in payload["definition"]["nodes"]}
    incomplete = []
    for patch in draft.bindings:
        request = nodes[patch.node]["request"]
        source = patch.source.model_dump(mode="json") if patch.source is not None else None
        if request["kind"] == "external":
            if source is None:
                incomplete.append(f"{patch.node}.request: required input is unbound")
            elif source["kind"] != "external":
                return DraftInspection(
                    status="invalid",
                    diagnostics=(f"{patch.node}.request requires an external binding",),
                )
            else:
                request["binding"] = source["binding"]
            continue
        arguments = request["arguments"]
        existing = next((item for item in arguments if item["name"] == patch.argument), None)
        if source is not None:
            if existing is not None:
                existing["source"] = source
            else:
                arguments.append({"name": patch.argument, "source": source})
        else:
            if existing is not None:
                arguments.remove(existing)
            if any(
                item.name == patch.argument and item.required
                for item in PROTOCOLS[request["protocol"]].arguments
            ):
                incomplete.append(f"{patch.node}.{patch.argument}: required input is unbound")
    if incomplete:
        return DraftInspection(status="incomplete", diagnostics=tuple(incomplete))
    try:
        document = type(draft.base_document).model_validate_json(json.dumps(payload))
    except ValidationError as error:
        return DraftInspection(status="invalid", diagnostics=(str(error),))
    return DraftInspection(status="complete", document=document)
