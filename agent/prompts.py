# agent/prompts.py
import inspect
import json
from typing import Any

# ==========================================
# 1. SYSTEM PROMPTS (The Core Logic)
# ==========================================
from agent.prompt_templates.tuner.rendering import (
    EFFICIENCY_BAND_PCT,
    render_builtin_model_roster,
    render_metric_identity_line,
    render_planner_dynamics_block,
    render_reflector_dynamics_block,
)

# Step 07 PR 07b (P2) — collapse advice about a health check the run does not
# actually run would tell the planner to look for a signal it can never
# receive. The PROSE stays here, its current owner (what class-127 mode
# collapse is, what a PSD amplitude collapse means is TIDMAD health semantics
# with no generic owner until Step 08 — an invented one would be worse than a
# recorded gap). What the authority decides is whether the sentence appears at
# all, and which check name it names.
_COLLAPSE_ADVICE_BY_CHECK = {
    "output_diversity": (
        "- `failure_reason` containing `{name}` means the model produced\n"
        "  near-constant values, commonly class-127 mode collapse.\n"
    ),
    "amplitude_collapse": (
        "- `failure_reason` containing `{name}` means the output PSD\n"
        "  amplitude collapsed relative to the reference.\n"
    ),
}


def render_collapse_advice(task_render, check_name: str) -> str:
    """One collapse-advice sentence, or "" when the run does not run that check.

    ``task_render is None`` keeps the shipped sentence: the direct callers of
    the prompt builders (tests, tooling) predate the run-scoped render object,
    and the bridge fails closed before a REAL render can reach here without one.
    """
    template = _COLLAPSE_ADVICE_BY_CHECK[check_name]
    if task_render is not None and not task_render.has_check(check_name):
        return ""
    return template.format(name=check_name)


def _builtin_roster(task_render) -> str:
    """The built-in architecture roster for the planner's output format.

    Falls back to the shipped registry when no run-scoped render object was
    supplied. That is the SAME authority, not a TIDMAD literal — the roster has
    no run-scoped variation today, because plugins are deliberately excluded
    from it.
    """
    if task_render is not None:
        return task_render.builtin_model_roster
    return render_builtin_model_roster()


PLANNER_PROMPT = """
You are a Senior ML Research Analyst specializing in hyperparameter optimization for deep learning models.
Your goal is to {METRIC_VERB} the `denoising_score` {SCORE_FIELD_NOUN} ({METRIC_IDENTITY_LINE}) across hyperparameter configurations for the following task:

{TASK_DESCRIPTION}

{AVAILABLE_MODELS_BLOCK}
### BASELINE REFERENCE RULE:
In Round 1, you **must** use the Baseline Configuration found in the initial Research Memory
(the record with "baseline" in its exp_id). Use the same model_config, train_config, and
loss_config as the baseline, but at your chosen trial_portion. This establishes a "Sparse
Baseline" — a reference point that shows how the baseline config performs on sparse data.
Do not change hyperparameters until this reference is set.

### PROGRESSIVE RESEARCH STRATEGY:
Plan your experiments across rounds, not just one at a time:
- **Phase 1: Screening** (first 25% of rounds): Broad exploration with low trial_portion
  (0.02-0.05) and low epochs (1-3). Test different loss types and learning rates quickly.
  Discard configs that fail to converge. Goal: find 2-3 promising directions.
- **Phase 2: Refinement** (middle 50% of rounds): Pick the top performing configs from
  Phase 1. Increase trial_portion to 0.1-0.3 and epochs to 5-10. Fine-tune lr,
  loss_type, and regularization. Goal: {METRIC_VERB} the score with sufficient data.
- **Phase 3: Solidification** (last 25% of rounds): Select the best candidate. Increase
  trial_portion to 0.5+ or switch to formal mode for definitive validation.
  The final round may be configured to require formal mode — see the
  ROUND CONTEXT block below for the per-run policy.

### RESEARCH MEMORY GUIDELINES:
- You operate based on the **Research Memory**, a log of all past experiments and insights.
- **Cross-Exploration Rule**: To avoid local minima, you must explore broadly:
    - **Architecture** (when free to choose): do not stay on one model for more than 2 consecutive runs if improvement is < 5%. Switch to a different architecture.
    - **Model config** (always applies): explore ALL tunable fields in model_config. Read the MODEL DESCRIPTION and CONFIG MANUAL carefully — every field listed there is a tuning lever. Model-specific parameters (e.g. gate vectors, layer counts, channel widths) are equally important as loss and learning rate.
    - **Loss config** (always applies): do not repeat the same `loss_type` for more than 2 consecutive runs without improvement. Cycle through the valid loss types for this model.
    - **Train config** (always applies): do not repeat the same `lr` and `batch_size` region for more than 2 consecutive runs. Try different learning rates (e.g. 1e-3, 3e-4, 1e-4) and batch sizes.
    - **EXCEPTION — Data Volume Override**: The Cross-Exploration Rule is **suspended** if
      `trial_portion` < 0.1 and the model shows signs of underfitting (high training loss,
      poor denoising score). In this case, your primary action must be to **double the
      trial_portion** while keeping the architecture and hyperparameters constant.
- **Hypothesis-Driven**: Every experiment must test a specific hypothesis.

### DEEP LEARNING BEST PRACTICES:
- **LR-Batch Scaling**: When increasing batch_size, scale learning_rate proportionally
  (linear scaling: lr_new = lr_old × bs_new / bs_old, or square-root scaling:
  lr_new = lr_old × sqrt(bs_new / bs_old)).
- **Underfitting vs Data**: If training loss is high, **increase trial_portion** before
  changing the model. Low data often prevents the optimizer from finding stable gradients.
- **Overfitting Control**: If training loss improves but denoising score drops, you MUST
  increase dropout, weight_decay, or reduce model capacity. Do NOT add more parameters.
- **Score Reliability**: Treat score improvements of < ±5% at trial_portion < 0.1 as
  noise. Do not pivot strategy based on noise — repeat with more data if unsure.

### COLLAPSE RECOVERY GUIDELINES:
- `denoising_score=-inf` or `denoising_score=None` with a non-None
  `failure_reason` means HealthGate detected model collapse or invalid output.
- `gate_action="continue"` with a non-None `failure_reason` means the gate
  detected a problem but allowed later rounds to run; it is NOT a healthy round.
{GATE_OUTPUT_DIVERSITY_ADVICE}{GATE_AMPLITUDE_COLLAPSE_ADVICE}- If `loss_type="ce"`, switch immediately to focal loss with `alpha={FOCAL_ALPHA_DEFAULT}`
  and `gamma={FOCAL_GAMMA_DEFAULT}`; CE is unstable on class-imbalanced data.
- If focal loss still collapses, reduce `lr` by 2-5×, for example
  `1e-3 → 5e-4 → 1e-4`.
- If `lr` is already low and collapse persists, switch from Adam to AdamW
  with `weight_decay=1e-4`.
- Do NOT increase model capacity or change architecture during collapse
  recovery. Stabilize training first and change one major factor at a time.
- Three or more consecutive records with non-None `failure_reason` indicate
  a fundamental configuration problem, not random variance.
- After persistent collapse, reset to the known-working baseline:
  focal loss (`alpha={FOCAL_ALPHA_DEFAULT}`, `gamma={FOCAL_GAMMA_DEFAULT}`), `lr=5e-4`, and Adam.
- Do not continue exploring a loss/optimizer/learning-rate region that has
  collapsed repeatedly.
- A finite score such as `-3.14` is NOT collapse. It is valid,
  low-but-real performance below the anchor ceiling.
- Treat collapse as present only when `failure_reason` is set; do not infer
  collapse from the sign of a finite score alone.

### EFFICIENCY AWARENESS:
- A simpler model (fewer parameters) or shorter training (fewer epochs) that achieves a score
  within {EFFICIENCY_BAND_PCT}% of the current best is a **highly valuable result** — prefer it over marginal gains
  from larger, slower experiments.
- When memory shows `is_more_efficient=True` for a past experiment, note its config:
  simpler configurations often generalise better and should be preferred as a starting point.
- Do not blindly scale up architecture or epochs when scores plateau. Instead, try:
    - Smaller model with better regularisation (dropout, weight_decay)
    - Fewer epochs with a better learning rate schedule
    - Different loss functions that may converge faster

### TRAINING DYNAMICS (per experiment, from its training history):
- `final_loss` / `loss_history` in memory records = the TRAINING objective.
- `denoising_score` in memory records = the golden metric, measured on the evaluation set.
- The user message carries one compact `training dynamics` line per recent experiment. Read it as
  facts, not as a verdict — no label is implied and none should be inferred mechanically:
    - `train A->B (trend, N ep)` — the training objective's first and last epoch values.
    - `val A->B (trend; best ep K, +D after best)` — the same for the validation objective, the
      epoch at which it was best, and how far it drifted afterwards.
    - `gap ±G (comparable)` — validation minus training at the final epoch, shown only when the
      two were measured on the same objective; `gap n/a (not comparable)` when they were not.
- Use them together with the score: a training objective that improves while the score does not
  move toward {METRIC_COMPARATIVE} is the case worth acting on, and which action fits depends on
  the trends, the gap and the data volume — decide it here rather than applying a fixed rule.

### TRIAL vs FORMAL MODE:
You can choose how much data to use for each experiment:
- **Trial mode** (`is_trial=true`): Train and evaluate on a sparse sample of segments across
  multiple files. Fast iteration — use this for early exploration when you are still searching
  for good hyperparameters. Scores are anchor-normalized and comparable across runs.
- **Formal mode** (`is_trial=false`): Train and evaluate on the full dataset (all segments
  across all validation files). Much slower but gives a definitive, comprehensive score.
  Use this when you have a promising config and want to validate it.

Trial strategies (only relevant when `is_trial=true`):
- `"snapshot"`: Sample uniformly across all validation files. Each file gets
  `trial_portion` fraction of its segments. Gives broad coverage but spreads data thinly
  per file.
- `"anchors"`: Sample from a small fixed subset of files (workflow-defined). More segments
  per file than snapshot at the same trial_portion, but other files receive zero coverage
  (their entries in `file_vector` are NaN).
- `"target"`: Sample from a caller-specified list of files (`target_files`). Concentrates
  all data on those files. {TARGET_STRATEGY_IMPACT_NOTE}

**Key tradeoff**: snapshot gives broad but shallow coverage per file. anchors and target
give deep coverage on fewer files.{SAMPLING_IMPACT_TRADEOFF}

`trial_portion` (0.01-1.0): fraction of segments per file for the **training scope**.
This determines how much data the model trains on. More data = better model but slower.
Start small (0.02-0.05) for fast hyperparameter exploration. If scores are consistently
poor, **increase trial_portion** (0.1-0.5) before changing hyperparameters — low scores
often mean insufficient training data, not bad hyperparameters.

`eval_portion` (0.01-1.0): fraction of segments per file for **validation** (inference +
scoring). Controls score fidelity. Can match trial_portion for fast checks, or be larger
for more reliable scores. In formal mode this is always 1.0.

`train_portion` (0.01-1.0): per-epoch subsample from the training scope. Default 0.1.
Each epoch sees a different random 10% of the training scope. Over multiple epochs the
model sees diverse data without loading everything at once.

### DATA VOLUME AWARENESS — CRITICAL:
- The baseline was trained on ALL segments (trial_portion=1.0). If your trial_portion is 0.05,
  you are training on 20× less data. **Poor scores on sparse data do not mean the hyperparameters
  are wrong** — they may mean the model needs more data.
- **Before switching hyperparameters after poor results, consider increasing trial_portion.**
  A 2× increase in trial_portion often helps more than changing loss_type or lr.
- If 2+ consecutive rounds show no improvement despite hyperparameter changes, double your
  trial_portion (e.g. 0.05 → 0.1 → 0.2).
- When you find a config that works well on sparse data, increase eval_portion or switch to
  formal mode to get a definitive score.

When reviewing past experiments in Research Memory:
- Compare `training_psd_segments` across records. The baseline typically trains on {FULL_SCOPE_SEGMENTS} segments.
  If your experiments train on 200 segments, you have 20× less data — increase trial_portion.
- Scores from larger portions are more reliable. A formal score (eval_portion=1.0) is the most
  definitive.

### AVAILABLE CUSTOM LOSSES:

{available_losses_block}

When the registry above lists one or more custom losses, you may set
`loss_config.loss_type = "custom"` AND `loss_config.loss_name = <name from
the table>` to train under that loss. The plugin is already generated and
dummy-tensor-validated; selecting it does NOT cost an extra implementor
call. When the block above says "No custom losses registered yet", the only
legal `loss_type` values are the four built-ins (`focal`, `focal_cw`, `ce`,
`smooth_l1`) — see the COMPATIBILITY section in the user message below.

{PER_FILE_TABLE_PROTOCOL}{SCORE_COMPARISON_TABLE}

Use this table — not just the scalar — to decide where to focus next.

### OUTPUT REQUIREMENT:
You must provide the next experiment setup in a strict JSON format.
"""

REFLECTOR_PROMPT = """
You are a Research Analyst. Your job is to transform raw experiment results into **Research Memory**.

### OBJECTIVES:
- **Validate Hypothesis**: Compare the initial hypothesis with the actual {SCORE_DISPLAY_NOUN} and Loss.
- **Extract Discovery**: Identify a specific pattern or rule learned from this run.
- **Update Memory**: Write a concise 'Memory Entry' that will guide the Planner in the next iteration.

### CRITICAL — TRAINING DYNAMICS:
- `final_loss` and `loss_history` are the TRAINING objective.
- `denoising_score` is the golden metric, measured on the evaluation set.
- The user message carries a compact `training dynamics` line for THIS experiment: the training
  objective's first and last epoch values and trend, the same for the validation objective, the
  epoch at which validation was best and how far it drifted after that, and the final
  train-validation gap when both were measured on the same objective.
- Reason from those facts together with the score. State what the numbers show and what it implies
  for the next configuration; do not attach a label the numbers do not establish, and do not infer
  one from the score's sign.

### CRITICAL — HOW TO JUDGE THE {SCORE_DISPLAY_NOUN_UPPER}:
- The `denoising_score` field carries the {METRIC_IDENTITY_LINE}.
- The {SCORE_DISPLAY_NOUN} is a relative metric. Its absolute value and sign mean nothing in isolation.
- ALWAYS compare against the Baseline Score and Best Score So Far provided in the context.
- A result is GOOD if its denoising_score is {METRIC_COMPARATIVE_UPPER} than the best score so far.
- A result is NEUTRAL if it matches previous scores.
- A result is BAD if it is {METRIC_ANTONYM_UPPER} than most previous scores.
- NEVER call a result a failure just because the score is negative.

{PER_FILE_COMPARISON_BLOCK}

{SCORE_COMPARISON_TABLE}

### CRITICAL — DATA VOLUME AWARENESS:
- Check `training_psd_segments` and `baseline_psd_segments` in the context.
- If this experiment trained on much LESS data than the baseline (e.g. 200 vs 4000 segments),
  poor scores may be caused by **insufficient training data**, not bad hyperparameters.
- In that case, the memory_update should recommend **increasing trial_portion** rather than
  changing loss_type or lr. Example: "Score is 5× below baseline but trained on 20× less data.
  Recommend increasing trial_portion from 0.05 to 0.2 before changing hyperparameters."
- If training data is comparable to baseline but score is still poor → then the hyperparameters
  are likely the issue.

### CRITICAL — HOW TO JUDGE THE TRAINING LOSS:
- Training loss is only comparable across experiments that use the SAME loss_type.
- If the current experiment uses a different loss_type than previous ones, DO NOT compare loss values.
- When loss_type is the same, a lower final_loss relative to previous same-loss experiments is a positive signal.

### CRITICAL — ATTRIBUTION:
- Always identify the key factor that caused this result to differ from previous experiments.
- Attribute results to specific hyperparameter choices: loss_type, lr, batch_size, latent_dims, epochs, etc.

### CRITICAL — EFFICIENCY AWARENESS:
- If `is_more_efficient` is True in the context, this is a **valuable discovery**: a simpler or
  faster configuration achieved comparable results. Flag this explicitly in `discovery` and
  `memory_update`. Simpler models that generalise well are often more useful than marginal score
  improvements from bloated architectures.
- `params_ratio` < 1.0 means this model has FEWER parameters than the baseline.
- `epochs_ratio` < 1.0 means this model needed FEWER epochs than the baseline.
- Even if this is NOT a new best, a small model within {EFFICIENCY_BAND_PCT}% of the best score is a meaningful result.

### CRITICAL — EFFICIENCY BENCHMARKING:
A configuration is only "Better" if it beats the best score (in the {METRIC_COMPARATIVE}-is-better
sense). But a configuration is "Valuable" if it lands within {EFFICIENCY_BAND_PCT}% of the best
score's observed range with <50% of the parameters or training time. Flag these as **High-Efficiency Discoveries** in your discovery and memory_update.
These efficient configs are strong candidates for the Solidification phase.

### CRITICAL — SCORE RELIABILITY:
- At trial_portion < 0.1, score differences of < ±5% are **noise**, not signal.
  Do NOT recommend pivoting strategy based on small differences at low data volume.
- If two experiments at low trial_portion have similar scores, recommend repeating
  with higher trial_portion before concluding one is better.

### Memory should answer: "What did we learn that we didn't know before?"
"""

# ==========================================
# 2. EXPLORATION CHECKLIST
# ==========================================

# Fields to exclude from the checklist (not meaningful to tune)
_CHECKLIST_SKIP_FIELDS = {"model_type", "batch_size"}


def _canonical_config_value(value: Any) -> Any:
    """A deterministic, hashable stand-in for a config value.

    The exploration checklist counts DISTINCT values per field and renders
    them. Config values arrive from JSON, so they may be scalars, lists or
    nested dicts — and `set.add` on a list raises `TypeError: unhashable
    type: 'list'`, which is what killed V20 launch attempt 1.

    Required properties, in the order they matter here:

    * **hashable** for every JSON-shaped value, so no input can crash the
      planner;
    * **deterministic** — the same value canonicalises identically across
      records and processes, or the distinct-count is meaningless;
    * **equal values collapse, different values do not.** Dict key order
      is normalised by sorting, so `{"a": 1, "b": 2}` and `{"b": 2, "a": 1}`
      count once rather than twice.

    `str(val)` — the previous `model_config`-only guard — satisfies only
    the first. It also lets `[1, 2]` collide with the string `"[1, 2]"`,
    and leaves two semantically identical dicts counting as two distinct
    values when their key order differs.

    Lists and tuples canonicalise identically: a tuple that survives a JSON
    round trip comes back a list, so treating them differently would make
    the same value count twice depending on where it was read from. The
    tags keep a sequence from ever colliding with a mapping or a scalar.
    """
    if isinstance(value, dict):
        return ("dict", tuple(sorted((k, _canonical_config_value(v)) for k, v in value.items())))
    if isinstance(value, list | tuple):
        return ("seq", tuple(_canonical_config_value(v) for v in value))
    if isinstance(value, set | frozenset):
        return ("set", tuple(sorted((_canonical_config_value(v) for v in value), key=repr)))
    return value


def build_exploration_checklist(
    config_schema: dict,
    memory_history: list,
) -> str:
    """
    Build a parameter exploration checklist from the config schema and past records.

    For each tunable field in model_config, loss_config, and train_config,
    shows what values have been tried and flags under-explored parameters.

    Args:
        config_schema: The model's config JSON schema (from ConfigClass.model_json_schema()).
        memory_history: List of past experiment record dicts.

    Returns:
        Markdown checklist string for injection into the planner prompt.
    """
    if not memory_history:
        return ""

    # V20 launch attempt 1 (2026-08-06, SHA d8e21d1a) died here on the very
    # first iteration: a proposal legitimately produced a LIST-valued
    # train_config entry, `set.add` raised `TypeError: unhashable type:
    # 'list'`, and every subsequent planning attempt hit the same line —
    # three attempts consumed, the round failed, the iteration recorded
    # `no_records`. The candidate never reached implementation, training or
    # HealthGate, so an infrastructure crash was being spent as scientific
    # search budget.
    #
    # The guard already existed for `model_config` and for neither of the
    # other two, which is the whole defect: one of three call sites knew
    # values could be composite.

    # Collect tried values per parameter from successful + error records.
    #
    # Keyed by a CANONICAL hashable form of the value, valued by the
    # original rendering. `len()` over the keys is the distinct-value count
    # the checklist markers use; the values are what the prompt displays.
    model_cfg_tried: dict[str, dict[Any, str]] = {}
    loss_cfg_tried: dict[str, dict[Any, str]] = {}
    train_cfg_tried: dict[str, dict[Any, str]] = {}

    def _record(bucket: dict[str, dict[Any, str]], key: str, val: Any) -> None:
        bucket.setdefault(key, {})[_canonical_config_value(val)] = str(val)

    for rec in memory_history:
        params = rec.get("params", {})
        for key, val in params.get("model_config", {}).items():
            if key in _CHECKLIST_SKIP_FIELDS:
                continue
            _record(model_cfg_tried, key, val)

        for key, val in params.get("loss_config", {}).items():
            _record(loss_cfg_tried, key, val)

        for key, val in params.get("train_config", {}).items():
            if key in _CHECKLIST_SKIP_FIELDS:
                continue
            _record(train_cfg_tried, key, val)

    # Build checklist lines
    lines = ["### EXPLORATION CHECKLIST"]
    lines.append(
        "Review which parameters have been explored. Under-explored parameters "
        "deserve attention — do not ignore model_config fields.\n"
    )

    def _format_bounds(spec: dict) -> str:
        """Render the field's allowed range / enum from a JSON-schema property."""
        # Enum / Literal fields take precedence
        if "enum" in spec:
            return f"allowed={spec['enum']}"
        lo_inclusive = spec.get("minimum")
        lo_exclusive = spec.get("exclusiveMinimum")
        hi_inclusive = spec.get("maximum")
        hi_exclusive = spec.get("exclusiveMaximum")
        lo_str = (
            f"[{lo_inclusive}"
            if lo_inclusive is not None
            else f"({lo_exclusive}"
            if lo_exclusive is not None
            else "(-inf"
        )
        hi_str = (
            f"{hi_inclusive}]"
            if hi_inclusive is not None
            else f"{hi_exclusive})"
            if hi_exclusive is not None
            else "+inf)"
        )
        if (
            lo_inclusive is None
            and lo_exclusive is None
            and hi_inclusive is None
            and hi_exclusive is None
        ):
            return ""
        return f"range={lo_str},{hi_str}"

    # Model config fields from schema
    schema_props = config_schema.get("properties", {})
    lines.append("**model_config:**")
    for field, spec in schema_props.items():
        if field in _CHECKLIST_SKIP_FIELDS:
            continue
        tried = model_cfg_tried.get(field, {})
        default = spec.get("default")
        desc = spec.get("description", "")
        bounds = _format_bounds(spec)

        if len(tried) == 0:
            status = "NEVER TRIED"
            marker = "[ ]"
        elif len(tried) == 1:
            status = "only 1 value tried"
            marker = "[ ]"
        else:
            status = f"{len(tried)} values tried"
            marker = "[x]"

        # Format tried values concisely. Iterate the VALUES: the keys are
        # canonical forms and would render as `('seq', (32, 64))` rather
        # than the `[32, 64]` an operator (and the planner) expects.
        if tried:
            tried_str = ", ".join(sorted(tried.values()))
            if len(tried_str) > 80:
                tried_str = tried_str[:77] + "..."
        else:
            tried_str = f"default={default}"

        # Append bounds so the LLM cannot propose out-of-range values
        suffix = f" — {status}"
        if bounds:
            suffix += f" — {bounds}"
        if desc:
            suffix += f" — {desc}"
        lines.append(f"- {marker} `{field}`: {tried_str}{suffix}")

    # Loss config
    lines.append("\n**loss_config:**")
    for key, tried in loss_cfg_tried.items():
        tried_str = ", ".join(sorted(tried.values()))
        marker = "[x]" if len(tried) >= 2 else "[ ]"
        lines.append(f"- {marker} `{key}`: {tried_str}")

    # Train config (just lr and epochs — most impactful)
    lines.append("\n**train_config:**")
    for key in ["lr", "epochs", "optimizer_type", "weight_decay"]:
        tried = train_cfg_tried.get(key, {})
        if not tried:
            continue
        tried_str = ", ".join(sorted(tried.values()))
        marker = "[x]" if len(tried) >= 2 else "[ ]"
        lines.append(f"- {marker} `{key}`: {tried_str}")

    return "\n".join(lines)


# Maximum characters to emit for the config-class source excerpt. Keeps the
# planner prompt bounded when a plugin config class grows large. Real-world
# plugin config bodies (validators + fields) typically run 500-1500 chars, so
# 4000 gives ~2-3x headroom before truncation kicks in.
_PLUGIN_SOURCE_EXCERPT_MAX_CHARS = 4000


def _extract_config_class_source(config_cls) -> str:
    """Return the source of a Pydantic config class, suitable for injection
    into the tuner's planner prompt.

    Why: ``PLUGIN_CONFIG_CLASS.model_json_schema()`` exposes per-field bounds
    (``ge`` / ``le`` / ``multiple_of``) but has no representation for
    ``@model_validator(mode='after')`` or cross-field ``@field_validator``
    bodies. The planner is therefore blind to hand-rolled invariants — this
    was the root cause of the ``exploit_cnn_v1`` iter-1 failure on 2026-04-17
    (7 consecutive ``nondecreasing channels`` violations).

    We use ``inspect.getsource(config_cls)`` which works uniformly for both
    built-in config classes (``ml_models/models_format_sandbox.py``) and
    agent-generated plugin classes (``agent_generated/models/*.py``) without
    any file-path heuristics. The returned source includes the class body and
    every ``@*_validator`` decorator inside it.

    Phase D.1 — see ``docs/improving_validation_awareness.md``.

    Args:
        config_cls: A Pydantic ``BaseModel`` subclass (or ``None``).

    Returns:
        The class source, truncated to ``_PLUGIN_SOURCE_EXCERPT_MAX_CHARS``
        with a ``"... (truncated)"`` marker appended when cut. Returns ``""``
        when ``config_cls`` is falsy or when ``inspect.getsource`` fails
        (e.g. dynamically constructed class, source file unavailable).
    """
    if config_cls is None:
        return ""
    try:
        src = inspect.getsource(config_cls)
    except (OSError, TypeError):
        # OSError: source file missing / unreadable.
        # TypeError: class is a builtin or dynamically constructed.
        return ""
    if len(src) > _PLUGIN_SOURCE_EXCERPT_MAX_CHARS:
        src = src[:_PLUGIN_SOURCE_EXCERPT_MAX_CHARS].rstrip() + "\n... (truncated)"
    return src


def format_plugin_source_excerpt_block(config_cls) -> str:
    """Wrap ``_extract_config_class_source`` output in the pinned
    planner-prompt heading.

    Returns ``""`` when the helper yields no source — caller should inject the
    result unconditionally (an empty string collapses cleanly in the prompt).

    Phase D.1 — paired with ``LLMBridge.plan(plugin_source_excerpt=...)``.
    """
    src = _extract_config_class_source(config_cls)
    if not src:
        return ""
    return (
        "## PLUGIN CONFIG SCHEMA (authoritative — read validators carefully)\n"
        "The planner prompt's JSON schema below cannot represent "
        "`@model_validator(mode='after')` or cross-field `@field_validator` "
        "bodies. Treat the source below as the single source of truth for any "
        "cross-field invariants; a proposed config that violates one will be "
        "rejected by the resource-eval skill and burn a retry attempt.\n\n"
        "```python\n"
        f"{src}\n"
        "```\n"
    )


# ==========================================
# 2.5 RESOURCE-GATE BLOCKS (Phase K, K.6 — see §10.3 / §10.11)
# ==========================================

# Static guidance text appended to the planner user prompt. Tells the LLM how
# to read the per-round [ACTIVE RESOURCE BUDGETS] block and which lever to
# pick when factors are over budget. Verbatim from
# docs/resource_estimator_implement.md §10.3.
RESOURCE_GATE_GUIDANCE_BLOCK = """### [RESOURCE GATE — RESOLVING OVER-BUDGET CONFIGS]

You will be shown vram_estimate_gb, time_estimate_minutes, the matching
budgets, the resulting factors (>1 = over budget, <1 = under), and the
current batch_size.

When deciding the next config:

  - If both factors are <= 1: continue per the exploration plan.
  - Otherwise, first consider whether changing batch_size alone can bring
    BOTH factors <= 1.
      - Lowering batch_size reduces vram_factor and raises time_factor.
      - Raising batch_size does the opposite.
      - batch_size cannot go below 1; whether you have room to lower or
        raise depends on the current batch_size shown above.
  - If batch_size adjustment alone cannot satisfy both budgets
    simultaneously, reduce model depth/width (num_blocks,
    hidden_channels, embedding_dim, etc.). Both axes shrink together.

Constraint: do NOT change segmentation_size to fit either budget. It is
pinned by frequency-resolution physics (must divide PSD_SEGMENT_LENGTH;
the valid divisor list is in your expert advice). Lowering seg_size to
escape the time gate inflates step count and typically makes the overrun
worse, not better.

The gates run again before training, so a misjudgement just costs one
skipped attempt (no round consumed). Prefer the cheaper lever first.
"""


def _format_active_resource_budgets_block(
    *,
    current_round=None,
    last_mode=None,
    trial_vram_budget_gb=None,
    formal_vram_budget_gb=None,
    trial_time_budget_minutes=None,
    formal_time_budget_minutes=None,
    last_vram_estimate_gb=None,
    last_time_estimate_minutes=None,
    last_batch_size=None,
):
    """Render the per-round [ACTIVE RESOURCE BUDGETS] block (K.6).

    The planner runs BEFORE this round's pre-flight gates, so the estimates
    shown are those of the most recent prior attempt (success or skipped).
    The mode label is the prior attempt's mode (`time_mode` on the record).
    For round 1 with no prior attempts, both estimates are None and the
    block falls back to "(no prior estimate)" lines.

    Returns "" when no budget AND no prior estimate is available — nothing
    informative to show.

    See docs/resource_estimator_implement.md §10.3 / §10.11.
    """
    any_budget = any(
        b is not None
        for b in (
            trial_vram_budget_gb,
            formal_vram_budget_gb,
            trial_time_budget_minutes,
            formal_time_budget_minutes,
        )
    )
    any_estimate = any(e is not None for e in (last_vram_estimate_gb, last_time_estimate_minutes))
    if not any_budget and not any_estimate:
        return ""

    # Fall back to "trial" when the prior round's mode is unknown (round 1
    # before any attempts have run). The exploration default is trial mode;
    # if the operator only set formal budgets the active-mode line still
    # surfaces "(no budget — gate disabled)" and the LLM can react.
    mode = last_mode if last_mode in ("trial", "formal") else "trial"
    if mode == "trial":
        active_vram_budget = trial_vram_budget_gb
        active_time_budget = trial_time_budget_minutes
    else:
        active_vram_budget = formal_vram_budget_gb
        active_time_budget = formal_time_budget_minutes

    if current_round is not None:
        header = f"[ACTIVE RESOURCE BUDGETS — round {current_round}, mode={mode}]"
    else:
        header = f"[ACTIVE RESOURCE BUDGETS — mode={mode}]"

    # VRAM line
    if active_vram_budget is None:
        vram_line = "  VRAM:  (no budget — gate disabled)"
    elif last_vram_estimate_gb is None:
        vram_line = f"  VRAM:  (no prior estimate)   budget {active_vram_budget:.2f} GB"
    else:
        factor = last_vram_estimate_gb / active_vram_budget
        verdict = "over" if factor > 1.0 else "under"
        vram_line = (
            f"  VRAM:  estimate {last_vram_estimate_gb:.2f} GB   "
            f"budget {active_vram_budget:.2f} GB   "
            f"factor {factor:.2f}  ({verdict})"
        )

    # Time line
    if active_time_budget is None:
        time_line = "  Time:  (no budget — gate disabled)"
    elif last_time_estimate_minutes is None:
        time_line = f"  Time:  (no prior estimate)   budget {active_time_budget:.1f} min"
    else:
        factor = last_time_estimate_minutes / active_time_budget
        verdict = "over" if factor > 1.0 else "under"
        time_line = (
            f"  Time:  estimate {last_time_estimate_minutes:.2f} min   "
            f"budget {active_time_budget:.1f} min   "
            f"factor {factor:.2f}  ({verdict})"
        )

    if last_batch_size is not None:
        bs_line = f"  Current batch_size: {last_batch_size}"
    else:
        bs_line = "  Current batch_size: (not yet set)"

    return "\n".join([header, vram_line, time_line, bs_line])


# ==========================================
# 3. USER PROMPT GENERATORS (The Context)
# ==========================================


def _format_known_constraints_block(dataset_config=None) -> str:
    """
    Render a SYSTEM-ENFORCED DATASET CONSTRAINTS block listing the dataset-level
    rules that the proposer's ``baseline_config`` is machine-validated against.

    Used by the proposing-stage prompt only — the comparison and causal-reasoning
    stages don't write ``baseline_config`` and don't need this block.

    Returns an empty string when ``dataset_config`` is None (backward-compat for
    callers that don't supply one — those callers pre-date this validator).

    See ``docs/improving_validation_awareness.md`` Phase A.2.

    Args:
        dataset_config: A ``DatasetConfig`` (typically ``TIDMAD``). When None,
            the helper no-ops and returns "".

    Returns:
        Formatted block string, or "" when ``dataset_config`` is None.
    """
    if dataset_config is None:
        return ""

    psd = dataset_config.psd_segment_length
    valid = dataset_config.valid_segmentation_sizes()
    return f"""## SYSTEM-ENFORCED DATASET CONSTRAINTS

Your `baseline_config` will be machine-validated against the dataset rules below.
A violation rejects the proposal and re-prompts you with the error — burning one
of your retry attempts. Pick valid values now.

  segmentation_size — must EXACTLY divide psd_segment_length ({psd:,}).
                      Valid values: {valid}.
                      Powers of 2 such as 16384, 8192, 4096 are INVALID
                      because they do not divide {psd:,}. Use a divisor from
                      the list above (16000 is the nearest valid neighbor of 16384).

"""


def _format_fixed_params_block(plan_overrides=None, max_epochs=None, resolved_data_scope=None):
    """
    Render a SYSTEM-FIXED PARAMETERS block for the planner prompt when the
    operator has frozen any plan fields via ``plan_overrides``, capped
    ``max_epochs``, or restricted the run to a partial DataScope. Returns an
    empty string when nothing is set, so the prompt is unchanged for runs
    that do not use overrides.

    The block tells the LLM (a) which fields it does NOT control this run, and
    (b) that the standard prompt's phase-progression / "increase trial_portion"
    advice does not apply when those knobs are frozen. Without this, the LLM
    wastes reasoning on knobs the workflow silently overrides.

    Args:
        resolved_data_scope: Sorted allowed file indices when the run's
            DataScope is PARTIAL; the caller passes ``None`` for a
            full-scope run. Disclosure only — enforcement is constructive
            (build_sample_set) + the sandbox boundary; plans proposing
            ``anchors``/``target`` under a partial scope are normalized to
            ``snapshot`` with recorded provenance. See
            docs/design/enable_partial_file_list.md.
    """
    overrides = dict(plan_overrides) if plan_overrides else {}
    has_max_epochs = max_epochs is not None
    has_partial_scope = resolved_data_scope is not None
    if not overrides and not has_max_epochs and not has_partial_scope:
        return ""

    lines = []
    if "is_trial" in overrides:
        lines.append(
            f"  is_trial         = {overrides['is_trial']}   "
            f"← trial mode (final round auto-flips to formal)"
        )
    if "trial_portion" in overrides:
        lines.append(f"  trial_portion    = {overrides['trial_portion']}")
    if "train_portion" in overrides:
        lines.append(
            f"  train_portion    = {overrides['train_portion']}    "
            f"← full per-epoch pass (no per-epoch subsampling)"
        )
    if "eval_portion" in overrides:
        lines.append(
            f"  eval_portion     = {overrides['eval_portion']}    ← formal mode auto-uses 1.0"
        )
    # Render any other override keys generically. NOT the same concept as
    # the schema's TRIAL_SCOPED_OVERRIDE_KEYS (review NOTE-g): that set is
    # "which keys the resolver DISCARDS on a formal round"; this set is
    # "which keys got a bespoke prompt line above vs the generic fallback
    # below". Same-name-adjacent, deliberately distinct — do not unify.
    rendered_keys = {"is_trial", "trial_portion", "train_portion", "eval_portion"}
    for k, v in overrides.items():
        if k not in rendered_keys:
            lines.append(f"  {k:16s} = {v}")
    if has_max_epochs:
        lines.append(f"  epochs (cap)     ≤ {max_epochs}      ← higher values are clamped")
    if has_partial_scope:
        lines.append(
            f"  data_scope       = files {resolved_data_scope}   "
            f"← the ONLY files this run may access"
        )
        lines.append(
            "  trial_strategy   = snapshot   ← forced under a partial data_scope "
            "(anchors/target are normalized to snapshot)"
        )
        lines.append("  eval_strategy    = snapshot   ← forced under a partial data_scope")

    fixed_lines = "\n".join(lines)
    strategy_surface = (
        "  - train_validation_align (trial_strategy/eval_strategy are FIXED to snapshot\n"
        "    over the data_scope files; target_files is unavailable this run)"
        if has_partial_scope
        else "  - trial_strategy + target_files; eval_strategy; train_validation_align"
    )
    return f"""
### SYSTEM-FIXED PARAMETERS (operator-set; do NOT vary):
The operator has frozen these plan fields. Any other value you pick will be silently
overridden — reflect these values verbatim in your JSON output and do not waste reasoning
on them.

{fixed_lines}

Your control surface this run:
  - model_type + model_config (architecture, segmentation_size, channel widths, …)
  - loss_config (loss_type)
  - train_config (lr, batch_size; epochs is capped)
{strategy_surface}

NOTE: Standard guidance below mentions varying trial_portion/epochs (phase-progression,
"increase trial_portion if scores are poor"). Those instructions do not apply this run
since those knobs are frozen — focus your reasoning on architecture, lr, and loss_type.
"""


_CONDENSED_KEYS = frozenset(
    {
        "exp_id",
        "status",
        "model_type",
        "denoising_score",
        "is_trial",
        # Surface the task-specific health-check message even after a record
        # falls out of the verbatim window — failure_reason is the primary
        # learning signal for the planner when a previous formal round
        # collapsed (e.g. amplitude collapse on SQUID denoising). Defensively
        # absent on healthy rounds; the comprehension below tolerates it.
        "failure_reason",
    }
)
_CONDENSED_MEMORY_KEYS = frozenset(
    {
        "hypothesis",
        "conclusion",
        "round_index",
    }
)

# Persistence ≠ prompt visibility (roadmap §22.6). Record-facing payloads
# that are PERSISTED on every record but NOT agent-facing yet are dropped from
# the planner's history serialization here; the persisted record is untouched.
#
# * Step 06 (operator-directed corrective, 2026-08-15): the metric interface's
#   `metric_result` / `metric_refusal`. Left in the verbatim window, the
#   planner would see two numbers for a collapsed formal attempt (the raw
#   `metric_result.scalar` beside the penalised `denoising_score`) with no
#   lifecycle explanation.
# * Step 07a: the trainer's `training_history` (R2 + R3 + objective identity)
#   and the derived `training_diagnosis`. 07a HIDES them at both renders (this
#   set, and the reflector's legacy-payload merge in the tuner) · 07b RENDERS
#   selected facts with direction wording · Step 09 INTERPRETS / condenses
#   them for the interpreter. Do not widen or narrow this set casually — a
#   change here is an LLM-visible byte change (Gate 1).
_PLANNER_HIDDEN_RECORD_KEYS = frozenset(
    {
        "metric_result",
        "metric_refusal",
        "training_history",
        "training_diagnosis",
        # Step 10 / P2b — secondary metrics are OBSERVATIONAL evidence for the
        # INTERPRETER, persisted for it to project and render. They are not
        # planner input: showing the planner a second, differently-directed
        # number beside the one it is optimising invites it to trade the two
        # off, which is exactly the vote secondaries must never get. The crash
        # carrier is hidden for a further reason — it is an operator-facing
        # diagnostic about the implementation, not a fact about the science.
        "secondary_metric_results",
        "secondary_metric_refusals",
        "secondary_metric_errors",
    }
)


def _planner_visible(rec: dict) -> dict:
    """``rec`` without the keys the planner must not see.

    Returns ``rec`` ITSELF when it carries none of them (a pre-Step-06 record
    keeps its identity in the verbatim window, exactly as before) and a
    shallow copy without them otherwise. Never mutates the input.
    """
    if not (_PLANNER_HIDDEN_RECORD_KEYS & rec.keys()):
        return rec
    return {k: v for k, v in rec.items() if k not in _PLANNER_HIDDEN_RECORD_KEYS}


#: How many most-recent records the planner sees VERBATIM. One symbol, because
#: Step 07 PR 07b renders a training-dynamics line per verbatim-window record:
#: two constants could disagree about which experiments are "recent" and the
#: block would describe a different set than the JSON beside it.
PLANNER_FULL_WINDOW = 3


def _truncate_memory_history(
    records: list[dict],
    full_window: int = PLANNER_FULL_WINDOW,
) -> list[dict]:
    """Sliding-window truncation for the planner's history context.

    Args:
        records:     Full experiment record list from sandbox.get_summary().
        full_window: Number of most-recent records to keep verbatim.

    Returns:
        New list (non-destructive). Recent records are unchanged apart from
        the Step-06 record-only payload keys, which are never rendered
        (``_PLANNER_HIDDEN_RECORD_KEYS``); older records are condensed to
        identity + score + hypothesis/conclusion.
    """
    if len(records) <= full_window:
        return [_planner_visible(rec) for rec in records]

    cutoff = len(records) - full_window
    condensed: list[dict] = []
    for rec in records[:cutoff]:
        # OD-1 (Step 07 PR 07b §3.10): iterate the RECORD's own key order,
        # filtered by membership — never the frozenset's. A frozenset of
        # strings iterates in hash order, so the condensed entries' JSON key
        # order (and therefore the planner prompt's BYTES for any history
        # longer than the verbatim window) differed between processes. Five
        # PYTHONHASHSEEDs produced five different orders; no golden ever caught
        # it because the PB-1 fixture has three records and never enters this
        # branch. Sorting would have been a different fix with a different
        # defect: it would impose an order the verbatim window does not use, so
        # a record would be serialised one way inside the window and another
        # way outside it.
        entry = {k: rec[k] for k in rec if k in _CONDENSED_KEYS}
        memory = rec.get("memory", {})
        if memory:
            entry["memory"] = {k: memory[k] for k in memory if k in _CONDENSED_MEMORY_KEYS}
        condensed.append(entry)

    return condensed + [_planner_visible(rec) for rec in records[cutoff:]]


def get_planner_user_prompt(
    memory_history,
    expert_advice="None",
    force_model="auto",
    current_round=None,
    max_rounds=None,
    trial_allowed=True,
    force_formal_round=True,
    plan_overrides=None,
    max_epochs=None,
    resolved_data_scope=None,
    # --- Phase K (K.6) — [ACTIVE RESOURCE BUDGETS] block inputs ---
    trial_vram_budget_gb=None,
    formal_vram_budget_gb=None,
    trial_time_budget_minutes=None,
    formal_time_budget_minutes=None,
    last_vram_estimate_gb=None,
    last_time_estimate_minutes=None,
    last_batch_size=None,
    last_mode=None,
    # --- L6b — tuner planner registry awareness ---
    registry=None,
    # --- Step 07 PR 07b (P2) — the run's authority-rendered task tokens ---
    task_render=None,
):
    """
    Constructs the prompt for the Planner.

    Args:
        memory_history: List of past experiment records.
        expert_advice:  Serialized expert advice string.
        force_model:    Model type constraint ("auto" = free choice).
        current_round:  Current round number (1-based). None = omit round context.
        max_rounds:     Total rounds in this run. None = omit round context.
        trial_allowed:  Whether the LLM may choose trial mode. When False, the
                        LLM must set is_trial=false.
        force_formal_round:
                        When True (default), the final round is presented to
                        the LLM as MANDATORY formal mode. When False, the
                        final round is presented as OPTIONAL formal — the
                        planner may use trial mode for fast verification
                        (testing/debugging only). The post-LLM override
                        chain (``_apply_mode_override_chain``) is gated on
                        the same flag so prompt and override agree.
        plan_overrides: Dict of plan fields the operator has frozen. When set,
                        a SYSTEM-FIXED PARAMETERS block is rendered so the LLM
                        does not waste reasoning on overridden knobs.
        max_epochs:     Hard cap on epochs. Rendered alongside plan_overrides.
        resolved_data_scope:
                        Sorted allowed file indices when the run's DataScope
                        is partial (None = full scope, no disclosure).
                        Rendered in the SYSTEM-FIXED PARAMETERS block with
                        the snapshot-only rule so the planner does not
                        propose anchors/target or reason about out-of-scope
                        files. Disclosure only — enforcement is post-hoc.

        trial_vram_budget_gb,
        formal_vram_budget_gb,
        trial_time_budget_minutes,
        formal_time_budget_minutes:
            Operator-supplied per-mode resource budgets. Forwarded into the
            [ACTIVE RESOURCE BUDGETS] block so the LLM sees the numeric
            ceiling that the upcoming pre-flight gate will enforce. None for
            any field means "(no budget — gate disabled)" on that axis.
            See docs/resource_estimator_implement.md §10.3 / §10.11.
        last_vram_estimate_gb,
        last_time_estimate_minutes,
        last_batch_size,
        last_mode:
            Resource fields from the most recent prior attempt's record
            (success or skipped). Surface what the LAST config produced so
            the LLM has a concrete number to react to. None for any field
            means "no prior data" — typically round 1 before any pre-flight
            has run. See §10.3 / §10.11.
    """
    windowed = _truncate_memory_history(memory_history) if memory_history else []
    history_context = (
        json.dumps(windowed, indent=2) if windowed else "No previous experiments recorded."
    )

    # Step 07 PR 07b (P3) — the training-dynamics block is rendered from the
    # RAW verbatim window, before `_truncate_memory_history` strips the hidden
    # keys. That ordering is the whole design: the planner gets an OWNED,
    # calibration-free SUMMARY of each recent trajectory, while the raw
    # `training_history` / `training_diagnosis` payloads stay out of the JSON
    # above (roadmap §22.6 — persistence is not prompt visibility). Nothing is
    # recomputed here; 07a derived and persisted the diagnosis.
    dynamics_block = (
        render_planner_dynamics_block(memory_history[-PLANNER_FULL_WINDOW:])
        if memory_history
        else ""
    )
    dynamics_section = f"\n{dynamics_block}\n" if dynamics_block else ""

    # L6b — registry awareness. ``has_custom_losses`` is True when the
    # capability registry contains at least one ``capability_type="loss"``
    # entry; in that case the planner is also told it MAY use
    # ``loss_type="custom"`` + ``loss_name=<entry from the AVAILABLE
    # CUSTOM LOSSES table in the system prompt>``. Default False (no
    # registry passed) preserves pre-L6b behaviour where only the four
    # built-in loss types were advertised. See
    # docs/design/enable_loss_inventory.md § L6b.
    has_custom_losses = False
    if registry is not None:
        try:
            has_custom_losses = bool(list(registry.list(capability_type="loss")))
        except Exception:
            # Defensive: registry may be a duck-typed stub in tests. Treat
            # any failure as "no custom losses available" rather than
            # propagating the error into prompt rendering.
            has_custom_losses = False
    custom_loss_note = (
        ' You may ALSO use `loss_type="custom"` with a `loss_name` from '
        "the AVAILABLE CUSTOM LOSSES table in the system prompt above — "
        "those plugins are already generated and validated, picking one "
        "costs no extra LLM call."
        if has_custom_losses
        else ""
    )

    # Handle the model constraint message + output type / valid losses
    model_constraint = ""
    if force_model != "auto":
        from ml_models.plugin_loader import (
            UnknownOutputContractError,
            get_output_type,
        )

        try:
            output_type = get_output_type(force_model)
        except UnknownOutputContractError as e:
            # V21 PR C1 — typed PROMPT-CONSTRUCTION refusal.
            #
            # This consumer was missed by C1's first census, which was built
            # from the execution path; prompt rendering is not on it. See the
            # PR C design doc §0.5a.
            #
            # Deliberately NOT swallowed like the custom-loss probe above.
            # That one degrades to "no custom losses", which costs the agent
            # an option. This one decides which loss families the planner is
            # told are legal, so guessing would hand the agent a prompt that
            # contradicts the live compatibility rule and make every plan it
            # produces invalid.
            raise ValueError(
                f"Cannot render the planner prompt for force_model={force_model!r}: {e!s}"
            ) from e
        # Step 07 PR 07b (P2): the output shape is the run-bound Model-I/O
        # contract's, not a literal. A run with no bound contract omits the
        # parenthetical rather than asserting TIDMAD's shape.
        shape = task_render.output_contract_shape if task_render is not None else None
        classifier_shape = f" (output {shape})" if shape else ""
        if output_type == "classifier":
            loss_note = (
                f"- This model is a **CLASSIFIER**{classifier_shape}. "
                "Valid loss types: **ce, focal, focal_cw**. "
                "Do NOT use smooth_l1 (regression only)."
                f"{custom_loss_note}\n"
            )
        elif output_type == "regressor":
            loss_note = (
                "- This model is a **REGRESSOR** (output [B, T]). "
                "Valid loss types: **smooth_l1**. "
                "Do NOT use ce, focal, or focal_cw (classification only)."
                f"{custom_loss_note}\n"
            )
        else:  # hybrid
            loss_note = (
                "- This model is a **HYBRID** — it supports ALL loss types: "
                "ce, focal, focal_cw, smooth_l1."
                f"{custom_loss_note}\n"
            )

        model_constraint = (
            f"\n### CRITICAL CONSTRAINT:\n"
            f"- You MUST use the '{force_model}' architecture. The model type is fixed and cannot be changed.\n"
            f"{loss_note}"
            f"- Because the architecture is fixed, the Cross-Exploration Rule applies to "
            f"**model_config, loss config, and train config**. You must explore ALL tunable "
            f"parameters in model_config (see the CONFIG MANUAL and MODEL DESCRIPTION for the "
            f"full list — every field is a tuning lever), as well as `loss_type`, `lr`, and "
            f"`batch_size`. Do not repeat the same configuration for more than 2 consecutive "
            f"runs without meaningful improvement. Model-specific parameters (e.g. gate vectors, "
            f"layer counts, channel widths) are equally important as loss and learning rate."
        )
    else:
        model_constraint = (
            "\n- You are free to choose any architecture based on the Cross-Exploration Rule. "
            "Even when switching architectures, continue to vary loss_type and train_config to explore the full search space.\n"
            "- **Loss compatibility**: 'smooth_l1' is ONLY for regressor models (fcnet). "
            "All other models are classifiers — use 'ce', 'focal', or 'focal_cw'."
            f"{custom_loss_note}"
        )

    # Build an OOM warning if any skipped_oom_risk records exist in memory
    oom_records = [r for r in memory_history if r.get("status") == "skipped_oom_risk"]
    oom_warning = ""
    if oom_records:
        last_oom = oom_records[-1]
        fix_hint = last_oom.get("memory", {}).get(
            "memory_update", "Reduce batch_size or segmentation_size."
        )
        oom_warning = (
            f"\n### ⚠️  OOM WARNING — MANDATORY ACTION REQUIRED:\n"
            f"Your last proposed config was REJECTED due to insufficient GPU memory "
            f"(status='skipped_oom_risk'). It was NEVER trained.\n"
            f"Required fix: {fix_hint}\n"
            f"You MUST propose a smaller config this round.\n"
        )

    # An INCONCLUSIVE pre-flight measured nothing, so it must not act as a
    # silent model-size ceiling. Saying so explicitly matters: the agent can
    # still SEE the failed attempts in memory, and without this it reasonably
    # infers that large models are unsafe — which is exactly how the V19
    # campaign of 2026-07-31 collapsed to toy models.
    inconclusive_note = ""
    inconclusive_records = [
        r for r in memory_history if r.get("failure_type") == "inconclusive_preflight"
    ]
    if inconclusive_records:
        inconclusive_note = (
            f"\n### NOTE - INCONCLUSIVE RESOURCE INSPECTION ({len(inconclusive_records)} attempt(s)):\n"
            f"A VRAM pre-flight step did not finish within its own time budget, so "
            f"those attempts have NO resource measurement. This is a limitation of "
            f"the inspection, NOT a measurement of your model.\n"
            f"It does NOT mean the model was too large, too slow, or infeasible. "
            f"Do NOT reduce model capacity, batch size, or segmentation size in "
            f"response to it, and do not treat larger models as unsafe. Only a "
            f"MEASURED out-of-memory result or a MEASURED peak above the VRAM "
            f"budget is evidence about capacity.\n"
        )

    # V20 B-C3b. The note above covers a pre-flight that measured nothing.
    # This one covers the harder case: a real, MEASURED out-of-memory that
    # the runtime attributed to something other than this candidate — a
    # neighbouring process holding the card, host pressure, an external
    # kill, or evidence too thin to settle it. The agent can see an OOM in
    # memory and will otherwise draw the one inference the measurement
    # explicitly refused to support. That inference is what collapsed the
    # V19 campaign to toy models.
    unattributed_oom_note = ""
    unattributed_oom_records = [
        r
        for r in memory_history
        if str(r.get("status", "")).endswith("_oom")
        and not (r.get("failure_attribution") or {}).get("may_recommend_resource_reduction", False)
    ]
    if unattributed_oom_records:
        reasons = {
            (r.get("failure_attribution") or {}).get("attribution", "unknown")
            for r in unattributed_oom_records
        }
        unattributed_oom_note = (
            f"\n### NOTE - OUT-OF-MEMORY NOT ATTRIBUTED TO YOUR CONFIG "
            f"({len(unattributed_oom_records)} attempt(s)):\n"
            f"Those attempts hit a real out-of-memory error, but the runtime "
            f"measurement did NOT attribute it to your configuration "
            f"(outcome(s): {', '.join(sorted(reasons))}).\n"
            f"It does NOT mean the model was too large. Do NOT reduce model "
            f"capacity, batch size, or segmentation size in response to those "
            f"attempts, and do not treat that architecture as infeasible. Only "
            f"an out-of-memory attributed to CANDIDATE CAPACITY — one that "
            f"would not have fitted even with the whole device to itself — is "
            f"evidence about your model's size.\n"
        )

    # Build a timing summary for the last successful experiment so the planner
    # can judge speed against whatever budget is set in the expert advice.
    slow_warning = ""
    slow_records = [
        r for r in memory_history if r.get("status") == "success" and r.get("timing") is not None
    ]
    if slow_records:
        last = slow_records[-1]
        t = last.get("timing", {})
        train_s = t.get("train_time_s") or 0
        infer_s = t.get("inference_time_s") or 0
        total_s = train_s + infer_s
        seg = last.get("params", {}).get("model_config", {}).get("segmentation_size")
        slow_warning = (
            f"\n### ⏱  LAST EXPERIMENT TIMING:\n"
            f"train={train_s / 60:.1f} min, inference={infer_s / 60:.1f} min, "
            f"total={total_s / 60:.1f} min" + (f" (segmentation_size={seg})" if seg else "") + ".\n"
            "The time budget is a HARD UPPER LIMIT, not a target. If the last "
            "run exceeded it, reduce model complexity. If it was well under, "
            "do NOT scale up just because there is headroom — smaller "
            "experiments are equally valid as long as they test the hypothesis.\n"
        )

    # Round context with phase information (when provided)
    round_context = ""
    if current_round is not None and max_rounds is not None:
        is_final = current_round == max_rounds
        rounds_left = max_rounds - current_round
        rounds_completed = current_round - 1

        # Determine current phase and compute rounds remaining in this phase
        progress = current_round / max_rounds
        if progress <= 0.25:
            phase = "Screening"
            phase_end = int(max_rounds * 0.25)
            rounds_in_phase_left = phase_end - current_round + 1
            phase_advice = "Focus on broad exploration with low trial_portion and low epochs."
        elif progress <= 0.75:
            phase = "Refinement"
            phase_end = int(max_rounds * 0.75)
            rounds_in_phase_left = phase_end - current_round + 1
            phase_advice = "Pick top configs from Screening. Increase trial_portion and epochs."
        else:
            phase = "Solidification"
            rounds_in_phase_left = rounds_left + 1  # includes current round
            phase_advice = "Select best candidate. Use high trial_portion or formal mode."

        round_context = (
            f"\n### ROUND CONTEXT:\n"
            f"- Current round: {current_round} / {max_rounds} "
            f"({rounds_completed} completed, {rounds_left} remaining after this one)\n"
            f"- Current phase: **{phase}** ({rounds_in_phase_left} rounds left in this phase) — {phase_advice}\n"
        )
        if is_final and force_formal_round:
            round_context += "- **THIS IS THE FINAL ROUND** — formal mode is MANDATORY. You MUST set `is_trial`: false.\n"
        elif not trial_allowed:
            round_context += "- Trial mode is DISABLED for this run. Set `is_trial`: false.\n"
        elif is_final and not force_formal_round:
            round_context += (
                "- This is the final round. Formal mode is OPTIONAL — you MAY use trial mode "
                "for fast verification when appropriate.\n"
                "- Use trial mode for fast exploration; switch to formal when you want a definitive score.\n"
            )
        else:
            round_context += (
                "- You may choose trial or formal mode.\n"
                "- Use trial mode for fast exploration; switch to formal when you want a definitive score.\n"
            )

    fixed_params_block = _format_fixed_params_block(plan_overrides, max_epochs, resolved_data_scope)

    # Phase K (K.6) — per-round numeric resource block + static guidance.
    # Both blocks are blank-string when no budgets/estimates are configured,
    # which collapses cleanly in the f-string template.
    active_budgets_block = _format_active_resource_budgets_block(
        current_round=current_round,
        last_mode=last_mode,
        trial_vram_budget_gb=trial_vram_budget_gb,
        formal_vram_budget_gb=formal_vram_budget_gb,
        trial_time_budget_minutes=trial_time_budget_minutes,
        formal_time_budget_minutes=formal_time_budget_minutes,
        last_vram_estimate_gb=last_vram_estimate_gb,
        last_time_estimate_minutes=last_time_estimate_minutes,
        last_batch_size=last_batch_size,
    )
    active_budgets_section = f"\n{active_budgets_block}\n" if active_budgets_block else ""
    resource_gate_guidance_section = (
        f"\n{RESOURCE_GATE_GUIDANCE_BLOCK}\n" if active_budgets_block else ""
    )

    return f"""
{fixed_params_block}
### Human Expert Advice:
{expert_advice}

### Current Research Memory:
{history_context}
{dynamics_section}{oom_warning}{inconclusive_note}{unattributed_oom_note}{slow_warning}{round_context}{active_budgets_section}{resource_gate_guidance_section}
### INSTRUCTIONS:
1. **Review Memory**: Look for patterns and previous failures/successes.
   - Records with status='skipped_oom_risk' were NEVER trained — they exceeded GPU memory.
   - Always follow the `memory.memory_update` field of any skipped record before proposing the next config.
   - Check the `timing` field of past experiments and compare against the time budget
     in Expert Advice. Reduce segmentation_size or model complexity if needed.
2. **Follow Expert Advice**: Prioritize the direction suggested by the human expert.
3. **Formulate Hypothesis**: Predict the outcome of this new trial.{model_constraint}
4. **Choose Trial or Formal Mode**: Decide whether to run a fast trial or a full formal evaluation.
5. **Propose Parameters**: Provide the JSON configuration for the next run.

### OUTPUT FORMAT (Strict JSON):
{{
    "model_type": "{force_model if force_model != "auto" else _builtin_roster(task_render)}",
    "reasoning": "How this experiment aligns with expert advice and past memory",
    "hypothesis": "Specific prediction for this run",
    "is_trial": "true | false (choose based on confidence in config)",
    "trial_strategy": "snapshot | anchors | target",
    "trial_portion": "0.02-1.0 (increase if scores are poor — more data helps)",
    "train_portion": "0.1 (rarely change)",
    "eval_strategy": "snapshot | anchors | target",
    "eval_portion": "0.02-1.0 (match trial_portion or larger for reliable scores)",
    "train_validation_align": "true | false",
    "model_config": {{ ... }},
    "train_config": {{ "lr": ..., "epochs": ..., "batch_size": ..., "device": "cuda" }},
    "loss_config": {{ "loss_type": "ce/focal/smooth_l1", ... }}
}}
"""


def get_reflector_user_prompt(
    exp_id,
    hypothesis,
    actual_results,
    reflection_context=None,
    training_diagnosis=None,
    metric_spec=None,
):
    """
    Constructs the prompt for the Reflector to summarize findings into Memory.

    reflection_context (optional dict) keys:
        baseline_score        - denoising score of the paper baseline
        best_score_so_far     - highest denoising score seen across all experiments
        is_new_best           - bool: does this experiment set a new record?
        rank                  - int: rank of this score among all completed experiments (1 = best)
        total_experiments     - int: total completed experiments so far
        best_config_so_far    - dict: params of the experiment with the best score
        best_same_loss_final_loss - float or None: best (lowest) final_loss among experiments
                                   with the same loss_type as this one (None if first of its type)
        current_loss_type     - str: loss_type used in this experiment
    """
    # Step 07 PR 07b (P3) — the CURRENT attempt's dynamics, rendered from the
    # TrainingDiagnosis 07a derived. The reflector receives the diagnosis and
    # nothing else: its `actual_results` already carries this round's
    # `final_loss` / `loss_history`, so a second TrainingHistory transport
    # would restate what is already there and widen the frozen bridge surface.
    dynamics_block = render_reflector_dynamics_block(training_diagnosis)
    # Step 07 PR 07b (P3) — the metric's IDENTITY beside the field name the
    # reflector actually reads. `denoising_score` stays the field (D1 is not
    # 07b's); what it MEASURES is now stated rather than assumed.
    metric_identity_line = render_metric_identity_line(metric_spec) if metric_spec else ""
    context_block = ""
    if reflection_context:
        c = reflection_context
        loss_type = c.get("current_loss_type", "?")
        best_same = c.get("best_same_loss_final_loss")
        loss_rank = c.get("same_loss_loss_rank")
        loss_total = c.get("same_loss_total")
        same_loss_block = (
            f"  final_loss rank (loss_type='{loss_type}') : "
            f"{loss_rank} / {loss_total} (1 = lowest = best convergence)"
            if loss_rank is not None
            else f"  final_loss rank (loss_type='{loss_type}') : first experiment with this loss type"
        )
        efficiency_block = (
            f"  params_ratio          : {c.get('params_ratio', 'N/A')}  "
            f"(current / baseline params; <1.0 = smaller model)\n"
            f"  epochs_ratio          : {c.get('epochs_ratio', 'N/A')}  "
            f"(current / baseline epochs; <1.0 = faster training)\n"
            f"  is_more_efficient     : {c.get('is_more_efficient', 'N/A')}  "
            f"(True = score within {EFFICIENCY_BAND_PCT}% of best AND fewer params or epochs)"
        )
        context_block = f"""
### Comparison Context (use this to judge the result):
  baseline_score        : {c.get("baseline_score", "N/A")}
  best_score_so_far     : {c.get("best_score_so_far", "N/A")}
  this_experiment_score : {actual_results.get("denoising_score", "N/A")}
  is_new_best           : {c.get("is_new_best", "N/A")}
  denoising_score rank  : {c.get("rank", "N/A")} / {c.get("total_experiments", "N/A")} (1 = best)
  {metric_identity_line}
  best_final_loss seen (same loss_type='{loss_type}') : {best_same if best_same is not None else "N/A (first of this type)"}
{same_loss_block}
  best_config_so_far    : {json.dumps(c.get("best_config_so_far"), indent=2) if c.get("best_config_so_far") else "N/A"}
### Efficiency Context:
  baseline_params       : {c.get("baseline_params", "N/A")}
  baseline_epochs       : {c.get("baseline_epochs", "N/A")}
  current_params        : {c.get("current_params", "N/A")}
  current_epochs        : {c.get("current_epochs", "N/A")}
{efficiency_block}
### Data Volume Context:
  training_psd_segments : {c.get("training_psd_segments", "N/A")}  (PSD segments used for training)
  eval_psd_segments     : {c.get("eval_psd_segments", "N/A")}  (PSD segments used for scoring)
  baseline_psd_segments : {c.get("baseline_psd_segments", "N/A")}  (baseline trained on this many)
  trial_portion         : {c.get("trial_portion", "N/A")}
  eval_portion          : {c.get("eval_portion", "N/A")}
  ⚠ If training_psd_segments << baseline_psd_segments, poor scores may be from
     insufficient data, NOT bad hyperparameters. Recommend increasing trial_portion.
"""

    return f"""
### Experiment Outcome for {exp_id}:
- **Original Hypothesis**: {hypothesis}
- **Actual Results**:
{json.dumps(actual_results, indent=2)}
{dynamics_block}
{context_block}
### INSTRUCTIONS:
1. Use the Comparison Context to judge whether this result is good, neutral, or bad.
2. Identify the key factor (loss_type, lr, architecture, etc.) that drove the result.
3. Compare final_loss ONLY against experiments with the same loss_type.
4. Synthesize a new Memory Entry.
5. Output a strict JSON containing the new insights.

### OUTPUT FORMAT (Strict JSON):
{{
    "conclusion": "Clear verdict: good/neutral/bad relative to baseline and best score, with reason",
    "key_factor": "The specific hyperparameter change most responsible for this result",
    "discovery": "One technical insight gained from this experiment",
    "memory_update": "Actionable advice for the next round based on this result"
}}
"""
