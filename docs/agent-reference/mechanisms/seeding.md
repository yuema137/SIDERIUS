# Run seed and seed derivation

Semantic owners: `src/core/seeding.py` (run seed and derivation),
`src/core/training_seeds.py` (torch-free trainer plan) and
`src/execute_tools/process_seeding.py` (process and loader seeding). Tests:
`tests/unit/core/test_seeding.py`,
`tests/unit/execute_tools/test_trainer_seeding.py`. Design and rollout:
issue #983.

## Scope

This page owns the run-seed value, its generation, the versioned
derivation `siderius-seed/v1` that turns one run seed into the seed of each
stochastic unit, and how the native trainer applies those seeds. It does not
own where a run seed is admitted, locked or displayed; later PRs of issue
#983 add those and document them with their owners.

**Landed state.** Every run-seed entry boundary resolves, locks and prints
one `run_seed` (lock, then `--run_seed`, then `resolve_run_seed`): the native
workflow startup and the standalone tuner CLI; see
[persistence-and-resume.md](persistence-and-resume.md#run-seed-in-the-lock-issue-983).
Candidate and preparation operations bind the seed at operation admission
(`OperationRecord.run_seed`), and direct `launch_candidate` / `prepare_candidate`
calls bind it before their first receipt; candidate training admission only
adopts the launch receipt's seed
([operations](../../../src/tools/candidate_operations/candidate-operations-contract.md#run-seed-issue-983),
[worker](../../../src/tools/candidate_worker/candidate-worker-contract.md#run-seed-and-tuner-coordinates-issue-983)).
A captured native chain carries an explicit seed as its declaration's
`run.run_seed`, rendered into the reviewed shell vector as `--run_seed N`;
otherwise iteration 1's startup generates it
([native chain](../../../src/tools/native_chain/native-chain-contract.md#run-seed-issue-983)).
The tuner derives every attempt seed from the locked seed
([Tuner attempt seeds](#tuner-attempt-seeds)) and hands the trainer a
`SeedContext`, so a tuner-driven trainer never generates its own seed. The
per-purpose pins `sampling_seed` and `train_base_seed` are retired
([Retired seed pins](#retired-seed-pins)).

Both entry kinds print their seed through one formatter,
`core.seeding.format_seed_line`: `[seed] run_seed=N source=S`, where `S` is
`operator`, `generated` or `locked` at the workflow startup and `supplied` or
`generated` at the trainer CLI.

## Public interface

| symbol | contract |
|---|---|
| `RunSeed` | `Annotated[int, Field(ge=0, le=2**53 - 1, strict=True)]`. Strict: `bool`, `float` and numeric strings are refused, not coerced. The upper bound keeps the value exact in a JavaScript number. |
| `RUN_SEED_MAX` | `2**53 - 1` |
| `SeedSource` | `Literal["operator", "generated"]` |
| `RunSeedBinding` | frozen, `extra="forbid"`: `value: RunSeed`, `source: SeedSource`, `derivation: Literal["siderius-seed/v1"]` (default). The recorded form of a run's seed. |
| `generate_run_seed() -> int` | `secrets.randbelow(2**53)`: uniform over `[0, 2**53 - 1]` from the OS CSPRNG. The only impure function in the module. |
| `resolve_run_seed(explicit: int \| None) -> RunSeedBinding` | `None` → generate, `source="generated"`; otherwise validate as `RunSeed`, `source="operator"`. Invalid explicit values raise `pydantic.ValidationError`. |
| `admitted_run_seed(explicit, admitted) -> RunSeedBinding` | the binding an entry boundary executes: `admitted` when an operation admission already bound one (it must equal what `resolve_run_seed(explicit)` binds: the operator's value, or `source="generated"` when `explicit` is `None`; otherwise `ValueError`), else `resolve_run_seed(explicit)`. Used by `launch_candidate`, `prepare_candidate`, `prepare_reusable_candidate` and the `OperationRecord` validator. |
| `SeedPurpose` | closed `Literal` (below). Extended only by a reviewed PR. |
| `SeedCoordinates` | frozen, `extra="forbid"`, `strict=True` (below). |
| `SEED_DERIVATION` | `"siderius-seed/v1"` |
| `SeedLineSource`, `format_seed_line(run_seed, source) -> str` | the single `[seed] run_seed=N source=S` stdout formatter; `S` ∈ `operator`, `generated`, `locked`, `supplied`. Used by `WorkspaceRunSeed.log_line` and the trainer's `seed_log_line`. |
| `canonical_json_bytes(atoms) -> bytes` | the canonical tuple encoding (below). Accepts only `str`, `int` (not `bool`) and `None`; anything else raises `TypeError`. |
| `derive_seed(run_seed, purpose, at) -> int` | the `v1` derivation; result in `[0, 2**63 - 1]`. Raises `ValidationError` for an invalid `run_seed` and `ValueError("unknown seed purpose …")` for a purpose outside `SeedPurpose`. |
| `MissingRunSeed` | `ValueError` subclass raised by a component that requires a seed and received `None`. Only an entry boundary may generate a run seed. |

The module imports neither torch nor NumPy, so the operation store and the
console may import it.

## Purposes

| group | `SeedPurpose` values |
|---|---|
| tuner | `tuner.train_sampling`, `tuner.eval_sampling` |
| trainer | `trainer.init` (torch), `trainer.init_numpy`, `trainer.init_python`, `trainer.epoch_subsample`, `trainer.epoch_order`, `trainer.epoch_shuffle` |
| data analysis | `data_analysis.sampling`, `data_analysis.program` |
| validation | `validation.probe` |

There is no per-unit intermediate purpose: every seed is derived directly
from the 53-bit `run_seed` plus coordinates. A 63-bit derived value is never
passed back to `derive_seed` as a root; `derive_seed` refuses it because the
`run_seed` argument is validated as `RunSeed`. A trainer therefore derives
its seeds from the run seed it is given (`SeedContext.run_seed`), never from a
derived value.

Each purpose is an independent stream. A consumer that draws a
data-size-dependent number of values from one purpose cannot shift the values
of another purpose.

## Coordinates

| field | type | meaning |
|---|---|---|
| `iteration` | `int ≥ 1 \| None` | global iteration index: native-chain iteration, or candidate-loop iteration continued across resume segments (never restarted at 1) |
| `node_id` | non-empty `str \| None` | authored graph node id on candidate graphs, unique within a graph; `None` on the native chain |
| `branch` | `int ≥ 0 \| None` | fan-out family index, only where one node runs several families |
| `round` | `int ≥ 1 \| None` | tuner round |
| `attempt` | `int ≥ 1 \| None` | tuner `total_attempts` |
| `epoch` | `int ≥ 0 \| None` | training epoch |

An absent coordinate is `None` and encodes as JSON `null`, never `0`. Labels
(`run_name`, `exp_id`, workspace paths), file counts, dataset lengths, batch
sizes, wall time and PIDs are never coordinates: renaming a run or changing the
data size does not change any derived seed.

## Derivation `siderius-seed/v1`

```
payload = canonical_json_bytes((
    "siderius-seed/v1", run_seed, purpose,
    at.iteration, at.node_id, at.branch, at.round, at.attempt, at.epoch,
))
derive_seed = int.from_bytes(sha256(payload).digest()[:8], "big") & (2**63 - 1)
```

`canonical_json_bytes` is `json.dumps(list(atoms), separators=(",", ":"),
ensure_ascii=True).encode("ascii")`. JSON keeps element boundaries and types,
so `("a", "bc")` ≠ `("ab", "c")`, `1` ≠ `"1"`, `None` ≠ `0`, and equal values
in different slots differ.

Invariants:

- Python `hash()`, set or dict iteration order, process state and labels are
  not inputs. The result is identical across processes and
  `PYTHONHASHSEED` values.
- The byte encoding is frozen for `v1`. Any change to field order, encoding,
  digest slice or mask is a new derivation identifier, not an edit to `v1`.
  The known-answer vectors in the test module pin it.
- The 63-bit result is accepted directly by `random.Random`,
  `torch.manual_seed` and `numpy.random.default_rng`. It exceeds
  JavaScript's safe-integer range; only the run seed is meant for display.

## Failure behavior

| input | result |
|---|---|
| explicit run seed `< 0`, `> 2**53 - 1`, `bool`, `float` or `str` | `pydantic.ValidationError` |
| coordinate of the wrong type (e.g. `iteration="1"`), below its bound, or an unknown field | `pydantic.ValidationError` |
| purpose outside `SeedPurpose` | `ValueError` |
| canonical atom that is not `str`, `int` or `None` | `TypeError` |

## Validation evidence

`tests/unit/core/test_seeding.py`: known-answer vectors checked against both
literals and an independent `hashlib` formula; derivation equality across two
subprocesses with `PYTHONHASHSEED=1` and `2`; boundary and type distinctness
of the canonical encoding; per-coordinate, `None`-vs-`0`, slot and purpose
distinctness; inclusive range bounds and strict refusal; full-range generation
without `hash()`.

`tests/unit/execute_tools/test_trainer_seeding.py`: two in-process CPU runs
with one `SeedContext`, started from different process RNG states, give
identical initial weights and loss histories, and a different run seed gives
different initial weights; a missing plan raises `MissingRunSeed` before model
construction; `main()` records generated and supplied seeds; freezing pins
only the subsample stream; the `[seed]` line is printed before training
starts; children get `PYTHONHASHSEED=0` unless the operator set a value.

## Trainer seeding

### `core/training_seeds.py` (torch-free)

| symbol | contract |
|---|---|
| `SeedContext` | frozen, `extra="forbid"`, `strict=True`: `run_seed: RunSeed`, `at: SeedCoordinates` (default all `None`). `at.epoch` must be `None`; the trainer owns the epoch (`ValidationError` otherwise). |
| `TrainingSeedPlan(context)` | frozen dataclass; a pure function of the context. |
| `.init_torch` / `.init_python` | `derive_seed(run_seed, "trainer.init" / "trainer.init_python", at)`, 63-bit |
| `.init_numpy32` | `derive_seed(run_seed, "trainer.init_numpy", at) & (2**32 - 1)` (legacy `np.random.seed` accepts 32 bits; the low bits of SHA-256 output are uniform) |
| `.process_seeds() -> ProcessSeedRecord` | `{torch, numpy, python}` = the three values above |
| `.epoch(k, *, freeze_subsample=False) -> EpochSeeds(subsample, order, shuffle)` | `order` / `shuffle` = `derive_seed(…, "trainer.epoch_order" / "trainer.epoch_shuffle", at with epoch=k)`. `subsample` = `derive_seed(…, "trainer.epoch_subsample", at with epoch=k')`, `k' = 0` when `freeze_subsample` else `k`. Freezing affects only the subsample stream. |
| `require_seed_plan(plan)` | returns `plan`; `None` raises `MissingRunSeed` |
| `resolve_trainer_seed_plan(context)` | the trainer CLI entry boundary: a context ⇒ `(TrainingSeedPlan(context), "supplied")`; none (a direct trainer invocation only) ⇒ a generated run seed with empty coordinates and `"generated"`. |
| `trainer_seed_record(plan, source)` | the results-JSON seed fields (below) |

The module imports neither torch nor NumPy, so a parent process can compute the
trainer's epoch-0 subsample seed without loading torch.

### `execute_tools/process_seeding.py` (training child)

| symbol | contract |
|---|---|
| `seed_process(plan) -> ProcessSeedRecord` | `random.seed(init_python)`, `np.random.seed(init_numpy32)`, `torch.manual_seed(init_torch)` (which also seeds every CUDA device) |
| `torch_generator(seed)` | a CPU `torch.Generator` seeded with `seed`, for a `DataLoader` sampler |
| `dataloader_worker_init(worker_id)` | in a loader worker: `np.random.seed(torch.initial_seed() % 2**32)` and `random.seed(torch.initial_seed())`; the worker's torch seed is already the loader generator's base seed plus `worker_id` |

### Engine behavior

`train_engine_sandbox.run_experiment_streaming(..., seed_plan=...)`:

1. `seed_plan=None` raises `MissingRunSeed` before the model is built. There is
   no label- or `hash()`-based fallback.
2. `seed_process(seed_plan)` runs before model construction, so weight
   initialization and dropout draw from seeded generators.
3. Target standardization's pool uses `seed_plan.epoch(0).subsample`.
4. Epoch `k` uses `EpochSeeds = seed_plan.epoch(k, freeze_subsample=…)`:
   `EpochSamplingParams.epoch_seed = subsample`; the sequential order stream is
   `random.Random(order)`; every `DataLoader` receives
   `generator=torch_generator(shuffle)` and
   `worker_init_fn=dataloader_worker_init`. The `[data_order]` line prints the
   subsample seed.
5. The R3 validation pass keeps its `fork_rng` isolation, so it consumes no
   training RNG state.

The legacy single-file branch of `main()` calls `seed_process` before building
its dataset and gives its loader the epoch-0 shuffle generator.

### Trainer CLI entry boundary

`--seed_context_json PATH` supplies a `SeedContext` (validated with
`SeedContext.model_validate_json`). When it is absent, `main()` generates a run
seed with `generate_run_seed`. Before any data, model or training work,
`main()` prints `[seed] run_seed=N source=supplied|generated`
(`seed_log_line`) to the child's stdout, so a crash, OOM or timeout does not
lose a generated seed. After training, `main()` adds to the results JSON
(`experiment_results_{model_type}_{exp_id}.json`):

| key | value |
|---|---|
| `seed_context` | the `SeedContext` as JSON |
| `seed_derivation` | `"siderius-seed/v1"` |
| `seed_source` | `"supplied"` or `"generated"` |
| `process_seeds` | `{torch, numpy, python}` |

These keys never reach an LLM: the tuner's `interpret_training_results`
forwards only `LEGACY_TRAINING_RESULT_KEYS` and `training_history`.

### Tuner attempt seeds

Owner: `nodes/ml_hyperparameter_tune_agent/attempt_seeds.py`
(`derive_attempt_seeds`, `require_run_seed`), called once per attempt by
`planning.prepare_attempt`.

- Input: `HyperparamTuningInput.run_seed` (required; `None` raises
  `MissingRunSeed` at tuner startup, before any LLM call) and
  `HyperparamTuningInput.seed_coordinates`, the caller-owned position
  (`iteration`, `node_id`, `branch`; supplying `round`, `attempt` or `epoch`
  is refused). The native workflow passes `SeedCoordinates(iteration=N)` for
  global chain iteration `N`. Candidate graphs pass
  `SeedCoordinates(iteration=N, node_id=<tuning node>)` for global loop
  iteration `N` (`1` outside a loop).
- The attempt position adds `round` = the tuner round index and
  `attempt` = `total_attempts` (global within the tuner run, restored on
  resume). `run_name`, `exp_id` and paths never enter.
- `TrialConfig.train_sampling_seed = derive_seed(run_seed, "tuner.train_sampling", at)`;
  `eval_sampling_seed` is the same value when `train_validation_align`, else
  `derive_seed(…, "tuner.eval_sampling", at)`; `TrialConfig.seed_context =
  SeedContext(run_seed, at)`. All three are written to
  `trial_config_{exp_id}.json`; none is in `ExperimentRecord` or
  `record_params`, so no seed reaches a prompt.
- The trainer receives the context as `--seed_context_json`
  (`configs/<run>/seed_context_<exp_id>.json`, written by
  `sandbox_executor.execute_training`). `--train_base_seed` no longer exists.
- GPU probe (M1): the probe builds its epoch-0 selection with
  `epoch_seed = TrainingSeedPlan(seed_context).epoch(0).subsample`, and
  `validate_native_inputs(..., seed_context=...)` refuses a protected launch
  whose derived epoch-0 subsample differs from the measured probe's.
- Sampling seeds are 63-bit. Task `build_scope` code must seed a generator that
  accepts them (`numpy.random.default_rng`, `random.Random`); legacy
  `np.random.seed`/`RandomState` accept only 32 bits.

### Retired seed pins

Owner: `core/retired_seed_pins.py`. `sampling_seed` and `train_base_seed` are
removed from `WorkflowLaunchConfig`, `HyperparamTuningInput`, `ProposalInput`,
both protocols and the authored-editor controls.

**Readback rule.** Records written before the retirement stay readable. A
`null` pin (every pre-S3b tuner input wrote both as `null`) is dropped. A set
pin is kept as historical provenance in the owning schema's
`retired_seed_pins` field and is never an execution input.

**Admission rule.** New work that *sets* a pin is refused before any
provider call, so no proposal tokens are spent on a bundle that can never
train: saving or reviewing a workflow source in the editor
(`AuthoringError` code `retired_seed_pin`), observing a candidate submission's
training settings (`workflow_preview.observe_bindings`), and reusable
candidate preparation (`reusable_admission`). A `null` pin is not a set pin and passes.

**Execution rule.** Launching or continuing anything that still carries a set
pin is refused, which covers requests admitted by an older build. Every
refusal raises `RetiredSeedPin` (or wraps its message):
`… carries retired seed pin(s) […]: seeds derive from run_seed; set --run_seed`.

| surface | readback (lenient) | admission (new work) | execution / continuation |
|---|---|---|---|
| `--sampling_seed` (runner CLI) / `run_chain.sh --sampling_seed` | — | parse error (exit 2) / exit 1 | — |
| workflow source `training_settings.launch` | editor `read` shows it | editor review/save refuses | — |
| candidate training settings (`request.json`, snapshots) | `null` dropped; set pins → `CandidateTrainingSettings.retired_seed_pins` | `observe_bindings` and reusable preparation refuse | `admit_training` refuses before the proposer (also loop continuation) |
| `HyperparamTuningInput` (`tuning_input.json`, graph evidence) | `null` dropped; set pins → `retired_seed_pins` | the protocol has no pin parameter | `HyperparamTuningAgent.run` refuses before any LLM call |
| `ProposalInput` (`proposal.json`) | ignored (`extra="ignore"`, unchanged) | the protocol has no pin parameter | — |
| reviewed launch projection (`LaunchExpectations.check_projection`) | `null` pins dropped before comparison | — | a set pin refuses |
| archived `trial_config_{exp_id}.json` with `train_base_seed` | plain JSON evidence; not re-validated | — | — |

### Child environment

`core/subprocess_env.subprocess_env()` sets `PYTHONHASHSEED=0` for every
SIDERIUS child built from it, unless the operator already set
`PYTHONHASHSEED` in the parent environment; that value is kept unchanged
(`setdefault`). `str`/`bytes` hashing, and therefore `set` iteration order in
task code, is then identical across children. The parent orchestrator process
keeps a randomized hash seed; that is a stated limitation.

**Accepted widening.** The design required this only for trainer and probe
children. It applies to every `subprocess_env()` child, including inference,
scoring, measurement workers, the code validator, historical inference and
the data-analysis executor, whose program stdout can reach prompts. For those
children a set-order-dependent output that used to vary per process is now
stable. No paper prompt fixture is regenerated by re-execution, so paper prompt
bytes are unaffected.

### What the seed alone guarantees

| property | CPU | CUDA |
|---|---|---|
| identical data selection, order and shuffle | yes | yes |
| identical initial weights | yes | yes, same torch version |
| identical dropout masks | yes | same device type and torch/CUDA version |
| bitwise-identical metrics on rerun | yes, same library versions and thread count | no: needs the separate kernel-determinism mode |
| identical LLM decisions | no | no |

## Data-analysis sampling

Owner: `agent.data_analysis.sampling_seed`; node behavior and records:
[data analysis agent](../../../src/nodes/data_analysis_agent/data_analysis_agent.md#sampling-seed-issue-983).
The executed analysis sampling seed is the operator-declared
`AnalysisResourceEnvelope.sampling_policy.seed` when the policy file sets it,
else `derive_seed(run_seed, "data_analysis.sampling", SeedCoordinates())`
(run-level: no iteration, no node id). The LLM plan never decides
explicitness: a declared seed must equal the plan's, and a derived one
replaces it. Only a declared seed is ever rendered into a prompt. The fixed
workflow passes its lock's `run_seed` to `DataAnalysisAgent(run_seed=...)`,
which raises `MissingRunSeed` for `None`. Data analysis runs only in the native
workflow (`model_exploration` → `run_optional_data_analysis`), not in candidate
preparation.

## Validation probes

Owner: `core.probe_seeds` (torch-free) and `execute_tools.process_seeding`
(`apply_process_seeds`, `seeded_scope`). A model probe's seeds are the
`validation.probe` value of a `SeedContext` at
`(iteration, node_id or None, attempt)`: Python and torch get the 63-bit
value, legacy NumPy its low 32 bits. `attempt` is the 1-based implementation
number within the iteration, so a retried implementation draws anew. The fixed
workflow builds the context from its lock's `run_seed` with `node_id=None`; a
candidate graph from the admitted run seed and its node's iteration and id.
`MLModelImplementor(probe_seed=...)` and `MLCodeValidatorAgent(probe_seed=...)`
carry it (constructor arguments, never prompt input).

- In-process probes (the implementor self-check, the validator's
  instantiation/gradient check) run inside `seeded_scope`, which restores the
  caller's Python, NumPy and torch states afterwards.
- `validator_probe_worker` receives the context through the environment
  variable `SIDERIUS_PROBE_SEED_CONTEXT` (`probe_seed_env`) and seeds its
  process before importing the candidate. The validator's pytest child gets
  the same entry, so a task-owned probe in generated pytest inherits it; the
  generated test source is not changed.
- `require_probe_seed` raises `MissingRunSeed` when no context is supplied or
  inherited. Standalone implementor/validator CLIs are entry boundaries: they bind
  `--run_seed` or generate a run seed (`core.seeding.resolve_run_seed`) and
  print the `[seed]` line.
- `ValidatorOutput.probe_seed` records the context. The legacy generated
  pytest templates (LLM-visible prompt text with `torch.randint`) are
  unchanged and run unseeded inside their pytest child.

## Generated code

**Analysis programs.** Every generated analysis program runs seeded: the
sandbox runner seeds Python `random` and legacy NumPy (low 32 bits) from the
request's seed before `analyze` runs. A `deterministic` program keeps the seed
it declared (kept as written); any other program gets
`AnalysisSamplingSeeds.program_seed` =
`derive_seed(run_seed, "data_analysis.program", SeedCoordinates())`
(`analysis_code_sandbox.executed_program_seed`), recorded in the run's
`sampling_seeds.json`. Program declarations and prompts are unchanged.

**Hard-coded seeds (Q4).** `core.generated_seed_scan.scan_seed_calls` reads
generated source and reports each seeding call (`manual_seed`,
`manual_seed_all`, `seed`, `SeedSequence`, and `default_rng` / `RandomState`
with an argument) as `GeneratedSeedCall(file, line, call)`. It never modifies,
strips or overrides code and never reaches a prompt; unparsable source yields
nothing. Records: `ValidatorOutput.generated_seed_calls` for the generated
plugin (omitted when empty), and
`generated_analysis/seed_calls/{source_sha256}.json` in the analysis run store
for each persisted analysis program. Such a call reseeds a generator with the
program's own constant: the one class of seed not derived from `run_seed`.

## Not yet provided

These belong to later #983 PRs:

- Console seed input and display (S6).
- The RNG census guard (S8).
