# V20 Priority Decisions

- **Status**: Active — V19 closed, V20 implementation plan
- **V19**: `v19r3_10iter_20260731_1842` — **CLOSED**, not to be
  restarted. Classified as an infrastructure validation campaign stopped
  after confirming pair-level GPU contention and HealthGate enforcement
  gaps (§14). Its artifacts are forensic evidence only.
- **Implementation target**: V20, launched as a genuinely new campaign
  after the §13.1 launch gate is complete and validated
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

## 1.4 Gradual genericization — a binding design principle

**Operator decision, 2026-08-01.** This is not background. It is a
design, scope, review and acceptance constraint on every V20 PR.

**Direction.** Reshape SIDERIUS from a TIDMAD-only repository into a
generic framework that can accommodate different datasets, scientific
tasks, metrics, execution environments and hardware configurations. This
happens by gradually separating TIDMAD-specific behaviour from generic
infrastructure and moving task-specific behaviour into explicit,
replaceable components.

**Mechanism — in-passing refactoring, never a big-bang rewrite.**
Whenever a module is touched for new development, that PR must also move
the touched surface toward the generic design **where doing so is
reasonably bounded and directly related to the touched code**. There is
no repository-wide mega-refactor PR. Genericization rides the normal
development ladder.

The standing review question for every PR:

> **Does the code this change touches still treat TIDMAD, the current
> task, or the current machine as the framework itself? If so, can that
> be moved outside the configuration or plugin boundary within this
> PR's reasonable scope?**

### 1.4.1 The four dimensions

**Dataset.** Generic infrastructure must not assume TIDMAD directory
layouts, file names, sample formats, fixed train/eval file counts, fixed
signal shapes, fixed segmentation conventions, or a particular denoising
data loader. Dataset behaviour enters through typed dataset
configuration, a dataset adapter/plugin, task-owned data preparation,
and capabilities the dataset component declares.

**Task.** Generic infrastructure must not hardcode denoising as the only
task, TIDMAD-specific prompts, architecture names meaningful to one task
only, fixed training/inference/scoring scripts, the assumption that
every task is exactly `train → inference → score`, or task-specific
failure labels inside generic runtime-control modules. Task behaviour
enters through task configuration, task plugins or adapters, task-owned
prompts, task-owned phase definitions, and typed task contracts.

**Metric.** Generic infrastructure must not assume one score name, one
score direction, one aggregation rule, one HealthGate metric set,
denoising-specific collapse checks, or TIDMAD-specific thresholds.
Metrics enter through typed metric configuration, metric plugins,
explicit direction and aggregation semantics, task-owned HealthGate
configuration, and machine-readable result contracts.

**Hardware.** Generic infrastructure must not assume a specific GPU
model, a single-GPU machine, a fixed physical GPU index, a fixed
CUDA-visible layout, a fixed 12 GiB per-attempt cap, a fixed 28 GiB pair
ceiling, a fixed 30,000 MiB host quota, fixed host-RSS limits, a fixed
number of concurrent chains, or `nvidia-smi` availability as an
unconditional fact. Hardware policy enters through one typed
configuration surface.

Conservative defaults for backward compatibility are permitted, and are
expected during the transition. They must be **explicit, documented,
recorded in provenance, overrideable through configuration,
distinguishable from dynamically discovered hardware facts, and never
silently presented as universal constants.**

### 1.4.2 Three categories that must never be conflated

This is the same discipline as §1.3, applied to configuration rather
than to evidence. A number in the code is not self-describing; where it
came from determines what may be done with it.

| Category | Examples | Where it comes from |
|---|---|---|
| **Measured runtime fact** | process tree, driver-visible GPU memory, device UUID, free memory, host RSS, subprocess return code, phase timestamps | measured directly by infrastructure |
| **Configured policy** | GPU cap, pair ceiling, host quota, fail-open vs fail-closed on telemetry failure, max concurrency, dataset locations, task phases, score direction, HealthGate checks | typed configuration or declared plugin capability — **never** a constant embedded in runtime code |
| **Task-specific interpretation** | what counts as collapse, which score is scientifically authoritative, whether a phase is training / simulation / reconstruction / analysis, what feedback the scientific agent should receive | the task/plugin layer, **not** generic runtime-control code |

A measured fact carries no policy. A configured policy is not evidence.
A task interpretation is not a property of the framework. Collapsing any
two of these is the same class of error as V19's contention
misattribution: a value used with an authority it never earned.

### 1.4.3 Configuration hierarchy — direction, not a mandate

```text
ResolvedRunConfig
├── dataset
├── task
├── metrics
├── hardware
├── runtime
├── health_gate
└── provenance
```

**This is a design direction. It is not authorization for a
repository-wide schema rewrite.** For the current PR ladder:

- each PR adds or consumes only the smallest relevant typed subsection;
- configuration is resolved **once**, near the orchestration boundary;
- lower-level generic modules receive resolved objects or explicit
  arguments;
- lower-level modules must not independently rediscover policy through
  scattered environment variables;
- environment variables may remain as **compatibility inputs to the
  resolver**, not as the policy source of truth;
- resolved values **and their source** are recorded in provenance.

### 1.4.4 Hardcoding classification

Not every number or task name is a defect. Before changing one,
classify it:

| Class | Treatment |
|---|---|
| example fixture | keep; label as an example |
| current TIDMAD compatibility default | keep; label explicitly as a compatibility default, record its future configuration source |
| generic infrastructure policy | must be typed configuration |
| task-owned configuration | must move to the task/plugin layer |
| hardware-owned configuration | must move to the hardware configuration surface |
| **unacceptable hardcoding** | fix in this PR, or file a follow-up with an ID and say why it is deferred |

**Do not mechanically replace every number or term.** Examples and
compatibility defaults may remain. What they may not do is masquerade
as universal framework rules.

### 1.4.5 Required in every V20 PR design document

Every PR design document under `docs/design/v20_priorities/` carries a
section titled **"Genericization impact and in-passing refactor"**
answering, specifically and not as boilerplate:

1. Which touched modules are generic infrastructure?
2. Which are task-, dataset-, metric-, or hardware-specific?
3. Does the PR introduce any new hardcoded assumption?
4. Which existing hardcoded assumption does it remove or move behind
   configuration?
5. Which assumptions remain, and why are they deferred?
6. What compatibility surface preserves existing TIDMAD behaviour?
7. What tests prove that generic infrastructure does not depend on a
   specific dataset, task, metric, or hardware model?

If a PR genuinely touches no relevant abstraction boundary, it says so
**with evidence**.

### 1.4.6 Shared checklist additions

**Implementation**

- [ ] No new TIDMAD-specific constant enters generic infrastructure
- [ ] No task-specific prompt, metric, file layout, model family or
      hardware ceiling is embedded in a generic runtime module
- [ ] New policy values enter through typed configuration or declared
      plugin capability
- [ ] Task-specific assumptions in touched code move behind the
      appropriate boundary when the refactor is bounded and directly
      related
- [ ] Backward compatibility for the current TIDMAD workflow is explicit

**Validation**

- [ ] Unit tests use synthetic or generic fixtures where task-specific
      data is not required
- [ ] At least one test exercises a **non-default** configuration
- [ ] Hardware tests do not assume physical GPU index 0 unless the test
      is explicitly scoped to that fixture
- [ ] Dataset/task/metric-specific tests remain in their owning layer
- [ ] Generic runtime-control tests do not import TIDMAD-specific
      modules

**Merge criteria**

- [ ] Genericization impact section completed
- [ ] No unexplained new hardcoded dataset, task, metric or hardware
      assumption
- [ ] All new policy is typed, configurable, and represented in
      provenance where operationally relevant
- [ ] Existing TIDMAD behaviour remains supported through
      configuration, not hidden special cases
- [ ] Deferred genericization work has a follow-up ID and does not
      undermine the PR's claimed abstraction

**Decomposition (§1.5) — every PR**

- [ ] The PR adds no new responsibility or new branching to a function
      already coordinating multiple unrelated concerns; where it would,
      a bounded responsibility boundary was extracted **first**
- [ ] Every extracted unit has explicit inputs, a typed result, a
      documented responsibility and bounded side effects — it does not
      read or mutate arbitrary outer state
- [ ] Behavioural parity proven: retry and round behaviour, phase
      ordering, timeout and signal semantics, persisted artifacts and
      statuses all unchanged
- [ ] A reachability test fails when the production path bypasses the
      extracted boundary, demonstrated by revert or mutation
- [ ] Strict type checking covers the extracted units, and the touched
      orchestrator is still small enough for the type checker to analyse
      at all
- [ ] No behaviour was changed "while refactoring"

---

## 1.5 Responsibility-oriented decomposition — a binding design principle

**Operator decision, 2026-08-01.** Equal in standing to §1.4. Where §1.4
governs *what* generic infrastructure may know, §1.5 governs *where new
logic may be put*.

### 1.5.1 The rule

SIDERIUS must not create or further enlarge giant orchestration
functions. A function that coordinates multiple phases, constructs
records, handles errors, mutates state, performs I/O **and** decides
control flow is not a valid extension point.

When new work touches such a function, the PR **first** creates the
smallest clear responsibility boundary the new work needs:

```text
identify the responsibility
→ extract a typed, independently testable boundary
→ prove behavioural parity
→ place the new feature inside that boundary
→ keep the top-level orchestrator doing sequencing
```

Bounded in-passing decomposition, exactly as with genericization. Never a
repository-wide rewrite, and never a full rewrite of one giant function
in a single PR.

### 1.5.2 Split by responsibility, not by line count

Mechanically cutting 2,487 lines into ten 250-line functions achieves
nothing. Extract coherent responsibilities:

```text
run()
├── planning coordinator
├── preflight coordinator
├── training phase handler
├── inference phase handler
├── scoring phase handler
├── failure/skip record builder
├── round transition controller
└── runtime evidence attachment
```

A top-level `run()` should end up doing: invoke a phase boundary,
receive a typed result, apply a small number of high-level transitions,
delegate task-specific interpretation and persistence.

### 1.5.3 A helper is not automatically a decomposition

Moving code into another file while it still reads and mutates arbitrary
outer state relocates the complexity without reducing it. Each extracted
unit requires:

- explicit inputs
- a typed result
- a documented responsibility
- bounded side effects
- focused tests
- **production reachability evidence** — a test that fails when the
  production path bypasses the boundary

### 1.5.4 Decomposition must preserve behaviour, and prove it

- parity before and after extraction
- unchanged retry and round behaviour
- unchanged phase ordering
- unchanged timeout and signal semantics
- unchanged persisted artifacts and statuses
- mutation/revert evidence that the tests detect a bypass
- strict type checking covering the extracted units

Never change retry, phase order, signal, timeout or scientific behaviour
"while refactoring".

### 1.5.5 Why this is a rule, not a preference

`HyperparamTuningAgent.run()` reached **2,487 lines** and sat *exactly*
on pyright's strict complexity ceiling: **258 branch nodes pass, 259
fail**. Past that limit strict mode does not degrade — it abandons the
whole function, so every annotation inside the tuner's main method was
going unverified. Nothing surfaced it until an unrelated PR added one
`if`.

The failure modes are not aesthetic:

- a small change can affect many unrelated paths
- tests can only be written with heavy mocking
- type checking silently gives up
- new logic is easy to wire and easy to leave unreachable
- no single step can be validated on its own
- every subsequent feature adds more branches

### 1.5.6 Review trigger

For every PR:

> Does this change add a new responsibility or new branching to a
> function that is already coordinating multiple unrelated concerns?

If yes, the PR establishes a bounded responsibility boundary first.
Adding implementation detail to an existing focused function is fine.
Adding another responsibility to a giant orchestrator is not.

### 1.5.7 Current application

`HyperparamTuningAgent.run()` is a known oversized orchestrator. **B-C4
admission branches must not be added to it.** Before B-C4, complete
**B-C4a0** — extract the tuner control boundary admission needs:
training-result handling, inference-result handling, failure/skip record
construction, runtime-evidence attachment, and the proceed/stop
transition. B-C4 then adds admission *through* those boundaries.

---

## 2. Priority summary

| # | Priority | Observed problem | Why it matters | V20 target behavior | V19 blocker? |
|---|---|---|---|---|---|
| **P0-1** | Calibration promotion never runs | `evaluate_promotions` / `record_promotion` have **zero production call sites** | The learning loop never closes; every decision falls back to `static_uncalibrated` | Promotion evaluated and recorded on the production path | No |
| **P0-2** | Bucket identity: `model_family` is always `unknown` | All 20 observations carry `model_family="unknown"` | Unknown family is its own bucket by design (D5) — it never inherits, so buckets fragment and stay unusable | Real family identity flows into observations | No |
| **P0-3** | Validated calibration is not an admission authority | No consumer treats a validated bucket as the final gate | Operator requirement: dynamic calibration should be the final gate | Validated calibration or a successful live probe is the final gate | No |
| **P0-4** | Calibration-quality reporting | A campaign can collect observations while zero are promotable, silently | "Dynamic calibration is running" was believed true when it was not | Every campaign reports bucketed/eligible/validated/rejected counts | No |
| **P1-1** | GPU-memory telemetry incomplete | Estimate (2.00 GB) and `nvidia-smi` (6,962 MiB) are different quantities; neither `max_memory_allocated` nor `max_memory_reserved` is persisted | The estimate-vs-actual gap cannot be attributed | Persist allocated / reserved / driver-visible per process and phase | No |
| **P1-2** | Chain-level GPU aggregation is unbounded | Measured 2026-07-31 19:55Z: loss chain tree **17.74 GiB** against a 12 GiB cap; pair total **28,732 MiB**, past the 28 GiB ceiling, 1,268 MiB from the host quota | The per-chain cap bounds a predicted per-attempt allocation, not what the chain's process tree holds | **PR A** (§6.6): route production pre-flight through the existing isolated worker, keep the parent CPU-only. **PR B** (conditional): chain/pair aggregation + OOM attribution, only if validation still shows it is needed | **PR A COMPLETE AND VALIDATED 2026-08-01** (§21). A5 + A6 measured: parents hold **0 MiB**, pair peak **15.52 GiB** vs V19's **28.05 GiB**. Root cause (§6.1) confirmed fixed. **PR B is now REQUIRED, not conditional** — A6 showed admission compares an estimate that under-reads driver-visible by ~1.8–2.0×, and the 28 GiB pair guard has no production caller |
| **P1-3** | Production host-memory telemetry absent | Peak RSS, RSS timeline, and phase attribution are not persisted on the production path | The 17M dilated-conv question cannot be settled from artifacts | Bounded RSS telemetry with phase attribution | No |
| **P1-4** | Long-sequence preflight memory amplification | A 17M candidate reached ≈26 GiB process-tree RSS in preflight | Unresolved between genuine requirement and inspection amplification | Phase-level bounded measurement to distinguish A from B | No |
| **P2-1** | Campaign-scoped stop and queue state | A previous campaign's queue-level `STOP` blocked a new campaign's launch | One campaign's terminal state has authority over another | All control state under `<campaign_root>/<campaign_id>/control/` | No |
| **P2-2** | Portable host-memory configuration | The 24 GiB worker threshold is derived for one machine | Not portable; environment-only control is weak for reproducibility | Backward-compatible layered config with recorded provenance | No |
| **P2-3** | Model-scale and downsizing-bias monitoring | Iteration 1 proposed 2.39M / 4.12M against advice suggesting 10M-100M | The original V19 failure expressed itself as systematic shrinking | Campaign-level scale-trend reporting | No — non-blocking, improve during V20 (§13.1) |
| **P0-5** | Formal campaign ran under an observe-only HealthGate policy, and zero-valid-trial handling is undefined | V19 launched with `health_checks_baseline_observe_mode.yaml`; all four rounds collapsed (`unique_int8` 1–4 of 256) and correctly resolved `continue` per that config | Degenerate rounds consumed formal budget and entered the record; formal ran on a plan no valid trial supported | Formal campaigns use the blocking config; a zero-valid-trial iteration yields no authoritative result or incumbent | **Blocks V20 launch** (§13.1 #5) |

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

### 6.6 Remediation — the narrow fix first (operator decision, 2026-07-31)

**Root cause, restated in one sentence.** The pre-flight VRAM check runs
inside the chain's main process, so that process creates a CUDA context
and keeps the allocator cache from the check for the whole iteration;
training and inference then hold their own copies in subprocesses, so
resources for the same model are held twice.

The evidence is sufficient for a narrow fix and does not justify a
rewrite: two orchestration-only parents held 15,906 MiB, ~55 % of all GPU
memory in use, and the arch parent held 6,962 MiB unchanged for three
minutes after its child exited, releasing only when the parent itself
exited. That rules out both transient overlap and a stale-process leak.

#### PR A — route production pre-flight through the existing isolated worker

The one change that must happen, and the smallest one available.

```
today                        target
─────────────────────────    ─────────────────────────────────
chain parent                 chain parent stays CPU-only
 → in-process VRAM preflight  → isolated pre-flight subprocess
 → parent creates CUDA ctx    → subprocess exits
 → cache held all iteration   → CUDA context and cache fully returned
 → training/inference child   → training/inference subprocess unchanged
```

`run_isolated_preflight` already exists and survived four rounds of GPU
validation; the production tuner simply still calls the old in-process
`run_skill`. So this is a **call-site replacement**, not a rewrite of
pre-flight: inputs, outputs and the disposition schema stay identical.

It removes, in one change: the parent's redundant GPU context; the
duplicate model instantiation in the parent; the reserved memory retained
after pre-flight; and the parent+child overlap at any instant.

**Scope.** One production call site, a result adapter, a little
manifest provenance, the guardrail tests below, and the doc updates.

**Explicitly not touched**: queue, training, inference, admission policy,
the 12 / 28 GiB thresholds, calibration, HealthGate, agent prompts.

#### Keep the existing subprocess architecture for training and inference

That part already behaves correctly — memory returns in full on child
exit, failures are isolated, and no single candidate can take down the
chain parent. Do not "unify" it.

The principle to hold:

```
anything that loads a model or touches CUDA  →  short-lived child
the long-lived orchestrator                  →  CPU-only
```

This is more reliable than sprinkling `torch.cuda.empty_cache()` in the
parent. `empty_cache()` frees only unused cached blocks; it cannot
guarantee the context, live references, or third-party allocations are
released. **Process exit is an unambiguous resource boundary; a cache
call is not.**

#### Production-wiring guardrails

Small tests that lock the call path, so "built but never called" cannot
recur (this is the §18 gap, and P0-1 is the same failure in another
subsystem):

- production pre-flight must go through `run_isolated_preflight`;
- the chain parent must not appear as a GPU process before or after
  pre-flight;
- production code must not call the old in-process GPU pre-flight;
- the manifest records the pre-flight execution mode, e.g.
  `isolated_subprocess`;
- a test asserts the parent never imports or instantiates the candidate
  model.

None of these change the workflow. They only pin the path.

#### What phase 1 must NOT do

**No dynamic chain-level kill yet.** Aggregate driver-visible protection
across a chain and a pair is the right eventual answer, but if the
parent's 6.9-8.9 GiB disappears once pre-flight is isolated, the largest
redundancy may already be gone. Measure first:

```
wire the isolated pre-flight
  → single-chain real validation
  → two-chain real validation
  → only then decide whether a live aggregate gate is needed
```

Do not introduce, at this stage: a continuous NVML scheduler; automatic
pausing of a chain; dynamic concurrency adjustment; a cross-process GPU
memory broker; or a resource-reservation protocol. Each has a wide blast
radius across the queue, watchdog and sandbox lifecycle, all of which
currently work.

**Do not make `empty_cache()` the primary fix** — see above; it may serve
as cleanup inside a worker, never as a substitute for isolation.

**Do not raise the 12 GiB, 28 GiB, or host quota.** The problem is
double-held resources and an under-scoped accounting boundary, not a
ceiling that is too low. Raising it would hide the defect.

#### Validation sequence

**Phase 1 — wiring and compatibility.** Change only the production call
site. Required: identical input config, identical structured result,
identical dispositions, identical error classification. Keep the old
in-process function so tests and other tools do not break; production
defaults to the isolated path. An explicit test-only fallback may remain,
but the formal workflow must never use it.

**Phase 2 — bounded single-chain GPU validation.** One light iteration,
one chain. Measure: whether the parent appears in `nvidia-smi` at all;
pre-flight worker peak; GPU state after the worker exits; training child
peak; inference child peak; the chain's driver-visible peak; and
allocated / reserved / driver-visible together.

```
pass criteria
  chain parent ≈ 0 GPU memory
  pre-flight worker exits cleanly
  no overlap between pre-flight and training
  no orphan processes
  scientific result path unchanged
```

Do not assume the chain peak will fall under 12 GiB. Measure it.

**Phase 3 — bounded two-chain validation.** Only after phase 2 passes:
a small concurrent arch + loss run. Required: pair aggregate stays below
28 GiB and away from the 30,000 MiB host quota; any OOM records peer
occupancy; peer contention is never recorded as candidate evidence; both
parents stay CPU-only.

Only if the pair still approaches the quota does PR B begin.

#### PR B — chain/pair aggregation and OOM attribution (conditional)

A separate PR, never merged into PR A, and only if phase 3 shows it is
still needed. Scope it to **measurement and attribution**, not automatic
workflow rearrangement:

1. register each chain's parent PID, process group and child PIDs;
2. read driver-visible memory per PID via NVML;
3. aggregate into chain total, peer chain total, pair total;
4. check pair headroom before launching a new GPU child;
5. on OOM, record candidate process memory, peer memory, free VRAM and
   pair total *as they were before the failure*.

Attribution can start simple, and answers §1.3 directly:

```
candidate process/tree independently exceeds its allowed measured scope
    → candidate-attributable

pair total near the device/quota ceiling while the peer holds
substantial memory
    → contention-attributable
    → no candidate-downsizing authority
```

Do not automatically kill a running peer. Refusing to start the next
stage, or marking the result as contention/infrastructure evidence, is
sufficient and far less invasive.

#### Host memory benefits, and what stays separate

Isolating pre-flight also returns CPU memory: the model and probe tensors
go away with the worker, the parent stops holding Python objects, model
structure and tracing data for the iteration, and every candidate's
temporaries get a clear lifetime.

The 26 GiB long-sequence host-memory question (§8) is **not** folded into
this PR. It remains its own investigation.

The isolated worker may cheaply persist phase peaks while it is there:

```
model construction peak RSS
training probe peak RSS
inspection peak RSS
batch search peak RSS
final worker peak RSS
```

Peaks only — no unbounded time series, so CPU and disk cost stay
negligible.

#### The recommended route, end to end

```
1. route production pre-flight through the existing isolated worker
2. guarantee the long-lived parent never touches CUDA
3. bounded single-chain measurement
4. bounded two-chain measurement
5. add a chain/pair aggregate gate only if the quota is still approached
```

This removes the confirmed redundancy and the CPU lifetime problem while
leaving the workflow, queue, training, inference and failure
classification logic intact. The §6.1-§6.5 evidence supports exactly this
narrow fix; it does not support a large refactor.

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

### 11.2 Entry points for resource-driven shrinking

The original V19 failure was resource pressure expressing itself as
systematic shrinking. Four doors have been identified; their status
differs sharply and should not be flattened:

| # | entry point | status |
|---|---|---|
| 1 | batch-search timeout read as capacity | **closed** (PR #151) |
| 2 | host memory misattributed | **closed** (PR #151) |
| 3 | peer-contention OOM read as candidate evidence | **CONFIRMED, open** (§6.5) |
| 4 | time-budget advisory rendered into the prompt | **OPEN, unmeasured** (below) |

#### Door 4 — the time estimate reaches the agent as prose

The runtime gate layer is healthy: no static estimate ever rejected a
candidate, `ADVISORY` / `REQUEST_PROBE` / `ALLOW` resolved correctly, and
every round finished inside its budget. That part needs no repair.

But the estimate is **also rendered into the planning prompt**
(`agent/prompts.py:645-650`):

```python
factor = last_time_estimate_minutes / active_time_budget
verdict = "over" if factor > 1.0 else "under"
time_line = (f"  Time:  estimate {…:.2f} min   budget {…:.1f} min   "
             f"factor {factor:.2f}  ({verdict})")
```

So for the arch formal round the agent was shown:

```
  Time:  estimate 237.80 min   budget 120.0 min   factor 1.98  (over)
```

while the round actually took **96.3 min** — factor **0.80**, *under*
budget with 20 % to spare. The estimator over-predicted by **2.47×**, and
that error reached the decision-maker as a stated fact carrying an
explicit "over" verdict.

The over-prediction is systematic rather than random:

| chain | round | estimate | budget | actual |
|---|---|---:|---:|---:|
| arch | formal | 237.8 min | 120 | **96.3 min** |
| arch | trial | 14.4 min | 20 | 7.8 / 11.2 min |
| loss | trial | 42.9 min | 20 | 16.5 / 17.3 min |

**This is not a defect in the gate; it is an influence path that bypasses
the authority layering.** The repaired architecture governs `REJECT`. It
does not govern what the prompt asserts.

**Status: OPEN, and no harm is demonstrated.** The evidence is thin and
points the other way. The 237.8 min / factor 1.98 line appeared on the
**formal** round — the last step of the iteration — so no subsequent
proposal was ever observed responding to it, and iteration 2 never ran.
The only observable size change went **up**: arch moved from 1,278,944 to
2,388,992 (+87 %). Nothing here shows the agent shrinking in response to
a time advisory.

Two things follow for V20. Whether door 4 is real is answerable only by
recording the estimate shown, the verdict word, and the next proposal's
size together (§11.3) — it is a behavioural question, not a code
question. And it is a far weaker concern than door 3, which is confirmed
and has already fired once; the two must not be given equal weight.

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

## 12A. P0-5 — Formal-campaign HealthGate policy and zero-valid-trial handling

*Numbered 12A rather than 13 so the existing section numbers and the
cross-references to §14 and §18 stay valid.*

### 12A.0 Correction — this is a launch choice, not an enforcement defect

An earlier revision of this section called the `continue` resolution a
**CONFIRMED DEFECT**. That was wrong, and the correction is recorded
rather than silently replaced, per §17.

The confirmed facts:

- the repository default `configs/health_checks.yaml` maps all three
  blocking checks to **`invalidate_round`**;
- V19 explicitly launched with a different file —
  `v19_queue_runner.sh:272` passes
  `--health_checks_config configs/health_checks_baseline_observe_mode.yaml`;
- that file deliberately maps the three blocking-named checks to
  `continue`, with the reason recorded verbatim in the materialised
  effective config: *"Observe only; production policy would invalidate a
  failed result."*;
- `resolved_action: continue` was therefore **correct execution of the
  selected configuration**. No action was ignored, dropped, or
  mis-resolved.

So detection, collapse classification, and action resolution all worked.
What went wrong is upstream of the code: **a formal campaign was launched
with an observe-only gate policy**, and there is no policy for what
happens when an iteration yields zero valid trials.

The priority is therefore restated:

```
was:  fix broken HealthGate enforcement
is:   define formal-campaign HealthGate policy and
      zero-valid-trial handling
```

One presentation defect does follow from the evidence and is real: the
gate IDs say `*_blocking` while the effective action is `continue`. That
naming misled this analysis directly — the `_blocking` suffix was the
reason the behaviour was first read as a defect.

### 12A.1 What the gates measured

The measurements are unambiguous, and they are why the policy question
matters rather than being academic. `unique_int8` counts how
many distinct values the model actually emits out of 256:

| chain | exp | score | output_diversity | output_std | amplitude_collapse |
|---|---|---:|---|---|---|
| arch | 001 | −0.7587 | **FAIL** 4,4,4,3,4 | pass | **FAIL** 0.996–0.997 |
| arch | 003 | −2.5390 | **FAIL** 1,2,1,1,1 | **FAIL** 0.0 on 4 of 5 files | **FAIL** 1.000 |
| loss | 002 | −0.3453 | **FAIL** 2,2,2,2,2 | pass | **FAIL** 0.993–0.995 |
| loss | 003 | −0.7831 | **FAIL** 2,2,2,2,2 | **FAIL** 0.20–0.40 | **FAIL** 0.9999 |

arch 003 emitted a **constant** signal on four of five files — standard
deviation exactly 0.0. The log names the mechanism: `Class-127 collapse
artifact — score would be 5.5762667 via 2^17 FP ratio`.

### 12A.2 What this is not

Three alternative explanations are ruled out by the artifacts, so the
investigation does not need to revisit them:

- **Not a gate-path defect.** Every check reported `n_files_io_failed: 0`
  with `files_completed = 5/5` and full per-file metrics.
- **Not mis-calibrated thresholds.** The `unique_int8 > 25` threshold was
  derived from FCNet's own worst file (52 on file 3, a 2.08× margin) and
  sits above the collapsed-baseline maximum of 15. On band 15-19
  specifically, FCNet measures **143–159**. Observed values of 1–4 fail by
  an order of magnitude against any defensible threshold.
- **Not a novel-architecture false positive.** The design doc anticipated
  legitimate models landing in `[15, 25)`; these are at 1–4, far outside
  that grey zone.

The three recording-only checks (`pearson_dispersion`,
`spectral_peak_ratio`, `per_file_output_std`) all passed, but they carry
no rejection threshold by design — their passing is not evidence of
health and must not be read as such.

### 12A.3 Consequences observed

The chain below is independent of which gate config was selected — it is
what happens whenever an iteration ends with no valid trial:

```
gates detect collapse → observe-only config → continue
  → the round still yields a score, recorded as a normal result
  → "no successful trial round is HealthGate-valid in this iteration"
  → Best score: None (no incumbent)
  → [FORMAL OVERRIDE] runs formal on an unvalidated plan,
     warning that the score "may be unreliable"
```

The system is honest in that warning, but an unreliable score that
reaches the records can still become an incumbent or a reported result.
**That gap remains even under a blocking config**, which is why it is a
separate requirement rather than a consequence of the config choice.

### 12A.4 Intended policy split

```
formal scientific campaign
    → configs/health_checks.yaml
    → a failed blocking check invalidates the round

baseline characterization / gate calibration / threshold study /
explicitly-labelled diagnostic campaign
    → observe-only config may be selected deliberately
    → its outputs remain non-authoritative
```

**Do not delete the observe-only config and do not change its
semantics.** Observe mode is legitimate and needed; the defect is that a
formal campaign used it, apparently unintentionally. The file name
`health_checks_baseline_observe_mode.yaml` suggests it was written for
baseline runs, not for a scientific campaign.

**Recommendation for V20 (operator decision).** Use the blocking config.
The observed collapse is not marginal: 1–4 distinct values out of 256,
standard deviation of exactly 0.0 on four files, amplitude collapse at
0.9999–1.000. Under observe mode, rounds this degenerate keep consuming
formal budget and keep entering the record.

### 12A.5 Unresolved policy requirements

These hold regardless of the config choice and are the actual PR D work:

- **no HealthGate-valid trial ⇒ no scientifically valid candidate** for
  that iteration;
- a formal run under a zero-valid-trial override must be explicitly
  **diagnostic / non-authoritative**;
- such a result must not enter incumbent selection;
- it must not enter scientific aggregation or the formal grand mean;
- the planner must receive **structured all-trials-invalid feedback**, so
  the next iteration changes the plan rather than resubmitting it
  unchanged;
- campaign manifests must record the **selected HealthGate mode** plainly,
  not only as a config path and hash;
- IDs and operator-facing labels must not say `blocking` when the
  effective action is `continue`.

### 12A.6 Remaining open questions

1. Was the observe-only config chosen deliberately for V19, or inherited
   from the V17/V18 baseline work and never switched? This determines
   whether the launcher needs a guard or only a changed argument.
2. Should a zero-valid-trial iteration abort, run formal as a labelled
   diagnostic, or skip formal entirely?
3. Does the interpreter already receive enough per-round gate evidence to
   explain the collapse to the proposer, or is that the PR 3 remainder?

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

Item 8 is now answered (§6.1) and the remaining work is sequenced as PR A
then a conditional PR B (§6.6). PR A is the only one authorized to start.

6. **PR A** — route production pre-flight through `run_isolated_preflight`;
   keep the chain parent CPU-only; add the production-wiring guardrails
7. Bounded single-chain, then two-chain GPU validation (§6.6 phases 2-3)
8. ~~Explain the chain parent's ~6.9 GiB CUDA context~~ — **answered**:
   in-process pre-flight, confirmed by measurement (§6.1)
9. Persist allocated / reserved / driver-visible VRAM
10. **PR B, only if phase 3 requires it** — chain/pair aggregation via
    NVML, pre-launch pair headroom check, contention-aware OOM
    attribution (§1.3)

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

### 13.1 Launch gate — what must be done before V20 runs

The list above orders work by importance. This section splits it by a
different question: **what would make a V20 campaign's results
uninterpretable if it were still missing?** Everything in the first tier
failed visibly in V19; running again without it would spend time and
money on known defects.

**Blocking — V20 does not launch until all six are complete and validated**

| # | Requirement | Why it blocks | Evidence |
|---|---|---|---|
| 1 | Production pre-flight runs in the isolated worker; parent stays CPU-only, holding no CUDA context or cache | The parent held 6,962 MiB for a whole iteration | §6.1, §6.6 |
| 2 | Chain/pair GPU aggregation and attribution: memory accounted over the process tree, contention-caused OOM never recorded as candidate failure, two-chain runs pass a real aggregate check | Pair reached 28,732 MiB and produced a mis-attributed OOM | §6.2, §6.5 |
| 3 | Measured-evidence admission: a formal candidate cannot proceed on `ADVISORY` alone; it needs calibration shown applicable to it, or a live probe of it | `ADVISORY` is currently a terminal state for admitted candidates | §3.0, §3.5 |
| 4 | Calibration promotion wired into production, `model_family` propagated, and validated/rejected/unusable counts reported | 20 observations, 0 promotions, family `unknown` throughout | §3.2, §3.3, §12 |
| 5 | Formal-campaign HealthGate policy: the campaign selects the blocking config and the choice is recorded plainly; with zero valid trials the formal output is not a scientific result or an incumbent | All four rounds collapsed under an observe-only config selected at launch | §12A |
| 6 | Campaign-scoped control state: STOP, queue state and pair summaries belong to a campaign; a stopped campaign cannot block a new one | The previous campaign's STOP blocked this one's launch | §9 |

**Non-blocking — improve during V20**

These sharpen analysis but do not decide whether a result is
interpretable, provided the six above hold:

- fuller RSS time series beyond phase peaks (§7);
- portable/auto host-memory configuration (§10);
- richer model-scale trend reporting (§11.3);
- time-estimate accuracy, including door 4 (§11.2);
- deeper allocated/reserved telemetry (§5) — *given* that basic aggregate
  safety from requirement 2 is already in place.

### 13.2 Suggested PR ladder

Not necessarily five mechanical PRs, but **each problem needs its own
acceptance criteria**, so a regression can be located instead of hunted
across a large change.

```
V19 closeout (§14)
  → PR A   isolated production pre-flight
           → bounded single-chain validation
           → bounded two-chain validation
  → PR B   chain/pair GPU aggregation and attribution
           → real contention validation
  → PR C   measured-evidence admission + calibration promotion
           → production reachability validation
  → PR D   HealthGate enforcement and zero-valid-trial policy
  → PR E   campaign-scoped controls
  → final V20 gate
  → launch V20
```

PR B remains conditional in the sense of §6.6 — its *scope* depends on
what the two-chain validation after PR A actually shows — but requirement
2 above is not optional. If PR A alone makes the pair demonstrably safe
and attribution correct, PR B can be small; it cannot be skipped without
evidence.

---

## 14. V19 closure

**V19 is closed. It will not be restarted.**

Formal classification:

```
V19 infrastructure validation campaign — stopped after confirming
pair-level GPU contention and HealthGate enforcement gaps.

Final state: STOPPED — PAIR-LEVEL GPU CONTENTION
```

**Do not describe V19 as "completed successfully".** It produced no
citable formal scientific result. The accurate description is that it
**concluded as a production diagnostic campaign** — and that is where its
value lies: it forced several hidden production defects into the open,
with measurements, in two hours of real running. Restarting it would
spend further time and money on defects that are now known.

### 14.0 What V19 established

**Validated — these work and V20 must not redesign them**

- static runtime estimates no longer hold rejection authority;
- VRAM pre-flight classification is correct across its typed dispositions;
- candidate-level and infrastructure failures are distinguishable;
- C13 stop semantics work at all three layers (§14.2).

**Exposed — these are the V20 work**

- production pre-flight is not wired to the isolated worker (§6.1);
- chain/pair GPU aggregate is not actually constrained (§6.2);
- a contention-caused OOM was attributed to a candidate (§6.5);
- calibration promotion is not wired into production (§3.2);
- `model_family` identity is missing from every observation (§3.3);
- HealthGate detected severe collapse while enforcement resolved to
  `continue` (§12A);
- no citable formal scientific result was produced.

The next step is not a V19 restart but the §13.1 launch gate, then a
fresh campaign.

### 14.0.1 V20 must be a genuinely new campaign

Required: new campaign ID, new run names, new workspaces, new report, new
queue state, cold start.

**Must not be reused**, because each would import a defect or a
contaminated judgement into a clean run:

```
proposal history          incumbent
HealthGate history        resource-failure feedback
the old STOP file         contention-polluted OOM evidence
```

V19's artifacts are retained as **forensic evidence only**.

### 14.1 Historical record — the stop decision

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

### 14.2 Campaign closeout — verified 2026-07-31 21:00 UTC

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

## 15. Evidence to collect — from V19's artifacts, and from V20

V19 is closed, so there is no "remainder" to observe. This list now has
two uses: what to mine from V19's retained artifacts, and what the V20
campaign must record from its first iteration onward so the same
questions are answerable without a second forensic exercise.

Per iteration: proposal
scale; realized parameter count; model family; runtime evidence tier;
live probe result; calibration bucket identity; promotion result;
training wall time; allocated / reserved / driver-visible VRAM where
available; process count per chain; HealthGate result; score;
next-iteration scale change; and every resource-related candidate
failure.

**Constraint on V19 artifacts**: read-only. They are forensic evidence
(§14.0.1) and nothing may be re-run against them to manufacture
telemetry that the campaign did not produce. Telemetry that does not
exist is itself a V20 finding (§7).

**Requirement on V20**: the fields above must be recorded as the
campaign runs, not reconstructed afterwards. Every gap in this list cost
a separate investigation during the V19 closeout — peak RSS, per-process
GPU attribution, and the feedback text actually shown to the agent were
each unavailable when the question arose.

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
| 1f | 2026-08-01 | **PR A complete and validated; PR B promoted from conditional to REQUIRED.** A5 (single chain) and A6 (dual chain) both PASS on real GPU: chain parents hold **0 MiB** — they never appear in `nvidia-smi --query-compute-apps` at all — and the pair peak is **15.52 GiB against V19's 28.05 GiB**, with 125.9 s of genuine concurrent training, no OOM, no orphan and no watchdog intervention. The §6.1 root cause is fixed. Three things were learned that the plan did not anticipate. **(a)** A5's contract check failed before it passed: the intermediate `IsolatedProbeResult` silently dropped **eight** worker fields, so `memory.vram_budget_gb` landed null where 456 pre-PR-A records held 12.0, and the whole D-A2 bounded-diagnostics mechanism had never reached a record. Forty-seven adapter tests missed it because each serialization layer was tested alone and the composed worker-JSON → IPC-model → adapter path never was. Repaired narrowly, with a composition suite driving the real production path and a schema-diff guardrail; revalidated 10/10. **(b)** Finding F1 — that the parent *must* appear in `nvidia-smi` because `hardware_context.discover()` initializes CUDA — was **wrong, and had already been used to weaken a pass criterion** before it was measured. Direct measurement: `discover()` sets `is_initialized()` but registers no compute process; only a real allocation does. The original stronger criterion was achievable all along and both runs met it. **(c)** A6 exposed the decisive fact for PR B: chain A was admitted at a 6.43 GB estimate and then held **12.52 GiB** — past the 12 GiB per-attempt cap it was admitted under. Admission compares a predicted *allocated* peak while the host quota counts driver-visible *reserved*, so `estimated <= 12 GiB` does not imply `driver-visible <= 12 GiB`; and `pair_admission.py`, which defines the 28 GiB ceiling, has **zero production callers**, so nothing enforced it during the run except an external validation monitor that is not part of the product. A6's pair was safe because the candidates were small relative to the cap, not because any mechanism made it so. §20.4's conditional start rule is therefore **resolved as REQUIRED** with a three-item minimum scope (real aggregate accounting, pre-phase headroom check, correct OOM attribution), and §20.9's "or formally deemed unnecessary" branch is **closed**. Recorded against over-reading: the two observed estimate-to-measured ratios (1.95×, 1.82×) demonstrate the estimate cannot protect a driver-visible quota, but two samples do not establish a scaling constant — PR B must measure the real aggregate, never multiply the estimate by a factor. |
| 1e | 2026-07-31 | **Correction to P0-5, before any code was written against it.** Revision 1d called the `continue` resolution a CONFIRMED DEFECT. It is not. The repository default `configs/health_checks.yaml` maps all three blocking checks to `invalidate_round`, but `v19_queue_runner.sh:272` launched V19 with `configs/health_checks_baseline_observe_mode.yaml`, which deliberately maps them to `continue` — the materialised effective config carries the reason verbatim: *"Observe only; production policy would invalidate a failed result."* Detection, collapse classification and action resolution all worked; `resolved_action: continue` was correct execution of the selected configuration. The priority is restated from *fix broken HealthGate enforcement* to **formal-campaign HealthGate policy and zero-valid-trial handling** (§12A). One real presentation defect survives: gate IDs read `*_blocking` while the effective action is `continue`, and that naming is what caused the original misreading. §12A.4 records the intended split — formal campaigns use the blocking config, while observe mode stays available and unchanged for baseline, calibration and explicitly-labelled diagnostic runs — with a recommendation to use blocking for V20 given collapse at 1–4 distinct values of 256 and std exactly 0.0 on four files. §12A.5 keeps the zero-valid-trial requirements, which hold under either config and are the actual PR D work: no valid trial means no valid candidate, any override run is non-authoritative and excluded from incumbent selection and scientific aggregation, the planner receives structured all-trials-invalid feedback, and the manifest records the selected mode plainly. No configuration file was modified in this documentation step. |
| 1d | 2026-07-31 | **V19 formally closed** (§14): classified as an *infrastructure validation campaign stopped after confirming pair-level GPU contention and HealthGate enforcement gaps*, final state `STOPPED — PAIR-LEVEL GPU CONTENTION`. Explicitly not "completed successfully" — it produced no citable formal scientific result; it concluded as a production diagnostic campaign, which is where its value lies. It will not be restarted, and V20 must be a genuinely new campaign (new ID, run names, workspaces, report, queue state, cold start) reusing no proposal history, incumbent, HealthGate history, resource-failure feedback, old STOP or contention-polluted OOM evidence; V19 artifacts are forensic evidence only. §14.0 separates what V19 validated (static estimates hold no rejection authority, pre-flight classification correct, candidate/infrastructure failures distinguishable, C13 stop semantics) from what it exposed (seven defects). New priority **P0-5** added as §12A: HealthGate detected severe collapse on all four rounds — `unique_int8` of 1–4 out of 256, one round emitting a constant signal — recorded `would_invalidate_under_production_policy: true`, and still resolved to `continue`, so collapsed rounds counted as results and formal ran on a plan no valid trial supported. Gate-path defect, mis-calibrated thresholds and novel-architecture false positives are each ruled out by the artifacts. §13.1 adds a launch gate splitting the work into six blocking requirements and five non-blocking improvements, and §13.2 records the PR A–E ladder with the rule that each problem needs its own acceptance criteria. |
| 1c | 2026-07-31 | Remediation plan added as §6.6 (operator decision): **PR A** routes the production pre-flight through the existing `run_isolated_preflight` and keeps the chain parent CPU-only — a call-site replacement, not a rewrite, with identical inputs, outputs and dispositions — plus production-wiring guardrails so "built but never called" cannot recur. Training and inference keep their subprocess architecture, which already returns memory correctly. Explicit non-goals recorded: no dynamic chain kill, no NVML scheduler, no memory broker, `empty_cache()` never as the primary fix, and no raising of the 12 / 28 GiB or host-quota ceilings, since the defect is double-held resources rather than a low ceiling. **PR B** (chain/pair NVML aggregation and contention-aware OOM attribution) is conditional on the phase-3 two-chain validation still showing risk, and must never be merged into PR A. Validation sequenced as wiring → bounded single-chain → bounded two-chain, with the chain peak measured rather than assumed. §11.2 restructured into four numbered entry points for resource-driven shrinking, adding door 4: the time estimate is rendered into the planning prompt (`prompts.py:645-650`) with an explicit "over" verdict — the arch formal round was shown "factor 1.98 (over)" for a round that took 96.3 min against a 120 min budget, a 2.47× over-prediction reaching the decision-maker as fact. Recorded as OPEN with no harm demonstrated: that line appeared on the formal round so no later proposal was observed, and the only observable size change went up 87 %. Door 4 is explicitly ranked far below the confirmed door 3. |
| 1b | 2026-07-31 | Campaign stopped and closed out. §6.1 upgraded from OPEN INVESTIGATION to **CONFIRMED DEFECT**: the chain parent's 6.9 GiB is the in-process VRAM pre-flight, traced call-path by call-path and confirmed by a pre-registered falsifiable prediction — the parent held 6,962 MiB unchanged across 13 samples over 3 minutes *after* its child exited, alone on the GPU. The fix (`run_isolated_preflight`, PR #151) exists and is GPU-validated with zero production call sites, making this the second instance of the P0-1 pattern; a reachability check is now a V20 requirement. §14 records the operator's 20:15 reversal on the §6.5 evidence and the full closeout: C13's three stop layers all correct, waves 2-4 never started, GPU returned to baseline, 645,054 tokens / $1.94 spent, and 20 observations that advanced calibration by nothing. |
| 1a | 2026-07-31 | Same day, before commit: §6.3 upgraded from HYPOTHESIS to CONFIRMED by direct measurement — pair total 28,732 MiB past the 28 GiB ceiling, loss chain tree 17.74 GiB against a 12 GiB cap, chain parents holding 55 % of all GPU memory. §14 escalation fired and is recorded with the operator's continue-with-monitoring decision; §6.4 records the accepted risk (a host-quota SIGTERM carries no memory error and resembles the misattributed C12 signature). |
| 1 | 2026-07-31 | Created from findings during the fresh V19 restart (`v19r3_10iter_20260731_1842`) after the runtime-estimation C1-C14 ladder and the PR #151 VRAM-preflight repair. Records: zero production promotion call sites; `model_family="unknown"` on all observations; the corrected `bucket_key` diagnosis; chain parent + sandbox child GPU aggregation; absent production RSS telemetry; the unresolved long-sequence amplification question; cross-campaign STOP scope; host-memory config portability; and model-scale monitoring. |

---

## 20. Proposed V20 PR Plan

Sections 1-19 record what V19 found and what V20 must fix. This section
translates those priorities into a small number of reviewable
implementation PRs, so that execution does not have to re-derive scope
and unrelated problems do not collect in one change.

**This section authorizes no implementation.** It defines how each PR
must be audited, built, validated and merged.

### 20.1 Planning principles

#### Gradual genericization (binding — §1.4)

Every PR below is additionally bound by §1.4: it must not deepen the
framework's dependence on TIDMAD, the denoising task, one metric family
or one machine, and it must move the surface it touches toward the
generic design where that refactor is bounded and directly related.

This is not in tension with the minimal-change principle. Minimal change
governs *how much* a PR does; genericization governs *which direction*
the part it does moves in. A PR that is minimal and moves the wrong way
is still the wrong PR.

#### Minimal-change principle

V20 preserves what already worked in V19: training and inference
subprocess execution, queue sequencing, operator-stop semantics, the
failure classification from PR #151, static-estimate non-authority, the
existing typed result schemas unless a schema change is explicitly
reviewed, and the current advice and scientific workflow unless a
specific PR says otherwise.

The preferred strategy, in order:

```
wire existing validated components into production
    before
building new infrastructure
```

Two of the five blocking problems (§13.1) are wiring, not construction.

#### One causal problem per PR

Each PR carries one dominant causal claim. Isolated pre-flight wiring,
GPU aggregation, calibration promotion, HealthGate policy and
campaign-control paths must not be combined — a regression in a combined
change cannot be located.

#### Evidence before expansion

Appearing in this plan does not authorize a PR. A conditional PR begins
only when the preceding validation shows it is necessary.

#### Per-PR design doc, reviewed before implementation

**Operator rule, 2026-07-31.** Every PR in this plan gets its own design
document under `docs/design/v20_priorities/`, and **no implementation
starts until the operator has reviewed and approved that document.**

```
docs/design/v20_priorities/
    pr_a_isolated_preflight_wiring.md
    pr_b_gpu_aggregation_attribution.md
    pr_c_measured_evidence_admission.md
    pr_d_healthgate_formal_policy.md
    pr_e_campaign_scoped_control.md
    README.md          — index and status of the five
```

Each document carries the §20.11 template filled in, the required
pre-implementation audit **already performed and evidence-cited**, the
commit plan, the checkpoints, and the validation plan. This mirrors the
V19 workflow (`docs/design/v19_priorities/`), which caught scope and
factual errors in review rather than in code.

This section (§20) defines *what* each PR must contain. The per-PR
document is where the actual audit findings, design decisions and commit
plan live. **Do not implement from §20 alone** — it is deliberately
scope-level, and the audits it requires will change the design.

#### Reachability requirement

Every production feature ships with a test proving the **actual
production call path** reaches it. Unit tests exercising a component in
isolation are insufficient.

This is not a stylistic preference. Two components in V19 were built,
tested, and in one case GPU-validated, and neither had a production call
site: calibration promotion (§3.2) and the isolated pre-flight worker
(§6.1). Both defects were invisible to a green test suite.

### 20.2 PR overview

| PR | Title | Main problem | Dependency | Blocking for V20 launch? |
|---|---|---|---|---|
| **A** | Wire isolated pre-flight into production | Long-lived parent retains a CUDA context and allocator cache | none | **Yes** |
| **B** | Chain/pair GPU aggregation and contention attribution | The per-attempt cap does not constrain actual chain process-tree usage | PR A validation | **MERGED 2026-08-02** (PR #153) |
| **C1** | Calibration identity, promotion and honest reporting | Observations are collected but never promoted, applied, or reported as unauthoritative | independent after design review | **Yes** — implemented, in review |
| **C2** | Authoritative GPU requirement acquisition and delivery | PR B's admission gate has no production input | C2 producer audit | **Yes** — not authorized yet |
| **D** | Formal HealthGate and zero-valid-trial policy | V19 deliberately used observe-only mode; formal proceeded with no valid trial | operator policy decision | **Yes** |
| **E** | Campaign-scoped control state | An old campaign's STOP can block a new campaign | independent | **Yes** |

Optional follow-ups, none of them launch blockers: GPU and host-memory
telemetry; portable host-memory configuration; model-scale trend
reporting; runtime-estimate quality reporting. Fold one into A-E **only**
when the scope stays small and validation stays attributable to a single
cause.

### 20.3 PR A — Wire isolated pre-flight into production

> **STATUS 2026-08-01: COMPLETE AND VALIDATED. Ready to merge (PR #152).**
> Full record in `v20_priorities/pr_a_isolated_preflight_wiring.md`.
>
> | Phase | Result |
> |---|---|
> | Implementation | isolated-worker wiring, parent-side adapter, production call-site switch, 13 reachability guardrails |
> | **A5** single chain | **PASS.** Parent never appeared in `nvidia-smi` across 910 samples, peak **0 MiB** |
> | A5 contract | **FAIL first**, then repaired: the IPC model silently dropped **eight** worker fields, including `limit_gb`, so `memory.vram_budget_gb` landed null where 456 pre-PR-A records held 12.0. Repaired and revalidated — 10/10 |
> | **A6** dual chain | **PASS.** Both parents 0 MiB, 125.9 s of genuine concurrent training, pair peak **15.52 GiB** vs V19's **28.05 GiB**, no OOM, no orphan, no watchdog |
>
> **Verdict:** `A6 PASS — PR A READY TO MERGE; PR B REQUIRED BEFORE V20 LAUNCH`.
>
> Two lessons are recorded in the PR doc rather than here: a finding
> asserted from source (F1, "the parent must appear in `nvidia-smi`")
> was refuted by measurement and had already been used to weaken a pass
> criterion; and 47 passing adapter tests missed a real regression
> because each serialization layer was tested alone and the composed
> path never was.

#### Objective

Route the production VRAM pre-flight through the already-implemented,
GPU-validated isolated worker. The long-lived chain parent must remain
CPU-only.

#### Confirmed root cause

```
production pre-flight runs in the chain parent
  → parent initializes CUDA
  → parent retains 6.9-8.9 GiB driver-visible memory
  → training/inference children allocate additional GPU memory
  → one chain exceeds its intended resource envelope
```

Wind-down evidence, arch chain alone on the GPU (§6.1):

```
child exited
  → parent retained 6,962 MiB unchanged for ~3 minutes (13 samples)
  → parent exited
  → GPU returned to the 273 MiB baseline
```

#### Scope

Only: the production pre-flight call boundary; the compatibility adapter
between the production caller and `run_isolated_preflight`; minimal
provenance recording; reachability tests; and the minimal phase-level
resource telemetry that validation requires.

#### Out of scope

Pre-flight algorithms, candidate configuration, batch-search policy,
typed dispositions, capacity authority, timeout values, the 12 GiB cap,
the 28 GiB pair ceiling, training execution, inference execution, queue
logic, HealthGate, calibration promotion, agent prompts.

`torch.cuda.empty_cache()` is not the primary repair (§6.6).

#### Required pre-implementation audit

Audit and document, before editing: every production caller of the
current in-process VRAM skill; the exact input schema; the exact output
schema; exception mapping; artifact paths; logging and feedback text;
timeout semantics; host-memory enforcement; model import and
construction ownership; and whether any caller depends on in-process
mutable state.

Produce a compatibility table:

| Behavior | Current in-process path | Isolated path | Required adapter |
|---|---|---|---|

**No implementation begins until this table is complete**, because the
two paths are already known to differ: the worker returns a bounded
typed disposition while the production caller consumes a richer result
dict. The adapter is the substance of this PR, not an afterthought.

#### Checkpoints

**A1 — Call-path audit complete.** Before/after production call graph;
full caller inventory; compatibility table; no unresolved input/output
mismatch.

**A2 — Production wiring implemented.**

```
parent
  → launch isolated pre-flight worker
  → receive bounded structured result
  → worker exits
  → parent remains CPU-only
```

**A3 — Deterministic compatibility.** Identical normalized input;
identical disposition mapping; identical agent-facing feedback; identical
artifacts where semantics require compatibility; no candidate model
construction in the parent; no production reachability to the old
in-process path.

**A4 — CI green.** ruff, formatting, strict pyright, affected pytest
suites, guardrails, production reachability tests.

#### Deterministic validation

1. formal production reaches `run_isolated_preflight`;
2. formal production cannot reach in-process GPU pre-flight;
3. the parent does not instantiate the candidate;
4. the parent does not initialize CUDA;
5. worker cleanup is complete;
6. result mapping is equivalent;
7. failure classification is unchanged;
8. timeout behaviour is unchanged;
9. training and inference subprocess paths are unchanged;
10. a regression test **fails** if direct in-process execution is restored.

#### Bounded real validation

**Phase A5 — single-chain GPU validation.** One bounded chain. Measure:
parent driver-visible GPU memory; pre-flight worker peak; worker memory
after exit; training child peak; inference child peak; chain
process-tree aggregate; allocated peak; reserved peak; driver-visible
peak; host RSS peak; orphan state.

```
pass criteria
  parent remains absent from nvidia-smi
  pre-flight worker releases GPU memory on exit
  training/inference paths unchanged
  no orphan
  no scientific-path regression
```

**Do not assume the chain fits under 12 GiB. Measure it.** The 17.74 GiB
figure from V19 was taken under contention and may not bound a
standalone run (§6.1).

**Phase A6 — dual-chain lightweight validation.** A bounded arch/loss
pair. Measure each chain aggregate, pair aggregate, host-quota margin,
process count, and any OOM with its attribution context. Pass when both
parents stay CPU-only, the pair aggregate stays safely below the campaign
ceiling and host quota, no contention-attributable candidate evidence is
produced, and no processes accumulate.

#### Stop conditions

Stop for operator review if production requires a persistent schema
change; caller behaviour cannot be preserved; the isolated worker cannot
represent an existing production outcome; the parent still initializes
CUDA after wiring; training or inference must be redesigned; or
validation reveals a new architecture-wide lifecycle problem.

#### Merge criteria

All checkpoints pass; single-chain validation passes; dual-chain
validation passes **or clearly demonstrates the need for PR B**;
production reachability is proven; no unrelated workflow change is
included.

#### Dependencies

None. PR A is the entry point of the ladder.

#### Expected artifacts

The compatibility table; before/after production call graph; the
single-chain and dual-chain measurement records (allocated, reserved,
driver-visible, host RSS, per phase); the reachability test suite; a
manifest field recording the pre-flight execution mode.


### 20.4 PR B — Chain/pair GPU aggregation and contention attribution

#### Start rule — RESOLVED 2026-08-01: PR B is REQUIRED

The condition was: begin only if PR A validation shows chain process-tree
usage can still exceed its intended scope, pair usage can still approach
the host quota, OOM attribution remains ambiguous, or driver-visible
occupancy cannot be inferred safely from candidate measurement alone.

**A6 satisfied the fourth clause outright, and the first as a
consequence.** Measured on 2026-08-01 with both parents CPU-only and
125.9 s of genuine concurrent training:

| Chain | Pre-flight estimate | Driver-visible peak | Ratio |
|---|---|---|---|
| A `wavenet` (302,784 params) | 6.429 GB | **12,820 MiB = 12.52 GiB** | 1.95× |
| B `punet` (6,762,568 params) | 1.655 GB | 3,076 MiB = 3.00 GiB | 1.82× |

Chain A was **admitted at an estimate of 6.43 GB and then held 12.52 GiB
— past the 12 GiB per-attempt cap it was admitted under.** Admission
compares a predicted *allocated* peak; the host quota counts
driver-visible *reserved*. These are different quantities, so

```text
estimated <= 12 GiB   does NOT imply   driver-visible <= 12 GiB
```

**What this does not license.** Two samples do not establish a scaling
constant. The observed 1.8–2.0× spread shows the estimate cannot
currently protect a driver-visible quota; it does **not** mean the gap
is 1.9× for every architecture, batch size and phase, and PR B must
therefore **measure the real aggregate rather than multiply the estimate
by any factor**. An earlier draft of the A6 report projected "2 × 12 ×
1.88 ≈ 45 GiB" — admissible as a risk illustration, inadmissible as a
conclusion, and recorded here so it is not quoted as one.

The pair was safe in A6 (15.52 GiB against a 28 GiB ceiling), but the
safety came from the candidates being small relative to the cap, not
from any mechanism. The mechanism that is supposed to bound the pair is
absent on both sides: the per-attempt cap does not bound actual usage,
and `core/runtime_control/pair_admission.py` — which defines the 28 GiB
ceiling — has **zero production callers**, so nothing enforces it at
runtime. During A6 the only thing standing between the run and the host
watchdog was an external validation monitor, which is not part of the
product.

So PR A's success and PR B's necessity are separate facts:

```text
PR A removed the redundant parent memory.          DONE, validated.
PR B must make the remaining real total controlled  REQUIRED.
at runtime.
```

PR B is no longer sized "by the evidence" as a possible
telemetry-only change. It is a **V20 launch blocker** (§13.1
requirement 2), with the minimum scope below.

#### Objective

Measure and attribute actual driver-visible GPU usage at process,
attempt, chain process tree, pair, and host-user levels, and prevent peer
contention from becoming candidate-level evidence (§1.3, §6.5).

#### Minimum scope — operator decision 2026-08-01

PR B does three things and no more. It is not a scheduler.

**1. Account for real memory, not predicted memory.**
Sum driver-visible usage over every GPU child of a chain, and over both
chains. Driver-visible is the quantity the host quota counts, so it is
the quantity the guard must use. The existing per-attempt estimate stays
where it is and keeps its current job — it is a planning input, not a
resource fact, and A6 showed it cannot serve as one.

**2. Check headroom before a new GPU phase starts.**
Before a chain launches a training or inference child, ask: what does
the peer hold right now, what will this phase need, and is there
headroom under the ceiling? This is the check `pair_admission.py`
already models and that nothing calls; wiring it — with measured inputs
rather than configured caps — is most of the work. **A guard that exists
and is never invoked is the defect this whole document was opened
about**, so PR B's acceptance must include a production-reachability
guardrail of the kind PR A shipped (a test that fails if the call site
is removed).

**3. Attribute an OOM correctly.**
Three outcomes must be distinguishable and separately recorded:

```text
candidate exceeded the limit while running alone   -> candidate failure
candidate failed while the peer held the memory    -> contention evidence
host quota killed the process                      -> infrastructure failure
```

Only the first may ever reach an agent as a reason to shrink a model.
The second and third must never do so — that misattribution is what
V19's §6.5 recorded, and it is why a wrong OOM label is more damaging
than a missing one.

**Explicitly still out of scope**: automatic peer killing, dynamic
concurrency reshaping, a memory broker, a general GPU scheduler, silent
serial fallback, and any raising of the 12 / 28 GiB or host-quota
ceilings.

#### Scope

Process-to-chain registration; lightweight NVML or equivalent
driver-visible measurement; chain and pair aggregate accounting; OOM
context capture; attribution logic; pre-launch or pre-phase aggregate
headroom checks; structured contention evidence.

#### Out of scope

A dynamic GPU scheduler; automatic peer killing; a memory broker;
automatic concurrency reshaping; silent serial fallback; threshold
increases; major queue redesign.

#### Required audit

Parent/child process lifecycle; process groups; CUDA-owning PIDs;
existing queue peer identity; external host-watchdog behaviour; the
current 12/28 GiB semantics; all OOM consumers; every place where an OOM
becomes agent feedback; current pair-guard inputs; and whether
driver-visible usage can be sampled reliably without privilege.

#### Attribution model

At minimum distinguish:

```
candidate-attributable
peer-contention-attributable
foreign-contention-attributable
host-quota intervention
unknown attribution
```

**A measurement carries rejection authority only when attribution is
sufficient.**

> **SUPERSEDED 2026-08-01 — see the PR B design's frozen §0.** The
> vocabulary above is the original scoping sketch and is **not** what
> was implemented. Two changes, both decided after audit:
>
> - **The peer/foreign split was declined for v1 (D-B1).** No peer
>   identity exists anywhere in the Python codebase, and inventing one
>   would mean a cross-chain registry — a larger system than the bug
>   requires. B-C1 measures "ours" versus "everything else" instead.
> - **"host-quota intervention" was split in two.** It conflated the one
>   case that is about the candidate's host footprint
>   (`host_memory_pressure`) with the one that is about the environment
>   (`external_termination`), and a `-9` cannot tell them apart.
>
> The implemented vocabulary is exactly five members —
> `candidate_gpu_capacity`, `gpu_contention`, `host_memory_pressure`,
> `external_termination`, `unknown` — of which **only the first**
> carries resource-reduction authority, enforced at construction.
> Checkpoint **B1**'s process identity model (campaign/wave/chain/…
> roles) and **B2**'s persisted peer occupancy are superseded by D-B1
> and D-B5 for the same reason; the "Expected artifacts" list below
> still names the process identity model, which PR B does not build.

#### Checkpoints

**B1 — process identity model.** Every GPU process maps to campaign,
wave, chain, run, iteration, phase, candidate, and parent/child role.

**B2 — telemetry correctness.** Persist allocated, reserved,
driver-visible, chain aggregate, pair aggregate, free GPU memory, peer
occupancy, timestamp and phase.

**B3 — attribution rules.** A real CUDA OOM must not automatically imply
candidate failure; the record shows whether the candidate, the peer, or
the host environment caused the condition.

**B4 — admission integration.** Check real aggregate headroom before
launching a new GPU phase. **Do not interrupt an active peer
automatically in this PR.**

**B5 — validation and CI.**

#### Deterministic validation

PID-to-chain attribution; process-tree aggregation; pair aggregation;
stale PID handling; PID reuse; missing telemetry; peer identity;
candidate OOM; contention OOM; host-watchdog signature; and no
candidate-downsizing authority for unattributable events.

#### Controlled GPU validation

Deliberately constructed scenarios: (1) a candidate genuinely exceeds
capacity; (2) a candidate fits alone but fails under expected peer
contention; (3) foreign GPU contention; (4) pair below ceiling; (5) pair
near ceiling; (6) host-quota-like termination; (7) worker exits and
memory returns.

#### Merge criteria

Contention OOM never becomes candidate evidence; genuine candidate OOM
retains authority; the pair aggregate protects the actual host limit;
missing attribution yields non-authoritative evidence; no scheduler or
automatic-kill behaviour is introduced.

#### Stop conditions

Stop for operator review if driver-visible sampling proves unreliable
without elevated privilege; if PID-to-chain attribution cannot be made
deterministic under PID reuse; if a headroom check would have to
interrupt a running peer to be effective; or if the attribution model
cannot separate peer contention from candidate capacity on real data.

#### Dependencies

PR A merged and its dual-chain validation complete. The *size* of PR B
follows those measurements (§20.4 conditional start rule).

#### Expected artifacts

The process identity model; per-phase aggregate telemetry records; the
seven controlled-scenario results; OOM records carrying peer occupancy
and free VRAM as they were before the failure.


### 20.5 PR C — Measured-evidence admission and calibration production wiring

> **Status, 2026-08-02.** PR C is implemented as **two** PRs. The
> authoritative record for both is
> `docs/design/v20_priorities/pr_c_measured_evidence_admission.md`.
>
> * **C1 — calibration identity, promotion and honest reporting.**
>   Implemented on `feature/v20-pr-c1-calibration-identity-promotion`, in
>   review. Layer-3 validated on real hardware (§17b there).
>   **C1 supplies nothing to PR B's admission gate, by design** — duration is
>   milliseconds, and a promoted millisecond is never a memory requirement.
>   So the D-B5 dependency below is **C2's**, not C1's.
> * **C1 scope correction:** historical duration is **observability-only** —
>   collected, promoted and reported, but never an input to the production
>   allow/reject time decision (operator decision, 2026-08-02). The paragraph
>   below describing PR C as owning "calibration production wiring" is
>   therefore accurate for C2 and **not** for C1.
> * **C2 — authoritative GPU requirement acquisition and delivery.** Not
>   authorized; gated on the read-only producer audit.

#### D-B5 dependency — PR C owns formal cold-start measurement

**Operator decision 2026-08-01.** PR B refuses a formal GPU phase when
no applicable *authoritative* driver-visible measurement exists, and
deliberately does **not** build its own acquisition or promotion path —
a second measurement authority is the shape of defect this document was
opened about.

PR C therefore owns supplying the first trustworthy measurement for a
formal candidate. The consequence, recorded rather than discovered
later:

```text
PR B may merge independently.

Formal V20 campaign launch requires BOTH
  PR B  runtime enforcement
  PR C  authoritative measurement production / promotion
```

Since every chain iteration proposes a new plugin, an unknown candidate
is the normal case — so until PR C lands, formal mode with new
candidates is blocked by design, not by accident.

#### What PR C is, stated against PR B

**Operator clarification, 2026-08-02.** The two are often conflated
because both concern "GPU memory", so the split is stated in one line
each:

```text
PR B   given a trustworthy measurement, admit or refuse the phase
       correctly before training starts

PR C   where that measurement came from, whether it genuinely applies
       to THIS candidate, and when it may be marked authoritative
```

PR C's checks are the applicability tuple, all of which must match
before a raw collected figure becomes admission-usable evidence:

```text
task and dataset / data-shape class
full model configuration
phase (training | inference)
runtime settings — batch, segment, portions
GPU UUID and hardware environment
measurement type and quality
```

Only after those pass may a figure be promoted from *just collected* to
*authoritative*. **A matching model name is not applicability.** Reusing
an older machine's number because the architecture is called the same
thing is precisely the unearned authority §1.3 exists to prevent.

#### Where PR C is developed, and where it must be exercised

These are different questions and were being answered as one.

**PR C's implementation is generic framework work and must not be done
on H100.** It should be built, unit-tested and reviewed on the normal
development branch, on whatever machine is convenient. Nothing about
applicability logic requires a particular card.

**But the measurement and promotion themselves must happen on the
hardware they describe.** When SIDERIUS moves to H100, PR C's flow has
to be *run there*:

```text
resolve the H100 GPU UUID
→ collect a bounded measurement on that device
→ PR C checks completeness and applicability
→ promote it as the H100's authoritative measurement
→ only then may PR B use it in a formal run
```

A 5090 measurement cannot become an H100 authoritative record even for a
byte-identical candidate: driver, memory management and real occupancy
differ, and A6 already showed predicted and driver-visible figures
diverging by ~1.9x on one card alone.

| Activity | Needs H100? |
|---|---|
| PR C implementation, unit tests, review | **No** — do it on the current machine |
| Collecting and promoting the H100 measurement | **Yes** — it describes that device |
| H100 formal campaign | **Yes**, and needs PR B *and* PR C complete |
| lilab B-G1/B-G2 | **No** — validates PR B with an explicitly labelled validation-only fixture, which is **not** PR C completion |

The last row matters for how B-G's report is read: passing B-G1/B-G2 on
lilab demonstrates that PR B uses applicable evidence correctly. It does
not demonstrate acquisition, applicability validation or promotion, and
the fixture it uses is labelled validation-only precisely so it is never
mistaken for a promoted record.

Cross-hardware bring-up as an operator sequence lives in
`docs/running_chain_test.md` ("New GPU host"), with the design rationale
in the PR B document §4b.

#### Genericization requirement (§1.4)

**A calibration record is a measurement of one thing under one set of
conditions. It is not a fact about the framework.** PR C's whole
subject is deciding when past evidence applies to a present candidate,
so applicability must be indexed by explicit dimensions, at minimum:

```text
task
dataset / data-shape class
phase
model or config identity
hardware identity
measurement type
```

Without those, TIDMAD calibration records silently become universal
constants — a record measured on this RTX 5090, on TIDMAD segment
lengths, for a denoising training phase, would be consulted for a
different task on different hardware and answer confidently.

That is §1.3's failure mode reached through a different door: evidence
used with an authority it never earned. §3's applicability rule already
says historical evidence must be *shown* applicable; PR C must make the
dimensions of that showing explicit rather than implicit in a bucket
key.

The registry root (`~/.siderius/runtime_calibration`) is per-user, so
records from different tasks and machines already share one store.
Indexing is not optional there.


#### Objective

Every formally admitted candidate has measured evidence applicable to
that concrete candidate (§3.5), and calibration promotion runs in
production.

#### Scope

Production call to promotion evaluation; production call to promotion
recording; correct `model_family` propagation; calibration-quality
reporting; the applicability predicate; admission consumer integration;
removal of terminal `ADVISORY` for formal admission.

#### Out of scope

Predicting arbitrary unseen architectures from history. Treating a
matching bucket key alone as establishing applicability. Changing static
prior semantics.

#### Required audit

Observation creation; the model-family source; bucket-key derivation;
promotion policy; the registry write path; promotion consumers; the
current admission decision graph; every terminal `ADVISORY` path; current
live-probe result handling; calibration invalidation and versioning.

#### Required design decision

Define applicability to the concrete candidate. Candidate dimensions:
architecture family; realized parameter range; batch; segment length;
operation; dtype; hardware; software stack; concurrency condition;
distance outside the observed range.

**Do not implement this predicate without an explicit design record.**

#### Checkpoints

**C1 — production promotion reachability.** A production observation
triggers promotion evaluation.

**C2 — family identity.** Known candidates no longer produce
`model_family="unknown"`.

**C3 — calibration quality report.** Campaign reports include
observations, bucketed/unbucketed, eligible, promoted, rejected,
rejection reasons, and coverage.

**C4 — admission authority.** Formal admission requires applicable
validated calibration **or** a successful bounded live probe.

**C5 — inconclusive fallback.** An inconclusive probe cannot silently
allow or reject; the fallback policy is explicit.

**C6 — real production confirmation.** A bounded real campaign proves
`observation → promotion evaluation → validated or rejected bucket →
admission consumer`.

#### Validation layers

**Layer 1** — deterministic reachability, schema, identity, authority.
**Layer 2** — broad controlled scenarios across families, scales,
hardware, concurrency, matching and mismatching buckets, repeated
observations, and contradictory measurements.
**Layer 3** — a small bounded real LLM + real training run proving
end-to-end production reachability.

#### Merge criteria

Production promotion actually occurs; family identity is correct; formal
admission never terminates at static `ADVISORY`; applicability is
explicit; live measurement overrides stale or inapplicable history; and
the campaign report cannot falsely imply calibration is active.

#### Stop conditions

Stop for operator review if the applicability predicate cannot be
defined without inventing thresholds; if promotion would require
observations whose identity is still incomplete; if removing terminal
`ADVISORY` would block candidates that no probe can measure in bounded
time; or if live measurement and validated calibration contradict each
other with no rule for which wins.

#### Dependencies

Independent of PR A and B after its design record is approved. Its
Layer-3 confirmation needs a working bounded real run, so in practice it
follows PR A.

#### Expected artifacts

The applicability design record; promotion evaluation and recording call
sites with reachability tests; the calibration-quality report format;
Layer-2 scenario matrix results; a bounded real-campaign trace showing
observation through admission.


### 20.6 PR D — Formal HealthGate and zero-valid-trial policy

#### Genericization requirement (§1.4)

**HealthGate is where task-specific science currently lives inside
generic orchestration**, so this PR is the clearest case of the §1.4.2
split.

Generic orchestration may own: whether a gate is **blocking or
observational**, whether its verdict is **authoritative or
non-authoritative**, gate ordering, severity resolution, and how a
verdict changes control flow.

The task configuration/plugin owns: what counts as collapse, the
metrics, the thresholds, what a valid result is, and the scientific
acceptance rules. `OutputDiversityCheck`'s `unique_int8 > 25` and
`AmplitudeCollapseCheck` are **denoising-specific**; a spectroscopy or
reconstruction task would have entirely different collapse signatures
and the same orchestration.

`configs/health_checks.yaml` is already the right shape — policy in
configuration rather than code. PR D must not undo that by moving
thresholds into the orchestrator while making them formal-aware.


#### Objective

Define which HealthGate mode a formal scientific campaign uses, and what
happens when no trial is valid.

#### Confirmed facts (§12A)

The repository default config invalidates failed blocking checks; V19
explicitly selected the observe-only config; `resolved_action=continue`
was correct for that config; this was a campaign-policy choice, not an
enforcement defect; all four observed rounds showed severe collapse; zero
valid trials existed; formal still ran under override.

#### Required operator policy

A formal V20 scientific campaign uses the true blocking config unless the
operator explicitly selects a diagnostic mode. Observe-only remains valid
for baseline characterization, threshold studies, diagnostics and gate
calibration.

#### Scope

Explicit campaign HealthGate mode; unambiguous resolved mode in the
manifest; zero-valid-trial handling; non-authoritative formal override;
incumbent exclusion; scientific-aggregation exclusion; structured
all-trials-invalid feedback; clearer operator-facing labels.

#### Out of scope

Retuning thresholds without new evidence; removing observe-only mode;
forcing a successful trial.

#### Required audit

Config selection in launchers; effective-config materialization;
gate-action resolution; valid-trial counting; `Best score: None`; the
formal override; incumbent ingestion; report aggregation; grand-mean
inclusion; planner feedback.

#### Checkpoints

**D1 — explicit mode.** The manifest states `blocking`, `observe_only`
or `diagnostic` plainly.
**D2 — valid-trial invariant.** Zero valid trials ⇒ no authoritative
formal scientific result.
**D3 — diagnostic formal.** May run, but is marked non-authoritative.
**D4 — incumbent exclusion.** No zero-valid-trial formal result enters
incumbent selection.
**D5 — reporting exclusion.** No non-authoritative formal result enters
scientific aggregation.
**D6 — feedback.** The planner receives structured all-trials-invalid
evidence.

#### Validation

Blocking mode; observe-only mode; zero-valid-trial; one-valid-trial;
mixed valid/invalid; diagnostic formal; incumbent exclusion; reporting
exclusion; manifest provenance. Layer 3 uses a small bounded real run
that **deliberately produces collapse** and proves the formal result
cannot become authoritative.

#### Merge criteria

Campaign mode is explicit; no authoritative result exists without a valid
trial; observe-only remains available and honest; labels do not
contradict effective behaviour; incumbent and reports enforce the policy.

#### Stop conditions

Stop for operator review if the blocking config would invalidate rounds
that are scientifically legitimate on some band; if zero-valid-trial
handling would deadlock an iteration with no path forward; or if
excluding non-authoritative results empties the report entirely, which
would indicate a deeper problem than gate policy.

#### Dependencies

An operator decision on the default mode for formal campaigns (§12A.4).
Otherwise independent.

#### Expected artifacts

The manifest mode field; the zero-valid-trial policy implementation and
its tests; the structured all-trials-invalid feedback block; a bounded
real run that deliberately collapses and proves non-authority.


### 20.7 PR E — Campaign-scoped control state

#### Genericization requirement (§1.4)

Campaign STOP, queue state and scoping are **generic campaign-control
infrastructure**. Two constraints follow.

Names, paths and state schemas must not encode TIDMAD-specific campaign
names, and must not assume exactly **two** scientific chains. The
current launcher hardcodes `MAX_CONC=2` (`v19_queue_runner.sh:80`) and
names the pair `arch`/`loss` (`:412-413`) — both are the *current
campaign shape*, not a framework property. A campaign with one chain, or
five, or chains named for something other than architecture and loss,
must not require a schema change.

`arch` and `loss` are also task-flavoured: they describe what *this*
exploration varies. A different task might vary a reconstruction prior
or a simulation parameter. The generic layer should carry a chain
identity and a role label supplied by configuration, not two names built
into paths.


#### Objective

One campaign's STOP, queue state or pair summary cannot control another
campaign.

#### Scope

```
<root>/<campaign_id>/control/STOP
<root>/<campaign_id>/queue_state/
<root>/<campaign_id>/pair_summaries/
```

Historical evidence is preserved.

#### Out of scope

Redesigning stop semantics; removing no-respawn behaviour; deleting
legacy STOP evidence.

#### Required audit

All STOP readers; all STOP writers; queue-level paths; chain-level paths;
runner state; pair-summary paths; resume behaviour; historical layouts;
cleanup scripts; tests and docs.

#### Checkpoints

**E1 — path model.** Every authority-bearing path contains campaign
identity.
**E2 — backward compatibility.** Historical evidence stays readable; a
legacy global STOP cannot block a new campaign.
**E3 — campaign mismatch protection.** The launcher rejects mismatched
campaign state.
**E4 — stop semantics preserved.** Operator stop still stops after the
current iteration, writes stopped state, prevents respawn, and prevents
later waves.
**E5 — recovery validation.** Start and stop multiple synthetic
campaigns and prove isolation.

#### Validation

Old campaign stopped and new campaign starts; two campaigns coexist;
wrong-campaign STOP ignored; correct-campaign STOP honoured; historical
global STOP archived and readable; resume reads only matching campaign
state; no destructive cleanup required. A small shell-level real queue
test may be used without GPU.

#### Merge criteria

No cross-campaign authority; stop semantics unchanged; historical
evidence preserved; no manual root-level cleanup required before a new
launch.

#### Stop conditions

Stop for operator review if historical layouts cannot be read without
ambiguity; if any authority-bearing path cannot carry campaign identity
without changing stop semantics; or if migration would require deleting
existing evidence.

#### Dependencies

None. PR E touches launcher and path logic only.

#### Expected artifacts

The path model; the campaign-mismatch guard; the multi-campaign
isolation test; a record of which historical layouts remain readable.


### 20.8 Optional telemetry and portability PRs

**Telemetry PR** — allocated/reserved/driver-visible GPU metrics; bounded
RSS phase peaks; process identity; model-scale trend reporting; admission
evidence summaries. Merge into A/B/C only if the scope stays narrow.

**Portable host-memory policy PR** — implement only after the launch
blockers are resolved. Requirements: backward-compatible legacy
behaviour; a fixed config mode; an opt-in hardware-aware mode; the
environment override preserved; resolved provenance persisted. Not a
launch blocker unless V20 must run on a different host.

### 20.9 Global checkpoints before V20 launch

**Implementation**

- PR A merged and GPU validated — **A5 + A6 PASS 2026-08-01**, merge pending;
- PR B completed. **The "or formally deemed unnecessary" branch is
  closed**: A6 measured the per-attempt cap being exceeded by an
  admitted candidate (12.52 GiB against a 12 GiB cap) and confirmed the
  28 GiB pair guard has no production caller, so PR B is required rather
  than conditional (§20.4);
- PR C merged and production reachability demonstrated;
- PR D merged and the zero-valid-trial policy proven;
- PR E merged and campaign isolation proven.

**Validation**

- deterministic CI green;
- broad controlled Layer-2 validation;
- bounded real GPU validation;
- small bounded real LLM + training validation;
- no production feature exists only in tests;
- parent orchestrators remain CPU-only;
- pair GPU usage remains below the operational ceiling;
- measured failures have both correct classification **and** attribution;
- formal admission has applicable measured evidence;
- no authoritative scientific result exists without a valid trial;
- a new campaign cannot read authority-bearing state from old campaigns.

**Final Gate.** One bounded Gate exercising: isolated pre-flight;
single-chain GPU lifecycle; dual-chain GPU lifecycle; chain/pair
aggregation if implemented; measured-evidence admission; promotion
reachability; HealthGate blocking; zero-valid-trial behaviour;
campaign-scoped stop; iteration restore.

**The Gate must use real production entry points. Do not create test-only
launch paths** — that would reproduce the very defect this plan exists to
prevent.

### 20.10 Recommended execution order

```
PR A                              DONE 2026-08-01
  → single-chain GPU validation   A5 PASS (contract repaired, revalidated)
  → dual-chain GPU validation     A6 PASS
  → decide whether PR B is required
                                  DECIDED: REQUIRED (§20.4)
  → merge PR #152                 <-- next

PR B (REQUIRED — no longer conditional)
  → independent design audit first, per the §20.1 per-PR rule
  → minimum scope only: real aggregate accounting,
    pre-phase headroom check, OOM attribution
  → contention validation

PR C
  → Layer-2 calibration evaluation
  → bounded production confirmation

PR D
  → bounded collapse / zero-valid-trial validation

PR E
  → queue isolation validation

final V20 Gate
  → fresh V20 campaign
```

PR C, D and E may be **developed** in parallel once their design
checkpoints are recorded, but each merges only after satisfying its own
acceptance criteria. PR B's size remains conditional on PR A's
measurements.

### 20.11 PR review template

Every V20 PR fills this in its description or design record. A PR is not
complete until it is filled.

```
Problem statement:
Confirmed evidence:
Scope:
Out of scope:
Production callers:
Persistent schema impact:
Backward compatibility:
Implementation checkpoints:
Deterministic tests:
Layer-2 evaluation:
Bounded real validation:
Failure classification:
Attribution:
Genericization impact:        <- §1.4.5, seven questions, not boilerplate
Hardcoding introduced:        <- classified per §1.4.4, or "none"
Hardcoding removed/deferred:  <- with follow-up IDs for the deferred
Artifacts:
Stop conditions:
Merge criteria:
Dependencies:
Operator decisions:
```
