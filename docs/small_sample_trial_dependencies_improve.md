# Downstream Agent Improvements for Multi-Fidelity Tuning

## Status: DESIGN — ready for implementation

## Context

The hyperparameter tuner now produces rich per-round data: `file_vector` (per-file
denoising scores), `training_psd_segments` / `eval_psd_segments` (data volume),
trial/formal mode context, `model_params`, and timing. However, the interpretation
agent and model proposal agent were built before the trial/formal feature existed.
They receive only a compressed summary (scores + one-line conclusions) and lose all
the granular information that could enable smarter diagnosis and more targeted
architecture proposals.

This document describes the changes needed to propagate trial context through the
full agent loop: **Tuner → Interpretation → Proposal → back to Tuner**.

---

## Current Data Flow (what's lost)

```
HyperparamTuningOutput (rich)
    │
    │  ml_model_tune_to_ml_result_interp::local_all_records
    │  ┌─────────────────────────────────────────────────────┐
    │  │ KEPT: model_type, run_name, status, completed_rounds │
    │  │       best_score, worst_score, best_config           │
    │  │       round_scores[], round_conclusions[]             │
    │  │                                                       │
    │  │ LOST: file_vector (per-file performance)              │
    │  │       training_psd_segments, eval_psd_segments         │
    │  │       trial context (is_trial, portion, strategy)     │
    │  │       model_params (parameter count)                  │
    │  │       loss_history (training curves)                  │
    │  │       timing (train/infer/score durations)            │
    │  │       formal vs trial score distinction               │
    │  └─────────────────────────────────────────────────────┘
    ▼
InterpretationInput (compressed)
    │
    │  Interpretation agent (LLM analysis)
    ▼
InterpretationOutput
    │
    │  ml_result_interp_to_ml_model_propose::local_full_context
    ▼
ProposalInput
    │
    │  Proposal agent (LLM design)
    ▼
ProposalOutput.expert_advice → HyperparamTuningInput (next model)
```

---

## Proposed Changes

### Step 1: Enrich `ModelRunSummary` schema

**File:** `agent/schemas/interpretation.py`

Add trial context and performance detail fields to `ModelRunSummary`:

```python
class ModelRunSummary(BaseModel):
    # --- Existing fields (unchanged) ---
    model_type: str
    run_name: str
    status: str
    completed_rounds: int
    best_denoising_score: Optional[float]
    worst_denoising_score: Optional[float]
    best_config: Optional[Dict[str, Any]]
    round_scores: List[Optional[float]]
    round_conclusions: List[Optional[str]]

    # --- New: per-file performance ---
    best_file_vector: Optional[List[float]] = None
    # Length-20 score vector from the best experiment. Each index = one
    # validation file (frequency, log scale: 0=lowest, 19=highest).
    # NaN for files not evaluated. Reveals frequency-dependent weaknesses.

    formal_score: Optional[float] = None
    # Score from the formal (final) round specifically, if available.
    # Distinct from best_denoising_score which may come from a trial round.

    formal_file_vector: Optional[List[float]] = None
    # File vector from the formal round. Definitive per-file performance.

    # --- New: model efficiency ---
    best_model_params: Optional[int] = None
    # Number of trainable parameters in the best-scoring model.

    # --- New: data volume context ---
    training_psd_segments: Optional[int] = None
    # PSD segments used for training in the best experiment.
    # Compare against baseline (typically 4000) to assess data sufficiency.

    eval_psd_segments: Optional[int] = None
    # PSD segments used for evaluation in the best experiment.

    trial_portion: Optional[float] = None
    # Trial portion used in the best experiment (if trial mode).

    # --- New: per-round detail ---
    round_trial_portions: Optional[List[Optional[float]]] = None
    # Trial portion used in each round. Shows if the agent adapted data volume.

    round_model_params: Optional[List[Optional[int]]] = None
    # Model parameter count per round. Shows if the agent explored model sizes.
```

### Step 2: Update protocol `ml_model_tune_to_ml_result_interp`

**File:** `agent/schemas/protocols/ml_model_tune_to_ml_result_interp.py`

Update `local_all_records()` to extract the new fields from `HyperparamTuningOutput`:

```python
def local_all_records(tuning_output: HyperparamTuningOutput) -> ModelRunSummary:
    records = tuning_output.all_records
    success = [r for r in records if r.status == "success" and r.denoising_score is not None]

    # Find best record
    best_rec = max(success, key=lambda r: r.denoising_score) if success else None

    # Find formal round (last record with is_trial=False, or the last record)
    formal_rec = None
    for r in reversed(success):
        if not r.is_trial:
            formal_rec = r
            break

    return ModelRunSummary(
        # Existing
        model_type=tuning_output.model_type,
        run_name=tuning_output.run_name,
        status=tuning_output.status,
        completed_rounds=tuning_output.completed_rounds,
        best_denoising_score=tuning_output.best_denoising_score,
        worst_denoising_score=min(r.denoising_score for r in success) if success else None,
        best_config=tuning_output.best_config,
        round_scores=[r.denoising_score for r in records],
        round_conclusions=[r.memory.conclusion if r.memory else None for r in records],

        # New: per-file performance
        best_file_vector=best_rec.file_vector if best_rec else None,
        formal_score=formal_rec.denoising_score if formal_rec else None,
        formal_file_vector=formal_rec.file_vector if formal_rec else None,

        # New: efficiency
        best_model_params=best_rec.model_params if best_rec else None,

        # New: data volume
        training_psd_segments=best_rec.training_psd_segments if best_rec else None,
        eval_psd_segments=best_rec.eval_psd_segments if best_rec else None,
        trial_portion=best_rec.trial_portion if best_rec else None,

        # New: per-round detail
        round_trial_portions=[r.trial_portion for r in records],
        round_model_params=[r.model_params for r in records],
    )
```

### Step 3: Update interpretation agent prompts

**File:** `nodes/result_interpretation_agent.py`

**Phase 1 (per-model) prompt additions:**

Add to the per-model LLM context:
- `file_vector` with explanation: "Per-file scores (file 0=lowest freq, file 19=highest).
  Identify which frequency ranges the model handles well vs poorly."
- Data volume: "Trained on X PSD segments (baseline: 4000). If X << 4000, poor scores
  may reflect insufficient data, not bad architecture."
- Formal vs trial: "Trial best: X (at portion Y). Formal score: Z (all data).
  Gap between trial and formal indicates sensitivity to data volume."
- Model params: "Best model has N parameters."

**Phase 2 (cross-model synthesis) prompt additions:**

Add to the cross-model context:
- Per-model file vectors for comparison: "PUNet scores near zero on files 0-3 but high
  on files 14-15. WaveNet scores well across all files. This suggests PUNet struggles
  with low frequencies."
- Efficiency comparison: "Model A achieves 90% of best score with 50% fewer parameters."

### Step 4: Enrich `InterpretationOutput`

**File:** `agent/schemas/interpretation.py`

Add fields for the interpreter to pass frequency analysis and trial context downstream:

```python
class InterpretationOutput(BaseModel):
    # --- Existing fields (unchanged) ---
    model_types: List[str]
    model_descriptions: Dict[str, str]
    per_model_summaries: Dict[str, PerModelSummary]
    per_model_best: Dict[str, float]
    per_model_worst: Dict[str, float]
    best_denoising_score: float
    worst_denoising_score: float
    best_config: Optional[Dict[str, Any]]
    key_findings: List[str]
    bottlenecks: List[str]
    take_home_message: str

    # --- New: frequency analysis ---
    per_model_file_vectors: Optional[Dict[str, List[float]]] = None
    # Best file_vector per model. Enables the proposal agent to see
    # which frequency ranges each architecture handles well.

    weak_frequency_files: Optional[Dict[str, List[int]]] = None
    # File indices where each model scores poorly (below threshold).
    # Computed by the interpreter from file_vector analysis.

    # --- New: efficiency context ---
    per_model_params: Optional[Dict[str, int]] = None
    # Parameter count of best model per architecture.

    # --- New: data volume context ---
    per_model_training_segments: Optional[Dict[str, int]] = None
    # Training PSD segments used per model's best experiment.
```

### Step 5: Update proposal agent prompt

**File:** `nodes/ml_model_proposal_agent.py`

**Call 1 (Reasoning) prompt additions:**

Add to the context the proposal agent sees:
- Per-model file vectors: show which frequencies are weak/strong per architecture
- "If file_vector shows all models struggle with files 0-3 (low frequencies), the new
  architecture should specifically target low-frequency signal recovery."
- Efficiency data: "Model A has N params, Model B has M params. Consider whether
  a smaller model could achieve comparable performance."
- Data volume context: "Models were trained with trial_portion=X. If scores are low
  and data was sparse, the new model should be designed to learn efficiently from
  limited data (e.g., strong inductive biases, skip connections)."

**Call 2 (Commit) prompt additions:**

Instruct the proposal agent to include in `expert_advice`:
- `suggested_directions` should include trial parameter guidance:
  - Recommended `trial_portion` based on model complexity
  - Recommended `epochs` for this architecture
  - Whether to use `snapshot` vs `target` strategy based on file_vector weaknesses
  - Frequency-specific training advice if file_vector shows patterns
- `constraints` should include data-aware limits:
  - "Start with trial_portion >= 0.1 — this architecture needs sufficient data"
  - "Use snapshot strategy for first 5 rounds, then switch to target on weak files"

### Step 6: Update protocol `ml_result_interp_to_ml_model_propose`

**File:** `agent/schemas/protocols/ml_result_interp_to_ml_model_propose.py`

Pass the new `InterpretationOutput` fields through to `ProposalInput`. Since the
protocol already passes the full `InterpretationOutput` as a serialized context,
this may require minimal changes — just ensure the new fields are included in the
serialization.

### Step 7: Update tests

**Files:**
- `tests/unit/agent/tune_ml_hyperparam_agent/test_hyperparam_schemas.py` — update
  `ModelRunSummary` fixtures with new fields
- `tests/unit/agent/protocols/test_ml_model_tune_to_ml_result_interp.py` — test
  that new fields are extracted correctly
- `tests/unit/agent/protocols/test_ml_result_interp_to_ml_model_propose.py` — test
  that new fields flow through
- `tests/integration/protocols/test_tune_to_interpret.py` — integration test with
  real data should produce non-null file vectors

---

## Implementation Order

```
Step 1: ModelRunSummary schema (add fields)
    │
Step 2: Protocol tuner → interpretation (extract fields)
    │
Step 3: Interpretation agent prompts (use fields in LLM context)
    │
Step 4: InterpretationOutput schema (add fields)
    │
Step 5: Proposal agent prompts (include trial guidance in expert_advice)
    │
Step 6: Protocol interpretation → proposal (pass fields through)
    │
Step 7: Tests (all steps)
```

Steps 1-2 can be tested independently (tuner → interpretation edge).
Steps 3-4 can be tested independently (interpretation agent with enriched input).
Steps 5-6 can be tested independently (proposal agent with enriched interpretation).
Step 7 verifies end-to-end.

---

## Backward Compatibility

All new fields are `Optional` with `None` defaults. Existing records from the `v0`
run (which lack `file_vector`, `training_psd_segments`, etc.) will produce `None`
for the new fields. The interpretation agent should handle `None` gracefully —
only include file_vector analysis when the data is available.

The proposal agent's enhanced `expert_advice` is backward compatible — the tuner
already consumes `ExpertAdvice` and the new guidance goes into existing fields
(`suggested_directions`, `constraints`). No schema change needed on `ExpertAdvice`.

---

## Expected Impact

1. **Interpretation agent** can now diagnose:
   - "PUNet struggles with low frequencies (files 0-3 near zero)" — from `file_vector`
   - "Scores are low because only 200 PSD segments were used" — from `training_psd_segments`
   - "Trial best was 0.67 but formal score was 1.07 — data volume matters" — from `formal_score`

2. **Proposal agent** can now advise:
   - "Start with trial_portion=0.2 — this model has many parameters and needs data"
   - "Use target strategy on files [0,1,2,3] — existing models struggle with low frequencies"
   - "Expect 10+ epochs for convergence based on similar model sizes"

3. **Tuner** receives richer expert advice that includes trial parameter guidance,
   making it more likely to use appropriate data volumes and strategies from round 1.
