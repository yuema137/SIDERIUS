# agent/prompt_templates/interpretation/rendering.py
"""Interpretation prompt construction and rendering (Step 09b).

The ResultInterpretationAgent's prompt surface — the system-prompt templates,
the user-prompt builders and the deterministic prompt-section renderers —
lives here. Step 09b C1 moved it BYTE-EXACTLY out of the node's main module
(parent design §13a: the node retains phase orchestration only; this module
owns every prompt byte).

Layering rule: this module imports SCHEMAS and framework authorities only.
It must never import the node package (``nodes.result_interpretation_agent``)
— the node calls the rendering module, never the reverse.
"""

import json
from typing import TYPE_CHECKING, Any

from agent.schemas.health_feedback import CollapseFingerprint
from agent.schemas.interpretation import ModelRunSummary
from agent.schemas.score_table import ScoreComparisonTable
from execute_tools.metric_order import MetricOrder

if TYPE_CHECKING:
    from collections.abc import Sequence

    from agent.schemas.interpretation import (
        InterpretationInput,
        InterpretationTaskBlocks,
        MetricIdentity,
        RecordFailureCounts,
        SecondaryMetricEvidence,
    )
    from agent.schemas.proposal import VocabEntry
    from agent.schemas.training_diagnosis import TrainingDiagnosis

# ---------------------------------------------------------------------------
# Phase 1 — Per-model summarization
# ---------------------------------------------------------------------------

PER_MODEL_SYSTEM_PROMPT = """\
You are a senior ML research analyst.

Your task: analyse the tuning run summary for ONE model architecture and produce a
structured analysis covering performance, per-sample behaviour where per-sample
evidence exists, data sensitivity, training dynamics, efficiency, and strategy
assessment. The research context is:

{TASK_DESCRIPTION}

You will receive:
- The model's architectural description (markdown + math)
- Best and worst golden-metric scores (trial best and formal score if available)
- Best configuration
- Score trajectory across rounds (with trial portions and model sizes)
- Per-round conclusions from the tuning agent's reflections

{TASK_GUIDANCE_SECTIONS}
Produce a JSON object with exactly these fields:

{
  "key_findings": [
    "Most important finding — concrete, references actual scores and configs",
    ...
  ],
  "bottlenecks": [
    "Root cause preventing further improvement for this specific model",
    ...
  ],
  "best_config_analysis": "Why the best config worked — what made it better than others",
  "score_trend": "How scores evolved across rounds — improving, plateauing, or erratic",
  "per_file_analysis": "Per-sample behaviour analysis. When the summary includes per-sample evidence (a score table), analyse it following the task guidance; when it does not, state explicitly that no per-sample evidence is available — never invent per-sample claims.",
  "data_sensitivity": "How sensitive the model is to data volume. Did scores improve when trial_portion increased? How large is the trial-vs-formal gap?",
  "efficiency_assessment": "Model parameter count vs performance. Is there a simpler config with similar score? Cost-performance tradeoff.",
  "strategy_assessment": "Did the agent explore effectively? Did it increase data when needed? Did it follow screening→refinement→solidification phases?"
}

Rules:
- key_findings: ranked by importance, evidence-based, reference actual values
- bottlenecks: root causes (e.g. 'architecture capacity ceiling'), not symptoms
- best_config_analysis: be specific about which hyperparameters mattered most
- score_trend: identify whether the model has saturated or still has room to improve
- per_file_analysis: follow the task guidance when per-sample evidence is present; otherwise state its absence
- data_sensitivity: reference the training data volume and trial_portion changes across rounds
- efficiency_assessment: reference model_params and training times if available
- strategy_assessment: comment on whether the agent's exploration strategy was effective
- Output only the JSON object — no preamble, no commentary, no markdown
"""


#: Framework-owned section headers for the task-guidance splice (Step 09b C2,
#: parent §13 ¶3). The KEY SET is the framework's protocol — a task supplies
#: VALUES for these four names and nothing else; growth is a framework
#: decision, never a per-task extension.
_TASK_SECTION_HEADERS = {
    "evidence_reading": "Task evidence guidance",
    "per_model_guidance": "Task analysis guidance (per-model)",
    "synthesis_guidance": "Task synthesis guidance",
    "prediction_guidance": "Task prediction guidance",
}

#: Where each section renders (framework-owned placement, frozen 09b §4.1):
#: evidence_reading appears in BOTH phase system prompts; per-model guidance
#: only in Phase 1; synthesis + prediction guidance only in Phase 2.
_PER_MODEL_SECTIONS = ("evidence_reading", "per_model_guidance")
_SYNTHESIS_SECTIONS = ("evidence_reading", "synthesis_guidance", "prediction_guidance")


def _render_task_sections(blocks: "InterpretationTaskBlocks | None", names: tuple[str, ...]) -> str:
    """The framework-owned splice: selected sections, in framework order.

    An ABSENT section renders NOTHING — no header, no bytes (absence of
    guidance is legal, frozen 09b §4.1). Present prose is preserved verbatim
    except for outer-edge whitespace, which the splice normalises so every
    section is framed identically regardless of how the declaration file's
    block scalars terminate.
    """
    if blocks is None:
        return ""
    parts: list[str] = []
    for name in names:
        content: str | None = getattr(blocks, name)
        if content is None:
            continue
        parts.append(f"### {_TASK_SECTION_HEADERS[name]}\n\n{content.strip()}\n\n")
    return "".join(parts)


def _build_per_model_system_prompt(inp: "InterpretationInput") -> str:
    """Assemble the Phase-1 system prompt: framework template + task values.

    Substitutes the ``{TASK_DESCRIPTION}`` placeholder from
    ``inp.task_description`` (T4b — see
    docs/design/enable_global_task_config.md § Commit T4) and splices the
    caller-supplied ``inp.task_blocks`` sections (Step 09b C2:
    ``evidence_reading`` + ``per_model_guidance``) at the framework's
    ``{TASK_GUIDANCE_SECTIONS}`` slot. ``task_blocks=None`` renders the bare
    task-free template — no section, no header.

    Production callers always populate ``inp.task_description`` via the
    workflow; test fixtures may leave it at the default ``""``, in which case
    the placeholder collapses to ``""`` (acceptable for tests, never reached
    in production).
    """
    rendered = PER_MODEL_SYSTEM_PROMPT.replace("{TASK_DESCRIPTION}", inp.task_description)
    rendered = rendered.replace(
        "{TASK_GUIDANCE_SECTIONS}\n",
        _render_task_sections(inp.task_blocks, _PER_MODEL_SECTIONS),
    )
    # V19 PR 3 §3.6 item 3 (flag-gated): instruction block for handling the
    # structured HealthGate evidence. OFF ⇒ byte-identical to the flag-less
    # assembly (golden-parity tested).
    if inp.enable_structured_health_feedback:
        rendered += HEALTH_FEEDBACK_SYSTEM_INSTRUCTIONS
    return rendered


HEALTH_FEEDBACK_SYSTEM_INSTRUCTIONS = """

### Structured HealthGate evidence (additional rules)

The user prompt may contain a "HealthGate summary" section and per-round
GATE labels. These are DETERMINISTIC facts from the health-gate system,
not opinions. Rules:

- Preserve every collapse fingerprint VERBATIM in your findings — the
  exact signature string with its numbers (e.g.
  "sample_dispersion_floor_blocking:dispersion=0.0"). Never paraphrase
  the numbers away.
- A high raw score on a round with invalid gate evidence is an INVALID
  result. Report it as a failure mode, never as an achievement.
- Rounds marked "unknown" or with legacy/no gate evidence carry NO
  health verdict. Do not describe them as healthy or collapsed.
- Attribute each fingerprint to exactly the model and rounds it came
  from. Never transfer evidence between models."""


def _render_health_summary_section(summary: ModelRunSummary, *, order: MetricOrder) -> list[str]:
    """Deterministic ``### HealthGate summary`` body (V19 PR 3 §3.6 item 2).

    Reads ONLY the ``round_health`` data — never LLM prose. Returns [] when
    every round is legacy/unknown with nothing to report, so the caller can
    skip the header entirely.

    ``order`` (Step 09a C3) picks the BEST-SCORING round whose recording
    diagnostics are rendered. That selection is a direction question: under a
    lower-is-better metric the old ``s > best_score`` literal would surface the
    WORST round's diagnostics while calling them the best round's.
    """
    counts = {"valid": 0, "invalid": 0, "unknown": 0}
    fingerprint_rounds: dict[str, list[int]] = {}
    fingerprint_by_sig: dict[str, CollapseFingerprint] = {}
    for i, health in enumerate(summary.round_health):
        counts[str(health.health_validity)] += 1
        if health.fingerprint is not None:
            sig = health.fingerprint.signature
            fingerprint_rounds.setdefault(sig, []).append(i + 1)
            fingerprint_by_sig.setdefault(sig, health.fingerprint)

    lines = [
        f"Round validity: {counts['valid']} valid, {counts['invalid']} invalid, "
        f"{counts['unknown']} unknown (of {len(summary.round_health)})"
    ]
    if fingerprint_rounds:
        lines.append(
            "Distinct collapse fingerprints (deterministic, from persisted gate evidence):"
        )
        for sig in sorted(fingerprint_rounds):
            rounds = fingerprint_rounds[sig]
            fp = fingerprint_by_sig[sig]
            lines.append(
                f"  - {sig}  (x{len(rounds)}, round{'s' if len(rounds) > 1 else ''} "
                f"{', '.join(str(r) for r in rounds)}) — {fp.human_readable}"
            )

    # Recording-only diagnostics for the best-scoring round, if any round
    # carries them (e.g. pearson_dispersion — the misleading-high-score
    # discriminator, design §2.4).
    best_idx = None
    best_score = None
    for i, s in enumerate(summary.round_scores):
        if s is not None and (best_score is None or order.is_better(s, best_score)):
            best_idx, best_score = i, s
    if best_idx is not None and best_idx < len(summary.round_health):
        recording = {
            k: v
            for outcome in summary.round_health[best_idx].gate_outcomes
            if outcome.gate_name.endswith("_recording")
            for k, v in outcome.key_metrics.items()
        }
        if recording:
            rendered = ", ".join(f"{k}={v}" for k, v in sorted(recording.items()))
            lines.append(f"Best-round recording diagnostics: {rendered}")

    if counts["invalid"] == 0 and counts["valid"] == 0 and not fingerprint_rounds:
        # All-unknown/legacy with no fingerprints: nothing informative.
        return []
    return lines


def render_metric_identity(identity: "MetricIdentity | None") -> str | None:
    """``golden metric `<id>` (<higher|lower> is better)`` — or None.

    Step 09b C3. The DIRECTION WORDS come from the existing 07b authority
    (:func:`agent.prompt_templates.tuner.rendering.render_metric_direction_words`,
    which asks `MetricOrder`), never from a literal spelled here: the
    direction vocabulary is interpreted in exactly one module, and a second
    renderer deciding "higher"/"lower" itself is the pattern Step 09 removed.

    The 07b line renderer itself takes a ``MetricSpec`` and reads ``spec.id``;
    a ``MetricIdentity`` names that field ``metric_id`` (it is the RECORD-borne
    identity, not the declaration), so this composes the same sentence around
    the shared direction words rather than adapting one carrier into the other.

    ``None`` (a summary carrying no record-borne identity — pre-Step-06
    outputs) renders NOTHING: the run-level identity line still states the
    metric, so a per-model absence is silent rather than fabricated.
    """
    if identity is None:
        return None
    from agent.prompt_templates.tuner.rendering import render_metric_direction_words

    words = render_metric_direction_words(identity)
    return f"golden metric `{identity.metric_id}` ({words['comparative']} is better)"


def render_interpretation_diagnosis_lines(
    best: "TrainingDiagnosis | None", formal: "TrainingDiagnosis | None"
) -> list[str]:
    """Up to two role-labelled training-dynamics lines for one model.

    Step 09b C3. The LINE GRAMMAR is 07b's
    (:func:`agent.prompt_templates.tuner.rendering.render_training_dynamics_line`),
    reused verbatim — including its explicit degenerate renderings ("training
    dynamics: none recorded" / "invalid (non-finite)"), because a silent
    omission reads to the model as "training was unremarkable".

    The two roles are rendered SEPARATELY on purpose (09a C6): a best trial
    round and the formal round are different experiments, and folding them
    would attribute one experiment's dynamics to the other. A role whose
    diagnosis is absent contributes NO line — the run may legitimately have
    no formal round — but a PRESENT diagnosis always renders, degenerate or
    not.

    ``objective_kind`` is deliberately not passed: the interpreter receives
    the projected diagnosis alone (no `training_history` reaches the
    summary), which is exactly the reflector's situation in 07b.
    """
    from agent.prompt_templates.tuner.rendering import render_training_dynamics_line

    lines: list[str] = []
    for role, diagnosis in (("best", best), ("formal", formal)):
        if diagnosis is None:
            continue
        lines.append(f"  {role}: {render_training_dynamics_line(diagnosis, None)}")
    return lines


def render_secondary_metrics(secondaries: "Sequence[SecondaryMetricEvidence]") -> list[str]:
    """One line per DECLARED secondary metric, in declaration order.

    Step 09b C3 (parent §4b; Q-09-7 = B). Secondaries are OBSERVATIONAL: each
    line states the metric's OWN identity and OWN direction — asked of its own
    `MetricOrder`, never of the run's — and none of them is ever compared,
    ranked or aggregated here.

    The three states are rendered as three DIFFERENT statements, because they
    are three different facts:

    * ``scored``      -> the value;
    * ``refused``     -> the refusal's contract id, verbatim and unparsed;
    * ``unavailable`` -> a NAMED ABSENCE ("declared, not evaluated this run").

    An empty collection renders NOTHING (production today — Step 10 owns the
    upstream transport), so no header is emitted for a task that declares no
    secondary metric.
    """
    from agent.prompt_templates.tuner.rendering import render_metric_direction_words

    lines: list[str] = []
    for evidence in secondaries:
        words = render_metric_direction_words(evidence.spec)
        head = f"  `{evidence.spec.id}` ({words['comparative']} is better): "
        status = evidence.status
        if status == "scored":
            assert evidence.result is not None  # narrowed by `status`
            lines.append(f"{head}{evidence.result.scalar}")
        elif status == "refused":
            assert evidence.refusal is not None  # narrowed by `status`
            lines.append(f"{head}not scoreable ({evidence.refusal.verdict.contract_id})")
        else:
            lines.append(f"{head}declared, not evaluated this run")
    return lines


def render_prediction_track_record(
    *,
    legacy_history: dict[str, int] | None,
    outcomes_by_semantics: dict[str, dict[str, int]] | None,
    legacy_gain: float | None,
    gain_by_semantics: dict[str, float] | None,
    scientific_accuracy: dict[str, float] | None,
) -> list[str]:
    """The prediction track record, VERSION-LABELLED and version-pure.

    Step 09b C4 — the ONE authority both the interpreter's synthesis prompt
    and the proposer's reasoning prompt render through, so the two consumers
    cannot drift into two different readings of the same pools.

    09a split prediction accounting into two incommensurable populations: the
    frozen ``legacy_v1`` pool (produced by the pre-correction band, which was
    direction-blind and sign-degenerate) and the live
    ``metric_order_signsafe_v2`` pool. This renderer never pools them and
    never labels one with the other's name. In particular the pre-09b
    proposer rendering paired v2 FRACTIONS with the v1 DENOMINATOR — the
    consequence Q-09a-3 declared and deferred here; the N below always comes
    from the pool whose fractions are being shown.

    Four shapes (frozen 09b §9):

    * **v2-only**    -> accuracy with its own N + the v2 gain, both labelled;
    * **legacy-only** -> NO percentages (an absent hit-rate is not a zero
      one) — one line stating the legacy pool size and that it is not
      comparable, plus the legacy gain when non-zero;
    * **mixed**      -> the v2 lines PLUS the legacy line, two labels;
    * **empty**      -> nothing at all (no header for a chain with no
      comparable prediction yet).

    ``unevaluated`` needs no branch here: 09a puts it in NEITHER pool, so it
    can never inflate an N or be read as a partial success.
    """
    from agent.schemas.interpretation import (
        COMPARABLE_OUTCOMES,
        PREDICTION_SEMANTICS_LEGACY_V1,
        PREDICTION_SEMANTICS_SIGNSAFE_V2,
    )

    legacy_history = legacy_history or {}
    outcomes_by_semantics = outcomes_by_semantics or {}
    gain_by_semantics = gain_by_semantics or {}

    # Both N's count the COMPARABLE outcomes only, by construction rather than
    # by trusting the incoming dict. 09a never writes a non-comparable key
    # into either pool, but the rendering this replaced summed
    # `pred_hist.values()` unfiltered — so an `unevaluated` key appearing
    # upstream would have silently inflated the denominator of a hit-rate.
    # A number the LLM reads as "how many predictions were judged" must not
    # depend on that.
    def _comparable_total(pool: dict[str, int]) -> int:
        return sum(pool.get(outcome, 0) for outcome in COMPARABLE_OUTCOMES)

    v2_total = _comparable_total(outcomes_by_semantics.get(PREDICTION_SEMANTICS_SIGNSAFE_V2, {}))
    legacy_total = _comparable_total(legacy_history)
    v2_gain = gain_by_semantics.get(PREDICTION_SEMANTICS_SIGNSAFE_V2, 0.0)

    lines: list[str] = []
    if v2_total and scientific_accuracy is not None:
        confirmed = scientific_accuracy.get("confirmed", 0.0) * 100
        partial = scientific_accuracy.get("partial", 0.0) * 100
        refuted = scientific_accuracy.get("refuted", 0.0) * 100
        lines.append(
            f"  Scientific accuracy ({PREDICTION_SEMANTICS_SIGNSAFE_V2}, N={v2_total}) : "
            f"confirmed={confirmed:.0f}%  partial={partial:.0f}%  refuted={refuted:.0f}%"
        )
        lines.append(
            f"  Cumulative information gain ({PREDICTION_SEMANTICS_SIGNSAFE_V2}) : {v2_gain:.3f}"
        )
    if legacy_total:
        lines.append(
            f"  Earlier predictions ({PREDICTION_SEMANTICS_LEGACY_V1}) : {legacy_total} "
            "outcome(s) recorded under pre-correction semantics — NOT comparable "
            "with the statistics above and not pooled into them"
        )
        if legacy_gain:
            lines.append(
                f"  Cumulative information gain ({PREDICTION_SEMANTICS_LEGACY_V1}) : "
                f"{legacy_gain:.3f}"
            )
    return lines


def render_failure_counts(counts: "RecordFailureCounts | None") -> list[str]:
    """What went wrong across one model's records, from EXISTING vocabularies.

    Step 09b C3 (parent §5). Every key comes from an authority that already
    owns it — `ExperimentRecord.status`, `TrainingDiagnosis.state`,
    `ValidationState`, `NotScoreableResult`'s contract ids, Health
    `gate_action` / `RoundHealth.provenance`. No new failure taxonomy is
    introduced, and an unknown FUTURE key renders verbatim under its own name
    because these are open dicts, not enums.

    Zero-valued and empty groups are omitted (a zero count is not evidence);
    ``None`` renders nothing at all — a cached model that carries no stored
    counts is ABSENT, never reported as "no failures".
    """
    if counts is None:
        return []

    def _group(label: str, mapping: dict[str, int]) -> str | None:
        present = {k: v for k, v in mapping.items() if v}
        if not present:
            return None
        rendered = ", ".join(f"{k}={v}" for k, v in sorted(present.items()))
        return f"  {label}: {rendered}"

    lines: list[str] = [f"  records: {counts.records_total}"]
    for label, mapping in (
        ("status", counts.status_counts),
        ("training diagnosis", counts.diagnosis_state_counts),
        ("validation", counts.validation_state_counts),
        ("gate actions", counts.gate_action_counts),
        ("health provenance", counts.health_provenance_counts),
    ):
        line = _group(label, mapping)
        if line is not None:
            lines.append(line)
    if counts.metric_refusal_count:
        refusals = ", ".join(f"{k}={v}" for k, v in sorted(counts.refusal_contract_ids.items()))
        suffix = f" ({refusals})" if refusals else ""
        lines.append(f"  metric refusals: {counts.metric_refusal_count}{suffix}")
    return lines


def _build_per_model_prompt(
    summary: ModelRunSummary,
    description: str | None,
    expert_advice_str: str = "",
    human_advice: str | None = None,
    *,
    structured_health_feedback: bool = False,
    order: MetricOrder | None = None,
) -> str:
    """Build the user prompt for a single model's summarization.

    ``structured_health_feedback`` (V19 PR 3 §3.6) gates the structured
    HealthGate additions — the trajectory gate labels and the
    ``### HealthGate summary`` section. OFF (default): output is
    byte-identical to the pre-PR3 prompt, proven by golden-file equality
    in ``test_health_prompt_parity.py`` — every PR 3 addition below must
    stay behind this flag.

    ``order`` (Step 09a C3) is needed ONLY by that flag-ON section, which
    picks a best-scoring round. It therefore keeps a ``None`` default so every
    flag-OFF caller and every prompt golden is untouched — and raises when the
    flag is ON without it, rather than rendering a round chosen by an assumed
    direction.
    """
    if structured_health_feedback and order is None:
        raise ValueError(
            "structured_health_feedback=True renders the best-scoring round's "
            "diagnostics, which requires the run's MetricOrder. Pass order=; the "
            "direction is never assumed."
        )
    lines = [
        f"## Model: {summary.model_type}",
        f"Run: {summary.run_name} | Status: {summary.status} | Rounds: {summary.completed_rounds}",
    ]
    # Step 09b C3 — what the scores below ARE and which way is better, stated
    # beside the D1 field labels rather than replacing them (the 07b Q-07b-3
    # precedent: the LLM reads `denoising_score` out of the record, and the
    # identity line says what that field measures).
    identity_line = render_metric_identity(summary.metric_identity)
    if identity_line is not None:
        lines.append(f"Metric               : {identity_line}")
    lines += [
        f"Raw best score       : {summary.best_denoising_score} "
        f"(health={summary.best_raw_health_validity})",
        f"Best valid score     : {summary.best_valid_denoising_score}",
        f"Worst denoising score: {summary.worst_denoising_score}",
    ]

    # Formal score (if available and distinct from best)
    if summary.formal_score is not None:
        lines.append(f"Formal round score   : {summary.formal_score}")

    # F-SCANE-4 — the ONE per-model headline that is BOTH HealthGate-valid AND
    # formal. Every other number above is mixed on one axis or the other:
    # `Raw best` and `Best valid` may come from a trial round, `Formal round
    # score` may come from a health-INVALID record. Before this line
    # `ModelRunSummary.best_valid_formal_score` had no production consumer past
    # its own construction, so the honest headline was persisted and rendered
    # nowhere while the mixed ones were rendered to the model.
    #
    # The ABSENCE is rendered too, and deliberately: "this model produced no
    # HealthGate-valid formal result" is the fact that matters most when it
    # holds, and omitting the line lets the mixed numbers above stand
    # unqualified — which is the shape of the defect, not a tidier prompt.
    if summary.best_valid_formal_score is not None:
        lines.append(f"Best valid formal    : {summary.best_valid_formal_score}")
    else:
        lines.append(
            "Best valid formal    : NONE — this model produced no "
            "HealthGate-valid formal result; every score above is from a "
            "trial round, a health-invalid record, or both."
        )

    # Model efficiency
    if summary.best_model_params is not None:
        lines.append(f"Best model params    : {summary.best_model_params:,}")

    # Data volume context. The label is the schema-derived record vocabulary
    # (`training_psd_segments`, presence-gated); the baseline-volume FACT that
    # used to ride here as a parenthetical is task science and lives in the
    # task's evidence_reading block since Step 09b C2 (design §22.2 DW-8).
    if summary.training_psd_segments is not None:
        lines.append(f"Training PSD segments: {summary.training_psd_segments}")
    if summary.eval_psd_segments is not None:
        lines.append(f"Eval PSD segments    : {summary.eval_psd_segments}")
    if summary.trial_portion is not None:
        lines.append(f"Trial portion (best) : {summary.trial_portion}")

    # Step 09b C3 — the deterministic evidence 09a projected onto the summary,
    # each family rendered by ONE authority and each section presence-gated
    # (an absent family emits no header, never a fabricated "none observed").
    diagnosis_lines = render_interpretation_diagnosis_lines(
        summary.best_training_diagnosis, summary.formal_training_diagnosis
    )
    if diagnosis_lines:
        lines += ["", "### Training dynamics", *diagnosis_lines]

    secondary_lines = render_secondary_metrics(summary.secondary_metrics)
    if secondary_lines:
        lines += [
            "",
            "### Secondary metrics (observational — never used for ranking)",
            *secondary_lines,
        ]

    failure_lines = render_failure_counts(summary.failure_counts)
    if failure_lines:
        lines += ["", "### Record outcomes", *failure_lines]

    if description:
        lines += ["", "### Architecture Description", description]
    lines += [
        "",
        "### Best Config",
        json.dumps(summary.best_config, indent=2) if summary.best_config else "none",
    ]

    # Per-file performance — rendered as the full ScoreComparisonTable
    # markdown (raw_baseline / ground_truth / model columns + subset-scoped
    # aggregates + Recovery line). Single source of truth lives on the
    # table.rendered_markdown field, produced by render_comparison_table.
    if summary.best_score_table is not None:
        lines += [
            "",
            "### Per-file performance (best experiment)",
            summary.best_score_table.rendered_markdown,
        ]

    if summary.formal_score_table is not None:
        lines += [
            "",
            "### Per-file performance (formal round — definitive)",
            summary.formal_score_table.rendered_markdown,
        ]
    elif summary.formal_file_vector is not None:
        # F-SCANE-4 — `formal_file_vector` is declared "Definitive per-file
        # performance" and had NO consumer of any kind, while the MIXED
        # `best_file_vector` was consumed. Its enriched twin above covers the
        # case where one exists; the enriched table is built from TIDMAD
        # reference science that a COMPOSED run deliberately omits
        # (F-12e-UX-7), so on those runs the definitive per-sample evidence
        # existed on the summary and reached nothing at all. Rendered as the
        # raw vector, and only where the richer view is genuinely absent.
        lines += [
            "",
            "### Per-sample performance (formal round — definitive, no enriched table)",
            json.dumps(summary.formal_file_vector),
        ]

    # Score trajectory with per-round trial portions and model params
    lines += ["", "### Score Trajectory (chronological)"]

    n_rounds = len(summary.round_scores)
    for i in range(n_rounds):
        score = summary.round_scores[i] if i < len(summary.round_scores) else None
        conclusion = summary.round_conclusions[i] if i < len(summary.round_conclusions) else ""
        trial_p = (
            summary.round_trial_portions[i]
            if summary.round_trial_portions and i < len(summary.round_trial_portions)
            else None
        )
        params = (
            summary.round_model_params[i]
            if summary.round_model_params and i < len(summary.round_model_params)
            else None
        )

        score_str = f"{score:.4f}" if score is not None else "skipped"
        extras = []
        if trial_p is not None:
            extras.append(f"portion={trial_p}")
        if params is not None:
            extras.append(f"params={params:,}")
        extra_str = f" [{', '.join(extras)}]" if extras else ""

        # V19 PR 3 §3.6 item 1 (flag-gated): label gate-invalidated rounds
        # with the resolved action and the deterministic collapse identity,
        # instead of the ambiguous bare "skipped".
        gate_str = ""
        if structured_health_feedback and i < len(summary.round_health):
            health = summary.round_health[i]
            if health.gate_action is not None and health.gate_action != "continue":
                cause = (
                    health.fingerprint.signature
                    if health.fingerprint is not None
                    else (health.failure_reason or "no persisted gate detail")
                )
                if score is None:
                    score_str = "invalidated"
                gate_str = f" [GATE {health.gate_action} — {cause}]"

        lines.append(f"  Round {i + 1}: score={score_str}{extra_str}{gate_str} — {conclusion}")

    # V19 PR 3 §3.6 item 2 (flag-gated): per-model HealthGate summary —
    # validity counts, distinct fingerprints with occurrence counts and
    # round indices, and recording-only diagnostics for the best round.
    # Rendered ONLY when there is something to say (no empty headers).
    # `order is not None` is guaranteed by the guard at the top of this
    # function whenever the flag is on; restating it here is what lets a type
    # checker see the narrowing, and it can never change behaviour.
    if structured_health_feedback and order is not None and summary.round_health:
        health_lines = _render_health_summary_section(summary, order=order)
        if health_lines:
            lines += ["", "### HealthGate summary", *health_lines]

    if expert_advice_str:
        lines += [
            "",
            "---",
            "## Expert Guidance",
            expert_advice_str,
        ]

    if human_advice:
        lines += [
            "",
            "---",
            "## Human Guidance (highest priority — overrides expert advice)",
            human_advice,
        ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Phase 2 — Cross-model synthesis
# ---------------------------------------------------------------------------

SYNTHESIS_SYSTEM_PROMPT = """\
You are a senior ML research analyst.

Your task: read structured summaries of multiple model architectures and produce a
cross-model interpretation that identifies the overall state of the research and
motivates the next step. The research context is:

{TASK_DESCRIPTION}

You will receive:
- Per-model summaries (key findings, bottlenecks, config analysis, score trends,
  per-file analysis, data sensitivity, efficiency, strategy assessment)
- Per-model best and worst scores
- Per-model parameter counts and training data volumes
- Overall best score and the config that produced it
- Established discoveries from previous iterations (if any) — empirical findings
  already confirmed by past experiments. Build on these, confirm or contradict them.

{TASK_GUIDANCE_SECTIONS}
Produce a JSON object with exactly these fields:

{
  "key_findings": [
    "Cross-model finding #1 — most important, compares models, references scores",
    ...
  ],
  "bottlenecks": [
    "Cross-model root cause #1 — what is fundamentally limiting ALL current models",
    ...
  ],
  "per_file_comparison": "Per-sample comparison across models. When per-sample evidence is present, follow the task guidance; when it is not, state explicitly that no per-sample evidence is available — never invent per-sample claims.",
  "efficiency_comparison": "Compare model sizes (parameter counts) against scores. Identify the best score-per-parameter architecture.",
  "take_home_message": "One sentence: the single most critical insight that motivates the next step."
}

Rules:
- key_findings: ranked by importance, MUST compare across models, reference actual scores
- bottlenecks: focus on fundamental limitations shared across architectures, not per-model issues
- per_file_comparison: follow the task guidance when per-sample evidence is present; otherwise state its absence
- efficiency_comparison: reference actual parameter counts and scores
- take_home_message: exactly one sentence
- Do not repeat per-model findings verbatim — synthesise and draw cross-model conclusions
- Output only the JSON object — no preamble, no commentary, no markdown
"""


# Narrative fields that, post-Commit-6.3 consolidation, are stored as
# ConsolidatedNarrative dicts `{"latest": str, "history": [...]}` instead of
# bare strings. The synthesis prompt builder still expects bare strings.
_NARRATIVE_FIELDS_FOR_PROMPT = (
    "best_config_analysis",
    "score_trend",
    "per_file_analysis",
    "data_sensitivity",
    "efficiency_assessment",
    "strategy_assessment",
)
# List fields that, post-Commit-6.3, are stored as list[ConsolidatedFinding]
# dicts instead of list[str].
_LIST_FIELDS_FOR_PROMPT = ("key_findings", "bottlenecks")


def _flatten_entry_for_prompt(entry: dict[str, Any]) -> dict[str, Any]:
    """Flatten a (possibly modern-shape) cache entry into the legacy display
    shape the synthesis prompt builder expects.

    Why: post-Commit-6.3 active cache entries hold ConsolidatedFinding dicts
    and ConsolidatedNarrative dicts. The synthesis builder reads narratives
    as bare strings and findings as list-of-strings. This helper bridges the
    two shapes without touching the builder — cache-miss (legacy flat) entries
    pass through unchanged.
    """
    flat: dict[str, Any] = {}
    for k, v in entry.items():
        if k == "_stats":
            continue
        if k in _LIST_FIELDS_FOR_PROMPT and isinstance(v, list):
            flat[k] = [
                item["statement"] if isinstance(item, dict) and "statement" in item else item
                for item in v
            ]
        elif k in _NARRATIVE_FIELDS_FOR_PROMPT and isinstance(v, dict):
            flat[k] = v.get("latest", "") or ""
        else:
            flat[k] = v
    return flat


def _build_synthesis_system_prompt(inp: "InterpretationInput") -> str:
    """Assemble the Phase-2 system prompt: framework template + task values.

    Mirrors :func:`_build_per_model_system_prompt` for the cross-model
    synthesis call site (sections spliced here: ``evidence_reading`` +
    ``synthesis_guidance`` + ``prediction_guidance``). See
    docs/design/enable_global_task_config.md § Commit T4 for the
    ``{TASK_DESCRIPTION}`` substitution contract.
    """
    rendered = SYNTHESIS_SYSTEM_PROMPT.replace("{TASK_DESCRIPTION}", inp.task_description)
    return rendered.replace(
        "{TASK_GUIDANCE_SECTIONS}\n",
        _render_task_sections(inp.task_blocks, _SYNTHESIS_SECTIONS),
    )


def _build_synthesis_prompt(
    per_model_summaries: dict[str, dict],
    per_model_best: dict[str, float | None],
    per_model_worst: dict[str, float | None],
    overall_best_score: float | None,
    overall_worst_score: float | None,
    overall_best_config: dict | None,
    per_model_best_valid: dict[str, float | None] | None = None,
    per_model_raw_best_health_validity: dict[str, str] | None = None,
    overall_best_valid_score: float | None = None,
    per_model_score_tables: dict[str, ScoreComparisonTable] | None = None,
    per_model_params: dict[str, int] | None = None,
    per_model_training_segments: dict[str, int] | None = None,
    expert_advice_str: str = "",
    human_advice: str | None = None,
    runtime_vocab: list | None = None,
    per_model_formal: dict[str, float | None] | None = None,
    per_model_formal_excluded: dict[str, str] | None = None,
    vocab_diversity_ratio: float | None = None,
    cumulative_information_gain: float | None = None,
    compressed_model_types: set[str] | None = None,
    workspace: str | None = None,
    metric_identity: "MetricIdentity | None" = None,
    prediction_outcomes_history: dict[str, int] | None = None,
    prediction_outcomes_by_semantics: dict[str, dict[str, int]] | None = None,
    cumulative_information_gain_by_semantics: dict[str, float] | None = None,
    scientific_accuracy: dict[str, float] | None = None,
) -> str:
    """Build the user prompt for cross-model synthesis.

    ``compressed_model_types`` (Commit 6.1 — Sliding Window) marks the
    model_types whose ``per_model_summaries`` entry has been replaced
    by a deterministic one-line takeaway (output of
    ``compress_model_summary``). For those entries, this function emits
    a short 3-line block (header + best/n_rounds + takeaway) instead of
    the full multi-section LLM-text expansion, and prefixes the block
    with a single header line that points the LLM to the on-disk
    iteration record for full detail. Active models render unchanged.
    """
    per_model_best_valid = per_model_best_valid or {}
    per_model_raw_best_health_validity = per_model_raw_best_health_validity or {}
    per_model_formal_excluded = per_model_formal_excluded or {}
    compressed_model_types = compressed_model_types or set()

    lines = [
        "## Overall Performance",
    ]
    # Step 09b C3 — the run's bound metric, stated ONCE at the top of the
    # cross-model comparison: "best across all models" means nothing without
    # knowing which way is better. Echoed from the identity `run()` already
    # bound (Step 09a C2); never re-derived here.
    run_identity_line = render_metric_identity(metric_identity)
    if run_identity_line is not None:
        lines.append(f"Metric: {run_identity_line}")
    lines += [
        f"Raw best across all models   : {overall_best_score}",
        f"Best valid across all models : {overall_best_valid_score}",
        f"Worst score across all models: {overall_worst_score}",
        f"Config that produced overall best:\n{json.dumps(overall_best_config, indent=2) if overall_best_config else 'none'}",
        "",
    ]

    # Render active models first (full block), then compressed models
    # (short block) under a single header. Stable iteration order is
    # preserved within each group via the dict's insertion order.
    active_items = [
        (mt, s) for mt, s in per_model_summaries.items() if mt not in compressed_model_types
    ]
    compressed_items = [
        (mt, s) for mt, s in per_model_summaries.items() if mt in compressed_model_types
    ]

    for model_type, summary in active_items:
        lines += [
            "---",
            f"## Model: {model_type}",
            f"Raw best   : {per_model_best.get(model_type)} "
            f"(health={per_model_raw_best_health_validity.get(model_type, 'unknown')})",
            f"Best valid : {per_model_best_valid.get(model_type)}",
            f"Worst score: {per_model_worst.get(model_type)}",
        ]
        # F-SCANE-1. Two distinct facts, and the second used to be a silence.
        # The authority filter EMPTIES `per_model_formal` when every formal
        # result is non-authoritative, so gating the caveat on that dict alone
        # removed the "may be from a trial round" warning in exactly the runs
        # whose formal evidence was unusable. A withheld formal score is now a
        # NAMED ABSENCE carrying its typed reason, never an omission.
        if per_model_formal:
            formal = per_model_formal.get(model_type)
            if formal is not None and formal != per_model_best.get(model_type):
                lines.append(
                    f"Formal score: {formal}  (best_score above may be from a trial round)"
                )
        if model_type in per_model_formal_excluded:
            lines.append(
                f"Formal score: WITHHELD — this model's formal result was excluded from "
                f"the scientific aggregate ({per_model_formal_excluded[model_type]}); "
                f"the best_score above may be from a trial round and is NOT a "
                f"scientifically authoritative result."
            )
        if per_model_params and model_type in per_model_params:
            lines.append(f"Parameters : {per_model_params[model_type]:,}")
        if per_model_training_segments and model_type in per_model_training_segments:
            lines.append(f"Training PSD segments: {per_model_training_segments[model_type]}")

        lines += ["", "### Key Findings"]
        for f in summary.get("key_findings", []):
            lines.append(f"  - {f}")
        lines += ["", "### Bottlenecks"]
        for b in summary.get("bottlenecks", []):
            lines.append(f"  - {b}")
        lines += [
            "",
            "### Best Config Analysis",
            summary.get("best_config_analysis", "N/A"),
            "",
            "### Score Trend",
            summary.get("score_trend", "N/A"),
        ]
        # New per-model analysis fields
        for field in [
            "per_file_analysis",
            "data_sensitivity",
            "efficiency_assessment",
            "strategy_assessment",
        ]:
            val = summary.get(field)
            if val:
                lines += ["", f"### {field.replace('_', ' ').title()}", val]

        # Per-file performance — the full ScoreComparisonTable markdown,
        # which already includes the Impact_Score-ranked secondary block.
        # No threshold-based attention cue: opportunity is read from the
        # Impact_Score column directly.
        if per_model_score_tables and model_type in per_model_score_tables:
            table = per_model_score_tables[model_type]
            lines += [
                "",
                "### Per-file performance (best experiment)",
                table.rendered_markdown,
            ]

        lines.append("")

    # Compressed (stable) models: single header + short blocks.
    if compressed_items:
        ws_hint = (
            f"see {workspace}/iter_*/interpretation.json for full detail"
            if workspace
            else "see prior interpretation.json files for full detail"
        )
        lines += [
            "---",
            "## Stable Architectures (Compressed)",
            f"[{len(compressed_items)} older architectures compressed for "
            f"context budget — {ws_hint}]",
            "",
        ]
        for model_type, summary in compressed_items:
            # Read the field the producer actually emits.
            #
            # This was:
            #     (A or B) if summary.get("key_findings") else "(no cached takeaway)"
            # and `compress_model_summary` returns exactly
            # {model_type, best_score, n_rounds, one_line_takeaway} -- never
            # `key_findings`. The guard was therefore always falsy and EVERY
            # compressed model rendered the placeholder, discarding a
            # takeaway the producer had already computed and truncated to
            # `max_takeaway_chars`. Both sides were tested and both were
            # green; nothing tested the join.
            #
            # No legacy fallback: `compressed_items` is fed only by
            # `compress_model_summary` (one call site, result.py:1301), and
            # 40 persisted interpretation artifacts contain zero
            # compressed-shaped entries carrying `key_findings`.
            takeaway = summary.get("one_line_takeaway") or "(no cached takeaway)"
            best = summary.get("best_score", per_model_best.get(model_type))
            n_rounds = summary.get("n_rounds", 0)
            lines += [
                f"- **{model_type}** (best={best}, n_rounds={n_rounds}): {takeaway}",
            ]
        lines.append("")

    # Established discoveries from previous iterations
    if runtime_vocab:
        discoveries = [
            v
            for v in runtime_vocab
            if (v.get("kind") if isinstance(v, dict) else getattr(v, "kind", None)) == "discovery"
        ]
        if discoveries:
            lines += [
                "---",
                "## Established Discoveries (from previous iterations)",
                "These are empirically confirmed findings from past experiments.",
                "Confirm, contradict, or build on them — do not simply repeat them verbatim.",
            ]
            for v in discoveries:
                name = v.get("name") if isinstance(v, dict) else getattr(v, "name", "")
                desc = (
                    v.get("description") if isinstance(v, dict) else getattr(v, "description", "")
                )
                lines.append(f"  [{name}]: {desc}")
            lines.append("")

    if expert_advice_str:
        lines += [
            "---",
            "## Expert Guidance",
            expert_advice_str,
            "",
        ]

    if human_advice:
        lines += [
            "---",
            "## Human Guidance (highest priority — overrides expert advice)",
            human_advice,
            "",
        ]

    # Research health metrics (centrifugal forces)
    if vocab_diversity_ratio is not None or cumulative_information_gain is not None:
        lines += ["---", "## Research Health Metrics"]
        if vocab_diversity_ratio is not None:
            stagnation_note = " [LOW — explore new concepts]" if vocab_diversity_ratio < 0.1 else ""
            lines.append(
                f"Vocabulary diversity ratio: {vocab_diversity_ratio:.3f}"
                f"  (fraction of feature/capability entries still in candidate tier){stagnation_note}"
            )
        # Step 09b C4 — the prediction track record renders through the ONE
        # version-aware authority. The pre-09b line printed the LEGACY scalar
        # under a description ("boldness × confirmed") that C4 of 09a had
        # already made false, with no version label at all.
        lines += render_prediction_track_record(
            legacy_history=prediction_outcomes_history,
            outcomes_by_semantics=prediction_outcomes_by_semantics,
            legacy_gain=cumulative_information_gain,
            gain_by_semantics=cumulative_information_gain_by_semantics,
            scientific_accuracy=scientific_accuracy,
        )
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Phase C — Semantic deduplication (C.6)
# ---------------------------------------------------------------------------

DEDUP_SYSTEM_PROMPT = """\
You are a scientific vocabulary curator for an ML research system.

Your task: determine whether a newly promoted vocabulary term is a near-duplicate
or synonym of an existing canonical term of the same kind.

Two terms ARE duplicates if they describe the same architectural concept using
different wording — e.g. "gated_recurrence" and "gated_rnn" both describe
hidden-state gating in recurrent networks.

Two terms are NOT duplicates if they describe related but technically distinct
concepts — e.g. "dilated_convolution" and "causal_convolution" are related but
have different technical properties and should remain separate entries.

Judge only on technical meaning, not superficial name similarity.

Respond with a JSON object and nothing else:
{
  "is_duplicate": true or false,
  "duplicate_of": "name_of_existing_term or null",
  "rationale": "one sentence"
}
"""


def _build_dedup_prompt(entry: "VocabEntry", existing_canonicals: list) -> str:
    """Build the user prompt for one dedup judgment."""
    lines = [
        "## Candidate term (newly promoted)",
        f"Name       : {entry.name}",
        f"Kind       : {entry.kind}",
        f"Description: {entry.description}",
        "",
        f"## Existing canonical terms (kind: {entry.kind})",
    ]
    for canon in existing_canonicals:
        name = canon.name if hasattr(canon, "name") else canon.get("name", "")
        desc = canon.description if hasattr(canon, "description") else canon.get("description", "")
        lines.append(f"  - {name}: {desc}")
    lines += [
        "",
        f'Is "{entry.name}" a near-duplicate or synonym of any of the existing terms above?',
    ]
    return "\n".join(lines)
