# Entrypoints and CLI

**Audience**: operators and anyone trying to find the right command.
**Authority**: `sdsc_submission_scripts/run_chain.sh`,
`sdsc_submission_scripts/_chain_common.sh`,
`sdsc_submission_scripts/run_one_iteration.py`,
`workflows/model_exploration.py`, `scripts/run_comparison.py`.

For exhaustive flag lists, run each entrypoint with `--help`. This page covers
the flags that decide *what a run is*.

---

## Which entrypoint

| you want to | use |
|---|---|
| run the full multi-iteration agent loop | `sdsc_submission_scripts/run_chain.sh` |
| launch the official Gold campaign (stage 1 search / stage 2 strict retrain) | `sdsc_submission_scripts/run_gold_campaign.sh` (binds the frozen campaign values and delegates to `run_chain.sh`; see `sdsc_submission_scripts/README.md` "Gold campaign" and `docs/campaign/stage_artifact_contract.md`) |
| run one arm of the prior-art baseline experiment (arXiv X9) | `sdsc_submission_scripts/launch_prior_baseline_experiment.sh` |
| run exactly one iteration (or debug one) | `sdsc_submission_scripts/run_one_iteration.py` |
| drive the workflow directly from Python | `workflows/model_exploration.py` |
| compare a built-in TIDMAD model against baselines | `scripts/run_comparison.py` |

> Note the directory: the chain launchers live in `sdsc_submission_scripts/`,
> **not** in `scripts/`. Several older documents said otherwise.

## `run_chain.sh` — the chain launcher

The primary user-facing entrypoint. Owns Python resolution, auto-resume, and
dispatch to either a foreground subprocess or a Slurm dependency chain.

```bash
bash sdsc_submission_scripts/run_chain.sh \
    --mode lilab \
    --workspace /path/to/workspace \
    --run_name my_run_v1 \
    --num_iterations 5 \
    --task_composition configs/task_composition/tidmad.yaml \
    --data_dir /path/to/data \
    --max_rounds 5
```

| flag | meaning |
|---|---|
| `--mode {lilab,sdsc}` | **the only flag the launcher validates as required.** `lilab` = foreground subprocess; `sdsc` = `sbatch` + `afterany` chain |
| `--workspace DIR` | chain workspace root — required in practice |
| `--run_name NAME` | pins the immutable run id — required in practice |
| `--task_composition FILE` | the task manifest. **Omitted = the legacy un-composed run** with byte-identical child argv |
| `--data_dir DIR` | physical data root. **Required for any composed run**; a composed run without it fails closed before any LLM or GPU work |
| `--num_iterations N` | default `2` |
| `--seed_paths P [P…]` | prior run outputs to seed from. **Optional** — an empty list is a valid cold start |
| `--auto_resume` / `--no_auto_resume` | default **ON**: pick up where a partial chain stopped |
| `--start_iter N` | manual override of auto-resume |
| `--dry-run` | walk the chain, print exact commands, no side effects |
| `--experiment_arm LABEL` | opaque experiment-arm label (arXiv U1). Pinned into `run_invariants_lock.json` and stamped on every record, tuner output and manifest; forwarded only when set. **Omitted = unlabelled**, byte-identical argv. Drives no behaviour |
| `--ml_lit_review_enabled` / `--no-ml_lit_review_enabled` | the literature-review node's presence in the workflow topology. Both the resolved flag and, when ON, the sha256 of the resolved lit-review YAML are pinned in the lock |

Everything else is pass-through to the iteration: `--data_scope`,
`--health_gate_enabled` / `--no-health_gate_enabled`, `--health_gate_files`,
`--health_checks_config`, `--healthgate_mode`, `--max_rounds`, and the trial /
formal time and VRAM budgets.

> The header comment inside `run_chain.sh` lists `--seed_paths` under "Required
> flags". That comment is stale — `_chain_common.sh:403-406` documents the
> opposite and omits the flag entirely for a cold start. Cold start is in fact
> the required posture for gate runs.

## `run_one_iteration.py` — one iteration

This is where composition is actually entered. Useful for debugging a single
iteration without chain machinery.

Two flags have **no defaults and are required for a formal launch** — the run
exits `2` without them:

| flag | choices |
|---|---|
| `--healthgate_mode` | `blocking` \| `observe_only` |
| `--result_authority` | `scientific` \| `diagnostic` |

Other flags that define a run:

| flag | default |
|---|---|
| `--task_composition` | `None` (legacy un-composed) |
| `--data_dir` | `None` |
| `--data_scope` | `None` (full scope) |
| `--health_gate_enabled` / `--no-health_gate_enabled` | enabled |
| `--health_gate_files` | `None` |
| `--health_checks_config` | `None` (framework default) |
| `--max_rounds` | `3` |
| `--max_proposal_attempts` | `3` |
| `--llm_config` | `None` |
| `--experiment_arm` | `None` (unlabelled; an empty string is refused). Opaque label pinned in the lock and stamped on records / outputs / manifests (arXiv U1) |
| `--ml_lit_review_enabled` / `--no-ml_lit_review_enabled` | `None` → the YAML's `enabled` decides (shipped: `false`). The resolved flag and the config's sha256 are pinned in the lock; an enabled but unreadable config refuses the launch |
| `--baseline_isolation` | off. Excludes the bundled baselines from the LLM-facing surface: bundled descriptions refused, prompt examples neutralised, built-in proposals refused by name (arXiv U3). Pinned in the lock |
| `--print_resolved_launch_config` | off. Print the resolved launch configuration (arm, lit-review topology + config sha256, isolation, composition, workspace, advice file, declared posture) as ONE JSON object and exit 0 with no side effects |

### `launch_prior_baseline_experiment.sh` — the two-arm experiment

One launcher, two arms, one argument changed:

```bash
bash sdsc_submission_scripts/launch_prior_baseline_experiment.sh \
    --arm with-prior-art|without-prior-art \
    --workspace DIR [--run_name NAME] [--mode lilab|sdsc] \
    [--dry-run] [--h100] [passthrough run_chain.sh flags...]
```

| arm | explicit child argv |
|---|---|
| `with-prior-art` | `--ml_lit_review_enabled --experiment_arm with-prior-art` |
| `without-prior-art` | `--no-ml_lit_review_enabled --experiment_arm without-prior-art --baseline_isolation` |

It wraps `run_chain.sh` (never the tuner node CLI); refuses `--seed_paths`
(cold-start rule), advice files (a second variable in either arm) and every
arm-decided flag; `--dry-run` prints the exact child argv AND the resolved
launch configuration; `--h100` sources `h100_posture.env` (must define the
`H100_CHAIN_ARGS` array, splatted after the launcher's own args) and refuses
loudly by name when the file is missing.

## `workflows/model_exploration.py` — the module CLI

The workflow itself, runnable directly. Accepts `--task_composition`,
`--run_name`, `--max_iterations` (default `1`), `--max_rounds` (default `10`),
`--max_proposal_attempts` (default `3`), `--target_score`, LLM routing flags and
advice flags.

## `scripts/run_comparison.py` — baseline comparison

⚠ **TIDMAD-only by construction.** It imports TIDMAD's dataset, file count,
sandbox and data directory directly, and it does **not** accept
`--task_composition`. It is a useful baseline harness for TIDMAD and is not a
general task runner.

```bash
python scripts/run_comparison.py --model punet --is_trial
```

Key flags: `--model` (required, single-valued), `--is_trial`, `--max_rounds`
(default `50`), `--provider` / `--model_id` and the `--reflect_*` split,
`--data_scope`, `--health_checks_config`.

## `scripts/stage3/stage3_composed_best.py` — Stage-3 Composed Best (Gold campaign)

Pools the four Stage-1 band winners' SOURCE-BAND deliverables and scores the
composed 20-file set **exactly once** through the shared
`scripts/stage3/stage3_common.compose_and_score` wrapper
(`docs/campaign/stage_artifact_contract.md` §1/§3/§4). Emits one authoritative
`denoising_score` plus an identity-only provenance JSON under
`{workspace_root}/stage3/composed_best/{arm}/`. Read-only against Stage-1
workspaces (the pooled input is a symlink farm in the stage3 namespace).

```bash
.venv/bin/python -m scripts.stage3.stage3_composed_best \
    --workspace_root /path/to/campaign_root --arm gold
```

Flags (both required, no defaults): `--workspace_root` (the campaign's
persistent root; band workspaces are `{workspace_root}/{arm}_band{BAND}`),
`--arm` (opaque arm label; must match each workspace's invariants lock).

Refusals (exit 2, message on stderr): missing/scope-mismatched/unverifiable
workspaces, anomalous `is_trial` shapes, missing `metric_spec` stamps, missing
winner deliverables (retention clause), and every `compose_and_score` refusal
(missing/duplicate pooled file indices, swapped anchor artifact). **No
per-band scalar appears in any output, log, or provenance field** — per-band
information is expressed only as per-file vector entries (F-SCAND-1; pinned by
an SRI-11 census test).

`stage3_common.compose_and_score(deliverable_dirs, *, files=range(20),
sample_set=None, reconciled_spec)` is the contract's §4 interface (as
amended by the supervisor's local-gate Step-09a ruling, 2026-08-26): all
three Stage-3 writers call it, none re-inlines `score_vector`, a partial
`files` range or non-`None` `sample_set` is refused, and `reconciled_spec`
is the caller's RECONCILED 09a `MetricSpec` stamp — required identity
transport for refusal envelopes; the composer derives nothing.

## `scripts/stage3/stage3_strict_best.py` — Stage-3 Strict Best (Gold campaign)

Fail-closed finalization over the Stage-2 retrain matrix: verifies all 16
units (`{workspace_root}/stage2/{design}_{band}/` with an atomic
`COMPLETE.json`, `healthgate_valid: true`, strict §2 schema), pools each
design's four band `deliverables/` dirs, obtains StrictScore(design) from
**one** `compose_and_score` call at full 0..19 scope, and selects the best
under `MetricOrder` (direction from the RECONCILED 09a `metric_spec`
stamps persisted in the 16 units' chain workspaces, read through the
manifest-verified loader and reconciled by the ONE authority — this module
derives nothing and contains no `max`/`min`/`sorted`; AST-censused). ANY
missing/malformed/invalid unit refuses the WHOLE finalization (one
aggregated refusal naming every failing unit, zero composer calls, no
selection, exit 2 — Q-S3-1 ruling A). The marker's own `denoising_score` is
validated and never echoed.

```bash
.venv/bin/python -m scripts.stage3.stage3_strict_best \
    --workspace_root /path/to/campaign_root \
    --designs wavenetA,punetB,gatedfnoC,rnnD
```

Flags: `--workspace_root` (required), `--designs` (required; comma-separated
ids of exactly 4 distinct frozen winner designs), `--out` (default
`{workspace_root}/stage3/strict_best/strict_best_selection.json`, written by
atomic rename, stamped `selection_rule =
strict_best.fail_closed.one_composed_score_per_design.v1`).

## `scripts/stage3/stage3_terminal_eval.py` — Stage-3 terminal re-evaluation (Gold campaign)

The ONE terminal full-scope (100%) measurement of the selected champion,
taken AFTER search freezes; the terminal number never feeds back into
search. Everything it writes lives under the isolation namespace
`{workspace_root}/stage3/terminal_eval/` (contract §3): output paths are
validated against the namespace at construction, a champion without
HealthGate-valid provenance is refused by name through `is_valid_candidate`,
scoring goes through the shared `compose_and_score` exactly once, and the
write path refuses band-shaped scalar fields. The module also ships the
read-closure guard (`audit_terminal_read_closure` /
`assert_terminal_read_closure`) proving no search-side consumer's input
roots reach the namespace — including planted-artifact detection via the
self-declared `artifact_namespace` marker.

```bash
.venv/bin/python -m scripts.stage3.stage3_terminal_eval \
    --champion_json /path/to/champion.json \
    --workspace_root /path/to/campaign_root
```

Flags (both required): `--champion_json` (a JSON file with the
`TerminalChampion` shape — identity + `deliverable_dirs` +
`provenance_records` + `metric_spec`, the champion's reconciled 09a stamp,
required since the Step-09a gate ruling; a spec-less champion is a pre-09a
shape and refuses at validation), `--workspace_root`. Refusals exit
non-zero with the named reason on stderr — a refusal must never look like
a successful terminal measurement.

## Data scope

`--data_scope` restricts everything a run touches — training, inference, scoring
and health peeks — to a subset of partitions. It is enforced constructively at
the sample-set builder and again at the sandbox I/O boundary, **never by prompts**.

```bash
--data_scope 4-9                 # or 4,5,6,7,8,9  or 0-3,7
--health_gate_files 4,7,9        # must be a subset of the scope
```

Under a partial scope, health-gate files must be declared explicitly and be
in-scope. Aggregate scores are **only comparable within one scope** — the
resolved scope is pinned by the workspace's invariants lock, and resuming with a
different one fails at startup.

> `--data_scope` is a partition-index concept from TIDMAD's topology. For a
> composed non-TIDMAD task it is refused by name; such a task expresses coverage
> through its own `TaskScopeCapability`.

## Which entrypoints accept `--task_composition`

| entrypoint | accepts it |
|---|:---:|
| `run_chain.sh` | ✅ (forwards) |
| `run_one_iteration.py` | ✅ |
| `workflows/model_exploration.py` | ✅ |
| `scripts/run_comparison.py` | ❌ |

---

## Next

- [Operating a run](../guides/operating-a-run.md) — resume, budgets, failure modes
- [Task composition reference](task-composition.md)
- [Configuration map](configuration-map.md)
