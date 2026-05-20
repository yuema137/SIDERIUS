# agent/schemas/cache_entry.py
"""
Pydantic data contract for the model-knowledge cache — the cumulative ledger
that replaces the legacy verbatim-copy `model_knowledge_cache` entry.

This module is the **schema footprint** for Commit 6.3 (Knowledge Accumulator
Refactor). The deterministic Merge & Prune logic lives in
``agent/cache_consolidator.py`` (Commit 6.3 / C2). LLM-driven extraction and
rendering of ``ErrorSignature`` lives in ``agent/skills/error_signature_skill.py``
(Commit 6); only the bare schema footprint is brought forward here so the
ledger contract is fully typed from day one and the Gate G3 preservation
guarantee (§2.9 Trap Test) is real on day one.

Field reconciliation between the live LLM-flat shape (8 fields emitted by
``PER_MODEL_SYSTEM_PROMPT``) and the accumulator schema is documented in the
design spec at ``docs/audit_and_optimize_token_usage_and_growth.md`` §8
Commit 6.3 Tasks.T2. The four types below implement that mapping:

  * ``ConsolidatedFinding``  — ranked observations (key_findings, bottlenecks)
                                that accumulate evidence across iters.
  * ``ConsolidatedNarrative``— single-string narratives merged by
                                replacement-with-history (latest + last-3 prior).
  * ``ErrorSignature``       — forensic primary source; load-bearing for
                                Gate G3. Never numerically capped or rank-pruned.
  * ``CacheEntry``           — top-level container for one ``model_type``.

The ``CacheEntry.from_legacy_dict`` classmethod is the zero-friction
chain-resume adapter that lifts a pre-6.3 flat-dict cache entry into the
accumulator shape (Q2(a) ruling — see commit message).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# Length / enum constants (centralised so tests and consolidator can import
# the same values rather than duplicating magic numbers).
# ---------------------------------------------------------------------------

FINDING_STATEMENT_MAX_CHARS: int = 500
NARRATIVE_LATEST_MAX_CHARS: int = 800
NARRATIVE_HISTORY_MAX_ENTRIES: int = 3
ERROR_SHORT_MESSAGE_MAX_CHARS: int = 120

# Closed enum from §2.2 (error_signature_skill contract).
FailureClass = Literal["vram", "training", "validation", "shape", "scoring", "unknown"]
FindingStrength = Literal["weak", "moderate", "strong"]


# ---------------------------------------------------------------------------
# ConsolidatedFinding
# ---------------------------------------------------------------------------


class ConsolidatedFinding(BaseModel):
    """One ranked observation accumulating evidence across iters.

    Identity is by ``statement`` semantics (text-similarity in the consolidator,
    not identity here). ``evidence_iters`` unions across iters where the same
    finding was re-surfaced; ``strength`` upgrades monotonically as evidence
    accrues.
    """

    model_config = ConfigDict(extra="forbid")

    statement: str = Field(
        ...,
        min_length=1,
        max_length=FINDING_STATEMENT_MAX_CHARS,
        description="The observation text. Non-empty; capped at "
        f"{FINDING_STATEMENT_MAX_CHARS} chars. Truncation is the "
        "consolidator's responsibility — the schema only rejects "
        "oversized input.",
    )
    evidence_iters: list[int] = Field(
        ...,
        min_length=1,
        description="Iters where this finding was surfaced. Grows by set-union "
        "during merge. Always non-empty (the iter that introduced "
        "the finding is included).",
    )
    strength: FindingStrength = Field(
        ...,
        description="Subjective strength tag from the LLM. Merge takes the "
        "max of (prior, new) under the ordering weak<moderate<strong.",
    )

    @field_validator("evidence_iters")
    @classmethod
    def _iters_non_negative(cls, v: list[int]) -> list[int]:
        if any(i < 0 for i in v):
            raise ValueError("evidence_iters entries must be >= 0")
        return v


# ---------------------------------------------------------------------------
# ConsolidatedNarrative
# ---------------------------------------------------------------------------


class ConsolidatedNarrative(BaseModel):
    """A single-string narrative field merged by replacement-with-history.

    On merge the prior ``latest`` is appended to ``history`` with its iter
    index; the new text becomes ``latest``. ``history`` is capped to the last
    ``NARRATIVE_HISTORY_MAX_ENTRIES`` entries — older prior narratives are
    archived by the consolidator and pruned from the in-memory entry.
    """

    model_config = ConfigDict(extra="forbid")

    latest: str = Field(
        ...,
        max_length=NARRATIVE_LATEST_MAX_CHARS,
        description="The current iter's narrative. Empty string is allowed "
        "(e.g. when the LLM had no signal for this field this "
        f"iter); capped at {NARRATIVE_LATEST_MAX_CHARS} chars.",
    )
    history: list[tuple[int, str]] = Field(
        default_factory=list,
        max_length=NARRATIVE_HISTORY_MAX_ENTRIES,
        description="List of (iter_index, prior_narrative) tuples in any "
        f"order. Capped to last {NARRATIVE_HISTORY_MAX_ENTRIES} "
        "entries by the consolidator; over-cap input is rejected "
        "by the schema.",
    )

    @field_validator("history")
    @classmethod
    def _history_iters_non_negative(cls, v: list[tuple[int, str]]) -> list[tuple[int, str]]:
        if any(iter_idx < 0 for iter_idx, _ in v):
            raise ValueError("history iter indices must be >= 0")
        return v


# ---------------------------------------------------------------------------
# ErrorSignature (bare footprint — Commit 6 will add extract() + render())
# ---------------------------------------------------------------------------


class ErrorSignature(BaseModel):
    """Forensic primary source for one distinct failure mode.

    The consolidator treats ``error_signatures`` as a SET keyed by
    ``(failure_class, top_user_frame, error_type)``. Duplicates merge by
    unioning ``evidence_iters``; distinct keys are NEVER dropped, regardless
    of any per-field cap. This is load-bearing for Gate G3 (§2.9 Trap Test).

    Commit 6 will add ``extract(traceback) -> ErrorSignature`` and
    ``render(sig) -> str``. Until then this is a passive container populated
    only by chains that already carry error_signatures upstream — older
    flat-dict cache entries default to an empty list via the legacy adapter.
    """

    model_config = ConfigDict(extra="forbid")

    error_type: str = Field(
        ...,
        min_length=1,
        description="The exception class name, e.g. 'torch.cuda.OutOfMemoryError'.",
    )
    short_message: str = Field(
        ...,
        max_length=ERROR_SHORT_MESSAGE_MAX_CHARS,
        description=f"Bare error message, capped at {ERROR_SHORT_MESSAGE_MAX_CHARS} chars.",
    )
    last_frames: list[str] = Field(
        default_factory=list,
        description="Last 3-5 traceback lines naming user code. Empty list "
        "is tolerated (the §2.2 skill may produce zero frames for "
        "non-Python failure modes).",
    )
    failure_class: FailureClass = Field(
        ...,
        description="Closed enum tagging the failure category. Part of the dedup key tuple.",
    )
    top_user_frame: str = Field(
        default="",
        description="The first user-code frame from last_frames (or empty if "
        "none). Part of the dedup key tuple; the consolidator "
        "derives this from last_frames when not pre-populated.",
    )
    evidence_iters: list[int] = Field(
        ...,
        min_length=1,
        description="Iters where this signature was observed. Grows by "
        "set-union during dedup merge. Never pruned.",
    )

    @field_validator("evidence_iters")
    @classmethod
    def _iters_non_negative(cls, v: list[int]) -> list[int]:
        if any(i < 0 for i in v):
            raise ValueError("evidence_iters entries must be >= 0")
        return v

    def key(self) -> tuple[str, str, str]:
        """The dedup tuple used by the consolidator's set-merge."""
        return (self.failure_class, self.top_user_frame, self.error_type)


# ---------------------------------------------------------------------------
# CacheEntry — top-level container for one model_type
# ---------------------------------------------------------------------------

# The 8 LLM-flat fields the interpretation agent emits today, in iteration
# order. Centralised so the legacy adapter and the consolidator share one
# source of truth.
_LEGACY_LIST_FIELDS: tuple[str, ...] = ("key_findings", "bottlenecks")
_LEGACY_NARRATIVE_FIELDS: tuple[str, ...] = (
    "best_config_analysis",
    "score_trend",
    "per_file_analysis",
    "data_sensitivity",
    "efficiency_assessment",
    "strategy_assessment",
)


def _truncate(text: str, limit: int) -> str:
    """Hard-truncate ``text`` to ``limit`` chars — used by the legacy adapter
    only, never by validators. Inserts no marker — the goal is silent
    forward-compat for pre-6.3 chains, not faithful round-trip."""
    if len(text) <= limit:
        return text
    return text[:limit]


class CacheEntry(BaseModel):
    """The consolidated cache entry for one ``model_type``.

    All 6 narrative fields are always present (with possibly-empty ``latest``)
    so downstream prompt assembly can render uniformly without per-field
    presence checks. ``error_signatures`` defaults to ``[]`` for entries
    seeded before the §2.2 skill lands.

    ``stats`` is a passthrough for the numerical ``_stats`` dict the interpretation
    agent already attaches today (best_score, completed_rounds, ...). It is
    intentionally untyped — the consolidator never touches it.
    """

    model_config = ConfigDict(extra="forbid")

    model_type: str = Field(
        ...,
        min_length=1,
        description="Architecture key (e.g. 'punet'). Cache is keyed by this.",
    )
    key_findings: list[ConsolidatedFinding] = Field(
        default_factory=list,
        description="Ranked observations. Pruned to <=8 by the consolidator.",
    )
    bottlenecks: list[ConsolidatedFinding] = Field(
        default_factory=list,
        description="Root-cause observations. Pruned to <=8 by the consolidator.",
    )
    best_config_analysis: ConsolidatedNarrative = Field(
        default_factory=lambda: ConsolidatedNarrative(latest=""),
        description="Narrative about the best config so far for this model_type.",
    )
    score_trend: ConsolidatedNarrative = Field(
        default_factory=lambda: ConsolidatedNarrative(latest=""),
    )
    per_file_analysis: ConsolidatedNarrative = Field(
        default_factory=lambda: ConsolidatedNarrative(latest=""),
    )
    data_sensitivity: ConsolidatedNarrative = Field(
        default_factory=lambda: ConsolidatedNarrative(latest=""),
    )
    efficiency_assessment: ConsolidatedNarrative = Field(
        default_factory=lambda: ConsolidatedNarrative(latest=""),
    )
    strategy_assessment: ConsolidatedNarrative = Field(
        default_factory=lambda: ConsolidatedNarrative(latest=""),
    )
    error_signatures: list[ErrorSignature] = Field(
        default_factory=list,
        description="Forensic primary sources. Set-merged on dedup key; NEVER "
        "numerically capped or rank-pruned (Gate G3 invariant).",
    )
    stats: dict[str, Any] = Field(
        default_factory=dict,
        description="Passthrough numerical stats (best_score, completed_rounds, "
        "etc.). The consolidator does not touch this field.",
    )

    # ------------------------------------------------------------------
    # Legacy adapter — zero-friction chain resume (Q2(a) ruling)
    # ------------------------------------------------------------------

    @classmethod
    def from_legacy_dict(
        cls,
        legacy: dict[str, Any],
        *,
        model_type: str,
        current_iter: int,
    ) -> CacheEntry:
        """Lift a pre-6.3 flat-dict cache entry into the accumulator shape.

        Pre-6.3 entries have the 8 LLM-flat fields directly (``key_findings:
        list[str]``, ``bottlenecks: list[str]``, the 6 narratives as bare
        ``str``), plus an optional ``_stats`` dict.

        The lift:
          * ``list[str]`` for findings/bottlenecks → ``list[ConsolidatedFinding]``
            with ``evidence_iters=[current_iter]`` and ``strength="moderate"``.
            (We cannot recover the original strength tag; "moderate" is the
            neutral default. Pre-6.3 chains had no accumulation, so this is
            the iter the verbatim copy was last refreshed.)
          * ``str`` for the 6 narrative fields → ``ConsolidatedNarrative(latest=str,
            history=[])``. History is empty because pre-6.3 chains overwrote
            the str on every cache hit — there is no prior version to recover.
          * ``error_signatures`` is not in the pre-6.3 shape; defaults to ``[]``.
          * ``_stats`` (legacy key) or ``stats`` (forward-compat) → ``stats``.

        Oversized findings (>500 chars) and oversized narratives (>800 chars)
        are silently truncated to fit the schema bounds — the lift's contract
        is "don't break chain resume", not "round-trip preserve".

        Empty strings in the findings/bottlenecks lists are dropped (they
        cannot become valid ``ConsolidatedFinding`` instances).
        """
        # ---- List-of-str fields → list[ConsolidatedFinding] ----
        list_payload: dict[str, list[ConsolidatedFinding]] = {}
        for field in _LEGACY_LIST_FIELDS:
            raw = legacy.get(field, []) or []
            lifted: list[ConsolidatedFinding] = []
            for item in raw:
                if not isinstance(item, str):
                    continue
                text = item.strip()
                if not text:
                    continue
                lifted.append(
                    ConsolidatedFinding(
                        statement=_truncate(text, FINDING_STATEMENT_MAX_CHARS),
                        evidence_iters=[current_iter],
                        strength="moderate",
                    )
                )
            list_payload[field] = lifted

        # ---- Str narrative fields → ConsolidatedNarrative ----
        narrative_payload: dict[str, ConsolidatedNarrative] = {}
        for field in _LEGACY_NARRATIVE_FIELDS:
            raw = legacy.get(field, "")
            text = raw if isinstance(raw, str) else ""
            narrative_payload[field] = ConsolidatedNarrative(
                latest=_truncate(text, NARRATIVE_LATEST_MAX_CHARS),
                history=[],
            )

        # ---- stats passthrough (accept both _stats and stats) ----
        stats_raw = legacy.get("_stats", legacy.get("stats", {})) or {}
        stats = stats_raw if isinstance(stats_raw, dict) else {}

        return cls(
            model_type=model_type,
            **list_payload,
            **narrative_payload,
            error_signatures=[],
            stats=stats,
        )
