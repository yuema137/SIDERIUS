# Design: V20 PR A — Wire Isolated Pre-flight into Production

- **Status**: **PHASE 1 COMPLETE — awaiting bounded GPU validation**
  2026-07-31. All five commits landed (§20.1); implementation record and
  test evidence in §20. Branch `feat/v20-pr-a-isolated-preflight`.
- **Parent plan**: `docs/design/v20_priorities.md` §6.6 (remediation),
  §13.1 requirement 1 (launch gate), §20.3 (PR scope)
- **Audited against**: `master` @ `6fa5a83` (2026-07-31)
- **Authorization**: implementation approved. GPU validation is **not**
  approved — the A5/A6 packages (§13) require separate operator approval
  before any GPU work runs. PR B must not start.

---

## 1. Problem statement

The production VRAM pre-flight runs **inside the chain's long-lived
parent process**, so that process creates a CUDA context and keeps the
allocator's reserved pool for the whole iteration. Training and
inference then hold their own copies in subprocesses, so the same
model's resources are held twice.

Confirmed on the V19 wave (parent doc §6.1):

```
two orchestration-only parents held 15,906 MiB — 55 % of all GPU memory
arch parent held 6,962 MiB unchanged for 3 minutes AFTER its child exited
parent exited → GPU returned to the 273 MiB baseline
```

`run_isolated_preflight` was built for exactly this, survived four
rounds of GPU validation, and has **zero production call sites**.

## 2. The audit changes the shape of this PR

§20.3 described PR A as "a call-site replacement, not a rewrite". The
audit shows that framing is **too optimistic**. Three material gaps
exist between what production consumes and what the isolated worker can
express. One of them is a hard blocker.

| # | Gap | Severity |
|---|---|---|
| 1 | Result contracts differ in shape: production consumes a 13-field rich dict; the worker returns a bounded typed disposition | Requires an adapter |
| 2 | `hardware_context` is passed in production and **not propagated** to the worker | Requires a serializable snapshot |
| 3 | Production may pass `vram_budget_gb=None` (the free×0.8 defensive mode); `IsolatedProbeSpec.vram_budget_gb` is `Field(gt=0.0)` and **cannot represent it** | **Hard blocker** — a direct swap would crash or silently change policy |

PR A is therefore **a compatibility adapter plus a call-site switch**,
not a substitution. It remains local — no algorithm, policy, schema or
subprocess architecture changes — but it is not one line.

## 3. Current production call graph

Exactly **one** production caller
(`nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py:2843`):

```
run_one_iteration.py                       (no torch import of its own)
 └ workflows/model_exploration.py:56        run_workflow()            in-process
    └ HyperparamTuningAgent.run()                                     in-process
       └ _run_skill("evaluate_vram_skill", sandbox, **active_params,
                    vram_budget_gb=chosen_vram_budget,
                    hardware_context=hardware_context)                 tune_agent:2843
          └ importlib.import_module(
                "agent.skills.evaluate_vram_skill.wrapper").run_skill(...)
             wrapper.py:49   import torch
             wrapper.py:225  cuda_context_bytes()   → CUDA context in the PARENT
             batch_resolver  searches batch sizes upward → high-water allocation
             wrapper.py:558  del model_for_train, …  → Python refs only
             (no torch.cuda.empty_cache() anywhere in the skill)
```

Everything else on the GPU is already a subprocess and already returns
its memory:

```
sandbox_executor → subprocess train_engine_sandbox.py    releases on exit
sandbox_executor → subprocess inference_single.py        releases on exit
```

**Target graph:**

```
HyperparamTuningAgent.run()                               in-process, CPU-only
 └ preflight adapter (new, parent side)
    └ run_isolated_preflight(spec)                        subprocess
       └ preflight_worker_main → wrapper.run_skill        all CUDA lives here
    ← bounded typed result
    → adapter reconstructs the legacy rich result
 → existing tuner consumer, unchanged
```

## 4. Production result contract — the 13 consumed fields

Every field read from `resource_check` in the tuner, with its call site
and what it drives:

| # | Field | Read at | Drives |
|---|---|---|---|
| 1 | `status` | 2849, 2864 | Control flow: `error` → raise; `schema_violation` → skip-record |
| 2 | `feasible` | 2914 | Control flow: `if not …get("feasible", True)` → OOM-risk path |
| 3 | `estimated_gb` | 2954 | `PhysicalRejection.estimated_gb` |
| 4 | `limit_gb` | 2953, 2997, 3945 | `PhysicalRejection.budget_gb`, `memory.vram_budget_gb` |
| 5 | `memory_killer` | 2924 | Killer-report detail on the rejection record |
| 6 | `suggestion` | 2955 | `PhysicalRejection.suggestion` — agent-facing |
| 7 | `verdict` | 2899, 2980 | `memory.discovery` text — agent-facing |
| 8 | `message` | 2849 | Error text in the raised `RuntimeError` |
| 9 | `violations` | 2865, 2870, 2878 | Schema-violation record; violating field list |
| 10 | `offending_config` | 2866 | Schema-violation record |
| 11 | `timeout_record` | 112 (`_raise_if_inconclusive`) | Inconclusive/timeout classification |
| 12 | `inference_batch` | downstream | Inference batch for the round |
| 13 | `inference_batch_uncalibrated` | 3004, 3950 | **Dead read — see §4.1** |

### 4.1 Pre-existing finding: `inference_batch_uncalibrated` is dead

`wrapper.py:34` records it as **removed**:

> `Removed: inference_batch_uncalibrated — obsolete now every batch is
> probed.`

The tuner still reads it in 6 places. `.get()` therefore always returns
`None` and both `if` branches are permanently dead.

This is **not** a PR A defect and PR A must **not** fix it — that would
be an unrelated change in a wiring PR. It is recorded here so the
adapter does not try to preserve a field the skill no longer produces.
Filed as **FU-A-1**.

## 5. Isolated-worker result contract

`preflight_worker_main._classify()` returns, by branch:

| Branch | Keys returned |
|---|---|
| `schema_violation` | `outcome`, `detail`, `schema_field`, `schema_message`, `phase` |
| `host_memory` | `outcome`, `detail`, `phase` |
| `cuda_oom` | `outcome`, `detail`, `phase` |
| `timeout` | `outcome`, `detail`, `phase`, `timeout_operation`, `timeout_budget_seconds`, `timeout_elapsed_seconds` |
| `inconclusive` | `outcome`, `detail`, `phase` |
| `error` | `outcome`, `detail`, `phase` |
| success / infeasible | `outcome`, `detail`, `phase`, `realized_parameter_count`, `estimated_gb`, `inference_batch` |

`PreflightOutcome` is the typed vocabulary:

```
COMPLETED_MEASUREMENT           MEASURED_CUDA_OOM
MEASURED_PEAK_ABOVE_VRAM_CAP    MEASURED_HARD_TIMEOUT
INCONCLUSIVE_MEASUREMENT        MEASURED_HOST_MEMORY_EXCEEDED
HOST_MEMORY_ALLOCATION_FAILURE  SCHEMA_REJECTED
PROBE_INFRASTRUCTURE_FAILURE
```

The worker's stated design principle (`preflight_worker_main.py:36`):
**"Only metadata crosses the boundary."** That principle is correct and
this PR preserves it — the adapter, not the worker, restores the rich
contract.

## 6. Field-by-field compatibility matrix

Classification: **M** measured in worker · **R** reconstructed in parent
· **P** presentation-only · **C** compatibility-only · **U** unsupported

| Production field | Worker source | Class | Adapter logic | Compatibility requirement |
|---|---|---|---|---|
| `status` | `outcome` | R | Map outcome → legacy status (§6.1) | Same control flow for every outcome |
| `feasible` | `outcome` | R | `False` iff outcome ∈ {`MEASURED_PEAK_ABOVE_VRAM_CAP`, `MEASURED_CUDA_OOM`} | Line 2914 branch must fire identically |
| `estimated_gb` | `estimated_gb` | M | Pass through | Numeric identity |
| `inference_batch` | `inference_batch` | M | Pass through | Numeric identity |
| `limit_gb` | — | R | Parent already holds `chosen_vram_budget`; reconstruct the effective cap | Must equal today's `min(usable_cap, budget)` |
| `num_params` | `realized_parameter_count` | M | Rename | Numeric identity |
| `timeout_record` | `timeout_operation` / `_budget_seconds` / `_elapsed_seconds` | M→R | Rebuild the `ProbeTimeoutRecord` shape | `_raise_if_inconclusive` behaves identically |
| `violations` | `schema_field`, `schema_message` | **U** | **Worker must be widened** (§6.2) | Violating-field list must not be lost |
| `offending_config` | — | **U** | **Worker must be widened** (§6.2) | Offending values must not be lost |
| `memory_killer` | — | **U** | **Worker must be widened, bounded** (§6.2) | Killer detail must not be lost |
| `message` | `detail` | R/P | Compose from outcome + detail | Error text may differ in wording, not in meaning |
| `suggestion` | — | P | Parent composes from outcome | Policy text stays in the parent |
| `verdict` | `detail` | P | Parent composes from outcome + measurements | Agent-facing text preserved in substance |
| `inference_batch_uncalibrated` | — | **C** | Do not reconstruct — dead (§4.1) | No behaviour change (both branches already dead) |

### 6.1 Outcome → legacy status mapping

Must be exhaustive; an unmapped outcome is a hard error, never a
silent default.

| `PreflightOutcome` | legacy `status` | `feasible` |
|---|---|---|
| `COMPLETED_MEASUREMENT` | `success` | `True` |
| `MEASURED_PEAK_ABOVE_VRAM_CAP` | `success` | **`False`** |
| `MEASURED_CUDA_OOM` | `success` | **`False`** |
| `SCHEMA_REJECTED` | `schema_violation` | n/a |
| `MEASURED_HARD_TIMEOUT` | `timeout` | n/a |
| `INCONCLUSIVE_MEASUREMENT` | `inconclusive` | n/a |
| `HOST_MEMORY_ALLOCATION_FAILURE` | `host_memory` | n/a |
| `MEASURED_HOST_MEMORY_EXCEEDED` | `host_memory` | n/a |
| `PROBE_INFRASTRUCTURE_FAILURE` | `error` | n/a |

**RESOLVED (D-A1, §16)**: keep both mapping to
`status="success", feasible=False` — PR A does not change control flow —
and additionally carry `preflight_outcome` so the typed cause survives
into artifacts.

### 6.2 The three fields the worker cannot express today

`violations`, `offending_config` and `memory_killer` have no worker
representation. Options:

- **Option 1 (recommended)** — widen the worker result with these three
  fields under an explicit **size bound** (proposal: 8 KiB serialized,
  truncated with a `truncated: true` marker). Keeps the parent CPU-only
  and preserves every field.
- **Option 2** — drop them and accept degraded records. Rejected:
  §20.3 requires that no field disappear silently, and
  `offending_config` is what makes a schema rejection actionable for
  the agent.
- **Option 3** — re-derive them in the parent. Rejected: it would
  require the parent to construct the candidate, which is the entire
  defect this PR removes.

**RESOLVED (D-A2, §16)**: approved, 8 KiB combined, structure preserved before free text.

## 7. `hardware_context` propagation

`HardwareContext` is a Pydantic model, so it *is* serializable — but the
worker needs only a small subset. Fields actually touched by
`wrapper.py`:

```
usable_cap_bytes    total_memory_bytes    device_name
usable_cap_gb       total_memory_gb       device_available
```

**Proposal**: add a bounded `HardwareSnapshot` to `IsolatedProbeSpec`
carrying exactly those six values plus the hardware fingerprint used for
calibration identity. Do not pass the full object.

**RESOLVED (D-A3, §16)**: approved, plus `device_index` and
`cuda_visible_devices` — device selection is currently implicit and
inherited rather than asserted. No `discover()` fallback in production;
an absent snapshot is a hard error.

## 8. The `vram_budget_gb=None` blocker

```python
# tune_agent:2829
chosen_vram_budget = trial_vram_budget if plan.is_trial else formal_vram_budget
# may be None → "the skill still runs but falls back to free×0.8
#                defensive behaviour (no operator ceiling)"

# isolated_probe.py:132
vram_budget_gb: float = Field(gt=0.0)     # cannot represent None
```

A direct swap would either raise a `ValidationError` on every
unbudgeted round, or require inventing a budget — silently converting
"no operator ceiling" into a specific ceiling. Both change policy.

**Proposal**: widen `IsolatedProbeSpec.vram_budget_gb` to
`float | None` with `gt=0.0` when present, and have the worker apply the
same free×0.8 defensive path the in-process skill applies today.

**RESOLVED (D-A4, §16)**: approved. The worker must not recompute a cap
when the budget is `None` — the parent resolves `hardware_context` and
passes the frozen `usable_cap_bytes`/`usable_cap_gb` in the snapshot.

This is an **IPC contract widening, not a persistent-schema migration**:
`IsolatedProbeSpec` is serialized only to a transient `<result>.spec.json`
for the worker it launches, appears in no manifest, and has no reader
outside validation scripts and tests (§16.1 B).

## 9. Hard invariant — no silent fallback

> **An isolated-worker failure must never silently fall back to the
> in-process CUDA pre-flight path.**

If the fallback existed, the original defect would return on precisely
the exception paths nobody watches. `PROBE_INFRASTRUCTURE_FAILURE` maps
to `status="error"`, which the tuner already raises on (line 2849) and
already classifies as infrastructure, not candidate, failure.

The old in-process entry point stays importable for unit tests and
standalone tooling, but a guardrail test asserts the formal production
path cannot reach it (§12 test 2 and test 10).

## 10. Proof that the parent stays CPU-only

Three independent checks, because a single one could pass by accident:

1. **Static** — no module reachable from the production pre-flight path
   imports `torch` in the parent.
2. **Runtime** — after a full pre-flight, the parent's CUDA state is
   unchanged from what it was *before* the pre-flight. **Corrected
   2026-08-01 — see §21.0.** This was originally written as
   "`torch.cuda.is_initialized()` is `False` in the parent", which is
   unachievable: `core/hardware_context.discover()` initializes CUDA in
   the tuner parent at `ml_hyperparameter_tune_agent.py:2101`, before
   any pre-flight runs. The shipped guardrail
   (`test_preflight_production_reachability.py:123`) asserts the
   strictly weaker and still-correct claim that importing the *adapter
   module* leaves `torch` unimported.
3. **Observational** — during the §13 GPU validation, the parent's
   driver-visible footprint does not **grow** across a pre-flight.
   **Corrected 2026-08-01 — see §21.0.** Originally "the parent PID
   never appears in `nvidia-smi --query-compute-apps`", which the same
   `hardware_context` finding refutes: the parent holds a bare CUDA
   context for its whole life regardless of PR A.

Check 3 is the one that actually failed in V19 and the only one that
exercises the real path. Its corrected form is a **delta**, not an
absence, and is therefore self-calibrating — it needs no prior estimate
of what a bare CUDA context costs on the host. See §21.9.

## 11. Scope and non-goals

**Exact proposed changed files:**

| File | Change | Decision gate |
|---|---|---|
| `agent/skills/evaluate_vram_skill/preflight_adapter.py` | **new** — parent-side adapter: outcome→legacy mapping, timeout-record rebuild, message/suggestion/verdict composition | — |
| `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py` | call boundary at :2843 only — `_run_skill("evaluate_vram_skill", …)` → adapter. Consumer logic untouched | — |
| `agent/skills/evaluate_vram_skill/isolated_probe.py` | `IsolatedProbeSpec.vram_budget_gb` → `float \| None`; add `HardwareSnapshot` | **D-A3, D-A4** |
| `agent/skills/evaluate_vram_skill/preflight_worker_main.py` | `_classify()` returns `violations`, `offending_config`, `memory_killer` under the size bound; accepts the snapshot and the nullable budget | **D-A2** |
| `tests/unit/agent/evaluate_vram_skill/test_preflight_adapter.py` | **new** — the §12 equivalence and mapping suite |  — |
| `tests/unit/guardrails/test_preflight_production_reachability.py` | **new** — §12 tests 1, 2, 8, 10 | — |
| `sdsc_submission_scripts/run_one_iteration.py` *(manifest only)* | record `preflight_execution_mode: isolated_subprocess` | — |
| `docs/design/v20_priorities/pr_a_isolated_preflight_wiring.md` | implementation record updated as checkpoints complete | — |

Four of the eight are new files; three of the four edits are confined to
a single function each. No file outside this list is touched.

**Changed, in prose**: the production call boundary; a new parent-side
adapter module; a bounded `HardwareSnapshot`; three widened worker result
fields; the `vram_budget_gb: float | None` widening; reachability and
equivalence tests; a manifest field recording the pre-flight execution
mode.

**Not changed**: pre-flight algorithms; batch-search policy; candidate
config; typed dispositions; capacity/downsizing authority; timeout
values; host-memory RSS protection; the 12 GiB cap; the 28 GiB pair
ceiling; training and inference subprocesses; queue and watchdog;
HealthGate; calibration; agent prompts; the tuner's consumer logic.

`torch.cuda.empty_cache()` is not used as the repair.

## 12. Deterministic validation

1. formal production reaches `run_isolated_preflight`;
2. formal production **cannot** reach the in-process GPU pre-flight;
3. inputs are preserved exactly (normalized config equality);
4. every `PreflightOutcome` maps to the legacy status/feasible pair in
   §6.1 — table-driven, exhaustive, unmapped outcome raises;
5. `violations` / `offending_config` / `memory_killer` survive the
   boundary, including the truncation marker at the size bound;
6. `timeout_record` reconstruction makes `_raise_if_inconclusive`
   behave identically;
7. candidate and infrastructure failure classes are unchanged;
8. the parent constructs no candidate model and initializes no CUDA;
9. training and inference subprocess paths are unchanged;
10. a regression test **fails** if production is rewired to the
    in-process path;
11. `vram_budget_gb=None` produces the same effective cap as today.

## 13. Bounded real validation

**Phase A5 — single chain.** Measure parent driver-visible GPU memory;
pre-flight worker peak; GPU after worker exit; training child peak;
inference child peak; chain process-tree aggregate; allocated, reserved
and driver-visible peaks; host RSS peak; orphan state.

```
pass:  parent footprint does NOT grow across a pre-flight   (revised — §21.9)
       worker releases GPU memory on exit
       no overlap between pre-flight and training
       no orphan
       scientific result path unchanged
```

> **Revised 2026-08-01.** The first criterion previously read "parent
> absent from nvidia-smi". §21.0 shows that is unachievable for reasons
> unrelated to PR A. The executable criteria live in §21.9; this block
> is retained as the summary.

**Do not assume the chain fits under 12 GiB — measure it.** V19's
17.74 GiB was taken under contention and does not bound a standalone run.

**Phase A6 — dual chain.** Bounded arch/loss pair. Pass when both
parents stay CPU-only, pair aggregate stays clear of the 28 GiB ceiling
and 30,000 MiB quota, no contention-attributable candidate evidence
appears, and no processes accumulate.

Neither phase runs without explicit operator approval.

## 14. Stop conditions

Stop for operator review if: the adapter cannot preserve a consumed
field; an outcome has no faithful legacy mapping; the parent still
initializes CUDA after wiring; `vram_budget_gb=None` cannot be handled
without a policy change; the size bound in §6.2 truncates real data in
practice; or validation reveals a lifecycle problem beyond pre-flight.

## 15. Merge criteria

All checkpoints pass; §12 deterministic suite green; A5 and A6 pass, or
A6 clearly demonstrates the need for PR B; production reachability
proven; no unrelated workflow change included; §20.11 template filled.

## 16. Operator decisions — RESOLVED 2026-07-31

All five approved, three with binding refinements.

### D-A1 — APPROVED: keep the legacy control flow, preserve the typed cause

`MEASURED_PEAK_ABOVE_VRAM_CAP` and `MEASURED_CUDA_OOM` both continue to
map to `status="success", feasible=False`. PR A must not change control
flow while wiring.

**Binding addition**: the adapter result must also carry the typed cause
so artifacts and downstream consumers can tell the two apart:

```
preflight_outcome: <PreflightOutcome>      ← new, additive
```

```
legacy control flow unchanged  +  typed cause preserved
```

Whether the two causes should ever drive different policy is deferred to
PR B or a dedicated follow-up. **Not decided in PR A.**

### D-A2 — APPROVED: Option 1, bounded at 8 KiB

`violations`, `offending_config` and `memory_killer` cross the boundary,
subject to:

- **8 KiB combined** serialized size;
- truncation on overflow, with `truncated: true`;
- truncation must never break JSON or schema validity;
- **structured core fields are preserved first**; free-text is truncated
  before structure — never an arbitrary byte cut;
- never return tensors, model objects, state dicts, or full tracebacks.

### D-A3 — APPROVED: snapshot, with device identity, no production discovery

```
usable_cap_bytes      total_memory_bytes     device_name
usable_cap_gb         total_memory_gb        device_available
hardware_fingerprint
device_index          cuda_visible_devices    ← see audit below
```

**Audit result — device identity is currently implicit.** Neither
`wrapper.py` nor `preflight_worker_main.py` contains any `cuda:N`,
`torch.cuda.set_device`, or explicit device selection. Both rely on the
default device of whatever `CUDA_VISIBLE_DEVICES` exposes. That happens
to work because the worker inherits the parent's environment, but it is
inherited, not asserted — on a multi-GPU host a mismatch would be
silent. `device_index` and `cuda_visible_devices` therefore join the
snapshot, and the worker asserts the device it lands on matches.

**Production**: a missing snapshot is a hard infrastructure/configuration
error. No silent `discover()`. A parent and a worker that independently
discover hardware can disagree about budget, device or fingerprint —
exactly the class of divergence this PR exists to remove.

**Standalone tooling** may opt into discovery explicitly, in a
non-production mode, with the provenance recorded.

### D-A4 — APPROVED: nullable budget, resolved by the parent

```
float > 0   → operator-provided ceiling
None        → no explicit operator ceiling
              → the same defensive effective cap production uses today
```

**Binding refinement**: the worker must **not** re-discover and
recompute a cap when the budget is `None`. The parent resolves
`hardware_context` first and passes the **frozen** `usable_cap_bytes` /
`usable_cap_gb` in the snapshot; the worker uses that frozen cap.

This keeps the free×0.8 defensive semantics, makes parent and worker
share one resolved cap, removes any need for production discovery, and
makes the result reproducible and auditable.

Manifest records all three:

```
operator_vram_budget_gb:  null
effective_vram_limit_gb:  <resolved>
effective_limit_source:   hardware_snapshot_defensive_cap
```

### D-A5 — CONFIRMED: dead field untouched

`inference_batch_uncalibrated` stays out of PR A as **FU-A-1**. It is
already a dead read, current behaviour does not change, and removing six
call sites in a wiring PR is unrelated cleanup that widens review.

**The adapter must not fabricate the field.** `.get()` continues to
return `None`.

### 16.1 Additional binding requirements from review

**A — the adapter formats, it does not decide.** Rebuilding `message`,
`suggestion` and `verdict` in the parent is compatibility formatting,
never a new decision layer. Reuse the wrapper's existing pure text
construction, or first extract a shared CPU-only formatter used by both
paths. Two independently-drifting text generators would recreate the
divergence this PR removes, and would do it where nobody is looking.

**B — `IsolatedProbeSpec` is an IPC contract, not a persistent schema.**
The earlier §8 wording was wrong. Audit result:

- `isolated_probe.py:340,343` writes `<result>.spec.json` beside the
  worker result, consumed only by the worker it launches;
- it is **not** written into any manifest;
- outside validation scripts and tests there is **no reader**.

So widening `vram_budget_gb` is an **IPC/schema contract widening**, not
a historical-data migration. Compatibility tests are still required —
the validation scripts construct the spec — but this must not be
described as persistent-schema migration.

## 17. Follow-ups filed, not fixed here

- **FU-A-1** — the tuner reads `inference_batch_uncalibrated` in 6
  places; the wrapper removed it. Both branches are permanently dead.
- **FU-A-2** — phase-level RSS peaks from the worker (parent doc §6.6)
  are cheap to add once the worker is on the production path, but they
  are telemetry, not wiring.

## 18. §20.11 review template

```
Problem statement:        §1
Confirmed evidence:       §1, parent doc §6.1
Scope:                    §11
Out of scope:             §11
Production callers:       §3 — exactly one
Persistent schema impact: §8 (vram_budget_gb), §6.2 (worker result)
Backward compatibility:   §6 matrix; old entry point retained for tests
Implementation checkpoints: parent doc §20.3 A1-A4
Deterministic tests:      §12
Layer-2 evaluation:       n/a — no agent-behaviour claim
Bounded real validation:  §13
Failure classification:   §6.1 — unchanged by construction
Attribution:              n/a — PR B scope
Artifacts:                compatibility table, A5/A6 measurements, manifest mode field
Stop conditions:          §14
Merge criteria:           §15
Dependencies:             none — entry point of the ladder
Operator decisions:       §16 (D-A1 … D-A5)
```

---

## 19. Commit plan

Five commits. Each is independently reviewable and carries no unrelated
cleanup. `[ ]` is not done; `[x]` is done **and verified with recorded
evidence** — never marked from intent.

> **Template scope note.** The standard this plan follows includes rules
> written for PR 2 (data ordering): full-permutation `file_order`,
> `shuffle` as the default path, and ordering kept separate from loader
> partitioning. **None apply to PR A**, which changes no data ordering
> and no loader. They are recorded as inapplicable rather than
> reinterpreted, so that a later reader does not look for ordering
> evidence that was never in scope.

### A-C1 — Widen the IPC contract (`isolated_probe.py`)

**Status: [x] implemented, uncommitted**

**1. Goal.** Let the spec express the two things production needs and the
worker currently cannot receive: a frozen hardware snapshot, and
`vram_budget_gb=None` meaning "no operator ceiling". Without this the
call-site switch cannot happen at all (§8), so it is the first commit and
belongs alone: it is a contract change with no behaviour change.

**2. Scope.** `agent/skills/evaluate_vram_skill/isolated_probe.py` —
new `HardwareSnapshot`; `IsolatedProbeSpec.vram_budget_gb` →
`float | None`; new `hardware` field; new `effective_cap_gb()` and
`effective_limit_source()`; one call site changed to
`spec.effective_cap_gb()`.

*Non-goals*: no worker behaviour, no adapter, no production call site.
*Depends on*: nothing.

**3. Implementation plan**

- [x] Add `HardwareSnapshot` with the D-A3 field list including
      `device_index` and `cuda_visible_devices`
- [x] Widen `vram_budget_gb` to `float | None` with `gt=0.0` when present
- [x] Add the optional `hardware` field
- [x] Add `effective_cap_gb()` — operator ceiling, else frozen defensive
      cap, else `None`
- [x] Add `effective_limit_source()` for manifest provenance
- [x] Point `IsolatedProbeResult.vram_cap_gb` at `effective_cap_gb()`
- [x] Docstring records that this is an IPC contract, not a persisted
      artifact (§16.1 B)

**4. Validation plan**

- [x] Existing suite unchanged: `tests/unit/agent/evaluate_vram_skill/`
- [ ] Unit: `effective_cap_gb()` returns the operator budget when set
- [ ] Unit: returns the frozen `usable_cap_gb` when budget is `None`
- [ ] Unit: returns `None` when both are absent
- [ ] Unit: `effective_limit_source()` returns each of the three values
- [ ] Negative: `vram_budget_gb=0` and `-1` still rejected by `gt=0.0`
- [ ] Negative: `HardwareSnapshot` rejects `usable_cap_bytes<=0` and an
      empty `device_name`
- [ ] Backward-compat: a spec built the old way (positional budget, no
      `hardware`) still validates and behaves identically

**5. Acceptance criteria**

- `IsolatedProbeSpec(vram_budget_gb=None, hardware=<snapshot>)`
  validates, and `effective_cap_gb()` equals `snapshot.usable_cap_gb`
  **to full float equality**, not approximately.
- A spec with `vram_budget_gb=12.0` yields `effective_cap_gb() == 12.0`
  regardless of the snapshot's cap.
- `effective_limit_source()` returns exactly one of
  `operator_vram_budget` / `hardware_snapshot_defensive_cap` /
  `unbounded_no_snapshot`.
- Every previously passing test in
  `tests/unit/agent/evaluate_vram_skill/` still passes, same count.

**6. Failure and edge cases**

| Case | Required behaviour |
|---|---|
| `vram_budget_gb=0` or negative | **Stop** — Pydantic rejects; a zero cap is not "no cap" |
| `hardware` absent **and** budget `None` | `effective_cap_gb()` → `None`; the worker is unbounded. Legal only for standalone tooling; production forbids it at the adapter (A-C3) |
| Snapshot with `device_available=False` | Carried through; the skill's CPU-mode path already handles it |
| Legacy spec without `hardware` | Validates — the field defaults to `None`; no migration needed since nothing persists it |

**7. Verification commands and evidence**

```bash
.venv/bin/python -m pytest tests/unit/agent/evaluate_vram_skill/ -q
```

- [x] **247 passed in 16.25 s** (baseline, before the change)
- [x] **247 passed in 12.38 s** for `test_isolated_preflight.py` subset:
      81 passed
- [ ] New unit tests for the seven cases above — not yet written

**8. Commit boundary.** Independently reviewable: a schema widening with
no consumer. Contains no adapter, no call-site change, no cleanup.
Diff summary and staged file list to be shown before committing.

### A-C2 — Worker consumes the snapshot and returns bounded rich fields

**Status: [x] implemented, uncommitted**

**1. Goal.** Make the worker able to produce everything the parent will
need, so A-C3 has something to adapt. Separate from A-C1 because that
was a contract and this is behaviour; separate from A-C3 because this
runs in the child and that runs in the parent — a regression in either
must be attributable.

**2. Scope.** `agent/skills/evaluate_vram_skill/preflight_worker_main.py`
— bounded rich-field serialization; snapshot consumption; nullable-budget
resolution; `_classify()` carries `violations`, `offending_config`,
`memory_killer`, `limit_gb`, `dominant_phase`, `verdict`, `suggestion`.

*Non-goals*: no change to what the skill measures, no change to the
disposition vocabulary, no parent-side code.
*Depends on*: A-C1.

**3. Implementation plan**

- [x] `RICH_FIELD_BUDGET_BYTES = 8 KiB`; `_clip_text`, `_shrink`,
      `_bounded_rich_fields`
- [x] Truncation shortens lists **before** dropping fields, records
      `<field>_omitted_count`, and sets `truncated: true`
- [x] Consume `spec["hardware"]`, pass the snapshot as `hardware_context`
- [x] Resolve `None` budget from the frozen `usable_cap_gb`; never
      re-discover
- [x] Log the device index and `CUDA_VISIBLE_DEVICES`
- [x] Log the effective limit and its source
- [x] `_classify()` schema branch returns `violations` +
      `offending_config`
- [x] `_classify()` infeasible branch returns `memory_killer`
- [x] `common` carries `limit_gb`, `dominant_phase`, and **forwards**
      `verdict` / `suggestion` (§16.1 A — one generator, no drift)
- [ ] Assert the device the worker lands on matches
      `snapshot.device_index` (D-A3 requires the assertion, not only the
      log)

**4. Validation plan**

- [x] Existing suite unchanged
- [x] Ad-hoc self-test of `_bounded_rich_fields` (evidence in §7)
- [ ] Unit: small payload passes through untouched, no `truncated` key
- [ ] Unit: 40×900-char violations → list halved until it fits, count
      recorded, JSON valid, first entry keeps all its keys
- [ ] Unit: a single oversized dict → replaced by an explicit marker,
      never silently removed
- [ ] Unit: `None` / `{}` / `[]` inputs produce `{}`
- [ ] Unit: budget `None` + snapshot → `run_skill` receives
      `usable_cap_gb`
- [ ] Unit: budget set + snapshot → `run_skill` receives the budget
- [ ] Negative: no tensor, state dict or traceback object can reach the
      payload (assert `json.dumps` needs no `default=` fallback for
      non-primitives)
- [ ] Device-mismatch test for the assertion above

**5. Acceptance criteria**

- For any input, `len(json.dumps(rich_fields).encode()) <= 8192`.
- Truncation always leaves `json.loads` succeeding.
- When truncation occurs, `truncated is True` **and** at least one
  structured entry survives whenever the input had one.
- With `vram_budget_gb=None`, the value passed to `run_skill` equals
  `snapshot.usable_cap_gb` exactly.
- `verdict` and `suggestion` in the worker result are byte-identical to
  the skill's own strings, truncated only at 400 chars.

**6. Failure and edge cases**

| Case | Required behaviour |
|---|---|
| Rich fields exceed 8 KiB | Trim lists, then mark dropped fields; **never** exceed the bound, never emit invalid JSON |
| Non-serializable object in a rich field | `default=str` keeps the write atomic; the negative test asserts this path is not reached in practice |
| Snapshot absent | Worker proceeds unbounded — legal for tooling, blocked for production in A-C3 |
| Worker lands on a different device than the snapshot | **Stop** — infrastructure error, not a candidate result |

**7. Verification commands and evidence**

```bash
.venv/bin/python -m pytest tests/unit/agent/evaluate_vram_skill/ -q
```

- [x] **247 passed in 16.47 s** after the change (unchanged count)
- [x] Self-test: 40 violations × 900 chars → 5,252 bytes ≤ 8,192, 10 kept
      with keys `['loc','msg','type']`, `violations_omitted_count: 30`,
      JSON valid
- [x] Self-test: oversized nested dict → 81 bytes, explicit marker
- [x] Self-test: empty input → `{}`
- [ ] Formal unit tests replacing the ad-hoc self-tests — **the self-test
      is evidence the code works, not a substitute for a committed test**

**8. Commit boundary.** Child-side only. No parent code, no call site.

### A-C3 — Parent-side compatibility adapter

**Status: [ ] not started**

**1. Goal.** Rebuild the legacy 13-field contract from the worker's typed
result so the tuner's consumer needs no change. Separate commit because
it is the only new decision surface in PR A and deserves review on its
own.

**2. Scope.** New
`agent/skills/evaluate_vram_skill/preflight_adapter.py`; new
`tests/unit/agent/evaluate_vram_skill/test_preflight_adapter.py`.

*Non-goals*: it must **not** generate agent-facing text (§16.1 A — the
worker forwards it), must not decide policy, must not import torch, and
must not construct the candidate.
*Depends on*: A-C1, A-C2.

**3. Implementation plan**

- [ ] `build_hardware_snapshot(hardware_context) -> HardwareSnapshot`
- [ ] `run_production_preflight(...)` — build spec, call
      `run_isolated_preflight`, adapt result
- [ ] Exhaustive outcome → `(status, feasible)` map per §6.1, as a
      module-level table
- [ ] **Unmapped outcome raises** — no default branch
- [ ] Carry `preflight_outcome` additively (D-A1)
- [ ] Rebuild `timeout_record` from the three `timeout_*` fields
- [ ] Pass through `estimated_gb`, `inference_batch`, `limit_gb`,
      `num_params`, `verdict`, `suggestion`, `violations`,
      `offending_config`, `memory_killer`
- [ ] Reject a missing snapshot in production mode (D-A3)
- [ ] Do **not** synthesize `inference_batch_uncalibrated` (D-A5)
- [ ] Module docstring states the no-silent-fallback invariant (§9)

**4. Validation plan**

- [ ] Unit: every `PreflightOutcome` maps to the §6.1 pair — table-driven
      over `get_args(PreflightOutcome)`, so a new outcome fails the test
- [ ] Unit: an unmapped outcome raises rather than defaulting
- [ ] Unit: `preflight_outcome` present on every adapted result
- [ ] Unit: `timeout_record` reconstruction satisfies
      `_raise_if_inconclusive`
- [ ] Unit: rich fields survive; `truncated` is propagated
- [ ] Unit: `inference_batch_uncalibrated` is absent, `.get()` → `None`
- [ ] Unit: production mode without a snapshot raises
- [ ] Guardrail: the adapter module imports no torch
      (`sys.modules` assertion after import)
- [ ] Parity: for a recorded in-process result fixture, the adapted
      result has the same `status`, `feasible`, and numeric fields

**5. Acceptance criteria**

- `set(get_args(PreflightOutcome))` equals the mapping table's key set —
  proven by test, not by inspection.
- For each of the nine outcomes the adapted `(status, feasible)` equals
  the §6.1 row exactly.
- `import agent.skills.evaluate_vram_skill.preflight_adapter` leaves
  `"torch" not in sys.modules` in a fresh interpreter.
- The adapter contains no string literal that is also produced by the
  worker — i.e. it forwards text, never composes it.

**6. Failure and edge cases**

| Case | Required behaviour |
|---|---|
| Worker returns an unknown `outcome` | **Stop** — raise; a silent default would hide a contract drift |
| Worker result file missing or unparsable | Map to `status="error"` → the tuner already raises (line 2849) |
| `PROBE_INFRASTRUCTURE_FAILURE` | `status="error"`; **never** retried in-process (§9) |
| Snapshot missing in production | **Stop** — configuration error |
| Rich fields truncated | Pass through with `truncated` intact; never re-request |

**7. Verification commands and evidence**

```bash
.venv/bin/python -m pytest tests/unit/agent/evaluate_vram_skill/test_preflight_adapter.py -q
.venv/bin/python -m pytest tests/unit/agent/evaluate_vram_skill/ -q
```

- [ ] Counts and wall time to be recorded here after the run

**8. Commit boundary.** New module plus its tests. No production caller
is switched yet, so this commit changes no runtime behaviour.

### A-C4 — Switch the production call site

**Status: [ ] not started**

**1. Goal.** Make production use the adapter. Isolated in its own commit
because it is the single line whose revert restores previous behaviour —
the rollback story must be one commit, not a bisect.

**2. Scope.**
`nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py`
around line 2843; `sdsc_submission_scripts/run_one_iteration.py` for the
manifest fields.

*Non-goals*: the tuner's consumer logic below the call site is untouched;
no admission-policy change; the old `_run_skill` entry point remains for
tests and tooling.
*Depends on*: A-C3.

**3. Implementation plan**

- [ ] Inspect the exact call site again before editing — the audit is
      from `6fa5a83`
- [ ] Replace `_run_skill("evaluate_vram_skill", …)` with the adapter
- [ ] Thread `hardware_context` into `build_hardware_snapshot`
- [x] Record `preflight_execution_mode: isolated_subprocess` in the
      manifest — **done 2026-08-01**, after A6. Stamped on *every*
      manifest branch (completed / no_records / failed), beside
      `health_feedback_policy` at `run_one_iteration.py:479`, for the
      same reason: a crashed iteration is exactly when an auditor needs
      to know how the pre-flight ran. The value is imported from
      `preflight_adapter.PREFLIGHT_EXECUTION_MODE` rather than written
      as a literal, so the manifest cannot claim a mechanism the build
      does not ship. 6 tests (4 branches parametrized, plus identity and
      JSON round-trip); 1,928 passed across the affected suites
- [ ] Record `operator_vram_budget_gb`, `effective_vram_limit_gb`,
      `effective_limit_source` (D-A4)
- [ ] Confirm no other line in the tuner is modified

**4. Validation plan**

- [ ] Unit: the tuner's existing pseudo-mode tests still pass unchanged
- [ ] Unit: the call site reaches `run_isolated_preflight` (mock
      assertion)
- [ ] Unit: `vram_budget_gb=None` round produces
      `effective_limit_source == "hardware_snapshot_defensive_cap"`
- [ ] Integration (pseudo): a full pseudo iteration completes with the
      adapter in place
- [ ] Backward-compat: records written by a pseudo run have the same
      keys as before, plus the additive ones

**5. Acceptance criteria**

- `git diff` for the tuner touches **only** the call-site block.
- A pseudo-mode iteration produces a record whose `memory` and
  `PhysicalRejection` fields are key-for-key identical to a pre-change
  run, plus `preflight_outcome`.
- The manifest contains all four new provenance fields with non-null
  values on a budgeted round.

**6. Failure and edge cases**

| Case | Required behaviour |
|---|---|
| Adapter raises | Propagates as today's `RuntimeError` — no in-process retry |
| `hardware_context` is `None` at the call site | **Stop** — production requires it (D-A3) |
| Worker times out | `MEASURED_HARD_TIMEOUT` → existing `_raise_if_inconclusive` path |

**7. Verification commands and evidence**

```bash
.venv/bin/python -m pytest tests/unit/agent/tune_ml_hyperparam_agent/ -q
.venv/bin/python -m pytest tests/integration/ -q -k pseudo
```

- [ ] Counts and wall time to be recorded here

**8. Commit boundary.** The behaviour switch, alone and revertible.

### A-C5 — Reachability guardrails and doc sync

**Status: [ ] not started**

**1. Goal.** Make the defect this PR fixes impossible to reintroduce
silently. Last commit because the guardrails must assert against the
final wiring.

**2. Scope.** New
`tests/unit/guardrails/test_preflight_production_reachability.py`; this
design document's progress markers; `docs/` node/skill docs touched by
the change (operator rule, 2026-07-28).

*Depends on*: A-C4.

**3. Implementation plan**

- [ ] Test: formal production reaches `run_isolated_preflight`
- [ ] Test: formal production **cannot** reach in-process GPU pre-flight
      — static assertion over the tuner source
- [ ] Test: the parent constructs no candidate model
- [ ] Test: the parent initializes no CUDA
- [ ] Test: **fails** if the call site is reverted to `_run_skill`
- [ ] Update `nodes/ml_hyperparameter_tune_agent/*.md` and any operator
      doc naming the pre-flight path
- [ ] Mark this document's checkboxes with recorded evidence

**4. Validation plan**

- [ ] The revert test is proven by temporarily reverting the call site
      and observing the failure — **a guardrail never asserted to fail is
      not a guardrail**
- [ ] Full affected-suite run
- [ ] `ruff check`, `ruff format --check`, `pyright` strict

**5. Acceptance criteria**

- Reverting A-C4 locally causes at least one guardrail test to fail, and
  that failure is recorded here.
- CI green on all four checks.
- Every `[ ]` in §19 is either `[x]` with evidence or explicitly deferred
  with a reason.

**6. Failure and edge cases**

| Case | Required behaviour |
|---|---|
| Guardrail passes on a reverted call site | The guardrail is wrong — fix it before merging |
| A test needs a GPU | Not permitted in this commit; GPU work is §13 and needs approval |

**7. Verification commands and evidence**

```bash
.venv/bin/python -m pytest tests/unit/guardrails/ -q
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

- [ ] Counts, wall time, and the revert-test evidence to be recorded here

**8. Commit boundary.** Tests and docs only. No production code.

### 19.1 After the five commits

- [ ] Push branch, open PR, CI green
- [ ] Fill the §18 review template in the PR description
- [ ] Submit the **A5 single-chain GPU validation package** for operator
      approval — §13. **No GPU work runs before that approval.**
- [ ] A6 dual-chain validation, after A5 passes
- [ ] PR B is not started

---

## 20. Implementation record

### 20.1 Commits

| Commit | SHA | Contents |
|---|---|---|
| A-C1 + A-C2 + A-C3 | `0c13c47` | IPC contract, worker rich fields, parent adapter, 47 tests |
| A-C4 + A-C5 | `1773270` | Call-site switch, 6-file stub fix via conftest, 13 guardrails |

**Deviation (recorded, not silent).** A-C1/A-C2/A-C3 landed together
because their tests share one file; splitting would have landed A-C1 and
A-C2 without tests, which is worse. A-C4/A-C5 landed together because the
call-site switch is untestable until its stubs follow it — an
intermediate commit would have been red. A-C4's revert boundary is
preserved: reverting `1773270` restores the previous production path.

### 20.2 The missed audit — test substitution

**What was audited**: production callers. Exactly one, confirmed.

**What was not audited**: where the *tests* substitute. Six files in
`tests/unit/agent/tune_ml_hyperparam_agent/` stub
`_run_skill("evaluate_vram_skill", …)`. Once production stopped calling
that, the stubs stopped intercepting.

**Why it hung instead of failing.** A stub that no longer intercepts does
not raise — it lets the real call through. The real call spawns a
subprocess with a 900-second deadline, so the suite sat silent. Observed
directly: `preflight_worker_main` running as pid 1627303 with its spec
under `/tmp/pytest-of-yuema137/pytest-489/…/preflight_workers/`.

A hang is worse than a failure here: it has no traceback, no failing
test name, and it reads as slowness.

**The corrected patch boundary.** One `conftest.py`, not six rewritten
dispatchers:

- an autouse fixture delegates `run_production_preflight` back to
  whichever `_run_skill` mock each test installed, resolved at call time
  so it sees the mock inside that test's own `with` block;
- a second autouse fixture makes `run_isolated_preflight` raise, so no
  unit test in the package can start a real worker.

Every existing stub, return dictionary and assertion is untouched. No
timeout was raised to mask anything.

**Generalizable lesson, for PRs C, D and E.** When production
reachability changes, audit both the production callers *and* the layer
at which tests substitute. Otherwise a test can walk past its own mock
and execute the expensive or dangerous path for real.

### 20.3 Checkpoint results

- [x] **A1** call-path audit — §3, §4, §5, §6
- [x] **A2** production wiring implemented — `1773270`
- [x] **A3** deterministic compatibility — 47 adapter tests, 13 guardrails
- [x] **A4** lint and format clean; pyright deferred to CI (§20.5)
- [x] Guardrail proven by reverting the call site: **2 of 13 failed**
      (`test_tuner_calls_the_adapter`,
      `test_tuner_no_longer_dispatches_the_vram_skill_in_process`),
      then 13/13 after restoring. A guardrail never asserted to fail is
      not a guardrail.
- [ ] **A5** single-chain GPU validation — **requires operator approval**
- [ ] **A6** dual-chain GPU validation — after A5

### 20.4 Test evidence

| Suite | Result |
|---|---|
| `tests/unit/agent/evaluate_vram_skill/` + `tests/unit/guardrails/` | **685 passed, 1 skipped, 3 xfailed in 24.53 s** |
| `tests/unit/agent/tune_ml_hyperparam_agent/` | **710 passed in 194.52 s** |
| `test_preflight_adapter.py` | **47 passed in 0.18 s** |
| `test_preflight_production_reachability.py` | **13 passed in 0.33 s** |
| `ruff check` / `ruff format --check` | clean, 19 files |

No worker process remained after any run. No GPU work was executed.

### 20.5 Not run locally

- **strict pyright** — deferred to CI. Recorded rather than claimed:
  local Node availability for pyright has not been verified in this
  session, and the repository rule forbids claiming a local check that
  was not actually run.

## 21. A5 validation package — audited 2026-08-01

Audit performed on branch `feat/v20-pr-a-isolated-preflight` at head
`7f35ecd`. Read-only: no production code was modified by this audit.
Two findings below invalidate criteria written in §10 and §13; both
sections carry inline corrections pointing here.

### 21.0 Two blocking findings

**F1 — the tuner parent always holds a CUDA context, and PR A did not
put it there.**

`ml_hyperparameter_tune_agent.py:2101` calls
`core.hardware_context.get_or_create(...)` unconditionally at the top of
`run()`, before any pre-flight. `get_or_create` calls `discover()` on
**every** path — including when a stored manifest already exists
(`hardware_context.py:341`, `fresh = discover()`). `discover()` calls
`torch.cuda.get_device_properties(0)` (`hardware_context.py:260`), and
`get_device_properties` begins with `_lazy_init()`
(`.venv/.../torch/cuda/__init__.py:632`), which retains the primary
context.

Consequence: the parent appears in `nvidia-smi --query-compute-apps` for
its whole life, at bare-context cost, on **every** launch surface. The
§10.3 and §13 criterion "parent absent from nvidia-smi" can never pass
and never could have. It is not a PR A regression and not a defect this
PR should fix — `hardware_context.py:17` claims discovery is "always
cheap (no kernel launch; only property reads)", which is true of the
*property read* and false of the *context retain*. Filed as **FU-A-4**.

The criterion that actually tests what PR A changed is a **delta**: the
parent's footprint must not grow across a pre-flight. That is stronger
evidence, not weaker — before PR A the growth was the whole defect
(V19: 6,962 MiB resident in the parent after its child had exited).

**F2 — two other code paths run real CUDA workloads in the tuner parent,
and both are gated by one flag.**

| Path | Parent-side GPU work | Gate |
|---|---|---|
| Time pre-flight warmup — `evaluate_time_skill/wrapper.py:404-431` | full `forward` / `backward` / `optimizer.step()` on `device`, with `torch.cuda.synchronize()` | `chosen_time_budget is not None` (`tuner:3063`) |
| `REQUEST_PROBE` resolution — `probe_wiring.py:99-126` → `run_bounded_probe`, in-process | real bounded training steps | reached only from inside the same `if` block (`tuner:3090`) |

Both live under `if chosen_time_budget is not None:` at `tuner:3063`.
**Omitting `--trial_time_budget_minutes` and `--formal_time_budget_minutes`
disables both.** If A5 sets a time budget, the parent acquires real
training allocations from a path PR A never touched, and the measurement
becomes unattributable — the exact failure mode §1.3 of the V20 doc
names. Omitting them is therefore a **hard requirement**, not a
convenience.

> ```text
> A5 validation isolation choice
> not a production policy recommendation
> ```
>
> Omitting the time budgets is a **variable-isolation decision scoped to
> this validation run**. It says nothing about whether formal V20
> production should set them, and it is **not** a proposal to change the
> runtime-control posture. Production keeps its time budgets.
>
> The reason is attribution, not preference: with a time budget set, the
> parent legitimately performs real forward/backward/optimizer work, so
> even a *correct* PR A would leave the parent touching large amounts of
> CUDA — and A5 could not tell whether an observed parent footprint came
> from the VRAM pre-flight or from the time-control path. Removing one
> of the two sources is the only way one run can attribute the other.
>
> That both time-control paths run real CUDA workloads **in the tuner
> parent** is itself a finding worth acting on. It is registered as
> **FU-A-10** and deliberately **not** fixed here: PR A's scope is the
> VRAM pre-flight call boundary, and widening it to the time-control
> subsystem would repeat the mistake §2 was written to prevent.

### 21.1 `--force_model` — DETERMINISTIC, with an observability gap

Declared once, on the tuner only: `ml_hyperparameter_tune_agent.py:4548`
(`type=str`, `default="auto"`, deliberately no `choices=`).
`scripts/run_comparison.py:700` is a subprocess argv element, not a
second declaration.

| Question | Answer | Evidence |
|---|---|---|
| Determines architecture family? | **Yes, structurally** | `tuner:2753` `if model_type_setting != "auto": model_type = model_type_setting`; `:2774` `model_config["model_type"] = model_type`; instantiated at `train_engine_sandbox.py:498/668` |
| Bypasses architecture proposal? | **N/A** — no proposer exists on this path | zero `force_model` hits in `nodes/ml_model_proposal_agent/`, `nodes/ml_model_implementor/`, `workflows/` |
| Can the planner still return a different one? | Yes, and it is silently discarded | `ExperimentPlan.model_type` is an unconstrained `str` (`hyperparam_tuning.py:685`); no validator compares it |
| Conflict handling | **Silent override** — no error, no warning, no log | `tuner:2752-2756`; the printed value at `:2760` is the forced one |
| Recorded in manifest? | Yes, 3 places | `run_config_{run}.json` (`tuner:2263`), `tuner_run_metadata.json` (`run_comparison.py:1510`), `run_output_{run}.json` (`tuner:4350`) |
| In the run-invariants lock? | **No** | `_CANONICAL` at `core/run_invariants.py:134-145` has no model field |
| Classification | **DETERMINISTIC** | — |

Two caveats that matter for A5, neither disqualifying:

1. Only `model_type` is overridden. `plan.model_cfg` is copied wholesale
   at `:2772` with just its `model_type` key patched — so a planner that
   plans for a different architecture leaks that architecture's
   hyperparameters into the forced model's config class, failing at
   config validation rather than at a mismatch check.
2. `--force_model` is absent from the run-invariants lock, so changing
   it on a resumed workspace is not rejected. A5 uses a fresh workspace,
   so this does not apply.

### 21.2 `--plan_overrides` — deterministic post-plan, but not on the tuner CLI

Declared **once**, and not where A5 needs it:
`sdsc_submission_scripts/run_one_iteration.py:838`. The tuner's own CLI
has **no** `--plan_overrides` — stated explicitly at
`ml_hyperparameter_tune_agent.md:180`. Under `--is_trial` the tuner
CLI *synthesizes* a fixed 3-key dict instead (`tuner:4984-4991`):
`{"is_trial": True, "trial_portion": …, "eval_portion": …}`.

Application is a **deterministic post-plan merge**, not a prompt hint —
`_apply_plan_overrides` (`tuner:1487-1510`) does
`plan.model_dump(by_alias=True) | overrides` then re-validates the whole
`ExperimentPlan`, called at `tuner:2577` immediately after the plan is
parsed. Unknown keys are **hard-rejected** at input construction
(`hyperparam_tuning.py:1816-1858`), and an invalid effective plan raises
the run-terminating `PlanOverridesError` — the lock is never silently
released. The merge is **shallow at the top level**: overriding
`model_config` / `train_config` / `loss_config` replaces the entire
dict, it does not merge sub-keys.

| Quantity | Fixable? | Mechanism | Evidence |
|---|---|---|---|
| `trial_portion` | Yes, **trial rounds only** | post-plan | `:1500`, `:2577`; formal substitutes at `:993-1000` |
| `train_portion` (trial) | Yes, trial rounds only | post-plan | `:1004-1008` |
| `formal_train_portion` | **Not via overrides** | separate CLI input, always deterministic | `:997`, `tuner:4679` |
| `eval_portion` | Yes, trial rounds only | post-plan | `:999` |
| `formal_portion` / `formal_eval_portion` | **Not via overrides** | separate CLI inputs, deterministic | `tuner:4673`, `:4685` |
| batch size | Yes, whole-`train_config` replace | post-plan; **clobbered** on forced formal rounds under `full_clone` | `:1500`; clobber `:571-573` |
| segment length | Yes, whole-`model_config` replace | post-plan; **clobbered** by `full_clone` | `:697-700`; clobber `:563` |
| learning rate | Yes, whole-`train_config` replace | post-plan; **clobbered** by `full_clone` *and* `hybrid_params` | `:565`, `:588` |
| epoch count | Yes, then capped | post-plan → `full_clone` may replace → `max_epochs` clamps **last** | `:2615-2621` |
| architecture dims | Yes, whole-dict | post-plan; **clobbered** by `full_clone` | `:1500`, `:563` |
| model-specific hyperparams | Same as above (inside `model_config`) | post-plan, whole-dict | `:697-700` |
| timeout budgets | **Not supported** — unknown key → hard error | separate CLI inputs | `hyperparam_tuning.py:1840` |
| VRAM budget | **Not supported** | separate `--{trial,formal}_vram_budget_gb` | `tuner:5016-5019` |

Three later mutations can defeat an override, all after `:2577`:
`_apply_mode_override_chain` (`:2581`) forces `plan.is_trial = False` on
a forced formal round and, under the default `full_clone` strategy,
overwrites `model_cfg` / `loss_cfg` / `lr` / `epochs` / `batch_size` from
the winning trial record; DataScope normalization forces
`trial_strategy = eval_strategy = "snapshot"` (`:2611`); and the
`max_epochs` clamp runs last (`:2615-2621`).

**The dict itself is never persisted.** Only the *effect* reaches the
record (`params.{model,train,loss}_config` at `:2791-2798`). There is no
`override_applied` provenance flag analogous to
`ordering_resolution_source`. Auditors can reconstruct what ran, not
whether a value was operator-forced. Filed as **FU-A-5**.

**Combination verdict.** `--force_model` and `--plan_overrides` **cannot
be combined**: they exist on disjoint launch surfaces. The tuner CLI has
the first and not the second; the chain runner has the second and not
the first. This is the central constraint on §21.5.

### 21.3 `--is_trial` — a pipeline selector, not a phase switch

Neither reading in the kickoff is correct. `--is_trial` is a **run-level
permission plus pipeline selector**. Declared `tuner:4600`; read exactly
once into `trial_allowed = agent_input.is_trial` (`tuner:2113`); every
later use is `trial_allowed` or `plan.is_trial`, which are different
variables.

| Question | Answer |
|---|---|
| Trial sampling mode, or skip-formal? | **Neither.** It enables the multi-file `SampleSet` + anchor-normalised scoring pipeline, and permits the planner to pick trial mode on non-final rounds |
| Does formal execute under it? | **Yes — and there is no separate formal phase.** Formal is a per-round *mode* |
| What gates formal? | `max_rounds`, not `is_trial`: `is_formal_round = completed_rounds == max_rounds - 1` (`tuner:2411`) |
| Can forced formal still run? | Yes, and it is the **default**: `force_formal_round` defaults `True` (`hyperparam_tuning.py:1123`) and is **not exposed on the tuner CLI** — launched directly it is always `True` |
| Are formal portions consumed? | **Yes**, whenever the round resolves to `mode == "formal"` (`tuner:993-1000`). And `mode == "formal"` *requires* `trial_allowed` (`:2626`) — without `--is_trial` a round can only be `"trial"` or legacy `"single_file"` |
| Are formal time budgets consumed? | Yes on formal-mode rounds (`tuner:3061`) — which is exactly why A5 omits them (F2) |
| Hard prerequisite | `segment_anchors.json` must exist in the data dir or startup raises `FileNotFoundError` (`tuner:2206-2216`). Verified present at `/home/klz/Data/TIDMAD/segment_anchors.json` |

**Per-round phase order in the agent path** (all with file:line):

| # | Phase | Site | Process |
|---|---|---|---|
| 1 | LLM planning | `brain.plan` `tuner:2531` | in-process |
| 2 | Override chain | `:2578`, `:2584` | in-process |
| 3 | SampleSet build | `:2731`, `:2738` | in-process |
| 4 | RT5 guardrails | `:2804` | in-process, no GPU |
| 5 | **VRAM pre-flight** | `run_production_preflight` **`:2864`** → `preflight_adapter.py:196` → `isolated_probe.py:412` `Popen` | **child, own session** |
| 6 | Time pre-flight | `:3075` — **skipped when no time budget** | in-process, **real CUDA** |
| 7 | **Training** | `:3233` → `sandbox_executor.py:869` | **child** |
| 8 | **Inference** | `:3305` → `sandbox_executor.py:1164` | **child** |
| 9 | Scoring | `sandbox.score_vector` `:3435` | in-process |
| 10 | HealthGate | `:3488-3496` | in-process |
| 11 | Reflection | `brain.reflect` `:3846` | in-process |
| 12 | Record commit | `:3878+`, `:4036` | — |

Note the call site is **`:2864`**, not `:2843` as §11 records — `:2840-2863`
is the rationale comment block. §11's line reference is stale from `6fa5a83`.

**Minimum LLM calls per round: 2** — `plan` (per attempt) and `reflect`
(only on an attempt reaching the success path).

`--max_rounds 1 --is_trial` therefore yields exactly one **formal** round:
`_apply_plan_overrides` sets `plan.is_trial = True` from the CLI-injected
dict, then `_apply_mode_override_chain` immediately flips it back to
`False` (`:673`) because `is_formal_round and force_formal_round`. No
trial-mode round ever executes. Formal inheritance finds no prior winner,
logs the expected `no successful trial round is HealthGate-valid`
warning (`:702`), and keeps the planner's plan.

### 21.4 Launch surface comparison

| | **S1** `run_comparison.py` agent path | **S2** chain runner (`sdsc_submission_scripts/`) | **S3** tuner CLI direct |
|---|---|---|---|
| Path to `agent.run()` | `main` → `run_agent` → **subprocess** → tuner `main` | `main` → `run_workflow` → **in-process** `_tune_agent.run()` | `main` → `agent.run()` |
| Reaches `:2864` | Yes | Yes | Yes |
| Process levels | 3 | 2 | 2 |
| Prepends a baseline train+infer+score | **YES — mandatory on a fresh workspace** (`:1333-1366`) | No | No |
| LLM agents / min calls | 1 / 1-2 | **5 / ≥5** | 1 / 1-2 |
| Architecture fixable | **Yes** (`--force_model`) | **No** — comes from the LLM proposer via `ml_model_valid_to_ml_model_tune.py:241` | **Yes** |
| `--plan_overrides` | No | **Yes** | No |
| Auto-repeats | No | No (`max_iterations=1` hardcoded `:1542`) | No |
| Stop file | **None** | **`{workspace}/.chain_halted`** → exit 3 | None |
| C9d launch self-test | No | **Yes** (`model_exploration.py:1822`) | No |
| Writes lock + effective YAML | Yes (both workspaces) | Yes | Yes |
| Min invocation | `--model X` | `--workspace --run_name --start_iteration` | `--force_model --run_name --workspace` |

Correction of record: the chain runner lives under
`sdsc_submission_scripts/`, not `scripts/`.

**S1 is disqualified.** On a fresh workspace — which the cold-start
operator rule mandates — Phase 1 unavoidably runs a complete baseline
train → inference → score before the tuner starts (`:1333-1366`), and it
does so through `run_baseline_trial`, the path already established as
invalid. That is a large block of unrelated GPU work inside the same
script whose aggregate we are trying to measure. `run_comparison.py:963-966`
says so itself: *"this script is a baseline benchmark runner, not a chain
entry point."*

### 21.5 Candidate determinism — **Class B**, and Class A is unreachable

| Class | Achievable? | Why |
|---|---|---|
| **A** — architecture *and* hyperparameters deterministic | **No, on any production surface** | The two mechanisms live on disjoint CLIs (§21.2). The only way to get both is a new override on the tuner CLI — which the kickoff forbids ("Do not add a new override mechanism solely for A5") — or a test-only shortcut, also forbidden |
| **B** — architecture structurally fixed, hyperparameters planner-chosen and recorded | **Yes — S3 only** | `--force_model` is deterministic (§21.1); the resulting hyperparameters land in `params.{model,train,loss}_config` of the round record |
| **C** — bounded LLM-generated candidate | Yes — S2 | The architecture *is* generated plugin code; no flag pins it |

**Recommendation: Class B on S3 as the primary, Class C on S2 as a
sequenced follow-on — not a fallback.**

The reasoning is the project's own §1.3 principle: *a measurement earns
authority only when both correctly classified and correctly attributed.*
A5 measures a GPU-memory lifecycle. Every non-deterministic element in
the candidate is an alternative explanation for whatever the numbers
show. On S2 the architecture is LLM-generated code of unknown size, so a
surprising parent footprint has at least two candidate causes; on S3 it
has one. S3 also guarantees the run *reaches* training and inference,
which S2 does not — an LLM-generated candidate can be rejected at
pre-flight, which would prove the worker lifecycle but leave the
"training begins only after pre-flight memory is released" criterion
untested.

S3 is not a shortcut: it is the tuner node's own documented CLI
(`nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.md`),
and it is literally what S1 Phase 3 execs at `run_comparison.py:688-710`,
minus Phases 1-2. It is neither the baseline-comparison path nor a
direct adapter call — the two the operator ruled out.

What S3 forfeits is real and is the reason S2 follows it: the C9d launch
self-test, the `.chain_halted` kill switch, the iteration manifest, and
the `SCHEMA_REJECTED` pre-flight branch, which only fires on
`PLUGIN_CONFIG_CLASS` validation failure for agent-generated plugins
(`tuner:2890-2892`) and is therefore reachable **only** on S2. That
branch is part of what PR A's adapter added, so it must eventually be
exercised — after the lifecycle itself is established.

#### 21.5.1 What A5-a proves, and what it does not

S3 is **not** a test-only shortcut, and the distinction is precise:

- it executes the real `HyperparamTuningAgent.run()` (`tuner:5042`), not
  a harness;
- it reaches the **same** production pre-flight call site as the formal
  chain — `run_production_preflight` at `tuner:2864`, byte-identical
  code, no branch distinguishes the caller;
- it spawns the real isolated worker, the real training subprocess and
  the real inference subprocess through the unmodified
  `sandbox_executor`;
- it does **not** call `preflight_adapter` or `isolated_probe` directly.

What it omits is everything *above* the tuner: chain orchestration, the
proposal → implementation → validation workflow, and baseline
comparison. So A5-a establishes exactly this much:

```text
real tuner production caller
  → isolated preflight
  → training
  → inference
```

and **not** campaign readiness. A green A5-a means PR A's production
wiring is correct at the call boundary. It does not mean the V20 chain
passes, does not exercise the plugin `SCHEMA_REJECTED` branch, and does
not substitute for A6 or for the §13.1 launch gate. Claiming otherwise
would be the same category error V19 §15 was written to close.

#### 21.5.2 Class B boundary — say what is fixed and what is not

The package is:

```text
deterministic architecture
bounded planner-selected hyperparameters
```

It is **not** a fixed candidate, and must not be described as one. The
architecture family is structurally forced; every hyperparameter inside
it is still chosen by the planner on that round, bounded only by
`--max_epochs 1` and `--formal_vram_budget_gb 12.0`.

Consequently the candidate is **identified after planning, not before**.
The A5 report must capture all five, from the sources named:

| Item | Source | Status |
|---|---|---|
| Forced model family | `run_config_{run}.json` → `force_model`; `records/{run}/{exp_id}.json` → `params.model_config.model_type` | persisted |
| Full realized config | `configs/{run}/{model,train,loss}_config_{exp_id}.json`, and `params.*` in the round record | persisted |
| Realized parameter count | `preflight_workers/{exp_id}.json` → `realized_parameter_count` (worker's own measurement, `preflight_worker_main.py:329`) | persisted **only in the worker file** — the tuner never consumes `num_params`, so it is absent from the round record. Cross-check against `model_params` in `records/{run}/experiment_results_*.json`, which training computes independently |
| Config hash | **does not exist** | **No candidate-config hash mechanism is implemented.** The only sha256 in the tuner is `health_config_sha256` (health policy, `core/run_invariants.py:109`) plus a sampling `seed_hash` (`tuner:2648`). The operator computes one post-hoc from the persisted config files — see §21.7. Filed as **FU-A-11** |
| Planner/forced conflict | **not recorded anywhere** | `tuner:2752-2756` discards `plan.model_type` silently — no error, no warning, no log, no persisted field. If the planner proposed a different architecture, A5's artifacts cannot show it. This is a known observability gap (§21.1), and it is why the forced family must be read back from `run_config` rather than assumed |

### 21.6 Telemetry — what production already persists

Audited across the whole tree. **No production code path persists any
measured GPU memory figure — allocated, reserved, or driver-visible.**

| Quantity | Production? | Persisted? |
|---|---|---|
| `torch.cuda.max_memory_allocated()` | Yes — `probe_production.py:223` | **No.** Flows to `ProbeResult.peak_vram_gb` → `RuntimeEstimate`, consumed for a decision at `decision_policy.py:288-298`, then dropped: `CalibrationObservation` (`registry_schemas.py:114-190`) has no such field |
| `torch.cuda.max_memory_reserved()` | **Not present** | — |
| `memory_allocated` / `memory_reserved` | **Not present** | — |
| `reset_peak_memory_stats` | `probe_production.py:123` | n/a |
| Host RSS **peak** (`getrusage`) | **Not present anywhere** | — |
| Host RSS instantaneous | `core/memory_probe.py:113`, parent only | **Yes** → `{workspace}/memory_trace.jsonl`, 2 rows/round (`pre_score`, `post_score`) |
| Pre-flight worker peak RSS | **Measured** — parent polls `_worker_tree_rss_bytes` every 0.25 s (`isolated_probe.py:432-435`) | **No** — `adapt_result` drops `host_memory`, `worker_pid`, `worker_pgid`, `exit_code`, `orphans_remaining`, `elapsed_seconds` (`preflight_adapter.py:138-193`) |
| `IsolatedProbeResult.cuda_peak_{allocated,reserved}_gb` | Declared `isolated_probe.py:222-223` | **Never assigned** — always `None` |
| Training subprocess peak VRAM | **Not present** | — |
| Inference subprocess peak VRAM | **Not present** | — |
| Subprocess PIDs | **Not recorded** on the chain path | — |
| Per-role telemetry in `sandbox_executor.py` | Memory: **none** (only the `RLIMIT_AS` *limits* 40/60/24 GiB). Timing: inference only | partial |

The three quantities `v20_priorities.md:422-432` says are missing really
are missing. **A5 therefore measures externally and treats every
in-repo number as an analytic estimate, not a measurement** — the
`memory.vram_estimate_gb` / `vram_budget_gb` written to the round record
(`tuner:3967-3970`) are the *predicted* figures, and comparing them to
the externally sampled truth is itself an A5 output.

Per PR A's non-goals, **no telemetry code is added for A5.** Three
zero-risk sources already exist and are used instead:

1. `{workspace}/preflight_workers/{exp_id}.worker.log` — already
   contains the worker's `[Probe RSS] delta=` line
   (`evaluate_vram_skill/wrapper.py:540,561-570`).
2. `{workspace}/preflight_workers/{exp_id}.json` — the worker's typed
   outcome, written atomically by the worker itself
   (`preflight_worker_main.py:108-113`).
3. External `nvidia-smi --query-compute-apps` polling — read-only.

There is **no** general-purpose GPU polling script in the repo. The
closest, `probe_subprocess.py:128-156` `sample_worker_vram_gb`, is not on
the production chain path (callers: `runtime_campaign.py`,
`probe_worker_main.py` only). A5 uses a shell sampler, not repo code.

#### 21.6.1 What A5 can and cannot authoritatively verify

A5 must not report an unavailable quantity as measured, and must not
fill a gap with a zero, a null or an estimate relabelled as an
observation. The split is fixed in advance:

**AUTHORITATIVELY VERIFIABLE by A5** (external `nvidia-smi` per-PID
sampling + existing artifacts):

| Quantity | Source |
|---|---|
| Driver-visible per-PID GPU memory | `nvidia-smi --query-compute-apps` |
| Parent delta across the pre-flight (`M1 − M0`) | derived from the above |
| Pre-flight worker appearance and full release on exit | the above, plus PID absence |
| Phase overlap / ordering between worker, training, inference | sample timestamps |
| Process cleanup and orphan state | `ps` + `--query-compute-apps` at `t5` |
| Parent host RSS at `pre_score` / `post_score` | `memory_trace.jsonl` |
| Worker host-RSS delta | `preflight_workers/{exp_id}.worker.log` |
| Worker typed outcome and `realized_parameter_count` | `preflight_workers/{exp_id}.json` |
| Per-phase wall time | `timing.*` in the round record |

**UNAVAILABLE — a gap, not a measurement:**

| Quantity | Why |
|---|---|
| `torch.cuda.max_memory_allocated()` | computed at `probe_production.py:223` but never persisted, and that path does not run in A5 (no time budget → no `REQUEST_PROBE`) |
| `torch.cuda.max_memory_reserved()` | not present in production at all |
| Training-subprocess peak VRAM | no instrumentation exists |
| Inference-subprocess peak VRAM | no instrumentation exists |
| Worker CUDA peak (`cuda_peak_{allocated,reserved}_gb`) | fields declared, never assigned — always `None` |
| Subprocess PIDs from artifacts | not recorded on the chain path; A5 recovers them from `ps`, which is external evidence, not a production artifact |

**Consequence for the A5 report.** Driver-visible memory is CUDA context
plus caching-allocator **reserved**; the pre-flight's `estimated_gb`
predicts **allocated** peak. These are different quantities. §21.9
criterion 9 compares them only as an order-of-magnitude sanity check and
must be labelled as such — it is **not** a calibration measurement, and
A5 must not be cited as evidence that the estimator is accurate. Closing
that gap is FU-A-6 / FU-A-7, not this run.

### 21.7 RECOMMENDED PACKAGE — A5-a

**Exact command.** Single process tree, no wrapper script.

```bash
timeout --signal=INT --kill-after=120 2700 \
.venv/bin/python nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py \
    --force_model punet \
    --provider openai --model_id gpt-5.5 \
    --reflect_provider openai --reflect_model_id gpt-5.5 \
    --run_name a5_preflight_lifecycle_v1 \
    --workspace /home/klz/Data/SIDEREIS_DATA/v20_a5/a5_preflight_lifecycle_v1 \
    --is_trial \
    --max_rounds 1 \
    --attempts_per_formal_round 1 \
    --max_epochs 1 \
    --formal_portion 0.02 \
    --formal_train_portion 1.0 \
    --formal_eval_portion 0.02 \
    --formal_vram_budget_gb 12.0 \
    --data_scope 6 \
    --health_gate_files 6 \
    --cleanup_denoised \
    --progress_bar
```

Run from the repository root. Every flag verified against `--help` on
the branch head.

**Deliberately absent, and why:**

| Omitted | Reason |
|---|---|
| `--trial_time_budget_minutes`, `--formal_time_budget_minutes` | **F2 — hard requirement.** Setting either makes the parent run real CUDA training from `evaluate_time_skill` and enables the in-process `REQUEST_PROBE` probe. Both would manufacture parent-side allocations from paths PR A never touched |
| `--seed_paths` | cold-start operator rule |
| `--trial_portion`, `--eval_portion`, `--train_portion` | dead — read only when `mode == "trial"` (`:1001-1008`), and the round is forced formal |
| `--trial_vram_budget_gb` | unselected branch (`:2830`, `:3061`) |
| `--file_index` | ignored under `--is_trial`; legacy single-file relic |
| `--trial_strategy`, `--eval_strategy` | deprecated no-ops that emit `DeprecationWarning` (`:4967-4974`) |
| `--formal_strategy` | default `snapshot` is the only legal value under a partial scope (`hyperparam_tuning.py:1916-1923`) |
| `--runtime_watchdog` | off by default; A5 must not have a killer competing with the measurement |
| `--enable_chain_incumbent_formal_gates` | inert without a chain incumbent (`:425-426`) |

**Call graph.**

```
[P0] ml_hyperparameter_tune_agent.py  main() :4493
      └─ HyperparamTuningAgent.run()  :5042
         ├─ get_or_create(...)        :2101   ← CUDA context enters P0 here (F1)
         ├─ round 0 == formal         :2411
         ├─ brain.plan()              :2531   ← LLM call 1
         ├─ run_production_preflight  :2864
         │    └─ preflight_adapter.py:196 → isolated_probe.py:412 Popen
         │         └─ [P1] preflight_worker_main   (own session)
         ├─ (time pre-flight SKIPPED — no budget)
         ├─ training_skill            :3233 → sandbox_executor.py:869
         │    └─ [P2] train_engine_sandbox
         ├─ inference_skill           :3305 → sandbox_executor.py:1164
         │    └─ [P3] inference_single
         ├─ score_vector              :3435   (in-process)
         ├─ HealthGate                :3488
         └─ brain.reflect()           :3846   ← LLM call 2
```

**Package parameters.**

| Field | Value |
|---|---|
| PR head | `7f35ecd1331fe314be1db07afb917b2a638042de` (branch `feat/v20-pr-a-isolated-preflight`) |
| Run name | `a5_preflight_lifecycle_v1` |
| Workspace | `/home/klz/Data/SIDEREIS_DATA/v20_a5/a5_preflight_lifecycle_v1` |
| Precondition | workspace **must not exist** — verify with `test ! -e <ws>` before launch |
| Candidate source | `--force_model punet`, deterministic override at `tuner:2753` |
| Forced architecture | `punet` (built-in registry model; healthiest of the four in the official-paper scan, 93-99 unique output values) |
| Hyperparameters | planner-chosen, bounded by `--max_epochs 1` and `--formal_vram_budget_gb 12.0`; recorded verbatim in `records/{run}/{exp_id}.json` → `params.*` |
| Determinism class | **B** |
| LLM calls | **exactly 2** (1 `plan` + 1 `reflect`; `attempts_per_formal_round 1` caps `plan` at 1) |
| Token/cost cap | ≤ 2 calls; expected well under $0.20. No retry loop can raise it — `attempts_per_formal_round 1` is the bound |
| Phases executed | pre-flight → training → inference → scoring → HealthGate → reflect. **No** time pre-flight, **no** bounded probe, **no** baseline |
| Data scope | file 6 only, paired `--health_gate_files 6` per the DS8 rule |
| Wall cap | 2700 s hard, `SIGINT` then `SIGKILL` after 120 s |
| Per-worker host-memory cap | unchanged production values: training `RLIMIT_AS` 40 GiB, inference 60 GiB, scoring 24 GiB (`sandbox_executor.py:92-96`); pre-flight worker bounded by the parent RSS monitor |
| VRAM cap | 12.0 GiB via `--formal_vram_budget_gb`, the §11 figure |
| Expected processes | P0 parent (persistent), P1 worker (transient), P2 training (transient), P3 inference (transient) — **never more than two GPU-touching processes alive at once**, and P1 must be gone before P2 exists |

**GPU sampling procedure** (read-only, started **before** the run):

```bash
mkdir -p /tmp/a5_samples && \
( while true; do
    ts=$(date +%s.%N)
    nvidia-smi --query-compute-apps=pid,used_gpu_memory \
               --format=csv,noheader,nounits |
      while IFS=, read -r pid mem; do
        echo "$ts,$pid,$mem,$(ps -p ${pid// /} -o comm= 2>/dev/null)"
      done
    sleep 1
  done ) > /tmp/a5_samples/gpu_samples.csv 2>&1 &
```

1 Hz is sufficient: the pre-flight worker's lifetime is seconds to
minutes, and the criteria are about ordering and deltas, not sub-second
peaks. Pair with `ps -eLf --forest` snapshots at the same cadence to map
PID → role.

**Hard precondition — an idle GPU. A5 does not start otherwise.**

```text
GPU must be idle at baseline
no foreign compute process
no active official-result scoring/inference process
```

Verified immediately before launch:

```bash
nvidia-smi --query-compute-apps=pid,process_name,used_gpu_memory \
           --format=csv,noheader          # must print nothing
nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits
                                          # record as the device baseline
```

This is not a nicety. V19's entire misdiagnosis came from measuring
under contention and attributing the result to the candidate; the
corrected §1.3 principle — a measurement earns authority only when both
correctly *classified* and correctly *attributed* — makes a contended
A5 sample **inadmissible**, not merely noisy. Under contention the
`M1 − M0` delta cannot be separated from a foreign process's
allocation, and the run must be discarded rather than interpreted.

**At audit time this precondition was NOT met**: PID 1777633
(`score_tidmad_official_banded.py --models fcnet punet`) held 3,696 MiB.
A5 waits for it to finish. Waiting is the correct action — running
early to save wall time is precisely how V19 produced a result that had
to be thrown away.

**Post-hoc candidate config hash.** No hash mechanism exists (§21.5.2),
so the operator computes one after the run over the persisted config
files, and records it in the A5 report as an operator-computed value —
never presented as a production artifact:

```bash
cat "$WS"/configs/"$RUN"/{model,train,loss}_config_*.json | sha256sum
```

**Persistent artifacts** (all under the workspace unless noted):

| Path | Content |
|---|---|
| `preflight_workers/{exp_id}.json` | worker's typed outcome — the PR A contract under test |
| `preflight_workers/{exp_id}.spec.json` | the `IsolatedProbeSpec` sent to the worker, incl. `HardwareSnapshot` |
| `preflight_workers/{exp_id}.worker.log` | worker stdout/stderr, incl. `[Probe RSS] delta=` |
| `records/{run_name}/{exp_id}.json` | round record: `timing.*`, `memory.vram_estimate_gb`, `memory.vram_budget_gb`, `params.*` |
| `summary_{run_name}.json`, `run_output_{run_name}.json`, `run_config_{run_name}.json` | run-level |
| `run_invariants_lock.json`, `health_checks_effective.yaml`, `{run}_hardware.json` | invariants |
| `memory_trace.jsonl` | parent RSS at `pre_score` / `post_score` |
| `/tmp/a5_samples/gpu_samples.csv` | the external truth, **outside** the workspace |

**Cleanup deadline.** Kill the sampler and confirm zero orphans within
5 minutes of P0 exit: `nvidia-smi --query-compute-apps` empty, and no
`preflight_worker_main` / `train_engine_sandbox` / `inference_single`
in `ps`. `--cleanup_denoised` removes the denoised HDF5 per round;
verify no `*_denoised_*.h5` remains.

### 21.8 SEQUENCED FOLLOW-ON — A5-b (only after A5-a passes)

Production-fidelity confirmation on S2. Class C. Adds the C9d launch
self-test, the iteration manifest, `.chain_halted`, and the only path
that can reach the `SCHEMA_REJECTED` pre-flight branch.

Invocation: the chain runner at `sdsc_submission_scripts/` (single
iteration), with

- `--workspace /home/klz/Data/SIDEREIS_DATA/v20_a5/a5_chain_fidelity_v1`
- `--run_name a5_chain_fidelity_v1 --start_iteration 1`
- `--max_rounds 1 --max_epochs 1 --attempts_per_formal_round 1`
- `--formal_portion 0.02 --formal_train_portion 1.0 --formal_eval_portion 0.02`
- `--formal_vram_budget_gb 12.0`
- `--data_scope 6 --health_gate_files 6`
- `--plan_overrides '{"train_config": {"batch_size": 8, "lr": 5e-4, "epochs": 1}}'`
- `--cleanup_denoised`
- wall cap 5400 s

No `--seed_paths` (cold start). No time budgets (F2 applies identically).
`--plan_overrides` narrows hyperparameter freedom but **cannot** fix the
architecture — that is generated plugin code and is the residual
non-determinism defining Class C. Kill switch:
`touch {workspace}/.chain_halted`. Expect ≥5 LLM calls, roughly
$1.50-2.50 and ~15 min of LLM latency per the gate standard.

The `--plan_overrides` value above must be re-checked against the
resolved plugin's config class before launch: the merge is a **whole-dict
replace**, so any `train_config` key the plugin requires and this dict
omits will surface as a `PlanOverridesError`.

### 21.9 Pass criteria — revised and executable

Let `M(p, t)` be the driver-visible MiB for PID `p` at sample time `t`,
and let the checkpoints be:

| | Definition |
|---|---|
| `t0` | after `[Tuner] Hardware context:` is printed, before P1 exists |
| `t1` | while P1 (worker) is present in `--query-compute-apps` |
| `t2` | first sample after P1 is absent, before P2 exists |
| `t3` | while P2 (training) is present |
| `t4` | while P3 (inference) is present |
| `t5` | after P0 exits |

**The parent criterion, stated exactly.** The retired form was:

```text
parent absent from nvidia-smi          ← IMPOSSIBLE (F1). Do not use.
```

The replacement is:

```text
parent GPU delta attributable to preflight
<= 64 MiB
```

with the two sampling points defined as:

```text
M0 = parent driver-visible GPU memory after hardware discovery,
     immediately before isolated preflight

M1 = parent driver-visible GPU memory after preflight worker exits
     and cleanup grace expires

pass if M1 - M0 <= 64 MiB
```

Operationally: `M0` is the last sample of `M(P0, ·)` before P1 first
appears — taken after `[Tuner] Hardware context:` is printed, so the
`hardware_context` CUDA context (F1) is already inside `M0` and cancels
out of the difference. `M1` is `M(P0, ·)` taken after P1 has been absent
for a **10-second cleanup grace**, so that asynchronous driver-side
teardown cannot be misread as a leak.

**64 MiB is a compatibility tolerance, not a resource budget.** It
absorbs driver-side accounting granularity and sampling jitter. It does
**not** authorize the parent to hold 64 MiB of pre-flight state, and it
must never be cited as a memory allowance in any policy, gate or
estimator. The expected value is ~0.

**Primary criteria:**

1. **Parent does not grow across a pre-flight.** `M1 − M0 ≤ 64 MiB`.
   Self-calibrating: needs no prior estimate of what a bare CUDA context
   costs on the host. Before PR A this delta was the whole defect.
2. **The worker actually appears on the GPU.** P1 must be present in
   `--query-compute-apps` for at least one sample with non-zero memory.
   A worker that never shows up has not proven isolation — it has proven
   nothing, and the run is void rather than passing.
3. **The worker fully releases on exit.** P1 absent at `M1`, and total
   device usage at `M1` ≤ device usage at `M0` + 64 MiB.
4. **No V19-style parent high-water.** `max_t M(P0, t)` over the entire
   run must never approach the V19 signature of ~6.9–8.9 GiB resident in
   the parent. This is a separate check from criterion 1: criterion 1
   catches a leak across one pre-flight, this catches a large parent
   allocation arising at any point, from any path.
5. **No overlap.** P1 and P2 are never present in the same sample.
   Strictly: `max{t : P1 present} < min{t : P2 present}`.
6. **No orphan.** At `t5`: `--query-compute-apps` empty; no
   `preflight_worker_main` / `train_engine_sandbox` / `inference_single`
   in `ps`.
7. **Result path unchanged.** `records/{run}/{exp_id}.json` contains
   `memory.vram_estimate_gb`, `memory.vram_budget_gb`,
   `params.inference_batch`; `summary_{run}.json` and
   `run_output_{run}.json` parse under their schemas; the HealthGate
   record is present.

**Secondary — recorded, not gating:**

8. `M0` itself — the bare-context cost attributable to F1, not to PR A.
9. `max_t M(P1, t)` vs the worker's own `estimated_gb`. **Order-of-
   magnitude sanity check only** — driver-visible memory is context +
   caching-allocator *reserved*, while `estimated_gb` predicts
   *allocated* peak. Per §21.6.1 this is not a calibration measurement
   and A5 must not be cited as evidence about estimator accuracy.
10. `max_t M(P2, t)`, `max_t M(P3, t)`, and the tree aggregate
    `max_t Σ_p M(p, t)`. **Do not assume < 12 GiB — measure it.** V19's
    17.74 GiB was taken under contention and does not bound a standalone
    run.
11. Host RSS peak from `memory_trace.jsonl` + the worker log's
    `[Probe RSS] delta=` line.
12. Wall time per phase from `timing.*` in the round record.
13. Candidate identity per §21.5.2: forced family, realized config,
    realized parameter count, operator-computed config hash.

**Explicitly NOT a criterion:** "P0 absent from `nvidia-smi`". F1 makes
it unachievable, for reasons predating and unrelated to this PR.

### 21.10 Stop conditions

Halt and return to operator review — do not iterate on the command — if
any of these occur:

- `M1 − M0 > 64 MiB` (criterion 1 fails) — the PR A defect is not fixed;
- P1 never appears on the GPU (criterion 2 fails) — the run is **void**,
  not passing: nothing was isolated because nothing was observed;
- `max_t M(P0, t)` approaches the V19 6.9–8.9 GiB signature
  (criterion 4 fails), from any path;
- P1 and P2 are ever co-resident — the lifecycle is not serialized;
- P1 exits non-zero with an infrastructure outcome, or the adapter
  raises `PreflightWiringError` (an unmapped outcome — a real contract
  gap, and exactly what §9's no-silent-fallback rule is for);
- any orphan survives the cleanup deadline;
- the run is `SIGTERM`ed by the host VRAM quota watchdog (30,000 MiB/user)
  — the measurement is then contention-contaminated and inadmissible,
  per the V19 attribution finding;
- the GPU was not idle at launch;
- the pre-flight rejects the candidate before training (`REJECT` /
  `SCHEMA_REJECTED`), which proves the worker lifecycle but leaves
  criterion 5 untested — re-scope, do not re-roll.

### 21.11 Follow-ups filed by this audit

| ID | Finding |
|---|---|
| **FU-A-4** | `hardware_context.discover()` initializes CUDA in every caller (`hardware_context.py:260` → `_lazy_init`), contradicting its own docstring claim at `:17` that discovery is "always cheap (no kernel launch)". `get_or_create` calls it even when a valid manifest exists (`:341`). Out of scope for PR A |
| **FU-A-5** | `plan_overrides` has no persisted provenance — only its effect reaches the record, so an auditor cannot distinguish an operator-forced value from an LLM-chosen one. Contrast `ordering_resolution_source` |
| **FU-A-6** | `adapt_result` (`preflight_adapter.py:138-193`) drops `host_memory`, `worker_pid`, `worker_pgid`, `exit_code`, `orphans_remaining`, `elapsed_seconds` — all already measured and typed. Persisting them would make future A5-class validation an artifact read rather than an external sampling exercise |
| **FU-A-7** | `IsolatedProbeResult.cuda_peak_allocated_gb` / `.cuda_peak_reserved_gb` are declared (`isolated_probe.py:222-223`) and never assigned — always `None`. A wire-up, not a new schema |
| **FU-A-8** | §11 records the call site as `:2843`; it is `:2864`. Stale since `6fa5a83` |
| **FU-A-9** | `--force_model` is absent from the run-invariants lock `_CANONICAL` set, so changing it on a resumed workspace is not rejected |
| **FU-A-10** | Two time-control paths run **real CUDA workloads in the tuner parent**: the time pre-flight warmup (`evaluate_time_skill/wrapper.py:404-431` — full forward/backward/`optimizer.step()`) and the in-process `REQUEST_PROBE` resolution (`probe_wiring.py:99-126` → `run_bounded_probe`). Same class of concern PR A fixed for the VRAM pre-flight, different subsystem. Deliberately out of PR A scope (§2); A5 sidesteps it by omitting the time budgets (§21.0 F2) |
| **FU-A-11** | No candidate-config hash exists. The only sha256 in the tuner is `health_config_sha256` (health policy) plus a sampling `seed_hash`. A candidate identity hash would make cross-run comparison auditable instead of requiring an operator-computed digest |

**Status: A5 VALIDATION PACKAGE READY FOR OPERATOR REVIEW.**
Not executed. PR #152 not merged. PR B not started.

## 22. A5 result and the narrow repair (2026-08-01)

A5-a ran once, on an idle GPU, at head `0629c11` (code byte-identical
to the reviewed `7f35ecd`). Wall time 84 s, 3 LLM calls, score 4.6958.

### 22.1 Lifecycle: PASS

All six gating criteria passed, and the parent criterion passed in a
form stronger than §21.9 asked for.

| Criterion | Result |
|---|---|
| Idle-GPU precondition | no foreign compute process in 910 samples |
| C2 worker executed | proven by artifact; process polling missed it (see 22.4) |
| C1 parent delta ≤ 64 MiB | parent **never appeared** in `--query-compute-apps`. M0 = M1 = 0 |
| C3 worker releases on exit | no worker PID survives; device back to 273 MiB baseline |
| C4 no V19 high-water | parent peak **0 MiB** (V19 signature ≥ 6,900 MiB) |
| C5 no overlap | worker result written 1.5 s before the first training GPU sample |

Measured peaks: training 3,076 MiB (8.3 s), inference 2,716 MiB (2.0 s),
chain aggregate **3,076 MiB**. No orphan, no watchdog event, denoised
HDF5 cleaned. **The V19 parent high-water mark is gone.**

### 22.2 F1 was wrong — correcting §21.0 and §10

§21.0 F1 claimed the tuner parent must appear in `nvidia-smi` because
`hardware_context.discover()` initializes CUDA, and on that basis §10.3
and §13 were rewritten away from "parent absent from nvidia-smi".

**The code reading was right; the operational conclusion was wrong.**
Measured directly on this host:

```
before          : cuda_initialized=False  apps=(empty)
after discover(): cuda_initialized=True   apps=(empty)     <-- no process
after 256 MiB   : cuda_initialized=True   apps=1845638, 850 MiB
```

`_lazy_init()` initializes the CUDA runtime and reads device properties
without registering a compute process. **Only a real allocation does.**
So V19's 6,962 MiB was the in-process pre-flight's *allocations*, not a
context — and the original criterion was achievable all along. A5 met
it.

What survives from F1: §10.2's correction stands, because
`torch.cuda.is_initialized()` really is `True` in the parent. What is
retracted: the claim that the parent must be visible in `nvidia-smi`,
and the framing of the delta criterion as a necessary weakening. The
delta remains a valid criterion — it is simply satisfied here in the
degenerate, strongest way.

Lesson, and it is the same one as §1.3: a correct reading of the code
is not a prediction about the system. F1 was asserted from source and
should have been measured before it was used to relax a criterion.

### 22.3 Artifact contract: FAIL, now repaired

`memory.vram_budget_gb` was `null`. All 456 pre-PR-A records carry
`12.0`. Confirmed regression.

**Mechanism.** `run_production_preflight` calls
`adapt_result(probe.model_dump())` (`preflight_adapter.py:231`), so the
payload is `IsolatedProbeResult` — not the worker's JSON. Loss happened
at *two* points: the model did not declare the fields, and the explicit
mapping in `run_isolated_preflight` did not pass them.

A mechanical four-layer diff found **eight** dropped fields, not the
four first observed:

```
limit_gb  dominant_phase  verdict  suggestion
violations  offending_config  memory_killer  truncated
```

The last four are the entire D-A2 bounded-diagnostics mechanism —
built in the worker by A-C2, tested in the worker, and discarded one
layer later. It had never once reached a record.

`verdict` survived only by accident: the adapter falls back to
`payload.get("detail")`, and the two texts happened to match.

`vram_cap_gb` (the cap the parent resolved) was already declared, one
letter-space away from `limit_gb` (the limit the worker applied) — the
likely reason the omission read as covered.

**Why 47 adapter tests missed it.** They call `adapt_result()` with
hand-built payload dicts that already contain the keys. Every layer was
tested and every layer was correct; nothing tested the sequence.

```text
Testing each serialization layer independently does not prove that the
composed worker-JSON -> IPC-model -> adapter path preserves the
contract.
```

**Repair** — narrow, no redesign. `IsolatedProbeResult` declares the
eight fields plus `violations_omitted_count`; the payload branch passes
them in the existing explicit-keyword style, which the module keeps for
strict pyright. The adapter forwards the new count. Production call
path, isolation, timeouts, dispositions, limits and tuner consumer
logic are untouched. `extra="allow"` was not used.

Two sub-decisions, both operator-approved 2026-08-01:

**(a) `truncated: true` never appears without a count.**
`_bounded_rich_fields` has three truncation modes — text shrinking,
list trimming, whole-field dropping — and only the middle one recorded
`{field}_omitted_count`. A record could therefore admit that evidence
was cut while giving no way to judge the scale of the loss, and the
scale is the measured part. The count is now emitted for every mode,
computed against the original list length rather than an already-shrunk
intermediate. The 8 KiB budget is unchanged.

**(b) The rich fields are typed `list`/`dict` **or** `str`.**
When a field will not fit, the worker deliberately replaces it with
`"[dropped: exceeded the rich-field budget]"` so its absence is
explicit — behavior with its own test
(`test_dropped_field_is_marked_not_removed`). The first draft of this
repair typed `violations` as `list | None`, which would have converted
that marker back into exactly the silent `None` it exists to prevent.
Caught before commit; the union is deliberate, and
`test_a_dropped_field_keeps_its_marker_rather_than_becoming_none`
holds it.

### 22.4 New tests

`tests/unit/agent/evaluate_vram_skill/test_preflight_ipc_composition.py`
drives the **real production path** — a real worker subprocess via the
`command=` seam, the real result file, the real payload mapping — then
asserts on the adapted result. No GPU.

27 tests: per-field survival for every dropped field; a test that
gives `verdict` and `detail` different text so the fallback cannot
masquerade as forwarding; drop-marker preservation; the uniform
truncation-count rule across all three modes with the 8 KiB budget
re-asserted; all three outcome classes; and a **schema-diff guardrail**
that enumerates worker keys behaviorally (by calling `_classify` for
every status it handles, not by parsing source) and fails when the
worker grows a field the IPC model cannot carry.

Proven to catch the defect: with the repair reverted, **11 of 16 fail**
(measured on the first 16, before the truncation tests were added),
including the guardrail. A guardrail never asserted to fail is not a
guardrail.

### 22.6 A5 contract revalidation — what the rerun must show

Same configuration and command as §21.7. It is a **contract** check,
not a re-proof of the lifecycle:

1. `memory.vram_budget_gb == 12.0` in the round record;
2. all eight fields plus `violations_omitted_count` reach the final
   artifact with correct values;
3. the six §21.9 criteria still PASS.

On criterion 1, keep the **stronger** form now that it is known
achievable: the parent must not appear in `--query-compute-apps` at all
and its peak must be 0 MiB. The `M1 − M0 ≤ 64 MiB` delta stays as a
recorded statistic, but it must not be used in place of "the parent
performed no real GPU allocation".

Not to be rerun before CI is green.

### 22.5 Sampling note

The pre-flight worker was **not** captured by process sampling at
~6.6 Hz — it is shorter than the polling window. Execution is proven by
the artifact channel (`preflight_workers/*.json`, written by the worker
itself). Recorded explicitly as a sampling miss, per the operator's
two-channel rule: a polling miss is an observer limitation, not
absence; a process sighting without a completed contract would not have
sufficed.

`preflight_execution_mode: isolated_subprocess` (§11) was
**unimplemented at the time of A5 and A6** and is scoped to the chain
runner's manifest, which the tuner-CLI path does not write. It was
implemented on 2026-08-01 *after* A6, as the last open scope item
before merge (§19 A-C5).

That ordering does not weaken the A5/A6 evidence, and the substitution
argument still stands on its own: the worker artifacts
(`preflight_workers/*.json`, written by the worker process itself) are
strictly stronger evidence than the field, because a string field is a
self-assertion while a file written by another PID is not. The manifest
field records which mechanism the build ships; the reachability
guardrails prove production reaches it. Neither replaces the other.

## 23. A6 dual-chain package — prepared 2026-08-01, NOT executed

A5 answered "is the wiring correct". A6 answers a different question:

```text
with the parent's redundant GPU memory gone, is the real concurrent
pair-level footprint safe, and is PR B still required?
```

Nothing here presumes PR B is needed. A6 exists to decide that from
measurement.

### 23.0 Two findings that shape the package

**F3 — `pair_admission.py` has zero production callers.**
`core/runtime_control/pair_admission.py` defines
`DEFAULT_PAIR_CEILING_GIB = 28.0`, `pair_ceiling_gib()`,
`evaluate_pair_admission()` and a `_cli`, and **nothing in the chain
calls any of it** (grep across the tree, excluding tests and the module
itself: no hits). It is the same shape as the calibration-promotion
defect V19 exposed — built, tested, and never wired.

Consequence for A6: **the 28 GiB ceiling is not enforced anywhere in
production.** The external stop monitor in §23.6 is not a convenience;
it is the only thing between this run and the host watchdog. Filed as
**FU-A-12**.

The module's `_cli` is still useful as a *pre-launch* gate, because it
answers the configured-cap question with the same function the Python
path would use rather than a second implementation in bash. Run against
this package's caps it returns:

```
feasible=true  aggregate=24.00 GiB  ceiling=28.00 GiB  headroom=4.00 GiB
"no host quota declared (SIDERIUS_GPU_VRAM_QUOTA_MIB unset):
 unknown, which is not the same as unlimited"
```

That last line is the honest state: the 30,000 MiB host quota is an
operator fact, not a declared environment fact, so the module cannot
tighten the ceiling to it automatically.

**F4 — short runs may never overlap, which would make A6 measure
nothing.** A5's training window was **8.0 s** inside a **79 s** run;
the rest is import, LLM planning and scoring. Two chains launched
together can therefore finish their training phases tens of seconds
apart and never be concurrent, and a pair aggregate sampled from
non-overlapping phases is not a pair measurement at all — it would read
as a comfortable pass while proving nothing.

The fix is to lengthen the window without raising the peak.
`--formal_portion` controls how many segments are processed, and peak
VRAM is set by `batch_size x segmentation_size`, not by segment count.
Raising the portion from 0.02 to 0.2 therefore multiplies training
duration roughly tenfold while leaving the per-attempt peak where A5
measured it. This is the one deliberate deviation from A5's parameters,
and it exists to make concurrency observable rather than to change what
is being measured.

**Consequently "no concurrent training was observed" is an
INCONCLUSIVE verdict for A6, never a PASS.** §23.8 makes that explicit.

### 23.1 Candidate selection, and why these two

Evidence from V19's own records (41 records carrying a VRAM estimate):

| Chain | n | estimate min / med / max | params min / med / max |
|---|---|---|---|
| arch | 16 | 0.25 / 0.49 / **2.34** GB | 42 k / 180 k / **2.92 M** |
| loss | 19 | 0.24 / 0.37 / **2.20** GB | 29 k / 83 k / **7.28 M** |

Both V19 chains ran overwhelmingly wavenet-family candidates. The pair
below sits at the **upper end** of that observed range, which is the
honest choice: not tiny enough to guarantee a pass, not chosen to force
an OOM.

| | Chain A ("arch-like") | Chain B ("loss-like") |
|---|---|---|
| Forced family | `wavenet` | `punet` |
| Paper-spec params (CPU-counted) | **302,784** | **6,762,568** |
| Position vs V19 range | mid | at/above the V19 maximum (7.28 M) |
| Prior measurement | none — no historical `wavenet` record carries a VRAM estimate | **A5: 3,076 MiB driver-visible, estimate 1.706 GB** |

`punet` is deliberately one side of the pair because A5 measured it
twice with an identical config hash: it is the calibrated side, so any
surprise in the pair aggregate can be attributed rather than guessed.
`wavenet` is the V19-family side.

#### 23.1.1 Two claims that must not be conflated

**Corrected 2026-08-01 after operator review.** WaveNet's *paper-spec*
configuration is ~302 k parameters — an order of magnitude below the
2.9 M–7.3 M candidates V19 actually ran concurrently. That is enough to
validate one thing and not the other:

| Claim | Does a 302 k WaveNet support it? |
|---|---|
| **Lifecycle concurrency** — two production parents, two isolated workers, two training children, correct ordering, no orphan | **Yes** |
| **V19-scale pair safety** — the concurrent footprint under representative load is safe, therefore PR B is not needed | **No** |

A6 does not pin WaveNet's hyperparameters (`--force_model` fixes the
family only, §21.1), so the planner selects the realized configuration
and it may land anywhere in the family's range. **No new
candidate-injection mechanism is added for A6.** Instead the realized
size is read from artifacts written *before* training — the worker
result and the persisted configs — and the run is classified after the
fact:

| Quantity | Source | Acceptance for "V19-scale" |
|---|---|---|
| realized parameter count | `preflight_workers/{exp_id}.json` → `realized_parameter_count` | **>= 2,000,000** |
| estimated VRAM | same file → `estimated_gb` | **>= 1.5 GB** |
| config hash | operator-computed over `configs/{run}/{model,train,loss}_config_*.json` | recorded |

A chain qualifies on **either** metric, because WaveNet's memory is
activation-dominated: a small parameter count with a large
`segmentation_size × batch_size` can still be a heavy candidate, and
judging it by parameters alone would misclassify it.

If **either** chain falls below both lines, the verdict is:

```text
A6 LIFECYCLE VALIDATION ONLY — LOAD NOT REPRESENTATIVE
```

Such a run may still establish the lifecycle claims. **It may not be
used to conclude that PR B is unnecessary for safety.** That
restriction is enforced mechanically by the analyzer, not left to the
report author.

> **Scope of the 2 M / 1.5 GB lines.** These are **A6
> representativeness criteria** — a test of whether *this validation's*
> load resembles what V19 actually ran. They are **not** a production
> admission threshold, not a candidate size policy, and not a proposed
> gate. Nothing should ever read them as "candidates below 2 M
> parameters are acceptable" or "1.5 GB is a limit". They exist only to
> stop a too-small run from being reported as evidence about pair
> safety, and they have no meaning outside that judgement.

**Neither is a plugin**, so both are structurally forced by
`--force_model` (§21.1) and neither can drift to another architecture.
Determinism class stays **B** for each chain: architecture fixed,
hyperparameters planner-selected and recorded.

### 23.2 The two commands

Both are the A5 family — the real `HyperparamTuningAgent.run()`
reaching `run_production_preflight` at `tuner:2864`. No baseline path,
no seed, no plugin, no adapter-direct call, no time budgets (F2).

**Chain A — arch-like**

```bash
cd /home/yuema137/SIDERIUS

timeout --signal=INT --kill-after=120 3600 \
  .venv/bin/python \
  nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py \
  --force_model wavenet \
  --provider openai --model_id gpt-5.5 \
  --reflect_provider openai --reflect_model_id gpt-5.5 \
  --run_name a6_arch_v1 \
  --workspace /home/klz/Data/SIDEREIS_DATA/a6_arch_v1 \
  --is_trial --max_rounds 1 --attempts_per_formal_round 1 --max_epochs 1 \
  --formal_portion 0.2 --formal_train_portion 1.0 --formal_eval_portion 0.05 \
  --formal_vram_budget_gb 12.0 \
  --data_scope 6 --health_gate_files 6 \
  --cleanup_denoised --progress_bar
```

**Chain B — loss-like**: identical except

```
  --force_model punet
  --run_name a6_loss_v1
  --workspace /home/klz/Data/SIDEREIS_DATA/a6_loss_v1
```

As in A5 both are executed from a bash array with `printf '%q'` of the
resolved argv, so a missing shell continuation is structurally
impossible, and every flag is re-checked against live `--help` before
launch.

### 23.3 Launch order and stagger

**Stagger = 0. Launch both within the same second.** V19 ran them
uncoordinated and concurrent; any stagger we impose is a scheduling
policy V19 did not have, and with 79-second runs even a 30 s stagger
could push the training windows apart and reproduce F4. The sampler is
started first and keeps running across both.

### 23.4 Expected process layout

Per chain: parent (expected **absent** from compute-apps, as in A5),
one pre-flight worker (transient, likely below the sampling window),
one training child, one inference child. Across the pair, concurrent
training and concurrent inference are expected and allowed. Within a
chain, pre-flight must not overlap its own training.

### 23.5 Caps

| | Value |
|---|---|
| Wall cap per chain | 3600 s (`SIGINT`, `SIGKILL` after 120 s) |
| LLM calls | <= 3 per chain, <= 6 total (`attempts_per_formal_round 1`) |
| Cost | < $0.40 total |
| Per-attempt VRAM cap | 12.0 GiB each (`--formal_vram_budget_gb`) |
| Configured pair aggregate | 24.0 GiB vs 28.0 ceiling — pre-checked by the `pair_admission` CLI |
| Host RSS | unchanged production `RLIMIT_AS`: train 40 / infer 60 / score 24 GiB |
**Runtime thresholds (operator decision 2026-08-01, corrected):**

| Line | Value | Behavior |
|---|---|---|
| Warning | **26 GiB = 26,624 MiB** | record and keep running; explain in the report |
| **A6 safety failure** | **28 GiB = 28,672 MiB** | record the exact PID/chain breakdown, graceful-stop both chains, classify A6 as failed for pair-level safety |
| Emergency | **29,000 MiB** | immediate escalation |
| Host quota | **30,000 MiB** | never intentionally reached; never waited for |

The failure line is the campaign ceiling **itself**, not a margin above
it. An earlier draft put the hard stop at 28.5 GiB; that was wrong,
because a validation which permits itself past the limit it exists to
validate is measuring a policy nobody runs. Crossing 28,672 MiB is not
a monitoring event — it is the A6 result.

The stop fires **before** the 30,000 MiB host watchdog, so the run ends
by our hand with attribution intact rather than being SIGTERMed from
outside with none.

### 23.6 Stop monitor — exact behavior

```
every 0.2 s:
    sample nvidia-smi --query-compute-apps=pid,used_gpu_memory
    aggregate := sum of used_gpu_memory over PIDs OWNED by the pair
    if aggregate >= 29,000 MiB:  emergency stop
    elif aggregate >= 28,672 MiB: A6 SAFETY FAILURE -> graceful stop
    elif aggregate >= 26,624 MiB: warn once, keep running

graceful stop:
    record the exact PID/chain/MiB breakdown at the trip
    SIGINT the two recorded parent PIDs
    wait 30 s; SIGKILL any surviving OWNED pid
    exit 3; never restart, resize or retry
```

**Ownership is decided by the ppid ancestry chain, not the session id.**
The pre-flight worker is spawned with `start_new_session=True`
(`isolated_probe.py:412`) and therefore has its *own* session — a
session-leader test would fail to claim it, and its memory would go
uncounted in the very aggregate this monitor exists to bound. The
monitor walks `/proc/<pid>/status` `PPid` upward (bounded to 24 hops)
and claims a PID if either captured parent is an ancestor.

Verified on this host before the package was submitted: both parents
claimed, their children claimed, `init` and an unrelated shell
correctly **not** claimed.

Safety properties, and how each is guaranteed:

- **It can only ever signal the validation pair.** The only PIDs it may
  signal are the two captured at launch from `$!`. It never derives a
  target from a name match, a `pgrep`, or the sample rows — a foreign
  process appearing in the samples raises the aggregate but is never a
  signal target.
- **A foreign process cannot cause a kill of our pair either**, because
  the aggregate counts only PIDs whose session leader is one of our two
  parents. A foreign process instead trips the idle-GPU precondition
  and invalidates the run (§23.8), which is the correct outcome.
- **It never restarts, resizes or retries.** A6 is observational.
- It is a sibling process, not a parent of either chain, so stopping
  the monitor cannot affect a running chain.

**What it cannot do.** A 0.2-second external sampler reduces risk; it
does not guarantee it. A single large allocation can take the pair from
under the warning line to over the quota between two samples, and the
host watchdog is not coordinated with this monitor and may act first.
The monitor is a bound on *expected* exposure, not a guarantee.

If the host watchdog acts first: preserve all evidence, classify A6 as
**failed**, and do **not** treat the kill as evidence about either
candidate — a SIGTERM from a quota enforcer says something about the
aggregate, not about the model. Do not retry.

### 23.7 Telemetry

Same read-only sampler as A5 (per-PID ~6.6 Hz measured, device total
~0.65 Hz, process tree every 5 s), extended with a PID-to-chain map
built from each PID's session leader so every sampled PID is attributed
to a run name and a role. Persisted under
`/home/klz/Data/SIDEREIS_DATA/a6_evidence_<date>/`: raw samples, the
PID-role map, phase transitions, per-process peaks, per-chain peaks,
the pair peak, cleanup evidence and both analyzer reports.

**Not claimed:** `torch.cuda.max_memory_allocated` / `max_memory_reserved`
and per-subprocess PyTorch peaks. Production still does not persist
them (§21.6); driver-visible per-PID memory is the measurement.

### 23.8 Pass criteria

A6 passes only if **all** hold:

1. both parents remain absent from `--query-compute-apps`, peak 0 MiB;
2. each chain's pre-flight worker executed (artifact channel) and exited;
3. no chain overlaps its own pre-flight with its own training;
4. **concurrent training was actually observed for at least 5
   continuous seconds** — both chains' training children active
   together, measured by the analyzer as the summed intersection of
   their training windows. Training/inference overlap may be reported
   as supplementary evidence but **does not substitute** for it;
5. pair aggregate stays below **28,672 MiB**, and the 26,624 MiB
   warning is either never reached or explained;
5b. both chains are **V19-scale** by §23.1.1;
6. host quota never approached;
7. no orphan; GPU returns to baseline;
8. no contention-attributable candidate evidence;
9. artifacts remain compatible on both chains, including
   `memory.vram_budget_gb == 12.0`.

If 1-3 and 5-9 hold but **4 does not**, the verdict is
`A6 INCONCLUSIVE`, not a pass: the pair aggregate was never actually
exercised, and a comfortable number from non-overlapping phases would
be a false reassurance of exactly the kind §1.3 warns about.

Verdict vocabulary — the analyzer emits exactly one:

```text
A6 PASS — PR A READY TO MERGE; PR B NOT REQUIRED FOR SAFETY
A6 PASS — PR A READY TO MERGE; PR B STILL RECOMMENDED FOR TELEMETRY
A6 INCONCLUSIVE — NO REPRESENTATIVE OVERLAP
A6 LIFECYCLE VALIDATION ONLY — LOAD NOT REPRESENTATIVE
A6 FAIL — PR B REQUIRED BEFORE V20 LAUNCH
A6 FAIL — PR A REPAIR REQUIRED
```

Only the two `A6 PASS` verdicts may inform a decision about PR B's
necessity. The middle two mean the run could not decide it.

#### 23.8.1 Production boundary — what A6 does NOT establish

State this in the A6 report verbatim, whatever the verdict:

- `core/runtime_control/pair_admission.py` has **zero production
  callers** (F3 / FU-A-12). The 28 GiB ceiling is a configured
  expectation, not a runtime protection.
- The A6 sampler and stop monitor are **validation infrastructure
  only**. They are not a production pair guard and must not be
  described, reused or counted as one.
- **A6 does not prove that production has a live aggregate GPU guard.**
  It cannot: no such guard is wired.

So even the most favourable outcome supports at most: *PR A removes the
practical pair-level risk under representative load, and PR B may be
reduced to telemetry and attribution.* The absence of a wired pair
guard remains an open item on its own, independent of PR B's fate, and
does not disappear because a two-chain run measured a comfortable
number.

### 23.9 OOM attribution

If a CUDA OOM occurs, record at once: failing PID, its own device
memory, the peer chain's device memory, pair total, free device memory,
the failing phase, and whether the peer held substantial memory at that
instant. **Do not treat an OOM as candidate evidence merely because its
exception type is CUDA OOM** — that is precisely the V19 misattribution
(9.20 GiB free = genuine; 125.94 MiB free = contention). Do not resize
and do not retry.

### 23.10 Stop conditions

Stop and return without retry for: a parent appearing in compute-apps;
pre-flight/training overlap within a chain; pair aggregate >= 28,672 MiB;
any `PreflightWiringError`; a malformed or missing worker artifact;
`memory.vram_budget_gb != 12.0` on either chain; an orphan; a foreign
GPU process at any point; host-watchdog intervention; or the GPU
failing to return to baseline.

### 23.11 Pre-launch gate

HEAD is the reviewed PR #152 head with a clean tree and green CI; PR
#152 unmerged; **both** workspaces absent; `--query-compute-apps`
empty and the device at its 273 MiB baseline; no stale tuner, worker,
training, inference, sampler, monitor or analyzer process; both
commands validated against live `--help`; the `pair_admission` CLI
returns feasible for the configured caps; evidence directory unique and
persistent.

**Not executed. Awaiting operator review.**

## 24. A6 result — executed 2026-08-01

Both chains launched in the same second at head `7072448` (code
byte-identical to the CI-green `2581f09`), on an idle GPU, one run only.

### 24.1 Measured

| | Chain A `wavenet` | Chain B `punet` |
|---|---|---|
| realized params | 302,784 | 6,762,568 |
| pre-flight estimate | 6.429 GB | 1.655 GB |
| **driver-visible peak** | **12,820 MiB (12.52 GiB)** | 3,076 MiB (3.00 GiB) |
| config sha256 | `384d9da6cf7638d5…` | `967151ec136918e7…` |
| `memory.vram_budget_gb` | 12.0 | 12.0 |
| contract check | 10/10 | 10/10 |
| wall | 256 s | 256 s |

```
parents (PID 1898443 / 1898444)   0 MiB — never in --query-compute-apps
concurrent training               125.9 s   (hard criterion >= 5 s)
pair aggregate peak               15,896 MiB = 15.52 GiB
                                  vs V19's pair 28,732 MiB = 28.05 GiB
intra-chain preflight x training  0 co-resident samples
FOREIGN processes                 0
warning / failure / emergency     none reached
orphans                           none; GPU back to 273 MiB baseline
LLM                               5 calls total, < $0.40
2,955 samples over 295 s
```

The representativeness rule earned its shape here: `wavenet` realized
only 302 k parameters but a **6.43 GB** estimate, so a parameters-only
test would have classified the heavier of the two chains as
unrepresentative. Both qualified — B on parameters, A on estimated VRAM.

**Scientific outcome, which A6 does not validate**: both chains ended
`failed_mode_collapse` (HealthGate `output_diversity`: wavenet 3 unique
int8 values on file 6, punet 19, threshold >25). Training and inference
executed in full (147 s / 133 s), so the memory measurement is
unaffected — the collapse was detected after the GPU work. Separately,
chain B's skipped attempt is recorded as `skipped_time_risk` when the
actual cause was the §5 batch-size guardrail; a pre-existing label
inaccuracy, not introduced here.

### 24.2 The finding that decides PR B

Chain A was **admitted at a 6.43 GB estimate and then held 12.52 GiB —
past the 12 GiB per-attempt cap it was admitted under.**

Admission compares a predicted *allocated* peak; the host quota counts
driver-visible *reserved*. They are different quantities, so

```text
estimated <= 12 GiB   does NOT imply   driver-visible <= 12 GiB
```

Observed ratios: 1.95× (A) and 1.82× (B). **Two samples do not
establish a scaling constant.** They show the estimate cannot protect a
driver-visible quota; they do not license multiplying any estimate by
~1.9 to predict a total. An earlier draft of this report projected
"2 × 12 × 1.88 ≈ 45 GiB" — usable as a risk illustration, not as a
result, and recorded here so it is not quoted as one. PR B must
**measure** the aggregate.

A6's pair was safe because the candidates were small relative to the
cap, not because a mechanism made them so. Both halves of the intended
mechanism are absent: the per-attempt cap does not bound actual usage,
and `pair_admission.py` — which defines the 28 GiB ceiling — has zero
production callers, so during A6 the only thing between the run and the
host watchdog was an external validation monitor that is not part of the
product.

### 24.3 Verdict

```text
A6 PASS — PR A READY TO MERGE; PR B REQUIRED BEFORE V20 LAUNCH
```

Not `PR B NOT REQUIRED` — the analyzer's mechanical verdict said that,
keyed only on the aggregate sitting under the warning line, and it is
wrong for the reason in §24.2. Not `PR A REPAIR REQUIRED` either: PR A
does exactly what it set out to do, and the parent redundancy is gone.

```text
PR A removed the redundant parent memory.            DONE, validated.
PR B must make the remaining real total controlled   REQUIRED.
at runtime.
```

**Production boundary, restated:** `pair_admission.py` has zero
production callers; the A6 sampler and stop monitor are validation
infrastructure only; **A6 does not prove that production has a live
aggregate GPU guard**, because none is wired.

### 24.4 Correction — the V19 comparison baseline

The analyzer originally printed A6's *pair* peak against V19's
**17.74 GiB**, which is V19's single loss-chain tree (parent 8,944 MiB +
training child 9,222 MiB), not its pair. The correct pair-to-pair
comparison is **15.52 GiB vs 28.05 GiB** (28,732 MiB, §6.3), which also
means V19 exceeded the 28 GiB ceiling while A6 stayed 12.5 GiB under it.
Fixed in the analyzer and in this record; the understated figure
appeared in the first A6 report and is corrected here.
