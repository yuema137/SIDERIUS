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
| `--trial_portion 0.02` | **mandatory** | Keeps each training epoch under 5 min on lilab GPU (~20K segments). At 0.05 a single attempt can generate 76 GB of intermediate files. |
| `--llm_config openai_tiered_v1.json` | **mandatory** | gpt-4o-mini (`certify_minimal.json`) cannot reliably generate proposals that pass the validator — Gate 2 run will complete but produce no `denoising_score`. |
| `--num_iterations 2` | recommended | Two iterations exercise the full chain including the interpretation→propose→implement loop. One iteration is acceptable for simpler features. |
| `--max_rounds 2` | recommended | Two rounds exercise the tuner planner's multi-round reasoning. |
| `--max_proposal_attempts 3` | recommended | Gives the implementor two self-correction chances. |

**Estimated wall time**: ~30-60 min (dominated by training; time-risk gate
keeps individual training runs under 5 min, but 2 iters × 2 rounds × up to
3 attempts = up to 12 training runs).

**Estimated cost**: ~$1.50-2.50 (gpt-5.4 dominant role).

**Pass criteria**:
1. Chain exits 0
2. `run_output_*.json` written for each iteration with non-null finite `denoising_score`
3. Feature-specific injection verified (e.g. `task_config_snapshot.yaml` present,
   SQUID text in interpretation output, etc.)

**Needs user approval**: yes (real LLM + real training cost and time).

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
