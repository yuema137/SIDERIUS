# nodes/interpretation_helpers.py
"""
Pure helper functions for result_interpretation_agent — Phase C vocabulary feedback.

These are deterministic Python functions with no LLM calls.
They evaluate predictions, generate discoveries, and build the runtime vocabulary.
"""

import math
from typing import Any, Dict, List, Optional

from agent.schemas.proposal import VocabEntry, ProposedVocabLink, FalsifiablePrediction


def evaluate_prediction(
    prediction: Dict[str, Any],
    actual_results: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Evaluate a FalsifiablePrediction against actual tuning results.

    Args:
        prediction: Serialized FalsifiablePrediction dict with
                    metric, current_value, predicted_value, threshold_for_refutation.
                    Common LLM aliases for 'denoising_score' are accepted:
                    'best_score', 'score', 'overall denoising score', etc.
        actual_results: Dict with at least 'best_denoising_score' and
                        optionally 'best_file_vector'.

    Returns:
        Dict with: metric, predicted_value, actual_value, outcome
        ('confirmed'/'refuted'/'partial'), boldness, information_gain.
    """
    metric = prediction.get("metric", "denoising_score")
    predicted = prediction.get("predicted_value")
    current = prediction.get("current_value")
    threshold = prediction.get("threshold_for_refutation")

    # Compute actual value from results
    actual = _compute_metric(metric, actual_results)

    if actual is None or predicted is None or current is None:
        return {
            "metric": metric,
            "predicted_value": predicted,
            "actual_value": actual,
            "outcome": "partial",
            "boldness": 0.0,
            "information_gain": 0.0,
            "notes": "Could not compute metric from results.",
        }

    # Determine outcome
    predicting_increase = predicted > current
    if predicting_increase:
        if actual >= predicted:
            outcome = "confirmed"
        elif threshold is not None and actual <= threshold:
            outcome = "refuted"
        else:
            outcome = "partial"
    else:
        # Predicting decrease (rare but valid for ablation experiments)
        if actual <= predicted:
            outcome = "confirmed"
        elif threshold is not None and actual >= threshold:
            outcome = "refuted"
        else:
            outcome = "partial"

    boldness = abs(predicted - current) / max(abs(current), 1e-6)
    information_gain = boldness if outcome == "confirmed" else 0.0

    return {
        "metric": metric,
        "predicted_value": predicted,
        "actual_value": actual,
        "current_value": current,
        "outcome": outcome,
        "boldness": round(boldness, 4),
        "information_gain": round(information_gain, 4),
    }


_DENOISING_SCORE_ALIASES = {
    "denoising_score",
    "best_score",
    "overall denoising score",
    "score",
    "best_denoising_score",
}


def _compute_metric(metric: str, results: Dict[str, Any]) -> Optional[float]:
    """
    Compute a metric value from tuning results.

    Supports:
      - 'denoising_score' (and common LLM aliases) → results['best_denoising_score']
      - 'mean(file_vector[N:M])' → mean of file_vector slice
      - 'file_vector[N]' → single file score
    """
    if metric in _DENOISING_SCORE_ALIASES:
        return results.get("best_denoising_score")

    fv = results.get("best_file_vector")
    if fv is None:
        return None

    # Parse mean(file_vector[N:M])
    if metric.startswith("mean(file_vector[") and metric.endswith("])"):
        inner = metric[len("mean(file_vector["):-len("])")].strip()
        try:
            parts = inner.split(":")
            start = int(parts[0])
            end = int(parts[1]) if len(parts) > 1 else start + 1
            values = [v for v in fv[start:end] if v is not None and not (isinstance(v, float) and math.isnan(v))]
            return sum(values) / len(values) if values else None
        except (ValueError, IndexError):
            return None

    # Parse file_vector[N]
    if metric.startswith("file_vector[") and metric.endswith("]"):
        try:
            idx = int(metric[len("file_vector["):-1])
            val = fv[idx]
            if val is not None and not (isinstance(val, float) and math.isnan(val)):
                return val
        except (ValueError, IndexError):
            pass
        return None

    return None


def generate_discoveries(
    prediction_eval: Optional[Dict[str, Any]],
    model_type: str,
    best_score: Optional[float],
    inherited_components: List[Dict[str, Any]],
    proposed_vocab_links: List[Dict[str, Any]],
    timing: Optional[Dict[str, Any]] = None,
    slow_threshold_s: float = 1800.0,
    overall_best_score: Optional[float] = None,
) -> List[VocabEntry]:
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
    """
    discoveries = []

    # Discovery 1: prediction outcome
    if prediction_eval and prediction_eval.get("outcome"):
        outcome = prediction_eval["outcome"]
        metric = prediction_eval.get("metric", "denoising_score")
        predicted = prediction_eval.get("predicted_value")
        actual = prediction_eval.get("actual_value")

        actual_str = f"{actual:.4f}" if actual is not None else "N/A"
        predicted_str = f"{predicted:.4f}" if predicted is not None else "N/A"

        if outcome == "confirmed":
            desc = (f"CONFIRMED: {model_type} achieved {metric}={actual_str} "
                    f"(predicted {predicted_str}). The hypothesis was supported.")
        elif outcome == "refuted":
            desc = (f"REFUTED: {model_type} achieved {metric}={actual_str} "
                    f"(predicted {predicted_str}). The hypothesis was NOT supported.")
        else:
            desc = (f"PARTIAL: {model_type} achieved {metric}={actual_str} "
                    f"(predicted {predicted_str}). Results are inconclusive.")

        # Related features from inherited components
        related = [ic.get("component", "") for ic in inherited_components if ic.get("component")]

        discoveries.append(VocabEntry(
            name=f"prediction_{model_type}_{outcome}",
            kind="discovery",
            description=desc,
            related_to=related[:5],  # limit related_to length
            tier="candidate",
            proposed_by_run=model_type,
        ))

    # Discovery 2: score comparison to SOTA
    if best_score is not None:
        # Use the strictest available SOTA: overall_best_score (current-iteration max across
        # all models) takes precedence over prediction_eval["current_value"] (the SOTA at
        # proposal time, which may be stale if a newer model has since surpassed it).
        sota_from_prediction = prediction_eval.get("current_value") if prediction_eval else None
        if overall_best_score is not None and sota_from_prediction is not None:
            sota_score = max(sota_from_prediction, overall_best_score)
        else:
            sota_score = sota_from_prediction if sota_from_prediction is not None else overall_best_score
        if sota_score is not None:
            if best_score > sota_score:
                desc = (f"{model_type} scored {best_score:.4f}, beating the previous "
                        f"SOTA of {sota_score:.4f} (+{best_score - sota_score:.4f}).")
            elif best_score > sota_score * 0.95:
                desc = (f"{model_type} scored {best_score:.4f}, within 5% of "
                        f"SOTA ({sota_score:.4f}). Competitive but not a clear improvement.")
            else:
                desc = (f"{model_type} scored {best_score:.4f}, significantly below "
                        f"SOTA ({sota_score:.4f}). The approach needs revision.")

            discoveries.append(VocabEntry(
                name=f"score_{model_type}_vs_sota",
                kind="discovery",
                description=desc,
                tier="candidate",
                proposed_by_run=model_type,
            ))

    # Discovery 3: timing (architectural resource cost)
    if timing is not None:
        train_s = timing.get("train_time_s") or 0
        infer_s = timing.get("inference_time_s") or 0
        total_s = train_s + infer_s
        if total_s >= slow_threshold_s:
            desc = (
                f"{model_type}: {total_s/60:.1f} min/experiment "
                f"(train={train_s/60:.1f}, infer={infer_s/60:.1f} min). "
                f"High compute cost — reduce segmentation_size or complexity."
            )
            discoveries.append(VocabEntry(
                name=f"timing_{model_type}_slow",
                kind="discovery",
                description=desc,
                tier="candidate",
                proposed_by_run=model_type,
            ))

    return discoveries


def promote_candidates(
    vocab: List[VocabEntry],
    min_runs: int = 3,
) -> tuple[List[VocabEntry], List[str]]:
    """
    Promote candidate VocabEntry items to canonical tier.

    A candidate is promoted when:
      - tier == "candidate"
      - kind in {"feature", "capability"}  (discoveries are never promoted)
      - len(seen_in_runs) >= min_runs

    The require_positive_delta criterion (promotion only when candidate
    contributed to SOTA-beating runs) is deferred — it requires per-run
    score context not currently available here. See C.5 design doc.

    Args:
        vocab:    Current runtime vocabulary.
        min_runs: Minimum distinct runs before promotion. Default 3.

    Returns:
        (updated_vocab, promoted_names) — updated list with tier changes
        applied, and the names of entries promoted this call.
    """
    updated: List[VocabEntry] = []
    promoted_names: List[str] = []

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


def compute_vocab_diversity_ratio(vocab: List[VocabEntry]) -> float:
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
    fc_entries = [
        v for v in vocab
        if (v.kind if hasattr(v, "kind") else v.get("kind", "")) in {"feature", "capability"}
    ]
    if not fc_entries:
        return 0.0
    candidates = [
        v for v in fc_entries
        if (v.tier if hasattr(v, "tier") else v.get("tier", "")) == "candidate"
    ]
    return len(candidates) / len(fc_entries)


def build_runtime_vocab(
    incoming_vocab: List[VocabEntry],
    new_discoveries: List[VocabEntry],
    proposed_candidates: List[Dict[str, Any]],
) -> List[VocabEntry]:
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
    vocab_by_name: Dict[str, VocabEntry] = {}
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
    # whether it is new or already present from a prior iteration.
    for candidate in proposed_candidates:
        if not isinstance(candidate, dict) or "name" not in candidate:
            continue
        name = candidate["name"]
        run = candidate.get("proposed_by_run") or ""
        if name not in vocab_by_name:
            try:
                entry = VocabEntry.model_validate(candidate)
                if run and run not in entry.seen_in_runs:
                    entry = entry.model_copy(update={"seen_in_runs": [run]})
                vocab_by_name[name] = entry
            except Exception:
                pass  # skip malformed candidates
        else:
            # Already present: extend seen_in_runs without duplicates
            existing = vocab_by_name[name]
            if run and run not in existing.seen_in_runs:
                vocab_by_name[name] = existing.model_copy(
                    update={"seen_in_runs": existing.seen_in_runs + [run]}
                )

    return list(vocab_by_name.values())
