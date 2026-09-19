# nodes/ml_model_proposal_agent/evidence_rendering.py
"""PRIVATE to ml_model_proposal_agent — rendering proposer evidence into prompts.

Step 10 / P3 C2 (design §4.3, §4.4, §6). One responsibility: turn the typed
:class:`~agent.schemas.proposer_evidence.ProposerInterpretationEvidence` into
the exact text and dict shapes the stage prompts carry. The node module keeps
SEQUENCING — plan the stages, call the LLM, assemble the record — and stops
holding the renderers inline.

This is a private submodule under the node's public boundary
(``tests/unit/nodes/test_node_public_boundary.py``): production code outside
the node must not import it, and it must not import the node's main module.

Why the shapes here look "dict-ish" for a typed migration
---------------------------------------------------------
``accumulated`` is ``json.dumps``-ed with ``default=str`` at the stage boundary
and is read by helpers that dispatch on ``isinstance(x, dict)``
(``proposal_helpers.build_candidate_markdown_block``). A typed object left in
there would silently render as ``_Score table unavailable._`` or as a ``str()``
repr. So the typed value is the INPUT to these renderers and plain JSON-able
structures are their OUTPUT — the migration moves where evidence is DECLARED,
not what the prompt bytes are.
"""

from __future__ import annotations

import json
from typing import Any

from agent.prompt_templates.interpretation.rendering import (
    render_prediction_track_record,
)
from agent.schemas.proposer_evidence import ProposerInterpretationEvidence

#: The keys, IN ORDER, that reach the stage prompts as ``interpretation_summary``.
#:
#: Relocated verbatim from ``_run_pipeline``'s inline comprehension. The order
#: is load-bearing: it is the JSON key order the LLM reads, and the goldens pin
#: it. The trailing prediction keys ride ALONGSIDE the legacy trio so a stage
#: can tell the frozen ``legacy_v1`` pool from the live v2 one (Step 09b C4);
#: a digest carrying none of them is unchanged here, because absent values are
#: filtered below exactly as the ``is not None`` comprehension did.
INTERPRETATION_SUMMARY_KEYS: tuple[str, ...] = (
    "model_types",
    "total_experiments",
    "best_denoising_score",
    "worst_denoising_score",
    "key_findings",
    "bottlenecks",
    "take_home_message",
    "per_model_best",
    "per_model_worst",
    "per_model_score_tables",
    "scientific_accuracy",
    "cumulative_information_gain",
    "prediction_outcomes_history",
    "prediction_outcomes_by_semantics",
    "cumulative_information_gain_by_semantics",
    "prediction_pool_sizes",
    "prediction_evaluation_semantics",
    "vocab_diversity_ratio",
)


def _jsonable(value: Any) -> Any:
    """Return the plain-JSON shape the raw dump carried for this value.

    Only ``per_model_score_tables`` holds models; everything else in the
    whitelist is already a scalar or a plain container. Written generically
    anyway, because a future typed field added to the whitelist must not
    silently reach ``json.dumps(default=str)`` as a repr string.
    """
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    return value


def build_interpretation_summary(
    evidence: ProposerInterpretationEvidence,
) -> dict[str, Any]:
    """The 18-key ``interpretation_summary`` block, byte-equal to the dict path.

    Same keys, same order, same ``is not None`` filtering, same JSON-visible
    value shapes as the comprehension this replaces. Parity is not asserted in
    prose: the C2 test builds the block BOTH ways over the same dump and
    requires deep equality.

    One DECLARED divergence, named because it is invisible in the fixtures:
    under the dict path a dump MISSING ``model_types`` produced ``None`` and
    was filtered out; the typed field defaults to ``[]``, which renders. No
    ``InterpretationOutput`` dump can omit it (the field is REQUIRED upstream),
    so production cannot reach this — but a hand-edited legacy CLI artifact
    can. It is pinned as a declared delta in the C2 test module rather than
    argued away; the differential fixtures cannot cover it, because on this
    input the two paths genuinely differ and agreement would be the bug.
    """
    summary: dict[str, Any] = {}
    for key in INTERPRETATION_SUMMARY_KEYS:
        value = getattr(evidence, key)
        if value is None:
            continue
        summary[key] = _jsonable(value)
    return summary


def render_healthgate_evidence_block(evidence: ProposerInterpretationEvidence) -> str:
    """Render the flag-gated ``[HEALTHGATE EVIDENCE]`` block (V19 PR 3 §3.7).

    Source of truth is EXCLUSIVELY the deterministic health fields
    (``per_model_round_health_counts``, ``per_model_collapse_fingerprints``,
    ``collapse_fingerprint_history``) — never ``key_findings`` or any other LLM
    prose. Distinct from the §14.N gate-exhaustion block (abort-class resource
    failures), which is untouched and rendered separately.

    Semantics (unchanged by the P3 migration — the bytes are golden-pinned):

    * Legacy evidence (all three fields absent) and empty evidence → ``""``
      (no header — callers splice unconditionally).
    * Evidence is grouped by model exactly as CB3 grouped it; nothing is
      aggregated across models and nothing is rendered unlabelled.
    * History entries are POST-retention (merge-time expiry, design §3.8), so
      every occurrence bucket shown is inside the retained window — counts here
      are retained-window counts by construction, never lifetime totals;
      iteration tags are the buckets' absolute iterations.
    * Entry-level raw metrics follow the representative-observation rule (§3.8)
      and are labelled as such — one representative value, not a summary of
      every occurrence.

    **Declared behaviour delta (P3 C2).** A malformed history entry used to
    raise a diagnostic ``ValueError`` HERE, at render time. It now fails
    earlier, at the projection boundary, through typed validation — so an
    entry reaching this function is already well-formed and there is nothing
    left to guard. Fail-closed moved upstream; it did not disappear.
    """
    counts_by_model = evidence.per_model_round_health_counts or {}
    fps_by_model = evidence.per_model_collapse_fingerprints or {}
    history_by_model = evidence.collapse_fingerprint_history or {}
    if not counts_by_model and not fps_by_model and not history_by_model:
        return ""

    # Model order: the evidence's model_types first (matches the per-model
    # scores section), then any evidence-only models — nothing silently dropped.
    ordered = list(evidence.model_types or [])
    for extra in sorted(set(counts_by_model) | set(fps_by_model) | set(history_by_model)):
        if extra not in ordered:
            ordered.append(extra)

    lines = [
        "[HEALTHGATE EVIDENCE] (deterministic, from the health-gate system — "
        "distinct from the resource-gate report above)"
    ]
    rendered_any = False
    for mt in ordered:
        counts = counts_by_model.get(mt)
        fps = fps_by_model.get(mt) or []
        history = history_by_model.get(mt) or []
        if not counts and not fps and not history:
            continue
        rendered_any = True
        lines += ["", f"### {mt}"]
        if counts:
            lines.append(
                f"Round validity (this iteration): {counts.get('valid', 0)} valid, "
                f"{counts.get('invalid', 0)} invalid, {counts.get('unknown', 0)} unknown"
            )
        if fps:
            lines.append("This iteration's collapse fingerprints:")
            for fp in fps:
                lines.append(f"  - {fp.signature} — {fp.human_readable}")
        if history:
            lines.append(
                "Retained history (bounded window; counts are retained-window "
                "occurrences, not lifetime totals):"
            )
            for entry in history:
                total = sum(o.count for o in entry.occurrences)
                iters = ", ".join(str(o.iteration) for o in entry.occurrences)
                lines.append(
                    f"  - {entry.signature}: {total} occurrence(s) across iteration(s) {iters}"
                )
                metrics = entry.metrics or {}
                if metrics:
                    rendered = "; ".join(f"{k}={v}" for k, v in sorted(metrics.items()))
                    lines.append(f"      Representative observation: {rendered}")
                source_ids = [i for o in entry.occurrences for i in o.source_exp_ids]
                if source_ids:
                    lines.append(
                        f"      Source experiments (recent, bounded): {', '.join(source_ids)}"
                    )
    if not rendered_any:
        return ""

    lines += [
        "",
        "Rules for using this evidence:",
        "  - Do not repeat a fingerprinted failure mode without naming a "
        "concrete mechanism expected to break it.",
        "  - The mechanism must change the actual relevant configuration "
        "(architecture family, output activation, normalization, loss, "
        "optimizer/training policy) — not merely the explanation text.",
        "  - A high raw score from an invalid round is a failure, not a success.",
        "  - Do not avoid unrelated healthy strategies merely because another model failed.",
        "  - Do not transfer one model's failure evidence to another model without justification.",
        "  - Do not claim this feedback was used unless the proposal actually "
        "changes a relevant mechanism.",
    ]
    return "\n".join(lines)


def truncate_description(text: str, max_chars: int = 1500) -> str:
    """Truncate a model description for prompt injection."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n[...truncated]"


def render_legacy_interpretation_section(
    evidence: ProposerInterpretationEvidence,
) -> list[str]:
    """The LEGACY reasoning prompt's interpretation region, from the typed value.

    Step 10 / P3 C3 (design §4.4). This is the second half of parent §11.2's
    acceptance rule: the legacy/standalone entrypoint survives, and it consumes
    the SAME typed evidence as production instead of independently mining the
    raw dump. Its prompt bytes are unchanged — PB-4 / S1-E and the C0 legacy
    goldens are the proof, on a full-coverage fixture and on a legacy artifact
    whose keys are absent rather than empty.

    Only the interpretation-derived region moves here. The surrounding blocks
    (hardware, data scope, constraints, previous failures, gate exhaustion,
    trial validity, human advice) are ``ProposalInput`` context rather than
    interpretation evidence, and their renderers live in the node module; a
    private submodule may not import its own node's main module, so pulling
    them across would have inverted the boundary this extraction exists to
    respect. The split is by ownership — evidence rendering here, input-context
    assembly there — which is also exactly where the seam already was.

    Two DEAD reads are deleted with this move: ``per_file_comparison`` and
    ``efficiency_comparison``. The producer has never declared either field, so
    both branches were provably unreachable and byte parity is unaffected.
    Parent non-goal 7 authorises repairing a dead read when a change touches
    that exact line, which this one does.
    """
    lines: list[str] = [
        "## Interpretation Summary",
        f"Models analysed     : {evidence.model_types}",
        # The dict path defaulted a MISSING key to the string 'unknown', which
        # is not the same as a present ``None``. Preserved explicitly rather
        # than left to ``or``, because the two render differently.
        f"Total experiments   : "
        f"{evidence.total_experiments if evidence.total_experiments is not None else 'unknown'}",
        f"Overall raw best    : {evidence.best_denoising_score}",
        f"Overall best valid  : {evidence.best_valid_denoising_score}",
        f"Overall worst score : {evidence.worst_denoising_score}",
        "",
    ]

    per_best = evidence.per_model_best or {}
    per_best_valid = evidence.per_model_best_valid or {}
    per_raw_health = evidence.per_model_raw_best_health_validity or {}
    per_worst = evidence.per_model_worst or {}
    if per_best:
        lines.append("### Per-model scores")
        for mt in evidence.model_types:
            lines.append(
                f"  {mt}: raw_best={per_best.get(mt)} "
                f"(health={per_raw_health.get(mt, 'unknown')}) "
                f"best_valid={per_best_valid.get(mt)} worst={per_worst.get(mt)}"
            )
        lines.append("")

    findings = evidence.key_findings or []
    if findings:
        lines.append("### Key Findings")
        for f in findings:
            lines.append(f"  - {f}")
        lines.append("")

    bottlenecks = evidence.bottlenecks or []
    if bottlenecks:
        lines.append("### Bottlenecks")
        for b in bottlenecks:
            lines.append(f"  - {b}")
        lines.append("")

    lines += [
        "### Take-home message",
        evidence.take_home_message or "",
        "",
    ]

    # Phase E — prediction track record.
    #
    # Step 09b C4: rendered by the ONE version-aware authority the interpreter's
    # own synthesis prompt uses. The pre-09b block here read `scientific_accuracy`
    # (v2-only since 09a) but computed its N from `prediction_outcomes_history`
    # (the FROZEN legacy pool) — v2 fractions over a v1 denominator, the
    # consequence Q-09a-3 declared and deferred to 09b. The renderer labels each
    # population with its own semantics id and never pools them; the section is
    # omitted entirely when no comparable prediction exists yet.
    track_record = render_prediction_track_record(
        legacy_history=evidence.prediction_outcomes_history,
        outcomes_by_semantics=evidence.prediction_outcomes_by_semantics,
        legacy_gain=evidence.cumulative_information_gain,
        gain_by_semantics=evidence.cumulative_information_gain_by_semantics,
        scientific_accuracy=evidence.scientific_accuracy,
    )
    if track_record:
        lines.append("### Prediction Track Record")
        lines += track_record
        lines.append("")

    # Phase C — vocabulary health
    vdr = evidence.vocab_diversity_ratio
    if vdr is not None:
        lines += [
            "### Vocabulary Health",
            f"  Diversity ratio : {vdr:.2f}  "
            f"({'LOW — consider proposing new vocabulary entries' if vdr < 0.1 else 'OK'})",
            "",
        ]

    # Per-model score tables — full rendered_markdown per model (Phase 5 C).
    # Legacy path has no ModelSelectionStrategy to split on, so every model
    # gets the complete 3-column table (raw_baseline / ground_truth / model)
    # plus the subset-scoped aggregate scalars.
    score_tables = evidence.per_model_score_tables
    if score_tables:
        lines.append("### Per-model score tables")
        lines.append("")
        for mt, table in score_tables.items():
            if not table.rendered_markdown:
                continue
            lines.append(f"#### {mt}")
            lines.append(table.rendered_markdown)
            lines.append("")

    # Per-model efficiency
    model_params = evidence.per_model_params
    if model_params:
        lines.append("### Model Parameters")
        for mt, params in model_params.items():
            score = per_best.get(mt)
            lines.append(f"  {mt}: {params:,} params → score {score}")
        lines.append("")

    # Per-model training data volume
    training_segs = evidence.per_model_training_segments
    if training_segs:
        lines.append("### Training Data Volume (PSD segments)")
        for mt, segs in training_segs.items():
            lines.append(f"  {mt}: {segs} segments (baseline=4000)")
        lines.append("")

    descriptions = evidence.model_descriptions or {}
    if descriptions:
        lines.append("## Existing Architecture Descriptions")
        for mt, desc in descriptions.items():
            lines += [f"### {mt}", truncate_description(desc), ""]

    best_config = evidence.best_config
    if best_config:
        lines += [
            "## Best Config So Far",
            json.dumps(best_config, indent=2),
            "",
        ]
    return lines


#: The direction-neutral authoring instruction rendered when the run declares
#: no usable metric identity. It carries NO numeric example and NO higher/lower
#: wording, because the Q-10-2 named absence forbids both: a consumer without an
#: identity shows raw values and refuses to rank, and a defaulted upward example
#: would be exactly the guess that rule exists to prevent.
#:
#: The three placeholders SHOUT their type. The with-identity example uses
#: numeric literals precisely because a pattern-matching model copies the shape
#: it is shown — and Gate 1 demonstrated that on this model population — so
#: prose sitting in a float-typed slot is the same hazard pointed the other way:
#: a model that copies it emits strings, `FalsifiablePrediction.model_validate`
#: rejects them, and the degraded regime burns causal-correction retries. Saying
#: "REPLACE WITH A NUMBER (not a string)" keeps the no-direction property while
#: removing the type trap.
_PREDICTION_EXAMPLE_WITHOUT_IDENTITY = """  "falsifiable_prediction": {
    "metric": "What to measure, e.g. 'file_vector[17]'",
    "current_value": "Use an observed baseline number, or null if unavailable; never invent SOTA",
    "predicted_value": "REPLACE WITH A NUMBER (not a string): what the new model should achieve. This run declares no metric direction, so do not assume which way is better — state the direction you intend in `rationale`",
    "threshold_for_refutation": "REPLACE WITH A NUMBER (not a string): the value on the REFUTED side of current_value",
    "rationale": "Why this specific predicted value, and in which direction."
  },"""


def render_metric_context_block(evidence: ProposerInterpretationEvidence) -> str:
    """D1 — state the run's metric and which direction is better. Once.

    Step 10 / P3 C4 (design §4.5). Before this block, NO proposer prompt stated
    the run's metric identity or its direction anywhere, while the comparison
    stage asked the model to pick the SOTA and the causal stage asked it to
    author a numeric prediction. Under a lower-is-better metric the model had to
    GUESS, and every worked example it could see was higher-is-better.

    The direction WORDS come from the existing authority chain
    (``render_metric_identity_line`` -> ``render_metric_direction_words`` ->
    ``MetricOrder.direction_words``) and never from a literal spelled here.
    That is not stylistic: the direction vocabulary may be interpreted in
    exactly ONE module, and a renderer deciding "higher"/"lower" itself is the
    pattern Step 09 removed and Step 06's C5 guard fails on.

    Absent identity renders the canonical ``METRIC_IDENTITY_UNAVAILABLE``
    phrase and an explicit instruction to use no direction language and make no
    ranking claim — the named absence, rendered rather than defaulted.
    """
    from agent.prompt_templates.tuner.rendering import (
        render_metric_direction_words,
        render_metric_identity_line,
    )
    from execute_tools.evaluation_metric import METRIC_IDENTITY_UNAVAILABLE

    identity = evidence.metric_identity
    if identity is None:
        return (
            "## Metric context\n"
            "\n"
            f"This run's metric identity is UNAVAILABLE ({METRIC_IDENTITY_UNAVAILABLE}).\n"
            "\n"
            "- Do NOT assume which direction is better. Use no directional\n"
            "  language about the scores you are shown.\n"
            "- Do NOT claim any model is best, strongest, state-of-the-art or\n"
            "  worst: without a declared direction nothing has been ranked.\n"
            "- Read the raw values, and say plainly when a comparison cannot be\n"
            "  made on this evidence.\n"
            "\n"
        )

    words = render_metric_direction_words(identity)
    return (
        "## Metric context\n"
        "\n"
        f"Every score in this prompt is on the {render_metric_identity_line(identity)}.\n"
        "\n"
        f"- Better means **{words['comparative']}**; worse means "
        f"{words['antonym']}. The task is to {words['verb']} it.\n"
        "- Read every comparison, ranking and state-of-the-art judgement on\n"
        "  that direction, not on which number looks larger.\n"
        f"- A prediction that improves on the current value must move "
        f"{words['comparative']}.\n"
        # The D2 aligning sentence (design §4.5): state what
        # `threshold_for_refutation` MEANS, in this run's direction, and name
        # the wrong reading explicitly. Gate 1 on candidate `b94b2da1`
        # observed a real model author `current 0.0172 -> predicted 0.0159,
        # threshold 0.0170` — the prediction moved correctly but the threshold
        # landed BETWEEN the prediction and the current value, i.e. read as a
        # "minimum improvement bar". Three numbers in an example do not teach a
        # semantic; the words have to.
        f"- `threshold_for_refutation` marks the REFUTED side of "
        f"`current_value`: put it on the\n"
        f"  **{words['antonym']}** side of `current_value`, NOT between your "
        f"prediction and the\n"
        f"  current value. A result that reaches the threshold means the "
        f"hypothesis was\n"
        f"  WRONG; a result {words['comparative']} than `current_value` is "
        f"what confirms it.\n"
        "\n"
    )


def render_falsifiable_prediction_example(
    evidence: ProposerInterpretationEvidence,
) -> str:
    """D2 — the authoring example, rendered on the run's declared direction.

    Step 10 / P3 C4 (design §4.5). The template used to hard-code
    ``current_value: 1.5, predicted_value: 2.5, threshold_for_refutation: 1.2``
    — an upward move with the refutation threshold BELOW current. That is
    correct under ``higher`` and inverted under ``lower``, and a
    pattern-matching model copies the shape it is shown. The three numbers now
    follow the declared direction:

    * ``predicted_value`` moves TOWARD BETTER;
    * ``threshold_for_refutation`` sits on the REFUTED side of
      ``current_value`` — the side a result would have to reach for the
      hypothesis to be considered wrong.

    The ``metric`` example names the RUN's metric id, which is also how the
    framework template stops carrying the ``'denoising_score'`` literal. The
    per-sample-slice form stays as a generic capability note.

    Both the direction and the arithmetic come from the existing authority:
    ``MetricOrder.toward_better`` / ``toward_worse`` compute the moves, so this
    renderer never decides which way is up.
    """
    from execute_tools.metric_order import MetricOrder

    identity = evidence.metric_identity
    if identity is None:
        return _PREDICTION_EXAMPLE_WITHOUT_IDENTITY

    order = MetricOrder(identity)
    current = 1.5
    predicted = order.toward_better(current, 1.0)
    threshold = order.toward_worse(current, 0.3)
    return (
        '  "falsifiable_prediction": {\n'
        f'    "metric": "What to measure, e.g. \'file_vector[17]\' '
        f"or '{identity.id}'\",\n"
        f'    "current_value": {current},\n'
        f'    "predicted_value": {predicted},\n'
        f'    "threshold_for_refutation": {threshold},\n'
        '    "rationale": "Why this specific predicted value."\n'
        "  },"
    )
