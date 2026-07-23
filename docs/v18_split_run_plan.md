# V18 Split-Mode Run Plan (DataScope groups) — rev 2

**Status**: Plan approved + refined by operator 2026-07-23 (rev 2:
all-in-scope HealthGate monitoring, scope-bearing run names, explicit
Wave 1 checkpoint with automatic summary + manual approval).
**Depends on**: `feat/enable-partial-file-list` (DS1–DS8), Checkpoint DS
Gates 1–2.
**Reference**: V17 launch template in `reports/v17_20260717.md` §13;
scope semantics in `docs/design/enable_partial_file_list.md`.

## Topology

Four DataScope groups × two explorer flavors = 8 chains, in two waves of
4 (the host cannot sustain 8 concurrent chains — CPU dataloader bound):

| Wave | Run name | Scope | `--health_gate_files` (ALL in-scope files) |
|---|---|---|---|
| 1 | `v18_loss_04_09` / `v18_arch_04_09` | `4-9` | `4,5,6,7,8,9` |
| 1 | `v18_loss_10_14` / `v18_arch_10_14` | `10-14` | `10,11,12,13,14` |
| 2 | `v18_loss_00_03` / `v18_arch_00_03` | `0-3` | `0,1,2,3` |
| 2 | `v18_loss_15_19` / `v18_arch_15_19` | `15-19` | `15,16,17,18,19` |

**HealthGate policy (rev 2)**: monitor **every file inside the scope** —
no representative-triplet selection, no ambiguity about what was
monitored. Verified architecturally clean: `apply_monitored_files` +
`validate_health_scope` + `materialize_effective_config` all accept the
full in-scope list (scope ⊆ scope trivially), and snapshot-only sampling
under a partial scope guarantees every monitored file has a denoised
output each round. Extra peek cost is a few small reads per round.

**Run naming (rev 2)**: `v18_{flavor}_{zero-padded scope}` is BOTH the
`--run_name` and the workspace basename, so the scope is visible in the
workspace path, `run_config_*.json`, iteration manifests, campaign
names, tuner summaries, dashboards, and the wave summary — everywhere
identity propagates from those two inputs.

## Wave 1 checkpoint (rev 2 — explicit gate before Wave 2)

```
Wave 1 (4 chains) → automatic summary → manual review → operator approval → Wave 2
```

After all four Wave-1 chains have exited, generate the review packet:

```bash
.venv/bin/python scripts/v18_wave_summary.py \
    /workspace/DATA/SIDERIUS_DATA/v18_loss_04_09 \
    /workspace/DATA/SIDERIUS_DATA/v18_arch_04_09 \
    /workspace/DATA/SIDERIUS_DATA/v18_loss_10_14 \
    /workspace/DATA/SIDERIUS_DATA/v18_arch_10_14
```

Per chain it reports: best raw + HealthGate-valid scores, best proposal,
completed/no_records/failed iteration counts, total completed rounds,
record-status statistics (success / collapse / error-skip), gate-action
distribution, the workspace's locked scope, and ABNORMAL flags (failed
manifests, manifest-vs-lock scope disagreements, missing lock/iters).
Wave 2 launches **only** after the operator reviews this packet and
approves. (Script is read-only and safe to run against live chains for
interim peeks.)

## What changes vs V17 (only the partial-file-list dimension)

1. `--data_scope <group>` + `--health_gate_files <all in-scope files>`
   per run (explicit monitored list is mandatory under a partial scope —
   the YAML default `[3,10,17]` is out of scope for every group).
2. **No `--seed_paths`** — all 8 chains are seedless cold starts (PR
   #126). Full-scope V17 seeds are, correctly, rejected by DS6b ingress
   validation; that rejection is the designed behavior, not a workaround.
3. Drop `--trial_strategy snapshot` (DS7 deprecated no-op).
4. One fresh workspace per chain, named after the run (8 total) — the
   run-invariants lock makes scope + gate policy workspace-immutable;
   `--auto_resume` validates (never recreates) the lock.

## What stays identical to V17 (verified against the V17 §13 command)

`--num_iterations 20 --auto_resume --max_rounds 3 --max_epochs 1`,
delta gates `0.0`/`0.5`, budgets `12`/`120` min and `10`/`12` GB VRAM
(4 concurrent × 12 GB = 48 GB < 63 GB H100 usable cap; partial-scope
formal rounds are cheaper than V17's — 4–6 files instead of 20),
`--formal_strategy snapshot --formal_round_strategy inherit_best_trial`,
`--exploration_mode explore --ml_lit_review_enabled`,
`--llm_config llm_configs/openai_tiered_v1.json`,
`--health_checks_config configs/health_checks_baseline_observe_mode.yaml`
(unchanged on disk — the run-level override is materialized per
workspace), and the V17 advice files reused verbatim (audited
scope-neutral).

## Configuration audit (rev 2 — full-dataset assumptions in reporting)

**Zero repo config edits required**, and the reporting/visualization
stack is scope-aware:

- `score_vector` always returns a **length-`NUM_FILES` vector padded
  with `None`** at unscored indices — partial scopes produce exactly the
  sparse shape the stack already handles.
- `ScoreComparisonTable` keeps its fixed 20-row frame by design
  (`scoring_helpers._build_rows`): out-of-scope rows carry
  `model=None` and their gain/headroom/weight/impact columns collapse to
  `None` — the same machinery that served the pre-DataScope
  `anchors`/`target` sparse-sampling strategies. Sampled-subset stats
  (`Linear_Weight`, `Impact_Score`) operate on `sampled_indices` only.
- `nodes/scoring_reference.py` holds full 20-file reference columns —
  a lookup table, valid for any subset.
- Interpretation helpers and the dashboard (`dashboard/`, `app.js`)
  contain no file-count assumptions (verified by sweep for
  `NUM_FILES` / `range(20)` / "20 files" hardcodes).
- Analysis rule: aggregate scalars are comparable only WITHIN a group;
  cross-group comparison uses per-file vectors (anchor-normalized per
  segment, globally comparable). The V18 chain-wide incumbent must be
  scope-keyed (`docs/design/v18_priorities.md` §3.4).

## Wave-1 launch commands (final; dry-run verified)

One screen session + log + exit marker per chain, per the V17 §13
wrapper pattern. `WS_ROOT=/workspace/DATA/SIDERIUS_DATA`.

```bash
# ---- v18_loss_04_09 ----
bash sdsc_submission_scripts/run_chain.sh \
  --mode lilab \
  --workspace "$WS_ROOT/v18_loss_04_09" \
  --run_name v18_loss_04_09 \
  --num_iterations 20 --auto_resume --max_rounds 3 --max_epochs 1 \
  --data_scope 4-9 --health_gate_files 4,5,6,7,8,9 \
  --skip_formal_min_delta 0.0 --bypass_formal_time_budget_min_delta 0.5 \
  --trial_time_budget_minutes 12 --formal_time_budget_minutes 120 \
  --trial_vram_budget_gb 10 --formal_vram_budget_gb 12 \
  --formal_strategy snapshot --formal_round_strategy inherit_best_trial \
  --exploration_mode explore --ml_lit_review_enabled \
  --llm_config llm_configs/openai_tiered_v1.json \
  --advice advice/workflow/v17_loss_explorer.json \
  --health_checks_config configs/health_checks_baseline_observe_mode.yaml

# ---- v18_arch_04_09: same, with ----
#   --workspace "$WS_ROOT/v18_arch_04_09" --run_name v18_arch_04_09
#   --advice advice/workflow/v17_arch_explorer.json

# ---- v18_loss_10_14: same as loss_04_09, with ----
#   --workspace "$WS_ROOT/v18_loss_10_14" --run_name v18_loss_10_14
#   --data_scope 10-14 --health_gate_files 10,11,12,13,14

# ---- v18_arch_10_14: same, with ----
#   --workspace "$WS_ROOT/v18_arch_10_14" --run_name v18_arch_10_14
#   --data_scope 10-14 --health_gate_files 10,11,12,13,14
#   --advice advice/workflow/v17_arch_explorer.json
```

Wave 2 = the same four shapes with `0-3`/`0,1,2,3` (`v18_*_00_03`) and
`15-19`/`15,16,17,18,19` (`v18_*_15_19`) — launched only after the
Wave-1 checkpoint is approved.

## Preconditions before Wave 1

1. Checkpoint DS Gate 1 (PASS 2026-07-23) and Gate 2 recorded.
2. Branch merged (or Wave 1 explicitly run from the feature branch —
   operator call).
3. Dry-run each Wave-1 command and confirm the banner shows the intended
   scope + full monitored list (done 2026-07-23 for all four).
