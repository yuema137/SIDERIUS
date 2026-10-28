# Run seed and seed derivation

Semantic owner: `src/core/seeding.py`. Tests:
`tests/unit/core/test_seeding.py`. Design and rollout: issue #983.

## Scope

This page owns the run-seed value, its generation, and the versioned
derivation `siderius-seed/v1` that turns one run seed into the seed of each
stochastic unit. It does not own where a seed is admitted, locked, recorded or
displayed, nor how a trainer seeds its RNGs; those are added by later PRs of
issue #983 and documented with their owners.

**Landed state.** The native workflow resolves, locks and prints one
`run_seed` per workspace (`--run_seed`, else the lock, else
`resolve_run_seed`); see
[persistence-and-resume.md](persistence-and-resume.md#run-seed-in-the-lock-issue-983).
No unit seed is derived from it yet: the tuner still derives its seeds from
`sha256(f"{run_name}_{total_attempts}")`, and the trainer's
`hash(exp_id)` fallback and unseeded process RNGs are unchanged. Do not cite
this page as evidence that any training or sampling is seeded.

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
its seeds from the run seed it is given (the planned `SeedContext.run_seed`),
never from a derived value.

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

## Not yet provided

These belong to later #983 PRs, not to `core/seeding.py`:

- `SeedContext` and the pure `TrainingSeedPlan`, in a torch-free
  `core/training_seeds.py`.
- Torch/NumPy process and generator seeding helpers, in
  `execute_tools/process_seeding.py`. The planned legacy `np.random.seed`
  reduction is `derive_seed(..., "trainer.init_numpy", at) & (2**32 - 1)`.
- Candidate admission, record and receipt fields, and the RNG census guard.
