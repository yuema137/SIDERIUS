# nodes/ml_model_proposal_agent/ml_model_proposal_agent.py
"""
ml_model_proposal_agent — Node 3 in the SIDERIUS graph.

Reads the structured interpretation from result_interpretation_agent and proposes
a new neural architecture that addresses the identified bottlenecks.

Uses a two-call chain-of-thought:
  1. Reasoning call (generate_text): free-form architectural reasoning — no JSON constraints,
     so the LLM can think deeply about bottlenecks, architecture families, and tradeoffs.
  2. Commit call (generate): given the reasoning, commit to a specific design as strict JSON
     matching ProposalOutput.

Consumed by ml_model_implementor via ``local_full_spec``
(agent/schemas/protocols/ml_model_propose_to_ml_model_impl.py), and by the
tuner via the fan-in ``local_validated_model``
(agent/schemas/protocols/ml_model_valid_to_ml_model_tune.py), which takes the
ProposalOutput beside the validator's output.

Node contract:
  run(input: ProposalInput) -> ProposalOutput
  CLI: --workspace, --run_name, --provider, --model_id
"""

import argparse
import json
import os
import uuid
from functools import lru_cache
from typing import Any

from pydantic import ValidationError

from agent.llm_bridge import LLMBridge
from agent.prompt_templates.proposal import live_loss_registry_names
from agent.prompts import _format_known_constraints_block
from agent.schemas.health_feedback import TrialValidityFeedback
from agent.schemas.hyperparam_tuning import GateExhaustionInfo
from agent.schemas.proposal import (
    CausalStageOwnedContent,
    FalsifiablePrediction,
    ProposalInput,
    ProposalOutput,
)
from agent.schemas.proposer_evidence import (
    build_proposer_evidence,
)
from agent.schemas.task_config import ForwardContract
from agent.skills.model_io_probe_skill import declared_output_tensor
from agent.utils.architectural_pattern_tagger import ARCHITECTURAL_PATTERNS
from agent.utils.proposer_preflight import estimate_proposal_time
from agent_generated._registry import CapabilityRegistry
from core.hardware_context import HardwareContext
from execute_tools.dataset_config import (
    DatasetConfig,
    declares_tidmad_topology,
    resolve_dataset_profile,
    tidmad_topology,
)
from ml_models.models_format_sandbox import (
    CLASSIFICATION_LOSSES,
    REGRESSION_LOSSES,
)
from nodes.ml_model_proposal_agent.evidence_rendering import (
    build_interpretation_summary,
    render_falsifiable_prediction_example,
    render_healthgate_evidence_block,
    render_legacy_interpretation_section,
    render_metric_context_block,
    truncate_description,
)
from nodes.proposal_helpers import evidence_order
from workflows.task_config import (
    get_task_description,
    load_task_config,
    render_forward_contract,
)

__all__ = [
    "MLModelProposalAgent",
    "ProposalContractRenderError",
    "main",
]

#: COMPATIBILITY ONLY — not part of the node's contract.
#:
#: Step 10 / P3 C2 gave this node its first PRIVATE submodule
#: (``evidence_rendering.py``), which brings it under the decomposed-node rules
#: in ``tests/unit/nodes/test_node_public_boundary.py``. Those rules exist to
#: keep "what is this node's public API" answerable once a decomposition starts
#: re-exporting moved helpers, and the interpreter node established the shape.
#:
#: The names below are re-exported from the moved rendering module because the
#: package ``__init__`` and a body of tests reach them at this path, and because
#: ``mock.patch("nodes.ml_model_proposal_agent.X")`` must keep resolving to the
#: object production actually calls.
#:
#: They are NOT documented in ml_model_proposal_agent.md, they are NOT a promise
#: to callers, and NO new production consumer may be added: import
#: ``evidence_rendering`` directly from inside the node instead. The list is
#: expected to shrink, never grow.
#:
#: Listing them here also KEEPS them alive: without a reference the linter
#: prunes the re-export.
_COMPATIBILITY_REEXPORTS = (
    build_interpretation_summary,
    render_falsifiable_prediction_example,
    render_healthgate_evidence_block,
    render_legacy_interpretation_section,
    render_metric_context_block,
    truncate_description,
)

#: The pre-P3 name for the relocated truncator, kept so existing importers and
#: ``mock.patch`` targets resolve. Compatibility scaffolding, not contract.
_truncate_description = truncate_description


# Maximum number of retries when the proposing stage produces invalid output.
# Total attempts = _MAX_PROPOSING_RETRIES + 1.
_MAX_PROPOSING_RETRIES = 2

# One retry when causal_reasoning produces a prediction below minimum_boldness.
_MAX_REASONING_RETRIES = 1

# P-1 fix (PR 3 audit §13): bounded correction retries when the causal stage's
# owned fields (inherited_components / falsifiable_prediction) fail schema
# validation. These fields are re-injected verbatim into ProposalOutput on
# every proposing structural attempt, so they can only be corrected at the
# causal stage itself. Total causal validation attempts = retries + 1.
_MAX_CAUSAL_CORRECTION_RETRIES = 2


def _applicable_dataset_constraints() -> DatasetConfig | None:
    """The dataset whose segmentation rule the proposer is actually judged by.

    C12-P-P / P1-A. Mirrors, and deliberately does NOT duplicate, the
    applicability decision of
    ``ProposalOutput._validate_baseline_segmentation_size`` (C12-P / B3): the
    PROMPT must state exactly the rule the VALIDATOR enforces. Before this, the
    prompt read the module-scope ``TIDMAD`` singleton unconditionally, so a
    composed foreign task was taught TIDMAD's PSD divisor rule — a rule B3 no
    longer applies to it.

    Applicability is a MEMBERSHIP TEST, never ``try: tidmad_topology(...)
    except ValueError``: that function raises for ABSENT sections *and* for
    sections PRESENT-BUT-MALFORMED, so catching it would silently reclassify a
    malformed TIDMAD profile as "this task declares none" and render no
    constraint at all. A malformed topology must stay loud.

    Returns:
        The applicable ``DatasetConfig``, or ``None`` when the run's profile
        declares no TIDMAD topology. ``None`` makes
        ``_format_known_constraints_block`` render ``""`` — its existing,
        documented contract — so no new channel is introduced.
    """
    profile = resolve_dataset_profile()
    if not declares_tidmad_topology(profile):
        return None
    return tidmad_topology(profile).dataset


def _active_time_budget_minutes(inp: ProposalInput) -> float | None:
    """Select the budget the pre-flight gate should check against.

    Returns ``None`` when the relevant budget is unset — the caller treats
    that as "pre-flight disabled for this proposal" rather than "budget=0".
    """
    if inp.is_trial:
        return inp.trial_time_budget_minutes
    return inp.formal_time_budget_minutes


def _live_model_registry_names(registry: CapabilityRegistry) -> list[str]:
    """Return the intersection of the capability index and the live
    ``MODEL_REGISTRY``.

    Fix for phantom Branch B model reuse. The implementor writes a
    ``CapabilityMetadata`` entry to ``agent_generated/_capability_index.json``
    *before* the code validator runs (``ml_model_implementor.py`` line 1690).
    If validation subsequently fails the entry stays in the index, so the
    next iteration's proposer sees the failed model as a Branch B reuse
    candidate. That is the v16 iter_015 loss-chain failure mode
    (``gated_dilated_tcn`` proposed in iter_009, never validated, offered
    to iter_015's proposer as reusable).

    ``ml_models.models_sandbox.MODEL_REGISTRY`` is populated only by
    ``register_model_in_memory``, which the workflow calls from
    ``_promote_model_to_global`` — after successful validation. It is the
    correct source of truth for "what has actually validated and is loadable
    right now."

    We keep the index as the source of the *metadata* (description,
    mathematical_definition) needed to render the ``{available_models_block}``
    prompt, but for the phantom-Branch-B validator context we filter to the
    intersection so ``ProposalOutput.model_validate`` only accepts
    ``model_name`` values that will actually load at training time.

    Returns:
        Sorted list of names present in both the capability index and the
        live in-memory ``MODEL_REGISTRY``. Empty list when the intersection
        is empty (fresh workspace or all indexed models are phantoms).
    """
    from ml_models.models_sandbox import MODEL_REGISTRY

    indexed = {m.name for m in registry.list(capability_type="model")}
    live = set(MODEL_REGISTRY.keys())
    return sorted(indexed & live)


@lru_cache(maxsize=1)
def _runtime_policy():
    """The one shared decision policy (C8g): resolved from the process-wide
    `shared_runtime_components()` factory, so the proposer and the tuner's
    pre-flight demonstrably decide with the same policy identity rather
    than with two independently constructed equals."""
    from core.runtime_control.estimator import shared_runtime_components

    return shared_runtime_components()[1]


def _build_preflight_advisory_note(
    num_params: int,
    estimated_minutes: float,
    factor: float,
    budget_minutes: float,
    policy_identity: str = "",
) -> str:
    """Render the labeled ADVISORY note for an over-budget static estimate.

    C1 (docs/design/runtime_estimation_and_calibration.md §8.1/§11.1):
    the static pre-flight estimate is ``static_uncalibrated`` provenance
    and carries NO blocking authority — it is recorded for observability
    only, never injected into a revision prompt, and never a reason to
    reject the proposal. The wave-1 incident showed this formula
    rejecting an 18.4M-parameter draft at a fabricated 84.64× factor.
    """
    suffix = f" [decided by {policy_identity}]" if policy_identity else ""
    return (
        f"PREFLIGHT_ADVISORY (provenance=static_uncalibrated, "
        f"confidence=low, blocking_eligible=no): the static cost model "
        f"projects {estimated_minutes:.1f} min against the "
        f"{budget_minutes:.1f} min budget (factor {factor:.2f}x) for the "
        f"estimated {num_params:,} parameters. This estimate has not been "
        f"validated on the implemented model; runtime decisions are made "
        f"from measured evidence after implementation. Do not infer a "
        f"parameter-count ceiling from this advisory." + suffix
    )


def _run_preflight_check(
    inp: ProposalInput,
    output: ProposalOutput,
) -> float | None:
    """Evaluate the static-formula pre-flight ADVISORY on a candidate
    ``output``.

    Mutates ``output`` in place: sets ``preflight_estimated_minutes`` and
    ``preflight_factor`` when the estimate runs; appends a
    ``PREFLIGHT_ADVISORY`` note when the estimate exceeds the budget;
    appends a ``PREFLIGHT_SKIPPED`` note when the LLM failed to supply a
    usable ``parameter_count_estimate``.

    C1 contract: the result is ADVISORY ONLY (static_uncalibrated
    provenance). Callers must not request proposal revision, inject
    rejection text into prompts, or otherwise derive blocking behavior
    from it. Returns the numeric ``factor`` for logging when the
    estimate ran, or ``None`` when it was skipped (budget disabled, or
    params missing / non-positive).
    """
    budget = _active_time_budget_minutes(inp)
    if budget is None:
        return None

    num_params = output.parameter_count_estimate
    if num_params is None or num_params <= 0:
        output.memo_consistency_notes.append(
            "PREFLIGHT_SKIPPED: parameter_count_estimate was None or "
            "non-positive; the pre-flight advisory could not run for this "
            "draft."
        )
        return None

    baseline = output.baseline_config or {}
    verdict = estimate_proposal_time(
        model_type=output.model_name,
        model_config=baseline.get("model_config") or {},
        train_config=baseline.get("train_config") or {},
        loss_config=baseline.get("loss_config") or {},
        num_params=num_params,
        time_budget_minutes=budget,
        train_portion=inp.train_portion,
        trial_portion=inp.trial_portion,
        data_scope=inp.data_scope,
    )
    output.preflight_estimated_minutes = verdict["estimated_minutes"]
    output.preflight_factor = verdict["factor"]
    if verdict.get("applicable") is False:
        output.memo_consistency_notes.append(
            "PREFLIGHT_SKIPPED: the static wall-time formula is not applicable "
            "to this task's declared topology."
        )
        return None
    factor = float(verdict["factor"])

    # C8b: the note is emitted on the SHARED policy's decision, not on a
    # private `factor > 1.0` comparison. The static producer's numbers are
    # unchanged; what changed is that the authority to act on them now
    # lives in exactly one place. A static estimate is structurally
    # incapable of REJECT/ABORT here (type-derived eligibility + §7.4
    # matrix row `static_prior/proposal = advisory_only`) — the assertion
    # below turns any future regression of that invariant into a crash
    # rather than a silently rejected proposal.
    from core.runtime_control.decision_policy import RuntimeBudget, RuntimeMode
    from core.runtime_control.estimate_types import from_proposer_preflight

    policy = _runtime_policy()
    decision = policy.decide(
        from_proposer_preflight(verdict),
        RuntimeBudget(time_seconds=budget * 60.0),
        RuntimeMode(phase="proposal", candidate_stage="proposal"),
    )
    if decision.kind in ("REJECT", "ABORT"):
        raise AssertionError(
            f"proposal-stage static evidence produced {decision.kind}: "
            f"{decision.reasons} — the C1/C8 advisory-only invariant is broken"
        )
    if decision.kind != "ALLOW":
        output.memo_consistency_notes.append(
            _build_preflight_advisory_note(
                num_params=num_params,
                estimated_minutes=float(verdict["estimated_minutes"]),
                factor=factor,
                budget_minutes=budget,
                policy_identity=policy.identity,
            )
        )
    return factor


def _check_citation_discipline(
    source_refs: list,
    causal_hypothesis: str,
    proposed_change: str,
) -> list:
    """Return a warning message for each source_ref that was cited but not referenced.

    Each source_ref in source_refs must appear verbatim in causal_hypothesis
    or proposed_change.  Violations are soft warnings — the proposal is not
    rejected, but the issues are appended to ProposalOutput.memo_consistency_notes
    so the validator and the human reviewer can see them.

    Args:
        source_refs: list of source_ref strings from DiscoveryMemo.
        causal_hypothesis: the reasoning text that should reference the cited items.
        proposed_change: the change description that should reference the cited items.

    Returns:
        List of violation strings, one per uncited source_ref.  Empty = all citations
        are properly referenced in the reasoning text.
    """
    combined = causal_hypothesis + " " + proposed_change
    violations = []
    for source_ref in source_refs:
        if source_ref not in combined:
            violations.append(
                f"CITATION_NOT_REFERENCED: source_ref '{source_ref}' is listed in "
                f"source_refs but does not appear verbatim in causal_hypothesis "
                f"or proposed_change. Either reference it in your reasoning or remove "
                f"it from citations."
            )
    return violations


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

PROPOSAL_REASONING_PROMPT = """\
You are a senior ML architect{ARCHITECT_ROLE}.

Your task: given a structured analysis of past hyperparameter tuning experiments
across one or more model architectures, reason deeply about what new neural
architecture could best overcome the identified bottlenecks.

{TASK_BACKGROUND}- The VRAM ceiling is published in the [HARDWARE CONTEXT] block at the top of
  the user message — treat that block's "Effective cap" as the hard limit,
  and justify `parameter_count_estimate` against that cap rather than
  against a fixed parameter budget.

In your reasoning, cover all of the following:
1. What structural weakness do the bottlenecks and take-home message specifically point to?
   Be concrete — name the architectural property that is limiting performance.
2. What architecture families could address that weakness?
   Consider: multi-scale convolutions, attention mechanisms, CNN+attention hybrids,
   state-space models (Mamba/S4), temporal convolution networks, etc.
   Discuss the tradeoffs of each in the context of this task.
3. Which approach do you think is most promising, and why?
   Justify your choice by connecting it directly to the identified bottlenecks.
4. What are the key design choices (depth, width, kernel sizes, attention heads, etc.)
   for a safe, moderate baseline configuration that fits within the GPU budget?
   Note: keep the mathematical_definition abstract (computational principles, not shapes).
   Concrete dimensions belong only in baseline_config.
5. What are the likely failure modes of this architecture?
   What should the hyperparameter tuning agent watch out for?
6. Per-file analysis and trial strategy guidance:
{EVIDENCE_READING}
   - Recommend a trial strategy for the hyperparameter tuner:
     * What trial_portion to start with (based on model complexity — larger models need more data)
     * How many epochs for initial screening vs refinement
     * Whether to use "snapshot" (broad coverage), "target"{TARGET_SELECTOR_CLAUSE}, or "anchors" (small fixed subset)
     * Whether the architecture is data-hungry (needs high trial_portion) or data-efficient

Think step by step. Be specific. Reference actual scores, model names{EVIDENCE_CITATION_CLAUSE}. Do not
produce JSON — that is the next step."""


PROPOSAL_COMMIT_PROMPT = """\
You are a senior ML architect. You have just completed a detailed reasoning step
about a new architecture proposal. Now commit to a specific design.

Output a JSON object with exactly these fields:

{
  "model_name": "short_snake_case_key",
  "output_type": "classifier" or "regressor" — REQUIRED. The output representation this model commits to. "classifier" emits {CLASSIFIER_OUTPUT_SHAPE} per-timestep class logits and admits loss_type ce/focal/focal_cw; "regressor" emits {REGRESSOR_EMITS} and admits loss_type smooth_l1. This is an INDEPENDENT design decision: do NOT pick a loss first and let the output follow, and do NOT infer one from the other. An inconsistent pair is rejected before training.",
  "model_description": "One paragraph plain-English description of the architecture and why it is expected to improve on the current best.",
  "mathematical_definition": "Must open with a three-sentence 'Golden Paragraph' that cites: (1) the forward contract for the output_type you chose — for 'classifier': 'Input: {INPUT_SHAPE}{INPUT_SEMANTICS}. Output: {OUTPUT_SHAPE} ({OUTPUT_DESCRIPTION})'; for 'regressor': 'Input: {INPUT_SHAPE}{INPUT_SEMANTICS}. Output: {REGRESSOR_OUTPUT_FORM}'; (2) the segmentation semantics — state whether the body is segment-local (no cross-segment state) or segment-cross (e.g. global attention within a segment), and whether causal masking is required; (3) the output dimension — for 'classifier', '{CLASS_AXIS_NOTE}'; for 'regressor', 'the head emits one continuous value per time step'. After the Golden Paragraph, describe the architectural framework abstractly: key computational stages, mathematical operations, data flow. Do NOT include concrete layer dimensions, kernel sizes, or channel counts — those belong in baseline_config.",
  "motivation": "Why this specific architecture addresses the bottlenecks from the interpretation. Must reference the take-home message directly and name at least one specific bottleneck.",
  "expert_advice": {
    "focus_areas": ["What to prioritise during hyperparameter tuning for this architecture"],
    "constraints": ["Hard limits — must include at least one VRAM limit (relative to the effective cap in [HARDWARE CONTEXT])"],
    "known_failures": ["Configs or approaches to avoid, based on patterns in the interpretation"],
    "suggested_directions": [
      "Concrete first experiments to try, e.g. 'start with depth=2, lr=1e-4'",
      "Trial strategy guidance: recommended trial_portion (e.g. 0.1 for data-hungry models)",
      "Recommended epochs for screening (1-3) vs refinement (5-10)"{PER_FILE_STRATEGY_DIRECTIONS}
    ],
    "rationale": "Why this guidance is appropriate for this specific architecture. Include reasoning about data volume needs{EVIDENCE_RATIONALE_CLAUSE}."
  },
  "baseline_config": {
    "model_config": { ... architecture-specific hyperparameter fields ... },
    "train_config": {
      "lr": 1e-4,
      "epochs": 10,
      "batch_size": 1,
      "optimizer_type": "adamw",
      "weight_decay": 1e-5,
      "device": "cuda"
    },
    "loss_config": { "loss_type": "focal", "alpha": 0.5, "gamma": 2.0, "reduction": "mean" }
  },
  "parameter_count_estimate": 1234567
}

Hard constraints — violating any of these makes the proposal invalid:
- model_name must NOT be any of the existing model types listed in the context
- model_name must be snake_case: lowercase letters, digits, and underscores only
- The input is fixed: {INPUT_SHAPE}. The OUTPUT depends on the `output_type` you
  choose — it is a design decision, not a fixed constant:
    * `"classifier"` → output {OUTPUT_SHAPE} (per-timestep class logits);
      legal `loss_type`: {CLASSIFIER_LOSSES}
    * `"regressor"`  → output {REGRESSOR_OUTPUT_FORM};
      legal `loss_type`: {REGRESSOR_LOSSES}
  Choose the pair deliberately and state it in `output_type`. Do NOT pick a loss
  first and let the output follow — they are independent choices, and an
  inconsistent pair is rejected before training.
- baseline_config must be conservative: fits comfortably within the effective cap shown in the [HARDWARE CONTEXT] (the VRAM gate rejects anything above it)
- expert_advice.constraints must include at least one VRAM limit (relative to
  the effective cap shown in the [HARDWARE CONTEXT]). Capacity constraints such
  as parameter-count ceilings may be included ONLY when justified by measured
  evidence or explicit capacity arithmetic — never as unexamined defaults
- parameter_count_estimate must be a positive integer — your best estimate of the total
  trainable parameter count at the baseline_config. An order-of-magnitude estimate is
  sufficient; be realistic about multi-head attention, state dims, dilated stacks, etc.
  This drives the proposer-side pre-flight cost check.

Output only the JSON object — no preamble, no markdown fences, no commentary."""


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------


def _render_task_background(task_description: str, fc: ForwardContract) -> str:
    """Render the ``{TASK_BACKGROUND}`` placeholder block for
    ``PROPOSAL_REASONING_PROMPT`` and the proposing-stage ``.md``
    templates.

    Returns the multi-line block ``Background on the task:`` header + a
    bullet for the task description + the rendered forward contract, with
    a trailing newline so the template's next line (``- The VRAM
    ceiling...``) follows naturally. Returns ``""`` when both
    ``task_description`` and ``fc`` are empty — only reachable from test
    fixtures that don't go through ``load_task_config`` (production
    callers always populate both).

    Mirrors the helper of the same name in
    ``nodes/ml_model_implementor/ml_model_implementor.py`` (T2) so that
    both agents render the task framing identically.
    """
    if not task_description and fc.is_empty():
        return ""
    parts = ["Background on the task:"]
    if task_description:
        parts.append(f"- {task_description}")
    fc_block = render_forward_contract(fc)
    if fc_block:
        parts.append(fc_block)
    # Trailing empty string → final "\n" so the next template line (the
    # VRAM-ceiling bullet) starts on a fresh line.
    parts.append("")
    return "\n".join(parts)


def _render_pipeline_task_background(task_description: str) -> str:
    """Render the ``{task_background_block}`` block for the THREE pipeline
    stage SYSTEM prompt templates (comparison, causal reasoning, proposing).

    Delegates to :func:`_render_task_background` with an EMPTY
    ``ForwardContract`` so that:

    * the ``Background on the task:`` label has exactly ONE authority in
      the codebase (PR 01b invariant F3) — it is never duplicated into
      the three ``.md`` templates; and
    * the forward contract is NOT expanded into the comparison and causal
      stages (PR 01b invariant F10). The proposing stage renders the
      contract separately through its own ``{forward_contract}``
      placeholder, which this block deliberately does not duplicate.

    Returns ``""`` for an absent or whitespace-only description, so the
    placeholder collapses to nothing and no label is emitted over blank
    space. A non-empty description renders the labelled block followed by
    ONE blank line; the templates therefore place the placeholder
    immediately against the next heading (``{task_background_block}##
    Your task``) and an empty description leaves the pre-JOIN bytes
    byte-identical.

    See ``docs/design/generic_framework_upgrade/
    step_01_proposer_hypothesis_space/pr_01b_task_description_join.md``
    § 4.1 (commit S1-C).
    """
    description = task_description.strip()
    if not description:
        return ""
    return _render_task_background(description, ForwardContract()) + "\n"


def _build_reasoning_system_prompt(inp: ProposalInput) -> str:
    """Substitute the ``{TASK_BACKGROUND}`` placeholder in
    ``PROPOSAL_REASONING_PROMPT`` from ``inp``.

    Production callers always have ``inp.task_description`` non-empty and
    ``inp.forward_contract`` fully populated (workflow injects from
    ``load_task_config()``); test fixtures may leave both at defaults, in
    which case the placeholder collapses to ``""``.
    """
    return (
        PROPOSAL_REASONING_PROMPT.replace(
            "{TASK_BACKGROUND}",
            _render_task_background(inp.task_description, inp.forward_contract),
        )
        # Step 12 / PR-12a C7 (D-12a-6) — task-owned proposer science. The
        # gating is a rendered STRING from the caller-supplied blocks, so this
        # assembly site substitutes tokens and never learns what a composition
        # is — the same discipline C7-2 used for the tuner surfaces.
        .replace("{ARCHITECT_ROLE}", render_architect_role(inp.proposal_blocks))
        .replace("{EVIDENCE_READING}", render_proposal_evidence_reading(inp.proposal_blocks))
        # C7-5 (Pr3) — the two per-file clauses left behind by C7-3, both
        # class (1): absent renders NOTHING rather than another task's columns.
        .replace(
            "{TARGET_SELECTOR_CLAUSE}",
            _declared(inp.proposal_blocks, "target_strategy_selector_clause") or "",
        )
        .replace(
            "{EVIDENCE_CITATION_CLAUSE}",
            _declared(inp.proposal_blocks, "evidence_citation_clause") or "",
        )
    )


def render_architect_role(blocks: Any) -> str:
    """The specialism clause of the architect role line (D-12a-6, Pr1).

    Rendered as a CLAUSE, not a whole sentence, so an absent declaration
    yields "You are a senior ML architect." — a role with no specialism,
    rather than another task's. Legacy renders TIDMAD's clause verbatim, so
    the un-composed bytes do not move.
    """
    role = getattr(blocks, "architect_role", None) if blocks is not None else None
    return f" specialising in {role}" if role else ""


def render_proposal_evidence_reading(blocks: Any) -> str:
    """How to read THIS task's score evidence (D-12a-6, Pr3).

    TIDMAD's version is a per-file `Impact_Score` / `Linear_Weight` ranking
    protocol. A task that declares none gets NOTHING — asking a model to rank
    by a column its evidence does not contain is worse than asking nothing.
    """
    reading = getattr(blocks, "evidence_reading", None) if blocks is not None else None
    return reading or ""


def _declared(blocks: Any, key: str) -> str | None:
    """One accessor, so no renderer below learns what a composition is."""
    return getattr(blocks, key, None) if blocks is not None else None


def render_classifier_output_shape(fc: ForwardContract) -> str:
    """The CLASSIFIER form's shape, derived from the run's declaration.

    Step 12 / PR-12a C7-5 (Pr2). The prompt used to say ``[B, 256, T]`` for
    every task. `declared_output_tensor` is the same authority the implementor
    renders from and the probe validates against, so the commit prompt cannot
    document a form the validator would reject.

    A task with no normalized ``model_io`` keeps the legacy behaviour: the
    declared ``output_shape`` with its dtype dropped, which is what the shape
    meant before Step 03 existed.
    """
    if fc.model_io is not None:
        return declared_output_tensor(fc.model_io, "classifier").render_shape()
    return fc.output_shape.split(" float")[0].split(" int")[0]


def render_regressor_output_form(fc: ForwardContract, blocks: Any, *, with_dtype: bool) -> str:
    """The CONTINUOUS form: a declared SHAPE plus, when declared, its meaning.

    Step 12 / PR-12a C7-5 (Pr2). The hardcoded
    ``[B, T] float32 (the denoised waveform directly)`` told a video task that
    it predicts a waveform. The shape is derived; the meaning is the task's,
    and an undeclared task gets the shape alone rather than TIDMAD's noun.
    """
    if fc.model_io is not None:
        tensor = declared_output_tensor(fc.model_io, "regressor")
        shape = tensor.render() if with_dtype else tensor.render_shape()
    else:
        shape = fc.output_shape if with_dtype else fc.output_shape.split(" float")[0]
    meaning = _declared(blocks, "continuous_output_meaning")
    if not meaning:
        return shape
    return f"{shape} ({meaning})" if with_dtype else f"{shape} {meaning}"


def render_input_semantics(blocks: Any) -> str:
    """The parenthetical naming what the input VALUES are (Pr2).

    Absent -> nothing, so the declared shape stands alone. Never another
    task's ADC indices.
    """
    semantics = _declared(blocks, "input_semantics")
    return f" ({semantics})" if semantics else ""


def render_class_axis_note(fc: ForwardContract, blocks: Any) -> str:
    """The contract-fixed statement about the class axis (Pr2).

    Absent -> a GENERIC statement, not an invented count: the declared output
    dimension is contract-fixed whatever the task is, and saying so is
    framework structure rather than science.
    """
    note = _declared(blocks, "class_axis_note")
    if note:
        return note
    return "the declared output dimension is contract-fixed, not a hyperparameter"


def render_per_file_strategy_directions(blocks: Any) -> str:
    """The task's per-sample strategy advice, as JSON list items (Pr3).

    The task declares one sentence per LINE and never writes JSON; the
    framework supplies the commas, quoting and indentation. Class (1): absent
    renders NOTHING, because advice about a column the run has no table for is
    worse than no advice.
    """
    guidance = _declared(blocks, "per_file_strategy_guidance")
    if not guidance:
        return ""
    lines = [line.strip() for line in guidance.splitlines() if line.strip()]
    return "".join(f',\n      "{line}"' for line in lines)


def render_output_contract_guidance(blocks: Any) -> str:
    """What this task's output representations MEAN (D-12a-6, Pr2).

    The SHAPES are already declared by the run's ``ForwardContract`` and are
    rendered from it; this is the prose beside them. Absent ⇒ the shapes
    stand alone, which is honest, rather than "256 amplitude bins" for a task
    that has none.
    """
    guidance = getattr(blocks, "output_contract_guidance", None) if blocks is not None else None
    return guidance or ""


def _render_cold_start_block(cold_start: bool) -> str:
    """Explicit cold-start banner for the proposer USER prompt.

    Non-empty ONLY when ``cold_start`` is True; returns the empty string
    otherwise so that seeded (history-backed) prompts are byte-for-byte
    unchanged. Communicates that no prior experimental evidence exists, treats
    registries as available options (not past results), and forbids claiming
    improvement over a non-existent history.
    """
    if not cold_start:
        return ""
    return (
        "[COLD START — NO PRIOR EXPERIMENTAL EVIDENCE]\n"
        "This is the first iteration of the chain. No prior experimental runs, "
        "scores, model history, or failures exist yet. Do not reference or claim "
        "improvement over previous results — there are none. Propose the first "
        "experiment grounded in the task contract, the available model and loss "
        "registries (listed below as available options, not past results), the "
        "advice, and the resource constraints."
    )


def _render_data_scope_block(scope) -> str:
    """Render the ``[DATA SCOPE]`` prompt block (DS7b).

    Returns ``""`` for a full scope — pre-DataScope prompts are
    byte-for-byte unchanged. Under a partial scope the proposer is told
    which files exist for this run and that sampling is snapshot-only, so
    drafts are not designed around out-of-scope data. Disclosure only —
    enforcement is the tuner/sandbox's job.
    """
    from execute_tools.dataset_config import TIDMAD as _TIDMAD

    if scope is None or scope.is_full(_TIDMAD.num_files):
        return ""
    resolved = scope.resolve(_TIDMAD.num_files)
    return (
        "[DATA SCOPE]\n"
        f"This run is restricted to validation files {resolved} — the ONLY\n"
        "files any training, inference, or scoring may access. Sampling is\n"
        "snapshot-only under this restriction (anchors/target strategies are\n"
        "normalized away). Design the proposal for THESE files' data; do not\n"
        "reason about, or optimize for, out-of-scope files."
    )


def _render_hardware_context_block(
    ctx: HardwareContext | None,
    vram_budget_gb: float | None,
) -> str:
    """Render the ``[HARDWARE CONTEXT]`` prompt block.

    Mirrors the three regimes of ``wrapper.py``'s ``[Hardware]`` log
    classifier (PHYSICAL / BUDGET / PHYSICAL VETO). See
    docs/phase66_ws_b_proposer_hardening.md §3.1.

    Returns ``""`` when ``ctx`` is None or ``device_available=False`` —
    CPU-only runs and legacy callers get no block injected, preserving
    back-compat with prompts rendered pre-WS-B.

    Regime selection:
      - ``vram_budget_gb is None``                 → PHYSICAL       (cap = usable_cap_gb)
      - ``vram_budget_gb <= usable_cap_gb``        → BUDGET         (cap = vram_budget_gb)
      - ``vram_budget_gb  > usable_cap_gb``        → PHYSICAL VETO  (cap = usable_cap_gb; operator ceiling is above the 80% physical safety floor and therefore ignored)
    """
    if ctx is None or not ctx.device_available:
        return ""

    usable = ctx.usable_cap_gb
    # Step 04a: the NUMBER comes from the shared `effective_cap_gb` rule so
    # the implementor's capacity prose cannot quote a different one. Only the
    # regime LABEL is rendered here, because only this block names it.
    effective = ctx.effective_cap_gb(vram_budget_gb)
    if vram_budget_gb is None:
        regime = "PHYSICAL"
    elif vram_budget_gb <= usable:
        regime = "BUDGET"
    else:
        regime = "PHYSICAL VETO"

    lines = [
        "[HARDWARE CONTEXT]",
        f"Device:            {ctx.device_name}",
        f"Total VRAM:        {ctx.total_memory_gb:.2f} GB",
        f"Usable cap (80%):  {usable:.2f} GB",
        f"Host:              {ctx.hostname}",
    ]
    if vram_budget_gb is not None:
        lines.append(f"Operator budget:   {vram_budget_gb:.2f} GB")
        lines.append(f"Effective cap:     {effective:.2f} GB")

    if regime == "PHYSICAL":
        lines.append(
            f"Regime:            PHYSICAL — no operator budget set; cap = {effective:.2f} GB."
        )
    elif regime == "BUDGET":
        lines.append("Regime:            BUDGET — operator's budget is the binding ceiling.")
    else:  # PHYSICAL VETO
        lines.append("Regime:            PHYSICAL VETO — operator budget exceeds the 80%")
        lines.append("                   physical safety floor; the physical cap wins.")

    lines.append("")
    lines.append(
        "Your baseline_config must fit within the **effective cap** shown above. "
        "The VRAM engine will reject any architecture whose predicted peak exceeds "
        "this ceiling; a rejection consumes a tuner attempt with no scored round. "
        "Size your baseline to stay comfortably below the cap (target ≤ 80% of the "
        "effective cap at baseline) so the tuner has headroom to vary batch_size "
        "and segmentation_size upward."
    )
    return "\n".join(lines)


def _render_constraints_block(
    constraints: list[str],
    existing_model_types: list[str],
) -> str:
    """Render the ``## Constraints`` prompt block (Commit P-d).

    Restores the constraints render path in pipeline mode. Pre-P-d this
    block was assembled only inside the legacy ``_build_reasoning_prompt``
    (at line 762-764), so production runs — which use pipeline mode
    exclusively — never saw `ProposalInput.constraints` nor the
    "your model_name must NOT be any of these" reminder list. This helper
    fixes that and is called at the top of every stage's user prompt by
    ``_run_pipeline``.

    Empty inputs yield an empty string so callers can skip-append in the
    same idiom as ``_render_hardware_context_block``.

    The proposing-stage `existing_model_types` name-uniqueness rule also
    reaches the LLM via the proposing system prompt's template variable
    ``{existing_model_types}``; rendering it again at the top of the user
    prompt is a deliberate redundancy — name-uniqueness is a frequent
    violation and the prompt is long enough that one reference at the top
    of the system prompt is insufficient signal.
    """
    if not constraints and not existing_model_types:
        return ""

    lines = ["## Constraints"]
    if existing_model_types:
        lines.append(
            f"Existing model type keys (your `model_name` must NOT be any of "
            f"these): {list(existing_model_types)}"
        )
    for c in constraints or []:
        lines.append(f"  - {c}")
    return "\n".join(lines)


def _format_recent_trial_validity_block(
    entries: list[TrialValidityFeedback],
) -> str:
    """Render the [RECENT TRIAL VALIDITY] block (V20 PR D, D-C6).

    Transports FACTS the gate system already recorded — record identities,
    which blocking gates failed, the reasons and metrics they emitted, and
    what could not be established. It states no remedy: what a particular
    metric implies for a particular task is the planner's judgement, and
    task-specific advice in workflow code is what §3.3 forbids.

    The distinctions are preserved rather than collapsed into "trials
    failed", because they call for different responses: an EXECUTION
    failure means the evidence is absent, a gate INVALIDITY means the
    evidence is negative, and validity UNKNOWN means the gates could not
    judge it at all.

    Empty list → "" so the placeholder collapses and a healthy chain's
    prompt is byte-identical to before.
    """
    if not entries:
        return ""

    lines: list[str] = [
        f"## [RECENT TRIAL VALIDITY] {len(entries)} iteration(s) with no valid trial",
        "",
        "These iterations ran trial rounds that produced NO HealthGate-valid",
        "candidate. This is not a budget problem — the trials ran. Treat the",
        "gate evidence below as the reason the results could not be used.",
        "",
    ]
    total = len(entries)
    for offset, entry in enumerate(entries):
        tag = f"iter N-{total - offset}"
        lines.append(f"### {tag}")
        lines.append(
            f"- {entry.trial_records_considered} trial(s): "
            f"{entry.invalid_count} gate-invalid, "
            f"{entry.unknown_validity_count} validity-unknown, "
            f"{entry.execution_failure_count} execution failure(s)"
        )
        if entry.healthgate_mode:
            lines.append(f"- healthgate_mode: {entry.healthgate_mode}")
        if entry.formal_skipped_for_no_valid_winner:
            lines.append(
                "- the formal round was SKIPPED because no valid trial winner existed "
                "(not because of the time budget)"
            )
        for outcome in entry.outcomes:
            bits = [f"status={outcome.status}", f"validity={outcome.health_validity.value}"]
            if outcome.failed_gate_names:
                bits.append(f"failed_gates={','.join(outcome.failed_gate_names)}")
            if outcome.failure_reasons:
                bits.append(f"reasons={','.join(outcome.failure_reasons)}")
            if outcome.key_metrics:
                metrics = ", ".join(f"{k}={v}" for k, v in sorted(outcome.key_metrics.items()))
                bits.append(f"metrics=({metrics})")
            lines.append(f"  - {outcome.exp_id or '<unidentified>'}: " + "; ".join(bits))
        for absent in entry.evidence_absent:
            lines.append(f"  - EVIDENCE ABSENT — {absent}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _format_recent_gate_exhaustions_block(
    entries: list[GateExhaustionInfo],
) -> str:
    """Render the [RECENT GATE EXHAUSTIONS] block per §14.N.3.

    Aggregate-window successor to the K.7.6 singular helper: carries the
    structured failure reports from up to the last 3 tuner iterations so
    the next proposer can spot *repeated* abort-class failures on the same
    architecture family and switch family rather than shrink.

    Empty list → "" so callers can unconditionally splice the result into
    a template (no empty section, no header).

    Non-empty list → header tagged with the entry count, each entry
    labelled with a relative iteration tag (``iter N-k``, oldest first,
    ``iter N-1`` = most recent), entries separated by a horizontal rule,
    and a closing paragraph that tells the LLM to switch family when the
    same failure mode recurs. See docs/resource_estimator_implement.md §14.N.
    """
    if not entries:
        return ""

    def _num(v, suffix=""):
        return f"{v}{suffix}" if v is not None else "n/a"

    def _factor(v):
        return f"{v:.2f}×" if v is not None else "n/a"

    def _entry_lines(info: GateExhaustionInfo, label: str) -> list:
        lines = [
            f"{label}",
            info.summary_message,
            "",
            "Resource accounting:",
            f"  Mode active:       {info.active_mode}",
            f"  VRAM budget:       {_num(info.vram_budget_gb, ' GB')}",
            f"  Time budget:       {_num(info.time_budget_minutes, ' min')}",
            f"  Baseline factors:  VRAM {_factor(info.baseline_vram_factor)}   "
            f"Time {_factor(info.baseline_time_factor)}",
            f"  Worst factors:     VRAM {_factor(info.worst_vram_factor)}      "
            f"Time {_factor(info.worst_time_factor)}",
            f"  Attempt counts:    {info.total_attempts} total, "
            f"{info.vram_gated_attempts} VRAM-gated,",
            f"                     {info.time_gated_attempts} time-gated, "
            f"{info.other_failure_attempts} other failures",
        ]
        # Fix 1 — surface structured architectural bans as a hard DO-NOT-PROPOSE
        # block. Tags are rendered with their English descriptions imported
        # from the tagger (single source of truth). Only tags with a
        # registered description appear; unknown tags are dropped defensively
        # (the completeness invariant in the tagger's tests prevents this in
        # practice). See docs/reliable_resource_proposer.md §9 Commit 4.
        described = [
            (t, ARCHITECTURAL_PATTERNS[t])
            for t in info.disallowed_architectural_patterns
            if t in ARCHITECTURAL_PATTERNS
        ]
        if described:
            lines += ["", "[DISALLOWED PATTERNS] DO NOT PROPOSE:"]
            for tag, description in described:
                lines.append(f"  - {tag}: {description}")
        return lines

    n = len(entries)
    plural = "s" if n > 1 else ""
    separator = "-" * 68
    lines = [f"[RECENT GATE EXHAUSTIONS (last {n} iteration{plural})]"]

    for i, info in enumerate(entries):
        # entries[0] is oldest → iter N-n ... entries[-1] is newest → iter N-1
        rel = n - i
        suffix = " (most recent)" if rel == 1 else ""
        label = f"iter N-{rel}{suffix}:"
        if i > 0:
            lines += ["", separator, ""]
        lines += _entry_lines(info, label)

    lines += [
        "",
        "For this iteration: if the same architecture family or scale appears",
        "in multiple entries above, that is a strong signal the family is",
        "structurally infeasible under the active budgets — propose a",
        "different family, not a smaller variant of the same family. If only",
        "a single entry is shown, treat it as one bounded report from the",
        "pre-attempt gates (whose time estimates may be uncalibrated): first",
        "adjust the workload plan (optimizer steps, batch size, segment",
        "sizing) to fit the budgets, reducing capacity only where the gate",
        "report shows a VRAM limit. Do not derive a permanent",
        "parameter-count ceiling from a single gate report.",
    ]
    return "\n".join(lines)


def _render_stage_user_prompt(accumulated: dict[str, Any]) -> str:
    """Render a pipeline-stage user prompt: native markdown + clean JSON.

    Splits the stage user prompt into two concatenated regions:

    * **Top-level markdown** — one section per candidate, carrying the full
      `ScoreComparisonTable.rendered_markdown` + fenced source code block.
      This is what the LLM reads for high-density per-file reasoning. Empty
      when there are no candidates.
    * **JSON region** — scalar metadata (`best_score`, `model_params`, etc.),
      non-candidate overview one-liners, `interpretation_summary`, and the
      rest of the pipeline state.

    Before dumping the JSON region, we:

    * Strip `score_table`, `source_code`, `source_code_lines` from every
      candidate entry (the heavy content now lives in the top-level markdown).
    * Drop `per_model_score_tables` from `interpretation_summary` — redundant
      with the top-level markdown and the non-candidate `score_summary` lines.
    """
    from nodes.proposal_helpers import (
        build_candidate_markdown_block,
        strip_heavy_fields_for_json,
    )

    candidates = accumulated.get("candidates") or []
    markdown_block = build_candidate_markdown_block(candidates)

    cleaned: dict[str, Any] = dict(accumulated)
    cleaned["candidates"] = strip_heavy_fields_for_json(candidates)
    interp_summary = cleaned.get("interpretation_summary")
    if isinstance(interp_summary, dict) and "per_model_score_tables" in interp_summary:
        cleaned["interpretation_summary"] = {
            k: v for k, v in interp_summary.items() if k != "per_model_score_tables"
        }

    json_region = (
        "## Accumulated context\n\n```json\n" + json.dumps(cleaned, indent=2, default=str) + "\n```"
    )
    if markdown_block:
        return f"{markdown_block}\n{json_region}"
    return json_region


# Keys in `accumulated` that came in from `ProposalInput` (vs. produced by
# upstream proposer stages such as `comparison`, `causal_reasoning`,
# `proposing_stage_errors`). Used by `_audit_proposer_components` to
# attribute prompt characters to the prior-stage-output bucket.
_PROPOSER_INPUT_KEYS = {
    "candidates",
    "non_candidates_overview",
    "interpretation_summary",
    "existing_model_types",
    "previous_failures",
}


def _extract_prior_stage_keys(accumulated: dict[str, Any]) -> dict[str, Any]:
    """Return the subset of ``accumulated`` produced by earlier proposer stages.

    Anything not in :data:`_PROPOSER_INPUT_KEYS` is treated as a stage output
    (``comparison``, ``causal_reasoning``, ``proposing_stage_errors``, etc.).
    """
    return {k: v for k, v in accumulated.items() if k not in _PROPOSER_INPUT_KEYS}


def _audit_proposer_components(
    *,
    inp: ProposalInput,
    accumulated: dict[str, Any],
    agent_cards_block: str,
    expert_context_block: str,
    vocab_block: str,
    system_prompt: str,
    stage_name: str,
) -> dict[str, Any]:
    """Pre-merge char-count breakdown of a proposer LLM call (§1.3).

    Returns a 10-key ``components`` dict suitable for ``bridge.generate(
    components=...)``, plus a ``stage_name`` and ``total_chars`` for tests
    and ad-hoc debugging. The breakdown mirrors the structure of the user
    prompt assembled by :func:`_render_stage_user_prompt` and the per-call-
    site appends of ``agent_cards_block`` / ``expert_context_block`` /
    ``vocab_block``. Each value is the char count of that component
    *before* tokenization, so a downstream report can localise bloat to a
    specific source even when the provider's tokenizer is opaque.

    Empty / missing blocks (``""`` or absent dict keys) yield ``0`` for
    that component — never a missing key. The 10 keys are stable and
    enforced by ``test_audit_components.py``.

    Commit 4.3.3 (Rev 8, 2026-05-05): added ``non_candidates_overview`` as
    a dedicated content key. The forensic audit (§8 Commit 4.3.2) showed
    this field carries a per-model dump pulled from ``model_descriptions``
    + ``model_knowledge_cache`` and grew from 15 K → 111 K chars between
    iter 1 and iter 14 of the V12 explore run — the dominant contributor
    (113 % of the catch-all delta) to the false ``template_and_scaffolding``
    11× signal. With this key live, the catch-all returns to its true
    fixed-template baseline (~8 K chars) and Phase 2 surgery operates on
    a trustworthy breakdown.

    Note (Commit 4.2, 2026-05-04): the audit hook covers the 10 *content*
    payloads injected into the user prompt, but not the template wrapper
    text (section headers, key-value preludes, stage instructions) added
    by the ``_build_*_prompt`` builders. Gate T1 measured that wrapper
    overhead at ~7.5-8.3 K chars per proposer call. To keep the row-level
    audit lossless, ``LLMBridge._record_usage`` augments the dict on
    write with a catch-all key ``template_and_scaffolding``
    (= ``chars.total - sum(this hook's 10)``). The hook itself is
    intentionally unaware of that key — it only reports content payloads
    it can derive from inputs.
    """
    from nodes.proposal_helpers import build_candidate_markdown_block

    # ---- candidates_markdown: identical computation to _render_stage_user_prompt
    candidates = accumulated.get("candidates") or []
    candidates_markdown_chars = len(build_candidate_markdown_block(candidates))

    # ---- interpretation_json: drop per_model_score_tables exactly like
    # _render_stage_user_prompt does, then serialise. Empty dict / missing
    # → empty JSON object literal "{}", contributing 2 chars.
    interp_summary = accumulated.get("interpretation_summary")
    if isinstance(interp_summary, dict) and "per_model_score_tables" in interp_summary:
        interp_summary = {k: v for k, v in interp_summary.items() if k != "per_model_score_tables"}
    interpretation_json_chars = len(json.dumps(interp_summary or {}, default=str))

    # ---- non_candidates_overview: list of per-non-candidate-model summary
    # dicts (lines 1010-1034), each carrying full ``description`` from
    # ``model_descriptions`` plus 4 cache fields (``key_findings``,
    # ``bottlenecks``, ``score_trend``, ``strategy_assessment``) drawn from
    # ``model_knowledge_cache``. Sized via the same compact serialization
    # used for ``interpretation_json`` / ``prior_stage_outputs`` for
    # consistency. Missing → ``[]`` → ``len("[]") == 2``. Promoted to a
    # named key by Commit 4.3.3 (Rev 8) after the §8 forensic audit
    # measured this single field at 15 K → 111 K chars across iter 1 → 14
    # of the V12 explore run — the dominant contributor (113 % of the Δ)
    # to the false ``template_and_scaffolding`` 11× growth signal.
    non_candidates_overview = accumulated.get("non_candidates_overview")
    non_candidates_overview_chars = len(json.dumps(non_candidates_overview or [], default=str))

    # ---- prior_stage_outputs: stage-produced keys, with heavy candidate
    # fields stripped to mirror what actually lands in the user prompt.
    prior_stage_payload = _extract_prior_stage_keys(accumulated)
    # candidates is an input key (handled separately above), but if a stage
    # ever overwrites it the markdown block already reflects that — leave
    # prior_stage_outputs to the actual stage-only keys.
    prior_stage_chars = len(json.dumps(prior_stage_payload, default=str))

    # ---- previous_failures: sum char count over the list of strings.
    previous_failures_chars = sum(len(s) for s in (inp.previous_failures or []))

    # ---- recent_gate_block: rendered via the same helper the prompt uses,
    # so the audit number matches what the LLM actually sees.
    recent_gate_chars = len(
        _format_recent_gate_exhaustions_block(inp.recent_gate_exhaustions or [])
    )
    recent_trial_validity_chars = len(
        _format_recent_trial_validity_block(inp.recent_trial_validity or [])
    )

    components: dict[str, int] = {
        "system_prompt": len(system_prompt or ""),
        "candidates_markdown": candidates_markdown_chars,
        "interpretation_json": interpretation_json_chars,
        "non_candidates_overview": non_candidates_overview_chars,
        "previous_failures": previous_failures_chars,
        "vocab_block": len(vocab_block) if vocab_block else 0,
        "expert_context_block": len(expert_context_block) if expert_context_block else 0,
        "agent_cards_block": len(agent_cards_block) if agent_cards_block else 0,
        "prior_stage_outputs": prior_stage_chars,
        "recent_gate_block": recent_gate_chars,
        "recent_trial_validity_block": recent_trial_validity_chars,
    }
    return {
        "stage_name": stage_name,
        "components": components,
        "total_chars": sum(components.values()),
    }


def _build_reasoning_prompt(inp: ProposalInput) -> str:
    """Build the user prompt for the legacy reasoning call.

    Step 10 / P3 C3: the interpretation region is rendered by the ONE typed
    adapter in ``evidence_rendering``; everything else here is
    ``ProposalInput`` context that was never interpretation evidence. The bytes
    are unchanged — PB-4 / S1-E and the C0 legacy goldens pin them on both a
    full-coverage fixture and a legacy artifact with absent keys.
    """
    lines = []

    # Phase 6.6 WS-B (B.2 bleed-over, landed with B.1 for Level-2 validation):
    # Render the [HARDWARE CONTEXT] block at the top of the user prompt so the
    # Proposer sees the effective VRAM ceiling (PHYSICAL / BUDGET / PHYSICAL
    # VETO regime) before any interpretation data. Empty string on CPU-only /
    # legacy-caller runs — no visible change for pre-WS-B test fixtures.
    hw_block = _render_hardware_context_block(inp.hardware_context, inp.vram_budget_gb)
    if hw_block:
        lines += [hw_block, ""]
    scope_block = _render_data_scope_block(inp.data_scope)
    if scope_block:
        lines += [scope_block, ""]

    lines += render_legacy_interpretation_section(inp.interpretation_evidence)

    lines += [
        "## Constraints",
        f"Existing model type keys (your model_name must NOT be any of these): {inp.existing_model_types}",
    ]
    for c in inp.constraints:
        lines.append(f"  - {c}")
    lines.append("")

    if inp.previous_failures:
        lines.append("## Previous Failed Proposals (DO NOT repeat these mistakes)")
        for i, failure in enumerate(inp.previous_failures, 1):
            lines.append(f"  {i}. {failure}")
        lines.append("")

    # Phase N (§14.N) — aggregate-window cross-iteration gate-exhaustion
    # report. Rendered from up to the last 3 tuner iterations so the
    # proposer can spot repeated abort-class failures on the same family
    # and switch family rather than shrink. Empty list → no block.
    gate_block = _format_recent_gate_exhaustions_block(inp.recent_gate_exhaustions)
    if gate_block:
        lines += [gate_block, ""]

    # V20 PR D (D-C6) — the all-trials-invalid report, spliced on the LEGACY
    # path too. Found by Gate 1: the first wiring reached only the pipeline
    # template, and the real proposer call took the legacy branch, so the
    # block never reached the model. That is the mirror image of the P3-V1
    # defect recorded below, where a legacy-only splice never reached
    # pipeline mode — both paths must carry it or the evidence is silently
    # dropped for whichever branch happens to run.
    trial_validity_block = _format_recent_trial_validity_block(inp.recent_trial_validity)
    if trial_validity_block:
        lines += [trial_validity_block, ""]

    # V19 PR 3 §3.7 (flag-gated) — structured HealthGate evidence, rendered
    # AFTER and visibly separate from the §14.N resource-gate block (a
    # different failure family). OFF (default): nothing rendered — the
    # prompt stays byte-identical to pre-PR3 (golden-parity tested) even
    # when the structured fields are present in the interpretation dump.
    if inp.enable_structured_health_feedback:
        health_block = render_healthgate_evidence_block(inp.interpretation_evidence)
        if health_block:
            lines += [health_block, ""]

    # NOTE: legacy ProposalInput.expert_advice render block was removed in
    # Commit P-d. The field was hard-removed from the schema; see proposal.py
    # for the rationale. External agent findings reach the proposer via
    # `agent_cards` + `expert_context` (rendered in _run_pipeline).

    if inp.human_advice:
        lines.append("## Human Expert Advice (high priority — address these explicitly)")
        if isinstance(inp.human_advice, str):
            lines.append(inp.human_advice)
        else:
            adv = inp.human_advice
            if adv.focus_areas:
                lines.append("### Focus areas")
                for item in adv.focus_areas:
                    lines.append(f"  - {item}")
            if adv.constraints:
                lines.append("### Additional constraints")
                for item in adv.constraints:
                    lines.append(f"  - {item}")
            if adv.known_failures:
                lines.append("### Known failures to avoid")
                for item in adv.known_failures:
                    lines.append(f"  - {item}")
            if adv.suggested_directions:
                lines.append("### Suggested directions")
                for item in adv.suggested_directions:
                    lines.append(f"  - {item}")
            if adv.rationale:
                lines += ["### Rationale", adv.rationale]
        lines.append("")

    return "\n".join(lines)


class ProposalContractRenderError(ValueError):
    """The commit system prompt cannot be rendered from the declaration.

    Raised instead of silently emitting a prompt whose I/O contract has
    collapsed to empty text. See ``_render_commit_system_prompt``.
    """


def _render_loss_legality(losses: frozenset[str]) -> str:
    """Render a loss-legality family as the prompt's backticked list.

    The ONE semantic authority for loss legality is
    ``ml_models.models_format_sandbox.CLASSIFICATION_LOSSES`` /
    ``REGRESSION_LOSSES``; this proposer-local renderer is a CONSUMER of
    that authority, never a second definition of it.

    Ordering is ``sorted()`` and that is part of the contract, not a
    convenience: frozenset iteration order varies per process (measured:
    three fresh interpreters produced three different orders), so
    iterating directly would make every prompt golden flaky across
    processes and defeat the exact-equality parity criterion.

    Args:
        losses: the authoritative family, e.g. ``CLASSIFICATION_LOSSES``.

    Returns:
        The families' names in ``sorted()`` order, each backticked and
        comma-separated — e.g. ``` `ce`, `focal`, `focal_cw` ```.

    Raises:
        ProposalContractRenderError: if the family is empty (an empty
            legality list would tell the agent that no loss is legal).
    """
    if not losses:
        raise ProposalContractRenderError(
            "loss-legality family is empty; refusing to render a prompt "
            "that declares no legal loss_type"
        )
    return ", ".join(f"`{name}`" for name in sorted(losses))


def _output_type_constraint_note(allowed: tuple[str, ...]) -> str:
    """The run-declared output-type constraint block (arXiv #259).

    ONE authority for both proposer modes (legacy commit prompt and the
    pipeline proposing stage), so the two prompts cannot state different
    constraints. Rendered ONLY when a constraint is declared — an
    unconstrained run's prompts are byte-identical to before the feature.
    The prompt is advisory; the deterministic gate on
    ``ProposalOutput.output_type`` is what enforces it.
    """
    allowed_list = ", ".join(f'"{t}"' for t in allowed)
    return (
        "\n\n## RUN CONSTRAINT — output_type\n"
        f"This run declares allowed output_type value(s): {allowed_list}. "
        'Your proposal MUST set "output_type" to one of these; any other '
        "value is refused deterministically before implementation (no retry "
        "credit is returned). Choose the loss family accordingly — the "
        "output_type/loss compatibility rule still applies.\n"
    )


def _default_output_type(allowed: tuple[str, ...] | None) -> str:
    """The omitted-key fallback for a raw LLM proposal (arXiv #259).

    Unconstrained runs keep the V21-PR-A legacy default ("classifier",
    byte-identical behavior). A run constrained to exactly ONE type defaults
    to that type — otherwise an LLM that simply omits the key would burn a
    retry on a refusal the constraint already resolves. A multi-type
    constraint keeps the legacy default and lets the gate decide.
    """
    if allowed is not None and len(allowed) == 1:
        return allowed[0]
    return "classifier"


def _render_commit_system_prompt(
    fc: ForwardContract,
    blocks: Any = None,
    *,
    allowed_output_types: tuple[str, ...] | None = None,
) -> str:
    """Render the legacy commit SYSTEM prompt from its declarations.

    Substitutes the tier-(i) verbatim-renderable task facts — those whose
    prompt literal equals a ``ForwardContract`` field byte-for-byte — plus
    the loss-legality families. Tier-(ii) surface variants (dtype-dropped
    shapes, slash-separated loss lists) and tier-(iii) undeclared text
    (the regressor output form, the "denoising bins" nouns) deliberately
    remain literal in the template: no authority declares them, and
    inventing a formatting rule for them is a Model/Loss-Contract
    decision owned by a later step.

    FAIL-CLOSED: an empty declaration raises rather than rendering a
    prompt with the I/O contract removed. The standalone CLI reaches this
    path, so a silent empty render would be a behavioural regression
    (the agent would be asked to design against no contract at all),
    not extraction parity.

    Args:
        fc: the declared forward contract (production: from
            ``load_task_config()``).

    Returns:
        The fully substituted system prompt — byte-identical to the
        previous constant under the shipped TIDMAD declaration.

    Raises:
        ProposalContractRenderError: if any substituted field is empty.
    """
    missing = [
        name
        for name, value in (
            ("input_shape", fc.input_shape),
            ("output_shape", fc.output_shape),
            ("output_description", fc.output_description),
        )
        if not value
    ]
    if missing:
        raise ProposalContractRenderError(
            "cannot render the proposal commit prompt: the forward contract "
            f"declares no {', '.join(missing)}. Populate configs/task_config.yaml "
            "(or pass a complete ForwardContract) — refusing to send a commit "
            "prompt whose I/O contract is empty."
        )
    return (
        PROPOSAL_COMMIT_PROMPT.replace("{INPUT_SHAPE}", fc.input_shape)
        .replace("{OUTPUT_SHAPE}", fc.output_shape)
        .replace("{OUTPUT_DESCRIPTION}", fc.output_description)
        .replace("{CLASSIFIER_LOSSES}", _render_loss_legality(CLASSIFICATION_LOSSES))
        .replace("{REGRESSOR_LOSSES}", _render_loss_legality(REGRESSION_LOSSES))
        # Step 12 / PR-12a C7-5 — the tier-(iii) literals this renderer's own
        # docstring deferred to "a later step". Shapes derived from the
        # declaration, prose from the task, and an undeclared task gets the
        # shape rather than TIDMAD's noun for it.
        .replace("{CLASSIFIER_OUTPUT_SHAPE}", render_classifier_output_shape(fc))
        .replace("{REGRESSOR_EMITS}", render_regressor_output_form(fc, blocks, with_dtype=False))
        .replace(
            "{REGRESSOR_OUTPUT_FORM}", render_regressor_output_form(fc, blocks, with_dtype=True)
        )
        .replace("{INPUT_SEMANTICS}", render_input_semantics(blocks))
        .replace("{CLASS_AXIS_NOTE}", render_class_axis_note(fc, blocks))
        .replace("{PER_FILE_STRATEGY_DIRECTIONS}", render_per_file_strategy_directions(blocks))
        .replace(
            "{EVIDENCE_RATIONALE_CLAUSE}", _declared(blocks, "evidence_rationale_clause") or ""
        )
    ) + ("" if not allowed_output_types else _output_type_constraint_note(allowed_output_types))


def _build_commit_prompt(reasoning: str, existing_model_types: list) -> str:
    """Build the user prompt for the commit call, injecting the reasoning."""
    return (
        f"## Your Reasoning\n\n{reasoning}\n\n"
        f"---\n\n"
        f"## Reminder — your model_name must NOT be any of: {existing_model_types}\n\n"
        "Now output the JSON proposal."
    )


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------


class MLModelProposalAgent:
    """
    Proposal agent — Node 3 in the SIDERIUS graph.

    Supports two modes:
      - **Legacy mode**: 2-call pattern (reasoning + commit). Used when
        ``reasoning_pipeline`` has no stages or ``use_pipeline=False``.
      - **Pipeline mode**: 3-stage configurable pipeline (comparison →
        causal reasoning → proposing). Used when ``reasoning_pipeline``
        has stages configured. See docs/adaptive_new_model_proposer.md §2A.

    Constructor DI (``bridge_factory``) follows PR #24's pattern: optional
    factory param, defaults to the real ``LLMBridge`` class. Tests can
    inject a ``RecordingLLMBridge``. The existing ``(provider, model_id)``
    interface is preserved for backward compat.
    """

    def __init__(
        self,
        provider: str = "gemini",
        model_id: str = "gemini-3.1-flash-lite-preview",
        max_retries: int | None = None,
        bridge_factory=None,
        capability_index_path: str | None = None,
        **kwargs,
    ):
        # **kwargs absorbs per-stage kwargs from ProposalLLMConfig flattening
        # (comparison_provider, reasoning_model_id, etc.) — these are for
        # future per-stage bridge routing, currently unused.
        self._bridge_factory = bridge_factory or LLMBridge
        self.bridge = self._bridge_factory(
            provider=provider,
            model_id=model_id,
            max_retries=max_retries,
        )
        # L5b — registry handle for loss-awareness rendering in the proposer
        # prompt. Mirrors the L4b implementor DI pattern. Tests pass
        # ``capability_index_path=str(tmp_path / "_capability_index.json")``
        # to avoid contaminating the canonical index; production callers
        # leave it None to use ``agent_generated/_capability_index.json``.
        self._registry = CapabilityRegistry(index_path=capability_index_path)

    def run(self, inp: ProposalInput) -> ProposalOutput:
        evidence = inp.interpretation_evidence
        print(f"Proposing new architecture based on interpretation of {evidence.model_types} ...")

        # Decide: pipeline mode or legacy mode
        has_pipeline = (
            inp.reasoning_pipeline
            and inp.reasoning_pipeline.stages
            and any(s.enabled for s in inp.reasoning_pipeline.stages)
        )

        output = self._run_pipeline(inp) if has_pipeline else self._run_legacy(inp)

        # V21 PR E — mint the candidate identity HERE: after the LLM JSON has
        # been parsed into a ProposalOutput, before it is persisted (O-E-4).
        # This is the single site covering both legacy and pipeline modes.
        # Unconditional assignment: even if a raw payload smuggled an id past
        # a parser whitelist, the system's mint overwrites it — the id is
        # never LLM-generated and never derived from model_name.
        output.candidate_id = f"cand_{uuid.uuid4().hex}"

        # --- Persist ---
        if inp.storage.backend == "local" and inp.storage.local:
            workspace = inp.storage.local.workspace
            run_name = inp.storage.local.run_name
            os.makedirs(workspace, exist_ok=True)
            out_path = os.path.join(workspace, f"proposal_{run_name}.json")
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(output.model_dump_json(indent=4))
            print(f"Proposal saved -> {out_path}")

        return output

    # ------------------------------------------------------------------
    # Legacy mode (existing 2-call pattern, backward compat)
    # ------------------------------------------------------------------

    def _run_legacy(self, inp: ProposalInput) -> ProposalOutput:
        """Original 2-call pattern: reasoning (text) + commit (JSON).

        C1 (runtime_estimation_and_calibration.md §23-C1): the static
        time pre-flight is ADVISORY ONLY — a single commit call, no
        reject-revise loop, no rejection text in prompts. An over-budget
        static estimate is recorded as a labeled advisory on the output.
        Legacy mode has no structural-retry inner loop — a
        schema-violating draft raises immediately (unchanged behavior).
        """
        reasoning_prompt = _build_reasoning_prompt(inp)
        print(f"    [PROMPT_SIZE] proposer_reasoning: {len(reasoning_prompt)} chars")
        # System prompt has its {TASK_BACKGROUND} placeholder substituted at
        # call time from inp.task_description + inp.forward_contract; see
        # docs/design/enable_global_task_config.md § Commit T3.
        reasoning_system_prompt = _build_reasoning_system_prompt(inp)
        reasoning = self.bridge.generate_text(
            reasoning_system_prompt,
            reasoning_prompt,
            label="proposer.legacy_reasoning",
        )
        print(f"   Legacy reasoning complete ({len(reasoning)} chars).")

        commit_prompt = _build_commit_prompt(reasoning, inp.existing_model_types)
        raw = self.bridge.generate(
            _render_commit_system_prompt(
                inp.forward_contract,
                inp.proposal_blocks,
                allowed_output_types=inp.allowed_output_types,
            ),
            commit_prompt,
            label="proposer.legacy_commit",
        )

        proposed_name = raw.get("model_name", "")
        if proposed_name in inp.existing_model_types:
            raise ValueError(
                f"LLM proposed model_name '{proposed_name}' which already exists in "
                f"existing_model_types: {inp.existing_model_types}. "
                f"Re-run or adjust the constraints."
            )

        output = ProposalOutput.model_validate(
            {
                "model_name": proposed_name,
                # V21 PR A: the allow-list is explicit, so a field absent here is
                # SILENTLY dropped and the schema default applies. Gate 1R caught
                # exactly that: the agent complied, and output_type never arrived.
                "output_type": raw.get(
                    "output_type", _default_output_type(inp.allowed_output_types)
                ),
                "model_description": raw.get("model_description", ""),
                "mathematical_definition": raw.get("mathematical_definition", ""),
                "motivation": raw.get("motivation", ""),
                "expert_advice": raw.get("expert_advice", {}),
                "baseline_config": raw.get("baseline_config", {}),
                "parameter_count_estimate": raw.get("parameter_count_estimate"),
                "custom_loss_spec": raw.get("custom_loss_spec"),
            },
            context={
                "loss_registry_names": live_loss_registry_names(self._registry),
                "model_registry_names": _live_model_registry_names(self._registry),
                "allowed_output_types": inp.allowed_output_types,
            },
        )

        factor = _run_preflight_check(inp, output)
        if factor is not None and factor > 1.0:
            print(
                f"   Pre-flight advisory (factor={factor:.2f}x, "
                f"static_uncalibrated — no revision requested)."
            )
        print(f"Proposed model (legacy): '{output.model_name}'")
        return output

    # ------------------------------------------------------------------
    # Pipeline mode (B.11 + B.12 — 3-stage reasoning pipeline)
    # ------------------------------------------------------------------

    def _run_pipeline(self, inp: ProposalInput) -> ProposalOutput:
        """Three-stage pipeline: comparison → reasoning → proposing."""
        from agent.prompt_templates.proposal import (
            load_stage_prompt,
            render_agent_cards,
            render_available_losses,
            render_available_models,
            render_expert_context,
        )
        from nodes.proposal_helpers import (
            build_score_summary_line,
            clamp_and_backstop_accumulated,
            enrich_candidates_with_source,
            resolve_exploration_mode,
            select_candidate_models,
        )

        pipeline = inp.reasoning_pipeline
        policy = pipeline.policy

        # B.16a — resolve exploration mode
        evidence = inp.interpretation_evidence
        order = evidence_order(evidence)
        mode = resolve_exploration_mode(evidence, pipeline)
        print(
            f"   Pipeline mode: {mode} | stages: {[s.name for s in pipeline.stages if s.enabled]}"
        )

        # B.10 — pre-filter models
        candidates = select_candidate_models(evidence, pipeline.model_selection)
        # Enrich with source code + descriptions for the comparison stage
        candidates = enrich_candidates_with_source(candidates)
        source_counts = sum(1 for c in candidates if c.get("source_code"))

        # Build lightweight summaries for models excluded by the pre-filter.
        # These models were tested but did not make the top-N cut. Their source
        # code is intentionally omitted (that is the point of filtering), but
        # the LLM still needs to know: what was tried, why it fell short, and
        # what we learned — so it can avoid repeating past failures and build
        # on partial successes.
        _CACHE_TEXT_FIELDS = (
            "key_findings",
            "bottlenecks",
            "score_trend",
            "strategy_assessment",
        )
        candidate_names = {c["model_type"] for c in candidates}
        cache = evidence.model_knowledge_cache or {}
        descriptions = evidence.model_descriptions or {}
        per_best = evidence.per_model_best_valid or {}
        score_tables = evidence.per_model_score_tables or {}

        non_candidates_overview = []
        for mt in evidence.model_types:
            if mt in candidate_names:
                continue
            entry = cache.get(mt) or {}
            overview: dict = {
                "model_type": mt,
                "best_score": per_best.get(mt),
                "description": descriptions.get(mt),
            }
            # Phase 5 C: compact score-table summary so the LLM sees the
            # per-file recovery context without the 20-row markdown weight.
            table = score_tables.get(mt)
            summary_line = build_score_summary_line(table.model_dump() if table else None)
            if summary_line:
                overview["score_summary"] = summary_line
            for field in _CACHE_TEXT_FIELDS:
                if entry.get(field):
                    overview[field] = entry[field]
            non_candidates_overview.append(overview)

        print(
            f"   Candidates: {[c['model_type'] for c in candidates]} "
            f"({len(candidates)} models, {source_counts} with source code); "
            f"non-candidates: {[o['model_type'] for o in non_candidates_overview]}"
        )

        # Prepare shared context for all stages.
        # P-d: hardware + constraints blocks are now rendered in pipeline mode
        # (pre-P-d these were rendered only in legacy mode at _build_reasoning_prompt
        # so production runs never saw them — dangling pointers in the system prompts).
        hardware_block = _render_hardware_context_block(inp.hardware_context, inp.vram_budget_gb)
        data_scope_block = _render_data_scope_block(inp.data_scope)
        constraints_block = _render_constraints_block(inp.constraints, inp.existing_model_types)
        agent_cards_block = render_agent_cards(inp.agent_cards)
        expert_context_block = render_expert_context(inp.expert_context)
        vocab_block = self._render_vocabulary(inp.vocab_seed)
        # Explicit cold-start banner — empty string unless inp.cold_start is True,
        # so seeded prompts are byte-for-byte unchanged.
        cold_start_block = _render_cold_start_block(inp.cold_start)

        # --- Run enabled reasoning stages (accumulate context) ---
        accumulated = {
            "candidates": candidates,
            "non_candidates_overview": non_candidates_overview,
            "interpretation_summary": build_interpretation_summary(evidence),
            "existing_model_types": inp.existing_model_types,
            "previous_failures": inp.previous_failures,
        }

        # Count confirmed feature→capability links: entries with non-empty related_to.
        def _get_related(entry) -> list:
            if hasattr(entry, "related_to"):
                return entry.related_to or []
            if isinstance(entry, dict):
                return entry.get("related_to") or []
            return []

        n_confirmed_links = sum(1 for v in inp.vocab_seed if _get_related(v))
        template_vars = {
            "minimum_boldness": str(policy.minimum_boldness),
            "n_agent_proposed": str(len([c for c in candidates if c.get("source") != "seed"])),
            "n_confirmed_links": str(n_confirmed_links),
            "existing_model_types": ", ".join(inp.existing_model_types),
            # PR 01a (S1-B): the proposing stage's output-contract table
            # states loss legality; it now DERIVES from the same authority
            # the validator uses instead of restating it. Only the legality
            # cells are extracted — the table's dtype-dropped shape column
            # is a different surface form with no declared formatting rule
            # (design §4.1 tier (ii); OD-S1-7 rejected inventing one).
            "CLASSIFIER_LOSS_LIST": _render_loss_legality(CLASSIFICATION_LOSSES),
            "REGRESSOR_LOSS_LIST": _render_loss_legality(REGRESSION_LOSSES),
            # Step 12 / PR-12a C7 (D-12a-6, Pr2) — what this task's output
            # representations MEAN. The SHAPES beside it already come from the
            # run's ForwardContract; this is the prose. A task that declares
            # none renders nothing, so the shapes stand alone rather than
            # carrying "256 amplitude bins" for a task that has none.
            "OUTPUT_CONTRACT_GUIDANCE": render_output_contract_guidance(inp.proposal_blocks),
            # Proposing-stage placeholder. Other stages don't reference it; the
            # template_vars replace is a no-op when the placeholder is absent.
            # See docs/improving_validation_awareness.md Phase A.2/A.3.
            # C12-P-P / P1-A — the applicable dataset, not the TIDMAD
            # singleton. A task declaring no TIDMAD topology renders "" here,
            # matching what B3's validator will actually enforce on it.
            "known_constraints_block": _format_known_constraints_block(
                _applicable_dataset_constraints()
            ),
            # Phase N (§14.N.3) — proposing-stage placeholder for the
            # aggregate-window gate-exhaustion report across up to the
            # last 3 tuner iterations. Empty list collapses to "".
            "recent_gate_exhaustions_block": _format_recent_gate_exhaustions_block(
                inp.recent_gate_exhaustions
            ),
            # V20 PR D (D-C6) — the all-trials-invalid report for the same
            # window. Empty list collapses to "".
            "recent_trial_validity_block": _format_recent_trial_validity_block(
                inp.recent_trial_validity
            ),
            # V19 PR 3 (§3.7) — structured HealthGate evidence for the
            # PRODUCTION pipeline path (P3-V1 reopen fix: the legacy-mode
            # splice in _build_reasoning_prompt never reached pipeline
            # mode). Same mechanism as the §14.N variable above; ""
            # when the flag is OFF or no supported evidence exists, so
            # the placeholder collapses and the OFF prompt is unchanged.
            "healthgate_evidence_block": (
                render_healthgate_evidence_block(evidence)
                if inp.enable_structured_health_feedback
                else ""
            ),
            # T3 — task config injection, JOINed to the pipeline stages by
            # PR 01b (S1-C). {forward_contract} is rendered into
            # proposing_stage.md; {task_background_block} is rendered into
            # ALL THREE stage base templates, so the stages that choose the
            # architecture family are no longer task-blind.
            #
            # Both keys are LOWERCASE because load_stage_prompt builds its
            # search token as f"{{{key}}}" from the key verbatim
            # (agent/prompt_templates/proposal/__init__.py) — an UPPERCASE
            # {TASK_DESCRIPTION} placeholder in a proposal stage template
            # could never substitute and would ship a literal brace token to
            # the LLM. (The uppercase form IS correct for the literature-
            # review templates and for PROPOSAL_REASONING_PROMPT, which do
            # their own explicit replace — a different surface.)
            #
            # See docs/design/enable_global_task_config.md § Commit T3 and
            # docs/design/generic_framework_upgrade/
            # step_01_proposer_hypothesis_space/pr_01b_task_description_join.md
            # § 4.1.
            # D1 / D2 (Step 10 / P3 C4) — the ONLY intentional LLM-facing
            # semantic deltas this PR makes, beside D3's static rewrite in
            # comparison_stage.md. Both render from the run's DECLARED metric
            # identity through the existing direction authority; neither
            # decides a direction here. The proposing stage declares neither
            # placeholder, so both are no-ops there — it neither ranks nor
            # authors a prediction (design §4.5).
            "metric_context_block": render_metric_context_block(evidence),
            "falsifiable_prediction_example": render_falsifiable_prediction_example(evidence),
            "task_background_block": _render_pipeline_task_background(inp.task_description),
            "forward_contract": render_forward_contract(inp.forward_contract),
            # L5b — loss-registry awareness. Rendered once per run() so all
            # stage prompts see a consistent snapshot of the registry — a
            # mid-run write (e.g. by the implementor in a parallel iteration)
            # would not retroactively change earlier stages' context. Empty
            # registry collapses to the fallback message ("No custom losses
            # registered yet — propose a new one..."). See
            # docs/design/enable_loss_inventory.md § Commit L5.
            "available_losses_block": render_available_losses(self._registry),
            # Symmetric for the model surface — rendered into the
            # ``{available_models_block}`` placeholder by the proposing
            # stage so the LLM can pick Branch B (reuse) for the model
            # config when an existing plugin already implements the
            # intended architecture. Empty registry collapses to the
            # fallback message ("No custom models registered yet...").
            # arXiv U3 (#260): under isolation the block names no bundled
            # built-in and offers no built-in branch; otherwise byte-identical.
            "available_models_block": render_available_models(
                self._registry, baseline_isolation=inp.baseline_isolation
            ),
        }

        for stage in pipeline.stages:
            if not stage.enabled:
                continue

            # Map system_prompt_key to filename:
            # COMPARATIVE_ANALYSIS → comparison_stage
            # CAUSAL_REASONING → causal_reasoning_stage
            stage_file_map = {
                "COMPARATIVE_ANALYSIS": "comparison_stage",
                "CAUSAL_REASONING": "causal_reasoning_stage",
            }
            stage_filename = stage_file_map.get(
                stage.system_prompt_key,
                stage.system_prompt_key.lower() + "_stage",
            )
            system_prompt = load_stage_prompt(
                stage_filename,
                exploration_mode=mode,
                template_vars=template_vars,
                mindset=inp.mindset,
                baseline_isolation=inp.baseline_isolation,
            )

            # Build user prompt in the P-d order:
            #   1. [HARDWARE CONTEXT] block
            #   2. ## Constraints block
            #   3. ## External Contributors block
            #   4. ## Expert Context block
            #   5. Candidate markdown + accumulated JSON region
            #   6. Vocab block
            # Findings now precede the experiment-history dump so the LLM
            # reads external calibration before anchoring on past results
            # (position-bias fix, Problem 3 of the audit).
            clamped_accumulated = clamp_and_backstop_accumulated(
                accumulated,
                top_k=policy.comparative_analysis_top_k,
                max_chars=policy.prior_stage_max_chars,
                input_keys=_PROPOSER_INPUT_KEYS,
                order=order,
            )
            user_prompt_parts: list[str] = []
            if cold_start_block:
                user_prompt_parts.append(cold_start_block)
            if hardware_block:
                user_prompt_parts.append(hardware_block)
            if data_scope_block:
                user_prompt_parts.append(data_scope_block)
            if constraints_block:
                user_prompt_parts.append(constraints_block)
            if agent_cards_block:
                user_prompt_parts.append(agent_cards_block)
            if expert_context_block:
                user_prompt_parts.append(expert_context_block)
            user_prompt_parts.append(_render_stage_user_prompt(clamped_accumulated))
            if vocab_block:
                user_prompt_parts.append(vocab_block)
            user_prompt = "\n\n".join(user_prompt_parts)

            print(f"   Stage '{stage.name}': calling LLM... [PROMPT_SIZE] {len(user_prompt)} chars")
            stage_audit = _audit_proposer_components(
                inp=inp,
                accumulated=clamped_accumulated,
                agent_cards_block=agent_cards_block,
                expert_context_block=expert_context_block,
                vocab_block=vocab_block,
                system_prompt=system_prompt,
                stage_name=stage.name,
            )
            stage_label = f"proposer.{stage.name}"
            if stage.output_mode == "text":
                result = self.bridge.generate_text(
                    system_prompt,
                    user_prompt,
                    label=stage_label,
                    components=stage_audit["components"],
                )
                accumulated[stage.name] = result
            else:
                result = self.bridge.generate(
                    system_prompt,
                    user_prompt,
                    label=stage_label,
                    components=stage_audit["components"],
                )
                accumulated[stage.name] = result

            print(f"   Stage '{stage.name}': done.")

        # --- Boldness check: re-run causal_reasoning if prediction is too timid ---
        # Mirrors the B.22 proposing-stage retry but targets Stage 2 specifically.
        # Stage 1 (comparison) is expensive; we never re-run it for a boldness violation.
        reasoning_raw = accumulated.get("causal_reasoning")
        if isinstance(reasoning_raw, dict):
            pred_raw = reasoning_raw.get("falsifiable_prediction")
            if pred_raw and isinstance(pred_raw, dict):
                try:
                    pred = FalsifiablePrediction.model_validate(pred_raw)
                    if pred.boldness < policy.minimum_boldness:
                        print(
                            f"   Boldness check: boldness={pred.boldness:.4f} < "
                            f"minimum_boldness={policy.minimum_boldness} — "
                            f"retrying causal_reasoning."
                        )
                        accumulated.setdefault("proposing_stage_errors", []).append(
                            f"BOLDNESS_TOO_LOW: prediction boldness={pred.boldness:.4f} "
                            f"is below minimum_boldness={policy.minimum_boldness}. "
                            f"Current: {pred.current_value}, "
                            f"Predicted: {pred.predicted_value}. "
                            f"Make a bolder prediction — increase the delta between "
                            f"current and predicted value."
                        )
                        reasoning_stage = next(
                            (
                                s
                                for s in pipeline.stages
                                if s.name == "causal_reasoning" and s.enabled
                            ),
                            None,
                        )
                        if reasoning_stage is not None:
                            retry_system = load_stage_prompt(
                                "causal_reasoning_stage",
                                exploration_mode=mode,
                                template_vars=template_vars,
                                mindset=inp.mindset,
                                baseline_isolation=inp.baseline_isolation,
                            )
                            clamped_accumulated = clamp_and_backstop_accumulated(
                                accumulated,
                                top_k=policy.comparative_analysis_top_k,
                                max_chars=policy.prior_stage_max_chars,
                                input_keys=_PROPOSER_INPUT_KEYS,
                                order=order,
                            )
                            # P-d order: hardware → constraints → cards →
                            # context → accumulated → vocab (matches the main
                            # reasoning-stage assembly above).
                            retry_parts: list[str] = []
                            if hardware_block:
                                retry_parts.append(hardware_block)
                            if data_scope_block:
                                retry_parts.append(data_scope_block)
                            if constraints_block:
                                retry_parts.append(constraints_block)
                            if agent_cards_block:
                                retry_parts.append(agent_cards_block)
                            if expert_context_block:
                                retry_parts.append(expert_context_block)
                            retry_parts.append(_render_stage_user_prompt(clamped_accumulated))
                            if vocab_block:
                                retry_parts.append(vocab_block)
                            retry_user = "\n\n".join(retry_parts)
                            print("   Stage 'causal_reasoning': retrying (boldness)...")
                            retry_audit = _audit_proposer_components(
                                inp=inp,
                                accumulated=clamped_accumulated,
                                agent_cards_block=agent_cards_block,
                                expert_context_block=expert_context_block,
                                vocab_block=vocab_block,
                                system_prompt=retry_system,
                                stage_name="causal_reasoning",
                            )
                            accumulated["causal_reasoning"] = self.bridge.generate(
                                retry_system,
                                retry_user,
                                label="proposer.causal_reasoning",
                                components=retry_audit["components"],
                            )
                except (ValidationError, Exception):
                    # Malformed prediction — corrected by the causal-owned
                    # validation block below (P-1 fix). The old assumption
                    # ("let the proposing stage handle it") was wrong: the
                    # proposing-stage retry re-injects this stage's values
                    # verbatim and can never correct them.
                    pass

        # --- P-1 fix (PR 3 audit §13): validate causal-stage-owned fields ---
        # inherited_components + falsifiable_prediction are extracted from
        # accumulated["causal_reasoning"] below and re-injected verbatim into
        # ProposalOutput.model_validate on EVERY proposing structural attempt.
        # A validation error in them is therefore uncorrectable downstream —
        # it must be corrected here, by the stage whose retry can reach the
        # producing response. Runs AFTER the boldness block because a boldness
        # retry may have replaced the causal output with a new, unvalidated
        # response. A pipeline without a causal_reasoning stage validates the
        # empty defaults and passes unchanged.
        causal_raw = accumulated.get("causal_reasoning")
        for causal_attempt in range(_MAX_CAUSAL_CORRECTION_RETRIES + 1):
            causal_dict = causal_raw if isinstance(causal_raw, dict) else {}
            try:
                # Same extraction expressions as the proposing-stage assembly
                # below — the two must agree on what gets validated.
                CausalStageOwnedContent.model_validate(
                    {
                        "inherited_components": causal_dict.get("inherited_components", []),
                        "falsifiable_prediction": causal_dict.get("falsifiable_prediction"),
                    }
                )
                break
            except ValidationError as exc:
                error_summary = "; ".join(
                    f"{' → '.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:5]
                )
                if causal_attempt == _MAX_CAUSAL_CORRECTION_RETRIES:
                    raise RuntimeError(
                        f"Causal-reasoning stage output failed validation of its "
                        f"causal-owned fields (inherited_components / "
                        f"falsifiable_prediction) after "
                        f"{_MAX_CAUSAL_CORRECTION_RETRIES} correction retries. "
                        f"Last error: {error_summary}"
                    ) from exc
                print(
                    f"   Stage 'causal_reasoning': causal-owned field validation "
                    f"failed (attempt {causal_attempt + 1}/"
                    f"{_MAX_CAUSAL_CORRECTION_RETRIES + 1}) — retrying with "
                    f"focused error feedback."
                )
                correction_system = load_stage_prompt(
                    "causal_reasoning_stage",
                    exploration_mode=mode,
                    template_vars=template_vars,
                    mindset=inp.mindset,
                    baseline_isolation=inp.baseline_isolation,
                )
                clamped_accumulated = clamp_and_backstop_accumulated(
                    accumulated,
                    top_k=policy.comparative_analysis_top_k,
                    max_chars=policy.prior_stage_max_chars,
                    input_keys=_PROPOSER_INPUT_KEYS,
                    order=order,
                )
                # P-d order — mirrors the boldness-retry assembly above.
                correction_parts: list[str] = []
                if hardware_block:
                    correction_parts.append(hardware_block)
                if data_scope_block:
                    correction_parts.append(data_scope_block)
                if constraints_block:
                    correction_parts.append(constraints_block)
                if agent_cards_block:
                    correction_parts.append(agent_cards_block)
                if expert_context_block:
                    correction_parts.append(expert_context_block)
                correction_parts.append(_render_stage_user_prompt(clamped_accumulated))
                if vocab_block:
                    correction_parts.append(vocab_block)
                correction_user = "\n\n".join(correction_parts) + (
                    "\n\n## VALIDATION ERROR — CORRECT AND RESEND\n"
                    "Your previous response failed schema validation of "
                    "causal-stage-owned fields:\n"
                    f"{error_summary}\n"
                    "Return the FULL corrected JSON object (same output schema "
                    "as instructed above), fixing ONLY the invalid fields and "
                    "keeping every other field unchanged."
                )
                correction_audit = _audit_proposer_components(
                    inp=inp,
                    accumulated=clamped_accumulated,
                    agent_cards_block=agent_cards_block,
                    expert_context_block=expert_context_block,
                    vocab_block=vocab_block,
                    system_prompt=correction_system,
                    stage_name="causal_reasoning",
                )
                causal_raw = self.bridge.generate(
                    correction_system,
                    correction_user,
                    label="proposer.causal_reasoning.correction",
                    components=correction_audit["components"],
                )
        if causal_raw is not accumulated.get("causal_reasoning"):
            # Only write back when a correction actually replaced the output —
            # never insert a causal_reasoning key into a pipeline that has no
            # causal stage.
            accumulated["causal_reasoning"] = causal_raw

        # --- B.12 + B.22: Proposing stage (always runs last, retries on validation failure) ---
        proposing_prompt = load_stage_prompt(
            "proposing_stage",
            exploration_mode=mode,
            template_vars=template_vars,
            baseline_isolation=inp.baseline_isolation,
        )
        # arXiv #259 — same authority as the legacy commit prompt; appended
        # ONLY when the run declares a constraint, so unconstrained pipeline
        # prompts stay byte-identical.
        if inp.allowed_output_types:
            proposing_prompt += _output_type_constraint_note(inp.allowed_output_types)

        # Phase K.8 debug instrumentation: optionally dump the rendered
        # proposing-stage system prompt so smoke runs can audit the exact
        # text the LLM saw (in particular the K.7.6 [PRIOR ITERATION GATE
        # EXHAUSTION] block). No-op when the field is None (default).
        if inp.debug_dump_proposing_prompt_path:
            from pathlib import Path

            dump_path = Path(inp.debug_dump_proposing_prompt_path)
            dump_path.parent.mkdir(parents=True, exist_ok=True)
            dump_path.write_text(proposing_prompt)
            print(f"   [debug] dumped proposing-stage system prompt → {dump_path}")

        # Extract scientific content from reasoning stages once — these don't change on retry.
        reasoning_output = accumulated.get("causal_reasoning", {})
        comparison_output = accumulated.get("comparison", {})
        if not isinstance(reasoning_output, dict):
            reasoning_output = {}
        if not isinstance(comparison_output, dict):
            comparison_output = {}

        inherited = reasoning_output.get("inherited_components", [])
        prediction = reasoning_output.get("falsifiable_prediction")
        vocab_links = comparison_output.get("proposed_vocab_links", [])
        # Separate candidates by kind: feature/capability → vocab pipeline; discovery → discoveries
        vocab_candidates = []
        discoveries = []
        for stage_output in [comparison_output, reasoning_output]:
            for candidate in stage_output.get("proposed_vocab_candidates", []):
                if not isinstance(candidate, dict):
                    continue
                kind = candidate.get("kind", "")
                if kind in {"feature", "capability"}:
                    vocab_candidates.append(candidate)
                elif kind == "discovery":
                    discoveries.append(candidate)

        # C1 (runtime_estimation_and_calibration.md §23-C1): the static time
        # pre-flight is ADVISORY ONLY — the former outer reject-revise loop
        # is removed. Schema errors are still handled by the structural-retry
        # loop below (unchanged behavior). Stages 1+2 are never re-run.
        output: ProposalOutput | None = None
        last_exc: Exception | None = None

        for attempt in range(_MAX_PROPOSING_RETRIES + 1):
            clamped_accumulated = clamp_and_backstop_accumulated(
                accumulated,
                top_k=policy.comparative_analysis_top_k,
                max_chars=policy.prior_stage_max_chars,
                input_keys=_PROPOSER_INPUT_KEYS,
                order=order,
            )
            # Proposing-stage user prompt — P-d order matches the reasoning
            # stages above except the vocab block is intentionally omitted
            # (proposing-stage prompts already cite vocab via system-prompt
            # template_vars; rendering it again would bloat the prompt).
            proposing_parts: list[str] = []
            if hardware_block:
                proposing_parts.append(hardware_block)
            if constraints_block:
                proposing_parts.append(constraints_block)
            if agent_cards_block:
                proposing_parts.append(agent_cards_block)
            if expert_context_block:
                proposing_parts.append(expert_context_block)
            proposing_parts.append(_render_stage_user_prompt(clamped_accumulated))
            proposing_user = "\n\n".join(proposing_parts)

            print(
                f"   Stage 'proposing': calling LLM "
                f"(structural {attempt + 1}/{_MAX_PROPOSING_RETRIES + 1})..."
            )
            # Proposing-stage user prompt does not append vocab_block
            # (only agent_cards + expert_context); the audit reflects
            # this so component sums match the actual prompt sent.
            proposing_audit = _audit_proposer_components(
                inp=inp,
                accumulated=clamped_accumulated,
                agent_cards_block=agent_cards_block,
                expert_context_block=expert_context_block,
                vocab_block="",
                system_prompt=proposing_prompt,
                stage_name="proposing",
            )
            raw = self.bridge.generate(
                proposing_prompt,
                proposing_user,
                label="proposer.proposing",
                components=proposing_audit["components"],
            )

            try:
                proposed_name = raw.get("model_name", "")
                if proposed_name in inp.existing_model_types:
                    raise ValueError(
                        f"model_name '{proposed_name}' already exists in "
                        f"existing_model_types: {inp.existing_model_types}. "
                        f"Choose a different name."
                    )

                output = ProposalOutput.model_validate(
                    {
                        "model_name": proposed_name,
                        # V21 PR A — see the note at the other construction site.
                        "output_type": raw.get(
                            "output_type", _default_output_type(inp.allowed_output_types)
                        ),
                        "model_description": raw.get("model_description", ""),
                        "mathematical_definition": raw.get("mathematical_definition", ""),
                        "motivation": raw.get("motivation", ""),
                        "expert_advice": raw.get("expert_advice", {}),
                        "baseline_config": raw.get("baseline_config", {}),
                        "inherited_components": inherited,
                        "falsifiable_prediction": prediction,
                        "proposed_vocab_links": vocab_links,
                        "proposed_vocab_candidates": vocab_candidates,
                        "proposed_discoveries": discoveries,
                        "memo_consistency_notes": raw.get("memo_consistency_notes", []),
                        "parameter_count_estimate": raw.get("parameter_count_estimate"),
                        "custom_loss_spec": raw.get("custom_loss_spec"),
                    },
                    context={
                        "loss_registry_names": live_loss_registry_names(self._registry),
                        "model_registry_names": _live_model_registry_names(self._registry),
                        "allowed_output_types": inp.allowed_output_types,
                    },
                )
                # Citation discipline — warnings, not hard failures.
                citation_violations = _check_citation_discipline(
                    source_refs=reasoning_output.get("source_refs", []),
                    causal_hypothesis=reasoning_output.get("causal_hypothesis", ""),
                    proposed_change=reasoning_output.get("proposed_change", ""),
                )
                if citation_violations:
                    output.memo_consistency_notes.extend(citation_violations)
                    print(
                        f"   Citation check: {len(citation_violations)} "
                        f"violation(s) appended to memo_consistency_notes."
                    )
                break  # structurally valid — proceed to pre-flight

            except (ValidationError, ValueError) as exc:
                last_exc = exc
                if isinstance(exc, ValidationError):
                    error_summary = "; ".join(
                        f"{' → '.join(str(loc_part) for loc_part in e['loc'])}: {e['msg']}"
                        for e in exc.errors()[:5]
                    )
                else:
                    error_summary = str(exc)

                if attempt < _MAX_PROPOSING_RETRIES:
                    print(
                        f"   Proposing attempt {attempt + 1} failed — injecting error and retrying."
                    )
                    errors_so_far = accumulated.get("proposing_stage_errors", [])
                    errors_so_far.append(
                        f"Attempt {attempt + 1} error: {error_summary}. "
                        f"Correct this in your next response."
                    )
                    accumulated["proposing_stage_errors"] = errors_so_far

        if output is None:
            raise RuntimeError(
                f"Proposing stage failed after {_MAX_PROPOSING_RETRIES + 1} "
                f"structural attempts. Last error: {last_exc}"
            ) from last_exc

        # ---- Static pre-flight ADVISORY on the structurally-valid draft ----
        # C1: advisory only (static_uncalibrated provenance) — recorded on
        # the output by _run_preflight_check; never a revision trigger.
        factor = _run_preflight_check(inp, output)
        if factor is not None and factor > 1.0:
            print(
                f"   Pre-flight advisory (factor={factor:.2f}x, "
                f"static_uncalibrated — no revision requested)."
            )
        print(f"Proposed model (pipeline): '{output.model_name}'")
        return output

    @staticmethod
    def _render_vocabulary(vocab_seed: list) -> str:
        """Render the full vocabulary seed into a prompt block.

        Renders all four kinds: feature, capability, discovery, candidate.
        Discoveries carry empirical CONFIRMED/REFUTED/PARTIAL outcomes and are
        critical for the feedback loop — the proposer must see them.
        """
        if not vocab_seed:
            return ""

        # Handle both VocabEntry objects and dicts
        def _get(entry, key, default: Any = ""):
            if hasattr(entry, key):
                return getattr(entry, key)
            if isinstance(entry, dict):
                return entry.get(key, default)
            return default

        features = [v for v in vocab_seed if _get(v, "kind") == "feature"]
        capabilities = [v for v in vocab_seed if _get(v, "kind") == "capability"]
        discoveries = [v for v in vocab_seed if _get(v, "kind") == "discovery"]
        candidates = [v for v in vocab_seed if _get(v, "kind") == "candidate"]

        lines = ["## Vocabulary\n"]

        if features:
            lines.append("### Features (concrete building blocks)")
            for v in features:
                pattern = _get(v, "pattern")
                pat_str = f" [pattern: {pattern}]" if pattern else ""
                related = _get(v, "related_to", [])
                rel_str = f" → enables: {', '.join(related)}" if related else ""
                lines.append(f"- **{_get(v, 'name')}**: {_get(v, 'description')}{pat_str}{rel_str}")
            lines.append("")

        if capabilities:
            lines.append("### Capabilities (measurable architectural properties)")
            for v in capabilities:
                related = _get(v, "related_to", [])
                rel_str = f" ← enabled by: {', '.join(related)}" if related else ""
                lines.append(f"- **{_get(v, 'name')}**: {_get(v, 'description')}{rel_str}")
            lines.append("")

        if discoveries:
            lines.append("### Discoveries (empirical outcomes — CONFIRMED/REFUTED/PARTIAL)")
            lines.append(
                "These are the results of past falsifiable predictions. "
                "Use them to avoid repeating failures and to build on confirmed findings."
            )
            for v in discoveries:
                lines.append(f"- **{_get(v, 'name')}**: {_get(v, 'description')}")
            lines.append("")

        if candidates:
            lines.append("### Candidates (proposed but not yet confirmed)")
            for v in candidates:
                lines.append(f"- **{_get(v, 'name')}**: {_get(v, 'description')}")
            lines.append("")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="SIDERIUS ml_model_proposal_agent")
    parser.add_argument(
        "--workspace",
        type=str,
        default="./siderius_workspace",
        help="Root directory for reading interpretation output and writing proposal",
    )
    parser.add_argument(
        "--run_name",
        type=str,
        default="v1",
        help="Run name — reads interpretation_{run_name}.json, writes proposal_{run_name}.json",
    )
    parser.add_argument("--provider", type=str, default="gemini", choices=["gemini", "openai"])
    parser.add_argument("--model_id", type=str, default="gemini-3.1-flash-lite-preview")
    args = parser.parse_args()

    from core.generated_library import bind_generated_library_to_workspace

    bind_generated_library_to_workspace(args.workspace)

    interp_path = os.path.join(args.workspace, f"interpretation_{args.run_name}.json")
    if not os.path.exists(interp_path):
        raise FileNotFoundError(
            f"Interpretation file not found: {interp_path}\n"
            f"Run result_interpretation_agent first, or check --workspace and --run_name."
        )
    with open(interp_path, encoding="utf-8") as f:
        interpretation = json.load(f)

    # PR 01a: the standalone CLI must supply the task declaration.
    # Before the commit-prompt extraction an absent contract was harmless
    # (the prompt was a zero-placeholder constant); now the render is
    # FAIL-CLOSED, so a CLI that omitted the contract would raise. This
    # entry point is a documented architectural surface
    # (docs/architecture.md "Has CLI interface"), so it loads the shipped
    # declaration through the SAME canonical loader every other production
    # caller uses (workflows/model_exploration.py, scripts/...): no second
    # config path is introduced.
    _task_cfg = load_task_config()
    # Step 10 / P3 C1 — the standalone entrypoint builds its evidence through the
    # SAME projection the protocol uses, on the SAME shape: the interpreter
    # persists exactly ``model_dump_json``, so the file loaded above and the
    # in-memory dump the workflow passes are one input shape with two sources.
    # This is what makes "one authority, two entrypoints" true rather than
    # aspirational — before it, the CLI was a second reader of the raw mapping
    # that had already drifted from production (parent §3.6).
    evidence = build_proposer_evidence(interpretation)
    agent_input = ProposalInput.model_validate(
        {
            "interpretation_evidence": evidence,
            "task_description": get_task_description(_task_cfg),
            "forward_contract": _task_cfg["forward_contract"],
            "storage": {
                "backend": "local",
                "local": {"workspace": args.workspace, "run_name": args.run_name},
            },
        }
    )
    print(
        f"✅ Input validated: models={evidence.model_types} | "
        f"experiments={evidence.total_experiments}"
    )

    agent = MLModelProposalAgent(provider=args.provider, model_id=args.model_id)
    output = agent.run(agent_input)

    print(f"\n{'=' * 60}")
    print(f"  Proposal — {output.model_name}")
    print(f"{'=' * 60}")
    print(f"  Description : {output.model_description}")
    print(f"  Motivation  : {output.motivation}")
    print("\n  Mathematical definition:")
    print(f"    {output.mathematical_definition[:500]}...")
    print("\n  Expert advice:")
    print(f"    Focus areas    : {output.expert_advice.focus_areas}")
    print(f"    Constraints    : {output.expert_advice.constraints}")
    print(f"    Suggested dirs : {output.expert_advice.suggested_directions}")
    print("\n  Baseline config:")
    print(f"    {json.dumps(output.baseline_config, indent=4)}")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
