# Health gates

**Audience**: anyone about to trust a score.
**Answers**: "how do I know this output is valid enough to evaluate at all?"

---

## The question health gates answer

A metric answers **"how good is this result?"**

A health gate answers **"is this result structurally and behaviourally valid
enough to be worth scoring, and to keep spending compute on?"**

These are different questions, and conflating them is expensive. A model that
collapses to emitting a near-constant output will still produce a score. Sometimes
a *plausible* score. A research loop that reads that score as evidence will
happily propose a variation on a broken architecture and burn another few GPU-hours
finding out.

Health gates catch that class of failure at round boundaries — before the compute
is spent, and without polluting the scoring pipeline with validity logic.

> **A health gate PASS is not a scientific success.** It means "nothing detectably
> invalid". A model can pass every gate and be scientifically useless. The gates
> guard the *floor*, not the ceiling.

## What a check looks at

Checks look at the model's actual behaviour on a small peeked sample — the spread
of its outputs, whether it emits more than one distinct symbol, whether one class
dominates, whether the spectrum has collapsed. They are cheap by design; they run
at round boundaries, not inside scoring.

Nine checks ship with the framework. Some are inherently generic and reusable by
any task of the right shape:

| check | catches |
|---|---|
| `sample_dispersion_floor` | continuous outputs with no spread — a constant prediction |
| `categorical_distinct_symbols` | a classifier that has stopped using its label space |
| `categorical_dominant_fraction` | a classifier predicting one class nearly always |
| `output_diversity`, `output_std`, `per_file_output_std` | degenerate signal output |
| `amplitude_collapse`, `spectral_peak_ratio`, `pearson_dispersion` | signal-specific collapse modes |

A task declares which checks it wants, with what thresholds. It may also supply
its own checks as plugins — including from outside the repository.

## Four verdicts, and why `inapplicable` exists

| verdict | meaning |
|---|---|
| `passed` | evaluated, nothing wrong detected |
| `failed` | evaluated, the condition was violated |
| `inapplicable` | **the check's declared inputs do not exist for this task** — it was never evaluated |
| `error` | the check could not complete |

`inapplicable` is the interesting one. Before this existed, a check that had
nothing to look at reported `passed=True` with an explanatory sentence — so
"everything passed" could mean "nothing was checked". Now applicability is decided
*before* the check runs, and an inapplicable check **never blocks and never counts
as a pass**.

`error` on a blocking check **fails closed**. A check that cannot run is not
treated as a check that succeeded.

## Blocking versus observational

When you declare a check, you choose exactly one thing about it: its
**disposition**.

- **blocking** — a failure changes what the run does
- **observational** — a failure is recorded as evidence and changes nothing

That is the whole of your policy choice. When the gate runs, whether it
short-circuits, what action a failure produces, and how severity resolves between
simultaneous failures are all derived by the framework from that one word. This is
deliberate: it makes it impossible for a task and the framework to hold
contradictory opinions about what a failure means.

## What a blocking failure does

A fired gate resolves to one of two actions:

| action | effect |
|---|---|
| `continue` | proceed normally |
| `invalidate_round` | this round's result is not a valid candidate |

When several gates fire in one round, severity resolves
`invalidate_round` > `continue`.

> Two further actions, `skip_iter` and `skip_to_formal`, were RETIRED from
> the vocabulary for v1 (F-SCANC-1, operator decision packet v1,
> 2026-08-26). The tuner-side wire that would have acted on them was
> severed by the C7 decomposition, so they were declared-but-unreachable
> semantics; a config declaring either now refuses at validation instead
> of silently claiming loop control the runtime does not implement.

## Where the settings live

Two documents, two owners, and the split is the point:

- **Your thresholds** live in your task's health config — the roster, the numbers,
  the peek set, the prose explaining what a failure means scientifically. It is
  your file, anywhere on disk, named by your manifest's `task_health:` section.
- **What a failure does** lives in framework policy — role, cadence,
  short-circuit, actions. The framework ships its policy (with an
  observational variant a run selects via `--healthgate_mode observe_only`),
  and a run can substitute its own policy file with `--health_checks_config`.

Strictness is a decision you write in your own task config; consequences are
a run-level policy selection. Neither document can express the other's
concern.

At run start the two are composed into a single effective config that is written
into the workspace and hashed. That hash is pinned by the run's invariants lock,
so resuming a workspace with different health settings fails at startup rather
than silently producing incomparable results.

---

## Next

- [Task composition reference](../reference/task-composition.md) — declaring `task_health`
- [Health gate mechanism reference](../agent-reference/mechanisms/health-gates.md) — for implementers
- [Objectives and metrics](objectives-and-metrics.md) — the other kind of number
