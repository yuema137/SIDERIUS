# Operating an explicitly composed run

SIDERIUS executes one task composition at a time. The caller owns the task,
data, scientific treatment, workspace, and resource budgets; the framework
owns validation, execution, persistence, and fail-closed routing.

## Required inputs

A run must provide:

- an explicit task-composition manifest;
- an existing physical data root;
- a writable, run-specific workspace;
- a run name and bounded iteration count;
- any task advice, literature-review configuration, or campaign policy that
  the caller intends to enable.

No scientific task, dataset, Health roster, metric, advice artifact, or
campaign is selected implicitly.

## Dry run first

Resolve the exact command without creating a workspace:

```bash
bash scripts/launch/run_chain.sh \
  --mode lilab \
  --workspace /tmp/siderius_run \
  --run_name qualification_v1 \
  --task_composition /absolute/path/to/composition.yaml \
  --data_dir /absolute/path/to/data \
  --num_iterations 2 \
  --max_rounds 2 \
  --dry-run
```

Inspect the resolved task identity, portions, budgets, Trial/Formal policy,
Health mode, advice identity, and executable child arguments. A design
document or launch wrapper is not evidence of an effective value.

## Fresh execution

Use a new workspace for a new scientific lineage:

```bash
bash scripts/launch/run_chain.sh \
  --mode lilab \
  --workspace /absolute/path/to/new_workspace \
  --run_name qualification_v1 \
  --task_composition /absolute/path/to/composition.yaml \
  --data_dir /absolute/path/to/data \
  --num_iterations 2 \
  --max_rounds 2 \
  --force_fresh
```

`--force_fresh` refuses a populated workspace; it does not erase one. Move or
archive old state explicitly before using the path for a new lineage.

## Resume

Use `--auto_resume` only when continuing the same comparable run:

```bash
bash scripts/launch/run_chain.sh \
  --mode lilab \
  --workspace /absolute/path/to/existing_workspace \
  --run_name qualification_v1 \
  --task_composition /absolute/path/to/composition.yaml \
  --data_dir /absolute/path/to/data \
  --num_iterations 4 \
  --auto_resume
```

The comparability lock refuses changes to identity-bearing configuration. Do
not bypass that refusal by rewriting manifests or copying an incumbent into a
fresh lineage.

Resumed scientific incumbents require independently valid Health evidence, not
just stored `scientific_authority` or `best_valid_formal_*` claims. Missing roles,
a missing or hash-mismatched effective policy, or missing required gate results
leave validity UNKNOWN and exclude the candidate with a named diagnostic. Raw
history remains readable; do not rewrite old records to manufacture evidence.
Explicit empty policies and explicitly disabled Health still permit finite
successful records. Failed or nonfinite records remain excluded.

## Resource qualification

Resource budgets are ceilings, not utilization targets. Static estimates may
inform planning; only measured evidence may refuse an expensive phase. A task
with semantic batches or variable-shaped inputs must provide them through its
declared task-data path so the probe measures executable data rather than a
shape-only surrogate.

Composed attempts also transport their evaluation scope to the isolated
preflight worker. Before training measurement, one real validation input runs
through the production inference input adapter and an evaluation-mode forward.
The Model-I/O contract selects the model dtype; dataset storage dtype may differ.
Input rejection reports both dtypes, the resolved dtype, shape, device and phase.
The check uses the existing single-probe timeout and worker memory bound.
Callers without an evaluation scope cannot receive this check. A successful
single-sample check does not establish full deliverable writing, scoring or
Health: qualify those paths with a bounded real candidate before a long run.

Hardware-derived watchdog profiles are caller-owned, content-pinned inputs.
When a run requires one, provide the complete profile binding through the
supported CLI. A missing or mismatched required profile must refuse before
training. An undeclared device/regime pair remains explicitly uncalibrated.

## Trial and Formal

Trial and Formal are two execution regimes inside a workflow. They are
independent of whether the caller labels the run an experiment,
qualification, or campaign. The same candidate execution path serves both;
the caller may vary declared scope and budget without introducing a second
training mechanism.

By default, Formal does not impose a batch-size floor beyond the task and
candidate contracts. A caller may declare an explicit rule when its scientific
treatment requires one.

## VRAM preflight watchdogs

VRAM preflight measures a candidate before expensive execution. One training
footprint probe materializes one task-valid batch, runs the model in training
mode, computes the declared loss, and records the tensors autograd would retain.
It does not call `backward()`, update the optimizer, train an epoch, or establish
the candidate's scientific quality. An inference probe similarly runs a bounded
forward, and inference-batch search may inspect multiple candidate batch sizes.

| Flag | Default | Bounds |
|---|---:|---|
| `--vram_probe_step_timeout_seconds` | `180` | one training-mode or inference footprint forward |
| `--vram_preflight_total_timeout_seconds` | `900` | the complete isolated preflight worker |
| `--vram_preflight_host_memory_limit_gb` | deployment default (normally `24`) | resident host memory for the complete isolated process tree |

Choose these values for the execution cost of one task-valid batch. A full
graph, long sequence, or expensive task plugin may need more time than a small
image batch. The host-memory limit is separately configurable because decoded
video, graph, and other task-valid batches can have materially different CPU
memory footprints. It is not the GPU VRAM ceiling. These safeguards do not
replace Trial/Formal wall-time budgets or change the VRAM ceiling. A timeout or
host-memory stop is an inconclusive measurement, never evidence that the model
is too large for the GPU.

Trial and Formal independently select one wall-time admission authority with
``--trial_time_admission_source`` and
``--formal_time_admission_source``. Both default to ``measured``: the advance
forecast does not admit or refuse, and executing-device verification enforces
the declared role budget. Select ``forecast`` only when avoiding measurement
cost is more important; then the advance workload forecast is the sole
admission authority and in-process measurement is record-only. A forecast
requires a supported complete workload description and refuses if that
evidence is unavailable. There is no silent fallback and no hybrid mode.

For workloads with unusually slow optimizer steps,
`--runtime_verification_max_wall_seconds` can extend the adaptive verifier's
observation window. Omit it to preserve the verifier default. This setting is
not a Trial or Formal budget: verification observes the first production
training steps and needs enough wall time to establish steady state before it
can extrapolate the complete workload.

A verifier refusal reports which evidence requirements remain unmet. Count
and elapsed-time minimums can both pass while a last slow observation still
needs a recovery observation (`pending_slow_observation`). The diagnostic
includes the current slow streak and sustained-slowdown threshold; it does
not classify one isolated delay as sustained slowdown or relax the caps.

The runtime watchdog is a separate last-resort safety mechanism. Selecting
either admission authority does not disable it or turn it into a second
admission decision.

Use `--no-runtime_watchdog` to explicitly disable phase deadline termination.
The diagnostic `--validation_max_phase_seconds` limit requires the resolved
watchdog to be enabled. An incompatible pair is refused at workflow launch,
before agent calls, using the same validation rule as direct tuner inputs.
To keep the watchdog off, omit that diagnostic phase limit. An external run
supervisor's total deadline remains independent of this setting.

## Failures and refusals

Interpret terminal evidence by responsibility:

| Outcome | Meaning |
|---|---|
| composition or argument refusal | required task or execution input is absent, invalid, or inconsistent |
| `code_package_integrity` | declared package/member/dependency pins cannot be trusted; the workflow halts the chain, not an ordinary candidate retry |
| admission refusal | measured evidence exceeds a declared execution ceiling |
| inconclusive preflight | the bounded measurement did not finish; it proves neither fit nor overflow |
| execution failure | training, inference, scoring, or persistence did not complete |
| Health invalidation | infrastructure completed, but the task declared the scientific output invalid |
| `no_records` manifest | no scientifically valid incumbent exists; typed negative feedback may still continue to the next iteration |
| completed manifest | an authoritative result was persisted for that iteration |

Do not report a Health-invalid candidate as an infrastructure failure, and do
not promote its scalar into a best-score trajectory.

A named task-code refusal writes `.chain_halted` with reason
`code_package_integrity` and exits 3. Guarded child diagnostics, when available,
live under `task_code/failures/`; queued iterations also respect the halt marker.
Read that diagnosis and restore the declared original files, or start a new
workspace for an intentional code change. Do not edit pins or clear a marker to
hide an unresolved failure. An early composition refusal may precede an iteration
manifest. Ordinary candidate errors, provider retries, Health invalidation and
resource-budget decisions retain their existing handling. See
[workspaces and resume](workspaces-and-resume.md) for source/pin ownership and
[package limits](../../src/core/local_code/README.md#refusal-and-limits).

## Campaign ownership

Campaign wrappers belong in the experiment repository. They may define bands,
parallelism, literature-review arms, frozen advice, monitoring, stop controls,
and later-stage authorization, but they must call these same framework entry
points against an exact SIDERIUS revision. SIDERIUS itself ships no production
campaign launcher or deployment inventory.


### Probe and calibration diagnostics

A candidate smoke test uses its declared temporal length, with a fixed contract
extent checked against the configuration. A reported probe contract conflict
should be resolved at that boundary, not by forcing the architecture to support
an unrelated short input. Scientific Health validity remains separate from
non-blocking diagnostic failures.

Successful inference measurements with unit `inference_sample` can enter the
calibration registry unchanged as milliseconds per sample. They are not relabeled
or numerically converted to milliseconds per batch. Unknown units and units
incompatible with the phase remain quarantined; existing identity, eligibility
and unit-bucket separation continue to apply.

## Data Analysis planning failures

Before analysis accesses data, an invalid plan gets one complete replanning
attempt after its bounded schema repair or binding resolution fails. The attempt
shares the original deadline and data-access policy; it does not regenerate the
prepared analysis program or disable the configured analysis treatment. Repeated
planning failure still stops honestly. See the
[Data Analysis contract](../../src/nodes/data_analysis_agent/data_analysis_agent.md#key-behavioral-notes)
for exact limits. Inspect the node's `structured_output_receipts.jsonl` for the
initial/repaired rejected drafts, hashes, and validation errors; only `plan.json`
is an admitted executable plan. Preserve those receipts before cleaning a failed run.
