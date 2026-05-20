# agent/cache_consolidator.py
"""
LLM-powered semantic consolidator for the model-knowledge cache (Commit 6.3 /
C2, Rev 8.5).

Asymmetric design by intent — only the two *list* fields need semantic
understanding because only they accumulate ranked observations across iters
with potential paraphrases, supersession, and contradictions. Narrative
fields and error_signatures are merged by pure deterministic rules.

Three internal paths, exposed so the asymmetric semantics are individually
testable:

  * ``_merge_list_field_llm``      — LLM-powered, 4 semantic rules. Used for
                                     ``key_findings`` and ``bottlenecks``.
  * ``_merge_narrative_field``     — deterministic replacement-with-history.
                                     Used for the 6 narrative fields.
  * ``_dedupe_error_signatures``   — deterministic strict set-merge. Used for
                                     ``error_signatures``. **Gate G3 invariant
                                     — no numerical cap, no LLM merge, no
                                     pruning of any kind.**

The public entry point :func:`consolidate` orchestrates the three paths and
returns the merged :class:`CacheEntry` plus the list of archived items
(rank-pruned list findings) that the C4 dispatcher persists to
``{workspace}/iter_{i}/cache_archive_{model_type}.json``.

Cost contract (Rev 8.5 §8 T4): at most 2 LLM calls per ``consolidate()``
invocation — one for ``key_findings``, one for ``bottlenecks``. If either
list is empty on both sides, that call is skipped (the trivial case is
handled deterministically).
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from agent.llm_bridge import LLMBridge
from agent.schemas.cache_entry import (
    FINDING_STATEMENT_MAX_CHARS,
    NARRATIVE_HISTORY_MAX_ENTRIES,
    NARRATIVE_LATEST_MAX_CHARS,
    CacheEntry,
    ConsolidatedFinding,
    ConsolidatedNarrative,
    ErrorSignature,
    FindingStrength,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Hard ceiling on survivors per list field per ``model_type`` (Rev 8.5 Rule 4).
#:
#: Tunable knob — the system prompt treats this as a variable supplied by the
#: user prompt's POLICY PARAMETERS section, so changing the constant is the
#: ONLY edit needed if empirical results call for a different cap. The system
#: prompt is invariant.
LIST_FIELD_MAX_SURVIVORS: int = 8

#: Hard ceiling on the ``<short prior summary>`` gist embedded in a Rule-2
#: ``[SUPERSEDES iter-N: ...]`` prefix. Tunable knob; same rule as above.
MAX_PRIOR_SUMMARY_CHARS: int = 80

#: Field names of the two LLM-merged list fields, in stable order.
LIST_FIELD_NAMES: tuple[str, ...] = ("key_findings", "bottlenecks")

#: Field names of the six replacement-with-history narratives.
NARRATIVE_FIELD_NAMES: tuple[str, ...] = (
    "best_config_analysis",
    "score_trend",
    "per_file_analysis",
    "data_sensitivity",
    "efficiency_assessment",
    "strategy_assessment",
)

#: Strength ordering for max() resolution during merge.
_STRENGTH_RANK: dict[str, int] = {"weak": 0, "moderate": 1, "strong": 2}

#: LLM call label for telemetry (§1.5 audit / 11-key components).
_LIST_MERGE_LABEL: str = "cache_consolidator.list_merge"


# ---------------------------------------------------------------------------
# Output schema for the LLM's structured JSON response
# ---------------------------------------------------------------------------


class _MergeDecisionItem(BaseModel):
    """One item the LLM emits as a survivor or archived entry.

    Mirrors :class:`ConsolidatedFinding` exactly so the LLM output is
    drop-in-validatable. The consolidator post-processes the field
    (e.g. truncates oversized statements, enforces evidence_iters integrity)
    before promoting items into the final :class:`CacheEntry`.
    """

    model_config = ConfigDict(extra="forbid")

    statement: str = Field(..., min_length=1)
    evidence_iters: list[int] = Field(..., min_length=1)
    strength: FindingStrength = Field(...)

    @field_validator("evidence_iters")
    @classmethod
    def _non_negative(cls, v: list[int]) -> list[int]:
        if any(i < 0 for i in v):
            raise ValueError("evidence_iters entries must be >= 0")
        return sorted(set(v))


class _MergeDecision(BaseModel):
    """Structured JSON response from the LLM list-merge call.

    The LLM emits up to :data:`LIST_FIELD_MAX_SURVIVORS` survivors plus any
    number of archived items. Together they cover every input item — the
    consolidator validates this in :func:`_validate_coverage` below.
    """

    model_config = ConfigDict(extra="forbid")

    survivors: list[_MergeDecisionItem] = Field(default_factory=list)
    archived: list[_MergeDecisionItem] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _max_strength(a: FindingStrength, b: FindingStrength) -> FindingStrength:
    """Return whichever of ``a`` and ``b`` ranks higher under
    weak < moderate < strong."""
    return a if _STRENGTH_RANK[a] >= _STRENGTH_RANK[b] else b


def _rank_findings(findings: list[ConsolidatedFinding]) -> list[ConsolidatedFinding]:
    """Deterministic ranking key for the rank-prune fallback.

    Sort key: ``(strength_rank desc, len(evidence_iters) desc, recency desc)``.
    Used only when the LLM returns more than :data:`LIST_FIELD_MAX_SURVIVORS`
    survivors (the validator below trims excess) and as the deterministic
    rank-prune in the empty-new fast path.
    """
    return sorted(
        findings,
        key=lambda f: (
            -_STRENGTH_RANK[f.strength],
            -len(f.evidence_iters),
            -max(f.evidence_iters),
        ),
    )


def _truncate_statement(text: str) -> str:
    """Hard-truncate a statement to fit the schema's char cap. Silent — the
    consolidator owns truncation, the schema only rejects oversized input."""
    if len(text) <= FINDING_STATEMENT_MAX_CHARS:
        return text
    return text[:FINDING_STATEMENT_MAX_CHARS]


def _truncate_narrative(text: str) -> str:
    if len(text) <= NARRATIVE_LATEST_MAX_CHARS:
        return text
    return text[:NARRATIVE_LATEST_MAX_CHARS]


# ---------------------------------------------------------------------------
# LLM prompt construction
# ---------------------------------------------------------------------------


_LIST_MERGE_SYSTEM_PROMPT = """\
You are a semantic merge engine for an ML experimentation knowledge ledger. \
You merge a list of PRIOR observations (from earlier iterations) with a list \
of NEW observations (from the current iteration) for a single ML model under \
a single named field. You return a structured JSON decision applying the four \
merge rules below.

The user prompt provides:
  * POLICY PARAMETERS — numerical caps (e.g. MAX_SURVIVORS, \
MAX_PRIOR_SUMMARY_CHARS, MAX_STATEMENT_CHARS). All caps are referenced by name \
in the rules below; the user prompt supplies the actual values for this call.
  * POLICY EXAMPLES   — concrete worked examples illustrating each rule. \
Apply the same logic to the DATA below; do not echo the examples verbatim.
  * DATA              — the PRIOR items, NEW items, MODEL_TYPE, FIELD, \
CURRENT_ITER for this specific merge.

You do NOT invent observations. You do NOT paraphrase items that need no \
merging. You classify pairs and apply the rules below. Do not assume any \
specific number is hardcoded here — read the values from POLICY PARAMETERS.

================================================================================
THE FOUR RULES (apply in order to each pair; an item participates in at most \
one rule per merge):
================================================================================

RULE 1 — SAME-MEANING MERGE
    If a NEW item conveys the same observation as a PRIOR item (paraphrases, \
    restatements, equivalent claims with different wording), collapse them \
    into ONE survivor whose `statement` is the clearer of the two and whose \
    `evidence_iters` is the union of both. `strength` is the MAXIMUM of the \
    two under ordering weak < moderate < strong.

RULE 2 — SUPERSESSION REPLACEMENT
    If a NEW item REFINES or CORRECTS a PRIOR item (same underlying claim, \
    but the new one is more precise, more measured, or revises an estimate), \
    emit ONE survivor whose `statement` is the NEW text prefixed with \
    "[SUPERSEDES iter-N: <short prior summary>] " where:
      * N is the prior item's most recent evidence_iter.
      * <short prior summary> is a gist of the prior statement, capped at \
        MAX_PRIOR_SUMMARY_CHARS characters (defined in POLICY PARAMETERS).
    `evidence_iters` is the UNION. `strength` is the MAXIMUM.

RULE 3 — CONTRADICTION PRESERVATION
    If a NEW item DIRECTLY CONTRADICTS a PRIOR item (sign flip on a metric, \
    opposite claim about cause, "X works" vs "X does not work"), do NOT \
    collapse them. Emit TWO survivors: the PRIOR item unchanged, and the \
    NEW item with statement PREFIXED "[CONFLICT iter-N vs iter-M] " where:
      * N is CURRENT_ITER (defined in DATA).
      * M is the prior item's most recent evidence_iter.
    Both survivors keep their original evidence_iters.
    THIS RULE IS LOAD-BEARING. Never collapse a contradiction into a \
    same-meaning merge — corrupting the evolutionary ledger by erasing a \
    sign-flip is the worst possible outcome.

RULE 4 — DISTINCT (NO MATCH)
    If a NEW item has no PRIOR counterpart that triggers Rule 1, 2, or 3, \
    emit it as its own survivor with `evidence_iters` = [CURRENT_ITER]. A \
    PRIOR item that no NEW item matches is also emitted as a survivor, \
    unchanged.

RANK-PRUNE
    After applying the rules, you may have up to (|prior| + |new|) survivors. \
    Rank them by (strength_desc, len(evidence_iters)_desc, \
    most_recent_iter_desc) and emit AT MOST MAX_SURVIVORS items in \
    `survivors`. Any survivors beyond that cap go into `archived`. Both \
    lists use the same item shape.

================================================================================
OUTPUT FORMAT
================================================================================

Return ONLY a JSON object with this exact shape (no markdown fences, no \
preamble, no trailing prose):

{
  "survivors": [
    {"statement": "...", "evidence_iters": [<int>, ...], "strength": "<weak|moderate|strong>"},
    ...up to MAX_SURVIVORS items...
  ],
  "archived": [
    {"statement": "...", "evidence_iters": [<int>, ...], "strength": "<weak|moderate|strong>"},
    ...zero or more items...
  ]
}

`strength` MUST be one of "weak", "moderate", "strong".
`evidence_iters` MUST be a non-empty list of non-negative integers.
`statement` MUST be a non-empty string; keep it within MAX_STATEMENT_CHARS \
(defined in POLICY PARAMETERS).

Every PRIOR or NEW input item MUST appear (possibly merged) in either \
`survivors` or `archived`. Do not silently drop items.
"""


_LIST_MERGE_POLICY_EXAMPLES = """\
POLICY EXAMPLES (illustrative — apply the same logic to the DATA below; do \
not echo these examples verbatim):

  RULE 1 — same-meaning merge:
    PRIOR: "ridge near 50 Hz dominates" (evidence_iters=[2], strength=moderate)
    NEW  : "the 50 Hz ridge is the dominant feature" (current_iter=5)
    → ONE survivor, statement = "ridge near 50 Hz dominates" (or the \
clearer of the two), evidence_iters=[2, 5], strength=moderate.

  RULE 2 — supersession replacement:
    PRIOR: "VRAM spike around 16 GB" (evidence_iters=[2], strength=moderate)
    NEW  : "VRAM ceiling measured at 15.8 GB" (current_iter=5)
    → ONE survivor, statement = "[SUPERSEDES iter-2: VRAM spike ~16 GB] \
VRAM ceiling measured at 15.8 GB", evidence_iters=[2, 5], strength=moderate.

  RULE 3 — contradiction preservation:
    PRIOR: "loss improved by 12% with dropout=0.3" (evidence_iters=[2], strength=moderate)
    NEW  : "loss degraded by 12% with dropout=0.3" (current_iter=5)
    → TWO survivors. PRIOR unchanged. NEW statement = "[CONFLICT iter-5 vs \
iter-2] loss degraded by 12% with dropout=0.3", evidence_iters=[5], strength=moderate.

  RULE 4 — distinct (no match):
    PRIOR: "ridge near 50 Hz dominates" (evidence_iters=[2], strength=moderate)
    NEW  : "training time scales linearly with batch_size" (current_iter=5)
    → TWO survivors. PRIOR unchanged. NEW emitted as its own survivor with \
evidence_iters=[5].
"""


def _format_prior_for_prompt(findings: list[ConsolidatedFinding]) -> str:
    if not findings:
        return "(none)"
    lines = []
    for i, f in enumerate(findings, 1):
        lines.append(
            f"  P{i}. statement={json.dumps(f.statement)} "
            f"evidence_iters={f.evidence_iters} strength={f.strength!r}"
        )
    return "\n".join(lines)


def _format_new_for_prompt(statements: list[str], current_iter: int) -> str:
    if not statements:
        return "(none)"
    lines = []
    for i, s in enumerate(statements, 1):
        lines.append(f"  N{i}. statement={json.dumps(s)} current_iter={current_iter}")
    return "\n".join(lines)


def _build_list_merge_user_prompt(
    *,
    model_type: str,
    field_name: str,
    prior: list[ConsolidatedFinding],
    new_statements: list[str],
    current_iter: int,
    max_survivors: int = LIST_FIELD_MAX_SURVIVORS,
    max_prior_summary_chars: int = MAX_PRIOR_SUMMARY_CHARS,
    max_statement_chars: int = FINDING_STATEMENT_MAX_CHARS,
) -> str:
    """Compose the user prompt for one (model_type, list-field) merge call.

    Three sections, in order: POLICY PARAMETERS (numerical caps the system
    prompt's rules reference by name), POLICY EXAMPLES (illustrative worked
    cases for each rule), DATA (the actual PRIOR/NEW items). The system
    prompt is invariant across calls; this builder carries every tunable
    knob and every concrete example as user-prompt context.

    The default arg values bind the consolidator's module constants
    (:data:`LIST_FIELD_MAX_SURVIVORS`, :data:`MAX_PRIOR_SUMMARY_CHARS`,
    :data:`FINDING_STATEMENT_MAX_CHARS`). Callers can override per-field or
    per-experiment without touching the system prompt — that is the whole
    point of the hybrid separation.
    """
    policy_params = (
        "POLICY PARAMETERS (numerical caps referenced by the system-prompt rules):\n"
        f"  MAX_SURVIVORS = {max_survivors}\n"
        f"  MAX_PRIOR_SUMMARY_CHARS = {max_prior_summary_chars}\n"
        f"  MAX_STATEMENT_CHARS = {max_statement_chars}\n"
    )

    data = (
        "DATA:\n"
        f"  MODEL_TYPE: {model_type}\n"
        f"  FIELD: {field_name}\n"
        f"  CURRENT_ITER: {current_iter}\n"
        "\n"
        "  PRIOR items (already in cache, from earlier iters):\n"
        f"{_format_prior_for_prompt(prior)}\n"
        "\n"
        f"  NEW items (current iter {current_iter}):\n"
        f"{_format_new_for_prompt(new_statements, current_iter)}\n"
    )

    closing = "Apply the four rules. Return the structured JSON decision."

    return f"{policy_params}\n{_LIST_MERGE_POLICY_EXAMPLES}\n{data}\n{closing}"


# ---------------------------------------------------------------------------
# Path 1: LLM-powered list field merge
# ---------------------------------------------------------------------------


def _wrap_new_as_findings(
    new_statements: list[str], *, current_iter: int
) -> list[ConsolidatedFinding]:
    """Wrap raw LLM-emitted statement strings as fresh ConsolidatedFinding
    instances tagged with ``current_iter``. Strength defaults to ``"moderate"``
    — the LLM-flat output (`PER_MODEL_SYSTEM_PROMPT`) does not emit per-item
    strength tags; the consolidator's job is structural, not re-classification.
    Empty statements and non-strings are dropped silently.
    """
    out: list[ConsolidatedFinding] = []
    for raw in new_statements:
        if not isinstance(raw, str):
            continue
        text = raw.strip()
        if not text:
            continue
        out.append(
            ConsolidatedFinding(
                statement=_truncate_statement(text),
                evidence_iters=[current_iter],
                strength="moderate",
            )
        )
    return out


def _decision_item_to_finding(item: _MergeDecisionItem) -> ConsolidatedFinding:
    return ConsolidatedFinding(
        statement=_truncate_statement(item.statement),
        evidence_iters=sorted(set(item.evidence_iters)),
        strength=item.strength,
    )


def _merge_list_field_llm(
    bridge: LLMBridge,
    *,
    model_type: str,
    field_name: str,
    prior: list[ConsolidatedFinding],
    new_statements: list[str],
    current_iter: int,
) -> tuple[list[ConsolidatedFinding], list[dict[str, Any]]]:
    """Semantic merge of one list field (``key_findings`` or ``bottlenecks``).

    Trivial fast paths (no LLM call):
      * prior == [] and new_statements == [] → ([], [])
      * prior == [] and new_statements non-empty → wrap new as fresh findings,
        rank-prune to ``LIST_FIELD_MAX_SURVIVORS``; LLM not needed (no prior
        to merge against, no semantic decisions to make).
      * prior non-empty and new_statements == [] → return prior unchanged
        (rank-pruned if over cap); no LLM call.

    Non-trivial: both lists non-empty → one ``bridge.generate()`` call with
    the four-rule prompt, output validated through :class:`_MergeDecision`,
    survivors and archived returned as ``(List[ConsolidatedFinding], List[dict])``.

    The archived list is returned as raw dicts (model_dump of the merge-decision
    item) so the C4 dispatcher can persist them to JSON without re-serialising
    Pydantic types.
    """
    # ---- Fast paths (no LLM call) ----
    if not prior and not new_statements:
        return [], []

    if not prior:
        fresh = _wrap_new_as_findings(new_statements, current_iter=current_iter)
        if len(fresh) <= LIST_FIELD_MAX_SURVIVORS:
            return fresh, []
        ranked = _rank_findings(fresh)
        survivors = ranked[:LIST_FIELD_MAX_SURVIVORS]
        archived = [
            {
                "statement": f.statement,
                "evidence_iters": f.evidence_iters,
                "strength": f.strength,
                "reason": "rank_prune_cap_no_prior",
            }
            for f in ranked[LIST_FIELD_MAX_SURVIVORS:]
        ]
        return survivors, archived

    if not new_statements:
        if len(prior) <= LIST_FIELD_MAX_SURVIVORS:
            return list(prior), []
        ranked = _rank_findings(prior)
        survivors = ranked[:LIST_FIELD_MAX_SURVIVORS]
        archived = [
            {
                "statement": f.statement,
                "evidence_iters": f.evidence_iters,
                "strength": f.strength,
                "reason": "rank_prune_cap_no_new",
            }
            for f in ranked[LIST_FIELD_MAX_SURVIVORS:]
        ]
        return survivors, archived

    # ---- LLM-powered merge ----
    user_prompt = _build_list_merge_user_prompt(
        model_type=model_type,
        field_name=field_name,
        prior=prior,
        new_statements=new_statements,
        current_iter=current_iter,
    )
    raw_response: dict[str, Any] = bridge.generate(
        _LIST_MERGE_SYSTEM_PROMPT,
        user_prompt,
        label=_LIST_MERGE_LABEL,
    )

    try:
        decision = _MergeDecision.model_validate(raw_response)
    except ValidationError as e:
        raise RuntimeError(
            f"cache_consolidator: LLM returned malformed merge decision "
            f"for ({model_type}, {field_name}): {e}\nRaw: {raw_response!r}"
        ) from e

    # Enforce the survivor cap defensively even if the LLM exceeds it.
    survivors_list = [_decision_item_to_finding(it) for it in decision.survivors]
    archived_list = [
        {
            "statement": _truncate_statement(it.statement),
            "evidence_iters": sorted(set(it.evidence_iters)),
            "strength": it.strength,
            "reason": "llm_archive",
        }
        for it in decision.archived
    ]

    if len(survivors_list) > LIST_FIELD_MAX_SURVIVORS:
        ranked = _rank_findings(survivors_list)
        overflow = ranked[LIST_FIELD_MAX_SURVIVORS:]
        survivors_list = ranked[:LIST_FIELD_MAX_SURVIVORS]
        for f in overflow:
            archived_list.append(
                {
                    "statement": f.statement,
                    "evidence_iters": f.evidence_iters,
                    "strength": f.strength,
                    "reason": "rank_prune_cap_overflow",
                }
            )

    return survivors_list, archived_list


# ---------------------------------------------------------------------------
# Path 2: Deterministic narrative replacement-with-history
# ---------------------------------------------------------------------------


def _merge_narrative_field(
    prior: ConsolidatedNarrative,
    new_text: str,
    *,
    prior_iter: int,
) -> tuple[ConsolidatedNarrative, list[dict[str, Any]]]:
    """Replacement-with-history merge for one narrative field.

    Rules (Rev 8.2 / 8.5 — unchanged):
      * If ``new_text`` is empty AND ``prior.latest`` is empty → return prior
        unchanged, no archive.
      * If ``new_text`` equals ``prior.latest`` byte-for-byte → no-op
        (idempotent; common when the model is stable and the LLM echoed
        the same narrative).
      * Otherwise → ``latest`` becomes ``new_text`` (truncated to schema
        cap); the prior ``latest`` (when non-empty) is prepended to
        ``history`` tagged ``prior_iter``; ``history`` is trimmed to
        :data:`NARRATIVE_HISTORY_MAX_ENTRIES` (oldest dropped to archive).

    No LLM call. Returns ``(merged, archived)`` where ``archived`` is the
    list of history entries that fell off the back of the deque.
    """
    new_clean = "" if new_text is None else str(new_text)
    new_clean = _truncate_narrative(new_clean)

    if not new_clean and not prior.latest:
        return prior, []

    if new_clean == prior.latest:
        return prior, []

    # Build new history: prior's latest pushed to the front (most recent),
    # followed by prior.history (already most-recent-first).
    new_history: list[tuple[int, str]] = []
    if prior.latest:
        new_history.append((prior_iter, prior.latest))
    new_history.extend(prior.history)

    # Trim to cap; overflow goes to the archive list as plain dicts.
    archived: list[dict[str, Any]] = []
    if len(new_history) > NARRATIVE_HISTORY_MAX_ENTRIES:
        overflow = new_history[NARRATIVE_HISTORY_MAX_ENTRIES:]
        new_history = new_history[:NARRATIVE_HISTORY_MAX_ENTRIES]
        for iter_idx, text in overflow:
            archived.append(
                {
                    "iter": iter_idx,
                    "narrative": text,
                    "reason": "narrative_history_cap",
                }
            )

    merged = ConsolidatedNarrative(latest=new_clean, history=new_history)
    return merged, archived


# ---------------------------------------------------------------------------
# Path 3: Deterministic strict set-merge for error_signatures
# ---------------------------------------------------------------------------


def _dedupe_error_signatures(
    prior: list[ErrorSignature],
    new: list[ErrorSignature],
) -> list[ErrorSignature]:
    """Strict set-merge by :meth:`ErrorSignature.key` tuple.

    Gate G3 (§2.9 Trap Test) invariant — NEVER drop a distinct signature,
    NEVER apply a numerical cap, NEVER invoke an LLM. Duplicate keys union
    their ``evidence_iters`` and take the longer ``last_frames`` (more
    forensic detail wins).

    Order in the returned list is stable: prior keys first in their original
    order, then new keys that did not collide.
    """
    by_key: dict[tuple[str, str, str], ErrorSignature] = {}
    order: list[tuple[str, str, str]] = []

    for sig in list(prior) + list(new):
        k = sig.key()
        if k not in by_key:
            by_key[k] = sig
            order.append(k)
            continue
        existing = by_key[k]
        unioned_iters = sorted(set(existing.evidence_iters) | set(sig.evidence_iters))
        longer_frames = (
            existing.last_frames
            if len(existing.last_frames) >= len(sig.last_frames)
            else sig.last_frames
        )
        # short_message: keep existing (forensic primary source); LLM-extracted
        # text from later iters does not get to overwrite earlier evidence.
        by_key[k] = ErrorSignature(
            error_type=existing.error_type,
            short_message=existing.short_message,
            last_frames=longer_frames,
            failure_class=existing.failure_class,
            top_user_frame=existing.top_user_frame,
            evidence_iters=unioned_iters,
        )

    return [by_key[k] for k in order]


# ---------------------------------------------------------------------------
# Helpers for ingesting the LLM-flat new response
# ---------------------------------------------------------------------------


def _extract_new_list(new_llm_response: dict[str, Any], field_name: str) -> list[str]:
    raw = new_llm_response.get(field_name, []) or []
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        text = item.strip()
        if text:
            out.append(text)
    return out


def _extract_new_narrative(new_llm_response: dict[str, Any], field_name: str) -> str:
    raw = new_llm_response.get(field_name, "")
    if not isinstance(raw, str):
        return ""
    return raw


def _extract_new_error_signatures(new_llm_response: dict[str, Any]) -> list[ErrorSignature]:
    """Pull ``error_signatures`` out of a fresh LLM response.

    The Phase-2 §2.2 ``error_signature_skill`` will eventually plant these
    pre-validated; until then most chains carry an empty list and this
    function gracefully returns ``[]``. When a non-empty list is present,
    each item is re-validated through the schema and silently skipped if
    malformed (the consolidator is fail-open on schema errors here — the
    cache update path is not the right place to surface §2.2 bugs).
    """
    raw = new_llm_response.get("error_signatures", []) or []
    out: list[ErrorSignature] = []
    for item in raw:
        if isinstance(item, ErrorSignature):
            out.append(item)
            continue
        if not isinstance(item, dict):
            continue
        try:
            out.append(ErrorSignature.model_validate(item))
        except ValidationError:
            continue
    return out


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def consolidate(
    bridge: LLMBridge,
    *,
    prior: CacheEntry,
    new_llm_response: dict[str, Any],
    new_stats: dict[str, Any],
    current_iter: int,
    prior_iter: int,
) -> tuple[CacheEntry, list[dict[str, Any]]]:
    """Merge ``new_llm_response`` into ``prior`` and return the consolidated
    :class:`CacheEntry` plus the archive list.

    Args:
      bridge: shared :class:`LLMBridge` instance. The list-merge paths invoke
        ``bridge.generate(...)`` with label ``"cache_consolidator.list_merge"``;
        the other two paths never touch the bridge. The bridge's model_id
        determines the merge LLM (callers should configure ``gpt-4o-mini`` or
        another cheap deterministic model — see §8 Commit 6.3 Rev 8.5 spec).
      prior: the existing cache entry for this ``model_type``. For fresh
        entries (first time the model has been interpreted), pass a default
        ``CacheEntry(model_type=...)`` — the list-merge fast-paths handle the
        empty-prior case without an LLM call.
      new_llm_response: the 8-field flat dict the per-model interpretation
        LLM emits (``key_findings``, ``bottlenecks``, the 6 narratives, and
        optionally ``error_signatures``).
      new_stats: passthrough numerical dict (best_score, completed_rounds, etc.).
        Stored on the returned entry's ``stats`` field untouched.
      current_iter: the iter we are CURRENTLY writing.
      prior_iter: the iter when ``prior`` was last written (needed to tag
        the narrative history entries; the schema does not carry this on
        ``latest`` so the dispatcher must supply it).

    Returns:
      Tuple of ``(merged_entry, archived_items)`` where ``archived_items``
      is a flat list of dicts the C4 dispatcher writes to
      ``{workspace}/iter_{current_iter}/cache_archive_{model_type}.json``.
      Each archive entry carries a ``reason`` field identifying which path
      produced it (rank_prune_*, llm_archive, narrative_history_cap).

    Cost:
      At most 2 LLM calls per invocation — one per list field. Each call
      is skipped when both sides of that field are empty (fast path).
    """
    archived: list[dict[str, Any]] = []

    # ---- List fields (LLM-powered) ----
    list_outputs: dict[str, list[ConsolidatedFinding]] = {}
    for field_name in LIST_FIELD_NAMES:
        prior_list = list(getattr(prior, field_name))
        new_list = _extract_new_list(new_llm_response, field_name)
        merged, archived_items = _merge_list_field_llm(
            bridge,
            model_type=prior.model_type,
            field_name=field_name,
            prior=prior_list,
            new_statements=new_list,
            current_iter=current_iter,
        )
        list_outputs[field_name] = merged
        for it in archived_items:
            archived.append(
                {
                    "field": field_name,
                    "model_type": prior.model_type,
                    "iter": current_iter,
                    **it,
                }
            )

    # ---- Narrative fields (deterministic) ----
    narrative_outputs: dict[str, ConsolidatedNarrative] = {}
    for field_name in NARRATIVE_FIELD_NAMES:
        prior_narr = getattr(prior, field_name)
        new_text = _extract_new_narrative(new_llm_response, field_name)
        merged, archived_items = _merge_narrative_field(
            prior_narr,
            new_text,
            prior_iter=prior_iter,
        )
        narrative_outputs[field_name] = merged
        for it in archived_items:
            archived.append(
                {
                    "field": field_name,
                    "model_type": prior.model_type,
                    **it,
                }
            )

    # ---- Error signatures (deterministic, no cap) ----
    new_sigs = _extract_new_error_signatures(new_llm_response)
    merged_sigs = _dedupe_error_signatures(prior.error_signatures, new_sigs)

    merged_entry = CacheEntry(
        model_type=prior.model_type,
        **list_outputs,
        **narrative_outputs,
        error_signatures=merged_sigs,
        stats=dict(new_stats) if new_stats else {},
    )
    return merged_entry, archived
