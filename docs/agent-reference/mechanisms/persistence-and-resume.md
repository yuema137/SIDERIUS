# Persistence, provenance and resume

**Semantic owners**: `core/run_invariants.py`, `core/resume.py`,
`workflows/model_exploration.py` (chain state)
**Status**: ✅ Current

---

## Purpose

Make a run's history durable and its comparability provable: what was persisted,
what identity it was produced under, and what may safely continue it.

## Non-responsibilities

- Persistence is **not** an inter-node channel. Nodes never read each other's
  output files.
- Not a database. Records are JSON logs on the workspace filesystem.

## What is persisted

| artefact | location | role |
|---|---|---|
| per-node output record | `{workspace}/{node}_{run_name}.json` | a **log** — for humans and recovery, never a channel |
| effective health config | `{workspace}/health_checks_effective.yaml` | the composed framework+task policy, sha256-pinned |
| run invariants lock | `{workspace}/run_invariants_lock.json` | pins the run's comparability identity |
| staged plugins | `{workspace}/plugins/{run_name}/` | the code that actually ran |

## The three communication mechanisms

Nodes communicate through **schema, storage and protocols — and nothing else**.

- **Schema** — each node's input/output `BaseModel` is the complete contract.
- **Storage** — per-node record files. A log, not a channel.
- **Protocols** — typed functions in `agent/schemas/protocols/` that assemble a
  downstream node's input from upstream outputs. The only place field mapping
  happens.

Reading a peer node's output file by convention is a defect, not a shortcut: it
creates an edge invisible to the protocol system.

## The invariants lock

Pins, per workspace:

- the resolved data scope,
- whether health gates are enabled,
- the sha256 of the effective health configuration,
- the formal evaluation fraction (`formal_eval_portion`),
- the run seed (`run_seed`) and its derivation (`seed_derivation`,
  `"siderius-seed/v1"`).

A resume, seed or reuse with any of these different **fails at startup**.

This exists because **aggregate scalars are only comparable within one scope,
one evaluation fraction and one health configuration.** A workspace that
silently accepted a changed value
would produce numbers incomparable with its own history, and nothing downstream
could tell.

`RunInvariants` partitions its fields: `_CANONICAL` values are compared;
`_PROVENANCE` values (such as the resolved role ceilings) are **recorded and never
compared**. Adding a field to the wrong partition either weakens the guarantee or
makes every resume fail.

Ordering at startup is load-bearing: materialize + hash the effective health
config → validate ingress evidence → create-or-validate the lock.

### Run seed in the lock (issue #983)

Owner: `core/run_seed_lock.py` (resolution) over `core/run_invariants.py`
(storage and comparison). The value contract is [seeding.md](seeding.md).

- `run_workflow` resolves the seed once, before `prepare_training_run`, with
  `resolve_workspace_run_seed(workspace, launch.run_seed)`. Precedence: an
  existing lock's `run_seed`, then the explicit `WorkflowLaunchConfig.run_seed`
  (`--run_seed`), then `resolve_run_seed` generation. It prints
  `[seed] run_seed=N source=operator|generated|locked` and the lock records the
  value before any node runs.
- The chain pre-flight (`run_one_iteration.compute_expected_invariants`) uses
  `continuation_run_seed`: the locked seed, else the flag. It never generates,
  so iteration 1 without `--run_seed` leaves generation to `run_workflow`.
- Both fields are `_CANONICAL` and are omitted from the lock when `None`, so a
  seedless lock keeps its pre-seed bytes. They are set together or not at all
  (`run_seed_lock_fields`).
- `run_seed_source` (`operator` | `generated`) records how the creating
  execution obtained the seed. It is `_PROVENANCE` (recorded, never compared),
  omitted when `None`, and absent from locks written by an execution that adopted
  an existing seed (the tuner sub-workspace lock, for example).
- History import (`--seed_paths`, `source_run_name`) reads only the target
  workspace lock, so a new workspace never inherits a source run's seed.
- `WorkflowLaunchConfig.run_seed` projects only when set (`omit_if_none`), so a
  seedless reviewed capture keeps its bytes. Candidate settings refuse it
  (`INACTIVE_LAUNCH_FIELDS`). Until S4 admits the seed with the operation,
  candidate training admission resolves its workspace seed the same way (lock,
  then generation) and prints the `[seed]` line.
- The standalone tuner CLI (`ml_hyperparameter_tune_agent.py main`) is an entry
  boundary too: lock, then `--run_seed`, then generation, before round 1.
- The tuner receives the locked value as `HyperparamTuningInput.run_seed`, locks
  it in its sub-workspace and writes it to `run_config_{run_name}.json`.

## Carried state across iterations

Two values must survive a real process restart, and both ride the canonical
lifecycle rather than a sidecar:

| value | rule |
|---|---|
| `vocab_link_confirmations` | latest-wins on the **whole dict**; a key-less digest is *skipped*, not a reset; malformed **raises** |
| `accumulated_key_findings` | chronological **union** |

The findings union has **one authority** — `core.resume.union_key_findings` —
which both the digest projection and the loop closure call. A structural guard
enforces this, because the differential test that used to guard it *passes* when
the rule is re-inlined.

The sidecar `accumulated_findings_*.json` is a **log**, never the transport
channel.

## Auto-resume

On by default. The chain launcher asks `scripts/launch/inspect_run_state.py --next-iter`
for the first incomplete iteration; if all are complete it exits cleanly rather
than redoing work.

```
--no_auto_resume    force a fresh start
--start_iter N      manual pin, overrides the inspector
```

> Known wrinkle: the launcher's `START_ITER` capture can be corrupted by plugin
> loader output on stdout. `--start_iter N` is the workaround.

## Provenance stamps

Records carry the composition fingerprint, the effective health config hash, the
resolved scope, and content hashes for file-declared plugins. Two records with the
same fingerprint were produced under the same declared semantics.

Both the **record** stamp and the **output** stamp must read one run-scoped
authority. A real gate run caught them disagreeing — the output stamp read the
tuner's own sub-workspace lock and resolved to `None`, which would have made a
composed multi-iteration chain refuse its own earlier output. No unit test could
see it.

## Fail-closed behaviour

| condition | result |
|---|---|
| resume with a different data scope | startup failure |
| resume with different health-gate enablement | startup failure |
| resume after editing a health plugin or task health config | startup failure (the digest moved) |
| resume with a `--run_seed` different from the locked `run_seed` | startup failure naming `run_seed` |
| continuing a workspace whose lock has no `run_seed` (created before the seed contract) | refused (`pre_seed_lock_violation`); the chain halts. The workspace stays readable and is not modified. A seedless comparison (old tooling reading the lock) still validates against it. |
| malformed carried confirmations | raises |
| inspector cannot compute the next iteration | launcher halts with both signals shown |

Each of these is the guard working. Do not relax one to make an in-progress tree
start.

## Source map

| concern | location |
|---|---|
| invariants + partitioning | `core/run_invariants.py` |
| run-seed resolution against the lock | `core/run_seed_lock.py` |
| findings union authority | `core/resume.py::union_key_findings` |
| lock construction ordering | `workflows/model_exploration.py:2196` (`build_run_invariants`) → `:2281` (`ensure_run_invariants`) |
| chain state carry | `workflows/model_exploration.py` (`ChainState`) |
| resume inspector | `scripts/launch/inspect_run_state.py` |

## Related

- [Operating a run](../../guides/operating-a-run.md) · [Composition](composition.md) · [Plugins](plugins.md)
