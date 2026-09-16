# agent/prompt_templates/proposal/__init__.py
"""
Prompt templates for the proposal agent's three-stage reasoning pipeline.

Templates are stored as .md files in this directory:
  - comparison_stage.md          (Stage 1 system prompt)
  - causal_reasoning_stage.md    (Stage 2 system prompt)
  - proposing_stage.md           (Stage 3 system prompt)
  - *_explore.md / *_exploit.md  (mode-specific additions)

The pipeline runner loads and assembles prompts at runtime via
load_stage_prompt() and render_expert_context().
"""

import os

from core.layout import checkout_path

_PROMPT_DIR = os.path.dirname(os.path.abspath(__file__))
# LEGACY CHECKOUT global losses dir (arXiv P1: read-only compatibility —
# promotions now land in the resolved generated-library losses dir, and
# ``live_loss_metadata`` accepts entries from EITHER location because both
# are on the training subprocesses' scan union).
_GLOBAL_LOSS_DIR = checkout_path("agent_generated", "losses")


def load_prompt(filename: str) -> str:
    """Load a prompt template from this directory."""
    path = os.path.join(_PROMPT_DIR, filename)
    with open(path, encoding="utf-8") as f:
        return f.read()


#: arXiv U3 (#260, ruling R6) — the worked examples inside
#: ``comparison_stage.md`` / ``causal_reasoning_stage.md`` used to hardcode
#: the shipped WaveNet baseline and its 5.57 score. They are now three named
#: substitution tokens; the LEGACY values below reproduce the pre-U3 template
#: bytes exactly (pinned by a byte-parity test), and the ISOLATED values name
#: no bundled architecture and no baseline figure.
LEGACY_EXAMPLE_LITERALS: dict[str, str] = {
    "example_model_type": "wavenet",
    "example_model_type_capitalized": "Wavenet",
    "example_sota_score": "5.57",
}

ISOLATED_EXAMPLE_LITERALS: dict[str, str] = {
    "example_model_type": "exemplar",
    "example_model_type_capitalized": "Exemplar",
    "example_sota_score": "1.23",
}


def proposal_example_literals(*, baseline_isolation: bool = False) -> dict[str, str]:
    """The example-literal substitutions for the stage templates.

    ``baseline_isolation=False`` (every legacy caller) yields the shipped
    baseline literals, so the rendered prompt is byte-identical to the
    pre-tokenized template. ``True`` yields neutral placeholders — an
    illustrative name that is not a shipped architecture and an
    illustrative score that is not the baseline's.
    """
    return dict(ISOLATED_EXAMPLE_LITERALS if baseline_isolation else LEGACY_EXAMPLE_LITERALS)


def load_stage_prompt(
    stage_name: str,
    exploration_mode: str = "explore",
    template_vars: dict | None = None,
    mindset: str | None = None,
    *,
    baseline_isolation: bool = False,
) -> str:
    """
    Load and assemble a stage's full system prompt.

    Loads the base template (e.g. ``comparison_stage.md``), injects the
    exploration/exploitation mode block, and substitutes template variables.

    The mindset block is injected at the ``{# EXPLORATION_MODE_BLOCK #}``
    placeholder. Priority:
      1. ``mindset`` argument (from advice file) — overrides the default
      2. ``{stage_name}_{exploration_mode}.md`` file — default fallback

    Args:
        stage_name: One of ``"comparison_stage"``, ``"causal_reasoning_stage"``,
                    ``"proposing_stage"``.
        exploration_mode: ``"explore"`` or ``"exploit"``.
        template_vars: Dict of ``{placeholder: value}`` for substitution.
                       E.g. ``{"minimum_boldness": "0.05", "n_agent_proposed": "3"}``.
        mindset: Optional mindset text from the advice file. When provided,
                 overrides the default ``_explore.md`` / ``_exploit.md`` block.
                 When absent, the mode file is used (backward compatible).
        baseline_isolation: arXiv U3 — selects the example literals (see
                 :func:`proposal_example_literals`). ``False`` renders the
                 legacy bytes; a caller's ``template_vars`` may still
                 override an example token explicitly.

    Returns:
        The assembled prompt string ready for the LLM.
    """
    base = load_prompt(f"{stage_name}.md")

    # Resolve mindset block: advice-provided mindset takes priority over mode file
    if mindset is not None:
        mode_block = mindset
    else:
        mode_file = f"{stage_name}_{exploration_mode}.md"
        mode_path = os.path.join(_PROMPT_DIR, mode_file)
        mode_block = load_prompt(mode_file) if os.path.exists(mode_path) else ""

    # Inject mode block into placeholder
    prompt = base.replace("{# EXPLORATION_MODE_BLOCK #}", mode_block)

    # Substitute template variables — the example literals first, so a
    # caller-supplied value for the same token still wins.
    merged = {
        **proposal_example_literals(baseline_isolation=baseline_isolation),
        **(template_vars or {}),
    }
    for key, value in merged.items():
        prompt = prompt.replace(f"{{{key}}}", str(value))

    return prompt


def render_agent_cards(cards: list) -> str:
    """
    Render agent name cards as a labeled 'Contributors' section.

    Called before render_expert_context() so the LLM reads who is
    contributing before it reads their specific findings.

    Args:
        cards: List of AgentCard dicts or Pydantic objects.

    Returns:
        Formatted string, or empty string when cards is empty (no noise
        in single-agent runs).
    """
    if not cards:
        return ""

    lines = [
        "## External Contributors\n",
        "Read each contributor's trust level and trust guidance before reading their findings.\n",
    ]
    for card in cards:
        if hasattr(card, "model_dump"):
            card = card.model_dump()
        name = card.get("agent_name", "unknown")
        lines.append(f"### {name}")
        # trust_level renders first — it is the machine-readable calibration the
        # proposer's synthesis rules reference; the prose fields are explanatory
        # context underneath.
        for field in (
            "trust_level",
            "role",
            "expertise_domain",
            "coverage",
            "limitations",
            "trust_guidance",
        ):
            val = card.get(field, "")
            if val:
                lines.append(f"  {field.replace('_', ' ').title()}: {val}")
        lines.append("")

    return "\n".join(lines)


def render_expert_context(items: list) -> str:
    """
    Render a list of ExpertContextItem dicts into a labeled prompt block.

    Groups items by kind, deduplicates by source_ref (last occurrence wins),
    and sorts each group by confidence descending (None last).
    The grouping and labeling IS the priority system — no explicit weights.

    Args:
        items: List of ExpertContextItem dicts (or Pydantic objects with
               .model_dump()).

    Returns:
        Formatted string ready for injection into any stage prompt.
    """
    if not items:
        return ""

    # Normalize to dicts
    normalized = []
    for item in items:
        if hasattr(item, "model_dump"):
            normalized.append(item.model_dump())
        else:
            normalized.append(item)

    # Deduplicate by source_ref — last occurrence wins (most recent agent's version kept)
    seen_cite_ids: dict[str, dict] = {}
    for item in normalized:
        source_ref = item.get("source_ref", "")
        seen_cite_ids[source_ref] = item
    deduplicated = list(seen_cite_ids.values())

    # Group by kind
    KIND_ORDER = ["empirical", "theoretical", "strategy_report", "human", "narrative", "literature"]
    KIND_LABELS = {
        "empirical": "EMPIRICAL FINDING",
        "theoretical": "THEORETICAL CONSTRAINT",
        "strategy_report": "STRATEGY REPORT",
        "human": "HUMAN DIRECTIVE",
        "narrative": "NARRATIVE CONTEXT",
        "literature": "LITERATURE REFERENCE",
    }

    groups: dict[str, list] = {}
    for item in deduplicated:
        kind = item.get("kind", "human")
        groups.setdefault(kind, []).append(item)

    # Sort each group by confidence descending; None sorts last
    def _conf_key(item: dict) -> float:
        c = item.get("confidence")
        return c if c is not None else -1.0

    lines = ["## Expert Context\n"]
    for kind in KIND_ORDER:
        if kind not in groups:
            continue
        for item in sorted(groups[kind], key=_conf_key, reverse=True):
            label = KIND_LABELS.get(kind, kind.upper())
            source = item.get("source", "unknown")
            confidence = item.get("confidence")
            conf_str = f", confidence={confidence}" if confidence is not None else ""
            source_ref = item.get("source_ref", "")

            lines.append(f"[{label}] (from {source}{conf_str}, source_ref={source_ref})")
            lines.append(f"  {item.get('content', '')}")
            lines.append("")

    # Handle any kinds not in KIND_ORDER
    for kind, items_in_group in groups.items():
        if kind in KIND_ORDER:
            continue
        for item in sorted(items_in_group, key=_conf_key, reverse=True):
            lines.append(f"[{kind.upper()}] (from {item.get('source', 'unknown')})")
            lines.append(f"  {item.get('content', '')}")
            lines.append("")

    return "\n".join(lines)


def render_data_analysis_evidence(evidence) -> str:
    """Render the one typed Data Analysis consumer view for the Proposer.

    ``None`` deliberately renders no bytes so analysis-disabled proposal
    prompts retain their legacy shape.  The renderer never opens report or
    skill artifact references.
    """

    if evidence is None:
        return ""
    if hasattr(evidence, "model_dump"):
        evidence = evidence.model_dump(mode="json")

    lines = [
        "## Data Analysis Evidence",
        f"Report: {evidence['report_ref']['logical_ref']} "
        f"(sha256={evidence['report_ref']['sha256']})",
        f"Executive summary: {evidence['executive_summary']}",
    ]
    for outcome in evidence.get("question_outcomes", []):
        lines.append(
            f"- Question {outcome['question_id']} [{outcome['status']}]: {outcome['summary']}"
        )
    for finding in evidence.get("findings", []):
        lines.append(
            f"- Finding {finding['finding_id']} "
            f"[{finding['confidence_level']} confidence]: {finding['statement']}"
        )
        lines.append(f"  Modeling relevance: {finding['modeling_relevance']}")
        lines.append(f"  Methods: {', '.join(finding['method_skill_ids'])}")
        for measurement in finding.get("quantitative_evidence", []):
            unit = f" {measurement['unit']}" if measurement.get("unit") else ""
            lines.append(
                f"  Measurement {measurement['result_key']}: "
                f"{measurement['value']}{unit} ({measurement['description']})"
            )
    for limitation in evidence.get("limitations", []):
        lines.append(f"- Limitation: {limitation}")
    for question in evidence.get("unresolved_questions", []):
        lines.append(f"- Unresolved: {question}")
    lines.append(
        "Use these measurements as evidence. Do not treat analysis-level relevance as an "
        "architecture or preprocessing decision."
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# L5 — Loss-registry awareness in the proposer prompt
# ---------------------------------------------------------------------------


_LOSS_REGISTRY_EMPTY_FALLBACK = (
    "## Available custom losses\n\n"
    "No custom losses registered yet — propose a new one grounded in "
    "lit-review findings, or use a built-in loss.\n"
)


_MODEL_REGISTRY_EMPTY_FALLBACK = (
    "## Available custom models\n\n"
    "No custom models registered yet — propose a new architecture or use "
    "a built-in model_type (e.g. wavenet, punet, fcnet).\n"
)

#: arXiv U3 (#260, ruling R6) — the isolated fallback names no bundled
#: architecture and offers no built-in branch (such a proposal is refused).
_MODEL_REGISTRY_EMPTY_FALLBACK_ISOLATED = (
    "## Available custom models\n\n"
    "No custom models registered yet — propose a new architecture (bundled "
    "built-in model types are not available in this run).\n"
)


def live_loss_metadata(registry) -> list:
    """Return custom losses that training subprocesses can load reliably.

    Capability-index entries are durable metadata, but older entries may
    point into an iteration workspace that still exists while being absent
    from the global loss-plugin directories scanned by fresh subprocesses.
    Such entries are not valid Branch-B reuse candidates.  Keep the prompt
    inventory and proposal-schema context aligned by using this helper for
    both surfaces.

    arXiv P1 — "reliably loadable" means the entry's file sits in one of
    the GLOBAL members of ``_resolve_loss_dirs``'s scan union: the resolved
    generated-library losses dir (where promotions write now) or the legacy
    checkout ``agent_generated/losses`` (pre-migration promotions, read-only
    compatibility). Workspace paths remain excluded for the same reason as
    before.

    Duck-typed test metadata without ``file_path`` remains accepted for
    backward compatibility; production ``CapabilityMetadata`` always has it.
    """
    from core.generated_library import generated_library_is_workspace_bound, generated_losses_dir

    global_loss_dirs = {os.path.abspath(generated_losses_dir())}
    if not generated_library_is_workspace_bound() and _GLOBAL_LOSS_DIR is not None:
        global_loss_dirs.add(_GLOBAL_LOSS_DIR)
    live = []
    for meta in registry.list(capability_type="loss"):
        file_path = getattr(meta, "file_path", None)
        if file_path is None:
            live.append(meta)
            continue
        absolute_path = os.path.abspath(file_path)
        if (
            os.path.dirname(absolute_path) in global_loss_dirs
            and absolute_path.endswith(".py")
            and os.path.isfile(absolute_path)
        ):
            live.append(meta)
    return live


def live_loss_registry_names(registry) -> list[str]:
    """Return names that are safe for proposer Branch-B loss reuse."""
    return [meta.name for meta in live_loss_metadata(registry)]


def render_available_losses(registry) -> str:
    """Render the loss-registry block for the proposer's prompt context.

    Pulls all entries with ``capability_type="loss"`` from the registry,
    sorts by ``created_at`` descending (most recently generated first —
    most recent generation is most likely to be relevant to the current
    bottleneck), and renders a markdown table of
    ``loss_name | source_iteration | description``.

    Args:
        registry: A ``CapabilityRegistry`` instance. Duck-typed: any
            object with a ``list(capability_type=...)`` method returning
            an iterable of ``CapabilityMetadata``-shaped objects (i.e.
            having ``name``, ``source_iteration``, ``description``,
            ``created_at`` attributes) is accepted, so tests can pass a
            simple stub without standing up a tmp index file.

    Returns:
        A multi-line string ready for ``str.replace`` substitution into
        the ``{available_losses_block}`` placeholder. Includes a trailing
        newline so the next template line follows naturally. When the
        registry has no ``loss`` entries, returns the documented fallback
        message (also ending in a newline).

    See ``docs/design/enable_loss_inventory.md`` § Commit L5.
    """
    return _render_loss_metadata(live_loss_metadata(registry))


def render_custom_loss_inventory(inventory) -> str:
    """Render one caller-resolved compatible inventory without re-reading storage."""

    if inventory.entries:
        return _render_loss_metadata(inventory.entries)
    if inventory.unavailable_reason and inventory.unavailable_reason != (
        "no loadable custom losses are registered"
    ):
        return (
            "## Available custom losses\n\n"
            f"Custom losses are unavailable for this run: {inventory.unavailable_reason}. "
            "Use the task's permitted builtin objective.\n"
        )
    return _LOSS_REGISTRY_EMPTY_FALLBACK


def _render_loss_metadata(metas) -> str:
    """Render already-filtered loss metadata; callers own eligibility."""

    if not metas:
        return _LOSS_REGISTRY_EMPTY_FALLBACK

    # ISO-8601 UTC strings sort chronologically; reverse=True puts the most
    # recent first. ``created_at`` is required by ``CapabilityMetadata``
    # (min_length=1) so this key is never empty.
    metas_sorted = sorted(metas, key=lambda m: m.created_at, reverse=True)

    lines = [
        "## Available custom losses",
        "",
        "The agent-generated loss registry currently contains the following "
        "losses, sorted most-recent first. You may **reuse** an existing entry "
        "by name OR **propose** a new one OR **use a built-in** loss type — "
        "see the 3-branch rule in the Rules section below.",
        "",
        "**Branch B vs Branch C judgment**: compare the formula below against "
        "the mechanism you want to introduce. If the existing loss already "
        "implements your intended mechanism, prefer Branch B (reuse) — adding "
        "a near-duplicate under a new name only fragments the evidence. "
        "Branch C is for genuinely novel mechanisms not captured below.",
        "",
    ]
    # L6c — subsection format (one ### block per loss). Safer than a markdown
    # table for multi-line mathematical definitions. Description stays on a
    # prose line (already normalised one-line by L4b); the formula gets its
    # own fenced code block so the LLM reads it as code, not flowing prose.
    for m in metas_sorted:
        desc = " ".join((m.description or "").split())
        source = m.source_iteration if m.source_iteration else "—"
        lines.append(f"### `{m.name}` (source: {source})")
        lines.append("")
        lines.append(f"**Description**: {desc}")
        # Back-compat: pre-L6c registry entries have mathematical_definition=""
        # — render the description only and skip the Formula block. When
        # non-empty, render the formula so the proposer can judge similarity
        # directly against a candidate Branch C without inferring the math.
        formula = (getattr(m, "mathematical_definition", "") or "").strip()
        if formula:
            lines.append("")
            lines.append("**Formula**:")
            lines.append("")
            lines.append("```")
            lines.append(formula)
            lines.append("```")
        lines.append("")
    return "\n".join(lines)


def render_available_models(registry, *, baseline_isolation: bool = False) -> str:
    """Render the model-registry block for the proposer's prompt context.

    ``baseline_isolation`` (arXiv U3, #260 / ruling R6): when True the block
    names no bundled built-in architecture and offers no built-in branch —
    the empty-registry fallback and the header sentence change; every
    per-entry line is unchanged. ``False`` renders the legacy bytes exactly.

    Symmetric to :func:`render_available_losses` but for the model surface.
    Pulls all entries with ``capability_type="model"`` from the registry,
    sorts by ``created_at`` descending, and renders one ``###`` block per
    model with description + architectural-definition fenced block.

    Phantom filter: entries in ``_capability_index.json`` whose name is
    NOT present in the live ``ml_models.models_sandbox.MODEL_REGISTRY`` are
    silently excluded from the rendered block. Historically the index and
    the runtime registry could disagree (implementor wrote the entry
    before the validator ran; validation failure left a phantom entry
    that the next proposer then advertised as a Branch B candidate — the
    v16 iter_015 ``gated_dilated_tcn`` failure mode). The
    ``feat/v16-fixes`` commit moved the registry write to post-validation
    so new phantoms cannot appear, but this filter also protects against
    any pre-existing pollution in older indexes. Tests that stub the
    registry can patch ``MODEL_REGISTRY`` — an empty patch is treated as
    "no filter applied" (any name in the stub registry is rendered) so
    the render-shape tests do not need to also stub the module registry.

    Args:
        registry: A ``CapabilityRegistry`` instance. Duck-typed: any
            object with a ``list(capability_type=...)`` method returning
            an iterable of ``CapabilityMetadata``-shaped objects is
            accepted, so tests can pass a simple stub.

    Returns:
        A multi-line string ready for ``str.replace`` substitution into
        the ``{available_models_block}`` placeholder. Includes a trailing
        newline so the next template line follows naturally. When the
        registry has no ``model`` entries (or every entry is a phantom),
        returns the documented fallback message.
    """
    metas = list(registry.list(capability_type="model"))
    # Lazy import so this module stays importable without the ml_models
    # side-effects (matters for docs builds and static analysis).
    from ml_models.models_sandbox import MODEL_REGISTRY

    if MODEL_REGISTRY:
        # Filter to entries whose plugin has actually loaded into the live
        # registry. When MODEL_REGISTRY is empty (fresh workspace / tests
        # that don't populate it), we skip the filter so legacy render
        # tests using stub registries continue to work unchanged.
        metas = [m for m in metas if m.name in MODEL_REGISTRY]

    if not metas:
        return (
            _MODEL_REGISTRY_EMPTY_FALLBACK_ISOLATED
            if baseline_isolation
            else _MODEL_REGISTRY_EMPTY_FALLBACK
        )

    metas_sorted = sorted(metas, key=lambda m: m.created_at, reverse=True)

    # The non-isolated sentence is the LEGACY bytes verbatim; the isolated one
    # drops the built-in branch, which the WITHOUT arm refuses anyway.
    branch_options = (
        "OR **propose** a new architecture — bundled built-in model types are "
        "not available in this run"
        if baseline_isolation
        else "OR **propose** a new architecture OR **use a built-in** model_type"
    )
    lines = [
        "## Available custom models",
        "",
        "The agent-generated model registry currently contains the following "
        "models, sorted most-recent first. You may **reuse** an existing "
        "entry by name (set ``baseline_config.model_config.model_name`` to "
        f"the entry's name) {branch_options} — see the 3-branch rule in the "
        "Rules section below.",
        "",
        "**Branch B vs Branch C judgment**: compare the description and "
        "architecture below against the design you have in mind. If the "
        "existing model already implements your intended architecture, "
        "prefer Branch B (reuse) — adding a near-duplicate under a new "
        "name only fragments the evidence and prevents controlled comparison "
        "(loss-explorer chains in particular MUST reuse the iter_001 model "
        "via Branch B for iter_002 onward to keep architecture as a CONTROL).",
        "",
    ]
    for m in metas_sorted:
        desc = " ".join((m.description or "").split())
        source = m.source_iteration if m.source_iteration else "—"
        lines.append(f"### `{m.name}` (source: {source})")
        lines.append("")
        lines.append(f"**Description**: {desc}")
        formula = (getattr(m, "mathematical_definition", "") or "").strip()
        if formula:
            lines.append("")
            lines.append("**Architecture**:")
            lines.append("")
            lines.append("```")
            lines.append(formula)
            lines.append("```")
        lines.append("")
    return "\n".join(lines)
