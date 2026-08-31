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
| launch the official Gold campaign (stage 1 search / stage 2 strict retrain) | `sdsc_submission_scripts/run_gold_campaign.sh` (binds the frozen campaign values — including `--llm_config llm_configs/openai_tiered_pro.json` on every band and unit, refusing the launch if it cannot be resolved — and delegates to `run_chain.sh`; carries an OPERATOR-SUPPLIED VRAM ceiling via `--gold_trial_vram_budget_gb` / `--gold_formal_vram_budget_gb` — both or neither, no value defaulted, unsupplied is inert but recorded, D-HW-6; see `sdsc_submission_scripts/README.md` "Gold campaign" and `docs/campaign/stage_artifact_contract.md`) |
| run one arm of the prior-art baseline experiment (arXiv X9) | `sdsc_submission_scripts/launch_prior_baseline_experiment.sh` |
| run exactly one iteration (or debug one) | `sdsc_submission_scripts/run_one_iteration.py` |
| drive the workflow directly from Python | `workflows/model_exploration.py` |
| compare a built-in TIDMAD model against baselines | `scripts/run_comparison.py` |
| gate a campaign launch before running any of the above | `sdsc_submission_scripts/campaign_preflight.sh` (see below) |

> Note the directory: the chain launchers live in `sdsc_submission_scripts/`,
> **not** in `scripts/`. Several older documents said otherwise.

## `campaign_preflight.sh` — the launch-blocking gate

One gate, rows `R1`…`R9`, each printing `PASS` / `FAIL` / `SKIP` / `INFO`
with its evidence; any `FAIL` exits non-zero. Full row descriptions live in
the script's own `--help` and in `sdsc_submission_scripts/README.md`. Two
things about its output are worth knowing before you read a report.

**A `SKIP` is not a `PASS`.** Rows bound to the X9 launcher (`R6`, `R7`) or
to the X9 four-way co-residency posture (`R4`) are skipped by name under
`--arm goldpod`. A row that the topology cannot exercise has proven
nothing, and it does not count as a failure either.

**R7 states which layers it actually compared.** The arm-symmetry row
(#255, launch validity is conditioned on it) compares five layers, and not
all of them are meaningful in every situation:

| layer | comparable when |
|---|---|
| resolved-config + child argv | always |
| prompt bytes / arm render (declared treatment wiring) | always |
| prompt bytes / neutral render (machine contamination) | the two surfaces come from two different hosts |
| environment | the two surfaces come from two different hosts |
| machine-local stores | the two surfaces come from two different hosts |

The last three are captured with no arm argument, so on ONE host they agree
by construction. R7 reports them as **`NOT COMPARED`** in that case — a
named absence, never a pass. A *difference* in those layers is still a
violation in every state; only the claim that their agreement proves
something is withheld.

Each arm publishes its surface to
`{workspace-root}/.campaign_arm_surface_{arm}.json`. How much that sibling
file is worth is **derived from the artifact's own recorded host, code
revision and capture time** — the preflight reports only *where it read the
file* (`--sibling-source published|local`, default `local`, so a forgotten
argument yields the weakest claim rather than the strongest). A surface
with no provenance
section (a pre-N-6 `campaign_arm_surface/v1` artifact) is **refused**, not
read. The derived state appears in the row and in the checker report:

| evidence state | meaning | R7 |
|---|---|---|
| `cross_pod_verified` | different hosts, same revision, within the freshness window | all five layers compared |
| `cross_pod_stale` | different hosts, same revision, but the older surface is beyond `--sibling-max-age-hours` (default 24; a future-dated surface counts as stale too) | compared, with a loud staleness caveat |
| `same_host` | both surfaces were captured on this host — including a *published* file this host wrote | three layers `NOT COMPARED` |
| `revision_mismatch` | the two surfaces were rendered by different code revisions | **FAIL** — the prompt bytes compare two renderers, not two machines |
| `unverifiable` | a surface carries no readable host, capture time or revision | three layers `NOT COMPARED` |

A caveat is printed in **every** state, and the unverified states are
louder than the verified one. For genuine cross-pod coverage, run the
preflight on the other arm's pod first so its surface is published, then
re-run here.

## `run_chain.sh` — the chain launcher

The primary user-facing entrypoint. Owns Python resolution, auto-resume, and
dispatch to either a foreground subprocess or a Slurm dependency chain.
It disables Python bytecode writes before its first interpreter invocation so
an external task cannot mutate the SIDERIUS source checkout. Run artifacts,
generated modules, and task-owned extensions remain under the declared
workspace.

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
| `--auto_resume` / `--no_auto_resume` | default **ON**: pick up where a partial chain stopped. The inspector's captured value is VALIDATED (F-SCANB-4): only the exit-0 capture's last line, and only a bare non-negative integer, becomes `START_ITER`; anything else (e.g. plugin-loader stdout chatter with no trailing value line) refuses loudly and names the workaround below — never a silent default |
| `--start_iter N` | manual override of auto-resume (also the refusal's named workaround) |
| `--dry-run` | walk the chain, print exact commands, no side effects |
| `--experiment_arm LABEL` | opaque experiment-arm label (arXiv U1). Pinned into `run_invariants_lock.json` and stamped on every record, tuner output and manifest; forwarded only when set. **Omitted = unlabelled**, byte-identical argv. Drives no behaviour |
| `--ml_lit_review_enabled` / `--no-ml_lit_review_enabled` | the literature-review node's presence in the workflow topology. Both the resolved flag and, when ON, the sha256 of the resolved lit-review YAML are pinned in the lock |
| `--ml_lit_review_config PATH` | forwards a task-owned literature-review YAML through the chain launcher; omit it only when the child default is intended |

Everything else is pass-through to the iteration: `--data_scope`,
`--health_gate_enabled` / `--no-health_gate_enabled`, `--health_gate_files`,
`--health_checks_config`, `--healthgate_mode`, `--max_rounds`, the epoch
ceilings (`--max_epochs`, and the per-role `--trial_max_epochs` /
`--formal_max_epochs` — D-BUD-6, forwarded only when typed), the required
runtime-profile declaration (`--required_runtime_profile_path` /
`--required_runtime_profile` / `--required_runtime_profile_sha256` —
F-PROFILE-WIRE-1, forwarded only when
typed, so an undeclared launch's child argv is byte-identical), and the
trial / formal time and VRAM budgets.

> The header comment inside `run_chain.sh` lists `--seed_paths` under "Required
> flags". That comment is stale — `_chain_common.sh:403-406` documents the
> opposite and omits the flag entirely for a cold start. Cold start is in fact
> the required posture for gate runs.

## `run_one_iteration.py` — one iteration

This is where composition is actually entered. Useful for debugging a single
iteration without chain machinery.

Direct invocation establishes the same no-bytecode policy before importing
framework modules and passes it to child processes. This keeps the framework
checkout read-only without changing workspace artifact ownership.

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
| `--max_epochs` | `1` (mode-agnostic epoch ceiling; must be >= 1) |
| `--trial_max_epochs` / `--formal_max_epochs` | `None` — per-role epoch ceilings (D-BUD-6; frozen campaign posture trial 2 / formal 1). Precedence per round role: per-mode value → `--max_epochs` → no clamp; must be >= 1, refused at parse otherwise |
| `--max_proposal_attempts` | `3` |
| `--llm_config` | `None` — **omitting it does not fail.** Empty forwards nothing (`_chain_common.sh:78`), and the runner then falls back to `WorkflowLLMConfig.uniform("gemini", --llm_model)` whose `--llm_model` default is `gemini-3.1-pro-preview` (`run_one_iteration.py:943`), so every LLM role silently resolves to the deprecated all-Gemini default and the run still exits 0. Pass an explicit routing config on any run whose model matters; the Gold campaign path binds `llm_configs/openai_tiered_pro.json` for you and refuses to launch if it cannot (F-LLM-WIRE-1) |
| `--required_runtime_profile_path` | `None`. The **ABSOLUTE** path of the profile artifact this launch requires. Part of the declaration and never derived — this is the clause that closes `finding_1_invisible_default`: while the artifact was located by the ordinary discovery rule (`$SIDERIUS_CALIBRATION_DIR/runtime_profiles_<gpu_slug>.json`), a binding certified *what was found* but never *that the right file was consulted*, so an overlay was used because the directory happened to hold a file of that name. When declared, resolution reads THIS file and never consults discovery — a missing declared artifact REFUSES even when discovery would have certified successfully. A relative path is refused at declaration, because the consuming subprocess runs with a different working directory (`run_chain.sh` cd's before exec) |
| `--required_runtime_profile` | `None` (undeclared → the legacy ladder: measured overlay > shipped > uncalibrated). Declares the runtime profile this launch REQUIRES, as `<gpu_slug>/<regime>` (e.g. `nvidia_h100_80gb_hbm3/single`), copied from a qualification run's recorded provenance. Must be declared together with `--required_runtime_profile_path` and `--required_runtime_profile_sha256`; any proper subset is refused, because half a binding is NO binding and resolving it as undeclared would leave the requirement silently unenforced. When declared, resolution is FAIL-CLOSED: a discovered device/regime that differs, a missing overlay, a digest mismatch, or a verified overlay lacking the row all REFUSE the launch instead of falling back (F-PROFILE-WIRE-1, mechanism F-H100-WD-1-PRETAG). Combining it with an explicit `--runtime_watchdog`/`--no-runtime_watchdog` also refuses — OPERATOR MODE never consults the profile, so the requirement would be unenforced |
| `--required_runtime_profile_sha256` | `None`. The 64-char lowercase-hex sha256 of the DECLARED artifact's bytes, certified for this run (`sha256sum "${SIDERIUS_CALIBRATION_DIR:-$HOME/.siderius}/runtime_profiles_<gpu_slug>.json"`). Hashed over the exact bytes parsed — a single read, never re-opened — so the profile consumed is provably the one that was qualified. Consumption is observable: `runtime_watchdog_provenance` reads `bound:<path>#sha256=<hex>` exactly when certification ran, and the digest it records is the one OBSERVED from the bytes read — never an echo of the declared value |
| `--experiment_arm` | `None` (unlabelled; an empty string is refused). Opaque label pinned in the lock and stamped on records / outputs / manifests (arXiv U1) |
| `--ml_lit_review_enabled` / `--no-ml_lit_review_enabled` | `None` → the YAML's `enabled` decides (shipped: `false`). The resolved flag and the config's sha256 are pinned in the lock; an enabled but unreadable config refuses the launch |
| `--ml_lit_review_config PATH` | literature-review YAML resolved by the iteration runner; composed tasks should supply their own task-specific framing |
| `--advice` / `--human_advice_file` | `None`. Path to the JSON advice artifact (`--advice` wins when both are given). Recognised top-level keys are exactly `interpret`, `propose`, `implement`, `validate`, `tune`, `mindset`, each a string or a list of lines. The key set is CLOSED: an unrecognised key, a key present but resolving to nothing, a non-text value, or a file with no recognised key at all REFUSES the launch by name (F-SCHED-5) — the digest is pinned as the run's treatment identity whether or not the content ever reaches a prompt, so an artifact that cannot inject must never get that far. Sparse advice stays legal; prefix a key with `_` to declare it deliberately inert. See `advice/README.md` |
| `--advice_sha256` | `None` (undeclared). The launcher's OBSERVED sha256 of the advice artifact's bytes, forwarded as a DECLARATION. The run certifies it against its own single read and then discards it: the lock always pins the digest THIS process observed, never an echo of the declared value. A mismatch REFUSES the launch — which is how an edit to the artifact between two band launches of one campaign is caught, since the bands run in SEPARATE workspaces that no per-workspace lock can ever compare. Undeclared is legal (the observed digest is still pinned) and emits no token, so a non-campaign chain's child argv is unchanged |
| `--baseline_isolation` | off. Excludes the bundled baselines from the LLM-facing surface: bundled descriptions refused, prompt examples neutralised, built-in proposals refused by name (arXiv U3). Pinned in the lock |
| `--print_resolved_launch_config` | off. Print the resolved launch configuration (arm, lit-review topology + config sha256, isolation, composition, workspace, advice file + resolved advice path + OBSERVED advice sha256, declared posture) as ONE JSON object and exit 0 with no side effects. Includes `required_runtime_profile_path` / `required_runtime_profile` / `required_runtime_profile_sha256` — recorded as `null` when undeclared, so "no profile was pinned" is an observable fact rather than an absent key |

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
HealthGate-valid provenance is refused by name through
`classify_under_pinned_policy` — against the gate set the champion's OWN
workspace pinned, never the repo-current shipped config, and an
unestablished roster is UNKNOWN and therefore a refusal —
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
shape and refuses at validation — plus `provenance_workspace`, the run
workspace whose pinned `health_checks_effective.yaml` governs every
provenance record, required since F-4 because the value it would otherwise
default to is a different run's policy), `--workspace_root`. Refusals exit
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
