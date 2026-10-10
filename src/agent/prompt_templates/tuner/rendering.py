"""Owned renderers for the tuner's LLM-facing task content (Step 07 PR 07b, P2).

Design: ``docs/design/generic_framework_upgrade/step_07_tuner_policy_and_training_diagnostics/
pr_07b_tuner_policy.md`` §3.6 (the per-block rendering table) and §3.9 (the
bridge surface).

The rule, and the only rule
---------------------------
**A token renders from a landed authority, or it stays a literal with the gap
recorded.** Nothing here invents a fact. There is no new task-config field, no
"reasonable default", no derivation of a number that no shipped object
declares. Every value below traces to an object that already exists and that
something other than a prompt already depends on:

============================  =========================================
token                         authority
============================  =========================================
builtin model roster          ``MODEL_REGISTRY`` insertion order
full-scope segments           the run-bound ``DatasetConfig``
output-contract shape         the run-bound ``ModelIOContract``
focal alpha / gamma           ``LossConfig``'s field defaults
health-check name tokens      the run's EFFECTIVE health config
efficiency band percent       the tuner's ``EFFICIENCY_BAND_FRACTION``
============================  =========================================

Under TIDMAD every one of these renders **the exact bytes the template used to
carry as a literal** — that is P2's acceptance criterion, and the Step-00 PB
goldens are what prove it (they must pass UNCHANGED after this commit, with
nothing regenerated). A contrast task renders different bytes from the same
code, which is the point.

What is deliberately NOT here
-----------------------------
The prose around these tokens. The five per-model one-line descriptions, the
CH1/CH2 log-space explanation, the class-127 and PSD-amplitude health wording,
the regressor/hybrid shape sentences, the "200 segments" illustration, the
built-in loss list (whose shipped literal wraps mid-list, so rendering it as one
token would move a byte P2 may not move — see §14.3): no
landed authority owns any of them, so 07b leaves them literal and records them
as Seam-3 (task pack, Step 12) / Step-08 gaps. Rendering them would have meant
inventing a task-config field to make a prompt look complete.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agent.prompt_rendering import prompt_boundary
from agent.prompt_templates.tuner.loss_context import PlannerLossContext
from agent.schemas.execution_provenance import AUTHORITY_DESCRIPTIONS
from ml_models.models_format_sandbox import LossConfig

#: The efficiency-equivalence band, as a fraction of a run's observed score
#: range. FRAMEWORK policy with a metric-independent definition (design §3.3
#: row 4), and ONE symbol with two consumers that must never disagree: the
#: tuner's reflection context computes the band from it, and both LLM prompts
#: state it to the agent. Two literals could drift, and the agent would be
#: optimising against a rule the tuner does not apply.
#:
#: It lives HERE rather than in the tuner because the import runs one way:
#: the tuner imports these renderers, and ``agent/prompts.py`` imports the
#: percentage — a constant in the tuner would make that a cycle.
EFFICIENCY_BAND_FRACTION = 0.05

#: The same constant as the prompts state it: ``"5"``.
EFFICIENCY_BAND_PCT = f"{EFFICIENCY_BAND_FRACTION * 100:g}"


def render_builtin_model_roster(registry: dict[str, Any] | None = None) -> str:
    """``"punet | fcnet | transformer | wavenet | rnn | gated_fno"``.

    The BUILT-IN roster, in ``MODEL_REGISTRY``'s declaration order. Agent-
    generated plugins are deliberately excluded even though they live in the
    same dict at runtime: they are *proposed* architectures, and offering one
    back to the planner as a rostered choice would let the tuner reselect the
    proposer's own output as if it were a shipped baseline.

    Args:
        registry: injection point for the contrast rung. ``None`` reads the
            shipped registry.
    """
    from ml_models.models_sandbox import BUILTIN_OUTPUT_TYPES, MODEL_REGISTRY

    source = MODEL_REGISTRY if registry is None else registry
    builtins = [name for name in source if name in BUILTIN_OUTPUT_TYPES]
    return " | ".join(builtins)


def render_full_scope_segments(dataset: Any | None) -> int | None:
    """Total PSD segments a full-scope run trains on: ``num_files × segments_per_file``.

    4 000 under TIDMAD's 20 files × 200 segments. The prompts use it as the
    reference volume a sparse trial is compared against ("the baseline
    typically trains on 4000 segments"), so a task with a different topology
    must not be told TIDMAD's number.

    Step 12 / PR-12d, seam B: ``None`` in, ``None`` out. A task that declares
    no physical geometry has no such volume, and the reference sentence must
    say so rather than report a number that does not exist. TIDMAD's value is
    untouched.
    """
    if dataset is None:
        return None
    return int(dataset.num_files) * int(dataset.segments_per_file)


def render_full_scope_segments_token(full_scope_segments: int | None) -> str:
    """The prompt TOKEN for the reference volume.

    The substitution belongs to this authority rather than to
    ``llm_bridge``, which is a substituter and owns no semantics. ``"N/A"`` is
    the vocabulary this repository's prompts already use for an unavailable
    quantity (``agent/prompts.py:1434``), so nothing new is introduced.
    """
    return "N/A" if full_scope_segments is None else str(full_scope_segments)


def render_output_contract_shape(contract: Any | None) -> str | None:
    """``"[B, 256, T]"`` — the model output's shape token, or ``None``.

    ``None`` when the run has no bound Model-I/O contract (the pre-Step-03
    adapter shape). The caller omits the token rather than guessing a shape:
    this string tells the planner which loss families are legal, so a wrong
    one makes every plan it produces invalid.
    """
    if contract is None:
        return None
    return contract.output.render_shape()


def render_focal_defaults() -> tuple[str, str]:
    """``("0.5", "2.0")`` — ``LossConfig``'s shipped focal ``alpha`` / ``gamma``.

    The collapse-recovery advice tells the planner to reset to these values.
    Read from the field defaults so the advice cannot drift from what a reset
    actually produces.
    """
    from ml_models.models_format_sandbox import LossConfig

    fields = LossConfig.model_fields
    # ``str(float)`` rather than ``:g``: the prompt says ``gamma=2.0`` and
    # ``:g`` would render ``2``, which is a byte change P2 may not make.
    return (str(fields["alpha"].default), str(fields["gamma"].default))


def render_gate_name_tokens(health_config: Any) -> dict[str, str]:
    """``{check_name: check_name}`` for every check the EFFECTIVE config runs.

    The collapse advice names checks (``output_diversity``,
    ``amplitude_collapse``) whose messages the planner is told to read out of
    ``failure_reason``. A run whose effective config does not declare a check
    of that name would be advised about a signal it can never receive, so the
    caller OMITS the sentence instead (§3.6).

    Only the NAMES are owned here. The surrounding explanation — what
    class-127 mode collapse is, what a PSD amplitude collapse means — is
    TIDMAD health semantics with no generic owner until Step 08, and stays
    literal with the gap recorded.
    """
    return {check.name: check.name for gate in health_config.health_gates for check in gate.checks}


# ===========================================================================
# Step 12 / PR-12a C7 — composition-gated LLM-facing task science (D-12a-5)
# ===========================================================================
#
# The governing rule: removing TIDMAD science is not sufficient. Each block
# below was classified (design §8.9) as either (1) optional TIDMAD-only
# advice, which may disappear on a composed run, or (2) required task
# semantics, which must be REPLACED from a task-owned authority.
#
# All four legacy strings are carried VERBATIM, so an un-composed run renders
# the exact bytes the template used to carry as a literal — the same
# discipline 07b's P2 used, and what keeps the C0 legacy prompt fixtures green
# through this commit.


#: (2) required. LEGACY bytes of the planner's built-in roster block.
LEGACY_AVAILABLE_MODELS_BLOCK = """### AVAILABLE MODELS:
1. **PositionalUNet (punet)**: U-Net with positional encoding for global signal structures.
2. **FCNet (fcnet)**: Fully-connected AutoEncoder, efficient for local smoothing.
3. **TransformerModel (transformer)**: Self-attention over time steps; memory scales O(T²) — use small segmentation_size.
4. **SimpleWaveNet (wavenet)**: Dilated causal convolutions; memory-efficient.
5. **RNNSeq2Seq (rnn)**: LSTM encoder-decoder; memory grows linearly with batch_size × segmentation_size.
"""

#: (1) optional. LEGACY bytes of the planner's per-file-table protocol prose.
#: On a composed run this explains evidence the run does not have: W4 already
#: sets `reference_scores = None`, so the table itself is ALREADY absent and
#: only the prose survives — describing `raw_baseline`, `ground_truth`, a
#: global `s_max` and an `Impact_Score` ranking to a task with none of them.
LEGACY_PER_FILE_TABLE_PROTOCOL = """### PER-FILE PERFORMANCE TABLE:

Below is a comparison of your best experiment's per-file scores against two
reference columns:

- **raw_baseline**  = no denoising at all (CH1 passed through the scorer).
- **ground_truth**  = what a perfect denoiser (CH2 substituted for CH1) scores.
- **model**         = your best experiment so far.

All three are log-space under the same global s_max, so differences are
directly comparable.

- `gain vs raw > 0`   → your model is doing useful work on that file.
- `headroom vs gt`    → how far below the theoretical ceiling you are.
- `Linear_Weight`     → the file's share of the linear denominator behind the
                        aggregate scalar. Sums to 1 across sampled files.
- `Impact_Score`      → the log-scalar gain you would obtain by lifting this
                        file's `model` to its `ground_truth`. This is the
                        per-file opportunity ranking; the table is followed
                        by a secondary block re-sorted by `Impact_Score`
                        descending.

Read the table by `Impact_Score` descending — that is where the next-iter
lever is. A multi-log-unit `headroom_vs_gt` does not by itself indicate
opportunity; only `Impact_Score` does. A high-weight file at its ceiling has
zero `Impact_Score` and is not actionable. If the entire `Impact_Score`
column is small in magnitude relative to the chain's per-iter gains, this
configuration has reached the dataset ceiling.

"""


def render_available_models_block(*, composed: bool) -> str:
    """The planner's model-context block.

    Class (2) — REQUIRED semantics — but the audit found the replacement
    ALREADY PRESENT (design §8.9 / F-12a-C7-3): ``LLMBridge.plan`` renders the
    run's own architecture description into the user message as
    ``[MODEL ARCHITECTURE DESCRIPTION]``, from the description source, on both
    paths and independently of this block. So "what model am I tuning?" is
    answered elsewhere in the same prompt, and what the five built-in lines add
    to a composed run is a menu of architectures it is not using.

    The composed rendering therefore replaces them with a pointer to that
    authority rather than restating it — restating would create a second
    place the same fact is rendered, which is the shape this PR removes
    everywhere else.

    Args:
        composed: whether the run is composed. PRESENCE only (C-P56-1).
    """
    if not composed:
        return LEGACY_AVAILABLE_MODELS_BLOCK
    return (
        "### THE MODEL UNDER TUNING:\n"
        "This run tunes ONE model, supplied by the task package. Its "
        "architecture description — when the task declares one — appears in "
        "the [MODEL ARCHITECTURE DESCRIPTION] block of the user message. Do "
        "not assume a built-in architecture or its properties.\n"
    )


def render_per_file_table_protocol(*, composed: bool) -> str:
    """The planner's per-file-table reading protocol.

    Class (1) — optional TIDMAD-only advice, so the composed path renders
    NOTHING. There is no task semantics to replace: the table this prose
    explains is already withheld from composed runs by W4, so what is being
    removed is an explanation of absent evidence.
    """
    return "" if composed else LEGACY_PER_FILE_TABLE_PROTOCOL


def render_score_field_noun(*, composed: bool) -> str:
    """What to call the `denoising_score` FIELD in prose.

    F-12-5, as the audit corrected it (design §8.9 / F-12a-C7-1). The literal
    `denoising_score` is a FROZEN RECORD KEY, task-invariant and genuinely
    correct on a composed run — the LLM really does read that key out of the
    history JSON, and substituting the composed metric id would tell it to
    read a key that does not exist. What is wrong when composed is the NOUN:
    calling that field "the metric" when the metric identity is what the
    parameterized clause beside it already carries.

    Legacy renders "metric", which is TRUE for a TIDMAD run — so this is the
    accurate word on both paths rather than a compromise, and legacy prompt
    bytes do not move.
    """
    return "field" if composed else "metric"


def render_score_display_noun(*, composed: bool) -> str:
    """What to call the score in the reflector's judgement protocol.

    Class (2) for the PROTOCOL (compare against baseline and best; never call
    a negative score a failure — all task-generic) and class (1) for its
    NAMING. Only the naming is gated: "Denoising Score" is a task-specific
    name for a field every task carries.
    """
    return "score" if composed else "Denoising Score"


#: (1) optional. LEGACY bytes of the planner's `"target"` justification — the
#: half of that bullet that argues from the per-file `Impact_Score` column.
#: The STRATEGY itself (`target_files` exists and concentrates data) is
#: framework machinery and is NOT gated; only the TIDMAD evidence it cites is.
LEGACY_TARGET_STRATEGY_IMPACT_NOTE = """Useful when the per-file score table indicates a small set of
  files carries most of the next-iter improvement budget — those are the files with the
  largest `Impact_Score` for the current best model. Choosing `target_files` is a
  data-allocation decision; it should be driven by the Impact_Score column, not by
  fixed file-index labels or thresholds."""

#: (1) optional. LEGACY bytes of the planner's sampling tradeoff advice that
#: reads the same absent table.
LEGACY_SAMPLING_IMPACT_TRADEOFF = """ Consult the per-file score table below — if
`Impact_Score` is roughly uniform across files, snapshot is efficient. If a small subset
of files dominates the `Impact_Score` ranking, target those files."""

#: (1) optional. LEGACY bytes of the reflector's per-file comparison block —
#: raw baseline, ground-truth ceiling, `Linear_Weight`, `Impact_Score`.
LEGACY_PER_FILE_COMPARISON_BLOCK = """### PER-FILE COMPARISON (Impact-Aware):
The score_comparison_table below shows per-file performance against the raw
baseline and the ground-truth ceiling, alongside `Linear_Weight` (each
file's share of the linear denominator behind the aggregate scalar) and
`Impact_Score` (the log-scalar gain available if that file's `model` were
lifted to its `ground_truth`). The table is followed by a secondary block
re-sorted by `Impact_Score` descending.

Use the table to produce per-file discoveries grounded in the
`Impact_Score` ranking — e.g., "architecture X recovered most of the
high-Impact rows but left rows with the largest remaining Impact untouched"
rather than "score went up." Cite `Impact_Score` and `Linear_Weight`
together when discussing per-file bottlenecks; do not assert that a file is
permanently weak from a single round's reading or from `headroom_vs_gt`
alone. These row-level insights compound across rounds when the next
planner inherits them."""


def render_target_strategy_impact_note(*, composed: bool) -> str:
    """Class (1). Composed renders nothing: the column it argues from does
    not exist for a composed run."""
    return "" if composed else LEGACY_TARGET_STRATEGY_IMPACT_NOTE


def render_sampling_impact_tradeoff(*, composed: bool) -> str:
    """Class (1). Same table, same absence."""
    return "" if composed else LEGACY_SAMPLING_IMPACT_TRADEOFF


def render_per_file_comparison_block(*, composed: bool) -> str:
    """Class (1). The reflector's per-file reference-science block."""
    return "" if composed else LEGACY_PER_FILE_COMPARISON_BLOCK


class TunerTaskRender(BaseModel):
    """Every P2 token for one run, rendered once at run scope.

    Built by the tuner from objects it already holds — the run-bound dataset
    profile, the run-bound Model-I/O contract, the materialized effective
    health config, the built-in registries — and passed to
    :meth:`LLMBridge.plan` as ONE additive kwarg.

    Frozen and extra-forbidding: a renderer that grew a new token would have to
    declare it here, which is what keeps "the prompt says only what an
    authority owns" checkable rather than aspirational.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    loss_context: PlannerLossContext | None = None

    builtin_model_roster: str = Field(
        description="The built-in architectures, pipe-joined, in registry order."
    )
    full_scope_segments: int | None = Field(
        default=None,
        description=(
            "num_files x segments_per_file for the run's dataset, or None for "
            "a task that declares no physical partition geometry."
        ),
    )
    output_contract_shape: str | None = Field(
        default=None,
        description="The model output's shape token, or None when no contract is bound.",
    )
    focal_alpha_default: str = Field(description="LossConfig's shipped focal alpha.")
    focal_gamma_default: str = Field(description="LossConfig's shipped focal gamma.")
    gate_check_names: tuple[str, ...] = Field(
        default=(),
        description="Every check name the run's EFFECTIVE health config declares.",
    )
    efficiency_band_pct: str = Field(
        description="The efficiency-equivalence band as a percentage, e.g. '5'."
    )

    # --- Step 12 / PR-12a C7 (D-12a-5) — composition-gated task science -----
    # Rendered here for the same reason every other token is: this class is
    # where "the prompt says only what an authority owns" is checkable. A
    # composed run's gating is a rendered STRING, not a branch at the
    # assembly site, so `llm_bridge` keeps substituting tokens and never
    # learns what a composition is.
    available_models_block: str = Field(
        default=LEGACY_AVAILABLE_MODELS_BLOCK,
        description=(
            "The planner's model-context block. Legacy: the five built-in "
            "descriptions, verbatim. Composed: the run's OWN model "
            "description, or a NAMED absence — never another task's roster."
        ),
    )
    per_file_table_protocol: str = Field(
        default=LEGACY_PER_FILE_TABLE_PROTOCOL,
        description=(
            "The planner's per-file-table reading protocol. Empty on a "
            "composed run: W4 already withholds the table it explains."
        ),
    )
    score_field_noun: str = Field(
        default="metric",
        description=(
            "What to call the `denoising_score` FIELD in prose. The field "
            "name itself is a frozen record key and is NOT gated (F-12a-C7-1)."
        ),
    )
    target_strategy_impact_note: str = Field(
        default=LEGACY_TARGET_STRATEGY_IMPACT_NOTE,
        description="The planner's `target` justification that argues from `Impact_Score`.",
    )
    sampling_impact_tradeoff: str = Field(
        default=LEGACY_SAMPLING_IMPACT_TRADEOFF,
        description="The planner's sampling tradeoff advice that reads the per-file table.",
    )
    per_file_comparison_block: str = Field(
        default=LEGACY_PER_FILE_COMPARISON_BLOCK,
        description="The reflector's per-file reference-science block.",
    )
    score_display_noun: str = Field(
        default="Denoising Score",
        description=(
            "What to call the score in the reflector's judgement protocol. "
            "The protocol is task-generic; only its naming is TIDMAD's."
        ),
    )

    def has_check(self, name: str) -> bool:
        """Whether the run's effective health config declares ``name``.

        The caller uses it to decide whether a piece of collapse advice about
        that check is honest for this run.
        """
        return name in self.gate_check_names


def build_tuner_task_render(
    *,
    dataset: Any,
    model_io_contract: Any | None,
    health_config: Any,
    efficiency_band_fraction: float,
    registry: dict[str, Any] | None = None,
    composed: bool = False,
    objective: LossConfig | None = None,
) -> TunerTaskRender:
    """Assemble the run's :class:`TunerTaskRender` from its landed authorities.

    Called ONCE, at tuner run scope. Every argument is an object the tuner
    already bound for another reason; nothing is loaded or derived here that
    the run did not already establish.
    """
    loss_context = None
    if composed:
        if model_io_contract is None:
            raise ValueError(
                "Composed planner requires declared ModelIO output facts for loss offers"
            )
        loss_context = PlannerLossContext(
            output_semantic=model_io_contract.output_semantic,
            output_has_temporal_axis=model_io_contract.output_has_temporal_axis,
            objective=objective,
        )
    alpha, gamma = render_focal_defaults()
    return TunerTaskRender(
        loss_context=loss_context,
        builtin_model_roster=render_builtin_model_roster(registry),
        full_scope_segments=render_full_scope_segments(dataset),
        output_contract_shape=render_output_contract_shape(model_io_contract),
        focal_alpha_default=alpha,
        focal_gamma_default=gamma,
        gate_check_names=tuple(render_gate_name_tokens(health_config)),
        efficiency_band_pct=f"{efficiency_band_fraction * 100:g}",
        # Step 12 / PR-12a C7. `composed=False` is the default at BOTH the
        # parameter and the field, so every existing caller renders the legacy
        # bytes without knowing this exists.
        available_models_block=render_available_models_block(composed=composed),
        per_file_table_protocol=render_per_file_table_protocol(composed=composed),
        score_field_noun=render_score_field_noun(composed=composed),
        score_display_noun=render_score_display_noun(composed=composed),
        target_strategy_impact_note=render_target_strategy_impact_note(composed=composed),
        sampling_impact_tradeoff=render_sampling_impact_tradeoff(composed=composed),
        per_file_comparison_block=render_per_file_comparison_block(composed=composed),
    )


# ===========================================================================
# P3 — direction, metric identity and training-dynamics rendering
# ===========================================================================
#
# These are the ONLY intentional LLM-visible byte changes in PR 07b (§3.7).
# Everything above renders task content that was already true; everything below
# says something the prompts previously either got wrong for a non-TIDMAD
# metric ("maximize the score") or compensated for with a hand-written rule
# ("Low training loss + poor denoising score -> overfitting").
#
# The vocabulary rule, inherited from 07a: these renderers state FACTS and
# never CALIBRATED LABELS. "val 2.95 -> 2.62 (decreasing; best ep 3, +0.07
# after best)" is a fact. "overfitting" is a judgement that depends on a
# threshold nobody has declared, and 07a deliberately refused to derive one.
# A test asserts the calibrated vocabulary is absent from every render.

#: Words a diagnosis render must never contain. 07a produced facts precisely
#: so the LLM does the interpreting with the run's context in hand; a renderer
#: that pre-labels the curve removes that choice and hides the threshold it
#: silently picked.
CALIBRATED_LABELS = (
    "overfitting",
    "overfit",
    "underfitting",
    "underfit",
    "converged",
    "convergence",
    "plateau",
    "plateaued",
    "diverged",
    "divergence",
)


def render_metric_direction_words(spec: Any) -> dict[str, str]:
    """The direction-dependent words the prompts need.

    Returns ``verb`` (maximize/minimize), ``comparative`` (higher/lower) and
    ``antonym`` — so a template can say "GOOD if HIGHER … BAD if LOWER" or its
    inverse without any caller re-reading ``direction``.

    Delegates to :class:`MetricOrder`, deliberately: comparing
    ``spec.direction`` here would make this module a SECOND interpreter of the
    declaration, which is the exact pattern 07b removed from the tuner. Step
    06's C5 guard enforces it — the vocabulary is declared in the metric module
    and interpreted in the order module, and nowhere else.
    """
    from execute_tools.metric_order import MetricOrder

    return MetricOrder(spec).direction_words


def render_metric_identity_line(spec: Any) -> str:
    """``golden metric `tidmad_denoising_score` (higher is better)``.

    The metric's IDENTITY, added beside the record field name rather than
    replacing it: ``denoising_score`` is the key the LLM actually reads out of
    the history JSON, and renaming it is D1's job, not 07b's (Q-07b-3). So the
    prompt now carries both — the field it reads, and what that field measures.
    """
    words = render_metric_direction_words(spec)
    return f"golden metric `{spec.id}` ({words['comparative']} is better)"


def _fmt(value: float | None, digits: int = 2) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def render_training_dynamics_line(diagnosis: Any, objective_kind: str | None = None) -> str:
    """ONE compact line of calibration-free training facts for one experiment.

    Example (planner, with the objective family label)::

        [focal] train 2.90->2.35 (decreasing, 5 ep) · val 2.95->2.62
        (decreasing; best ep 3, +0.07 after best) · gap +0.27 (comparable)

    ``objective_kind=None`` omits the ``[...]`` label — the REFLECTOR path.
    That is not an oversight: the reflector is given the ``TrainingDiagnosis``
    and nothing else (§3.8), because its ``actual_results`` already carries
    this round's ``final_loss`` and ``loss_history`` under the run's own loss
    config, and adding a second transport for the objective family would widen
    the frozen bridge surface to restate something already present.

    Degenerate states render explicitly rather than silently: a legacy record
    with no history says so, a non-finite history says so, and a gap that is
    not comparable says why. Rendering nothing would read to the LLM as "the
    training was unremarkable".
    """
    state = getattr(diagnosis, "state", None)
    if diagnosis is None or state == "absent":
        return "training dynamics: none recorded"
    if state == "invalid":
        return "training dynamics: invalid (non-finite)"

    label = f"[{objective_kind}] " if objective_kind else ""
    parts = []

    epochs = diagnosis.epochs_completed
    epoch_note = f", {epochs} ep" if epochs is not None else ""
    truncated = ", truncated" if diagnosis.truncated else ""
    parts.append(
        f"train {_fmt(diagnosis.train_first)}->{_fmt(diagnosis.train_last)} "
        f"({diagnosis.train_trend or 'n/a'}{epoch_note}{truncated})"
    )

    if diagnosis.validation_state == "present":
        best = diagnosis.best_validation_epoch
        best_note = f"; best ep {best}" if best is not None else ""
        degradation = diagnosis.final_vs_best_validation_degradation
        # F-SCANE-2. This suppression used to be an ACCIDENT: at one epoch the
        # derivation produced a literal `0.0`, which is falsy, so the LLM
        # happened never to see a fabricated "+0.0 after best". The record and
        # the operator report had no such accident protecting them. Since the
        # ruling landed the value is `None` under
        # `validation_degradation_verdict != "observed"`, so the same falsy
        # test now expresses the intended rule and these bytes are unchanged
        # in BOTH cases (a genuine observed 0.0 still renders nothing, exactly
        # as before).
        deg_note = f", +{_fmt(degradation)} after best" if degradation else ""
        parts.append(
            f"val {_fmt(diagnosis.validation_first)}->{_fmt(diagnosis.validation_last)} "
            f"({diagnosis.validation_trend or 'n/a'}{best_note}{deg_note})"
        )
    else:
        parts.append("val not recorded")

    gap = diagnosis.train_validation_gap_final
    if gap is None:
        reason = "not comparable" if diagnosis.comparability != "established" else "unavailable"
        parts.append(f"gap n/a ({reason})")
    else:
        parts.append(f"gap {gap:+.2f} (comparable)")

    return label + " · ".join(parts)


def render_planner_dynamics_block(records: list[dict]) -> str:
    """The planner's per-experiment dynamics block, one line per record.

    Built from the SAME windowed records the history JSON is built from, but
    BEFORE the raw ``training_history`` / ``training_diagnosis`` keys are
    stripped — so the planner sees an owned SUMMARY of the trajectory while the
    raw structured payloads stay hidden at the boundary (roadmap §22.6:
    persistence is not prompt visibility). 07b never recomputes a diagnosis;
    it renders the one 07a derived and persisted.

    Records with no diagnosis still get a line, so the block's shape does not
    depend on how many rounds happened to record a history.
    """
    from agent.schemas.training_diagnosis import TrainingDiagnosis

    if not records:
        return ""
    lines = []
    for record in records:
        raw = record.get("training_diagnosis")
        diagnosis = None
        if isinstance(raw, dict):
            diagnosis = TrainingDiagnosis.model_validate(raw)
        elif raw is not None:
            diagnosis = raw
        objective_kind = (record.get("training_history") or {}).get("objective_kind")
        exp_id = record.get("exp_id", "?")
        lines.append(f"- {exp_id}: {render_training_dynamics_line(diagnosis, objective_kind)}")
    header = f"### Training dynamics (last {len(records)} experiments)"
    return header + "\n" + "\n".join(lines)


def render_reflector_dynamics_block(diagnosis: Any) -> str:
    """The reflector's block for the CURRENT attempt.

    ``objective_kind=None`` by construction — see
    :func:`render_training_dynamics_line`.
    """
    return "### TRAINING DYNAMICS (this experiment)\n  " + render_training_dynamics_line(
        diagnosis, None
    )


@prompt_boundary("tuner.execution_provenance")
def render_execution_provenance_block(provenance: Any) -> str:
    """What the framework RESOLVED after the plan was authored.

    Renders the empty string in the common case — a run whose authored plan
    survived resolution intact has nothing to correct, and its prompt bytes
    must not move. The block appears only when the planner's prose and the
    executed configuration actually DISAGREE.

    The block is worded as an authority, not as a hint. The reflector is
    reading a hypothesis written before any of these overrides happened; told
    only the values, a model reconciles the two by averaging them, and the
    witnessed defect (F15) is precisely a reflection that narrated a proposed
    loss as though it had run. So the block states which side governs, and
    names the step that overruled each field so the reflector can explain the
    difference rather than paper over it.
    """
    if provenance is None or not getattr(provenance, "events", ()):
        return ""

    lines = [
        "### RESOLVED EXECUTION AUTHORITY (governs — read this over the hypothesis)",
        "",
        "The hypothesis above is a PRE-EXECUTION PROPOSAL. The framework overruled",
        "the following value(s) after it was written, so the hypothesis does NOT",
        "describe what ran:",
        "",
    ]
    for event in provenance.events:
        described = AUTHORITY_DESCRIPTIONS.get(event.authority, event.authority)
        lines.append(
            f"  - {event.field_path}: proposed {event.proposed} "
            f"-> EXECUTED {event.executed}   [{described}]"
        )
    lines += [
        "",
        "Describe and judge what EXECUTED. Do not attribute this outcome to a",
        "proposed value that was overruled, and do not repeat such a value as if",
        "it had been used. Where the proposal and the executed configuration",
        "differ, the executed configuration is the fact.",
    ]
    return "\n".join(lines)
