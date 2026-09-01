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
bash sdsc_submission_scripts/run_chain.sh \
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
bash sdsc_submission_scripts/run_chain.sh \
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
bash sdsc_submission_scripts/run_chain.sh \
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

## Resource qualification

Resource budgets are ceilings, not utilization targets. Static estimates may
inform planning; only measured evidence may refuse an expensive phase. A task
with semantic batches or variable-shaped inputs must provide them through its
declared task-data path so the probe measures executable data rather than a
shape-only surrogate.

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

## Failures and refusals

Interpret terminal evidence by responsibility:

| Outcome | Meaning |
|---|---|
| composition or argument refusal | required task or execution input is absent, invalid, or inconsistent |
| admission refusal | measured evidence exceeds a declared execution ceiling |
| inconclusive preflight | the bounded measurement did not finish; it proves neither fit nor overflow |
| execution failure | training, inference, scoring, or persistence did not complete |
| Health invalidation | infrastructure completed, but the task declared the scientific output invalid |
| `no_records` manifest | no scientifically valid incumbent exists; typed negative feedback may still continue to the next iteration |
| completed manifest | an authoritative result was persisted for that iteration |

Do not report a Health-invalid candidate as an infrastructure failure, and do
not promote its scalar into a best-score trajectory.

## Campaign ownership

Campaign wrappers belong in the experiment repository. They may define bands,
parallelism, literature-review arms, frozen advice, monitoring, stop controls,
and later-stage authorization, but they must call these same framework entry
points against an exact SIDERIUS revision. SIDERIUS itself ships no production
campaign launcher or deployment inventory.
