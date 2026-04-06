# Soft Edges: Expert Advice for All Nodes

## Status: COMPLETE

## Motivation

The SIDERIUS graph has two types of inter-node communication:

- **Hard edges** (protocols): typed data pipelines with schema-validated input/output.
  These define the required data flow. Adding a new hard edge requires a new protocol
  file, schema changes, and tests.

- **Soft edges** (expert_advice): advisory information from any source — upstream agents,
  parallel agents, or humans. These carry guidance that influences the LLM's decisions
  but don't change the node's data contract.

Currently, only `tune_ml_hyperparam_agent` has `expert_advice: ExpertAdviceInput` as
input. All other nodes have only `human_advice: Optional[str]`. This limits the system's
extensibility — when we want a new agent to advise an existing node, we'd have to modify
the schema.

## Design Principle

**Every node should accept `expert_advice` as a standard soft input**, using the same
`ExpertAdvice` schema. This enables:

1. **Any agent can advise any other agent** without new protocols
2. **Humans override expert advice** — `human_advice` always has higher priority
3. **Multiple advisors** can contribute — expert_advice can be merged from multiple sources
4. **Future nodes attach without schema changes** — just wire the expert_advice

## Priority Hierarchy

```
human_advice         (highest — human always overrides)
    │
expert_advice        (structured guidance from upstream/parallel agents)
    │
LLM's own judgment   (lowest — the node's internal LLM reasoning)
```

## Current State

| Node | `expert_advice` | `human_advice` | Status |
|------|----------------|----------------|--------|
| `tune_ml_hyperparam_agent` | ✅ `ExpertAdviceInput` | ✅ `Optional[str]` | Complete |
| `result_interpretation_agent` | ✅ `ExpertAdviceInput` | ✅ `Optional[str]` | Complete |
| `ml_model_proposal_agent` | ✅ `ExpertAdviceInput` | ✅ `Optional[ExpertAdviceInput]` | Complete |
| `ml_model_implementor` | ✅ `ExpertAdviceInput` | ✅ `Optional[str]` | Complete |
| `ml_code_validator_agent` | ✅ `ExpertAdviceInput` | ✅ `Optional[str]` | Complete |

## Proposed Change

Add `expert_advice: ExpertAdviceInput = Field(default="")` to each node's input schema.
The `ExpertAdviceInput` type is `Union[str, ExpertAdvice]` — accepts either a plain
string or the structured `ExpertAdvice` object.

### ExpertAdvice schema (already exists)

```python
class ExpertAdvice(BaseModel):
    focus_areas: List[str]           # What to prioritize
    constraints: List[str]           # Hard limits to respect
    known_failures: List[str]        # What to avoid
    suggested_directions: List[str]  # Concrete actions to try
    rationale: str                   # Why this guidance applies
```

This schema is generic enough for any node:

| Node | Example `focus_areas` | Example `constraints` |
|------|----------------------|----------------------|
| Interpreter | "Focus on frequency-dependent performance" | "Compare all models on same data volume" |
| Proposal | "Prioritize architectures with skip connections" | "Model must be < 50K parameters" |
| Implementor | "Use only Conv1d and ReLU" | "No external dependencies" |
| Validator | "Pay extra attention to gradient flow" | "Must pass within 2 attempts" |
| Tuner | "Start with trial_portion=0.2" | "VRAM < 10 GB" |

### Implementation Steps

1. **Schema changes** — add `expert_advice: ExpertAdviceInput = Field(default="")` to:
   - `InterpretationInput`
   - `ProposalInput`
   - `ImplementorInput`
   - `ValidatorInput`

2. **Node prompt injection** — each node serializes `expert_advice` and injects it
   into the LLM prompt, similar to how the tuner does it (using `_serialize_expert_advice`).
   Position: after the main context, before human_advice (so human has last word).

3. **Workflow wiring** — `model_exploration.py` can optionally pass expert_advice
   from one node to another (e.g., interpreter → proposal, validator → implementor).

4. **Tests** — verify each node accepts both string and structured ExpertAdvice.

### Files to change

| File | Change |
|------|--------|
| `agent/schemas/interpretation.py` | Add `expert_advice` field |
| `agent/schemas/proposal.py` | Add `expert_advice` field (rename current `human_advice` type?) |
| `agent/schemas/implementor.py` | Add `expert_advice` field |
| `agent/schemas/validator.py` | Add `expert_advice` field |
| `nodes/result_interpretation_agent.py` | Inject expert_advice in prompts |
| `nodes/ml_model_proposal_agent.py` | Inject expert_advice in prompts |
| `nodes/ml_model_implementor.py` | Inject expert_advice in prompts |
| `nodes/ml_code_validator_agent.py` | Inject expert_advice in prompts |
| `workflows/model_exploration.py` | Optionally wire expert_advice between nodes |
| Tests | Update fixtures for each node |

## Example Future Use Cases

1. **`data_analysis_agent` → `interpreter`**: "The dataset has a 10× imbalance in
   signal strength between files 0-3 and files 15-19. Weight your analysis accordingly."

2. **`resource_monitor_agent` → `tuner`**: "GPU memory is 75% used. Reduce batch_size
   for the next round."

3. **`interpreter` → `proposal`**: "All models fail on files 0-3 (low frequencies).
   The new architecture must specifically handle long-wavelength signals."
   (Currently this flows through the serialized interpretation dict, but structured
   ExpertAdvice would make it explicit and actionable.)

4. **`validator` → `implementor`**: "The previous implementation failed gradient flow
   check due to vanishing gradients through 8 sequential layers. Add residual connections."
   (Currently this flows through `previous_failures`, but ExpertAdvice would be richer.)

## Backward Compatibility

- `expert_advice` defaults to `""` (empty string) — existing code works unchanged
- `ExpertAdviceInput = Union[str, ExpertAdvice]` — both forms accepted
- No protocol changes needed — expert_advice is a soft input, not a protocol field
