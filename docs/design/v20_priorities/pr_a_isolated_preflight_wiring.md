# Design: V20 PR A — Wire Isolated Pre-flight into Production

- **Status**: **APPROVED for implementation** 2026-07-31 — audit
  complete, all five decisions resolved (§16). No production code has
  been modified by this document.
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
2. **Runtime** — after a full pre-flight, `torch.cuda.is_initialized()`
   is `False` in the parent (or `torch` is absent from `sys.modules`).
3. **Observational** — during the §13 GPU validation, the parent PID
   never appears in `nvidia-smi --query-compute-apps`.

Check 3 is the one that actually failed in V19 and the only one that
exercises the real path.

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
pass:  parent absent from nvidia-smi
       worker releases GPU memory on exit
       no overlap between pre-flight and training
       no orphan
       scientific result path unchanged
```

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
