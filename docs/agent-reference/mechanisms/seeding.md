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

**Landed state.** The trainer is seeded (see [Trainer seeding](#trainer-seeding)).
The tuner does not yet derive its seeds from a run seed: it still computes
`train_sampling_seed`, `train_base_seed` and `eval_sampling_seed` from
`sha256(f"{run_name}_{total_attempts}")` and passes only `--train_base_seed`
to the trainer, so a tuner-driven trainer runs under the
[interim rule](#interim-tuner-transport). No run seed is locked or shown yet.

## Public interface

| symbol | contract |
|---|---|
| `RunSeed` | `Annotated[int, Field(ge=0, le=2**53 - 1, strict=True)]`. Strict: `bool`, `float` and numeric strings are refused, not coerced. The upper bound keeps the value exact in a JavaScript number. |
| `RUN_SEED_MAX` | `2**53 - 1` |
| `SeedSource` | `Literal["operator", "generated"]` |
| `RunSeedBinding` | frozen, `extra="forbid"`: `value: RunSeed`, `source: SeedSource`, `derivation: Literal["siderius-seed/v1"]` (default). The recorded form of a run's seed. |
| `generate_run_seed() -> int` | `secrets.randbelow(2**53)`: uniform over `[0, 2**53 - 1]` from the OS CSPRNG. The only impure function in the module. |
| `resolve_run_seed(explicit: int \| None) -> RunSeedBinding` | `None` → generate, `source="generated"`; otherwise validate as `RunSeed`, `source="operator"`. Invalid explicit values raise `pydantic.ValidationError`. |
| `SeedPurpose` | closed `Literal` (below). Extended only by a reviewed PR. |
| `SeedCoordinates` | frozen, `extra="forbid"`, `strict=True` (below). |
| `SEED_DERIVATION` | `"siderius-seed/v1"` |
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
construction; `main()` records generated and supplied seeds, keeps the interim
`B + k` subsample values and refuses two subsample authorities; freezing pins
only the subsample stream; children get `PYTHONHASHSEED=0`.

## Trainer seeding

### `core/training_seeds.py` (torch-free)

| symbol | contract |
|---|---|
| `SeedContext` | frozen, `extra="forbid"`, `strict=True`: `run_seed: RunSeed`, `at: SeedCoordinates` (default all `None`). `at.epoch` must be `None`; the trainer owns the epoch (`ValidationError` otherwise). |
| `TrainingSeedPlan(context, pinned_subsample_base=None)` | frozen dataclass; a pure function of the context. |
| `.init_torch` / `.init_python` | `derive_seed(run_seed, "trainer.init" / "trainer.init_python", at)`, 63-bit |
| `.init_numpy32` | `derive_seed(run_seed, "trainer.init_numpy", at) & (2**32 - 1)` (legacy `np.random.seed` accepts 32 bits; the low bits of SHA-256 output are uniform) |
| `.process_seeds() -> ProcessSeedRecord` | `{torch, numpy, python}` = the three values above |
| `.epoch(k, *, freeze_subsample=False) -> EpochSeeds(subsample, order, shuffle)` | `order` / `shuffle` = `derive_seed(…, "trainer.epoch_order" / "trainer.epoch_shuffle", at with epoch=k)`. `subsample` = `derive_seed(…, "trainer.epoch_subsample", at with epoch=k')`, `k' = 0` when `freeze_subsample` else `k`. Freezing affects only the subsample stream. |
| `require_seed_plan(plan)` | returns `plan`; `None` raises `MissingRunSeed` |
| `resolve_trainer_seed_plan(context, train_base_seed)` | the trainer CLI entry boundary: a context ⇒ `(TrainingSeedPlan(context), "supplied")`; none ⇒ a generated run seed with empty coordinates and `"generated"`. A context together with `train_base_seed` raises `ValueError`. |
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
seed with `generate_run_seed`. `main()` adds to the results JSON
(`experiment_results_{model_type}_{exp_id}.json`):

| key | value |
|---|---|
| `seed_context` | the `SeedContext` as JSON |
| `seed_derivation` | `"siderius-seed/v1"` |
| `seed_source` | `"supplied"` or `"generated"` |
| `process_seeds` | `{torch, numpy, python}` |
| `pinned_subsample_base` | only under the interim rule below |

These keys never reach an LLM: the tuner's `interpret_training_results`
forwards only `LEGACY_TRAINING_RESULT_KEYS` and `training_history`.

### Interim tuner transport

Until the tuner derives a `SeedContext` (issue #983 S3b), it passes only
`--train_base_seed B`. The trainer then generates a run seed for the
initialization, order and shuffle streams (`seed_source="generated"`) and
pins only the subsample stream to `B + k` (`B` when `freeze_subsample`),
exactly the values the tuner used before. The GPU probe builds its epoch-0
selection with `epoch_seed=B`, which equals the trainer's epoch-0 subsample
seed. `--seed_context_json` together with `--train_base_seed` is refused.
S3b removes `--train_base_seed` and `pinned_subsample_base`.

### Child environment

`core/subprocess_env.subprocess_env()` sets `PYTHONHASHSEED=0` for every
SIDERIUS child (training, inference, scoring, measurement and probe workers),
so `str`/`bytes` hashing and therefore `set` iteration order in task code are
identical across children. The parent orchestrator process keeps a randomized
hash seed; that is a stated limitation.

### What the seed alone guarantees

| property | CPU | CUDA |
|---|---|---|
| identical data selection, order and shuffle | yes | yes |
| identical initial weights | yes | yes, same torch version |
| identical dropout masks | yes | same device type and torch/CUDA version |
| bitwise-identical metrics on rerun | yes, same library versions and thread count | no: needs the separate kernel-determinism mode |
| identical LLM decisions | no | no |

## Not yet provided

These belong to later #983 PRs:

- Tuner derivation of `SeedContext` and the GPU probe check on derived
  values (S3b); removal of `--train_base_seed`.
- Admission and lock integration, record fields, display, and the RNG census
  guard.
