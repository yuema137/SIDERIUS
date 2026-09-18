# Entrypoints and CLI

**Audience**: operators and anyone trying to find the right command.
**Authority**: `scripts/launch/run_chain.sh`,
`scripts/launch/_chain_common.sh`,
`src/workflows/run_one_iteration.py`,
`src/workflows/model_exploration.py`. Scientific comparison launchers live in
the external task repository.

For exhaustive flag lists, run each entrypoint with `--help`. This page covers
the flags that decide *what a run is*.

---

## Which entrypoint

| you want to | use |
|---|---|
| run the full multi-iteration agent loop | `scripts/launch/run_chain.sh` |
| launch a task-specific campaign | use the campaign entrypoint in the experiment repository; it delegates to this repository's `run_chain.sh` |
| run one arm of a task-specific comparison | use that experiment repository's launcher with an explicit SIDERIUS checkout |
| run exactly one iteration (or debug one) | `src/workflows/run_one_iteration.py` |
| drive the workflow directly from Python | `src/workflows/model_exploration.py` |
| compare a task model against baselines | use the task package's comparison entrypoint |
| gate a campaign launch | use the campaign-owned preflight in the experiment repository |
| run standalone literature review for an explicit task | `src/nodes/ml_literature_review/ml_literature_review.py` with `--task_composition`, `--data_dir`, and `--lit_review_config`; see the [node guide](../../src/nodes/ml_literature_review/ml_literature_review.md#cli-usage) |

> Maintained shell launchers live in `scripts/launch/`, the Slurm wrapper in
> `scripts/slurm/`, and the Python iteration owner in `src/workflows/`.

The literature CLI binds the full task contract before constructing the agent.
Its data directory must exist even though this node does not train or score.
An absolute external literature YAML is supported; relative `--lit_review_config`
paths remain checkout-root-relative. A contradictory history metric id/direction
refuses; absent or matching stamps are not proof of whole-task compatibility.

## Archived X9 preflight reference

The X9 preflight and its executable documentation moved to
`siderius-exp/campaigns/tidmad_x9`. The material below is historical design
context only; none of the named campaign paths is a SIDERIUS entrypoint.

### Historical launch-blocking gate

One gate, rows `R1`…`R9`, each printing `PASS` / `FAIL` / `SKIP` / `INFO`
with its evidence; any `FAIL` exits non-zero. Full row descriptions live in
the script's own `--help` and in the archived experiment documentation. Two
things about its output are worth knowing before you read a report.

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
bash scripts/launch/run_chain.sh \
    --mode lilab \
    --workspace /path/to/workspace \
    --run_name my_run_v1 \
    --num_iterations 5 \
    --task_composition configs/task_composition/quickstart.yaml \
    --data_dir /path/to/data \
    --max_rounds 5
```

| flag | meaning |
|---|---|
| `--mode {lilab,sdsc}` | required `lilab` = foreground subprocess; `sdsc` = `sbatch` + `afterany` chain |
| `--workspace DIR` | chain workspace root — required in practice |
| `--run_name NAME` | pins the immutable run id — required in practice |
| `--task_composition FILE` | the required task manifest; omission is refused |
| `--data_dir DIR` | physical data root. required; a run without it fails closed before any LLM or GPU work |
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

The generic chain also accepts
`--vram_probe_step_timeout_seconds` (default `180`) and
`--vram_preflight_total_timeout_seconds` (default `900`), plus
`--vram_preflight_host_memory_limit_gb` (omission preserves the deployment
default, normally `24`). The first bounds one
training-mode or inference footprint forward; the second bounds the complete
isolated preflight worker; the third bounds resident host memory for that
worker's process tree. They are workflow safeguards, not task declarations,
training-step counts, GPU VRAM ceilings, or Trial/Formal runtime budgets. See
[`operating-a-run.md`](../guides/operating-a-run.md#vram-preflight-watchdogs).

`--runtime_verification_max_wall_seconds` is an optional pass-through for the
adaptive in-subprocess verifier. It is omitted by default, preserving the
framework verifier default; slow-step workloads may set it explicitly without
changing their Trial or Formal budgets.

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

In a fresh Python process, both the script and
`python -m workflows.run_one_iteration` parse and normalize arguments, then bind
`--workspace` to `{workspace}/generated_library` before importing the resume and
workflow owners that load model registries. A stale ambient generated-library
root is replaced by that workspace binding. Implicit legacy checkout model
discovery is excluded; plugins in the selected workspace still load. `--help`
and missing required arguments exit before those registry-bearing imports.

This is an entry-ordering guarantee, not arbitrary Python isolation: explicit
`SIDERIUS_PLUGIN_DIRS` overrides remain supported, already-imported registries
are not reset, and unbound low-level helper calls retain legacy discovery.
The configuration-printing path also imports selected workspace plugins; their
import-time effects and stdout are not suppressed.

Two flags have **no defaults and are required for a formal launch** — the run
exits `2` without them:

| flag | choices |
|---|---|
| `--healthgate_mode` | `blocking` \| `observe_only` |
| `--result_authority` | `scientific` \| `diagnostic` |

Other flags that define a run:

| flag | default |
|---|---|
| `--task_composition` | required |
| `--data_dir` | required |
| `--data_scope` | `None` (full scope) |
| `--health_gate_enabled` / `--no-health_gate_enabled` | enabled |
| `--health_gate_files` | `None` |
| `--health_checks_config` | `None` (framework default) |
| `--max_rounds` | `3` |
| `--max_epochs` | `1` (mode-agnostic epoch ceiling; must be >= 1) |
| `--trial_max_epochs` / `--formal_max_epochs` | `None` — per-role epoch ceilings (D-BUD-6; frozen campaign posture trial 2 / formal 1). Precedence per round role: per-mode value → `--max_epochs` → no clamp; must be >= 1, refused at parse otherwise |
| `--max_proposal_attempts` | `3` |
| `--retain_model_outputs` | off: retire exact per-sample outputs after scoring/Health and after Data Analysis consumes historical predictions. On retains them; certified models and bounded evidence remain in either case. The value is pinned for resume. See [model-output retention](model-output-retention.md). |
| `--retain_training_checkpoints` | off: retire each exact training-original checkpoint after the tuner iteration and its output finish; every certified model blob remains. On retains the originals too. The value is pinned for resume. See [training-checkpoint retention](training-checkpoint-retention.md). |
| `--cleanup_denoised` / chain-only `--no-cleanup_denoised` | Legacy spellings. Cleanup already applies by default; the negative chain spelling is translated to `--retain_model_outputs` so existing explicit-retention campaigns keep their treatment. A conflicting cleanup/retention pair is refused. |
| `--llm_config` | `None` — **omitting it does not fail.** Empty forwards nothing (`_chain_common.sh:78`), and the runner then falls back to `WorkflowLLMConfig.uniform("gemini", --llm_model)` whose `--llm_model` default is `gemini-3.1-pro-preview` (`run_one_iteration.py:943`), so every LLM role silently resolves to the deprecated all-Gemini default and the run still exits 0. Pass an explicit routing config on any run whose model matters. Task-specific campaigns must bind and validate their own routing config. |
| `--required_runtime_profile_path` | `None`. The **ABSOLUTE** path of the profile artifact this launch requires. Part of the declaration and never derived — this is the clause that closes `finding_1_invisible_default`: while the artifact was located by the ordinary discovery rule (`$SIDERIUS_CALIBRATION_DIR/runtime_profiles_<gpu_slug>.json`), a binding certified *what was found* but never *that the right file was consulted*, so an overlay was used because the directory happened to hold a file of that name. When declared, resolution reads THIS file and never consults discovery — a missing declared artifact REFUSES even when discovery would have certified successfully. A relative path is refused at declaration, because the consuming subprocess runs with a different working directory (`run_chain.sh` cd's before exec) |
| `--required_runtime_profile` | `None` (undeclared → the legacy ladder: measured overlay > shipped > uncalibrated). Declares the runtime profile this launch REQUIRES, as `<gpu_slug>/<regime>` (e.g. `nvidia_h100_80gb_hbm3/single`), copied from a qualification run's recorded provenance. Must be declared together with `--required_runtime_profile_path` and `--required_runtime_profile_sha256`; any proper subset is refused, because half a binding is NO binding and resolving it as undeclared would leave the requirement silently unenforced. When declared, resolution is FAIL-CLOSED: a discovered device/regime that differs, a missing overlay, a digest mismatch, or a verified overlay lacking the row all REFUSE the launch instead of falling back (F-PROFILE-WIRE-1, mechanism F-H100-WD-1-PRETAG). Combining it with an explicit `--runtime_watchdog`/`--no-runtime_watchdog` also refuses — OPERATOR MODE never consults the profile, so the requirement would be unenforced |
| `--required_runtime_profile_sha256` | `None`. The 64-char lowercase-hex sha256 of the DECLARED artifact's bytes, certified for this run (`sha256sum "${SIDERIUS_CALIBRATION_DIR:-$HOME/.siderius}/runtime_profiles_<gpu_slug>.json"`). Hashed over the exact bytes parsed — a single read, never re-opened — so the profile consumed is provably the one that was qualified. Consumption is observable: `runtime_watchdog_provenance` reads `bound:<path>#sha256=<hex>` exactly when certification ran, and the digest it records is the one OBSERVED from the bytes read — never an echo of the declared value |
| `--experiment_arm` | `None` (unlabelled; an empty string is refused). Opaque label pinned in the lock and stamped on records / outputs / manifests (arXiv U1) |
| `--ml_lit_review_enabled` / `--no-ml_lit_review_enabled` | `None` → the YAML's `enabled` decides (shipped: `false`). The resolved flag and the config's sha256 are pinned in the lock; an enabled but unreadable config refuses the launch |
| `--ml_lit_review_config PATH` | literature-review YAML resolved by the iteration runner; composed tasks should supply their own task-specific framing |
| `--advice` / `--human_advice_file` | `None`. Path to the JSON advice artifact (`--advice` wins when both are given). Recognised top-level keys are exactly `interpret`, `propose`, `implement`, `validate`, `tune`, `mindset`, each a string or a list of lines. The key set is CLOSED: an unrecognised key, a key present but resolving to nothing, a non-text value, or a file with no recognised key at all REFUSES the launch by name (F-SCHED-5) — the digest is pinned as the run's treatment identity whether or not the content ever reaches a prompt, so an artifact that cannot inject must never get that far. Sparse advice stays legal; prefix a key with `_` to declare it deliberately inert. See the [human advice guide](../guides/advice.md) |
| `--advice_sha256` | `None` (undeclared). The launcher's OBSERVED sha256 of the advice artifact's bytes, forwarded as a DECLARATION. The run certifies it against its own single read and then discards it: the lock always pins the digest THIS process observed, never an echo of the declared value. A mismatch REFUSES the launch — which is how an edit to the artifact between two band launches of one campaign is caught, since the bands run in SEPARATE workspaces that no per-workspace lock can ever compare. Undeclared is legal (the observed digest is still pinned) and emits no token, so a non-campaign chain's child argv is unchanged |
| `--baseline_isolation` | off. Excludes the bundled baselines from the LLM-facing surface: bundled descriptions refused, prompt examples neutralised, built-in proposals refused by name (arXiv U3). Pinned in the lock |
| `--print_resolved_launch_config` | off. Print the resolved launch configuration (arm, lit-review topology + config sha256, isolation, composition, workspace, advice file + resolved advice path + OBSERVED advice sha256, declared posture) as ONE JSON object and exit 0 before iteration execution or run-artifact writes. Startup still binds the workspace and imports plugins; plugin stdout can precede the JSON. Includes `required_runtime_profile_path` / `required_runtime_profile` / `required_runtime_profile_sha256` — recorded as `null` when undeclared, so "no profile was pinned" is an observable fact rather than an absent key |

### `launch_prior_baseline_experiment.sh` — the two-arm experiment

One launcher, two arms, one argument changed:

```bash
Use the external experiment repository's documented `launch_prior_baseline_experiment.sh` entrypoint for this historical comparison.
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

## Task-specific baseline comparison — external consumer

`scripts/run_comparison.py` is no longer a framework entrypoint. Its task-owned
successor is `tasks/tidmad/tools/run_comparison.py` in `siderius-exp`.
Use that repository's documented environment and task inputs; invoking the
old path from a SIDERIUS checkout will not work. Generic framework runs use
the declared-composition workflow entrypoints above.

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
| `src/workflows/model_exploration.py` | ✅ |
| `src/nodes/ml_model_proposal_agent/ml_model_proposal_agent.py` | ✅ (required) |
| `src/nodes/ml_literature_review/ml_literature_review.py` | ✅ (required, with `--data_dir`) |
| External task comparison launcher | Task-owned; inspect the selected exp revision |

---

## Next

- [Operating a run](../guides/operating-a-run.md) — resume, budgets, failure modes
- [Task composition reference](task-composition.md)
- [Configuration map](configuration-map.md)

### Cooperative epoch allocation

Chain, iteration and tuner entrypoints accept
`--training_budget_reserve_fraction FLOAT` (default omitted/`None`). This
explicit opt-in reserves part of each resolved role time budget for downstream
work and enables time/cap-based epoch allocation. Both role budgets and
explicit epoch caps in `1..100` are required. It does not enable scientific
early stopping or a watchdog. See [cooperative training](cooperative-training-budget.md).
