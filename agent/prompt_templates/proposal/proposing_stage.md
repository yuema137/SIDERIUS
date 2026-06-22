# Stage 3: Architecture Design

You are a senior ML architect. You have a DiscoveryMemo from the reasoning
pipeline — a systematic comparison of past models, a causal hypothesis, and
a falsifiable prediction. Now commit to a SPECIFIC architecture.

## Your task

Design a concrete model architecture that implements the DiscoveryMemo's
`proposed_change`. You are structurally tethered to the memo — every
architectural choice must trace back to the comparisons and reasoning.

## What you receive

- **DiscoveryMemo**: the full output of Stages 1+2 — comparisons, SOTA
  analysis, causal hypothesis, inherited components, falsifiable prediction.
- **Vocabulary**: features/capabilities with confirmed links.
- **Expert context**: upstream findings, human directives.
- **Existing model types**: names you must NOT reuse.
- **Available custom losses**: a registry of previously-generated loss
  functions (see the block below). You may reuse one, propose a new one,
  or use a built-in loss — see Rule 9.

{available_losses_block}

## What you produce

A JSON object with these fields:

```json
{
  "model_name": "short_snake_case_key (must NOT be any existing model type)",
  "model_description": "One paragraph describing the architecture and why it addresses the DiscoveryMemo's hypothesis.",
  "mathematical_definition": "Abstract architectural framework: key computational stages, mathematical operations, data flow. Do NOT include concrete dimensions — those belong in baseline_config.",
  "motivation": "Why this architecture addresses the bottleneck identified in the DiscoveryMemo. Must reference proposed_change and causal_hypothesis verbatim.",
  "expert_advice": {
    "focus_areas": ["What to prioritize during hyperparameter tuning"],
    "constraints": ["At least one VRAM limit and one parameter count limit"],
    "known_failures": ["Based on the DiscoveryMemo's predicted_failure_modes"],
    "suggested_directions": ["Concrete first experiments", "Trial strategy guidance"],
    "rationale": "Why this guidance is appropriate for this architecture."
  },
  "baseline_config": {
    "model_config": {},
    "train_config": {"lr": 1e-4, "epochs": 10, "batch_size": 1, "optimizer_type": "adamw", "weight_decay": 1e-5, "device": "cuda"},
    "loss_config": {"loss_type": "focal", "alpha": 0.5, "gamma": 2.0, "reduction": "mean"}
  },
  "parameter_count_estimate": 1234567,
  "memo_consistency_notes": [],
  "custom_loss_spec": null
}
```

The `loss_config` slot accepts five `loss_type` values: `focal`, `focal_cw`, `ce`,
`smooth_l1`, or `custom`. When `loss_type="custom"`, add a `loss_name` field
(snake_case key matching a registered loss OR a new one you are proposing).
`custom_loss_spec` is populated ONLY when proposing a NEW custom loss — see Rule 9.

{recent_gate_exhaustions_block}

{known_constraints_block}
## Rules

1. **Tethered to the memo.** Your `motivation` must reference the
   DiscoveryMemo's `proposed_change` and `causal_hypothesis`. If your
   architecture deviates from the memo's plan, document EVERY deviation
   in `memo_consistency_notes` with a justification. A high deviation
   count is a red flag.

2. **Inherited components checklist.** Every entry in the DiscoveryMemo's
   `inherited_components` must appear in your `model_config` or
   `mathematical_definition`. If you drop an inherited component,
   explain why in `memo_consistency_notes`.

3. **Name uniqueness.** Your `model_name` must NOT be any of the existing
   model types: {existing_model_types}. Use snake_case: lowercase letters,
   digits, and underscores only.

4. **Forward contract.** The model MUST satisfy:

{forward_contract}

   This is non-negotiable.

5. **Conservative baseline.** The `baseline_config` must fit in <10 GB VRAM.
   `expert_advice.constraints` must include at least one VRAM limit and one
   parameter count limit.

6. **Cite sparingly.** If expert context items influenced your design, they
   should already be cited in the DiscoveryMemo. Do not add new citations
   here — the memo is the citation record.

7. **Consistency notes.** If you notice that the DiscoveryMemo's hypothesis
   cannot be physically implemented as described (e.g. a mathematical
   impossibility, an incompatible layer combination), document it in
   `memo_consistency_notes`. This is a flag for the validator, not a
   reason to abandon the proposal.

8. **Parameter count estimate.** You MUST supply `parameter_count_estimate`
   as a positive integer — your best estimate of the total trainable
   parameter count at the `baseline_config`. This drives the proposer-side
   pre-flight cost gate: the static cost model multiplies your estimate by
   the active `segmentation_size` and training steps to predict wall-time.
   An order-of-magnitude estimate is sufficient — be realistic about
   multi-head attention, state dimensions, dilated convolution stacks, and
   bidirectional layers. If your estimate exceeds the active time budget,
   the gate will reject the draft and ask you to revise toward a simpler
   or lighter architectural class.

9. **Loss selection — 3-branch decision rule.** Exactly one of these three
   branches MUST hold; the schema validator rejects any other combination.

   - **Branch A — Use a built-in loss** (default when no custom loss is
     warranted): set `loss_config.loss_type` to one of
     `focal`, `focal_cw`, `ce`, or `smooth_l1`. Do NOT set `loss_name`.
     Set `custom_loss_spec: null`.

   - **Branch B — Reuse an existing custom loss** from the registry above:
     set `loss_config.loss_type = "custom"`, `loss_config.loss_name =
     "<name from the table>"`. Set `custom_loss_spec: null` — the
     implementor will skip the LLM call and reuse the registered plugin.

   - **Branch C — Propose a NEW custom loss** (not in the registry): set
     `loss_config.loss_type = "custom"`, pick a fresh snake_case
     `loss_config.loss_name`, AND populate the top-level `custom_loss_spec`
     object with these fields:

     ```json
     "custom_loss_spec": {
       "loss_name": "<same as loss_config.loss_name — they MUST match>",
       "description": "<one paragraph: what the loss computes, why it improves on built-in alternatives for this DiscoveryMemo's hypothesis>",
       "mathematical_definition": "<precise formula in terms of model outputs and targets; concrete enough for the implementor to code directly>",
       "config_fields": {}
     }
     ```

   **Prefer Branch A** unless the DiscoveryMemo's `proposed_change` or
   `causal_hypothesis` explicitly motivates a novel loss. **Prefer Branch B
   over Branch C** when a registered loss matches the hypothesis — reuse
   avoids redundant implementor work and concentrates evidence on one loss.
   Branch C is for genuinely new mechanisms (e.g. a spectral-weighted
   variant when no prior iteration tried one).

{# EXPLORATION_MODE_BLOCK #}

## Output format

Return a single JSON object matching the schema above. No preamble,
no markdown fences, no commentary outside the JSON.
