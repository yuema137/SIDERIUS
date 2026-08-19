# nodes/interpretation_helpers.py
"""
Pure helper functions for result_interpretation_agent — Phase C vocabulary feedback.

These are deterministic Python functions with no LLM calls.
They evaluate predictions, generate discoveries, and build the runtime vocabulary.
"""

import re
from collections.abc import Sequence
from typing import Any

from agent.schemas.interpretation import OUTCOME_UNEVALUATED
from agent.schemas.proposal import VocabEntry
from execute_tools.metric_order import MetricOrder

#: The relative band inside which a score counts as "within 5% of SOTA".
#: FROZEN at 0.05 (Step 09a Q-09a-5): C3 corrects the band's DIRECTION and its
#: negative-reference arithmetic, and must NOT retune its width.
_DISCOVERY_RELATIVE_BAND = 0.05

# ---------------------------------------------------------------------------
# Candidate semantic deduplication (heuristic, zero LLM cost)
# ---------------------------------------------------------------------------
#
# v15 retrospective surfaced a structural failure: every candidate had
# ``len(seen_in_runs) == 1`` for the entire 20-iter run because the proposer
# invented a fresh hyper-specific compound name each iter even when proposing
# the same mechanism (7 distinct names for "weight each sample by something",
# 22 EMD-family names, etc.). With no candidate ever reaching seen_in_runs >=
# 3, ``promote_candidates`` never fired and the vocab became a passive log.
#
# This dedup heuristic runs INSIDE ``build_runtime_vocab`` BEFORE a new
# candidate is added to the vocab. If the new candidate is semantically
# similar to an existing candidate of the same kind, the new candidate's
# ``seen_in_runs`` is merged into the existing entry instead — accelerating
# the path to the promotion threshold. The existing entry's ``aliases``
# field records the new name for traceability.
#
# Two cheap predicates are OR'd:
#
#   1. **Substring match on names** (with a length floor of 5 to avoid
#      trivial 2-3 char matches). Catches ``emd_loss`` vs ``emd_bin_loss``,
#      ``selective_ssm`` vs ``selective_ssm_block``, etc.
#   2. **Content-word overlap on descriptions** (at least 3 shared
#      non-stopword tokens). Catches paraphrased descriptions of the same
#      mechanism that don't share a substring in their names.
#
# Both are deliberately permissive — the cost of a false-merge (two genuinely
# distinct concepts collapse into one entry) is bounded: the merged entry
# stays accurate to the original mechanism description; only the new variant
# name is lost to an alias. The cost of a false-non-merge (the v15 status
# quo) is permanent inability to ever promote either entry. We optimise for
# the former.

_STOPWORDS: frozenset[str] = frozenset(
    {
        # Articles, prepositions, conjunctions, common verbs/copulas
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "from",
        "are",
        "was",
        "were",
        "has",
        "have",
        "had",
        "but",
        "not",
        "all",
        "any",
        "can",
        "may",
        "such",
        "via",
        "into",
        "out",
        "over",
        "under",
        "between",
        "across",
        "each",
        "per",
        "also",
        "than",
        "then",
        "when",
        "where",
        "while",
        "which",
        "would",
        "could",
        "should",
        "more",
        "less",
        "most",
        "least",
        "use",
        "uses",
        "used",
        "using",
        "based",
        "make",
        "made",
        "give",
        "gives",
        "given",
        # ML-generic words that don't discriminate between mechanisms.
        "loss",
        "model",
        "layer",
        "network",
        "output",
        "input",
        "data",
        "value",
        "values",
        "score",
        "scores",
        "type",
        "types",
        "feature",
        "function",
        "method",
        "approach",
        "result",
        "results",
    }
)


def _content_words(text: str) -> set[str]:
    """Lowercase content words from a description, excluding stopwords and
    short tokens.

    Used by ``_find_duplicate_candidate`` to compute the description-overlap
    predicate. Tokenises on non-alphabetic characters so snake_case and
    hyphenated tokens both split cleanly. Tokens shorter than 4 characters
    are dropped along with the ``_STOPWORDS`` set — both filters keep the
    overlap signal grounded in mechanism-bearing words (``ordinal``,
    ``wasserstein``, ``curriculum``) and away from generic plumbing.
    """
    tokens = re.findall(r"[a-z]+", text.lower())
    return {t for t in tokens if len(t) >= 4 and t not in _STOPWORDS}


def _find_duplicate_candidate(
    new_name: str,
    new_kind: str,
    new_description: str,
    existing_vocab: dict[str, VocabEntry],
    *,
    min_shared_words: int = 3,
    name_substring_min_len: int = 5,
) -> VocabEntry | None:
    """Return an existing **candidate** entry of the same kind that the
    new candidate likely duplicates, or ``None`` if genuinely novel.

    Two-pass heuristic, no LLM:

      1. **Name substring match** (with length floor). If either lowercased
         name contains the other as a substring and both have length >=
         ``name_substring_min_len``, treat as duplicate.
      2. **Description content-word overlap.** If the two descriptions
         share at least ``min_shared_words`` non-stopword content tokens,
         treat as duplicate.

    The caller is responsible for merging ``seen_in_runs`` and ``aliases``
    into the returned entry.

    Args:
        new_name: Name of the incoming candidate.
        new_kind: Kind of the incoming candidate (``"feature"`` or
            ``"capability"``). Discoveries are never deduplicated; the
            caller should not invoke this function for them.
        new_description: Description of the incoming candidate.
        existing_vocab: Current vocab keyed by name.
        min_shared_words: Threshold for the description-overlap predicate.
        name_substring_min_len: Minimum length both names must have for the
            substring predicate to fire. Avoids spurious matches on tiny
            tokens.

    Returns:
        The existing candidate entry to merge into, or ``None`` if no
        duplicate is found. Only entries with ``tier == "candidate"`` and
        ``kind == new_kind`` are considered — canonical entries are out of
        scope (a candidate that overlaps a canonical should still be
        considered new; it can be merged at promotion time by the existing
        ``_dedup_promoted`` path).
    """
    new_name_lower = new_name.lower()
    new_words = _content_words(new_description)

    for entry in existing_vocab.values():
        if entry.tier != "candidate":
            continue
        if entry.kind != new_kind:
            continue
        if entry.name == new_name:
            # Exact-name match is the caller's job — this function only
            # finds NEAR-duplicates.
            continue
        ex_name_lower = entry.name.lower()
        # Predicate 1: substring on names, with length floor
        if (
            len(new_name_lower) >= name_substring_min_len
            and len(ex_name_lower) >= name_substring_min_len
            and (new_name_lower in ex_name_lower or ex_name_lower in new_name_lower)
        ):
            return entry
        # Predicate 2: content-word overlap on descriptions
        ex_words = _content_words(entry.description)
        if len(new_words & ex_words) >= min_shared_words:
            return entry
    return None


def generate_discoveries(
    prediction_eval: dict[str, Any] | None,
    model_type: str,
    best_score: float | None,
    inherited_components: list[dict[str, Any]],
    proposed_vocab_links: list[dict[str, Any]],
    timing: dict[str, Any] | None = None,
    slow_threshold_s: float = 1800.0,
    overall_best_score: float | None = None,
    *,
    order: MetricOrder,
) -> list[VocabEntry]:
    """
    Generate kind='discovery' VocabEntry entries from this iteration's results.

    Produces up to 4 discovery sentences based on:
    - Whether the prediction was confirmed/refuted
    - What score the model achieved vs SOTA
    - Whether the model was unusually slow (timing discovery)
    - Which features were inherited and whether they helped

    Args:
        timing: Dict with train_time_s, inference_time_s, scoring_time_s from
                the best experiment's timing record. When provided and total
                time exceeds slow_threshold_s, a timing discovery is generated.
        slow_threshold_s: Total experiment time (train+inference) above which
                          a timing discovery is emitted. Default 1800s (30 min).
        overall_best_score: The best score across ALL models seen this iteration
                            (new + cached). Used as the SOTA baseline for the
                            score comparison discovery. Falls back to
                            prediction_eval["current_value"] (the SOTA at
                            proposal time) when not provided, but that value
                            may be stale if a newer model has since surpassed it.
        order: the run's ``MetricOrder`` (Step 09a C3, keyword-only, REQUIRED).
                            Discovery 2 picks the strictest SOTA and compares
                            against it — both are direction questions.
    """
    discoveries = []

    # Discovery 1: prediction outcome
    #
    # Step 09a C4 (E5): an UNEVALUATED prediction produces no discovery. The
    # pre-09a code emitted one for ANY truthy outcome, and since an
    # uncomputable metric was labelled "partial", production published
    # "PARTIAL: <model> achieved metric=N/A ... Results are inconclusive." as
    # a scientific finding — then carried it in the vocabulary. A comparison
    # that could not be made is not an inconclusive result; it is no result.
    if (
        prediction_eval
        and prediction_eval.get("outcome")
        and prediction_eval.get("outcome") != OUTCOME_UNEVALUATED
    ):
        outcome = prediction_eval["outcome"]
        metric = prediction_eval.get("metric", "denoising_score")
        predicted = prediction_eval.get("predicted_value")
        actual = prediction_eval.get("actual_value")

        actual_str = f"{actual:.4f}" if actual is not None else "N/A"
        predicted_str = f"{predicted:.4f}" if predicted is not None else "N/A"

        if outcome == "confirmed":
            desc = (
                f"CONFIRMED: {model_type} achieved {metric}={actual_str} "
                f"(predicted {predicted_str}). The hypothesis was supported."
            )
        elif outcome == "refuted":
            desc = (
                f"REFUTED: {model_type} achieved {metric}={actual_str} "
                f"(predicted {predicted_str}). The hypothesis was NOT supported."
            )
        else:
            desc = (
                f"PARTIAL: {model_type} achieved {metric}={actual_str} "
                f"(predicted {predicted_str}). Results are inconclusive."
            )

        # Related features from inherited components
        related = [ic.get("component", "") for ic in inherited_components if ic.get("component")]

        discoveries.append(
            VocabEntry(
                name=f"prediction_{model_type}_{outcome}",
                kind="discovery",
                description=desc,
                related_to=related[:5],  # limit related_to length
                tier="candidate",
                proposed_by_run=model_type,
            )
        )

    # Discovery 2: score comparison to SOTA
    if best_score is not None:
        # Use the strictest available SOTA: overall_best_score (current-iteration max across
        # all models) takes precedence over prediction_eval["current_sota"] (the SOTA at
        # proposal time, which may be stale if a newer model has since surpassed it).
        sota_from_prediction = prediction_eval.get("current_sota") if prediction_eval else None
        if overall_best_score is not None and sota_from_prediction is not None:
            # "strictest" = the BETTER of the two on the metric's own axis.
            sota_score = order.best(
                [sota_from_prediction, overall_best_score], key=lambda value: value
            )
        else:
            sota_score = (
                sota_from_prediction if sota_from_prediction is not None else overall_best_score
            )
        if sota_score is not None:
            # Step 09a C3. The relative band used to scale the reference by
            # (1 - margin) and compare directly — degenerate for a NEGATIVE
            # reference, because scaling a negative SOTA by
            # 0.95 moves it UP, so the "within 5%" arm was unreachable for every
            # TIDMAD score and a competitive model was reported as "significantly
            # below". The corrected form measures the DISTANCE against a band
            # width taken from the reference's MAGNITUDE. The margin is unchanged
            # at 0.05 (frozen, Q-09a-5) — only direction and the negative-reference
            # arithmetic are fixed.
            distance = abs(best_score - sota_score)
            band_width = _DISCOVERY_RELATIVE_BAND * abs(sota_score)
            if order.is_better(best_score, sota_score):
                desc = (
                    f"{model_type} scored {best_score:.4f}, beating the previous "
                    f"SOTA of {sota_score:.4f} (+{distance:.4f})."
                )
            elif distance <= band_width:
                desc = (
                    f"{model_type} scored {best_score:.4f}, within 5% of "
                    f"SOTA ({sota_score:.4f}). Competitive but not a clear improvement."
                )
            else:
                desc = (
                    f"{model_type} scored {best_score:.4f}, significantly below "
                    f"SOTA ({sota_score:.4f}). The approach needs revision."
                )

            discoveries.append(
                VocabEntry(
                    name=f"score_{model_type}_vs_sota",
                    kind="discovery",
                    description=desc,
                    tier="candidate",
                    proposed_by_run=model_type,
                )
            )

    # Discovery 3: timing (architectural resource cost)
    if timing is not None:
        train_s = timing.get("train_time_s") or 0
        infer_s = timing.get("inference_time_s") or 0
        total_s = train_s + infer_s
        if total_s >= slow_threshold_s:
            desc = (
                f"{model_type}: {total_s / 60:.1f} min/experiment "
                f"(train={train_s / 60:.1f}, infer={infer_s / 60:.1f} min). "
                f"High compute cost — reduce segmentation_size or complexity."
            )
            discoveries.append(
                VocabEntry(
                    name=f"timing_{model_type}_slow",
                    kind="discovery",
                    description=desc,
                    tier="candidate",
                    proposed_by_run=model_type,
                )
            )

    return discoveries


def promote_candidates(
    vocab: list[VocabEntry],
    min_runs: int = 2,
) -> tuple[list[VocabEntry], list[str]]:
    """
    Promote candidate VocabEntry items to canonical tier.

    A candidate is promoted when:
      - tier == "candidate"
      - kind in {"feature", "capability"}  (discoveries are never promoted)
      - len(seen_in_runs) >= min_runs

    Post-v15: ``min_runs`` lowered from 3 to 2. v15 retrospective found
    that no candidate ever reached ``seen_in_runs >= 3`` across 20
    iterations because the proposer invented a new compound name per iter
    even for repeated mechanisms (root cause documented in
    ``reports/v15_20260628.md`` §4.5). The complementary fix in
    ``build_runtime_vocab`` now merges semantic near-duplicates into one
    entry via ``_find_duplicate_candidate``; combined with the lower
    ``min_runs`` floor and the new comparison-stage prompt instruction,
    candidates that genuinely repeat across iterations should now actually
    promote.

    The require_positive_delta criterion (promotion only when candidate
    contributed to SOTA-beating runs) is deferred — it requires per-run
    score context not currently available here. See C.5 design doc.

    Args:
        vocab:    Current runtime vocabulary.
        min_runs: Minimum distinct runs before promotion. Default 2
            (post-v15 lowered from 3). Tests may override.

    Returns:
        (updated_vocab, promoted_names) — updated list with tier changes
        applied, and the names of entries promoted this call.
    """
    updated: list[VocabEntry] = []
    promoted_names: list[str] = []

    for entry in vocab:
        if (
            entry.tier == "candidate"
            and entry.kind in {"feature", "capability"}
            and len(entry.seen_in_runs) >= min_runs
        ):
            updated.append(entry.model_copy(update={"tier": "canonical"}))
            promoted_names.append(entry.name)
        else:
            updated.append(entry)

    return updated, promoted_names


def compute_vocab_diversity_ratio(vocab: Sequence[VocabEntry | dict[str, Any]]) -> float:
    """
    Compute the vocabulary diversity ratio: candidate features/capabilities
    as a fraction of total vocab entries.

    Measures how actively the system is exploring new architectural concepts.
    A low ratio (few candidates) signals vocabulary stagnation — the system
    is only recycling canonical terms. The exploration resolver uses this to
    force explore mode when the ratio falls below a threshold.

    Discovery entries are excluded from both numerator and denominator because
    they are empirical findings, not architectural building blocks, and their
    count doesn't reflect vocabulary health.

    Args:
        vocab: Current runtime vocabulary (seed + candidates + discoveries).

    Returns:
        float in [0, 1]: n_feature_capability_candidates / n_feature_capability_total.
        Returns 0.0 for an empty vocabulary or one with no features/capabilities.
    """
    # ``isinstance(v, VocabEntry)`` is preferred over ``hasattr(v, X)`` because
    # pyright treats it as a type guard and narrows the union on each branch:
    # the ``if`` leg sees ``VocabEntry`` (with .kind/.tier), the ``else`` leg
    # sees ``dict`` (with .get). Behaviour is identical for every input we
    # observe in production — runtime-validated VocabEntry instances or raw
    # dicts from legacy JSON payloads.
    fc_entries = [
        v
        for v in vocab
        if (v.kind if isinstance(v, VocabEntry) else v.get("kind", "")) in {"feature", "capability"}
    ]
    if not fc_entries:
        return 0.0
    candidates = [
        v
        for v in fc_entries
        if (v.tier if isinstance(v, VocabEntry) else v.get("tier", "")) == "candidate"
    ]
    return len(candidates) / len(fc_entries)


def build_runtime_vocab(
    incoming_vocab: list[VocabEntry],
    new_discoveries: list[VocabEntry],
    proposed_candidates: list[dict[str, Any]],
) -> list[VocabEntry]:
    """
    Build the updated runtime vocabulary for the next iteration.

    Merges: incoming vocabulary + new discoveries + any new candidates
    from the proposal. Deduplicates by name.

    Args:
        incoming_vocab: Vocabulary from previous iteration (or seed).
        new_discoveries: Discovery entries from this round's evaluation.
        proposed_candidates: New feature/capability candidates from the
                            proposal's proposed_vocab_candidates.

    Returns:
        Updated vocabulary list (deduplicated by name).
    """
    # Start with incoming vocab
    vocab_by_name: dict[str, VocabEntry] = {}
    for entry in incoming_vocab:
        if hasattr(entry, "name"):
            vocab_by_name[entry.name] = entry
        elif isinstance(entry, dict):
            vocab_by_name[entry["name"]] = VocabEntry.model_validate(entry)

    # Add new discoveries
    for discovery in new_discoveries:
        vocab_by_name[discovery.name] = discovery

    # Add proposed candidates (features/capabilities from the proposal).
    # Track seen_in_runs: append proposed_by_run whenever a candidate is encountered,
    # whether it is new, an exact-name match, or a heuristic near-duplicate of
    # an existing candidate (post-v15 fix; see ``_find_duplicate_candidate``).
    for candidate in proposed_candidates:
        if not isinstance(candidate, dict) or "name" not in candidate:
            continue
        name = candidate["name"]
        run = candidate.get("proposed_by_run") or ""
        if name not in vocab_by_name:
            # New name — but check whether it's a NEAR-DUPLICATE of an
            # existing candidate of the same kind. v15 retrospective: 7
            # different feature-tier candidates described the same
            # reweighting mechanism but with different compound names; this
            # caused seen_in_runs to permanently cap at 1 across all 20
            # iterations. The heuristic dedup runs BEFORE the new entry is
            # appended so its run signal merges into the existing entry.
            try:
                entry = VocabEntry.model_validate(candidate)
            except Exception:
                continue  # skip malformed candidates
            # Discoveries are never deduplicated (they're empirical results
            # uniquely tied to one run, not architectural primitives).
            duplicate_of: VocabEntry | None = None
            if entry.kind in {"feature", "capability"}:
                duplicate_of = _find_duplicate_candidate(
                    new_name=entry.name,
                    new_kind=entry.kind,
                    new_description=entry.description,
                    existing_vocab=vocab_by_name,
                )
            if duplicate_of is not None:
                # Merge: extend the existing entry's seen_in_runs with this
                # run and record the new name as an alias. The existing
                # entry's description / related_to / etc. are kept verbatim
                # — the assumption is that the first author of a candidate
                # name wrote the canonical description for that mechanism.
                updates: dict[str, Any] = {}
                if run and run not in duplicate_of.seen_in_runs:
                    updates["seen_in_runs"] = [*duplicate_of.seen_in_runs, run]
                if entry.name not in duplicate_of.aliases:
                    updates["aliases"] = [*duplicate_of.aliases, entry.name]
                if updates:
                    vocab_by_name[duplicate_of.name] = duplicate_of.model_copy(update=updates)
            else:
                # Genuinely new candidate — add as a fresh entry.
                if run and run not in entry.seen_in_runs:
                    entry = entry.model_copy(update={"seen_in_runs": [run]})
                vocab_by_name[name] = entry
        else:
            # Exact-name match: extend seen_in_runs without duplicates.
            existing = vocab_by_name[name]
            if run and run not in existing.seen_in_runs:
                vocab_by_name[name] = existing.model_copy(
                    update={"seen_in_runs": [*existing.seen_in_runs, run]}
                )

    return list(vocab_by_name.values())


def update_vocab_link_confirmations(
    prev_vocab_links: list[dict[str, Any]],
    prediction_outcome: str | None,
    run_name: str,
    existing_confirmations: dict[str, list[str]],
    runtime_vocab: Sequence[VocabEntry | dict[str, Any]],
    min_runs: int = 3,
) -> tuple[dict[str, list[str]], list[VocabEntry], list[str]]:
    """
    Update vocab link confirmation tracking and promote confirmed links to VocabEntry.related_to.

    A ``ProposedVocabLink`` asserts that a feature enables a capability.
    When the experiment's prediction_outcome is ``'confirmed'`` (the model beat
    SOTA), every proposed link from that run is counted as one confirmation for
    the feature→capability pair.  Once a pair has been confirmed in ≥ min_runs
    distinct runs, the capability name is added to the feature's
    ``VocabEntry.related_to`` in ``runtime_vocab`` — the relationship graduates
    from hypothesis to established fact.

    Only ``'confirmed'`` predictions count; ``'partial'`` and ``'refuted'``
    outcomes leave link counts unchanged.

    Args:
        prev_vocab_links: ``proposed_vocab_links`` from the previous proposal.
                          Each dict must have ``'feature'`` and ``'capability'`` keys.
        prediction_outcome: Outcome from evaluate_prediction — 'confirmed',
                            'partial', 'refuted', or None.
        run_name: Identifier for this run (typically model_type).  Used to
                  deduplicate: the same run can only confirm a link once.
        existing_confirmations: Carry-forward mapping from 'feature:capability'
                                to list of confirming run_names.
        runtime_vocab: Current runtime vocabulary to update related_to in.
        min_runs: Confirmation threshold for promotion. Default 3.

    Returns:
        (updated_confirmations, updated_vocab, newly_promoted_pairs)
        where newly_promoted_pairs is a list of 'feature:capability' strings
        that were promoted to VocabEntry.related_to in this call.
    """
    # Deep-copy confirmations so we never mutate the caller's dict
    updated_confs: dict[str, list[str]] = {k: list(v) for k, v in existing_confirmations.items()}

    # Record confirmations from this run (only when prediction was confirmed)
    if prediction_outcome == "confirmed" and run_name:
        for link in prev_vocab_links:
            feature = link.get("feature", "")
            capability = link.get("capability", "")
            if not feature or not capability:
                continue
            key = f"{feature}:{capability}"
            if key not in updated_confs:
                updated_confs[key] = []
            if run_name not in updated_confs[key]:
                updated_confs[key].append(run_name)

    # Promote pairs that have enough confirmations to VocabEntry.related_to.
    # Build an index for O(1) feature lookup. The legacy ``dict`` branch is a
    # historic defensive guard that, in practice, never fires; if it did, the
    # original code stored the raw dict under a strongly-typed ``dict[str,
    # VocabEntry]`` key and would crash later at ``.model_copy``. We preserve
    # the symbolic name-extraction call for parity but skip the unsafe write,
    # closing the latent corruption hole.
    vocab_by_name: dict[str, VocabEntry] = {}
    for entry in runtime_vocab:
        if isinstance(entry, VocabEntry):
            vocab_by_name[entry.name] = entry
        else:
            entry.get("name", "")  # legacy fallback flow — no-op container side-effect

    newly_promoted: list[str] = []
    for key, run_names in updated_confs.items():
        if len(run_names) < min_runs:
            continue
        feature, _, capability = key.partition(":")
        feat_entry = vocab_by_name.get(feature)
        if feat_entry is None:
            continue
        # ``feat_entry`` is provably ``VocabEntry`` here (the index above only
        # admits VocabEntry values). The historic dict-fallback leg is kept
        # for archaeology: ``isinstance`` narrows the same way ``hasattr``
        # used to, runtime is unchanged for every observed input.
        existing_related = (
            feat_entry.related_to
            if isinstance(feat_entry, VocabEntry)
            else feat_entry.get("related_to", [])
        )
        if capability not in existing_related:
            updated = feat_entry.model_copy(update={"related_to": [*existing_related, capability]})
            vocab_by_name[feature] = updated
            newly_promoted.append(key)

    updated_vocab = list(vocab_by_name.values())
    return updated_confs, updated_vocab, newly_promoted


# ---------------------------------------------------------------------------
# Commit 6.1: Active-model selection + per_model Stability Filter +
#             synthesis-prompt compression.
#
# These three helpers form the "Active Model" policy that gates two distinct
# growth axes in the interpretation agent (V12 forensic finding):
#   axis 1 — synthesis prompt size grows linearly because every cached
#            model_type is concatenated verbatim into the prompt.
#   axis 2 — per_model LLM call count grows linearly because every cached
#            model_type triggers a fresh per_model call each iter.
#
# The shared decision is: which model_types are "active enough to need
# attention" this iter? Stable models are pulled from the cache as-is,
# without a fresh LLM call (axis 2) and represented as a one-line takeaway
# in the synthesis prompt (axis 1). The thresholds (top_k, last_n,
# score_delta_threshold) are configured via InterpretationInput.
# ---------------------------------------------------------------------------


def select_active_models(
    cache_entries: dict[str, dict[str, Any]],
    current_iter_summaries: list[
        Any
    ],  # List[ModelRunSummary]; loose-typed to avoid circular import
    top_k: int = 3,
    last_n: int = 2,
    score_delta_threshold: float = 0.05,
    *,
    order: MetricOrder,
) -> set[str]:
    """Pick the active model_types as the union of three sets.

    The active set is the union of:

      1. **Top-K by best score** — the K models with the highest
         ``_stats.best_denoising_score`` across ``cache_entries``. Ties
         broken by lexicographic order on ``model_type`` for determinism.
         Models whose cached ``best_denoising_score`` is None are excluded
         from this ranking (cannot be ranked).
      2. **Last-N most-recent** — the N model_types from
         ``current_iter_summaries`` (these are by definition the freshest
         tuning runs this iter). If ``len(current_iter_summaries) > last_n``,
         the helper takes the first N from the list (callers may pre-sort
         by proposal time). If ``last_n=0`` this set is empty.
      3. **Delta-Δ models** — for each ``mt`` in ``current_iter_summaries``
         that also has a prior cache entry, include ``mt`` if
         ``abs(new_best_score - cached_best_score) >= score_delta_threshold``.
         A model in ``current_iter_summaries`` with no prior cache entry
         contributes via Last-N (no prior score to compare to).

    Args:
        cache_entries: Mapping ``{model_type: cache_entry}`` from
            ``InterpretationInput.model_knowledge_cache`` (i.e., the cache
            as it exists at the start of this iter, before any updates).
        current_iter_summaries: This iter's ``ModelRunSummary`` list (one
            per newly-tuned model). Pass the full list; the helper handles
            ordering for the Last-N selection.
        top_k: Top-K cap by best_score. Default 3.
        last_n: Last-N cap by recency. Default 2.
        score_delta_threshold: Absolute delta (in normalised score units)
            required to include a model via the Delta-Δ pathway. Default
            0.05.

    Returns:
        ``Set[str]`` of active model_types. Always a subset of
        ``set(cache_entries.keys()) | {s.model_type for s in current_iter_summaries}``.
    """
    if top_k < 0 or last_n < 0 or score_delta_threshold < 0:
        raise ValueError(
            "select_active_models thresholds must be non-negative: "
            f"top_k={top_k}, last_n={last_n}, score_delta_threshold={score_delta_threshold}"
        )

    active: set[str] = set()

    # (1) Top-K by raw score for prompt-refresh scheduling. This controls LLM
    # summarization cost, not execution-candidate eligibility.
    scored = [
        (mt, entry.get("_stats", {}).get("best_denoising_score"))
        for mt, entry in cache_entries.items()
    ]
    scored = [(mt, s) for mt, s in scored if s is not None]
    # Step 09a C3. Was `(-x[1], x[0])` — "biggest number first". A NEGATED sort
    # key IS a direction literal, and it selects the WORST K under a minimised
    # metric. `rank` is 1 + (values strictly better), so ties share a rank and
    # still break on model_type: identical order to the old key under `higher`,
    # correctly inverted under `lower`.
    present_scores = [value for _, value in scored]
    scored.sort(key=lambda x: (order.rank(present_scores, x[1]), x[0]))
    active.update(mt for mt, _ in scored[:top_k])

    # (2) Last-N most-recent: current iter's summaries.
    recent_mts = [s.model_type for s in current_iter_summaries]
    active.update(recent_mts[:last_n])

    # (3) Delta-Δ: current iter's summaries with significant score change vs cache.
    for s in current_iter_summaries:
        mt = s.model_type
        new_score = s.best_denoising_score
        if new_score is None:
            continue
        prior = cache_entries.get(mt, {}).get("_stats", {}).get("best_denoising_score")
        if prior is None:
            continue  # no baseline to compare; covered by Last-N
        if abs(new_score - prior) >= score_delta_threshold:
            active.add(mt)

    return active


def compress_model_summary(
    model_type: str,
    cache_entry: dict[str, Any],
    max_takeaway_chars: int = 150,
) -> dict[str, Any]:
    """Compact a frozen cache entry into a one-line summary for the synthesis prompt.

    The returned dict is meant to slot into the synthesis prompt's per-model
    loop in place of the full multi-section block. Total target: ≤ 200 chars
    when serialised back into the prompt (one line of metadata + one line
    of takeaway).

    The takeaway is **deterministically extracted** from the entry's
    ``key_findings`` (first finding, truncated to ``max_takeaway_chars``).
    No LLM call is issued. If ``key_findings`` is empty, the takeaway falls
    back to ``best_config_analysis`` (truncated), then to a placeholder.

    Args:
        model_type: The architecture key (used in the returned dict).
        cache_entry: A frozen cache entry — the dict stored at
            ``model_knowledge_cache[model_type]``. Expected keys: any of
            ``key_findings`` (list[str]), ``best_config_analysis`` (str),
            and the ``_stats`` block (numerical).
        max_takeaway_chars: Hard cap on the takeaway string. Default 150.

    Returns:
        ``{"model_type": str, "best_score": Optional[float], "n_rounds": int,
           "one_line_takeaway": str}``.
    """
    if max_takeaway_chars <= 0:
        raise ValueError(f"max_takeaway_chars must be positive, got {max_takeaway_chars}")

    stats = cache_entry.get("_stats", {}) or {}

    # findings shape evolves across Commit 6.3:
    #   pre-6.3 / cache-miss build  : list[str]                     (legacy flat dump)
    #   post-6.3 / consolidator dump: list[{"statement": str, ...}] (CacheEntry.model_dump)
    # The takeaway is always the first finding's text; the consolidator
    # encodes [SUPERSEDES]/[CONFLICT] prefixes directly into the statement,
    # so the same render rule works for both shapes.
    findings = cache_entry.get("key_findings") or []
    takeaway = ""
    if findings:
        first = findings[0]
        if isinstance(first, str):
            takeaway = first
        elif isinstance(first, dict) and isinstance(first.get("statement"), str):
            takeaway = first["statement"]
    if not takeaway:
        # best_config_analysis is str (legacy) or {"latest": str, ...} (modern).
        bca = cache_entry.get("best_config_analysis")
        if isinstance(bca, str) and bca:
            takeaway = bca
        elif isinstance(bca, dict) and isinstance(bca.get("latest"), str) and bca["latest"]:
            takeaway = bca["latest"]
    if not takeaway:
        takeaway = "(no cached takeaway)"

    if len(takeaway) > max_takeaway_chars:
        takeaway = takeaway[: max_takeaway_chars - 1].rstrip() + "…"

    return {
        "model_type": model_type,
        "best_score": stats.get("best_denoising_score"),
        "n_rounds": stats.get("completed_rounds", 0) or 0,
        "one_line_takeaway": takeaway,
    }


def should_recall_per_model(
    model_type: str,
    cache_entry: dict[str, Any] | None,
    current_iter_summary: Any | None,  # Optional[ModelRunSummary]
    active_set: set[str],
    score_delta_threshold: float = 0.05,
) -> bool:
    """Decide whether to issue a fresh ``interpretation.per_model`` LLM call.

    Returns ``True`` when the agent must re-summarise the model_type with a
    fresh LLM call this iter; returns ``False`` when the cached entry is
    safe to reuse verbatim (zero LLM cost — the V12 fix).

    The decision tree:

      1. **Cache miss** (``cache_entry is None``): always ``True``.
         A model never seen before must be summarised at least once,
         regardless of active-set membership.
      2. **Cache hit + not in active_set**: ``False``. Stable historical
         model — reuse the prior summary, skip the LLM call.
      3. **Cache hit + in active_set + has new training data**: ``True``.
         The active model has fresh evidence to reflect; re-call the LLM.
         "Has new training data" means ``current_iter_summary`` is not
         ``None`` AND either (a) ``completed_rounds`` increased vs. the
         cached count, OR (b) ``abs(new_best - cached_best) >= threshold``.
      4. **Cache hit + in active_set + no new training data**: ``False``.
         The model is in the active set (e.g., via Top-K) but had no new
         tuning rounds this iter. Reuse the cache; do not waste an LLM
         call on unchanged data.

    Args:
        model_type: The architecture key (used for clarity; the function
            does not look it up — the caller passes ``cache_entry`` and
            ``current_iter_summary`` directly).
        cache_entry: The prior cache entry, or ``None`` for a cache miss.
        current_iter_summary: This iter's ``ModelRunSummary`` for this
            model_type, or ``None`` if the model was not tuned this iter.
        active_set: The set of active model_types from ``select_active_models``.
        score_delta_threshold: Score-delta cutoff for "has new evidence".
            Should match the threshold used in ``select_active_models``
            so the two decisions are coherent. Default 0.05.

    Returns:
        ``bool`` — ``True`` to issue a fresh LLM call, ``False`` to reuse
        the cached entry verbatim.
    """
    # (1) Cache miss → must summarise.
    if cache_entry is None:
        return True

    # (2) Stable model (not in active set) → reuse cache.
    if model_type not in active_set:
        return False

    # (3 & 4) Active model — only recall if there's new evidence.
    if current_iter_summary is None:
        return False  # no new tuning data this iter

    cached_stats = cache_entry.get("_stats") or {}
    cached_rounds = cached_stats.get("completed_rounds", 0) or 0
    new_rounds = getattr(current_iter_summary, "completed_rounds", 0) or 0
    if new_rounds > cached_rounds:
        return True

    cached_best = cached_stats.get("best_denoising_score")
    new_best = getattr(current_iter_summary, "best_denoising_score", None)
    return (
        cached_best is not None
        and new_best is not None
        and abs(new_best - cached_best) >= score_delta_threshold
    )
