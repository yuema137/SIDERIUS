# nodes/proposal_helpers.py
"""
Pure helper functions for ml_model_proposal_agent.

These are deterministic Python functions with no LLM calls, no I/O,
and no side effects. They prepare context for the reasoning pipeline.
"""

import os
import re
from collections.abc import Iterable
from typing import Any

from agent.schemas.proposal import (
    ModelSelectionStrategy,
    ReasoningPipelineConfig,
)
from agent.schemas.proposer_evidence import ProposerInterpretationEvidence
from execute_tools.evaluation_metric import metric_identity_unavailable_notice
from execute_tools.metric_order import MetricOrder

# Root of the SIDERIUS project
_SIDERIUS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def evidence_order(evidence: ProposerInterpretationEvidence) -> MetricOrder | None:
    """The order the interpretation evidence was actually produced under.

    Step 10 / P3 C2. This REPLACES P2a C4's ``_interpretation_order``, which
    read ``metric_identity`` out of the raw dict and carried an explicit note
    to P3: *"supply this same identity through that reader and delete this
    function — the semantics to preserve are 'read the declared identity,
    never assume a direction, and fall back to order-free `all` when it is
    absent'"*. Those semantics are preserved exactly; only the carrier changed.

    The identity has already been validated by the ONE transported-identity
    validator when the evidence was projected, so there is nothing to re-derive
    and no second place a direction could be decided.

    Returns:
        The order, or ``None`` when the run carries no usable identity — a
        NAMED absence (cold start, a scoreless input, or a pre-09a digest),
        never a default direction.
    """
    identity = evidence.metric_identity
    return MetricOrder(identity) if identity is not None else None


# ---------------------------------------------------------------------------
# B.10 — Model selection pre-filter
# ---------------------------------------------------------------------------


def select_candidate_models(
    evidence: ProposerInterpretationEvidence,
    strategy: ModelSelectionStrategy,
) -> list[dict[str, Any]]:
    """
    Pre-filter past models before the comparison stage.

    Reduces the full set of models from the interpretation to a candidate
    set based on the strategy. Controls token cost (fewer models = cheaper
    comparison call) while expert_context controls focus (what to emphasize).

    Step 10 / P3 C2: takes the TYPED proposer evidence instead of the raw
    interpretation dump. The comparison semantics below are P2a's and are
    deliberately unchanged — only the carrier moved.

    Args:
        evidence: the proposer's typed view of the interpretation.
        strategy: ModelSelectionStrategy from the pipeline config.

    Returns:
        List of per-model summary dicts, each containing model_type,
        best_score, and any available metadata (score_table, params, etc.).
        The ``score_table`` entry carries the SERIALIZED
        ``ScoreComparisonTable`` dict (``rendered_markdown`` + scalars + rows)
        — dict-shaped on purpose: ``build_candidate_markdown_block`` dispatches
        on ``isinstance(table, dict)``, so handing it the typed object would
        silently render "_Score table unavailable._" instead.
    """
    model_types = evidence.model_types
    per_raw_best = evidence.per_model_best or {}
    per_best = evidence.per_model_best_valid or {}
    per_raw_health = evidence.per_model_raw_best_health_validity or {}
    per_worst = evidence.per_model_worst or {}
    score_tables = evidence.per_model_score_tables or {}
    model_params = evidence.per_model_params or {}
    descriptions = evidence.model_descriptions or {}
    training_segs = evidence.per_model_training_segments or {}

    # Build a summary for each model
    all_models = []
    for mt in model_types:
        table = score_tables.get(mt)
        summary = {
            "model_type": mt,
            "best_score": per_best.get(mt),
            "raw_best_score": per_raw_best.get(mt),
            "raw_best_health_validity": per_raw_health.get(mt, "unknown"),
            "worst_score": per_worst.get(mt),
            "score_table": table.model_dump() if table is not None else None,
            "model_params": model_params.get(mt),
            "description": descriptions.get(mt),
            "training_segments": training_segs.get(mt),
            "source": "seed" if mt in _BUILTIN_MODELS else _guess_source(mt),
        }
        all_models.append(summary)

    # Apply strategy
    method = strategy.method
    params = strategy.params

    if method == "all":
        return all_models

    if method == "top_n":
        n = params.get("n", 10)
        scored = [m for m in all_models if m["best_score"] is not None]
        # Step 10 P2a C4 — the ONE site where a wrong direction changes what
        # the SYSTEM DOES rather than what it displays. `reverse=True` on a
        # minimised metric handed the proposer the WORST N candidates and
        # called them the best.
        order = evidence_order(evidence)
        if order is None:
            # Q-P2a-1 (operator ruling): no usable metric identity means NO
            # metric ranking happened, so this falls back to the EXISTING
            # order-free `all` semantics rather than inventing a first-N /
            # declaration-order-N policy. The result is deliberately NOT
            # described as "top N" or "best" anywhere — nothing was ranked.
            print(
                metric_identity_unavailable_notice(
                    f"the proposer's top_n({n}) candidate cut",
                    detail="returning the full candidate set unranked",
                )
            )
            return all_models
        ranked = sorted(
            scored,
            key=lambda m: order.rank([c["best_score"] for c in scored], m["best_score"]),
        )
        return ranked[:n]

    if method == "human_specified":
        specified = set(params.get("models", []))
        return [m for m in all_models if m["model_type"] in specified]

    if method == "feature_match":
        # Filter to models whose description mentions the target feature
        feature = params.get("feature", "")
        return [m for m in all_models if m.get("description") and feature in m["description"]]

    # Unknown strategy — return all with a warning
    print(f"[proposal_helpers] Unknown model selection method: {method!r}, returning all models.")
    return all_models


# Known built-in model types — used to set source="seed"
_BUILTIN_MODELS = {"punet", "wavenet", "fcnet", "transformer", "rnn", "gated_fno"}


def _guess_source(model_type: str) -> str:
    """Guess whether a model was agent-proposed based on available data.

    Step 10 / P3 C2 dropped an unused ``interpretation`` parameter in passing:
    the body never read it, and keeping it would have forced the typed
    migration to thread evidence into a function that does not consume it.
    """
    # Simple heuristic: if it's not a built-in, it's agent-proposed
    return "proposed"


# ---------------------------------------------------------------------------
# B.16a — Exploration mode resolver
# ---------------------------------------------------------------------------


def load_model_source(model_type: str) -> str | None:
    """
    Load the source code for a model.

    Searches:
      1. Built-in models: extracts the relevant class(es) from
         ``ml_models/models_sandbox.py`` by finding the class name
         associated with the model_type in MODEL_REGISTRY-style patterns.
      2. Agent-generated plugins: reads from
         ``agent_generated/models/{model_type}/{model_type}.py``
         or ``agent_generated/models/{model_type}.py``.

    Returns the source code as a string, or None if not found.
    """
    # Try agent-generated plugin first (more specific)
    plugin_candidates = [
        os.path.join(_SIDERIUS_ROOT, "agent_generated", "models", model_type, f"{model_type}.py"),
        os.path.join(_SIDERIUS_ROOT, "agent_generated", "models", f"{model_type}.py"),
    ]
    for path in plugin_candidates:
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                return f.read()

    # Try built-in models — extract from models_sandbox.py
    sandbox_path = os.path.join(_SIDERIUS_ROOT, "ml_models", "models_sandbox.py")
    if not os.path.isfile(sandbox_path):
        return None

    # Map model_type to class names
    _MODEL_CLASS_MAP = {
        "punet": ["PositionalUNet", "DoubleConv", "Down", "Up", "OutConv", "PositionalEncoding"],
        "fcnet": ["AE"],
        "transformer": ["TransformerModel"],
        "wavenet": ["CausalConv1d", "WaveNetBlock", "SimpleWaveNet"],
        "rnn": ["Seq2SeqEncoder", "Seq2SeqDecoder", "RNNSeq2Seq"],
        "gated_fno": ["FullSpectrumGatedConv1d", "GatedFNO"],
    }

    class_names = _MODEL_CLASS_MAP.get(model_type)
    if not class_names:
        return None

    with open(sandbox_path, encoding="utf-8") as f:
        full_source = f.read()

    # Extract each class definition (from 'class Name' to the next top-level class or EOF)
    extracted = []
    lines = full_source.split("\n")
    for target_class in class_names:
        in_class = False
        class_lines = []
        for line in lines:
            if re.match(rf"^class {target_class}\b", line):
                in_class = True
                class_lines = [line]
            elif in_class:
                # End of class: next top-level class or top-level non-indented code
                if re.match(r"^class \w", line) or (
                    re.match(r"^[A-Z_]", line) and not line.startswith(" ")
                ):
                    in_class = False
                else:
                    class_lines.append(line)
        if class_lines:
            extracted.append("\n".join(class_lines))

    return "\n\n".join(extracted) if extracted else None


def enrich_candidates_with_source(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Add source code to each candidate model summary.

    Loads the model's source code (from built-in or agent-generated) and
    adds it as a ``source_code`` field. Models without available source
    get ``source_code: None``.
    """
    for candidate in candidates:
        mt = candidate.get("model_type")
        if mt:
            source = load_model_source(mt)
            candidate["source_code"] = source
            if source:
                candidate["source_code_lines"] = len(source.split("\n"))
    return candidates


# ---------------------------------------------------------------------------
# Phase 5 C — stage user-prompt rendering helpers
#
# These lift the heavy, read-intensive content (score_table markdown + source
# code) out of the JSON-escaped candidate dicts into a top-level markdown
# block the LLM reads natively. Scalar metadata stays in the JSON region.
# See docs/aggregated_score_table_awareness.md §"Sub-commit C detailed plan".
# ---------------------------------------------------------------------------


def build_score_summary_line(score_table: dict[str, Any] | None) -> str | None:
    """One-liner summary for a non-candidate model's score table.

    Reads ``aggregate.{model_scalar, raw_baseline_scalar, percent_of_ceiling_log,
    num_sampled_files}`` from a serialized ``ScoreComparisonTable`` dict and
    returns one of:

    * ``"log_scalar=X.XX, recovery=YY% on N files"`` — normal case.
    * ``"log_scalar=X.XX, below raw baseline on N files"`` — when
      ``model_scalar < raw_baseline_scalar``. Mirrors the below-baseline
      guard in ``execute_tools.scoring_helpers.render_comparison_table`` so
      we never emit a misleading sign-flipped percentage here.

    Returns ``None`` when ``score_table`` is ``None`` or lacks an
    ``aggregate`` sub-dict — caller decides whether to omit the field.
    """
    if not isinstance(score_table, dict):
        return None
    agg = score_table.get("aggregate")
    if not isinstance(agg, dict):
        return None

    model_scalar = agg.get("model_scalar")
    raw_baseline = agg.get("raw_baseline_scalar")
    recovery = agg.get("percent_of_ceiling_log")
    n_files = agg.get("num_sampled_files")
    if model_scalar is None or n_files is None:
        return None

    if raw_baseline is not None and model_scalar < raw_baseline:
        return f"log_scalar={model_scalar:.2f}, below raw baseline on {n_files} files"

    if recovery is None:
        return f"log_scalar={model_scalar:.2f} on {n_files} files"

    return f"log_scalar={model_scalar:.2f}, recovery={recovery * 100:.1f}% on {n_files} files"


def build_candidate_markdown_block(candidates: list[dict[str, Any]]) -> str:
    """Top-level markdown block rendering each candidate's full detail.

    For each candidate dict, emits a section:

    ```
    ### Candidate: <model_type>

    <score_table.rendered_markdown>

    #### Source Code
    ```python
    <source_code>
    ```

    ---
    ```

    Falls back to ``_Score table unavailable._`` / ``_Source code
    unavailable._`` when the corresponding field is missing. Returns an
    empty string when ``candidates`` is empty — callers typically omit
    the whole block (heading + separator) on an empty return.
    """
    if not candidates:
        return ""

    sections: list[str] = ["## Candidate Models — detailed view", ""]
    for candidate in candidates:
        mt = candidate.get("model_type", "<unknown>")
        sections.append(f"### Candidate: {mt}")
        sections.append("")

        table = candidate.get("score_table")
        rendered = table.get("rendered_markdown") if isinstance(table, dict) else None
        if rendered:
            sections.append(rendered)
        else:
            sections.append("_Score table unavailable._")
        sections.append("")

        source = candidate.get("source_code")
        sections.append("#### Source Code")
        if source:
            sections.append("```python")
            sections.append(source)
            sections.append("```")
        else:
            sections.append("_Source code unavailable._")
        sections.append("")
        sections.append("---")
        sections.append("")

    return "\n".join(sections).rstrip() + "\n"


def strip_heavy_fields_for_json(
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Shallow copy per candidate with heavy fields removed for JSON dump.

    Removes ``score_table``, ``source_code``, and ``source_code_lines`` —
    the fields that live in the top-level markdown block after
    ``build_candidate_markdown_block``. Preserves every other field so
    stage prompts that enumerate candidate scalars (``best_score``,
    ``model_params``, ``description``, ``source``, ...) keep working.

    Input list is not mutated.
    """
    _HEAVY_FIELDS = ("score_table", "source_code", "source_code_lines")
    return [
        {k: v for k, v in candidate.items() if k not in _HEAVY_FIELDS} for candidate in candidates
    ]


def resolve_exploration_mode(
    evidence: ProposerInterpretationEvidence,
    pipeline: ReasoningPipelineConfig,
) -> str:
    """
    Decide whether to use explore or exploit mode.

    In 'auto' mode, checks two signals in priority order:

    1. Vocabulary stagnation (centrifugal): if the fraction of candidate
       feature/capability entries in the runtime vocab has dropped below
       policy.vocab_stagnation_threshold, force explore mode to prevent
       the system from only reusing canonical terms.

    2. Evidence depth: fewer than 5 agent-proposed models → explore to
       build up experimental evidence before switching to exploitation.

    Step 10 / P3 C2: takes the TYPED proposer evidence. Both signals below
    are direction-free and unchanged — only the carrier moved.

    Args:
        evidence: the proposer's typed view of the interpretation.
        pipeline: The reasoning pipeline config (carries exploration_mode and policy).

    Returns:
        "explore" or "exploit".
    """
    if pipeline.exploration_mode != "auto":
        return pipeline.exploration_mode

    # Signal 1: vocabulary stagnation
    vocab_diversity_ratio = evidence.vocab_diversity_ratio
    if (
        vocab_diversity_ratio is not None
        and vocab_diversity_ratio < pipeline.policy.vocab_stagnation_threshold
    ):
        return "explore"

    # Signal 2: evidence depth
    agent_proposed = [mt for mt in evidence.model_types if mt not in _BUILTIN_MODELS]

    if len(agent_proposed) < 5:
        return "explore"

    return "exploit"


# ---------------------------------------------------------------------------
# C6.2 — Proposer stage-output management (Rev 8.6)
#
# Three pure helpers + one private iter-parser used by the proposer agent
# (C6.2-C3) to clamp DiscoveryMemo.comparative_analysis to the top-K most
# load-bearing entries and to backstop any unexpectedly large string values
# inside non-input stage outputs before they reach _render_stage_user_prompt.
#
# All four functions are non-mutating and pure. See docs/audit_and_optimize_
# token_usage_and_growth.md §8 Commit 6.2-C2 for the algorithmic rationale.
# ---------------------------------------------------------------------------

_PROPOSED_ITER_PATTERN = re.compile(r"^proposed_iter_(\d+)$")


def _iter_index_from_source(source: Any) -> int:
    r"""Parse the iteration index from a ``ModelComparison.source`` string.

    The schema description (``agent/schemas/proposal.py:200-202``) declares
    source values as ``"seed"`` or ``"proposed_iter_N"``. This parser is the
    canonical mapping used by ``clamp_comparative_analysis`` to derive a
    recency signal from the LLM-populated entries.

    Mapping:
      - ``"seed"`` -> ``0`` (oldest, pre-iteration provenance).
      - ``"proposed_iter_N"`` -> ``N`` (matched by ``^proposed_iter_(\d+)$``).
      - anything else (malformed, missing, wrong type) -> ``-1`` so the
        entry falls last on a descending sort and is most likely to be
        clamped out when the pool is over-capacity.
    """
    if not isinstance(source, str):
        return -1
    if source == "seed":
        return 0
    match = _PROPOSED_ITER_PATTERN.match(source)
    if match is None:
        return -1
    return int(match.group(1))


def _ranks_by_order(
    indexed: list[tuple],
    order: MetricOrder | None,
) -> dict[int, int] | None:
    """1-based rank of each entry's ``best_score`` under ``order`` — 1 is BEST.

    Returns ``None`` when there is no order, which is the caller's signal that
    no metric ranking may happen at all (Q-P2a-1). Returning ``None`` rather
    than an empty mapping keeps "we did not rank" distinguishable from "we
    ranked and everything tied".

    A missing or non-numeric ``best_score`` takes ``order.worst_sentinel``, so
    "missing sorts as worst" stays true under BOTH directions. The pre-P3 code
    hardcoded ``-inf`` for that, which is "worst" only under ``higher``; under
    ``lower`` it is the BEST possible value, and a missing score would have been
    promoted ahead of every real measurement.

    Ranks are computed ONCE here rather than inside a sort key. Two reasons:
    the same mapping serves Draw A and the final truncation, so they cannot
    disagree; and ``MetricOrder.rank`` is O(n) per call, which inside a
    comparator made the clamp O(n^2 log n) in the size of the comparison pool.
    """
    if order is None:
        return None

    def _score(item: tuple) -> float:
        score = item[1].get("best_score")
        return score if isinstance(score, int | float) else order.worst_sentinel

    scores = [_score(it) for it in indexed]
    return {it[0]: order.rank(scores, _score(it)) for it in indexed}


def clamp_comparative_analysis(
    comparative_analysis: list[dict[str, Any]],
    top_k: int = 5,
    *,
    order: MetricOrder | None,
) -> list[dict[str, Any]]:
    """Clamp the comparative_analysis list with a 3-best + 2-recent hybrid.

    The audited growth driver in proposer prompts is the unbounded length
    of ``DiscoveryMemo.comparative_analysis``. Per-entry caps already exist
    on ``ModelComparison`` (key_mechanism / lesson_for_next_proposal ≤ 1000
    chars each); the list itself was unbounded until this commit.

    Algorithm (Rev 8.6 Point 3 ruling):
      - **Draw A**: the 3 BEST entries under ``order``.
      - **Draw B**: top 2 most-recent (by ``_iter_index_from_source(source)``
        descending) from the *remainder* (entries not in Draw A).
      - **Union**: deduplicate by ``model_type`` — first-seen wins, so
        Draw-A winners take precedence over recency on collision.
      - **Backfill**: if ``len(union) < top_k``, pull more entries from
        the still-remaining pool sorted by recency descending until length
        reaches ``top_k`` (or the pool is exhausted).
      - **Truncate**: if ``len(union) > top_k`` (possible when ``top_k < 5``),
        keep Draw-A winners first, then most-recent, until length equals
        ``top_k``.

    **Direction (F-P3-1, Step 10 / P3 C2 — Q-P3-4 = INCLUDE / BOUNDED).**
    Draw A used to be ``sorted(key=lambda it: (-_score(it), it[0]))``: raw
    ``best_score`` DESCENDING, with a missing score sorting as ``-inf``. Both
    halves silently assume higher-is-better, and the values are the run's
    PRIMARY scores copied out of ``ModelComparison.best_score``. Under a
    ``lower`` metric the draw therefore curated the three WORST models'
    comparison entries into every later-stage prompt.

    The fix consults the SAME ``MetricOrder`` authority every other primary-score
    decision uses. No new comparator, no new direction derivation, no new
    ordering semantics — the preference decision already existed here; only its
    direction handling was wrong. Under ``higher`` the resulting order is
    identical to the old ``-score`` sort (both are best-first with ties broken
    by original index), which is what keeps TIDMAD and Pets byte-stable.

    This site is invisible to the P2a AST scanner by construction — the golden
    name is read inside ``_score`` and the sort key's own text carries no
    golden token — and that scanner is deliberately NOT widened to catch it
    (its one-hop precision contract was measured at 22 false positives against
    12 real sites). The standing guard here is behavioural: the hand-computed
    retention fixtures in the C2 test module.

    Parameters
    ----------
    comparative_analysis
        The list value of ``DiscoveryMemo.comparative_analysis`` — a list
        of dicts with at least ``model_type``, ``source``, and ``best_score``
        keys. Missing keys are tolerated by the sort fallbacks (a missing
        ``best_score`` is treated as ``order.worst_sentinel``, so "missing
        sorts as worst" stays true under BOTH directions).
    top_k
        Maximum number of entries to retain. Independent knob, no relation
        to the fixed 3+2 draw constants — those are the initial allocation;
        ``top_k`` is the final cap and backfill target.
    order
        The run's declared metric order, or ``None`` when the run carries no
        usable metric identity. Keyword-only and REQUIRED with no default:
        every caller must state which it has, because a silently-defaulted
        ``None`` would quietly drop the score draw. ``None`` takes the
        Q-P2a-1 shape — the score-based draw is SKIPPED entirely and retention
        falls back to the existing direction-independent recency behaviour,
        claiming nothing about which entries are "best", because without an
        identity nothing was ranked.

    Returns
    -------
    A new list of at most ``top_k`` entries. The input list is not mutated;
    inner dicts are shared by reference (not deep-copied — entries are
    treated as read-only payload).
    """
    n = len(comparative_analysis)
    if n <= top_k:
        return list(comparative_analysis)

    indexed = list(enumerate(comparative_analysis))

    def _recency(item: tuple) -> int:
        return _iter_index_from_source(item[1].get("source"))

    # ``None`` when the run declares no usable identity: no metric ranking
    # happened, so Draw A is SKIPPED rather than reordered. Inventing a
    # direction here is precisely what the Q-10-2 named absence forbids.
    ranks = _ranks_by_order(indexed, order)

    if ranks is None:
        draw_a: list[tuple] = []
    else:
        draw_a = sorted(indexed, key=lambda it: (ranks[it[0]], it[0]))[:3]

    draw_a_indices = {it[0] for it in draw_a}

    remainder_after_a = [it for it in indexed if it[0] not in draw_a_indices]
    by_recency_b = sorted(remainder_after_a, key=lambda it: (-_recency(it), it[0]))
    draw_b = by_recency_b[:2]
    draw_b_indices = {it[0] for it in draw_b}

    union: list[tuple] = []
    seen_model_types: set = set()
    for it in draw_a + draw_b:
        mt = it[1].get("model_type")
        if mt is not None and mt in seen_model_types:
            continue
        union.append(it)
        if mt is not None:
            seen_model_types.add(mt)

    if len(union) < top_k:
        already_indices = draw_a_indices | draw_b_indices
        remaining_pool = [it for it in indexed if it[0] not in already_indices]
        by_recency_rest = sorted(remaining_pool, key=lambda it: (-_recency(it), it[0]))
        for it in by_recency_rest:
            if len(union) >= top_k:
                break
            mt = it[1].get("model_type")
            if mt is not None and mt in seen_model_types:
                continue
            union.append(it)
            if mt is not None:
                seen_model_types.add(mt)

    if len(union) > top_k:
        # Same order authority as Draw A, for the same reason. Without an
        # identity the truncation is recency-only — the direction-independent
        # half of the existing behaviour, kept intact.
        if ranks is None:
            union.sort(key=lambda it: (-_recency(it), it[0]))
        else:
            union.sort(key=lambda it: (ranks[it[0]], -_recency(it), it[0]))
        union = union[:top_k]

    return [it[1] for it in union]


_ELISION_MARKER_TEMPLATE = "\n[... {n} chars elided ...]\n"
_ELISION_MARKER_FINGERPRINT = " chars elided ...]"
_MIN_MAX_CHARS = 40


def safe_stage_string_truncator(text: str, max_chars: int = 4000) -> str:
    """Middle-truncate a string with a high-signal head + tail + marker.

    Used as the leaf operation of :func:`apply_string_backstop`. Kept as a
    pure string -> string function so the truncation rule can be unit-tested
    in isolation from the recursive walker.

    Parameters
    ----------
    text
        The raw string value. Returned verbatim if already under cap or if
        the elision marker fingerprint is already present (idempotence).
    max_chars
        Maximum allowed length. Must be ``>= 40`` — the marker template
        consumes ~32 chars on its own, leaving < 8 chars of head + tail for
        anything smaller, which would be useless.

    Returns
    -------
    Either ``text`` unchanged, or a new string of the form
    ``first_half + marker + last_half`` with total length ``<= max_chars``.

    Raises
    ------
    ValueError
        If ``max_chars < 40``. Defensive floor — this indicates a
        configuration error in the caller (likely a misset
        ``ResearchPolicy.prior_stage_max_chars``).
    """
    if max_chars < _MIN_MAX_CHARS:
        raise ValueError(
            f"safe_stage_string_truncator: max_chars={max_chars} below "
            f"defensive floor of {_MIN_MAX_CHARS}. The elision marker "
            f"alone consumes ~32 chars; anything smaller leaves no useful "
            f"head/tail. Check ResearchPolicy.prior_stage_max_chars."
        )

    if len(text) <= max_chars:
        return text

    if _ELISION_MARKER_FINGERPRINT in text:
        return text

    elided_chars = len(text) - max_chars
    marker = _ELISION_MARKER_TEMPLATE.format(n=elided_chars)
    overhead = len(marker)
    while overhead >= max_chars:
        elided_chars += 1
        marker = _ELISION_MARKER_TEMPLATE.format(n=elided_chars)
        overhead = len(marker)
        if elided_chars > len(text):
            return text

    remaining = max_chars - overhead
    head_len = remaining // 2
    tail_len = remaining - head_len
    head = text[:head_len]
    tail = text[len(text) - tail_len :] if tail_len > 0 else ""

    while True:
        candidate = head + marker + tail
        new_elided = len(text) - len(head) - len(tail)
        if new_elided == elided_chars:
            return candidate
        elided_chars = new_elided
        marker = _ELISION_MARKER_TEMPLATE.format(n=elided_chars)
        overhead = len(marker)
        remaining = max_chars - overhead
        if remaining < 0:
            return text
        head_len = remaining // 2
        tail_len = remaining - head_len
        head = text[:head_len]
        tail = text[len(text) - tail_len :] if tail_len > 0 else ""


def apply_string_backstop(stage_output: Any, max_chars: int = 4000) -> Any:
    """Recursively middle-truncate every string leaf exceeding ``max_chars``.

    Walks ``stage_output`` and rebuilds the structure with the same shape,
    replacing any string value longer than ``max_chars`` with the output of
    :func:`safe_stage_string_truncator`. Non-string scalars and short
    strings pass through verbatim. Containers are recreated (deep-copy
    semantics for the structure, shallow on string contents which are
    immutable anyway).

    Parameters
    ----------
    stage_output
        Any JSON-compatible nested structure. Dicts have keys preserved
        and values recursed into; lists have order preserved and elements
        recursed into; everything else passes through.
    max_chars
        Threshold forwarded to :func:`safe_stage_string_truncator`. Same
        ``>= 40`` requirement applies; passing a smaller value will raise
        as soon as the walker encounters a string long enough to trigger
        truncation. Validation is deferred to the leaf call so empty /
        all-short structures don't fail under an invalid cap.

    Returns
    -------
    A new structure with the same shape as ``stage_output`` and only
    string leaves potentially shortened. The input is not mutated.
    """
    if isinstance(stage_output, dict):
        return {key: apply_string_backstop(value, max_chars) for key, value in stage_output.items()}
    if isinstance(stage_output, list):
        return [apply_string_backstop(item, max_chars) for item in stage_output]
    if isinstance(stage_output, tuple):
        return tuple(apply_string_backstop(item, max_chars) for item in stage_output)
    if isinstance(stage_output, str):
        return safe_stage_string_truncator(stage_output, max_chars)
    return stage_output


# C6.2-C3: Orchestration helper — glue layer for proposer prompt assembly.
# The 3-best + 2-recent hybrid logic lives in `clamp_comparative_analysis`
# above; the middle-truncation logic lives in `apply_string_backstop`.
# This helper just composes them into the read-only `clamped_accumulated`
# view consumed by `_render_stage_user_prompt` and `_audit_proposer_components`
# in `nodes/ml_model_proposal_agent.py`.


def clamp_and_backstop_accumulated(
    accumulated: dict[str, Any],
    *,
    top_k: int,
    max_chars: int,
    input_keys: Iterable[str],
    order: MetricOrder | None,
) -> dict[str, Any]:
    """Build a clamped + backstopped copy of ``accumulated`` for prompt assembly.

    Pure orchestration. The actual algorithms live in the C2 helpers
    :func:`clamp_comparative_analysis` (3-best + 2-recent hybrid) and
    :func:`apply_string_backstop` (recursive middle truncation). This
    function composes them into a single non-mutating call suitable for
    use immediately before :func:`_render_stage_user_prompt` and
    :func:`_audit_proposer_components` in the proposer agent.

    Behaviour:

    1. Keys in ``input_keys`` (proposer-input fields like ``candidates``,
       ``interpretation_summary``, ``existing_model_types``,
       ``non_candidates_overview``, ``previous_failures``) pass through
       **verbatim** — same object reference, no recursion, no copy.
       The clamping contract is per-iter; input-side context is the
       caller's responsibility to size.
    2. If ``accumulated`` contains a ``"comparison"`` key whose value is
       a dict containing a list-valued ``"comparative_analysis"`` field,
       that list is passed through :func:`clamp_comparative_analysis`
       with the supplied ``top_k``. A *new* comparison dict is built with
       the clamped list substituted in. The original
       ``accumulated["comparison"]`` is never mutated.
    3. Every non-input key (after the comparison clamp above) is passed
       through :func:`apply_string_backstop` with ``max_chars`` to
       middle-truncate any string leaf above the threshold.

    The function returns a new outer dict. Original input is bit-for-bit
    unchanged (verified by C2's ``test_input_not_mutated`` for the inner
    helpers; this layer only adds shallow-copy + new-comparison-dict
    construction).

    Parameters
    ----------
    accumulated
        The proposer's per-iter context dict. Mixes input-side keys
        (carried in from ``ProposalInput``) with stage-output keys
        (``comparison``, ``causal_reasoning``, ``proposing_stage_errors``,
        etc.) accumulated as enabled stages run.
    top_k
        Forwarded to :func:`clamp_comparative_analysis`. Typically
        ``policy.comparative_analysis_top_k`` (default 5).
    max_chars
        Forwarded to :func:`apply_string_backstop`. Typically
        ``policy.prior_stage_max_chars`` (default 4000). Must be
        ``>= 40``; violations raise from the leaf truncator (see
        :func:`safe_stage_string_truncator`).
    order
        The run's declared metric order, or ``None`` for a run with no usable
        metric identity. Forwarded verbatim to
        :func:`clamp_comparative_analysis` (F-P3-1, Step 10 / P3 C2).
        Keyword-only and REQUIRED with no default, so a caller cannot silently
        drop the score draw by forgetting it.
    input_keys
        Iterable of key names that should bypass both clamp and backstop
        (input-side context that this layer is not responsible for).
        Typically ``_PROPOSER_INPUT_KEYS`` from
        ``nodes.ml_model_proposal_agent``.

    Returns
    -------
    A new outer dict with the same keys as ``accumulated``. Input-side
    values pass through by reference. Stage-output values are either
    backstopped (string leaves shrunk) or, for ``comparison``,
    clamped-then-backstopped.
    """
    input_keys_set = set(input_keys)
    result: dict[str, Any] = {}

    for key, value in accumulated.items():
        if key in input_keys_set:
            result[key] = value
            continue

        if key == "comparison" and isinstance(value, dict):
            new_comparison: dict[str, Any] = dict(value)
            inner_list = new_comparison.get("comparative_analysis")
            if isinstance(inner_list, list):
                new_comparison["comparative_analysis"] = clamp_comparative_analysis(
                    inner_list,
                    top_k=top_k,
                    order=order,
                )
            result[key] = apply_string_backstop(new_comparison, max_chars=max_chars)
            continue

        result[key] = apply_string_backstop(value, max_chars=max_chars)

    return result
