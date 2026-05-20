# agent/prompts.py
import inspect
import json

# ==========================================
# 1. SYSTEM PROMPTS (The Core Logic)
# ==========================================

PLANNER_PROMPT = """
You are a Senior Signal Processing Researcher specialized in deep learning for signal denoising.
Your goal is to optimize the 'Denoising Score' for the TIDMAD dataset.

### AVAILABLE MODELS:
1. **PositionalUNet (punet)**: U-Net with positional encoding for global signal structures.
2. **FCNet (fcnet)**: Fully-connected AutoEncoder, efficient for local smoothing.
3. **TransformerModel (transformer)**: Self-attention over time steps; memory scales O(T²) — use small segmentation_size.
4. **SimpleWaveNet (wavenet)**: Dilated causal convolutions; memory-efficient.
5. **RNNSeq2Seq (rnn)**: LSTM encoder-decoder; memory grows linearly with batch_size × segmentation_size.

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
  loss_type, and regularization. Goal: maximize score with sufficient data.
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

### EFFICIENCY AWARENESS:
- A simpler model (fewer parameters) or shorter training (fewer epochs) that achieves a score
  within 5% of the current best is a **highly valuable result** — prefer it over marginal gains
  from larger, slower experiments.
- When memory shows `is_more_efficient=True` for a past experiment, note its config:
  simpler configurations often generalise better and should be preferred as a starting point.
- Do not blindly scale up architecture or epochs when scores plateau. Instead, try:
    - Smaller model with better regularisation (dropout, weight_decay)
    - Fewer epochs with a better learning rate schedule
    - Different loss functions that may converge faster

### TRAINING vs VALIDATION — CRITICAL:
- `final_loss` / `loss_history` in memory records = measured on the **TRAINING dataset**.
- `denoising_score` in memory records = measured on the **VALIDATION dataset**.
- These are different datasets. Always look at BOTH when reading past results:
    - Low training loss + poor denoising score → overfitting → propose stronger regularisation
      (higher dropout, weight_decay, fewer epochs, smaller model).
    - High training loss + poor denoising score → underfitting → propose larger model or more epochs.
    - Both improve together → the direction is correct, continue exploring.

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
  all data on those files. Useful when the per-file score table indicates a small set of
  files carries most of the next-iter improvement budget — those are the files with the
  largest `Impact_Score` for the current best model. Choosing `target_files` is a
  data-allocation decision; it should be driven by the Impact_Score column, not by
  fixed file-index labels or thresholds.

**Key tradeoff**: snapshot gives broad but shallow coverage per file. anchors and target
give deep coverage on fewer files. Consult the per-file score table below — if
`Impact_Score` is roughly uniform across files, snapshot is efficient. If a small subset
of files dominates the `Impact_Score` ranking, target those files.

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
- Compare `training_psd_segments` across records. The baseline typically trains on 4000 segments.
  If your experiments train on 200 segments, you have 20× less data — increase trial_portion.
- Scores from larger portions are more reliable. A formal score (eval_portion=1.0) is the most
  definitive.

### PER-FILE PERFORMANCE TABLE:

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

{SCORE_COMPARISON_TABLE}

Use this table — not just the scalar — to decide where to focus next.

### OUTPUT REQUIREMENT:
You must provide the next experiment setup in a strict JSON format.
"""

REFLECTOR_PROMPT = """
You are a Research Analyst. Your job is to transform raw experiment results into **Research Memory**.

### OBJECTIVES:
- **Validate Hypothesis**: Compare the initial hypothesis with the actual Denoising Score and Loss.
- **Extract Discovery**: Identify a specific pattern or rule learned from this run.
- **Update Memory**: Write a concise 'Memory Entry' that will guide the Planner in the next iteration.

### CRITICAL — GAP ANALYSIS (Generalization Gap):
- `final_loss` and `loss_history` are measured on the **TRAINING dataset**.
- `denoising_score` is measured on the **VALIDATION dataset**.
- These are completely separate datasets. You MUST explicitly analyze the "Generalization Gap":
    - Training loss decreases BUT denoising score does not improve → **OVERFITTING**.
      Gap is widening. Action: increase dropout, weight_decay, or reduce model size/epochs.
    - Training loss is high AND denoising score is poor → **UNDERFITTING** or **INSUFFICIENT DATA**.
      Both metrics are stagnant. Action: if trial_portion < 0.1, recommend increasing data first.
      If trial_portion is already large, increase model capacity or epochs.
    - Both improve together → healthy generalisation. Gap is stable or narrowing.

### CRITICAL — HOW TO JUDGE THE DENOISING SCORE:
- The Denoising Score is a relative metric. Its absolute value and sign mean nothing in isolation.
- ALWAYS compare against the Baseline Score and Best Score So Far provided in the context.
- A result is GOOD if its denoising_score is HIGHER than the best score so far.
- A result is NEUTRAL if it matches previous scores.
- A result is BAD if it is LOWER than most previous scores.
- NEVER call a result a failure just because the score is negative.

### PER-FILE COMPARISON (Impact-Aware):
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
planner inherits them.

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
- Even if this is NOT a new best, a small model within 5% of the best score is a meaningful result.

### CRITICAL — EFFICIENCY BENCHMARKING:
A configuration is only "Better" if it beats the best score. But a configuration is
"Valuable" if it achieves ≥95% of the best score with <50% of the parameters or training
time. Flag these as **High-Efficiency Discoveries** in your discovery and memory_update.
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

    # Collect tried values per parameter from successful + error records
    model_cfg_tried: dict[str, set] = {}
    loss_cfg_tried: dict[str, set] = {}
    train_cfg_tried: dict[str, set] = {}

    for rec in memory_history:
        params = rec.get("params", {})
        for key, val in params.get("model_config", {}).items():
            if key in _CHECKLIST_SKIP_FIELDS:
                continue
            model_cfg_tried.setdefault(key, set())
            # Convert lists/dicts to string for set storage
            model_cfg_tried[key].add(str(val) if isinstance(val, (list, dict)) else val)

        for key, val in params.get("loss_config", {}).items():
            loss_cfg_tried.setdefault(key, set())
            loss_cfg_tried[key].add(val)

        for key, val in params.get("train_config", {}).items():
            if key in _CHECKLIST_SKIP_FIELDS:
                continue
            train_cfg_tried.setdefault(key, set())
            train_cfg_tried[key].add(val)

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
        tried = model_cfg_tried.get(field, set())
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

        # Format tried values concisely
        if tried:
            tried_str = ", ".join(str(v) for v in sorted(tried, key=str))
            if len(tried_str) > 80:
                tried_str = tried_str[:77] + "..."
        else:
            tried_str = f"default={default}"

        # Append bounds so the LLM cannot propose out-of-range values
        suffix = f" — {status}"
        if bounds:
            suffix += f" — {bounds}"
        lines.append(f"- {marker} `{field}`: {tried_str}{suffix}")

    # Loss config
    lines.append("\n**loss_config:**")
    for key, tried in loss_cfg_tried.items():
        tried_str = ", ".join(str(v) for v in sorted(tried, key=str))
        marker = "[x]" if len(tried) >= 2 else "[ ]"
        lines.append(f"- {marker} `{key}`: {tried_str}")

    # Train config (just lr and epochs — most impactful)
    lines.append("\n**train_config:**")
    for key in ["lr", "epochs", "optimizer_type", "weight_decay"]:
        tried = train_cfg_tried.get(key, set())
        if not tried:
            continue
        tried_str = ", ".join(str(v) for v in sorted(tried, key=str))
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


def _format_fixed_params_block(plan_overrides=None, max_epochs=None):
    """
    Render a SYSTEM-FIXED PARAMETERS block for the planner prompt when the
    operator has frozen any plan fields via ``plan_overrides`` or capped
    ``max_epochs``. Returns an empty string when nothing is set, so the prompt
    is unchanged for runs that do not use overrides.

    The block tells the LLM (a) which fields it does NOT control this run, and
    (b) that the standard prompt's phase-progression / "increase trial_portion"
    advice does not apply when those knobs are frozen. Without this, the LLM
    wastes reasoning on knobs the workflow silently overrides.
    """
    overrides = dict(plan_overrides) if plan_overrides else {}
    has_max_epochs = max_epochs is not None
    if not overrides and not has_max_epochs:
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
    # Render any other override keys generically
    rendered_keys = {"is_trial", "trial_portion", "train_portion", "eval_portion"}
    for k, v in overrides.items():
        if k not in rendered_keys:
            lines.append(f"  {k:16s} = {v}")
    if has_max_epochs:
        lines.append(f"  epochs (cap)     ≤ {max_epochs}      ← higher values are clamped")

    fixed_lines = "\n".join(lines)
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
  - trial_strategy + target_files; eval_strategy; train_validation_align

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


def _truncate_memory_history(
    records: list[dict],
    full_window: int = 3,
) -> list[dict]:
    """Sliding-window truncation for the planner's history context.

    Args:
        records:     Full experiment record list from sandbox.get_summary().
        full_window: Number of most-recent records to keep verbatim.

    Returns:
        New list (non-destructive). Recent records are unchanged; older
        records are condensed to identity + score + hypothesis/conclusion.
    """
    if len(records) <= full_window:
        return list(records)

    cutoff = len(records) - full_window
    condensed: list[dict] = []
    for rec in records[:cutoff]:
        entry = {k: rec[k] for k in _CONDENSED_KEYS if k in rec}
        memory = rec.get("memory", {})
        if memory:
            entry["memory"] = {k: memory[k] for k in _CONDENSED_MEMORY_KEYS if k in memory}
        condensed.append(entry)

    return condensed + list(records[cutoff:])


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
    # --- Phase K (K.6) — [ACTIVE RESOURCE BUDGETS] block inputs ---
    trial_vram_budget_gb=None,
    formal_vram_budget_gb=None,
    trial_time_budget_minutes=None,
    formal_time_budget_minutes=None,
    last_vram_estimate_gb=None,
    last_time_estimate_minutes=None,
    last_batch_size=None,
    last_mode=None,
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

    # Handle the model constraint message + output type / valid losses
    model_constraint = ""
    if force_model != "auto":
        from ml_models.plugin_loader import get_output_type

        output_type = get_output_type(force_model)
        if output_type == "classifier":
            loss_note = (
                "- This model is a **CLASSIFIER** (output [B, 256, T]). "
                "Valid loss types: **ce, focal, focal_cw**. "
                "Do NOT use smooth_l1 (regression only).\n"
            )
        elif output_type == "regressor":
            loss_note = (
                "- This model is a **REGRESSOR** (output [B, T]). "
                "Valid loss types: **smooth_l1**. "
                "Do NOT use ce, focal, or focal_cw (classification only).\n"
            )
        else:  # hybrid
            loss_note = (
                "- This model is a **HYBRID** — it supports ALL loss types: "
                "ce, focal, focal_cw, smooth_l1.\n"
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

    fixed_params_block = _format_fixed_params_block(plan_overrides, max_epochs)

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
{oom_warning}{slow_warning}{round_context}{active_budgets_section}{resource_gate_guidance_section}
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
    "model_type": "{force_model if force_model != "auto" else "punet | fcnet | transformer | wavenet | rnn | gated_fno"}",
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


def get_reflector_user_prompt(exp_id, hypothesis, actual_results, reflection_context=None):
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
            f"(True = score within 5% of best AND fewer params or epochs)"
        )
        context_block = f"""
### Comparison Context (use this to judge the result):
  baseline_score        : {c.get("baseline_score", "N/A")}
  best_score_so_far     : {c.get("best_score_so_far", "N/A")}
  this_experiment_score : {actual_results.get("denoising_score", "N/A")}
  is_new_best           : {c.get("is_new_best", "N/A")}
  denoising_score rank  : {c.get("rank", "N/A")} / {c.get("total_experiments", "N/A")} (1 = best)
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
  ⚠ NOTE: final_loss/loss_history above = TRAINING dataset.
           denoising_score above = VALIDATION dataset (different data).
           Reason about the gap between them to detect overfitting or underfitting.
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
