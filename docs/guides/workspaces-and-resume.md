# Workspaces and resume

**Audience**: anyone about to re-run a command against an existing run directory,
or wondering what the files in one are.
**Answers**: what a workspace contains, what happens when you launch into an
existing one, and when you need a new one.

For *steering* a live run (budgets, scope, refusal table), see
[operating a run](operating-a-run.md). This page is about the directory itself.

---

## The two-verb model

Every launch is one of two things, decided by the workspace you point it at:

| you point `--workspace` at | what happens |
|---|---|
| an empty or new directory | a **fresh** run |
| a workspace with prior state, same declared semantics | a **resume** — the chain continues from the first incomplete iteration (auto-resume is on by default) |
| a workspace with prior state, *different* declared semantics | a **refusal at startup** — the invariants lock does not match |

There is no third verb. You cannot "partially reuse" a workspace under changed
settings: if you want a different data scope, different health-gate enablement
or a different health configuration, use a new workspace. Aggregate scores are
only comparable within one scope and one health configuration, and the lock
exists so that a workspace never silently mixes incomparable numbers.

## What a chain workspace contains

The chain launcher (`run_chain.sh` → `run_one_iteration.py`) names each
iteration `iter_NNN` and uses it as that iteration's `run_name`. After a run,
the workspace looks like this:

```
{workspace}/                            # --workspace
├── run_invariants_lock.json            # the comparability identity — never edit
├── health_checks_effective.yaml        # composed health policy, sha256-pinned — never edit
├── iter_001_hardware.json              # {run_name}_hardware.json — the GPU as the run saw it
├── plugins/
│   └── iter_001/{model_type}/          # the generated model code that actually ran
│                                       #   (+ description.md per plugin)
├── iter_001/                           # one directory per chain iteration
│   ├── manifest.json                   # iteration summary — what auto-resume reads
│   ├── task_config_snapshot.yaml       # the task config as it was at launch
│   ├── workflow_iter_001.json          # the iteration's workflow summary
│   ├── accumulated_findings_iter_001.json  # findings log (a log, not the carrier)
│   └── iteration_001/                  # workflow-internal (always 001 in chain mode)
│       ├── interpretation_iter_001.json        # per-node output records:
│       ├── ml_literature_review_iter_001.json  #   {node}_{run_name}.json — logs for
│       │                                       #   humans and recovery, never a channel
│       ├── attempt_001/                # one per proposal attempt
│       │   ├── proposal_iter_001.json
│       │   ├── implementor_iter_001.json
│       │   ├── validation_iter_001.json
│       │   ├── models/{model_name}.py  # the candidate as written
│       │   └── tests/
│       └── {model_name}/               # the tuner's working directory ↓
└── iter_002/ …                         # and so on, one record set per iteration
```

The tuner's working directory holds the compute-heavy residue of one model's
tuning rounds:

```
{model_name}/
├── summary_iter_001.json         # per-experiment summaries (what the dashboard reads)
├── run_output_iter_001.json      # the tuner node's full output record
├── run_config_iter_001.json      # the resolved run configuration
├── configs/ · records/           # per-round configs and records
└── cached_models/                # checkpoints and reusable artifacts
```

Three rules of thumb:

- **Records are logs.** Nodes never read each other's files — data flows
  through typed protocols in memory. Read records to understand a run; never
  wire anything to them.
- **Generated files are provenance.** Editing `run_invariants_lock.json` or
  `health_checks_effective.yaml` by hand produces a run whose recorded
  provenance is a lie. Change the source configs and start a new workspace
  instead.
- **`plugins/` is the actual science.** It contains the model code the agents
  wrote and ran. On resume, plugin classes from earlier iterations are
  restored from here automatically.

> ℹ **The cross-run library is per-user, not per-checkout.** Every run also
> *promotes* its generated models and losses (plus the capability index)
> into the **generated-capability library** —
> `$SIDERIUS_GENERATED_LIBRARY_DIR` if set (absolute path), else
> `~/.siderius/generated_library` — and preloads that library at the next
> startup. The repository checkout is **never written**: a pre-migration
> checkout's `agent_generated/` contents remain readable as a legacy
> fallback, but all new promotions land in the resolved library. Two
> workspaces under one user share the library by default; collaborators
> who want fully isolated candidate pools point
> `SIDERIUS_GENERATED_LIBRARY_DIR` at per-project roots. Each run's
> invariants lock records which library it resolved (`generated_library`,
> provenance-only).

## What resume actually restores

Auto-resume is **on by default**. Re-running the same command against the same
workspace:

1. asks the inspector (`scripts/inspect_run_state.py --next-iter`) for the
   first incomplete iteration, judged from each `iter_NNN/manifest.json`;
2. restores plugin classes from `plugins/iter_001 … iter_{N-1}` and seeds the
   new iteration with the prior iterations' output records — you do not pass
   them by hand;
3. restores the loop's carried memory: the accumulated key findings
   (chronological union) and the vocabulary link confirmations (latest wins).
   These are what make iteration N+1 smarter than iteration 1;
4. continues. If every iteration is already complete, it exits cleanly rather
   than redoing work.

```bash
--no_auto_resume     # do not inspect; start at iteration 1
--start_iter N       # pin the starting iteration manually
```

> Known wrinkle: the launcher's automatic `START_ITER` capture can be corrupted
> by plugin-loader output on stdout. If a resume starts at a wrong iteration,
> pin it with `--start_iter N`. See
> [persistence and resume](../agent-reference/mechanisms/persistence-and-resume.md).

`--no_auto_resume` does **not** bypass the invariants lock. A fresh start into
a used workspace is still validated against the lock — different settings still
refuse. New settings, new workspace.

## What the lock pins

At startup a run writes (or validates against)
`{workspace}/run_invariants_lock.json`. Today it pins:

- the resolved data scope,
- whether health gates are enabled,
- the sha256 of the effective health configuration.

Any resume, seed or reuse with one of these different fails at startup with a
message naming the mismatch. That failure is the guard working — see
[when it refuses](define-a-task.md#when-it-refuses) and the
[mechanism reference](../agent-reference/mechanisms/persistence-and-resume.md)
for the exact semantics.

Editing a **file-declared plugin** or the task health config between runs also
moves the pinned digest, so the workspace refuses to continue under silently
changed science. Same rule: new semantics, new workspace.

## Seeding a new workspace from an old run

`--seed_paths` passes prior run outputs into a *new* workspace as starting
evidence. It is optional — an empty list is a valid cold start, and cold start
is the required posture for gate runs. Seeds are subject to the same invariants
validation: a seed produced under a different scope is refused rather than
silently blended.

## Decision table

| you want to | do |
|---|---|
| continue an interrupted run | re-run the same command; auto-resume finds the spot |
| add more iterations to a finished run | same command with a larger `--num_iterations` |
| re-run with a different scope / health config / thresholds | **new workspace** |
| start clean but keep old evidence as input | new workspace + `--seed_paths` |
| force iteration 1 in a used workspace | `--no_auto_resume` (semantics must still match the lock) |
| inspect why a resume refused | read the startup error — it names the mismatched invariant |

---

## Next

- [Operating a run](operating-a-run.md) — budgets, scope, refusals
- [Troubleshooting](troubleshooting.md) — symptom-first diagnosis
- [Persistence and resume mechanism](../agent-reference/mechanisms/persistence-and-resume.md) — for implementers
