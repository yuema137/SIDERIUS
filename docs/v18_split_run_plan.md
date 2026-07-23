# V18 Split-Mode Run Plan (DataScope groups)

**Status**: Plan approved in session 2026-07-23 (operator: run split-mode
V18; wave 1 = groups 4-9 + 10-14 only, wave 2 after wave 1 completes;
everything else identical to V17).
**Depends on**: `feat/enable-partial-file-list` (DS1–DS8), Checkpoint DS
Gates 1–2.
**Reference**: V17 launch template in `reports/v17_20260717.md` §13;
scope semantics in `docs/design/enable_partial_file_list.md`.

## Topology

Four DataScope groups × two explorer flavors = 8 chains total, run in two
waves of 4 (host cannot sustain 8 concurrent chains — CPU dataloader
bound):

| Wave | Group | Scope | `--health_gate_files` (low/mid/high in scope) | Runs |
|---|---|---|---|---|
| 1 | G0409 | `4-9` | `4,7,9` | loss + arch |
| 1 | G1014 | `10-14` | `10,12,14` | loss + arch |
| 2 (after wave 1) | G0003 | `0-3` | `0,2,3` | loss + arch |
| 2 (after wave 1) | G1519 | `15-19` | `15,17,19` | loss + arch |

Wave 2 starts only after ALL four wave-1 chains have written their final
iteration manifests (exit markers), matching the operator's resource
constraint.

## What changes vs V17 (ONLY the partial-file-list dimension)

1. **`--data_scope <group>` + `--health_gate_files <triplet>`** per run.
   The monitored triplet is MANDATORY under a partial scope (startup
   error without it — the YAML default `[3,10,17]` is out of scope for
   every group).
2. **No `--seed_paths` — all 8 chains are seedless cold starts.** The V17
   pregate seeds are full-scope records; DS6b ingress validation will
   (correctly) refuse them under any partial scope. PR #126 makes
   seedless the supported path. Optional later: scoped Phase-1 baselines
   per group via `run_comparison.py --data_scope`, but that adds GPU time
   and is NOT part of this plan.
3. **Drop `--trial_strategy snapshot`** from the V17 command — DS7 made
   it a deprecated warn-and-ignore no-op (strategy is snapshot-forced
   under a partial scope anyway).
4. **One fresh workspace per chain, 8 total** — the run-invariants lock
   makes scope + gate policy workspace-immutable; never point two groups
   at one workspace. `--auto_resume` still works per workspace (the lock
   is validated, not recreated, on resume).

## What stays identical to V17 (verified against the V17 command)

- `--num_iterations 20 --auto_resume --max_rounds 3 --max_epochs 1`
- Delta gates: `--skip_formal_min_delta 0.0
  --bypass_formal_time_budget_min_delta 0.5` (V17 fixed 0.0 reference is
  scope-neutral; each chain's incumbent lives inside one scope, so
  comparability holds within-chain)
- Budgets: `--trial_time_budget_minutes 12
  --formal_time_budget_minutes 120 --trial_vram_budget_gb 10
  --formal_vram_budget_gb 12`. VRAM check for 4 concurrent chains on the
  H100: worst case 4 × 12 GB = 48 GB < 63 GB usable cap. (Formal rounds
  are CHEAPER than V17's: snapshot over 4–6 files instead of 20.)
- `--formal_strategy snapshot --formal_round_strategy inherit_best_trial`
- `--exploration_mode explore --ml_lit_review_enabled`
- `--llm_config llm_configs/openai_tiered_v1.json`
- `--health_checks_config configs/health_checks_baseline_observe_mode.yaml`
  (UNCHANGED on disk — the run-level `health_gate_files` override is
  applied at materialization into each workspace's
  `health_checks_effective.yaml`; the shipped YAML is never edited)
- Advice files `advice/workflow/v17_{loss,arch}_explorer.json` — audited
  scope-neutral (no file-index or 20-files phrasing; "snapshot
  comparability" language is compatible). Reused verbatim.

## Config-audit conclusion

**Zero repo config edits required.** All scoping enters via CLI flags;
the effective HealthGate config and the run-invariants lock are
materialized per workspace. `configs/task_config.yaml`, both HealthGate
YAMLs, `llm_configs/*`, and the advice files stay untouched.

Known shared surface (same as V17's 2-chain concurrency, now ×4): the
global `agent_generated/` loss/model promotion directories are shared
across concurrent chains by design (issue #92 early-promotion is
idempotent/atomic). No action; noted for awareness.

**Analysis caveat**: aggregate scalars are comparable only WITHIN a
group (scope-homogeneity). Cross-group comparison uses per-file vectors
(anchor-normalized per segment, globally comparable) — never the
scalars. The V18 chain-wide incumbent design must be scope-keyed
(`docs/design/v18_priorities.md` §3.4).

## Wave-1 launch commands (template; `${DATE}=$(date +%Y%m%d_%H%M)`)

Substitute `FLAVOR∈{loss,arch}` / `GROUP∈{0409→"4-9"/"4,7,9",
1014→"10-14"/"10,12,14"}`; one screen session + log + exit marker per
chain, exactly like the V17 §13 wrapper:

```bash
bash sdsc_submission_scripts/run_chain.sh \
  --mode lilab \
  --workspace /workspace/DATA/SIDERIUS_DATA/v18_${FLAVOR}_g${GROUP}_${DATE} \
  --run_name v18_${FLAVOR}_g${GROUP}_${DATE} \
  --num_iterations 20 \
  --auto_resume \
  --max_rounds 3 \
  --max_epochs 1 \
  --data_scope <group-scope> \
  --health_gate_files <group-triplet> \
  --skip_formal_min_delta 0.0 \
  --bypass_formal_time_budget_min_delta 0.5 \
  --trial_time_budget_minutes 12 \
  --formal_time_budget_minutes 120 \
  --trial_vram_budget_gb 10 \
  --formal_vram_budget_gb 12 \
  --formal_strategy snapshot \
  --formal_round_strategy inherit_best_trial \
  --exploration_mode explore \
  --ml_lit_review_enabled \
  --llm_config llm_configs/openai_tiered_v1.json \
  --advice advice/workflow/v17_${FLAVOR}_explorer.json \
  --health_checks_config configs/health_checks_baseline_observe_mode.yaml
```

Wave 2 = the same four commands with `0-3`/`0,2,3` and `15-19`/`15,17,19`,
launched only after all wave-1 exit markers exist.

## Preconditions before wave 1

1. Checkpoint DS Gates 1 (PASS 2026-07-23) and 2 (in progress) recorded.
2. Branch merged (or wave 1 explicitly run from the feature branch —
   operator call).
3. Dry-run each of the 4 wave-1 commands (`--dry-run`) and confirm the
   `[DATASCOPE]`/`Data scope` banner shows the intended group + triplet.
