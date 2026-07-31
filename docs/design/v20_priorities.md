# V20 Priority Decisions

- **Status**: Draft — evidence collection during V19
- **Current campaign**: `v19r3_10iter_20260731_1842`
- **Implementation target**: V20
- **Current V19 policy**: continue unless an explicit stop condition in
  §14 is met
- **Created**: 2026-07-31, from findings during the fresh V19 restart
  after the runtime-estimation (C1-C14) and VRAM-preflight (PR #151)
  repairs
- **Scope of this document**: problem statements, required
  investigations, and candidate solution directions. It authorizes no
  implementation and changes no production behavior.

Every claim below is labelled:

| Label | Meaning |
|---|---|
| **CONFIRMED DEFECT** | Code or artifact evidence shows the system does not do what it was designed to do |
| **CONFIRMED LIMITATION** | The system behaves as designed, but the design does not cover the case |
| **OPEN INVESTIGATION** | Evidence establishes that something happens; the cause is not yet established |
| **HYPOTHESIS** | A candidate explanation with no confirming evidence yet |

---

## 1. Purpose and scope

### 1.1 What V19 validated — do not redesign this

The V19 restart validated the runtime-control safety architecture. These
principles are settled and V20 must preserve them:

- static uncalibrated estimates have **no rejection authority**;
- bounded measurement can be requested when evidence is too weak
  (`REQUEST_PROBE`);
- candidate failures are separated from infrastructure failures;
- CUDA OOM, host-memory excess, hard timeout, inconclusive measurement,
  and infrastructure failure are **separately classified** dispositions,
  each with derived authority — only measured evidence of the matching
  kind may reject;
- isolated per-candidate workers prevent one candidate from killing the
  parent process;
- operator stop terminates the chain loop and does not respawn
  iterations (C13);
- pairwise queue admission and aggregate resource guards are active;
- fresh campaigns do not reuse contaminated trajectory state.

The recurring failure mode these repairs eliminated was always the same
shape: **one signal standing in for something it did not measure** — a
batch-search timeout for capacity, wall time for host memory, address
space for resident memory, "inconclusive" for "a deadline elapsed".
V20 must not reintroduce it.

### 1.2 What V20 must close

V19 closed the gap between *guessing* and *rejecting*. It did not close
the gap between:

```
collecting measurements
```

and:

```
using validated measurements as the final production gate
```

V20's central goal is to close that second gap, plus the resource
observability and campaign isolation work that supports it.

### 1.3 A measured event requires both classification and attribution

V19's repairs established that a signal must not stand in for something
it did not measure. The wave-1 CUDA OOM pair (§6.5) establishes the next
requirement, which is not the same one:

> **A measurement earns authority only when it is both correctly
> classified and correctly attributed.**
>
> Classification asks *what kind of event was this* — CUDA OOM, host
> memory, timeout, inconclusive. V19 solved this.
>
> Attribution asks *what caused it* — the candidate, or conditions the
> candidate did not create. V19 did not address this, and a correctly
> classified measurement with wrong attribution carries full rejection
> authority today.

The arch chain's OOM in §6.5 is the worked example: a real
`torch.OutOfMemoryError`, correctly typed and accurately measured,
produced while the peer chain held two-thirds of the GPU. Every
V19-repaired check passes on it, and it is still not evidence about the
candidate.

This applies symmetrically to the applicability rule in §3: historical
evidence must be shown applicable to the candidate, and live evidence
must be shown attributable to it.

---

## 2. Priority summary

| # | Priority | Observed problem | Why it matters | V20 target behavior | V19 blocker? |
|---|---|---|---|---|---|
| **P0-1** | Calibration promotion never runs | `evaluate_promotions` / `record_promotion` have **zero production call sites** | The learning loop never closes; every decision falls back to `static_uncalibrated` | Promotion evaluated and recorded on the production path | No |
| **P0-2** | Bucket identity: `model_family` is always `unknown` | All 20 observations carry `model_family="unknown"` | Unknown family is its own bucket by design (D5) — it never inherits, so buckets fragment and stay unusable | Real family identity flows into observations | No |
| **P0-3** | Validated calibration is not an admission authority | No consumer treats a validated bucket as the final gate | Operator requirement: dynamic calibration should be the final gate | Validated calibration or a successful live probe is the final gate | No |
| **P0-4** | Calibration-quality reporting | A campaign can collect observations while zero are promotable, silently | "Dynamic calibration is running" was believed true when it was not | Every campaign reports bucketed/eligible/validated/rejected counts | No |
| **P1-1** | GPU-memory telemetry incomplete | Estimate (2.00 GB) and `nvidia-smi` (6,962 MiB) are different quantities; neither `max_memory_allocated` nor `max_memory_reserved` is persisted | The estimate-vs-actual gap cannot be attributed | Persist allocated / reserved / driver-visible per process and phase | No |
| **P1-2** | Chain-level GPU aggregation is unbounded | Measured 2026-07-31 19:55Z: loss chain tree **17.74 GiB** against a 12 GiB cap; pair total **28,732 MiB**, past the 28 GiB ceiling, 1,268 MiB from the host quota | The per-chain cap bounds a predicted per-attempt allocation, not what the chain's process tree holds | Define and enforce the cap over the chain's GPU process tree, measured driver-visible; route pre-flight through the existing isolated worker (§6.1) | **Campaign stopped §14.1.** Root cause CONFIRMED (§6.1): the parent's share is the in-process pre-flight, never released |
| **P1-3** | Production host-memory telemetry absent | Peak RSS, RSS timeline, and phase attribution are not persisted on the production path | The 17M dilated-conv question cannot be settled from artifacts | Bounded RSS telemetry with phase attribution | No |
| **P1-4** | Long-sequence preflight memory amplification | A 17M candidate reached ≈26 GiB process-tree RSS in preflight | Unresolved between genuine requirement and inspection amplification | Phase-level bounded measurement to distinguish A from B | No |
| **P2-1** | Campaign-scoped stop and queue state | A previous campaign's queue-level `STOP` blocked a new campaign's launch | One campaign's terminal state has authority over another | All control state under `<campaign_root>/<campaign_id>/control/` | No |
| **P2-2** | Portable host-memory configuration | The 24 GiB worker threshold is derived for one machine | Not portable; environment-only control is weak for reproducibility | Backward-compatible layered config with recorded provenance | No |
| **P2-3** | Model-scale and downsizing-bias monitoring | Iteration 1 proposed 2.39M / 4.12M against advice suggesting 10M-100M | The original V19 failure expressed itself as systematic shrinking | Campaign-level scale-trend reporting | No — monitor per §14 |

---

## 3. P0-1/P0-3 — Admission must rest on measured evidence for the concrete candidate

> **The governing rule (operator formulation, 2026-07-31).**
>
> The final admission decision must be based on **measured evidence for
> the concrete candidate**. Validated calibration may serve as that
> evidence **only when its applicability to this candidate is
> established**; otherwise a bounded live probe of this candidate is
> required.
>
> This is deliberately *not* "dynamic calibration is always the final
> gate". Predicting whether an unseen architecture will fit from history
> alone is neither reliable nor a goal. Calibration's job is to scope
> the probe, avoid redundant measurement, and inform similar workloads —
> not to substitute for measuring a candidate that differs materially
> from anything in the bucket.

### 3.0 What is already achieved, and what is not

| Property | Status |
|---|---|
| A static estimate cannot reject a candidate | **achieved** |
| A probe can be requested when evidence is too weak | **achieved** |
| When a probe runs, its measurement decides | **achieved** |
| Every formally admitted candidate has applicable measured evidence | **not achieved** |

The remaining gap is precisely the `ADVISORY` path. `ADVISORY` means
"informational only; execution proceeds unaffected", so a candidate can
reach formal execution having never been measured, with the trial wall
clock or the watchdog as the only backstop. That is a safe *failure*
mode, not a correct admission.


### 3.1 Observed problem

**CONFIRMED DEFECT.** Measured on the live registry
(`/home/yuema137/.siderius/runtime_calibration`) at 2026-07-31 ~19:50
UTC, while `v19r3_10iter_20260731_1842` was running:

```
observations        : 20   (18 thirty minutes earlier — actively growing)
promotions recorded :  0
bucket status       : every bucket "unvalidated"
```

Consequently every runtime decision observed in the live chain logs
carried `evidence static_uncalibrated`, e.g.:

```
arch : Est 237.8 min / budget 120.0  →  policy REQUEST_PROBE, evidence static_uncalibrated
loss : Est 244.3 min / budget  20.0  →  policy ADVISORY,      evidence static_uncalibrated
loss : Est  42.9 min / budget  20.0  →  policy ADVISORY,      evidence static_uncalibrated
arch : Est  14.4 min / budget  20.0  →  policy ALLOW,         evidence static_uncalibrated
```

### 3.2 Root cause — corrected

An earlier reading of a single observation record suggested
`bucket_key = None`. **That reading was wrong** and is recorded here so
the error is not inherited by V20 planning. `bucket_key` is not a stored
field; it is derived by `calibration_policy.py:311` from seven
components. Recomputing it over the live registry shows bucketing works
correctly:

```
n=5  training |optimizer_step |foreign_contended     |…|unknown|stack:44136fa355b3
n=5  inference|inference_batch|foreign_contended     |…|unknown|stack:44136fa355b3
n=4  inference|inference_batch|single_candidate_idle |…|unknown|stack:44136fa355b3
n=4  training |optimizer_step |single_candidate_idle |…|unknown|stack:44136fa355b3
n=1  training |optimizer_step |single_candidate_idle |…|unknown|stack:cb380df61b90
n=1  inference|inference_batch|single_candidate_idle |…|unknown|stack:cb380df61b90
```

Two corrections follow from this:

- concurrency identity is **not** uniformly `foreign_contended` — four of
  six buckets are `single_candidate_idle`. The earlier claim came from
  sampling one record;
- bucket keys are well-formed, and several buckets already hold 4-5
  observations.

The actual defect is narrower and more actionable:

> **`evaluate_promotions` and `record_promotion` are called only from
> tests.** A repository-wide search excluding `tests/` and `.venv`
> returns exactly one non-test hit — the definition itself
> (`calibration_policy.py:463`) and the registry method
> (`calibration_registry.py:204`). No production code path evaluates or
> records a promotion.

The registry collects observations correctly, derives buckets correctly,
and never promotes any of them, because nothing asks it to.

### 3.3 Secondary defect — `model_family` is always `unknown`

**CONFIRMED DEFECT.** All 20 observations carry `model_family="unknown"`.
Per the `bucket_key` docstring, this is deliberate isolation, not a
fallback:

> "Unknown family is its own bucket (D5) — it never inherits a known
> family's calibration."

So even once promotion runs, `unknown` buckets carry calibration that
applies to nothing else. Both defects must be fixed together; fixing
promotion alone would validate buckets that cannot generalize.

Population sites to audit (`model_family=` non-test call sites):

- `core/runtime_control/observation_store.py:129` — `str(ctx["model_family"])`
- `agent/skills/evaluate_time_skill/wrapper.py:499` — `model_type`
- `core/runtime_control/probe.py:555`
- `core/runtime_control/probe_wiring.py:170`

### 3.4 Why this matters

The governing invariant is:

```
before implementation:  runtime estimates are priors
after  implementation:  runtime decisions are measurements
```

The current system satisfies the first half and not the second. It is
**safe but unable to learn**: it will not reject on a guess, but it also
cannot allow on evidence, so it re-probes indefinitely or defers to the
watchdog.

The operator requirement (2026-07-31) is explicit:

> Dynamic calibration data should be the final gate that decides whether
> a candidate is admitted.

`ADVISORY` must not remain a long-term production state meaning "no
trustworthy evidence, proceed anyway".

### 3.5 V20 target behavior — authority layering

```
static / historical prior
  → decides only WHETHER TO MEASURE      (never a final gate)

validated calibration
  → applicability to THIS candidate must be established first
  → if established : may serve as the measured evidence
  → if not         : a bounded live probe is required

bounded live probe of this candidate
  → succeeded    : its measurement is the final gate — ALLOW / REJECT
  → inconclusive : no ALLOW and no REJECT from runtime evidence;
                   follow an explicit retry / fallback / stop policy
```

Authority rules:

| Evidence | May ADVISE | May REQUEST_PROBE | May finally ALLOW | May REJECT |
|---|---|---|---|---|
| static prior (tier 0) | yes | yes | **no** | **no** |
| historical prior alone (tier 1) | yes | yes | **no** | **no** |
| validated calibration, applicability **not** established | yes | yes | **no** | **no** |
| validated calibration, applicability established | yes | — | yes | yes, subject to §3.6 |
| successful bounded live probe | yes | — | yes (this candidate) | yes (measured OOM / measured peak over cap / optimistic bound over budget) |
| inconclusive probe | yes | yes | **no** | **no** |

Two requirements follow that the current system does not meet:

1. **`ADVISORY` must not be a terminal state for a formally admitted
   candidate.** It may route to measurement; it may not stand in for it.
2. **Applicability must be an explicit, checkable predicate**, not an
   assumption that a matching bucket key implies a matching workload.
   Deciding what establishes applicability — architecture family,
   parameter scale, sequence length, batch, distance from the bucket's
   observed range — is open question 7 in §3.6.

An inconclusive probe must not silently become either allow or reject.
The fallback policy for inconclusive evidence must be explicit and
written down, not implied by control flow.

### 3.6 Questions V20 must resolve

Do not guess these during implementation — they are design decisions:

1. Which fields define a calibration bucket, and which are mandatory?
2. How is missing bucket identity handled — reject the observation at
   write time, or persist it in an explicit `unbucketed` state?
3. Can an observation with `model_family="unknown"` ever be promoted, or
   is it permanently non-authoritative?
4. Can contended observations be promoted, or only idle ones?
5. Minimum observation count and consistency threshold for promotion
   (this is open decision **D4**).
6. Does validated calibration expire? On what — time, generation, stack
   change, hardware change?
7. Hardware and workload matching rules for applying a bucket to a new
   candidate.
8. When a live measurement contradicts validated calibration, which
   wins, and does the calibration get invalidated?
9. May validated calibration **reject** a candidate outright, or only
   allow — with rejection still requiring a live measurement? (The
   conservative reading of §1.1 argues for the latter; this is an
   operator decision.)

---

## 4. P0-2 — Calibration bucket identity and promotion

### 4.1 Required investigation

Trace the full path and identify precisely where identity is lost:

```
candidate implementation
  → workload metadata
  → hardware provenance
  → concurrency identity
  → observation creation
  → bucket-key derivation
  → registry write
  → promotion evaluation      ← currently absent in production
  → admission consumer        ← currently never reads a promotion
```

Check whether each of these is populated and stable in production
observations: model family; realized parameter count; architecture /
config identity; batch size; segment length; training vs inference
phase; data portion; hardware identity; dtype; concurrency identity;
peer identity; software / runtime stack version.

Known from the live registry: hardware id, execution environment id,
concurrency identity, operation, unit, and stack identity **are**
populated. `model_family` is not.

### 4.2 Concurrency identity

**CONFIRMED LIMITATION.** The vocabulary is
`single_candidate_idle` / `pairwise_expected_peer` /
`foreign_contended`. Live data contains the first and the third but not
the second: when two campaign chains run concurrently, the peer is
classified as foreign rather than as an expected peer.

This is the carry-forward C12 finding **F-1** (`pairwise_expected_peer`
unreachable when the peer computes). It is conservative and safe — it
never claims a controlled concurrency condition it did not have — but it
collapses two genuinely different conditions into one bucket.

V20 should evaluate peer-aware queue registration so that the campaign's
own paired chain is recognized as an expected peer, with campaign and
pair identity propagated into the probe.

### 4.3 Candidate solution directions

Evaluate, do not assume:

- a typed canonical bucket-key builder with mandatory-field validation;
- validation of bucket identity **before** observation persistence, so
  an unusable observation is rejected loudly rather than stored;
- an explicit `unbucketed_observation` state rather than silent
  degradation;
- promotion rejection carrying a machine-readable reason;
- peer-aware queue registration (§4.2);
- separate buckets retained for idle / expected-peer / foreign /
  unknown contention.

**Non-goal**: do not promote incomplete observations merely to increase
coverage. A validated bucket built from unidentified observations is
worse than no bucket, because it would carry authority it has not
earned.

---

## 5. P1-1 — Complete GPU-memory telemetry

### 5.1 Observed problem

**CONFIRMED LIMITATION.** Preflight estimated:

```
arch : 2.00 GB / cap 12.00 GB
loss : 2.09 GB / cap 12.00 GB
```

`nvidia-smi` during production training (19:36 UTC) reported:

```
pid 1422046   6,962 MiB   arch  (chain parent)
pid 1430174   6,962 MiB   arch  (sandbox child)
pid 1431162   1,626 MiB   loss
GPU total    15,839 MiB / 32,607 MiB
```

These are **not the same quantity**, so the ratio is not an error
measurement:

- the estimate composes
  `params + forward_activation + cuda_context` (`batch_resolver.py:67`)
  — a predicted **allocated** peak;
- `nvidia-smi used_gpu_memory` reports what the process holds from the
  driver — CUDA context plus the PyTorch caching allocator's **reserved**
  pool, which retains freed blocks and grows with allocation history.

**OPEN INVESTIGATION**: how much of the arch gap is caching-allocator
reservation versus a genuine estimate shortfall. This cannot be settled
from current artifacts, because neither `max_memory_allocated()` nor
`max_memory_reserved()` is persisted anywhere on the production path.

### 5.2 Required measurements

Persist per process and per chain, stamped with phase and timestamp:

| Quantity | Source |
|---|---|
| peak allocated | `torch.cuda.max_memory_allocated()` |
| peak reserved | `torch.cuda.max_memory_reserved()` |
| current allocated | `torch.cuda.memory_allocated()` |
| current reserved | `torch.cuda.memory_reserved()` |
| driver-visible process memory | NVML / `nvidia-smi` |
| chain aggregate driver-visible | sum over the chain's GPU process tree |
| pair aggregate driver-visible | sum over both chains |

Phases: model construction, preflight, trial training, formal training,
evaluation, inference, cleanup.

### 5.3 Which metric has authority

The three metrics answer different questions and V20 must not conflate
them:

- **allocated** — what the candidate's tensors actually need. This is
  the scientific quantity, and the right basis for calibration and for
  cross-candidate comparison.
- **reserved** — what PyTorch holds. Useful for diagnosing fragmentation
  and allocator behavior.
- **driver-visible** — what the driver, other processes, and the host
  watchdog see.

The host enforces an external ~30,000 MiB (29.30 GiB) per-user quota by
summing driver-visible usage and SIGTERMing the highest PID. It killed a
C12 probe on exactly this line. Therefore:

> The pair-level operational safety check must be based on
> **driver-visible aggregate** usage. Allocated peaks alone cannot
> protect against the host quota.

Separate the two concepts explicitly in the design: the *scientific
candidate VRAM requirement* and the *operational driver-visible GPU
occupancy*. Never present a predicted allocated peak and an
`nvidia-smi` reading side by side without labelling which is which.

---

## 6. P1-2 — Chain-level and pair-level GPU aggregation

### 6.1 Observed problem

**CONFIRMED LIMITATION.** Process inspection at 19:52 UTC resolved the
duplicate-process question:

```
pid 1422046  ppid 1422045  pgid 1422005  etime 01:07:16
  run_one_iteration.py --run_name …_arch_15_19          ← chain parent
pid 1437893  ppid 1422046  pgid 1437893  etime 00:10:04
  execute_tools/inference_single.py -m wavenet_full_…   ← sandbox child

pid 1422756  ppid 1422755  pgid 1422720  etime 01:05:43
  run_one_iteration.py --run_name …_loss_15_19          ← chain parent
pid 1441190  ppid 1422756  pgid 1441190  etime 00:06:42
  execute_tools/train_engine_sandbox.py                 ← sandbox child
```

The two arch processes were **the chain parent and its sandbox child**,
not a leak and not a stale process. This is expected architecture.

What is **not** covered by design: the chain parent
(`run_one_iteration.py`) holds a CUDA context of its own, measured at
6,962 MiB. Combined with its child, one chain held ≈13.6 GiB against a
**12 GiB per-chain cap**.

**CONFIRMED DEFECT — traced and measured 2026-07-31.** The parent's
6.9 GiB is the in-process VRAM pre-flight, never released.

The call path (all non-test, traced on `195a9a1`):

```
run_one_iteration.py                      ← no torch import of its own
 └ workflows/model_exploration.py:56       from … import run_workflow   (in-process)
    └ HyperparamTuningAgent.run()                                        (in-process)
       ├ _run_skill("evaluate_vram_skill")   tune_agent:1041-1048
       │    importlib.import_module(...).run_skill(sandbox, ...)   ← IN-PROCESS call
       │    evaluate_vram_skill/wrapper.py:49   import torch
       │    evaluate_vram_skill/wrapper.py:225  cuda_context_bytes()  → CUDA context
       │    batch_resolver searches batch sizes upward → allocates to a high-water mark
       │    wrapper.py:558  del model_for_train, …   ← frees Python refs only
       │    (no torch.cuda.empty_cache() anywhere in the skill)
       │                          ⇒ caching-allocator reserved pool held for the
       │                            entire life of the chain parent
       ├ sandbox_executor → subprocess train_engine_sandbox.py   ← releases on exit
       └ sandbox_executor → subprocess inference_single.py       ← releases on exit
```

Training and inference are `subprocess.Popen` and give everything back
when they exit. **Only the pre-flight runs in the parent, and only its
memory persists.**

**Measured confirmation.** A falsifiable prediction was registered before
the evidence existed: if this diagnosis is right, the parent must keep
its memory after its child exits. The wind-down of the arch chain, alone
on the GPU with no contention, sampled every 15 s:

```
20:56:12  total=7240  pid=1422046  mem=6962   ← child already exited
   …      13 consecutive samples, 3 minutes
20:59:15  total=7240  pid=1422046  mem=6962
20:59:30  total=273   ALL_GPU_PROCS_EXITED    ← parent exits, GPU returns to baseline
```

| Prediction | Supports diagnosis if | Measured |
|---|---|---|
| parent holds ~6.9 GiB after child exits | yes | **6,962 MiB, unchanged** ✓ |
| parent memory does not vary with child phase | yes | one value ever observed: 6,962 ✓ |
| parent memory fixed from early on | yes | constant across all sampling ✓ |
| GPU returns to baseline once parent exits | yes | 273 MiB ✓ |

All four hold. The 6.9 / 8.9 GiB difference between the two chains is
consistent with the batch search reaching different high-water marks.

**The fix already exists and is already GPU-validated.** PR #151 built
`run_isolated_preflight` (`isolated_probe.py` + `preflight_worker_main.py`)
precisely to run pre-flight in its own process. Its only non-test call
site is `scripts/vram_preflight_validation.py` — **zero production call
sites**. Routing the production pre-flight through it should remove the
parent's CUDA context entirely.

> **This is the same structural defect as P0-1, in a second subsystem.**
>
> | | built | unit-tested | GPU-validated | wired to production |
> |---|---|---|---|---|
> | calibration promotion | ✓ | ✓ | — | **✗** |
> | isolated pre-flight worker | ✓ | ✓ | ✓ | **✗** |
>
> Two components, both correct, both unreachable from the code that
> needs them. §18 states the rule this violates: a unit test proves the
> function works and cannot prove production calls it. V20 should add a
> reachability check for both.

**Not yet measured**: the predicted pair total after the fix. An earlier
draft estimated ~12.5 GiB; that is arithmetic, not evidence, and must be
confirmed by a bounded single-chain GPU validation after the wiring
lands. Note also that the 17.74 GiB loss-chain tree was measured *under
contention* — the caching allocator grows opportunistically, so a
standalone peak could be higher, not lower. Serial-execution safety is
therefore also unproven.

### 6.2 The cap does not mean what it appears to mean

The 12 GiB per-chain cap is currently enforced at **candidate admission**
— it bounds what one attempt is predicted to need. It does not bound the
sum of what all processes owned by that chain hold at the same time.

V20 must define resource scope explicitly, at every level:

| Scope | Currently bounded? |
|---|---|
| per process | implicitly, by the candidate estimate |
| per candidate attempt | yes — the 12 GiB admission cap |
| per chain process tree | **no** |
| per concurrent pair | predicted only (2 × 12 = 24 GiB against a 28 GiB ceiling) |
| per user on the host | externally, by the root watchdog at 29.30 GiB |

Recommended investigation target: the per-chain limit should normally
apply to the chain's **complete GPU process tree**, and the pair guard
should use the aggregate of both trees measured from driver-visible
usage.

### 6.3 Margin — hypothesis confirmed within the hour

At 19:36 UTC the position looked comfortable:

```
pair guard predicted : 24.00 GiB   (2 × 12, ceiling 28.00)
measured actual      : 15.5 GiB
host quota           : 29.30 GiB
```

At 19:55 UTC — nineteen minutes later, same campaign, same iteration —
the measured position was:

```
arch parent  6,962 MiB  +  arch child (inference)  3,310 MiB  = 10,272 MiB (10.03 GiB)
loss parent  8,944 MiB  +  loss child (training)   9,222 MiB  = 18,166 MiB (17.74 GiB)
                                                       total  = 28,732 MiB (28.05 GiB)
```

Sampled five times over 40 s: **stable at 28,732 MiB**, not a transient
peak. This is **CONFIRMED**, and it upgrades P1-2 from a modelling gap
to an observed one:

| bound | value | measured | status |
|---|---|---|---|
| per-chain cap | 12 GiB | loss tree **17.74 GiB** | **exceeded by 48 %** |
| campaign pair ceiling | 28 GiB (28,672 MiB) | 28,732 MiB | **exceeded by 60 MiB** |
| host quota | 29.30 GiB (30,000 MiB) | 28,732 MiB | 1,268 MiB margin (4.2 %) |

Two facts make this more than a bookkeeping breach:

1. **The chain parents hold 15,906 MiB between them — 55 % of all GPU
   memory in use.** Two processes whose job is to orchestrate
   subprocesses account for more than half the occupancy. Explaining
   this (§6.1) is now the highest-value item in P1-2.
2. **The per-chain admission cap cannot see this.** Both chains were
   admitted against a 12 GiB predicted requirement and are jointly
   holding 28.05 GiB, because the cap bounds a predicted per-attempt
   allocation and nothing bounds the process tree.

The §14 escalation condition was reported to the operator at 19:56 UTC.
**Operator decision: continue the campaign with automated monitoring**,
accepting the risk in §6.4. No campaign state was modified.

### 6.4 The accepted risk

If usage crosses 30,000 MiB the host watchdog SIGTERMs the highest PID.
At the time of the decision that was the loss training sandbox. The
consequence is not only a lost training run:

> A watchdog SIGTERM arrives with **no memory error attached**. That is
> precisely the C12 `transformer@8M-ceiling` signature that was
> originally misattributed — a kill that looks like a candidate failure
> but was a host-quota event.

If such a failure reached the agent misclassified, it could push the
next proposal smaller — the §11.2 third entry point, arriving through
the resource door this document exists to close. V20 must ensure a
host-quota kill is classified as an **infrastructure** event and never
as candidate evidence.

### 6.5 Contention manufactures candidate-level evidence — CONFIRMED

Both wave-1 chains hit a real `torch.OutOfMemoryError` during iteration
1. The two are **not the same kind of event**, and the difference is the
most important thing in this section.

| | loss chain, R1a1 | arch chain, R2a1 |
|---|---|---|
| free VRAM at failure | **9.20 GiB** | **125.94 MiB** |
| this process held | 20.13 GiB | 17.58 GiB |
| the rest of the GPU | mostly free | held by the **peer chain** |
| attributable to the candidate? | **yes** | **no** |
| agent's response | batch 16 → 8, **params unchanged** (7,280,256) | params 2,924,160 → 1,278,944 |

The loss event is exactly what the repaired system is for: a genuine
per-candidate capacity limit, measured, with a correctly targeted
response that reduced batch size rather than model size.

The arch event is the problem. The GPU had **125.94 MiB free out of
31.34 GiB** — the candidate did not exhaust the GPU, the *pair* did. Yet
a measured `torch.OutOfMemoryError` carries rejection authority by
design, so contention was converted into candidate-level evidence that
the system is built to trust.

**This generalizes the applicability rule in §3.** Applicability has two
directions, and only one of them was previously stated:

1. is historical calibration applicable **to this candidate**? (§3)
2. is this measurement attributable **to this candidate**, or to
   conditions it did not create?

A measurement taken while a peer chain held two-thirds of the GPU is not
evidence about the candidate. V20 must record the concurrency conditions
under which every measurement was taken and refuse rejection authority
to a measurement whose failure is not attributable to the candidate —
the same discipline already applied to inconclusive probes.

Note that this is the **third** entry point for resource-driven
downsizing (§11.2), and unlike the first two it is not a
misclassification: the OOM is real, correctly typed, and correctly
measured. Only its *attribution* is wrong.

**Scope note — no systematic shrinking yet.** arch recovered to
2,388,992 in R3 after the post-OOM 1,278,944, and its shrink was
justified in the log by HealthGate collapse evidence
(`output_diversity`, `amplitude_collapse`), not by the OOM. loss moved
7,280,256 → 4,117,792 → 3,774,544 without a resource trigger. This is
**OPEN INVESTIGATION**, not a confirmed downsizing trend.

**Do not change the per-chain policy mid-campaign.**

---

## 7. P1-3 — Production host-memory telemetry

### 7.1 Observed problem

**CONFIRMED LIMITATION.** The isolated-probe validation harness enforces
process-tree RSS at 24 GiB and samples it every 0.25 s. The production
preflight path runs in-process and persists none of:

- peak process-tree RSS;
- an RSS timeline;
- phase-level host-memory attribution.

The live campaign therefore produced no RSS figure at all for either
chain, which is why the observation table in
`reports/v19_fresh_10iter_20260731_1842.md` has that column empty.

### 7.2 V20 target behavior

Persist **bounded** host-memory telemetry — bounded is a requirement, not
a preference, because an unbounded time series would bloat every
workspace:

| field | note |
|---|---|
| `phase` | construction / preflight / trial / formal / eval / inference / cleanup |
| `timestamp` | |
| `rss_gib` | process-tree resident |
| `process_count` | |
| `batch_candidate` | during batch search |
| `event` | threshold crossing, enforcement, cleanup |

Persist peaks and phase transitions always; sample the timeline at a
bounded rate or on events. Record the threshold in force, its
provenance, and the cleanup result.

---

## 8. P1-4 — Long-sequence preflight memory amplification

### 8.1 Observed problem

**OPEN INVESTIGATION.** A schema-valid ~17M-parameter long-sequence
dilated-conv candidate reached ≈26 GiB process-tree RSS during preflight
and was correctly stopped at the 24 GiB limit. The stop was right
behavior: measured host-memory excess is a valid rejection.

What remains unresolved is which of these is true:

- **A** — the memory was genuinely required by the candidate's preflight;
- **B** — the memory was amplified by optional or inefficient inspection
  behavior.

Current evidence cannot distinguish them. A diagnostic attempt on
2026-07-31 was itself kernel-OOM-killed at 56.7 GiB because its
step-wise 8 GiB guard could not interrupt a single large allocation; its
output is **not valid candidate evidence**. The recorded verdict is
**C — insufficient evidence**, and V20 must not inherit A or B as
settled.

### 8.2 Required investigation

Measure bounded, phase-level host memory for: model construction;
parameter counting; training-phase probe; structural tracing; batch
search; bounded CUDA forward; cleanup.

Determine whether growth comes from genuine activation/autograd
requirements, sequence length, an over-large initial batch candidate,
convolution or attention intermediates, structural tracing, optional
human-readable breakdown generation, retained references, duplicate
model construction, or CPU-only surrogate behavior that differs from
production GPU behavior.

### 8.3 Candidate solution directions

Evaluate without presuming the outcome:

- skip optional structural tracing when authoritative measurement is
  already available;
- separate human-readable diagnostics from the admission path;
- use inference mode for inference-only checks;
- start from a small safe batch before searching upward;
- release batch-local data before the next attempt;
- avoid duplicate model construction;
- perform the authoritative bounded measurement on the actual target
  device.

**Non-goals**: do not optimize away a genuine resource requirement, and
do not weaken the 24 GiB boundary. If the candidate really needs 26 GiB
of host memory in preflight, rejecting it is correct and must keep
working.

---

## 9. P2-1 — Campaign-scoped stop and queue state

### 9.1 Observed problem

**CONFIRMED DEFECT.** The first launch of `v19r3_10iter_20260731_1842`
stopped immediately with `QUEUE STOPPED (operator)`. The cause was a
queue-level `STOP` file created at 08:17 when the **previous**
contaminated campaign was stopped, left in the shared `v19/` root:

```
QUEUE_STOP_FILE="${QUEUE_STOP_FILE:-$WS_ROOT/STOP}"
```

The stop mechanism itself worked exactly as designed — C13 correctly
refused to launch. The defect is scope: one campaign's terminal state
held authority over a different campaign.

The file was archived (moved, not deleted) into
`v19r2_10iter_20260731_0750_stop_evidence/` and the campaign relaunched
cleanly.

### 9.2 V20 target behavior

```
<campaign_root>/<campaign_id>/control/STOP
<campaign_root>/<campaign_id>/queue_state/
<campaign_root>/<campaign_id>/pair_summaries/
```

Requirements:

- a stopped campaign cannot block a new campaign;
- old STOP evidence remains preserved and readable;
- no global destructive cleanup is required to start a campaign;
- launchers reject campaign-ID mismatches;
- operator stop remains no-respawn (C13 semantics unchanged);
- historical layouts remain readable, but legacy global state must not
  exercise authority over a new campaign.

---

## 10. P2-2 — Portable host-memory configuration

### 10.1 Observed problem

**CONFIRMED LIMITATION.** `default_worker_memory_limit_bytes()` returns
24 GiB, derived for this host: `2 × 24 + 4 + 1 = 53` of 61.8 GiB. The
derivation is sound for this machine and portable to no other. Control
is currently by environment variable only, which is convenient for
operators and weak for reproducibility.

This is the same portability class the repository rules already govern:
machine-specific values must come from configuration, not from an
implicit assumption about the host.

### 10.2 V20 target behavior

Layered, backward-compatible resolution:

```
CLI
  > environment
  > campaign config
  > server profile
  > opt-in hardware-aware auto mode
  > legacy default
```

Backward-compatibility requirements: absence of new config preserves
current behavior exactly; the existing environment variable keeps
working; the current default is unchanged unless explicitly configured;
existing launchers remain valid; historical manifests remain readable;
auto mode is never enabled globally without separate validation.

Record the resolved value **and its provenance** in every campaign
manifest.

---

## 11. P2-3 — Model-scale and downsizing-bias monitoring

### 11.1 Observed problem

**OPEN INVESTIGATION.** Fresh V19 iteration 1 proposed:

| chain | round | params | event |
|---|---|---:|---|
| arch | R1 a1 | 2,924,160 | completed, score −0.7587 |
| arch | R2 a1 | 2,924,160 | **CUDA OOM** (125.94 MiB free — contention, §6.5) |
| arch | R2 a2 | 1,278,944 | shrink attributed in-log to HealthGate collapse |
| arch | R3 a1 | 2,388,992 | recovered upward |
| loss | R1 a1 | 7,280,256 | **CUDA OOM** (9.20 GiB free — genuine, §6.5) |
| loss | R1 a2 | 7,280,256 | batch 16 → 8, **params unchanged** |
| loss | R2 a1 | 4,117,792 | |
| loss | R3 a1 | 3,774,544 | |

The chains **opened higher than a single-round snapshot suggests** —
2.92M and 7.28M, not the 2.39M / 4.12M visible mid-iteration. The loss
chain's opening proposal approaches the advice's 10M-100M range. A first
report of this campaign quoted the mid-iteration values and understated
the opening scale; the full sequence above supersedes it.

Against the contaminated campaign (2.92M / 0.18M opening), the loss
chain grew ~40×. Two resource failures occurred, both real CUDA OOMs —
zero host-memory triggers, zero timeouts, zero ambiguous
classifications, against 15 timeouts in the contaminated campaign.

There is currently **no confirmed evidence** of resource-driven
systematic shrinking: arch recovered after its post-OOM dip, and loss
reduced params with no resource trigger in the intervening rounds.
Whether the drift from 7.28M to 3.77M is scientific or inherited
pressure is **OPEN**.

### 11.2 The third possible entry point

The original V19 failure was resource pressure expressing itself as
systematic shrinking. Two entry points are now closed (timeout
misclassification, host-memory misattribution). A third is theoretically
open: **time budget**. Observed estimates exceeded budgets substantially
(§3.1) while remaining advisory. If the agent sees those advisories and
shrinks models to fit the wall clock, the same effect returns through a
new door.

**HYPOTHESIS only.** Iteration 1 arch held 2.39M across rounds 1 and 2
with no shrinking observed.

### 11.3 Required V20 analysis

Track across iterations: proposed family; proposed and realized
parameter count; estimated and measured VRAM; estimated and measured
runtime; admission disposition; **the feedback text actually shown to
the agent**; and the next proposal's size.

Determine whether scale is driven by scientific reasoning, advice, time
budget, measured runtime, host-memory failure, VRAM failure,
implementation difficulty, or inherited negative feedback.

**Non-goal**: do not enforce a minimum parameter count. A small model
may be scientifically correct. What requires an explanation is
*persistent* toy-scale exploration against explicit advice.

---

## 12. P0-4 — Calibration-quality reporting

### 12.1 Observed problem

**CONFIRMED DEFECT** (reporting, not computation). The system collected
20 observations while zero were promotable, and nothing surfaced that
fact. It was believed for the entire campaign design phase that dynamic
calibration was active. It was not.

### 12.2 V20 target behavior

Every campaign report must include:

```
observations collected
observations bucketed
observations unbucketed             (with reason)
promotion-eligible observations
validated buckets
rejected promotions                 (with reason per rejection)
coverage by model family / workload / hardware / concurrency identity
```

Every admission log line must state: evidence used; evidence tier;
bucket identity; calibration version; sample count; error statistics;
and which component held final authority.

> A campaign must never imply that dynamic calibration is active when it
> has zero validated buckets.

---

## 13. Priority ordering

**P0 — Calibration authority and identity**

1. Wire promotion evaluation into the production path
2. Fix `model_family` identity at the observation sources
3. Resolve concurrency / peer identity (C12 F-1)
4. Make validated calibration or a live measurement the final gate
5. Add calibration-quality reporting

This is highest priority because it closes the central runtime-control
loop, and because every other runtime decision inherits from it.

**P1 — GPU resource truth**

6. Persist allocated / reserved / driver-visible VRAM
7. Attribute GPU processes to chain and phase
8. Explain the chain parent's ~6.9 GiB CUDA context
9. Enforce or report chain-tree and pair aggregates correctly

**P1 — Host-memory observability**

10. Persist bounded RSS telemetry
11. Attribute memory by preflight phase
12. Resolve the long-sequence amplification question (A vs B)

**P2 — Campaign isolation and portability**

13. Campaign-scoped STOP and queue state
14. Backward-compatible host-memory configuration
15. Opt-in hardware-aware policy

**P2 — Scientific exploration monitoring**

16. Track model-scale trends and feedback effects
17. Detect systematic downsizing bias

---

## 14. V19 continuation policy

None of the findings in this document is an automatic stop condition for
the running campaign.

> **Escalation record — 2026-07-31 19:56 UTC.** The first condition
> below fired: driver-visible aggregate reached 28,732 MiB, past the
> 28 GiB campaign ceiling, 1,268 MiB (4.2 %) from the host quota, stable
> over 40 s (§6.3). Reported to the operator with three options
> (graceful stop of the loss chain; graceful stop of both; continue with
> monitoring). **Operator decision at 19:56: continue with automated
> monitoring**, accepting the §6.4 risk.
>
> **Reversed at 20:15 UTC on new evidence.** The §6.5 contention-OOM
> finding — a real `torch.OutOfMemoryError` produced with 125.94 MiB
> free, attributable to the peer chain rather than the candidate —
> changed the balance: the risk was no longer hypothetical wasted GPU
> time but demonstrated mis-attributed feedback to the agent. **Operator
> decision: stop both chains gracefully.** Stopping both rather than one
> preserves comparability; the two chains would otherwise have run the
> rest of the campaign under materially different resource conditions.

### 14.1 Campaign closeout — verified 2026-07-31 21:00 UTC

**Final verdict: `STOPPED — PAIR-LEVEL GPU CONTENTION`.** Not a candidate
failure and not a runtime-estimation failure — every disposition was
correctly classified and no static estimate rejected anything. The gap is
attribution (§1.3) and aggregate control (§6.2).

C13's three stop layers all behaved as designed:

```
chain   chain_stopped.json ×2, respawn: false
        arch  "stop observed after iteration 1 (iteration exit 0)"    ← ran to completion
        loss  "stop observed after iteration 1 (iteration exit 143)"  ← SIGTERM, 128+15
runner  "chain … STOPPED on request (EXIT=99) — no restart suggested"
queue   "QUEUE STOPPED (operator_stop_requested) at wave 1:
         wave 1 ended under an operator stop — no further wave launched"
        RUNNER_EXIT=99
```

| check | result |
|---|---|
| waves 2-4 | never started |
| GPU after stop | 0 processes, 273 MiB baseline, no stragglers |
| watchdog kills / signal terminations | none |
| CUDA OOM events | exactly 2, both in iteration 1 (§6.5) |
| spend | 645,054 tokens / $1.94 — 1.1 % of the 60M / $180 caps |
| calibration delta | 20 observations, **0 promotions**, 6 buckets, `family=unknown` throughout |

The calibration line is the P0 defect restated as an outcome: a full
two-hour wave of real training produced twenty measurements and advanced
the calibration state by nothing.

**Continue V19 while all of these hold:**

- total driver-visible GPU memory stays safely below the host quota;
- no unexplained foreign contention appears;
- no unexplained GPU process accumulation occurs;
- static priors remain non-authoritative;
- measured failures continue to be correctly classified;
- no systematic cross-family downsizing is observed;
- queue, watchdog, and stop behavior remain healthy.

**Stop and escalate if any of these occur:**

- driver-visible aggregate approaches or exceeds the 28 GiB campaign
  ceiling or the 29.30 GiB host quota;
- a chain accumulates GPU processes beyond the expected parent + one
  sandbox child;
- multiple scientifically reasonable candidates are rejected because
  calibration identity is missing;
- static evidence is observed exercising rejection authority;
- measured evidence is ignored or misclassified;
- host-memory failures repeat across model families;
- calibration or artifact state becomes corrupt;
- operator stop fails to terminate the chain loop;
- any material production defect threatens campaign validity.

---

## 15. Evidence to collect from the remainder of V19

Update this document after the campaign with, per iteration: proposal
scale; realized parameter count; model family; runtime evidence tier;
live probe result; calibration bucket identity; promotion result;
training wall time; allocated / reserved / driver-visible VRAM where
available; process count per chain; HealthGate result; score;
next-iteration scale change; and every resource-related candidate
failure.

**Constraint**: do not modify the running V19 to obtain telemetry it
does not currently produce. Use existing artifacts and read-only
monitoring only. Telemetry that does not exist is itself a V20 finding
(§7), not a reason to touch a running campaign.

---

## 16. Non-goals

V20 priorities do **not** include:

- forcing proposals toward 300M parameters;
- raising resource limits so more candidates pass;
- treating every inconclusive result as a failure;
- removing process isolation;
- weakening host-memory protection;
- restoring rejection authority to static estimates;
- changing the active V19 campaign mid-run;
- redesigning the validated C12-C14 principles without new evidence.

---

## 17. Acceptance criteria for V20 planning

This planning document is complete when each priority contains: observed
production evidence; a precise problem statement; safety or scientific
impact; questions requiring investigation; candidate solution
directions; non-goals; proposed validation; priority level; and its
relationship to V19 continuation.

Do not claim a root cause where evidence is insufficient. Every claim
must carry one of the four labels defined at the top of this document.
The §3.2 correction is the standing example: a plausible root cause
(`bucket_key = None`) was recorded, then disproved by direct
measurement, and the real defect turned out to be different and
narrower. Record the correction rather than quietly replacing it.

---

## 18. V20 validation principle

No V20 feature is complete because a field, module, or prompt was added.
Behavioral claims require:

- **Layer 1** — deterministic delivery and classification checks;
- **Layer 2** — broad controlled calibration across deliberately
  constructed scenarios with repeated samples;
- **Layer 3** — small bounded real LLM + real training confirmation.

For runtime and resource controls, additionally require bounded
real-system validation wherever the feature depends on actual GPU, host
memory, process lifecycle, or concurrency. A calibration promotion path
that has only ever run in tests is precisely the defect described in
§3.2 — unit tests proved the function works and could not prove anything
about whether production calls it.

---

## 19. Changelog

| Rev | Date | Change |
|---|---|---|
| 1b | 2026-07-31 | Campaign stopped and closed out. §6.1 upgraded from OPEN INVESTIGATION to **CONFIRMED DEFECT**: the chain parent's 6.9 GiB is the in-process VRAM pre-flight, traced call-path by call-path and confirmed by a pre-registered falsifiable prediction — the parent held 6,962 MiB unchanged across 13 samples over 3 minutes *after* its child exited, alone on the GPU. The fix (`run_isolated_preflight`, PR #151) exists and is GPU-validated with zero production call sites, making this the second instance of the P0-1 pattern; a reachability check is now a V20 requirement. §14 records the operator's 20:15 reversal on the §6.5 evidence and the full closeout: C13's three stop layers all correct, waves 2-4 never started, GPU returned to baseline, 645,054 tokens / $1.94 spent, and 20 observations that advanced calibration by nothing. |
| 1a | 2026-07-31 | Same day, before commit: §6.3 upgraded from HYPOTHESIS to CONFIRMED by direct measurement — pair total 28,732 MiB past the 28 GiB ceiling, loss chain tree 17.74 GiB against a 12 GiB cap, chain parents holding 55 % of all GPU memory. §14 escalation fired and is recorded with the operator's continue-with-monitoring decision; §6.4 records the accepted risk (a host-quota SIGTERM carries no memory error and resembles the misattributed C12 signature). |
| 1 | 2026-07-31 | Created from findings during the fresh V19 restart (`v19r3_10iter_20260731_1842`) after the runtime-estimation C1-C14 ladder and the PR #151 VRAM-preflight repair. Records: zero production promotion call sites; `model_family="unknown"` on all observations; the corrected `bucket_key` diagnosis; chain parent + sandbox child GPU aggregation; absent production RSS telemetry; the unresolved long-sequence amplification question; cross-campaign STOP scope; host-memory config portability; and model-scale monitoring. |
