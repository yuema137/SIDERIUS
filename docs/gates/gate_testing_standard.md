# SIDERIUS Gate Testing Standard

**Status**: Canonical (2026-06-19)  
**Source**: Extracted from `enable_global_task_config` Checkpoint T lesson learned.  
**Purpose**: Reusable gate definitions for all SIDERIUS feature design docs.

---

## Gate definitions

Every SIDERIUS feature commit plan uses one or more of these gates before
committing and before merging. The gate tier is declared in each commit's
"Test gate" annotation.

### Unit only (no gate label)

Pure Python, no LLM, no GPU. Run freely without user approval.

- `pytest tests/unit/...`
- ruff check + ruff format --check
- pyright

### Gate 1 — Real LLM + pseudo training

**Purpose**: verify that a real LLM, given the new/changed prompts, produces
structurally valid output (compiles, passes schema validation, passes
dummy-tensor check). Does NOT require real training.

**When to use**: after any commit that changes an LLM-facing system prompt or
schema (implementor, proposer, validator, interpreter).

**Setup**:
- Real LLM: `llm_configs/openai_tiered_v1.json` (gpt-5.4 for
  proposer/implementor/interpreter; gpt-5.4-mini for validator)
- Pseudo training: dummy-tensor check only — no GPU, no real training loop
- Estimated wall time: ~2-5 min
- Estimated cost: ~$0.05-0.20

**Pass criteria**:
- LLM call completes without error
- Output passes Pydantic schema validation
- Generated code (if implementor) compiles + passes dummy-tensor check

**Needs user approval**: yes (real LLM cost).

---

### Gate 2 — Real LLM + real training (smoke test)

**Purpose**: verify end-to-end plumbing with production LLMs and real
training. Binary signal: does the chain complete with a non-null finite
`denoising_score`?

**When to use**: at Checkpoint commits (end of a feature's commit plan)
before merging to master.

**Canonical command**:
```bash
bash sdsc_submission_scripts/run_chain.sh \
    --mode lilab \
    --workspace /tmp/checkpoint_$(date +%s) \
    --run_name checkpoint_smoke \
    --num_iterations 2 \
    --max_rounds 2 \
    --max_proposal_attempts 3 \
    --max_epochs 1 \
    --trial_portion 0.02 \
    --train_portion 0.02 \
    --eval_portion 0.02 \
    --trial_time_budget_minutes 5 \
    --no-force_formal_round \
    --formal_time_budget_minutes 30 \
    --llm_config llm_configs/openai_tiered_v1.json \
    --seed_paths \
        /home/klz/Data/SIDEREIS_DATA/wavenet/small_sample_trial_v0/agent/run_output_small_sample_trial_v0_agent.json \
        /home/klz/Data/SIDEREIS_DATA/punet/small_sample_trial_v0/agent/run_output_small_sample_trial_v0_agent.json
```

**Important**: do NOT use `tee` to capture chain stdout. The Claude Code
harness capture file is sufficient and can be read on demand. `tee` writes
a duplicate log to `/tmp` that accumulates over the run and can exhaust
the tmpfs filesystem.

**Critical parameter constraints** (lesson learned from Checkpoint T, 2026-06-18):

| Parameter | Value | Why |
|---|---|---|
| `--trial_time_budget_minutes 5` | **mandatory** | Engages the time-risk gate. Without it, training runs without a time ceiling and Gate 2 can take 60-90+ min and fill disk. Validated to work in prior Checkpoint S runs. |
| `--no-force_formal_round` | **mandatory** | Disables the default behavior of forcing the last round to be a full formal training run. Without this flag, the last round uses the full dataset regardless of `--trial_portion`, causing 2+ hour runtimes (observed in Gate 3 iter_002 round 2: 2h 02m on 2026-06-22). All rounds should stay in trial mode for smoke tests. |
| `--formal_time_budget_minutes 30` | safety net | Safety net in case `--no-force_formal_round` is accidentally omitted or a future config silently re-enables formal forcing. Only active when a formal round actually runs. |
| `--trial_portion 0.02` | **mandatory** | Keeps each training epoch under 5 min on lilab GPU (~20K segments). At 0.05 a single attempt can generate 76 GB of intermediate files. |
| `--llm_config openai_tiered_v1.json` | **mandatory** | gpt-4o-mini (`certify_minimal.json`) cannot reliably generate proposals that pass the validator — Gate 2 run will complete but produce no `denoising_score`. |
| `--num_iterations 2` | recommended | Two iterations exercise the full chain including the interpretation→propose→implement loop. One iteration is acceptable for simpler features. |
| `--max_rounds 2` | recommended | Two rounds exercise the tuner planner's multi-round reasoning. |
| `--max_proposal_attempts 3` | recommended | Gives the implementor two self-correction chances. |

**Estimated wall time**: ~30-60 min (all rounds in trial mode with
`--no-force_formal_round`). Per-iter breakdown: ~15 min LLM setup
(interp + 3-stage proposer + implementor + validator) + 2 × ~8 min trial
rounds (5 min training cap + overhead) = ~30 min per iter × 2 iters.
Variance comes from gpt-5.4 latency spikes and any proposal/implementor
repair attempts.

**Estimated cost**: ~$1.50-2.50 (gpt-5.4 dominant role).

**Pass criteria — HealthGate framework correctness**

These criteria test the HealthGate infrastructure only, not model denoising quality.

1. Chain exits 0
2. Every round has a recorded `gate_action` in `final_record`
   (any value: PASS, INVALIDATE_ROUND, ABORT_CHAIN)
3. Every `denoising_score` is either:
   a. A finite positive number, OR
   b. `None` / `-inf` WITH a corresponding `gate_action` of
      `INVALIDATE_ROUND` or `ABORT_CHAIN` in that round's record
   (A `None` score with no `gate_action` recorded is a framework bug)
4. No phantom `5.5762667` appears as a final accepted score
   (phantom scores caught and invalidated by HealthGate are acceptable)
5. At least one round triggers a HealthGate evaluation
   (confirms gate firing logic is reachable)

The following are explicitly NOT pass/fail criteria for Gate 2:
- Whether denoising_score > baseline
- Whether the model learned to denoise
- Whether score is above any threshold

**Needs user approval**: yes (real LLM + real training cost and time).

---

### Gate 2 parameter plans (Lite / Regular)

Added 2026-07-23 from the runtime-control Gate 2 audit (design doc
§12, commit `cb1b6b0`). Two vetted combinations. Guiding policy:
**be generous on GPU VRAM, stingy on wall time** — a VRAM-gate
rejection wastes a whole Gate attempt, while time is controlled by
portions and budgets.

**Portion semantics crib (code-traced — do not infer from names):**

- Training scope: per file `max(1, round(formal_portion × 200))` PSD;
  per-epoch subsample `max(1, round(formal_train_portion × scope))`;
  steps = `(ΣPSD × (10M//seg)) // batch × epochs`.
- **Eval scope is INDEPENDENT of `formal_portion`**: per file
  `max(1, round(formal_eval_portion × 200))` PSD — drives inference
  AND scoring. The naive `formal_portion × formal_eval_portion`
  intuition is wrong.
- Per-file floors of 1 PSD mean many-file scopes never go below
  1 PSD/file regardless of portion.
- Scoring = eval PSD × per-host `per_psd_segment_seconds` ÷ 8 workers
  — ≤ ~6% of total even at `formal_eval_portion=1.0` on a 6-file
  scope, so it stays a historical-estimate phase under the 0.10
  share limit.

| Parameter | **Lite Plan** (~30-45 min, ~$1) | **Regular Plan** (~45-90 min, ~$1.5-2.5) |
|---|---|---|
| Purpose | fastest full-lifecycle proof incl. ONE forced formal round | tighter runtime-prediction statistics + multi-iteration LLM loop |
| `--num_iterations` / `--start_iteration` | 1 | 2 |
| `--max_rounds` | 2 (1 trial + 1 forced formal) | 2 |
| `--max_proposal_attempts` | 3 | 3 |
| `--data_scope` | `4-9` (6 files) | `4-9` |
| `--trial_portion / --train_portion / --eval_portion` | 0.02 / 1.0 / 0.01 | 0.02 / 1.0 / 0.01 |
| `--formal_portion / --formal_train_portion / --formal_eval_portion` | 0.02 / 1.0 / 0.01 (→ 3,000 steps @ seg 10k b8; 12 eval PSD) | 0.10 / 1.0 / 0.05 (→ 15,000 steps; 60 eval PSD) |
| `--max_epochs` | 1 | 1 |
| `--trial_time_budget_minutes` | 5 | 5 |
| `--formal_time_budget_minutes` | 30 (Gate-specific; production policy stays 120) | 45 |
| `--trial_vram_budget_gb / --formal_vram_budget_gb` | 24 / 24 (GENEROUS — never let the VRAM gate eat a Gate attempt) | 24 / 24 |
| `--runtime_watchdog` | on (passive validation) | on |
| Guardrails | defaults (150k / batch≥4) | defaults |
| force_formal_round | **default ON** (deviation from the trial-only smoke — required when the feature under test must exercise real formal admission; use `--no-force_formal_round` for features that don't) | default ON |
| `--llm_config` | `openai_tiered_v1.json` | `openai_tiered_v1.json` |

Notes:

- The trial-only smoke (canonical command above) remains correct for
  features that don't touch the formal path; the plans here add the
  formal-round variant with SMALL formal portions instead of the
  dangerous full-dataset formal that motivated
  `--no-force_formal_round`.
- Estimated single-formal-round compute at Lite scale: setup ~20 s +
  training 1-5 min (unknown LLM-invented model, 25-100 ms/step band)
  + inference ~10-25 s + scoring ~3 s + ~50 s subprocess startups.
- Pathological/rejection demonstrations should NOT run the workload:
  drive the executor directly (e.g.
  `scripts/pregate_runtime_control_validation.py`-style, no LLM) with
  guardrails overridden and the production budget — rejection arrives
  in ~2 min (setup + live verification only).

**Failure handling**:
- If all proposals fail validation → LLM quality issue, not a feature bug.
  Check that `--llm_config openai_tiered_v1.json` is set (not certify_minimal).
- If SIGSEGV / OOM during inference → retry once; if repeats, investigate
  VRAM budget. Check `--trial_vram_budget_gb` setting.
- If disk fills → `--trial_portion 0.02` + `--trial_time_budget_minutes 5`
  must both be set. Check `/tmp` usage with `du -sh /tmp/*`.

---

## Gate assignment by commit type

| Commit type | Typical gate |
|---|---|
| Config files, YAML, schema-only | Unit only |
| New loader/renderer (pure Python) | Unit only |
| Prompt placeholder substitution | Unit only + optional Gate 1 |
| New LLM-facing system prompt | Gate 1 |
| New agent node or workflow wiring | Gate 1 |
| Checkpoint (end of feature) | Gate 2 |
| Loss function generation (L4) | Gate 1 (dummy-tensor) + Gate 2 at Checkpoint L |

---

## Seed paths (canonical)

```
/home/klz/Data/SIDEREIS_DATA/wavenet/small_sample_trial_v0/agent/run_output_small_sample_trial_v0_agent.json
/home/klz/Data/SIDEREIS_DATA/punet/small_sample_trial_v0/agent/run_output_small_sample_trial_v0_agent.json
```

These are the baseline seed files used for all smoke tests.
