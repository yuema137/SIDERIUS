"""Pydantic-only judge references a workflow declaration may name.

Workflow declaration validation imports this module and nothing else from
``agent`` (the import guard in ``tests/unit/workflows/test_workflow_definition.py``
allowlists exactly this module): it depends on pydantic only. ``judge_task``
re-exports every name, so the rubric bytes and digests it owns are unchanged.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Identifier = Annotated[str, StringConstraints(pattern=r"^[a-zA-Z][a-zA-Z0-9_-]*$", max_length=100)]
Version = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$", max_length=40)]

#: Debate rounds a ``debate-judge/v1`` declaration may request (declaration and
#: debate call schemas share it).
MAX_DEBATE_ROUNDS = 4


class StrictJudgeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, allow_inf_nan=False)


class RubricRef(StrictJudgeModel):
    """Exact reference to a rubric: identity plus the content digest it was declared with."""

    id: Identifier
    version: Version
    sha256: Digest
