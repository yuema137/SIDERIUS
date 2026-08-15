# SIDERIUS Genericity Contract

**Status**: living contract — created 2026-07-28 (V19 PR 2, commit A).
**Authority**: this document defines the generic seams ONCE. Every in-passing
refactor converges to the seams named here. Inventing a new abstraction
requires updating this document FIRST (baseline rule,
`docs/design/v19_priorities.md` §1.3 guardrail 1).

## Why this exists

SIDERIUS is being reshaped from a TIDMAD-only repository into a generic
dataset/task/metric framework (operator decision 2026-07-27). The mechanism is
**gradual, in-passing refactoring, never a big-bang**: when a PR touches a
module, that PR also moves the touched module toward the seams below, in its
own commit.

Without a single written target, incremental refactors produce divergent
half-generic layers. That is what this file prevents.

Progress against the seams is tracked in
`docs/design/tidmad_coupling_ledger.md`.

---

## Seam 1 — Indexed dataset

**Status: partially implemented** (training filename template landed in V19
PR 2 commit A).

A dataset is an indexed collection of files, each holding a fixed number of
segments. The contract is:

```text
file_index -> (readable path, segment list)
```

resolved through `DatasetConfig` (`execute_tools/dataset_config.py`), never
through a filename literal inlined at the call site.

Implemented today:

| Concern | Contract surface |
|---|---|
| Physical constants | `DatasetConfig.psd_segment_length`, `.segments_per_file`, `.num_files`, `.sampling_frequency` |
| Training filename | `DatasetConfig.training_file_name(file_index)` — the ONLY place a training filename is built |
| Filename patterns | `DatasetConfig.training_file_pattern` / `.validation_file_pattern`, validated at construction (see below) |
| Which files a run may touch | `DataScope` (+ `resolve(dataset)`) |
| Which segments are in play | `SampleSet` = `{file_index: [segment_indices]}`, built by `execute_tools/sample_set_builder.py`, boundary-validated by `validate_sample_set` |

**Pattern validation is part of the contract.** `str.format()` does NOT raise
when a replacement field is absent, so a pattern like `training_file.h5` would
map every file index to the SAME file and corrupt an entire run with no error
raised anywhere. `DatasetConfig` therefore validates at construction that each
pattern (a) contains a usable `file_index` replacement field and (b) actually
formats with an integer index. A dataset whose pattern cannot distinguish
files is rejected before any file is opened.

**Not yet generic**: the training engine still reads the module-level `TIDMAD`
singleton. Commit A moved the *template* behind the config seam, not the
*choice of dataset*. Injecting the dataset instance is a later step on the
ladder; the coupling ledger tracks it.

**Porting target**: adding a second indexed dataset should be a
`configs/task_config.yaml`-level change (the already-declared porting entry
point), not a grep-and-replace across Python sources.

---

## Seam 2 — Configuration: proposed / override / resolved

**Status: first implementation in V19 PR 2 (ordering).**

Governing principle (operator, 2026-07-28):

> Configurable options may have a proposed value, an operator override, and a
> resolved execution value. Only the resolved value defines what ran. Every
> override must remain visible in provenance and downstream interpretation.

Concretely, for any option that adopts this pattern:

```text
default
  -> agent proposal      (intent; from the LLM plan, typed and validated)
  -> operator override   (control; chain-level, stable for the chain)
  -> resolved value      (fact; the ONLY thing execution consumes)

precedence: operator override > agent proposal > default
```

Rules that come with the pattern:

1. **One resolver per option.** Precedence is implemented exactly once.
   Workflow, node, and execution layers consume the resolver's output; they
   never re-derive precedence.
2. **Execution consumes resolved values only.** The execution layer does not
   know how a value was resolved.
3. **Provenance records all three levels** plus the resolution source, so a
   reviewer can reconstruct "agent proposed X, operator overrode with Y,
   executed Z, source S" from the record alone.
4. **Attribution uses resolved values.** Downstream interpretation and any
   feedback path must describe the resolved value as what ran. An overridden
   proposal is never reported as executed.
5. **Structural validity is checked at every intake**, even for a value that
   an override will discard — malformed agent output must not be silently
   masked. Checks that depend on resolution (e.g. against a resolved
   `DataScope`) apply to the resolved value.
6. **Chain locking applies to the override, not the resolution.** The operator
   override is chain control policy and is pinned in the run-invariants lock;
   the resolved value may legitimately vary per round when no override is
   active.

Reference implementation: data ordering
(`docs/design/v19_priorities/pr2_data_ordering.md` §3.6–§3.8).

### Permissions taxonomy

Adopting this pattern does NOT make an option agent-settable. Each option
declares its permissions explicitly:

| Class | Meaning |
|---|---|
| `agent-settable` | The agent may propose a value. |
| `operator-overridable` | An operator may force a value for a chain. |
| `chain-locked` | The controlling value is pinned in the run-invariants lock; changing it mid-chain is a violation. |
| `frozen` | Not configurable by agent or operator. Changing it requires a design decision and a written justification. |

Safety limits (resource budgets, watchdog policy) and the frozen scoring rules
do **not** become agent-settable merely because ordering is. The migration
inventory in the coupling ledger records the expected class for each candidate
option; the class is confirmed by the PR that migrates it.

---

## Seam 3 — Task pack

**Status: PLACEHOLDER** — partially anticipated by `configs/task_config.yaml`
(`task_description`, `forward_contract`), which is already injected into agent
system prompts. TIDMAD-worded prose still exists in node prompt modules (see
ledger).

To be defined by the first PR that genuinely needs a second task. Expected
scope: task description, forward contract, and task-specific prompt fragments
travelling as one pluggable unit rather than as literals spread across nodes.

**Do not invent this seam ad hoc** — update this section first.

---

## Seam 4 — Metric

**Status: DEFINED and LANDED — Step 06 (PR #213, merged `02f382eb`, 2026-08-15).**
`execute_tools/evaluation_metric.py`: `MetricSpec` (id · direction · aggregation
· transform · references · EXECUTABLE `ScoreabilityContract`), the
`EvaluationMetric` handle (scoreability BEFORE arithmetic), `MetricResult` /
`NotScoreableResult`; the frozen TIDMAD scorer is instance #1 derived under
Regime A (`derive_tidmad_metric`) and both production scoring routes go
through the handle. Contract test evidence: the strict direction-only rung
(C6a) and the broader different-metric rung (C6b) in
`tests/unit/execute_tools/test_step06_c6_stage_b_direction_rung.py`. Not yet
generic (owned later): direction-sensitive policy consumers (Step 07a / D1),
task-level metric declaration (Step 12), the lexical loss-id rule (temporary
debt — roadmap §20.8). Design: `docs/design/generic_framework_upgrade/step_06_metric_interface.md`.
The hard constraint below still holds.

**Frozen exception (baseline §1.3 guardrail 4)**: the TIDMAD score formula is
frozen and stays byte-identical, because published-paper comparability depends
on it. Metric pluggability means new metrics plug in **beside** it; it is
never rewritten. This applies to the `log_{5.27}` convention, the global
`s_max` ruler, and the grand-mean aggregation.

*(Historical expectation, superseded by Step 06: "to be defined by the first PR
that adds a second metric — name, per-file vector, scalar aggregate,
comparability rules". The landed interface makes the per-sample vector OPTIONAL
— a scalar-only metric is a first-class instance — and adds the executable
scoreability contract.)*

**Do not invent this seam ad hoc** — update this section first.

---

## Working rules

- **Contract tests, not claims.** Each genericized seam gets a unit test
  against a minimal synthetic second-dataset (or second-task/metric) fixture.
  A seam without such a test is "renamed", not "generic". Current evidence:
  `tests/unit/execute_tools/test_dataset_contract.py`.
- **In-passing, own commit.** The refactor rides on the normal development
  ladder, lives in its own commit within the PR, and is skippable for urgent
  fixes.
- **Bounded.** A PR genericizes the module it touches. Sites in other modules
  become ledger entries, not scope creep.
- **Update this doc first** when a new abstraction is needed.
