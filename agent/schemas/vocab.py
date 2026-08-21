# agent/schemas/vocab.py
"""The runtime vocabulary entry — one shared home, imported by both sides.

Step 10 / P3 C1 (design §4.2). ``VocabEntry`` was declared in
``agent/schemas/proposal.py`` — the DOWNSTREAM node's schema — and imported
from there by ``agent/schemas/interpretation.py``, the UPSTREAM node's schema.
That is a backwards edge in the graph: a producer depending on its consumer's
module. It cost nothing while nothing else crossed, and it becomes a genuine
import cycle the moment ``proposal.py`` needs a type that ``interpretation.py``
declares.

The entry belongs to neither node. The interpreter MINTS vocabulary entries and
the proposer READS them, so this module is the shared home both import, and the
backwards edge is gone.

``proposal.py`` re-exports the name, so every existing
``from agent.schemas.proposal import ... VocabEntry`` importer keeps working
unchanged; the relocation is verbatim, with no field, default, description or
validator touched.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# B.6a — Unified vocabulary entry (features + concepts)
class VocabEntry(BaseModel):
    """A single vocabulary entry — feature or capability.

    Adding a new kind (e.g. 'failure_pattern') requires NO code changes —
    just add entries with the new kind value. See §2B composability principle.
    """

    name: str = Field(description="Canonical snake_case name.")
    kind: str = Field(
        description="'feature' (concrete architectural building block, e.g. "
        "'dilated_causal_conv') or 'capability' (measurable "
        "architectural property the feature provides, e.g. "
        "'receptive_field'). New kinds can be added freely."
    )
    description: str = Field(max_length=1000)
    related_to: list[str] = Field(
        default_factory=list,
        description="Names of connected VocabEntry items. "
        "Feature→concept and concept→feature links.",
    )
    tier: Literal["canonical", "candidate"] = "candidate"
    pattern: str | None = Field(
        default=None, description="AST/regex for features. None for concepts."
    )
    proposed_by_run: str | None = None
    seen_in_runs: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    origin: str | None = Field(
        default=None,
        description="Source agent for externally-contributed entries. "
        "E.g. 'ml_literature_review', 'physics_literature_review'. "
        "None = proposed during an experiment run (proposed_by_run carries the run name). "
        "When set, proposed_by_run must be None — external contributions do not "
        "count toward seen_in_runs and cannot be promoted via the run-count criterion.",
    )
