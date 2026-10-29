# Entrypoints and CLI

**Authority**: `scripts/launch/run_chain.sh`,
`scripts/launch/_chain_common.sh`,
`src/workflows/run_one_iteration.py`,
`src/workflows/model_exploration.py`. Scientific comparison launchers live in
the external task repository.

## Independent training-validation snapshot

Chain and one-iteration entrypoints accept `--training_validation_portion`
(`0 < value <= 1`, omitted by default). A composed task selects a seeded
snapshot once per attempt for epoch loss, reused across its epochs. Final
inference/scoring and Health keep their original evaluation scope, including
`--formal_eval_portion`. Omission preserves existing behavior; changing the
setting on resume is refused. See the [tuner contract](../../src/nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.md#optional-snapshot-for-training-validation)
for selection, provenance and supported routes. This is an experimental policy,
not the test-only `--validation_max_samples` workload ceiling.

## Compute requirement (issue #1136)

A real launch (neither `--is_pseudo_llm` nor `--is_pseudo_training`; predicate
`workflows.standard_launch.is_real_launch`) requires a CUDA device visible to
PyTorch. No CPU training mode exists. `run_one_iteration` checks this through
`core.gpu_requirement.real_launch_gpu_refusal` (which reads
`core.hardware_context.discover()`) after the formal-launch policy and the
`--print_resolved_launch_config` view, and before the halt/brake checks, the
iteration directory, the run lock and any LLM call. On refusal it prints
`[run_one_iteration] LAUNCH REFUSED: SIDERIUS real training needs an NVIDIA GPU
with CUDA, and none is visible here (...)` to stderr and exits `2`. No manifest is
written, so the consecutive-failure brake does not count it; `run_chain.sh`
records the iteration as failed (`iter:2`) and the chain ends incomplete. The
runtime-control launch guard raises `LaunchGuardFailure` with the same sentence
when its measurement capability reports `accelerator_unavailable`; other
unavailability reasons (for example a missing dataset) keep the bounded-probe
wording. The chain header prints `Compute device   : NVIDIA GPU with CUDA required
(checked before any model call)` for real chains and `not checked (pseudo-mode; ...)`
for pseudo chains, including under `--dry-run`. Pseudo launches, `--dry-run` and
`--print_resolved_launch_config` are not checked.

For exhaustive flag lists, run each entrypoint with `--help`. This page covers
the flags that decide *what a run is*.

---

## Which entrypoint

| you want to | use |
|---|---|
| inspect or explicitly probe a forensic snapshot | `python -m tools.runtime_replay`; see the [replay contract](runtime-replay.md) |
| prepare a fresh candidate from reusable authored v2 source | `python -m tools.candidate_prepare --reusable-request PATH`; [preparation contract](../../src/tools/candidate_prepare/candidate-prepare-contract.md#managed-reusable-preparation), no launch/resume |
| launch a retained reusable candidate capture | `build_reusable_operation(config, selection, request_id)` then existing `python -m tools.candidate_operations submit --store-config FILE --request FILE`; [operation contract](../../src/tools/candidate_operations/candidate-operations-contract.md#retained-reusable-candidate-operations) |
| capture and enforce a fresh foreground native chain | `python -m tools.native_chain review --request PATH`, then `run_chain.sh` with paired `--expected_chain_capture` / `--expected_chain_capture_sha256` and `--chain_capture_input_max_bytes`; [capture contract](../../src/tools/native_chain/native-chain-contract.md) |
| dispatch a captured chain independently of the caller | `python -m tools.candidate_operations review --store-config FILE --request FILE`, then `submit`, `status`, `log`; [operation contract](../../src/tools/candidate_operations/candidate-operations-contract.md#captured-native-chain-operation) |
| stop, pause or resume a running authored research loop | `python -m tools.candidate_operations stop-loop`, `pause-loop`, `review-loop-resume` or `write-loop-resume` (`--store-config FILE --operation-id UUID`), then `submit`; [loop control recipe](../../src/tools/candidate_operations/candidate-operations-contract.md#control-an-authored-loop-from-code-or-the-cli) |
| run the full multi-iteration agent loop | `scripts/launch/run_chain.sh` |
| launch a task-specific campaign | use the campaign entrypoint in the experiment repository; it delegates to this repository's `run_chain.sh` |
| run one arm of a task-specific comparison | use that experiment repository's launcher with an explicit SIDERIUS checkout |
| run exactly one iteration (or debug one) | `src/workflows/run_one_iteration.py` |
| preview arguments/defaults for a fresh standard iteration without launching | [`python -m tools.setup_review`](../../src/tools/setup_review/README.md); optional JSON/HTML declaration inspection, not complete preflight |
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

## Live execution output names

`run_workflow()` validates its filesystem-consumed `run_name` with the shared
component rule before launch binding or run-directory creation. Unsafe names
raise `ValueError`; ordinary names and output layouts remain unchanged.
Direct `TidmadSandbox` construction and its training, inference and scoring
methods apply the same check before task resolution, name-derived writes or
child launch. `StubSandbox` inherits the constructor guard and checks each
independently supplied execution name before pseudo-state changes. Standalone
training and inference mains check parsed `--run_name` before loading task
contracts or preparing runtime execution, and raise `ValueError` on refusal.

This does not restrict archival decoding or read-only source selectors,
including the scoring CLI's deliverable selector. It is a component check,
not a guarantee covering arbitrary path arguments or symlinks. The validator
is included in both runtime-verifier and preflight source identities; historical
profiles must qualify the changed assembly before activation.

## Infrastructure aborts

`run_workflow()` returns typed tuner outputs, including an output whose
`termination_reason` is `infrastructure_abort` when runtime evidence fails.
The workflow preserves that output and stops before scientific aggregation or
another candidate. Its workflow summary has `status: failed` and
`termination_reason: infrastructure_abort`. Ordinary candidate failures retain
their existing continuation policy.

Python campaign callers must inspect the returned list with
`workflows.termination.infrastructure_abort_reason(results)` and stop when the
result is not `None`; earlier successful scores do not make the campaign safe
to continue. The direct model-exploration CLI exits 3 on this condition.
The one-iteration CLI preserves its manifest, writes `.chain_halted`, and exits
3; the marker prevents the next chained iteration from starting. The direct
Python API and model-exploration CLI do not create a chain marker or implement
automatic recovery. Diagnose the failed evidence channel before explicitly
starting further work; do not reinterpret an abort as a model-quality failure.

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
| `--seed_paths P [P…]` | prior run outputs to seed from. **Optional** — an empty list is a valid cold start. Imported history never supplies the new run's `run_seed` |
| `--run_seed N` | the run seed (issue #983), an integer in `[0, 2**53 - 1]`; forwarded to every iteration only when set. Omitted: iteration 1 generates one and later iterations adopt the locked value. See the runner table below |
| `--auto_resume` / `--no_auto_resume` | default **ON**: pick up where a partial chain stopped. The inspector's captured value is VALIDATED (F-SCANB-4): only the exit-0 capture's last line, and only a bare non-negative integer, becomes `START_ITER`; anything else (e.g. plugin-loader stdout chatter with no trailing value line) refuses loudly and names the workaround below — never a silent default |
| `--start_iter N` | manual override of auto-resume (also the refusal's named workaround) |
| `--dry-run` | walk the chain, print exact commands, no side effects |
| `--experiment_arm LABEL` | opaque experiment-arm label (arXiv U1). Pinned into `run_invariants_lock.json` and stamped on every record, tuner output and manifest; forwarded only when set. **Omitted = unlabelled**, byte-identical argv. Drives no behaviour |
| `--ml_lit_review_enabled` / `--no-ml_lit_review_enabled` | the literature-review node's presence in the workflow topology. Both the resolved flag and, when ON, the sha256 of the resolved lit-review YAML are pinned in the lock |
| `--ml_lit_review_config PATH` | forwards a task-owned literature-review YAML through the chain launcher; omit it only when the child default is intended |
| `--gpu_execution_policy_json FILE` | optional GPU execution policy JSON file; forwards the supplied path unchanged to every iteration in both modes. Use an absolute path when the file is outside the checkout. The native Python runner owns typed validation and run identity; omission preserves its default. A missing or empty argument is refused by the launcher. |

The auto-resume default and manual `--start_iter` override above describe
ordinary launches without a native chain capture. Captured
`native-standard-chain/v1` fixes `--start_iter 1` and `--no_auto_resume` and
requires a workspace that does not exist; even an existing empty directory is
refused. See the [native chain guide](../../src/tools/native_chain/README.md)
for the supported scope and refusal behavior.

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
| `--llm_config` | `None`: with no legacy `--llm_model`, selects the complete economical profile from `WorkflowLLMConfig.default()`. Explicit JSON takes priority and preserves partial-config inheritance; any key the config does not declare, at any route depth, is refused (a key starting with `_` is an inert annotation and is ignored). Explicit `--llm_model` retains legacy Gemini routing. Save an explicit config with scientific experiments. See [default routing](llm-defaults.md). |
| `--required_runtime_profile_path` | `None`. The **ABSOLUTE** path of the profile artifact this launch requires. Part of the declaration and never derived — this is the clause that closes `finding_1_invisible_default`: while the artifact was located by the ordinary discovery rule (`$SIDERIUS_CALIBRATION_DIR/runtime_profiles_<gpu_slug>.json`), a binding certified *what was found* but never *that the right file was consulted*, so an overlay was used because the directory happened to hold a file of that name. When declared, resolution reads THIS file and never consults discovery — a missing declared artifact REFUSES even when discovery would have certified successfully. A relative path is refused at declaration, because the consuming subprocess runs with a different working directory (`run_chain.sh` cd's before exec) |
| `--runtime_watchdog_deadline_policy` | `budget-ceiling-v1`. Enabled watchdogs use the minimum declared phase ceilings, independently of forecast admission; missing reachable-phase ceilings refuse before tuner setup/LLM calls. Explicit `forecast-tightening-v1` retains the old forecast-based deadline and floor. Standard workflow, multi-round chain and tuner CLI all transport the selection. See [watchdog deadlines](watchdog-deadlines.md). |
| `--required_runtime_profile` | `None` (undeclared → the legacy ladder: measured overlay > shipped > uncalibrated). Declares the runtime profile this launch REQUIRES, as `<gpu_slug>/<regime>` (e.g. `nvidia_h100_80gb_hbm3/single`), copied from a qualification run's recorded provenance. Must be declared together with `--required_runtime_profile_path` and `--required_runtime_profile_sha256`; any proper subset is refused, because half a binding is NO binding and resolving it as undeclared would leave the requirement silently unenforced. When declared, resolution is FAIL-CLOSED: a discovered device/regime that differs, a missing overlay, a digest mismatch, or a verified overlay lacking the row all REFUSE the launch instead of falling back (F-PROFILE-WIRE-1, mechanism F-H100-WD-1-PRETAG). Combining it with an explicit `--runtime_watchdog`/`--no-runtime_watchdog` also refuses — OPERATOR MODE never consults the profile, so the requirement would be unenforced |
| `--required_runtime_profile_sha256` | `None`. The 64-char lowercase-hex sha256 of the DECLARED artifact's bytes, certified for this run (`sha256sum "${SIDERIUS_CALIBRATION_DIR:-$HOME/.siderius}/runtime_profiles_<gpu_slug>.json"`). Hashed over the exact bytes parsed — a single read, never re-opened — so the profile consumed is provably the one that was qualified. Consumption is observable: `runtime_watchdog_provenance` reads `bound:<path>#sha256=<hex>` exactly when certification ran, and the digest it records is the one OBSERVED from the bytes read — never an echo of the declared value |
| `--run_seed` | `None`. The run's one seed, an integer in `[0, 2**53 - 1]` (out of range or non-integer exits `2` at parse). Precedence at workflow startup: the workspace lock's `run_seed`, then this flag, then generation. The value and `seed_derivation` are pinned in `run_invariants_lock.json` and `run_config_{run_name}.json` before any node runs, and stdout shows `[seed] run_seed=N source=operator\|generated\|locked`. A value different from the locked seed, or any continuation of a workspace whose lock predates the seed contract, halts with exit `3` (`run_contract_failure`); the old workspace stays readable. The retired `--sampling_seed` is refused with `seeds derive from run_seed; set --run_seed`. See [persistence and resume](../agent-reference/mechanisms/persistence-and-resume.md#run-seed-in-the-lock-issue-983) |
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
It has no `--run_seed`: `run_workflow` adopts the workspace lock's `run_seed`
or generates and locks a new one.

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

### Permanent run-contract failures

The iteration runner preserves a failed manifest, writes `.chain_halted` and
exits **3** when the run-invariants pre-flight or prior-state restoration refuses
the run (including a `run_seed` conflict or a pre-seed workspace), or
metric/interpretation declarations conflict. The foreground chain propagates this permanent halt;
queued iterations refuse before starting work. Ordinary candidate exceptions
retain the existing failure policy. An external supervisor must preserve the
permanent status and suppress service-level retries; stopping only the inner
chain does not control an outer service manager.

For persisted external metrics, reconciliation compares the complete serialized
declaration rather than the Python scoreability subclass. A data-only restored
contract can match its active declaration without acquiring execution authority.
Changed aggregation, transforms, references or contract parameters still refuse.

- [Operating a run](../guides/operating-a-run.md) — resume, budgets, failure modes
- [Task composition reference](task-composition.md)
- [Configuration map](configuration-map.md)

### Cooperative epoch allocation

Chain, iteration and tuner entrypoints accept
`--training_budget_reserve_fraction FLOAT` (default omitted/`None`). This
explicit opt-in reserves part of each resolved role time budget for downstream
work and enables time/cap-based epoch allocation. Both role budgets and
explicit positive integer epoch caps are required; there is no additional
100-epoch ceiling. It does not enable scientific early stopping or a watchdog. See [cooperative training](cooperative-training-budget.md).

### Optional optimizer-step guard

The chain shell, iteration CLI and tuner CLI default `--max_steps_per_attempt`
to `0` (disabled); they no longer inject a 150,000-step ceiling. Configure time
budgets for runtime admission/allocation. The explicit positive option remains
available for bounded harnesses and is recorded in provenance. It is not a
hardware-independent estimate of runtime. See
[cooperative training budget](cooperative-training-budget.md) for execution
limits and Formal resource recovery.


## Generated model and loss identifiers

Live model and loss identifiers must be single filesystem components: non-empty,
not `.` or `..`, and without `/`, `\`, colons or Unicode control characters.
The shared rule preserves valid names unchanged. The workflow checks proposals,
including fixed validation plans, before name-derived renaming; the implementor
checks selected names before generation. Independent staging and promotion paths
check before copying. Archived schemas remain readable but do not grant live
execution eligibility. This rule does not certify generated source code or
protect against malicious pre-existing symlinks under destination directories.

## Professional and Assistant reusable candidate setup

Both routes use `tools.candidate_prepare.prepare_reusable_candidate` and its
`--reusable-request` CLI. Professional callers author external project files;
Assistant callers help author the same files and explicit selections. Source
owns task references/advice; request owns fresh run identity and runtime policy.
In the console Workflow builder, both collaboration modes explicitly choose a
configured task version, **Update workflow references**, inspect the diff/findings,
confirm them and save. First save pending edits; a bound edit needs its matching
configured selection for ordinary review. Adopting an unchanged current snapshot
of unbound v2 source requires a separate confirmation before later edits. Changed
references support fresh managed candidates, including source-declared native
fanout/family profiles, with native structured interface checks and explicit review; see the
[task-version guide](../../src/tools/candidate_console/README.md#bind-a-task-version).
Assistant help proposes choices and edits the
same source; it does not replace explicit selection or acceptance. Saving source
is separate from preparing or launching its next capture.
The [preparation contract](../../src/tools/candidate_prepare/candidate-prepare-contract.md#managed-reusable-preparation)
owns managed-only support, failure receipts and the authored-v2 versus generated-v1
publication boundary. For authorized execution, both routes retain the exact
selection through `select_reusable_preparation` and construct
`build_reusable_operation(config, selection, request_id)`. Save that submission
outside the envelope and use existing `submit_operation` or CLI `submit --request`.
The [operation contract](../../src/tools/candidate_operations/candidate-operations-contract.md#retained-reusable-candidate-operations)
owns configured containment, original-v2 verification at admission/dispatch and
exact-UUID recovery without relaunch. Current source edits affect future captures;
retry uses the unchanged saved submission. Prepared inputs, admitted operation and
native terminal validation are different states. Three-stage candidate outputs do not imply training or scientific scoring.
Four-stage native completion requires inspecting its scores and termination evidence. This does not replace native chain entrypoints or
add resume. The configured console can explicitly prepare saved reusable source
and select, review and launch a three-stage or source-declared four-stage capture through the
[New run and prepared-run flow](../../src/tools/candidate_console/README.md#prepare-saved-source-or-open-an-existing-run).


Reusable four-stage source owns sparse `training_settings` and one managed
`native-training.settings` binding. Professional and Assistant callers edit that
same source; the GUI [training inspector](../../src/tools/candidate_console/README.md#edit-reusable-training-settings)
provides budgets, epoch ceilings, portions, independent seeds and retention.
Preparation creates a matching seed/settings pair; explicit launch invokes the
existing native tuner. Native completion is distinct from scientific validity,
and neither this route nor offline tests establish historical replay parity.

For independent proposal families, Professional and Assistant callers can author
`execution_profile="native-proposal-families/v1"` in reusable v2 source, give each
proposer its own managed seed binding, and use the same review/prepare/retained
launch flow. The [family preparation contract](../../src/tools/candidate_prepare/candidate-prepare-contract.md#reusable-independent-proposal-families)
owns exact indexing and explicit-profile receipt semantics. Existing source/canvas
keeps the actual instance edges; prepared review lists independent instances
executed serially. Direct version-1 native requests remain supported. Both routes
use the same native executor and independent operation/HTTP observation; neither
aggregates, ranks or promises distinct scientific proposals.
