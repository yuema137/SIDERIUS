# Runtime Estimation and Calibration Architecture

**Status:** Draft  
**Scope:** Generic runtime estimation, calibration, admission, and watchdog control  
**Primary incident motivating this design:** V19 wave 1 uncalibrated proposer pre-flight  
**Last updated:** 2026-07-30

---

## 1. Summary

SIDERIUS currently contains two conceptually different runtime-estimation
paths.

The downstream runtime-control path operates after a candidate model has
been implemented. It can execute bounded warmup and verification runs,
measure training and inference throughput on the current hardware, apply
historical correction factors, and use measured evidence for admission
and watchdog decisions.

The proposer-side pre-flight runs before the candidate model exists as
executable code. It therefore cannot directly measure the proposed model.
The current implementation instead applies a static formula based largely
on the proposal's self-reported parameter count and workload metadata.

The core defect is not that a static prior exists. A static prior can be
useful as a low-confidence risk signal. The defect is that this
uncalibrated prior currently has blocking authority:

```text
uncalibrated proposal estimate
→ reject and revise proposal
→ inject rejection text into the revision prompt
→ persist the resulting resource conclusion into later trajectory context
```

In V19 wave 1, this mechanism rejected an approximately 18.4-million
parameter proposal at an estimated `84.64×` budget factor and a
1.76-million parameter proposal at `8.12×`. A much smaller proposal was
then accepted. The proposer generalized these rejections into a standing
constraint to keep models below approximately 400,000 parameters.

The same behavior is visible historically in V18r and likely contributed
substantially to the repeated generation of `tiny_`, `micro_`, and
`nano_` models.

This document proposes a generic architecture with the following central
rule:

> Static proposal-time estimates may identify risk, but only live
> measurements or explicitly validated calibrated evidence may exercise
> blocking runtime authority.

The long-term design should work without server-specific source-code
patches. Hardware-specific behavior belongs in runtime observations and
calibration artifacts, while all production components consume a shared,
hardware-independent estimation interface.

---

## 1.1 Audit status classification (2026-07-30 code audit)

Every section of this document is classified against the CURRENT
codebase. Markers used throughout:

* **[CONFIRMED CURRENT]** — verified behavior of the existing code, with
  file:line or artifact evidence (§15 holds the citations).
* **[PARTIALLY EXISTS]** — infrastructure exists but is incomplete,
  dormant, or not wired to the consumers this design requires.
* **[PROPOSED]** — does not exist yet; to be implemented (§23 ladder).
* **[OPEN]** — requires an operator decision (§20) or empirical data
  (§24) before implementation.

Section status index:

| Section | Status | Key evidence / pointer |
|---|---|---|
| §1, §4 incident + causal chain | [CONFIRMED CURRENT] | forensic snapshot; chain log rejection lines; §15.1/§15.5-6 |
| §4.1 "calibration available" | [CONFIRMED CURRENT] **with F-1 nuance**: the artifact exists AND is dormant — its only reader/writer (TimeEval warmup) is disabled in current launch posture (empty `data_dir`) | §15 F-1 |
| §5.1 proposal-time pre-flight | [CONFIRMED CURRENT] | `proposer_preflight.py:152-171`; §15.1 row 1 |
| §5.2 runtime verification | [CONFIRMED CURRENT] | RT2 sidecars; §15.1 row 6 |
| §5.3 calibration history | [CONFIRMED CURRENT] with precision note in-section (actual k mechanics differ from the conceptual formula) | `calibration.py`; §15.3 |
| §6 core principles | design intent — [CONFIRMED] as the EXISTING intent of RT1 rev 4 (`training_skill/estimator.py:72-80`), [PROPOSED] as enforced behavior at the proposer edge |
| §7.1-§7.2 unified estimator + request | [PROPOSED] | C3/C5 |
| §7.3 estimate + provenance | [PARTIALLY EXISTS] — `core/runtime_control/records.py:41-72` already defines `PredictionSource` (11 values), `MEASUREMENT_BACKED_SOURCES` as the ONLY formal-eligible set, and a `Confidence` literal; `classify_prediction_source` (total_assembly.py:162) already implements a 3-class authority policy. The §7.3 vocabulary is a renamed superset — C3 MUST reconcile with this, not fork it | records.py |
| §7.4 decision policy object | [PROPOSED] (authority rules exist implicitly in admission/watchdog; no shared policy object) | C3/C4 |
| §8.1 Stage A advisory default | [PROPOSED] — current Stage A is BLOCKING (the defect) | C1 |
| §8.2 Stage B bounded probe | [PARTIALLY EXISTS] — warmup machinery (`wrapper.py:271-430`) implements exactly this measurement, but requires `data_dir`+CUDA+registered type and is dormant (F-1); not wired as a mandatory pre-trial stage | C5 |
| §8.3 historical correction | [PARTIALLY EXISTS] — k-table EMA exists (training only); applicability/extrapolation labels do NOT exist | C6 |
| §8.4 precedence | [PARTIALLY EXISTS] — measurement-vs-prior split exists (records.py); the full 6-tier order does not | C3 |
| §9.1 hardware profile | [PARTIALLY EXISTS] — O1a `HardwareContext` manifests already collect GPU model/count/VRAM, driver, CUDA_VISIBLE_DEVICES, platform, python, repo commit per iteration; compute capability/dtypes/storage class and a schema version are not collected | C5 (extend) |
| §9.2 live resource snapshot | [PROPOSED] (no per-probe contention snapshot exists) | C5 |
| §9.3 cross-hardware reuse | [CONFIRMED CURRENT] as a constraint — per-GPU files, no transfer path exists (and none is claimed) | §15.3 |
| §10 calibration registry | [PARTIALLY EXISTS] — actual storage is a single `~/.siderius/time_calibration_<gpu_slug>.json` (+ `SIDERIUS_CALIBRATION_DIR` override, which ALREADY exists); the proposed multi-dir registry, schema versioning, uncertainty, and contention metadata do NOT exist | §15.3; C6 |
| §11 proposal-context safety | [PROPOSED]; §15.5 confirms the current paths violate it (incl. F-2 template-mandated ceiling) | C2 |
| §12 formal-run invariants | [PROPOSED] — no launch guard exists | C4 |
| §13.1 trial admission record-only | [CONFIRMED CURRENT] (sidecar evidence: trial budget=None) | §15.4 |
| §13.1 probe-before-trial sequence | [PROPOSED] | C5 |
| §13.2 formal admission | [CONFIRMED CURRENT] (measured, factor 2.0) | §15.4 |
| §13.3 watchdog | [CONFIRMED CURRENT] (measured × 3.5, floor 120, kill persists) | §15.4 |
| §14 migration phases | [PROPOSED] roadmap → concrete in §23 |
| §15 audits | [CONFIRMED CURRENT] — completed with evidence |
| §16 risks | [OPEN] analysis; §16.7 realized-vs-proposed param divergence is [CONFIRMED CURRENT] (312K claimed vs 42,064 realized, wave-1) |
| §17 testing strategy | [PROPOSED] (maps into §23 validation plans) |
| §18 acceptance criteria | [PROPOSED] — 33 restart-blocking criteria (operator-resolved list) |
| §19 recovery plan | [OPEN] operator-gated; stop + forensics steps [x] done; restart gated on the COMPLETE architecture (§21 resolved) |
| §20 decisions | D1-D8 all [RESOLVED — operator 2026-07-30]; D3/D4/D5 resolved at the C7 gate and implemented in `calibration_policy.py` |
| §22 design invariant | [CONFIRMED] as documented intent (RT1 rev 4), [PROPOSED] as enforced behavior at every edge |

---

## 2. Goals

This design has six primary goals.

### 2.1 Dynamic estimation

Runtime decisions should be based primarily on bounded measurements of
the actual implemented model on the current machine and under the current
runtime conditions.

The system should measure, where applicable:

* model setup and compilation time;
* training time per step;
* inference time per batch or segment;
* peak allocated and reserved VRAM;
* data-loading and file-transition overhead;
* GPU utilization and clock state;
* competing GPU processes or other resource contention.

### 2.2 Generic hardware support

The same source code must work on different hardware, including but not
limited to:

* NVIDIA H100;
* RTX 5090;
* A100;
* other CUDA GPUs;
* future accelerators supported by the execution backend.

New hardware should require calibration or probing, not source-code
changes.

### 2.3 Unified runtime authority

Proposer pre-flight, tuner/runtime verification, admission, and watchdog
logic must not maintain incompatible private cost models.

All components should consume a shared runtime-estimation protocol and
the same evidence model.

### 2.4 Evidence-aware decisions

Every runtime estimate must include provenance, uncertainty, and
applicability information.

The system must distinguish:

* static prior;
* historical prior;
* live bounded probe;
* in-subprocess runtime verification;
* complete observed execution.

Decision authority must depend on evidence quality.

### 2.5 Safe formal execution

Formal runs must never silently use an uncalibrated static estimate as a
blocking decision.

Missing or insufficient evidence must lead to one of:

* advisory-only treatment;
* a bounded live probe;
* explicit pre-launch failure where calibrated evidence is mandatory.

### 2.6 Clean scientific trajectories

Low-confidence resource estimates must not become persistent scientific
claims or standing architecture constraints.

In particular, the system must prevent conclusions such as:

```text
Keep parameter count below 400,000.
```

from being inferred solely from an uncalibrated pre-flight rejection.

---

## 3. Non-goals

This design does not attempt to:

* predict runtime exactly before implementation;
* guarantee that every accepted proposal finishes within its budget;
* make parameter count a universal proxy for computational cost;
* transfer raw timing values directly between unrelated hardware;
* eliminate watchdog termination;
* optimize model performance or choose model architecture;
* change scientific scoring, HealthGate thresholds, or incumbent policy;
* make all runtime estimates independent of workload configuration.

The system should produce bounded, evidence-qualified estimates rather
than false precision.

---

## 4. Incident description

### 4.1 V19 wave 1

Formal V19 wave 1 launched on the RTX 5090 environment with valid runtime
calibration history available at:

```text
~/.siderius/time_calibration_nvidia_geforce_rtx_5090.json
```

The artifact contained approximately:

* 720 measured historical entries;
* more than 200 per-model correction factors;
* tuner-generated observations from prior runs.

The downstream tuner and runtime-control path could use measured warmup
timing, historical correction factors, and in-subprocess verification.

**[CONFIRMED CURRENT — F-1 correction]**: "available" must be qualified.
The audit (§15) proved the warmup path that reads AND feeds this
artifact was itself disabled in the launch posture (empty `data_dir` →
"[warmup skipped]… falling back to static formula",
`wrapper.py:308-309`), so the artifact was dormant: the k-table's last
entry predates V18r's 2026-07-24 launches. Only RT2 in-subprocess
verification (admission/watchdog) was measured. The incident therefore
has THREE wiring gaps: the proposer edge (below), the dormant
data-path (F-1a), and the unverified fresh-plugin probe capability
(F-1b) — see §15.

The proposer-side pre-flight did not consume this system.

Its production behavior was effectively:

```text
ms_per_step = None
gpu_name = None
inference_ms_per_step = None
```

The pre-flight therefore used a static parameter-count-based formula and
a default inference-batch assumption.

This was not an exceptional lookup failure. It was the normal production
behavior of that path.

### 4.2 Causal chain

```text
scale-oriented formal advice
→ proposer drafts an approximately 18.4M-parameter model
→ static proposer pre-flight estimates 84.64× trial budget
→ proposer is asked to revise
→ proposer drafts an approximately 1.76M-parameter model
→ static proposer pre-flight estimates 8.12× trial budget
→ proposer is asked to revise again
→ much smaller proposal survives the revision sequence
→ rejection messages remain in proposer context
→ proposer persists a sub-400K parameter constraint
→ future iterations inherit the contaminated constraint
```

The resulting 42K and 83K realized models are not evidence that:

* the proposer ignored the advice;
* the 20-minute trial budget was truly infeasible;
* large models cannot run on the machine;
* small models were scientifically preferable.

They are evidence that an uncalibrated static screen exercised excessive
authority before a live measurement was possible.

### 4.3 Historical evidence

A read-only historical audit found the same mechanism in V18r:

* repeated pre-flight rejections;
* factors as high as approximately `12.8×`;
* many `static_uncalibrated` provenance records;
* a chronic population of `tiny_`, `micro_`, and `nano_` plugins.

This indicates a structural design issue rather than an isolated V19
configuration error.

---

## 5. Current architecture

### 5.1 Proposal-time pre-flight

The proposal-time pre-flight runs before model implementation.

Available information may include:

* proposed architecture family;
* estimated parameter count;
* batch size;
* segment length;
* trial workload;
* proposer-authored complexity claims.

Unavailable information includes:

* actual executable graph;
* measured kernel performance;
* real activation memory;
* real training throughput;
* real inference throughput;
* implementation-specific setup overhead.

The current implementation attempts to estimate runtime statically and
can trigger proposal revision.

### 5.2 Runtime verification

After implementation, the tuner/runtime path can execute the actual
candidate model.

It can observe:

* setup time;
* measured training time;
* measured inference time;
* VRAM;
* runtime failures;
* hardware state.

This path is better aligned with the intended runtime-control design.

### 5.3 Calibration history

Historical calibration stores the relationship between bounded runtime
measurements and later observed execution.

A correction factor may conceptually be written as:

```text
k = observed complete runtime / bounded-probe extrapolation
```

**[CONFIRMED CURRENT — actual mechanics]** (`calibration.py:121-192`):
the implemented k is per (gpu, model_type), updated by an ASYMMETRIC EMA
of `actual_ms_per_step / warmup_ms_per_step` (α_up 0.5 on
under-prediction, α_down 0.1 on over-prediction), clipped to
[0.5, 5.0], with a `(gpu, *)` wildcard fallback and a 3-consecutive-
violation drift detector. It covers TRAINING ms/step only — inference
uses a separate hard-coded batch registry (`core/inference_defaults.py`,
silent fallback 25). No uncertainty, applicability range, contention
flag, or schema version is stored (gaps addressed by C5/C6).

The history improves estimates by accounting for effects that a short
probe may not capture, including:

* warmup;
* compilation;
* data transitions;
* validation overhead;
* checkpoint overhead;
* thermal or clock behavior;
* workload-specific fixed costs.

Calibration history should correct live measurement. It should not
replace live measurement when the actual model can be executed.

---

## 6. Core design principles

### 6.1 Live measurement is primary

Once a candidate implementation exists, runtime estimation must begin
from a bounded live probe on the current machine.

Historical calibration is a correction layer around live measurement.

Static formulas are fallback priors and risk indicators.

The estimator architecture has three distinct layers:

```text
1. Raw live measurement
   The actual candidate model is executed for a bounded probe on the
   current machine and current runtime state.

2. Probe extrapolation
   Measured setup, training throughput, inference throughput, and
   workload size are used to project complete runtime.

3. Historical calibration correction
   Historical observations correct systematic differences between the
   bounded probe and the later complete execution.
```

Conceptual decomposition of a projected total:

```text
estimated_total_runtime
=
measured_setup_time
+ measured_training_rate × projected_training_work
+ measured_inference_rate × projected_inference_work
+ calibrated_fixed_overheads
```

One global training `k` value is NOT sufficient for all runtime
components. The design must support separate correction and uncertainty
treatment for: setup; training; inference; I/O or file-transition
overhead; concurrent-execution overhead. (The current single
training-only k-EMA, §5.3, is a legacy input to this design, not its
shape.)

### 6.2 Hardware identity is context, not the estimator

Hardware-specific calibration is still necessary because different
machines have different:

* throughput;
* memory capacity;
* kernel behavior;
* compilation behavior;
* data-transfer behavior.

However, GPU identity alone must never determine the estimated runtime.

The production estimate should combine:

```text
current model measurement
+ current workload
+ current hardware and software state
+ historical correction
+ uncertainty
```

### 6.3 Current contention must be observed

The same machine may behave differently depending on:

* other GPU processes;
* GPU memory pressure;
* utilization;
* clocks;
* power limits;
* CPU or storage contention.

Each bounded probe should therefore record a resource snapshot.

Measurements collected under significant contention must be marked as
such and should not silently update clean calibration history.

### 6.4 Blocking authority follows evidence quality

A runtime estimate may block execution only when its provenance and
applicability satisfy an explicit policy.

Low-confidence evidence must never have greater authority than measured
evidence.

### 6.5 Runtime evidence must be structured

Runtime conclusions should not be represented only as natural-language
warnings.

Every estimate should be a typed record with explicit provenance,
confidence, applicability, and decision eligibility.

### 6.6 Cold start does not discard calibration

A cold scientific run means:

* no prior proposal trajectory;
* no incumbent restoration;
* no previous interpretation history;
* no prior run-state reuse.

It does not mean:

* no access to shared hardware calibration;
* no access to runtime measurement infrastructure;
* no access to validated machine profiles.

---

## 7. Proposed architecture

### 7.1 Unified `RuntimeEstimator`

Introduce a shared runtime-estimation interface used by all runtime
consumers.

Conceptually:

```python
class RuntimeEstimator(Protocol):
    def estimate(
        self,
        request: RuntimeEstimateRequest,
    ) -> RuntimeEstimate:
        ...
```

The estimator should not be owned by the proposer, tuner, admission
controller, or watchdog.

It should be created through a shared factory and passed to all runtime
consumers.

### 7.2 Runtime request

A request should contain the information available at the current stage.

Conceptually:

```python
@dataclass(frozen=True)
class RuntimeEstimateRequest:
    phase: Literal["proposal", "trial", "formal"]
    operation: Literal["training", "inference", "combined"]

    model_identity: str | None
    model_family: str | None
    parameter_count: int | None
    model_features: Mapping[str, object]

    batch_size: int
    segment_length: int
    train_steps: int
    inference_batches: int

    dtype: str
    device: str
    workspace: Path | None

    executable_model_available: bool
    allow_live_probe: bool
```

The exact schema should be determined after auditing current typed
runtime-control inputs.

### 7.3 Runtime estimate

The response must contain more than one scalar.

Conceptually:

```python
@dataclass(frozen=True)
class RuntimeEstimate:
    expected_seconds: float | None
    lower_seconds: float | None
    upper_seconds: float | None

    training_seconds: float | None
    inference_seconds: float | None
    setup_seconds: float | None

    peak_vram_gb: float | None

    provenance: RuntimeEstimateProvenance
    calibration_id: str | None
    hardware_profile_id: str | None
    probe_id: str | None

    applicability: RuntimeApplicability
    confidence: Literal["low", "medium", "high"]

    advisory_eligible: bool
    blocking_eligible: bool
    formal_execution_eligible: bool

    warnings: tuple[str, ...]
```

Possible provenance values may include:

```text
static_prior
historical_prior
similarity_prior
live_probe
live_probe_calibrated
in_process_verification
complete_observation
```

The final vocabulary should remain small and semantically precise.

**[PARTIALLY EXISTS — reconcile, do not fork]**: the runtime-control
layer ALREADY defines a provenance vocabulary with the same authority
rule (`core/runtime_control/records.py:41-72`): `PredictionSource` with
prior values (`static_uncalibrated`, `legacy_calibration_prior`,
`historical_observation_prior`, `historical_orchestration`) explicitly
"never formal-eligible on their own", measurement-backed values
(`real_dataset_setup`, `real_training_verification`,
`real_inference_verification`, `measured_representative_scoring`,
`real_dataset_warmup`) as the ONLY formal-eligible set
(`MEASUREMENT_BACKED_SOURCES`), plus `bounded_negligible` and
`derived_total`, a `Confidence` literal, and a 3-class authority
classifier (`classify_prediction_source`, `total_assembly.py:162`).
Commit C3's mapping obligation: the §7.3 names above are presentation
aliases over this existing vocabulary (e.g. `static_prior` ↔
`static_uncalibrated`, `in_process_verification` ↔
`real_*_verification`); one vocabulary must remain canonical, and the
audit recommends the EXISTING records.py one, extended where §7.3 needs
distinctions it lacks (`live_probe` vs `live_probe_calibrated`,
`complete_observation`).

Final mapping table (presentation language → canonical code value;
C3 keeps exactly ONE canonical vocabulary):

| Design concept | Canonical current or extended code value |
| --- | --- |
| Static prior | `static_uncalibrated` |
| Historical prior | `historical_observation_prior` |
| Legacy calibration prior | `legacy_calibration_prior` |
| Real dataset warmup | `real_dataset_warmup` |
| Live probe | new canonical value ONLY if existing values cannot express it (decide at C3 after vocabulary reconciliation) |
| Calibrated live probe | new canonical value if necessary (same rule) |
| In-process training verification | `real_training_verification` |
| In-process inference verification | `real_inference_verification` |
| Complete observation | explicit canonical value if needed |

Field naming: prefer `formal_decision_eligible` /
`blocking_decision_eligible` over introducing a NEW field named
`formal_execution_eligible` — unless the audit confirms the existing
code's `formal_execution_eligible` usage (records.py §93) is documented
and unambiguous, in which case extend the existing name rather than
renaming it (decide at C3; do not carry two near-synonyms). The illegal
state `static prior + blocking authority` must be unrepresentable by
the typed model, not merely discouraged.

### 7.4 Decision policy

The estimator provides evidence. A separate policy determines what to do
with that evidence.

Conceptually:

```python
class RuntimeDecisionPolicy(Protocol):
    def decide(
        self,
        estimate: RuntimeEstimate,
        budget: RuntimeBudget,
        mode: RuntimeMode,
    ) -> RuntimeDecision:
        ...
```

Possible decisions:

```text
ADVISORY
REQUEST_PROBE
ALLOW
REJECT
ABORT
```

This separation prevents the estimator from silently embedding policy.

**Resolved decision-policy matrix** (operator, 2026-07-30 — the
authority rule of §6.4 made concrete; C4 implements this table, C8 wires
it to every consumer):

| Evidence source | Proposal stage | Trial admission | Formal admission | Watchdog |
| --- | --- | --- | --- | --- |
| Static prior | Advisory only | Cannot block | Cannot block | Never used |
| Historical prior only | Advisory or request probe | Cannot block alone | Cannot block alone | Never used alone |
| Live probe, contended | Request clean retry or conservative handling | Conditional | Cannot be sole formal blocker | Temporary conservative deadline only |
| Live probe, clean but not historically corrected | May block on measured OOM or measured hard cap | Conditional | Conditional with explicit uncertainty | May protect execution |
| Calibrated live probe | May support blocking | May block | May block | Yes |
| In-process verification | Not applicable before implementation | Record or adjust | May block | Yes |
| Complete observation | Future context and calibration input | Future context | Future context | Calibration update |

Resolved semantics:

* deterministic VRAM impossibility may block before execution;
* measured OOM may block;
* a measured bounded-probe wall-cap hit may block;
* historical evidence alone may not block a novel candidate;
* unsupported extrapolation may not block without a live probe;
* static prior may never be used to revise a formal proposal;
* contended evidence must not silently become clean calibration
  evidence.

Blocking authority is NEVER a caller-controlled free boolean:
eligibility must be DERIVED from canonical provenance and applicability
rules by the typed model (illegal states unrepresentable, §7.3).

---

## 8. Two-stage estimation

### 8.1 Stage A: proposal-time risk screening

At proposal time, executable code usually does not exist.

The system may use:

* estimated parameter count;
* model-family history;
* architectural features;
* workload metadata;
* hardware capacity;
* similar prior models.

The result must be treated as a prior.

Default policy:

```text
static or low-confidence proposal estimate
→ advisory only
```

The proposer may be told:

* the proposal appears resource-intensive;
* the estimate is low confidence;
* implementation will be followed by a bounded live probe;
* a smaller fallback may be useful.

The proposer must not be told that a particular parameter ceiling is a
validated requirement unless measured evidence supports it.

### 8.2 Stage B: post-implementation bounded probe

After implementation and before full trial execution, run a bounded probe
of the actual candidate.

The probe should measure:

* model construction;
* optional compilation;
* several warmup steps;
* several timed training steps;
* several timed inference batches;
* peak VRAM;
* data-loading overhead where relevant;
* hardware contention indicators.

The probe should be bounded by explicit limits:

```text
maximum wall time
maximum training steps
maximum inference batches
maximum VRAM
```

The measured values are then extrapolated to the configured workload.

### 8.3 Historical correction

The system may apply a correction factor derived from similar historical
runs.

The correction should be selected by explicit applicability rules, which
may include:

* hardware profile;
* software stack;
* model family;
* operation type;
* batch size range;
* segment-length range;
* parameter or compute range;
* dtype;
* probe schema version.

The estimate must state whether it is:

* interpolation;
* bounded extrapolation;
* unsupported extrapolation.

Unsupported extrapolation must reduce confidence and blocking authority.

### 8.4 Runtime verification

Where the existing design already performs in-subprocess runtime
verification, that measurement should supersede earlier estimates.

Evidence precedence should be:

```text
complete observation
> in-process verification
> calibrated live probe
> uncalibrated live probe
> historical or similarity prior
> static prior
```

A lower-ranked estimate must never overwrite a higher-ranked measurement.

---

## 9. Hardware and environment model

### 9.1 Hardware profile

Each execution environment should expose a structured hardware profile.

Possible fields:

```text
GPU model
GPU count
VRAM
compute capability
driver version
CUDA version
PyTorch version
supported dtypes
CPU model and count
system RAM
storage class
calibration schema version
```

The profile provides applicability context.

It does not directly predict runtime.

### 9.2 Live resource snapshot

Each live probe should record:

```text
GPU utilization
GPU memory use
SM and memory clocks
power state
active GPU processes
CPU load
RAM pressure
storage throughput or relevant I/O state
```

A measurement should be marked `contended` when foreign resource use
exceeds a defined threshold.

Contended measurements may still protect the active run conservatively,
but should not automatically update the clean historical calibration.

### 9.3 Cross-hardware reuse

Raw timing values should not be assumed transferable across hardware.

Generic reuse means:

* shared code;
* shared schemas;
* shared probe procedure;
* shared decision policy;
* shared validation rules.

It does not mean that an H100 timing profile is numerically valid for a
5090.

A future normalized hardware model may support transfer learning or
cross-device priors, but this is not required for the first correct
implementation.

---

## 10. Calibration registry

### 10.1 Purpose

The calibration registry stores validated historical relationships
between bounded probes and later execution.

It may contain:

* runtime observations;
* correction factors;
* uncertainty;
* applicability ranges;
* sample counts;
* recency;
* contention status;
* schema and software versions.

### 10.2 Storage — REQUIRED versioned registry (C5)

**[CONFIRMED CURRENT]**: the actual store today is a single
`~/.siderius/time_calibration_<gpu_slug>.json` per GPU with the
`SIDERIUS_CALIBRATION_DIR` override already implemented (§15.3). It is a
useful LEGACY SOURCE, not the final generic registry.

The complete architecture requires a versioned calibration schema with
these fields (or equivalent structured records):

```text
schema_version
calibration_id
content_hash
hardware_profile_id
software_stack_identity
device identity
dtype
operation type
model family or feature bucket
parameter/compute range
batch-size range
segment-length range
training observations
inference observations
setup observations
I/O observations where applicable
sample count
uncertainty/error distribution
recency
contention state
probe schema version
writer identity/version
```

Required behavior: atomic writes; corruption detection; explicit
compatibility checking; explicit drift/stale handling; content-addressed
or stable hashed identity; a READ-ONLY legacy adapter for the old
k-table; no silent numerical reuse across incompatible hardware; no
source-code patch for a new server. The registry must support the
existing `SIDERIUS_CALIBRATION_DIR` override or a documented compatible
replacement. Calibration files are never hand-edited during validation.

A possible layout (final layout decided at C5 after inspecting
repository conventions):

```text
~/.siderius/runtime_calibration/
    hardware_profiles/
    observations/
    models/
    registry.json
```

The active calibration identity and hash must be recorded in each formal
run.

### 10.3 Read and write policy

Potential consumers:

* runtime estimator;
* proposer advisory screen;
* tuner;
* trial admission;
* formal admission;
* watchdog;
* reporting.

Writers should be limited.

Only validated runtime observations should update calibration history.

Static predictions and LLM self-reported parameter counts must not update
measured calibration tables.

**Resolved update-eligibility policy** (operator, 2026-07-30 — baseline;
D4 thresholds resolved at the C7 gate, see §20-D4):

```text
clean live probe:
eligible according to probe policy

contended live probe:
not eligible for clean calibration update

in-process verified observation:
eligible if environment/applicability checks pass

complete execution:
eligible and highest-value observation

static prior:
never eligible

LLM parameter estimate:
never eligible

historical replay output:
never eligible by itself
```

Contention telemetry is recorded with every probe. Foreign contention is
distinguished from intended pairwise concurrency. A pairwise-concurrent
observation may update a concurrency-specific calibration bucket but
must not overwrite the idle bucket. Explicit concurrency identity
vocabulary:

```text
single_candidate_idle
pairwise_expected_peer
foreign_contended
unknown_contention
```

---

## 11. Proposal-context safety

### 11.1 Structured resource evidence

Resource evidence passed to an LLM should be explicitly qualified.

Example:

```text
Runtime estimate provenance: static_prior
Confidence: low
Budget ratio estimate: 8.12
Decision: advisory
Blocking eligible: no

This estimate has not been validated on the implemented model.
Do not infer a permanent parameter-count ceiling from it.
```

### 11.2 Persistence policy

Persistent proposer or interpreter context may include:

* actual measured runtime;
* calibrated estimates with applicability information;
* explicit timeout or OOM outcomes;
* tentative risk signals clearly marked as tentative.

It must not convert an uncalibrated warning into an unqualified standing
constraint.

### 11.3 Context contamination test

Tests must prove that an uncalibrated warning cannot produce a persistent
system-authored constraint such as:

```text
keep all future models below N parameters
```

The LLM may still independently propose a small model, but the system
must not present an uncalibrated estimate as authoritative evidence.

---

## 12. Formal-run invariants

Before any formal trajectory begins, validate:

```text
runtime estimator factory initialized
hardware profile resolved
calibration registry readable or explicitly absent
runtime decision policy resolved
proposer, tuner, admission, and watchdog use compatible estimator contracts
formal mode prohibits uncalibrated blocking decisions
runtime provenance will be persisted
```

The required invariant is not necessarily:

```text
every proposal must have a pre-existing calibrated estimate
```

A novel model may not have one.

The required invariant is:

```text
formal execution must have a valid path from low-confidence prior
to bounded live measurement before blocking runtime decisions
```

A formal launch must hard-fail before the first LLM call if the system is
configured such that:

* proposer pre-flight can block on static evidence;
* no bounded live probe exists;
* estimator provenance cannot be recorded;
* runtime consumers use incompatible estimation paths.

**Guard mechanism (operator revision, 2026-07-30): NO source-code
introspection.** The runtime-estimation policy is explicit and typed.
The formal configuration and run invariants record fields such as:

```text
runtime_estimation_schema_version
runtime_estimation_policy_version
estimator_factory_id
decision_policy_id
static_proposal_blocking = false
live_probe_required = true
training_inference_separation_required = true
contention_capture_required = true
```

At startup the guard CONSTRUCTS the real estimator and decision policy
and runs a deterministic behavioral self-test:

```text
static prior            → ADVISORY
measured OOM            → blocking-capable result
measured live probe     → decision follows configured budget policy
historical prior alone  → no formal blocking
```

The guard tests actual policy behavior, not function names or source
layout, and runs before: any LLM call; scientific workspace mutation;
proposal persistence; training; trajectory-state creation.

The run-invariants lock and manifests additionally record:

```text
hardware/environment profile identity
calibration registry identity/hash
probe policy version
contention policy version
proposal-time static-blocking policy
training/inference separation policy
concurrency regime
live-probe-required flag
legacy calibration adapter version, if used
```

Resume with an incompatible runtime-estimation policy must fail before
LLM calls, training, or trajectory-state mutation. Legacy workspaces
missing these fields must not silently become V19-treatment
workspaces.

---

## 13. Admission and watchdog policy

### 13.1 Trial admission and the candidate lifecycle

The current record-only trial admission policy may remain appropriate
while runtime observations are being collected.

The complete candidate lifecycle (authoritative ordering):

```text
proposal
→ implementation
→ static implementation validation
→ load the actual candidate
→ bounded live probe
→ runtime estimate
→ admission
→ trial execution
→ in-process verification
→ watchdog
→ complete observation
```

"Static implementation validation" = no-real-workload checks:
importability; interface/schema compliance; deterministic shape checks;
configuration validation; plugin registration/loading; no full training
or inference. **[CONFIRMED CURRENT — reconciliation required]**: the
existing validator runs dummy-tensor forward/backward and a gradient
check (`ValidatorOutput.instantiation_passed` /
`gradient_check_passed`) — synthetic-tensor, not real-workload; this is
compatible with "static validation" but MUST be documented at C6 so the
bounded live probe remains the FIRST authoritative runtime measurement
(dummy-tensor timings are never runtime evidence).

### 13.2 Formal admission

Formal admission may block when based on:

* calibrated live measurement;
* in-process verification;
* sufficiently applicable historical evidence;
* explicit confidence and safety factors.

### 13.3 Watchdog

The watchdog remains the final wall-time safety mechanism.

It should use the strongest available runtime evidence and preserve:

* estimate provenance;
* factor;
* floor;
* resulting deadline.

A watchdog kill is valid measured evidence and may be persisted.

---

## 14. Proposed migration strategy

### Phase 0: stop invalid authority — [x] C1 half done (2026-07-30: static time pre-flight is advisory-only; prompt-side labeling/persistence policy = C2, pending)

Immediately prevent `static_uncalibrated` proposal estimates from
triggering blocking revision in formal mode.

Such estimates become advisory.

Also prevent their rejection text from being persisted as unqualified
trajectory knowledge.

This phase is a safety correction, not the final architecture.

### Phase 1: define shared types and evidence hierarchy

Introduce:

* `RuntimeEstimateRequest`;
* `RuntimeEstimate`;
* provenance vocabulary;
* applicability vocabulary;
* decision-eligibility fields;
* evidence precedence rules.

Wrap existing runtime estimates without initially changing all
algorithms.

### Phase 2: introduce shared estimator factory

Create one estimator factory per run.

Pass estimator identity or estimator access consistently to:

* proposer pre-flight;
* tuner;
* runtime admission;
* watchdog;
* reporting.

Remove private runtime formulas where they duplicate shared behavior.

### Phase 3: bounded post-implementation probe

Make live probing an explicit production stage.

Reuse existing warmup and RT2 verification machinery where possible
rather than creating a parallel probe implementation.

### Phase 4: calibration registry integration

Adapt the existing per-GPU k-table and observation history to the shared
estimator interface.

Verify:

* current 5090 history;
* H100 history;
* training coverage;
* inference coverage;
* applicability and extrapolation.

### Phase 5: bootstrap and external usability

Provide a user-facing calibration command, for example:

```bash
python -m siderius.runtime.calibrate --device cuda:0
```

The final command and module location should follow repository
conventions.

The bootstrap should:

1. inspect the environment;
2. generate a hardware profile;
3. run bounded representative probes;
4. measure training and inference;
5. record VRAM;
6. validate outputs;
7. register the calibration;
8. run a consumer-parity self-test.

### Phase 6: remove legacy authority

After the new system is validated:

* remove or isolate the old static blocking path;
* retain static estimation only as a clearly marked prior;
* migrate documentation and launch invariants;
* preserve legacy artifact readers where required.

---

## 15. Required audits before implementation

**Status: COMPLETE (2026-07-30, read-only; evidence cited per row).**
Two findings discovered during this audit go beyond the incident
description in §4 and materially shape the commit ladder in §23:

* **F-1 (calibration loop dormant since ~2026-07-20) — split into two
  INDEPENDENT wiring defects (operator revision, 2026-07-30):**
  - **F-1a — data-path wiring defect**: the chain launch did not supply
    or resolve the dataset path needed by the warmup/probe path.
  - **F-1b — fresh-plugin probe capability defect**: the existing warmup
    machinery is keyed to registered model types
    (`wrapper.py:379`: "[warmup skipped] unknown model_type") and its
    ability to load a NEWLY IMPLEMENTED candidate plugin before trial
    execution is unverified. Fixing `data_dir` alone (F-1a) must NOT be
    mistaken for completing live-probe integration: the final probe
    must execute the ACTUAL newly implemented candidate, not a
    pre-existing registry model with a similar name.
  Original finding: The tuner-side
  TimeEval warmup path — the ONLY reader of the k-table and the ONLY
  trigger of the calibration write-back (write fires solely when
  `breakdown.source == "real_dataset_warmup"`,
  `ml_hyperparameter_tune_agent.py:3760-3794`) — requires a non-empty
  `data_dir` (`evaluate_time_skill/wrapper.py:308-309`: "[warmup
  skipped] no data_dir; falling back to static formula"). The V18r
  2026-07-24 launches and the V19 wave-1 launch both ran with `Data
  dir:` EMPTY (banner evidence in `v18r_arch_04_09_20260724_0757.log`
  and the wave-1 forensic logs). Consequence: since ~2026-07-20 (the
  k-table's last history entry) BOTH the calibrated read path and the
  calibration write-back have been inactive in chain launches — static
  estimates at every TimeEval site, with only RT2 in-subprocess
  verification (admission/watchdog) measured.
* **F-2 (template-mandated parameter ceiling).** The proposal template
  REQUIRES the proposer to author a parameter-count constraint:
  "expert_advice.constraints must include at least one VRAM limit and
  one parameter count limit"
  (`ml_model_proposal_agent.py:285,315-316`). Combined with pre-flight
  rejection text in revision prompts, the system structurally compels
  the "<400K" style standing constraint that §11 prohibits.

### 15.1 Current runtime-estimator inventory — [x] DONE

| Component | File/function | Inputs | Provenance | Consumer | Blocking? | Persisted? |
| --------- | ------------- | ------ | ---------- | -------- | --------- | ---------- |
| Proposer time pre-flight | `agent/utils/proposer_preflight.py::estimate_proposal_time` (called from `ml_model_proposal_agent.py` reject-revise loop, `_run_preflight_check`) | LLM `parameter_count_estimate`, batch, seg, synthesized trial sample set; **hardcodes** `ms_per_step=None, gpu_name=None, inference_ms_per_step=None` (lines 152-171) | static only (`num_params×seg×bs×3e-9` ms, floor 2 ms) | proposer revision loop | **YES** — reject-revise ×3 intra-attempt, then lowest-factor emitted with `PREFLIGHT_OVERBUDGET_EMITTED` memo | rejection blocks → revision prompts → committed proposal context |
**Audit correction (2026-07-30, C1 inspection):** NO proposer-side VRAM
gate exists. The earlier "Proposer VRAM pre-flight" row was wrong — the
`[Pre-flight 1/2]` VRAM line in the wave-1 log belongs to the
TUNER-side gate. All VRAM text in the proposal agent is prompt/context
only; the enforcing VRAM control is tuner-side `evaluate_vram_skill`.
The proposer pre-flight is time-only.

| Tuner TimeEval | `agent/skills/evaluate_time_skill/wrapper.py` | real-dataset warmup ms/step × k(gpu,model) when `data_dir`+CUDA+registry model+dataset size available; else static (stamped `static_uncalibrated`) | measured×k OR static | tuner round planning gate | gate-level (skill verdict) | `time_check.breakdown` in records |
| Training estimator | `agent/skills/training_skill/estimator.py::estimate_wall_time_seconds` | ms_per_step (None→static), num_params, workload | as supplied; RT1 rev 4 comment (lines 72-80): static = "PRELIMINARY RISK SCREEN only… no silent static fallback is permitted on formal paths"; cites 2026-07-23 22×-under incident | TimeEval + proposer preflight | via callers | breakdown |
| Inference estimator | `agent/skills/inference_skill/estimator.py` | inference_ms (None→params-scaled static), `inference_batch_for()` with **silent fallback 25** for unregistered types | static in both incident paths | same | via callers | breakdown |
| RT2 in-subprocess verification | `core/runtime_control/` (session, verifier, adaptive) via `core/sandbox_executor.py` | measured setup + first-production-steps training/inference | measured | admission (`decide_admission`), watchdog (`_watchdog_deadline_provider`) | admission: formal only (factor 2.0, budget); trial record-only; watchdog kill | runtime-observation sidecars |
| Watchdog deadline | `core/sandbox_executor.py::_watchdog_deadline_provider` | Σ predicted(measured) × watchdog factor (3.5), floor 120 | measured | process-group kill | yes | sidecar `watchdog_status` |

### 15.2 Probe inventory — [x] DONE

Existing measurement machinery the §8.2 bounded probe can reuse (no
parallel implementation needed):

* **TimeEval real-dataset warmup** (`wrapper.py:271-430`): builds a mini
  dataset, runs `n_warmup_batches=3` + `n_timed_batches=7` real steps on
  CUDA, median aggregation, fast-fail for hopeless configs, k-correction
  and calibration write-back downstream. Preconditions (all must hold —
  each currently unmet in chain launches per F-1): non-empty `data_dir`,
  CUDA, registered model_type, dataset ≥ required segs.
* **RT2 in-subprocess verification**: setup measurement + adaptive
  training/inference verification (the first production steps) — already
  the measured basis for admission/watchdog; not available pre-trial.
* **Inference per-file timing sidecars** (`configs/iter_*/inference_timing_*.json`)
  and `_aggregate_inference_file_timings` (wrapper:153-220).
* **Hardware snapshots**: O1a `HardwareContext` manifests per iteration.
* Gap vs §8.2: no pre-trial probe of the freshly implemented plugin (the
  warmup path exists but is keyed to registered model types and dormant
  without data_dir); no contention snapshot at probe time.

### 15.3 Calibration artifact audit — [x] DONE

| Property | Value |
|---|---|
| Location | `~/.siderius/time_calibration_nvidia_geforce_rtx_5090.json` (313 KB); env override `SIDERIUS_CALIBRATION_DIR` (unset) |
| Schema | `{gpu_name, k_values{model_type→k}, history[720]}`; entries carry seg/batch/steps/warmup-vs-actual ms + violation flag |
| Writer | tuner post-training ONLY, and only from `real_dataset_warmup` runs (`ml_hyperparameter_tune_agent.py:3760-3794`) — asymmetric EMA α_up 0.5 / α_down 0.1, k clipped [0.5, 5.0] |
| Readers | TimeEval warmup path (`lookup_k`); legacy-prior adapter `to_legacy_prior_entries` → observation store (`legacy_calibration_prior`, never formal-eligible alone) |
| Hardware key | per-GPU file (slug); **no cross-hardware transfer by design** — any H100 table lives on the H100 host and is numerically irrelevant to the 5090 |
| Coverage | training ms/step only (inference batch registry is a separate hard-coded table in `core/inference_defaults.py`, fallback 25); 200+ model types; parameter range implicit (V18-era small models — multi-million coverage is thin: relevant to §8.3 extrapolation labels) |
| Freshness | last entry 2026-07-20 → **dormant since** (F-1); no contention metadata; no schema version field |
| Uncertainty | none stored (k point estimates + history variance implicitly available) |

### 15.4 Consumer parity audit — [x] DONE

| Control | Provenance | Blocking? | Budget | Persistent consequence |
|---|---|---|---|---|
| Proposer time pre-flight | static, always (API cannot receive calibration) | YES | trial 20 min | rejection text → prompts → committed context |
| Tuner TimeEval | static in current launch posture (F-1); measured×k when warmup available | gate verdict | round budget | breakdown in records |
| Trial admission | measured (RT2) | no — record-only | — | observations |
| Formal admission | measured (RT2) | yes (factor 2.0) | 120 min | attempt consumed on measured evidence |
| Watchdog | measured × 3.5, floor 120 | yes (kill) | — | measured kill evidence |

Mismatch summary: the only uncalibrated control is the only pre-measurement
blocking control with persistent prompt-level consequences — the exact
inversion of §8.4's precedence rule. Units are compatible (seconds);
workload assumptions compatible (same sample-set synthesis); the parity
defect is provenance/authority, not units.

### 15.5 Prompt and persistence audit — [x] DONE

* Pre-flight rejection → `_build_preflight_rejection_block` → revision
  prompt (unlabeled as low-confidence) → surviving proposal's
  motivation/constraints → interpretation → accumulated context. This is
  the confirmed contamination path (wave-1 "<400K" evidence in the
  forensic snapshot).
* **F-2**: the proposal template independently REQUIRES a parameter-count
  constraint in `expert_advice.constraints` — even absent rejections,
  the system compels a ceiling; with rejections, the ceiling gets the
  uncalibrated number.
* `PREFLIGHT_OVERBUDGET_EMITTED` memo note (agent:1310-1315) persists
  factor values into `memo_consistency_notes`.
* DiscoveryMemo (lit-review) framing is derived from advice + registry —
  no direct runtime feedback path found there.
* Provenance/confidence preserved: NOWHERE on this path today.

### 15.6 Historical audit — [x] DONE (bounded sample)

* V19 wave 1 (forensic snapshot): 2 rejections (84.64×, 8.12×) + 1
  exhaustion-acceptance at 1.46×; proposed 18.4M → 1.76M → 312K est;
  realized 42,064 (7.4× below even the accepted estimate — §16.7
  confirmed live); "<400K" persisted. Loss chain: realized 83,424.
* V18r sampled chains: `v18r_arch_04_09` — 16 rejections (factors 1.07-12.64×),
  85 `static_uncalibrated` records; `v18r_arch_10_14` — 8 rejections
  (1.34-12.83×), 33 records. Same mechanism, entire campaign.
* Directional correctness of the static verdicts: UNVERIFIED either way —
  replay against calibrated/measured evidence is the purpose of §17.10;
  do not assume the large proposals would have passed.
* Remaining [ ] (optional, non-blocking): full-campaign quantification
  across all V18r chains (initial-vs-realized parameter counts per
  iteration). Bounded sample above is sufficient to justify the design.

---

## 16. Potential risks and unresolved problems

### 16.1 Probe overhead

A live probe consumes time and GPU resources.

Mitigations:

* strict probe caps;
* reuse probe work for the actual trial;
* cache valid probe results;
* avoid repeated probing of identical implementations.

### 16.2 Probe representativeness

A short probe may not capture:

* compilation stabilization;
* long-run throttling;
* file transitions;
* I/O;
* validation;
* memory fragmentation.

Mitigations:

* historical correction;
* uncertainty bounds;
* fixed overhead terms;
* in-process verification;
* watchdog.

### 16.3 Novel architecture extrapolation

A new model family may lack relevant historical calibration.

The system must not pretend that a nearby model is equivalent.

Possible behavior:

```text
low-confidence prior
→ bounded live probe
→ conservative uncertainty
```

### 16.4 Dynamic contention

Current contention may make the probe slower than a clean run.

The system must decide whether to:

* wait;
* proceed conservatively;
* mark the observation contended;
* exclude it from long-term calibration.

This policy needs explicit thresholds.

### 16.5 I/O-dominated workloads

Some workloads may be dominated by storage rather than GPU compute.

The estimator must avoid assuming that runtime scales primarily with
parameter count or GPU throughput.

### 16.6 Training and inference asymmetry — ELEVATED TO REQUIREMENT

Training and inference must be measured separately, with SEPARATE APIs
and evidence records for:

```text
training milliseconds per step
inference milliseconds per batch or segment
setup/compile time
per-file or file-transition overhead
peak VRAM
```

A model may have:

* inexpensive training but expensive full-scope inference;
* expensive training but efficient inference;
* architecture-specific inference overhead.

A single `ms_per_step` value is insufficient.

Inference work units must be explicit and convertible:
`batch` (inference_batch segments per forward), `segment` (one PSD
segment), `file` (all segments of one data file), `full-scope
evaluation` (all in-scope files × eval portion). Conversions:
`segments_per_file × n_files × eval_portion = total_segments`;
`ceil(total_segments / inference_batch) = batches`. The estimator must
state which unit a measured rate is in and convert explicitly — never
mix units silently.

The hard-coded inference batch registry (`core/inference_defaults.py`)
is NOT a measured inference calibration. The silent fallback value `25`
must either be removed from formal paths or represented only as a
low-confidence prior with no blocking authority (C6/C8).

### 16.7 Parameter-count reliability — ELEVATED TO REQUIREMENT

Proposal-stage parameter count is LLM-authored and may differ
substantially from the implemented model.
**[CONFIRMED CURRENT]**: wave-1 arch claimed 312K, realized 42,064
(7.4× off).

The system must recompute after implementation:

```text
realized parameter count
trainable parameter count
dtype-adjusted parameter memory
estimated activation footprint where possible
```

Realized values supersede proposal self-reports in: probe requests;
runtime estimates; VRAM checks; admission; artifacts; future
proposer/interpreter context; calibration records. The proposal
estimate is retained only as provenance for comparing planned versus
realized implementation.

### 16.8 Calibration drift

Calibration can become stale after changes to:

* CUDA;
* PyTorch;
* driver;
* dtype;
* kernels;
* model implementation;
* storage;
* workload.

The registry needs explicit invalidation or compatibility rules.

### 16.9 Concurrent chains

When two chains share a GPU, live probes may interfere.

The system must define whether probing occurs:

* serially;
* under the actual intended concurrency;
* with contention explicitly modeled.

A measurement collected under one concurrency regime should not silently
be applied to another.

### 16.10 Excessive conservatism

Large safety factors can recreate the same small-model pressure even
with measured estimates.

Safety factors must be visible, tested, and justified separately from
the underlying estimate.

---

## 17. Testing strategy

### 17.1 Static authority guard

Test:

```text
formal mode
+ static_prior estimate
→ cannot produce blocking rejection
```

### 17.2 Context contamination guard

Test that low-confidence runtime warnings:

* remain labeled;
* do not become system-authored hard parameter ceilings;
* are not restored as measured facts.

### 17.3 Live-probe propagation

Using a deterministic fake probe, prove:

```text
measured training speed
+ measured inference speed
→ shared RuntimeEstimate
→ admission
→ watchdog
→ manifest and runtime observation
```

### 17.4 Consumer parity

Assert proposer, tuner, admission, and watchdog receive:

* the same estimator identity;
* compatible workload definitions;
* the same calibration identity where applicable;
* the same provenance vocabulary.

### 17.5 Hardware portability

Test at least two synthetic hardware profiles.

The source-code path must be identical.

Only the runtime profile and observations may differ.

### 17.6 Contention handling

Test:

* clean probe;
* foreign GPU process;
* high memory pressure;
* reduced clock;
* missing telemetry.

Verify appropriate provenance and calibration-write policy.

### 17.7 Training/inference separation

Use different sentinel values for:

* train ms/step;
* inference ms/batch;
* setup time.

Prove they remain separate through total-time estimation.

### 17.8 Calibration range

Test:

* interpolation;
* supported extrapolation;
* unsupported extrapolation;
* stale schema;
* incompatible software stack.

### 17.9 Resume invariants

Resume should preserve runtime-estimation policy identity.

A change in blocking policy, provenance requirements, or estimator schema
should be handled explicitly.

### 17.10 Historical replay — TWO DISTINCT MODES (operator revision)

Replay preserved proposals from the stopped V19 attempt (~18.4M,
~1.76M, the accepted small proposal, relevant loss-chain proposals).

**Metadata replay** (no GPU): uses preserved proposal metadata and
historical records; may compare legacy static estimate, historical
prior, applicability labels, estimated workload. It must NOT claim
ground-truth runtime.

**Executable replay** (bounded GPU, operator-gated): requires an actual
loadable candidate implementation; may run a bounded live probe, a
calibrated estimate, and a bounded actual segment. ONLY executable
replay may validate the runtime of a specific candidate.

**[CONFIRMED CURRENT]**: the preserved 18.4M and 1.76M proposals were
REJECTED DRAFTS — no implementation was ever generated for them, so
they are metadata-replay-only unless equivalent models are implemented
for the §25 campaign. Any report must say this explicitly; a no-GPU
metadata replay must never be presented as empirical runtime
validation.

---

## 18. Acceptance criteria (revised — restart-blocking, operator 2026-07-30)

V19 is not restart-ready until ALL conditions below are true.

1. Static proposal estimates cannot block in formal mode.
2. Historical prior alone cannot block a novel candidate.
3. Prompt/runtime warnings preserve provenance and confidence.
4. The proposal template does not mandate a parameter-count ceiling.
5. Actual newly implemented candidates pass through a bounded live probe.
6. Training and inference are measured separately.
7. Setup and fixed overheads are represented.
8. Realized parameter count supersedes the LLM estimate.
9. A unified estimator factory is used by every runtime consumer.
10. A shared decision policy controls all blocking authority.
11. The canonical provenance vocabulary is singular and typed.
12. Illegal static-plus-blocking states are unrepresentable.
13. The calibration registry is versioned and hardware/environment-aware.
14. Calibration compatibility, drift, and uncertainty are explicit.
15. Contention is measured and persisted.
16. Foreign contention cannot pollute clean calibration.
17. Intended pairwise concurrency is validated and represented.
18. The user-facing bootstrap/calibration workflow works on a fresh
    environment.
19. Legacy k-table artifacts migrate or adapt safely.
20. Formal launch self-tests actual policy behavior.
21. Runtime-estimation policy is locked in run invariants.
22. Resume with incompatible policy fails before LLM/training.
23. Real-GPU validation passes pre-registered thresholds.
24. No systematic model-size suppression remains.
25. No architecture-family-specific underprediction remains unaddressed.
26. Formal queue-runner hardening is complete.
27. Operator stop terminates the full chain loop.
28. Stopped-wave relics are cleaned without damaging forensics.
29. Fresh workspaces contain no contaminated context.
30. Full CI is green on the exact restart head.
31. A cold-start production smoke passes.
32. An explicit V19 restart report is reviewed.
33. The operator explicitly authorizes V19 restart.

---

## 19. V19 recovery plan

The stopped wave remains classified as:

```text
STOPPED — INVALID UNCALIBRATED PREFLIGHT STATE
```

Its forensic snapshot must remain read-only.

Before restart (aligned with the RESOLVED §21 requirement — the
complete architecture, not a minimum scope):

1. finish the audits in this document — [x] done (§15);
2. implement and validate the full C1-C14 ladder (§23);
3. validate the existing 5090 observation history via the C5 legacy
   adapter and C7 applicability labels;
4. run the §24 campaign under pre-registered thresholds (C12);
5. replay the rejected proposals (metadata mode; executable mode only
   for loadable candidates — §17.10);
6. remove the verified incomplete active-run relics (C13, §26);
7. create fresh workspaces;
8. run the Layer-2 zero-LLM production-path validation and the Layer-4
   cold-start smoke;
9. obtain CI green on the exact restart head;
10. present the Layer-5 stop-and-show restart report against all 33
    §18 criteria;
11. receive explicit operator authorization.

No trajectory state, proposals, interpretations, incumbents, or plugin
state from the stopped attempt may enter the restarted run.

---

## 20. Open decisions

The following decisions require explicit resolution before implementation.

### D1. Minimum scope for V19 restart — RESOLVED (operator, 2026-07-30)

V19 must not restart until the complete generic runtime-estimation
architecture defined in this document is implemented and validated.

The required scope includes:

- canonical runtime-evidence and provenance types;
- a unified `RuntimeEstimator` interface and production factory;
- a shared `RuntimeDecisionPolicy`;
- proposal-time advisory-only handling for static estimates;
- removal of prompt contamination and template-mandated parameter
  ceilings;
- mandatory post-implementation bounded live probing;
- separate training and inference measurement paths;
- realized parameter-count recomputation;
- hardware and environment profiling;
- live contention capture;
- a versioned calibration registry;
- uncertainty and applicability handling;
- calibration drift and compatibility handling;
- shared estimator consumption by proposer, tuner, admission, watchdog,
  and reporting;
- formal launch invariants and run-invariant locking;
- a user-facing calibration/bootstrap workflow;
- legacy calibration migration support;
- multi-family and multi-scale real-GPU validation;
- pairwise-concurrency validation;
- formal queue-runner hardening;
- fresh-workspace cleanup and restart validation.

Phase 0-only, C1-C5-only, or any other partial implementation is not
sufficient for V19 restart.

### D2. Proposal-time policy — RESOLVED (operator, 2026-07-30)

```text
Static prior:
advisory only

Historical prior alone:
advisory or request probe; never sole formal blocker

Deterministic VRAM impossibility:
may block

Measured probe OOM:
may block

Measured probe wall-cap hit:
may block with persisted measured provenance

Calibrated clean live probe:
may block according to policy

Unsupported extrapolation:
must request a live probe; may not block alone
```

**Placement clarification (operator, 2026-07-30):** "deterministic VRAM
impossibility may block" remains an approved POLICY principle, and its
production placement is now decided: **VRAM authority begins only after
implementation** — using (1) realized model properties, (2)
deterministic memory accounting where reliable, (3) bounded live
peak-memory measurement. There is NO proposer-side VRAM gate:
proposal-authored parameter counts or architecture descriptions may be
shown as non-authoritative context only and must not trigger
reject-revise behavior. The shared `RuntimeDecisionPolicy` (C4/C8) may
block on: deterministic post-implementation capacity impossibility;
measured probe OOM; measured peak VRAM exceeding the configured
budget.

### D3. Contention threshold — RESOLVED (operator, 2026-07-30)

Contention is classified from **pre-probe external state and process
identity**, never from the probe's own utilization:

```text
known foreign GPU process present                       → foreign_contended
pre-probe external GPU memory > max(1 GiB, 10% of VRAM)  → foreign_contended
pre-probe sustained GPU utilization >= 20% for >= 10 s   → foreign_contended
telemetry unavailable OR unexplained clock/power throttling → unknown_contention
only the current probe process                          → single_candidate_idle
only the current probe + the explicitly registered peer  → pairwise_expected_peer
```

Self PID **and** child PIDs are excluded. An intended peer must be
identified **explicitly** (registered PID), never inferred from a
process name. Classification uses a **bounded sampling window**, not one
instantaneous `nvidia-smi` sample. **All raw telemetry used for the
classification is recorded.** These thresholds are **policy-versioned**
(`calibration_policy@<semver>+<config-hash>`) and may change only
through an explicit design update.

Implementation: `core/runtime_control/calibration_policy.py`
(`CalibrationPolicy`, `classify_contention_window`,
`sample_contention_window`) — see the §23-C7 record for the two derived
implementation decisions (throttle-bit mask; unidentified foreign
counts).

### D4. Calibration update policy — RESOLVED (operator, 2026-07-30)

Two-stage lifecycle: **candidate observation → validated observation →
calibration-eligible**. Every measured observation is persisted as an
immutable candidate when schema and content validation pass; it becomes
calibration-authoritative only when provenance is measurement-backed, no
foreign contention is present, hardware/environment compatibility
passes, units and workload metadata are complete, the record hash and
schema validate, it belongs to the correct concurrency bucket, no
unsupported extrapolation is being treated as observation, and the
required later comparison evidence exists.

```text
1 clean observation                            → persisted candidate only
2 mutually consistent clean observations       → provisional calibration
>= 3 consistent, no drift violation            → validated calibration
consistency criterion: max rate / min rate <= 1.5 within one bucket
```

Setup, training, inference, I/O, idle and pairwise-concurrency buckets
stay separate. Measured OOM, wall-cap hits and abnormal termination are
valuable **failure evidence** but must never update throughput
calibration. In-process verification and complete execution may validate
an earlier probe only when their operation/workload units are
comparable. All promotions are deterministic, versioned, and recorded as
**new derived records** — an observation is never mutated in place.

Implementation: `CalibrationPromotion` (`registry_schemas.py`),
`evaluate_bucket` / `validate_against_verification` /
`evaluate_promotions` / `detect_drift` (`calibration_policy.py`),
`record_promotion` / `bucket_status` (`calibration_registry.py`).

### D5. Unknown model families — RESOLVED (operator, 2026-07-30)

An unknown family must **not** prevent the bounded live probe:

```text
proposal stage       → static/historical evidence is advisory only
post-implementation  → run the generic bounded live probe on the actual candidate
after measurement    → classify into an existing family ONLY when supported by
                       explicit implementation metadata or deterministic
                       structural features
otherwise            → model_family = "unknown" (or a generic feature bucket)
```

The candidate is never forced into the nearest known family, and an
unknown candidate never receives historical-family calibration authority
before local measurement. A dedicated family-identification probe is
deferred as an optimization — not required for the V19 restart.

Implementation: `classify_model_family` + family-keyed buckets
(`calibration_policy.py`), `CalibrationObservation.model_family`,
`probe_observations(..., model_family=...)`.

### D6. Probe reuse — RESOLVED (operator, 2026-07-30)

For the first implementation:

```text
probe work is not counted as trial work
```

This keeps the scientific semantics and accounting simple. Probe reuse
may be considered later as an optimization after the estimator is
validated.

### D7. Formal launch invariant — RESOLVED (operator, 2026-07-30)

```text
A pre-existing historical calibration is not mandatory for a novel
candidate.

A validated live-probe path is mandatory.

No blocking decision may rely solely on uncalibrated or historical-prior
evidence.
```

### D8. Concurrency calibration — RESOLVED (operator, 2026-07-30)

V19 restart requires both idle and pairwise-concurrent runtime
validation.

The estimator must distinguish intrinsic single-candidate cost from
concurrency overhead.

The initial strategy is:

1. measure each candidate under a controlled idle probe;
2. run a bounded pairwise-concurrent verification;
3. compute or record a contention multiplier or concurrency observation;
4. use concurrency-aware evidence for admission and watchdog decisions;
5. persist the concurrency regime in every estimate and calibration
   record.

An estimate collected under one concurrency regime must not silently be
used as if it represented another.

Concurrency-model requirements: live-probe scheduling (serial vs
concurrent) is defined per stage in §23-C6/C12; admission evaluates
individual budgets with the aggregate regime recorded (aggregate-budget
policy is validated in C12); watchdog deadlines use evidence from the
matching concurrency regime; foreign contention is distinguished from
the intended peer chain via the §21-policy concurrency identity
vocabulary. Suggested initial model: idle intrinsic estimate × measured
pairwise contention multiplier — NOT assumed constant across families or
sizes without §25-campaign validation.

---

## 21. Resolved restart requirement (operator, 2026-07-30)

The complete generic runtime-estimation architecture is a mandatory
prerequisite for V19 restart.

No intermediate commit, migration phase, safety fix, or local validation
independently authorizes restart.

Restart authorization requires every acceptance criterion in this
document to pass, followed by an explicit operator review and approval.

The stopped V19 wave remains `STOPPED — INVALID UNCALIBRATED PREFLIGHT
STATE`; its forensic snapshot remains read-only; no intermediate phase,
passing suite, or commit authorizes restart.

---

## 22. Design invariant

The central invariant of this design is:

> Before implementation, runtime estimates are priors.
> After implementation, runtime decisions are measurements.

Any implementation that allows a static proposal prior to override an
available or obtainable live measurement violates this design.

---

## 23. Implementation plan — full commit ladder (C1-C14, operator-resolved scope)

Standard per stage: Goal / Scope & dependencies / Implementation plan /
Unit validation / Pseudo integration / Real-GPU validation (where
applicable) / Acceptance criteria / Failure & edge cases / Migration &
rollback / Commit boundary. `[ ]` = not done; `[x]` only with recorded
evidence. Inspect before modifying; STOP AND ASK on ambiguity;
stop-and-show before every commit; no stage bundles unrelated
scientific-policy changes; no real LLM/training without operator
approval; **no V19 restart at any intermediate stage** (§21).

Exact commit counts may split at clean boundaries per the repository
split-commit rule; every responsibility below keeps an explicit owner.

### C1 — `fix(runtime): stop static proposal-time blocking authority`

**Goal.** Remove the incident's direct cause (§8.1 default policy):
static time estimates lose reject-revise authority. The tuner-side VRAM
gate is out of scope and remains unchanged; NO proposer-side VRAM gate
exists or is added (operator decisions, 2026-07-30).
**Scope/deps.** `agent/utils/proposer_preflight.py` (provenance +
eligibility in the result), `nodes/ml_model_proposal_agent/ml_model_proposal_agent.py`
(both reject-revise sites; time rejection → advisory; VRAM check
unchanged), node `.md` sync. No estimator-math changes; tuner/RT paths
untouched. Deps: none.
**INTERIM-API NOTE (binding).** The `blocking_eligible`-style field
added here is a TEMPORARY BRIDGE only: callers must not freely set it;
C3/C4 replace dictionary authority with canonical typed provenance and
policy-derived decisions (`decision = runtime_decision_policy.decide(...)`,
never `if result["blocking_eligible"]`). C1 tests must not normalize
free-setting of blocking authority as a permanent API.
**Implementation plan.**
- [ ] Inspect both pre-flight loop sites + `_run_preflight_check` and
      every consumer of `preflight_factor`/`preflight_estimated_minutes`.
- [ ] Result gains `provenance="static_uncalibrated"` +
      derived (not caller-set) advisory-only eligibility.
- [ ] Time factor > 1 → structured advisory (§11.1 wording), no
      revision request, no rejection block in prompts.
- [ ] Both time-based reject-revise loops (legacy `_run_legacy` +
      pipeline `_run_pipeline` outer loop) collapse to a single
      proposal pass for time-preflight purposes; structural/schema
      retries unchanged.
- [ ] Preserve observability (factor/minutes recorded on output).
- [ ] Retire or re-scope `PREFLIGHT_OVERBUDGET_EMITTED`.
- [ ] Doc sync.
**Unit validation.** Over-budget static verdict → exactly one proposing
call, advisory recorded, prompt free of rejection text (both paths);
eligibility cannot be interpreted as blocking from static provenance;
params ≤ 0 / budget None → gate skipped, no crash; tuner VRAM suites
untouched and green (no production diff in that subsystem); regression
test demonstrably fails on the pre-C1 blocking behavior.
**Pseudo integration.** Existing proposer pseudo suites unchanged.
**Acceptance.** (a) 84.64×-class draft yields 1 proposing LLM call +
labeled advisory + no revision + no PREFLIGHT_OVERBUDGET_EMITTED, on
BOTH the pipeline and legacy paths; (b) zero unlabeled rejection text
in rendered prompts (asserted in tests); (c) all proposer suites green;
(d) tuner VRAM subsystem has zero diff.
**Failure/edge.** factor==1.0; estimate exceptions; missing budget;
legacy dict-key readers (keys unchanged).
**Migration/rollback.** Pure behavior flag at the agent policy level;
revert = restore reject-revise branch. No artifact-format changes.
**Boundary.** One behavior + tests + doc sync.
- [ ] Evidence recorded (commands, counts, wall time).

### C2 — `fix(proposal): remove prompt contamination and template-mandated parameter ceilings`

**Goal.** Close the §11/§15.5 contamination vectors incl. F-2.
**Scope/deps.** Proposal template blocks (`ml_model_proposal_agent.py`
~285/315-316), advisory renderer (C1), interpreter-side carry path
(inspect first). Formal advice files untouched; the LLM may still
voluntarily propose small models (§11.3). Deps: C1.
**Implementation plan.**
- [x] Template contract inspected: the mandate existed in FOUR spots
      (`ml_model_proposal_agent.py` legacy commit prompt, example +
      hard-constraints bullet; `agent/prompt_templates/proposal/
      proposing_stage.md`, example + rule 5). Enforcement audit: only
      non-emptiness is validated
      (`execute_tools/workflow_validation.py:107`);
      `ExpertAdvice.constraints` has no content validation; the
      validator agent only serializes advice as prompt guidance. The
      STOP-AND-ASK condition did NOT materialize → removal proceeded
      autonomously. All four spots now require a VRAM limit only, with
      capacity constraints permitted "ONLY when justified by measured
      evidence or explicit capacity arithmetic".
- [x] §11.1 advisory labeling: SUPERSEDED in prompt form by the C1
      operator decision (advisory stays artifact-only; the static
      estimate is NOT reintroduced into prompts). The persisted
      advisory note carries the §11.1 labels (done in C1).
- [x] Persistence audit: repo-wide sweep shows `memo_consistency_notes`
      has NO downstream prompt consumer — the C1 advisory cannot leak
      into future prompts via any existing path.
- [x] Additional contamination surfaces found and fixed: the
      gate-exhaustion closing's unqualified "reduce parameter count"
      order → provenance-qualified, workload-first, explicit
      no-permanent-ceiling (multi-entry family-switch retained); the
      stale `<10 GB VRAM` literal (real budget 16 GB — VRAM-side
      small-model pressure) → defers to the `[HARDWARE CONTEXT]`
      effective cap; the exploit-template "reduce parameter count
      first" trade-off → workload-first per the operator's RESOURCE
      USE advice clause.
- [x] Doc sync + fixture updates (PR3 flag-OFF parity golden
      regenerated from the same fixture; `[HEALTHGATE EVIDENCE]`
      absence re-asserted post-regeneration).
**Unit validation.** Rendered prompts: ceiling-mandate absent through
the REAL loader in both explore/exploit modes; VRAM bullet retained;
justification language present; qualified exhaustion closing;
ProposalOutput schema unchanged.
**Pseudo integration.** §17.2 contamination guard operates on real
templates/loader/renderer output.
**Acceptance.** (a) no template-mandated parameter ceiling (VRAM bullet
retained) — MET; (b) prompt-side runtime numbers: the only remaining
runtime-number prompt path is the gate-exhaustion block, now
provenance-qualified; the static advisory never enters prompts
(operator decision) — MET; (c) guard evidence recorded — MET.
**Failure/edge.** Restored legacy contexts already containing ceilings
(out of scope — fresh workspaces only); legacy fixtures updated.
**Migration/rollback.** Template-text change; revert restores old text.
**Boundary.** Prompt/persistence only.
- [x] Evidence recorded (commit `a5a2d9d`):
      `test_prompt_ceiling_policy.py` — 8 guards (mandate-free
      templates via real loader both modes, justification language,
      qualified closing, family-switch retention, stale-literal
      removal); proposer dir **524 passed, 1.5 s**; golden parity
      suite 3 passed post-regeneration; targeted ruff check + format
      clean. One test-side fix during development: exact-substring
      assert failed on line-wrapped text → whitespace-normalized
      (test bug; production wording correct).

#### Implementation record — 2026-07-30 / C2 (commit `a5a2d9d`)

**Question encountered.** (a) Is the template mandate schema-validated
anywhere? (b) The PR3 flag-OFF parity golden byte-pins the full
reasoning prompt, embedding the exhaustion closing being reworded —
regenerate or preserve? (c) Are the exhaustion closing's shrink order
and the exploit-template capacity-first trade-off within C2 scope?

**Audit evidence.**
- `execute_tools/workflow_validation.py:107` — non-emptiness only;
  `agent/schemas/proposal.py::ExpertAdvice.constraints` — free list;
  validator agent — guidance-only consumer.
- `test_health_prompt_parity.py` — golden exists to prove PR3 flag-OFF
  byte-parity, not to freeze exhaustion wording.
- Repo-wide `memo_consistency_notes` sweep — no prompt re-render path.
- Gate-exhaustion TIME factors originate from pre-attempt gates that
  may be `static_uncalibrated` (F-1) — an unqualified shrink order
  from that data is exactly the §11 hazard.

**Decision.** Remove the mandate (VRAM requirement + justification
qualifier); regenerate the golden from the same fixture; reword the
exhaustion single-entry closing; fix the `<10 GB` literal; reorder the
exploit trade-off to workload-first.

**Rationale.** Prompt-text-only, reversible, within C2's
anti-contamination mandate; aligns templates with the operator's own
V18r RESOURCE USE advice; no scientific setting, advice file, tuner,
or authority change.

**Validation.** As recorded above (524 proposer tests; 8 new guards;
golden parity re-proven).

**Status.** Final.

#### Implementation record — 2026-07-30 / commit-discipline interpretation

The autonomous-execution protocol §7 ("commits do not individually
require approval; do not artificially stop after every small commit")
conflicts with the appended legacy rule 3 ("stop before each full
commit"). Interpretation adopted and disclosed in-session: §7 governs;
reports at stage boundaries and mandatory gates. Reversible at any
operator instruction. Status: Final unless operator overrides.

### C3 — `feat(runtime): canonical runtime evidence/provenance types`

**Goal.** §7.2/§7.3: one typed evidence model wrapping existing
producers; single canonical vocabulary (reconciled with `records.py`,
mapping table in §7.3 — no parallel enum); eligibility DERIVED from
provenance/applicability; illegal static+blocking unrepresentable.
**Scope/deps.** New `core/runtime_control/estimate_types.py` (Pydantic);
adapters for: proposer preflight, TimeEval breakdown, RT2 verification,
observations, k-corrected warmup; reconcile `PredictionSource` /
`MEASUREMENT_BACKED_SOURCES` / `Confidence` /
`classify_prediction_source` (extend, never fork; resolve the
`formal_execution_eligible` vs `formal_decision_eligible` naming per
§7.3 rule). No consumer decision-path switches yet. Deps: none (may
land parallel to C1/C2).
**Implementation plan.**
- [x] Vocabulary reconciliation audit: `records.PredictionSource` is
      canonical, EXTENDED with three additive values
      (`bounded_live_probe`, `bounded_live_probe_calibrated`,
      `complete_observation`), all classified MEASUREMENT_BACKED; the
      existing `RuntimePrediction` admission invariant governs them
      unchanged (probe without verification+steady state can never be
      formal-eligible — test-proven). NAMING RESOLVED per the §7.3
      rule: `formal_execution_eligible` KEPT (records.py usage is
      documented and schema-enforced); no `formal_decision_eligible`
      synonym introduced. `HISTORICAL_EVIDENCE_SOURCES` unchanged.
- [x] `core/runtime_control/estimate_types.py`: `RuntimeEstimateRequest`
      + `RuntimeEstimate` (frozen Pydantic; separate
      training/inference/setup seconds per §16.6; applicability +
      concurrency-identity vocabularies; warnings). Eligibility is
      DERIVED (`derive_decision_eligibility`): priors advisory-only;
      measurement-backed blocks unless contended; formal additionally
      requires verification+steady state. Validator makes
      static/historical + blocking/formal UNREPRESENTABLE;
      `make_estimate` is the sole supported construction path.
- [x] `evidence_rank()` — §8.4 six-tier total order covering EXACTLY
      the canonical Literal (set-equality test).
- [x] Four read-only adapters: proposer pre-flight (real C1 verdict),
      TimeEval result (REAL wrapper result shape, `wrapper.py:812-824`
      — corrected from an initially guessed shape during
      implementation), RT2 observation record (REAL wave-1 forensic
      sidecars as committed fixtures), legacy k-table entry.
- [x] Doc sync (this section).
**Unit validation.** every provenance value; derivation rules;
precedence order + idempotence; adapter round-trips on forensic
fixtures; unknown provenance rejected.
**Pseudo integration.** none required (no consumer switch).
**Acceptance.** (a) all adapters validate on real fixtures; (b) illegal
state unrepresentable (constructor test); (c) precedence proven; (d)
zero production call-site changes in diff.
**Failure/edge.** legacy sidecars missing fields → conservative
low-confidence, never raise on optional absence; malformed → named
error.
**Migration/rollback.** Additive module; no consumers changed.
**Boundary.** Types + adapters + tests.
- [x] Evidence recorded: `tests/unit/core/test_estimate_types.py` —
      **20 tests** (vocabulary/tier set-equality, six-tier order,
      priors-never-block sweep over the full Literal, unrepresentable
      illegal states, contended-probe demotion, bounds ordering,
      adapters on real artifacts incl. both forensic sidecars);
      adjacent runtime-control suites
      (test_runtime_control_model/test_total_assembly/
      test_watchdog_admission_split) — combined **70 passed, 1.2 s**;
      ruff check + format clean.

#### Implementation record — 2026-07-30 / C3

**Question encountered.** (a) Extend `formal_execution_eligible` or
introduce `formal_decision_eligible`? (b) Are the three new sources
measurement-backed (formal-eligibility-capable)? (c) The wave-1 TRIAL
forensic record has `components.inference.prediction = None` — how does
the observation adapter represent an absent prediction?

**Audit evidence.**
- `records.py:88-101` — `formal_execution_eligible` carries a
  documented, schema-enforced admission invariant → the §7.3 rule's
  "documented and unambiguous" branch applies: KEEP the name.
- `records.py` prior/measurement split + §8.2/§8.4 — a bounded live
  probe IS a live measurement of the actual configuration →
  measurement-backed; the unchanged admission invariant still denies
  formal eligibility without verification+steady state, and the
  §7.4 matrix's contended-probe demotion is enforced at the envelope.
- `provenance.py` module contract — "a provenance gap is recorded as a
  gap, never fabricated": my first adapter draft defaulted a missing
  prediction to static provenance — a fabrication; corrected.
- Wave-1 trial sidecar (fixture) — inference prediction absent by
  design (adaptive inference verification had not formed one).

**Decision.** Keep `formal_execution_eligible`; classify the three new
sources measurement-backed; observation adapter EXCLUDES unpriced
components from the total, takes the weakest source over PRICED
components only, and emits an explicit "expected_seconds does NOT
cover it" warning per gap.

**Rationale.** One canonical vocabulary, no synonym drift; provenance
honesty over completeness; the existing invariant remains the single
authority for formal eligibility.

**Validation.** The 20-test suite above; the trial-fixture test proves
the gap path (measurement-backed weakest-priced provenance +
inference=None + warning); the formal-fixture test proves the
fully-priced path with §16.6 separation.

**Status.** Final (adapters read-only until C4/C8 consumers).

### C4 — `feat(runtime): unified RuntimeEstimator, factory, and RuntimeDecisionPolicy`

**Goal.** §7.1/§7.4/§9-directive: the shared estimator implementation
layer — one factory per run, one estimate-assembly path, one decision
policy implementing the §7.4 matrix; estimator/policy identity values
defined for invariants (locked in C9).
**Scope/deps.** New estimator/factory/policy modules under
`core/runtime_control/` (exact layout after inspecting seams);
`estimate = estimator.estimate(request)`;
`decision = policy.decide(estimate, budget, mode)`; static formulas
demoted to typed prior producers inside the estimator; NO consumer
rewiring yet (C8). Proposer must not load calibration tables directly;
no consumer keeps a private authoritative formula after C8. Deps: C3.
**Implementation plan.**
- [x] Layering audit: only agent→core imports exist; producers are
      DEPENDENCY-INJECTED; production wiring uses function-level lazy
      imports (`production_estimator_factory`) — no module-level
      core→agent edge.
- [x] `core/runtime_control/identity.py`: canonical structured payload
      → sorted-keys JSON → SHA-256[:12]; sets REJECTED (order must be
      explicit); `<name>@<semver>+<hash12>` per the approved scheme.
- [x] `core/runtime_control/decision_policy.py`: table-driven §7.4
      matrix (`_POLICY_MATRIX` — declarative rows feed the identity
      payload) + behavioral rules; decision vocabulary
      ADVISORY/REQUEST_PROBE/ALLOW/REJECT/ABORT with REJECT
      candidate-local vs ABORT unsafe-workflow documented and
      enforced; `CapacityCheck` (deterministic accounting, `realized`
      flag) implements the post-implementation-only VRAM placement;
      measured OOM/wall-cap/peak-violation → REJECT; uncalibrated
      clean probe blocks on time ONLY beyond its own optimistic bound
      (no new thresholds — D3/D4/D5 untouched).
- [x] `core/runtime_control/estimator.py`: `RuntimeEstimator` protocol,
      `DefaultRuntimeEstimator` (tier-0 static producer wired; C6/C7
      producers arrive through the same seams), `RuntimeEstimatorFactory`
      (one estimator+policy per run), identities incl. the legacy
      static-formula constants in the estimator payload (a formula
      change moves the identity).
- [x] Characterization: tier-0 estimates numerically identical to the
      legacy `estimate_proposal_time` across 4 shapes incl. the wave-1
      18.4M rejected-draft shape.
- [x] Doc sync (this section).
**Unit validation.** every §7.4 matrix cell; policy refuses
non-derived eligibility; factory identity stability; request
validation.
**Pseudo integration.** factory constructed in a pseudo run without
consumer switches (smoke).
**Acceptance.** (a) matrix behavior proven cell-by-cell; (b) estimator
byte-equivalent outputs vs legacy paths for identical inputs
(characterization tests) — no silent numeric drift before C8; (c)
identities stable and serializable.
**Failure/edge.** missing registry (explicitly absent → prior-only
estimates, §12); no CUDA host (CI!) → static/prior paths only.
**Migration/rollback.** Additive; consumers still on legacy paths.
**Boundary.** Estimator layer only, no rewiring.
- [x] Evidence recorded: `tests/unit/core/test_runtime_decision_policy.py`
      — **28 tests** (all matrix cells; priors never REJECT/ABORT on
      budget; realized-capacity REJECT vs LLM-authored ADVISORY vs
      pre-implementation ADVISORY; measured oom/wall_cap/peak-VRAM
      REJECT; over-budget-never-ABORT sweep; ABORT reserved for the
      invalid measured-failure+prior-provenance combination; identity
      format, cross-process determinism (subprocess ×2), insertion-order
      invariance, behavioral-change hash movement, precedence-order-as-
      behavior, no environmental inputs, set rejection, semver
      validation; 4-shape characterization parity). Full
      `tests/unit/core/` — **561 passed, 5.1 s**; ruff check+format
      clean; `git diff` over nodes/agent/workflows/execute_tools/
      launcher = EMPTY (no consumer rewired).

#### Implementation record — 2026-07-30 / C4

**Question encountered.** (a) How do core-layer modules reach the
legacy agent-layer producers without inverting the dependency
direction? (b) What belongs in the estimator identity payload beyond
the resolution order? (c) How does an uncalibrated clean probe block on
time without introducing a D3/D4/D5-class threshold? (d) When is ABORT
legitimate?

**Audit evidence.**
- Import sweep: `agent.skills.* → core.*` edges exist
  (inference_defaults, server_configs); zero `core → agent` edges.
- `training_skill/estimator.py:57,65,81` + `core/inference_defaults.py:60`
  — the behaviorally relevant static constants.
- §7.4 row "live probe, clean but not historically corrected":
  "conditional with explicit uncertainty".

**Decision.** (a) Injection + lazy production wiring. (b) The static
formula constants are policy-relevant defaults → included (formula
drift moves the identity; hardware/paths/timestamps excluded and
test-asserted absent). (c) The probe's OWN uncertainty bound: REJECT
on time alone only when `lower_seconds > budget` — uses the estimate's
uncertainty, no new policy threshold. (d) ABORT only for unsafe input
states (e.g. a measured failure reported with prior provenance —
evidence-channel corruption); over-budget never ABORTs (test-swept).

**Rationale.** Preserves layering; makes behavioral drift lock-visible
per the approved identity scheme; §6.4 authority-follows-evidence
without pre-empting C7 threshold decisions.

**Validation.** The 28-test suite + characterization parity above.

**Status.** Final (producers beyond tier-0 arrive in C6/C7; consumer
rewiring in C8).

### C5 — `feat(runtime): versioned hardware/environment profile and calibration registry`

**Goal.** §9.1 + §10.2 requirements: structured hardware profile
(extending O1a), versioned registry with schema/compat/drift handling,
read-only legacy k-table adapter.
**Scope/deps.** Extend `core/hardware_context.py` (compute capability,
dtypes, storage class, schema version — inspect first);
new registry module + on-disk layout; `SIDERIUS_CALIBRATION_DIR`
compatibility; content hashing; corruption detection; NO writers except
the validated observation path (C7). Deps: C3 (types), C4 (factory
consumes). 
**Implementation plan.**
- [x] `core/runtime_control/registry_schemas.py`: versioned typed
      schemas — RegistryManifest, HardwareCompatibilityProfile,
      ExecutionEnvironmentProfile (operator amendment §3: TWO separate
      hardware concepts; no hostname anywhere; stable installation
      UUID), CalibrationObservation (full field list per the approval
      §6; content hash EXCLUDES timestamp_metadata; validation_status
      IS content — a status change is a NEW record; schema-enforced:
      prior provenance can never be stored as a measured observation,
      closing the fallback-25 masquerade), CalibrationSummary (derived
      view with source IDs + generation anchor), LegacySourceReference.
      Full-digest IDs `sha256:<64hex>`; 12-char display alias only.
- [x] `core/runtime_control/calibration_registry.py`: split layout
      (registry.json index + per-record content-named files under
      observations/ hardware_profiles/ environment_profiles/ +
      rebuildable summaries/ + installation_id), tmp+rename atomic
      writes, advisory flock for index read-modify-write,
      record-before-index commit ordering (crash → orphan re-adopted,
      never a dangling index entry), rebuild_index with per-file hash
      verification (corruption/tamper exclusion + report),
      derive_summary + versioned stale-detected cache,
      SIDERIUS_CALIBRATION_DIR honored (registry coexists with the
      legacy files under the same override dir).
- [x] Cross-machine authority rule (§3.3): `as_estimate` demotes
      evidence from a different execution environment (or unvalidated
      local evidence) to `historical_observation_prior` — tier 1,
      never blocking alone; local validated evidence keeps measured
      provenance.
- [x] Legacy k-table adapter `adapt_legacy_k_table`: read-only
      (byte-identity asserted), content-hash + adapter-version
      reference, entries stamped legacy provenance via the existing C3
      adapter.
- [x] Doc sync (this section). O1a §9.1 field extension deferred to C6
      (the probe producer collects the profile inputs — recorded as a
      C6 dependency, not silently dropped).
**Unit validation.** schema round-trip; corruption → detected; 
incompatible keys → explicit rejection (each §17.8 case); adapter on
the REAL 720-entry table; env override.
**Pseudo integration.** registry resolution inside the C4 factory.
**Acceptance.** (a) registry create/read/validate on temp dirs; (b)
real legacy table adapts read-only with correct provenance; (c)
cross-hardware reuse impossible without explicit compatibility pass.
**Failure/edge.** absent registry (legal: explicitly-absent state);
partial writes; concurrent writers (atomic rename semantics like the
existing k-table).
**Migration/rollback.** Old file untouched (read-only adapter);
registry additive.
**Boundary.** Profile + registry + adapter.
- [x] Evidence recorded: `tests/unit/core/test_calibration_registry.py`
      — **25 tests** covering the operator §7 list: deterministic
      canonical IDs; full-digest + display alias; identical-record
      dedup vs semantic-difference non-dedup; 8-thread × 40-record
      concurrent writes with index integrity + per-record hash
      verification; interrupted-write invisibility; index
      reconstruction; tamper detection (load raises, rebuild excludes
      + reports); orphan re-adoption; stale-cache detection via
      generation + source-ID subset; environment separation under an
      identical compatibility profile; cross-machine → historical-
      prior-only; local-validated keeps measured provenance;
      local-unvalidated demoted; env-var override; read-only legacy
      adapter (source bytes unchanged, idempotent referencing);
      adapted entries stay `legacy_calibration_prior`; corrupt-index
      error names rebuild_index; generation increments only on
      change. Full `tests/unit/core/` — **586 passed, 5.1 s**; ruff
      check + format clean; consumer diff EMPTY.

#### Implementation record — 2026-07-30 / C5

**Question encountered.** (a) How to make concurrent observation
writes safe without a heavyweight store? (b) Where does the
installation UUID live? (c) Is `validation_status` content or
metadata? (d) O1a profile-collection extension — in C5 or C6?

**Audit evidence.**
- Existing `observation_store.py` calibration keys/eligibility — the
  registry reuses the concepts at cross-run scope; name collision with
  records.RuntimeObservation avoided via `CalibrationObservation`.
- Existing k-table atomic write (tmp+rename) — same primitive adopted;
  index read-modify-write additionally flock-guarded (rename alone
  cannot close the read-modify-write race).

**Decision.** Content-named one-file-per-record (idempotent concurrent
writes, natural dedup, tamper-evident filenames); flock only around
the small index; record-before-index ordering; installation UUID file
inside the registry root; validation_status IN the hash (immutable
records — revalidation is a new record); profile COLLECTION deferred
to C6 where the probe producer gathers the inputs (schemas are C5,
population is C6).

**Rationale.** Matches the approval's atomicity principles with the
smallest reliable mechanism; keeps records immutable and the index
rebuildable; no privacy-sensitive identifiers.

**Validation.** The 25-test suite above.

**Status.** Final (C6 populates profiles + observations; C7 owns the
validated write policy).

### C6 — `feat(runtime): post-implementation bounded live probe (setup, training, inference, VRAM)`

**Goal.** §8.2 as a mandatory lifecycle stage (§13.1): first real
runtime execution of the ACTUAL implemented candidate; fixes F-1a
(data-path resolution) AND F-1b (fresh-plugin loading) as SEPARATE
verified items; separate training/inference/setup/VRAM measurements
(§16.6 units); contention snapshot (§9.2).
**Scope/deps.** Probe engine reusing warmup machinery
(`evaluate_time_skill/wrapper.py`) + RT2 seams; dataset-path resolution
from the SAME source of truth training uses (F-1a — inspect;
STOP AND ASK if none); fresh-plugin load path (F-1b — probe loads the
just-validated plugin, recomputes realized parameters per §16.7);
probe caps (wall/steps/batches/VRAM, operator-visible); tuner
call-site ordering (probe after validation, before round-1 planning);
rollback flag. Deps: C3-C5.
**Implementation plan.**
- [x] F-1a audit RESOLVED: the single source of truth EXISTS —
      `execute_tools/data_paths.py::TIDMAD_DATA_DIR` (from
      `tidmad_data_config.yaml`), already used by `core/sandbox_executor.
      _tidmad_data_dir()` for every training subprocess. Only the
      warmup path ignored it. The probe resolves through it when no
      explicit `data_dir` is supplied — no second convention. (No
      STOP-AND-ASK needed.)
- [x] C6a — probe ENGINE (`core/runtime_control/probe.py`): pure
      orchestration over injected executors (setup / timed train step /
      timed inference batch / peak-VRAM) + injected telemetry — fully
      unit-testable without GPU; caps (wall + step/batch counts,
      defaults mirror the proven 3+7 warmup posture); OOM/wall-cap/
      load-failure are MEASURED outcomes preserving partial evidence;
      warmup steps excluded from timing; realized-property capture
      (`RealizedModelProperties`); count-based D3-neutral concurrency
      classification (presence of foreign compute processes + declared
      peer expectation — no utilization thresholds);
      `extrapolate_probe` (separate train/inference/setup, bounds from
      the probe's own timing spread); `probe_observations` → distinct
      training/inference `CalibrationObservation`s, `unvalidated`
      (C7 owns promotion).
- [x] C6b-1 — PRODUCTION executors (`core/runtime_control/
      probe_production.py` + `execute_tools/probe_data.py`): real torch
      + LIVE `ml_models.models_sandbox.MODEL_REGISTRY` load (F-1b;
      probe must run post-registration — enforced error otherwise) +
      canonical dataset path via `data_paths.TIDMAD_DATA_DIR` (F-1a;
      missing dataset raises — no synthetic fallback) + CUDA-event
      timing + `torch.cuda.max_memory_allocated` peak; realized
      properties recomputed from the instantiated module; optimizer
      switch mirrors `train_engine_sandbox` (verified: AdamW default
      w/ weight_decay, Adam, SGD); loss via the real `get_criterion`;
      §9.1 profile collectors (`collect_hardware_compatibility_profile`
      — no hostname; `collect_execution_environment_profile` —
      installation UUID). All heavy imports lazy; real execution only
      in the operator-gated GPU smoke / C12.
- [x] C6b-2 — device-aware executors (CPU probes legal for tests; no
      fabricated VRAM on CPU); §16.6 explicit unit conversions
      (`total_eval_segments` with the per-file 1-segment floor,
      `batches_for_segments`); F-1a/F-1b DIRECT tests (fresh REAL
      nn.Module registered into the LIVE registries and probed on CPU
      with hand-verified realized counts; unregistered type hard-errors;
      canonical-path resolution + no-synthetic-fallback proven);
      zero-LLM end-to-end chain test: implementation → REAL CPU probe →
      estimate → C4 policy ALLOW → C5 registry artifacts with realized
      supersession. One production defect found/fixed during testing:
      `probe_data` inherited the dataset's production sampling stride
      (sample_size=20 → 0 segments on small files); probe reads
      sequential segments (sample_size=1) — diagnosed from the dataset
      indexing math before fixing.
- [x] Workflow wiring DEFERRED to C8 per the operator's C6 directive
      ("C6 produces evidence only; decisions remain owned by the C4
      policy") — the original C6 wiring bullet is superseded; recorded
      here, not silently dropped. Reuse assessment: the probe shares
      the dataset loader + the 3+7 posture; step-timing convergence
      with TimeEval's warmup happens at C8 when TimeEval is rewired
      onto the estimator (no third long-term divergent timing path).
- [x] GPU smoke EXECUTED (operator-approved, 2026-07-30) — **PASS**,
      46.3 s total wall (cap 300 s), idle 5090, isolated registry
      `/home/klz/Data/SIDEREIS_DATA/c6_smoke_registry`, zero LLM, no
      V19/forensic paths (asserted in-script):
      * registered probe `punet_ce_loss_control_nano`: realized
        45,408 params; setup 22.5 s (CUDA context + H5 index
        dominate); train 17.62 ms/step (spread 17.60-17.65); inference
        3.17 ms/batch (3.16-3.18); peak VRAM 1.60 GB alloc / 1.61 GB
        reserved.
      * FRESH plugin `c6_smoke_fresh_probe` (written moments before,
        loaded via the REAL `register_model_in_memory` loader,
        asserted previously absent — F-1b on hardware): realized
        59,536 params; setup 21.9 s; train 8.06 ms/step; inference
        2.10 ms/batch; peak 1.62/2.23 GB.
      * Both probes `single_candidate_idle`; extrapolated estimates
        `bounded_live_probe` + blocking-eligible; training/inference
        measured separately; 4 observations (2 per probe, distinct
        train/inference) registered + hash-verified on reload;
        registry generation 8; NO fallback/downgrade path (no
        inference_defaults involvement by construction).
      * SMOKE FINDING → production fix: the contention snapshot
        counted the probing process's OWN CUDA context as a foreign
        compute app, misclassifying probe B as `foreign_contended`
        after probe A initialized CUDA in-process (the in-script
        contention guard STOPPED the first attempt — working as
        designed). Fix: self-PID exclusion in
        `capture_contention_snapshot` + 2 regression tests; the smoke
        re-ran clean. This finding also matters for C12: same-process
        sequential probes must self-exclude; PEER processes remain
        counted (test-proven).
**Unit validation.** caps honored; fast-fail; contended flag; realized
supersession; unit conversions (§16.6) with sentinels; fallback-25
never blocking.
**Pseudo integration.** deterministic fake probe through
estimate → decision → trial-control → artifacts (§17.3), sentinel
train/inference/setup separation proven end-to-end (§17.7); rollback
flag → byte-identical pre-C6 pseudo behavior.
**Real-GPU validation.** smoke probe of ONE registered + ONE freshly
implemented plugin (bounded, minutes) — operator approval required;
full matrix deferred to C12.
**Acceptance.** (a) every implemented candidate gets exactly one probe
record before round 1 (pseudo-proven); (b) F-1b: a NEW plugin (not in
any registry) is actually probed (GPU smoke evidence); (c) sentinel
separation + realized-parameter supersession proven; (d) contended
fake probe never updates calibration; (e) rollback parity.
**Failure/edge.** probe OOM (measured evidence, may block per §7.4);
wall-cap hit (measured, may block); dataset unavailable (explicit
provenance downgrade + guard-visible warning, never silent static);
concurrent peer probing (§16.9, record regime); plugin load failure
(validator-stage concern; probe must not mask).
**Migration/rollback.** rollback flag restores pre-probe flow.
**Boundary.** Probe engine + wiring; calibration WRITE policy is C7.
- [x] C6a evidence: `tests/unit/core/test_runtime_probe.py` — **16
      tests** (four concurrency branches + telemetry-gap honesty; ok
      path medians/spreads; warmup exclusion; setup load-failure/OOM;
      training OOM preserving measured peak; wall-cap via injected
      clock; caps recorded; extrapolation phase separation + bounds;
      non-ok cannot extrapolate; clean probe blocking-capable while
      never formal-eligible; contended demotion; probe-OOM→REJECT via
      the C4 policy; registry round-trip of distinct train/inference
      records). Full `tests/unit/core/` — **602 passed, 5.2 s**; lint
      clean.
- [ ] C6b evidence pending.

### C7 — `feat(runtime): calibration update, uncertainty, applicability, drift, and contention policy`

**Goal.** §8.3 + §10.3 policy + §16.8: validated write path
(update-eligibility table), per-component uncertainty, applicability
labels (interpolation / bounded / unsupported extrapolation), drift
detection, concurrency-bucketed records.
**Scope/deps.** Registry write path (C5), probe/verification/complete
observation writers (C6, RT2, tuner post-run), applicability
derivation, D3/D4/D5 resolution REQUIRED before this stage's contention
thresholds finalize (STOP AND ASK = operator decision point). Deps:
C5, C6.
**Implementation plan.**
- [x] Update-eligibility enforcement (§10.3 table) at the single
      PROMOTION seam — `eligibility_problems()` /
      `evaluate_bucket()`. Per D4's two-stage lifecycle the WRITE seam
      stays open to every schema-valid measurement (candidates are
      evidence); eligibility governs whether a candidate may back
      calibration authority. Priors can never enter at all: the
      `CalibrationObservation` schema rejects non-measurement
      provenance.
- [x] Uncertainty per component (`bucket_uncertainty`): cross-observation
      max/min ratio + the widest producer-recorded within-observation
      spread. No distribution is invented where none was measured.
- [x] Applicability labels + authority downgrade
      (`classify_applicability`, `applicability_for_request`,
      `downgrade_for_applicability` — demotes provenance to
      `historical_observation_prior`, which is what removes blocking
      eligibility since eligibility is derived, never assigned).
- [x] Drift/staleness rules (`detect_drift`): software-stack identity is
      part of the bucket key, so a stack change starts a fresh bucket by
      construction; ratio violations are reported, never averaged away.
- [x] Concurrency buckets (idle vs pairwise never cross-written) —
      plus operation, unit, hardware, EXECUTION ENVIRONMENT and family.
- [x] D5 unknown-family handling (`classify_model_family`,
      `CalibrationObservation.model_family`,
      `probe_observations(model_family=...)`).
- [x] D3 windowed contention classifier + the raw PID/throttle telemetry
      it needs (`classify_contention_window`, `sample_contention_window`,
      `probe.descendant_pids`, enriched `ContentionSnapshot`).
- [x] Deterministic promotion records persisted
      (`CalibrationPromotion`, `registry.record_promotion` /
      `load_promotion` / `bucket_status`, rebuild + tamper detection).
- [x] Doc sync (§20-D3/D4/D5 resolutions + this record).
**Unit validation.** every eligibility row; label boundaries;
drift cases (§17.8); bucket isolation; static/LLM values can never
reach the write path (type-enforced).
**Pseudo integration.** probe→registry→next-estimate loop with fake
observations.
**Acceptance.** (a) all §10.3 rows enforced by tests; (b) an 18.4M-class
request vs small-model history labeled unsupported-extrapolation with
downgraded authority; (c) idle bucket provably unpolluted by pairwise
writes.
**Failure/edge.** empty history; single-sample buckets (uncertainty
floor); clock skew in recency.
**Migration/rollback.** write path additive; legacy table still
read-only.
**Boundary.** Calibration lifecycle only.

**Implementation record (C7).**

*Files.* `core/runtime_control/calibration_policy.py` (new, ~700 lines);
`registry_schemas.py` (+`CalibrationPromotion`, `model_family`,
`"provisional"` status, non-authoritative `validation_status` doc);
`calibration_registry.py` (+`promotions/` directory, `record_promotion`,
`load_promotion`, `iter_promotions`, `bucket_status`, promotion-aware
`rebuild_index` and `as_estimate`); `probe.py` (+`descendant_pids`,
`_query_throttle_reasons`, PID-level `ContentionSnapshot`,
`probe_observations(model_family=...)`).

*Authority chain.* observation (immutable candidate, always
`unvalidated`) → `CalibrationPromotion` (derived, content-addressed,
cites ≥2 source observation IDs) → `registry.bucket_status()` →
`as_estimate()`. Because observations are never mutated, the promotion
record is the ONLY status source; `as_estimate` now consults it.

*Derived decisions taken during implementation* (each is
policy-versioned or documented, none silently chosen):

1. **`provisional` is not calibration-authoritative.** D4 names the
   middle state "provisional calibration"; `as_estimate` keeps measured
   provenance only at `validated` and demotes `provisional` to a
   historical prior with an explicit warning. Conservative reading —
   raising it later is a one-line policy change.
2. **Throttle-bit mask.** D3 says "unexplained clock/power throttling →
   unknown_contention", but `clocks_throttle_reasons.active` reports
   benign states too. The idle RTX 5090 on this deployment reports
   `0x4` (SwPowerCap) continuously, so treating any active bit as
   throttling would mark EVERY measurement `unknown_contention`. The
   policy therefore treats only genuine derating bits as unexplained:
   `HwSlowdown 0x08 | SyncBoost 0x10 | SwThermalSlowdown 0x20 |
   HwThermalSlowdown 0x40 | HwPowerBrakeSlowdown 0x80`
   (`DEFAULT_DERATING_THROTTLE_MASK`). It is a policy field, so changing
   it changes the policy identity. **Operator may revise.**
3. **Missing throttle telemetry is not evidence of throttling.** The
   field is optional (older drivers / non-NVIDIA); `None` leaves the
   verdict to the core telemetry-availability rule.
4. **A foreign COUNT without PIDs still contends.** If telemetry reports
   N compute processes but no PID detail, the unidentified remainder is
   treated as foreign — a peer must be positively identified, never
   assumed.
5. **Execution environment is part of the bucket key.** §3.3 grants
   local authority only to local evidence, so cross-machine
   observations form their own bucket and can never be promoted into
   local blocking authority.
6. **`bounded_extrapolation` is RESERVED, never assigned.** Choosing how
   far past measured evidence authority may travel is a margin
   decision; inventing one would recreate the uncalibrated-extrapolation
   failure this subsystem exists to prevent. Anything outside the
   measured range is `unsupported_extrapolation` until an operator fixes
   a margin. **Operator decision pending — not restart-blocking** (the
   conservative label is strictly safer).

*Boundary honored.* No production consumer was rewired: the probe engine
still uses its C6 count-based classifier, and the windowed D3 classifier
is exercised by tests only until C8 wires it. No budget, portion, or
scientific setting changed. V19 remains stopped.

- [x] Evidence recorded: `tests/unit/core/test_calibration_policy.py` —
      **61 tests** (D3: idle / unregistered-PID / registered-peer /
      peer+stranger / no-name-inference / count-without-PIDs / 10 %
      threshold on a large device / 1 GiB floor on a small device /
      sustained-vs-spike utilization / telemetry gap / derating throttle
      / benign power-cap / absent throttle field / policy-versioned
      thresholds / bounded 5-sample window with no trailing sleep / raw
      telemetry payload. D4: 1→candidate, 2→provisional, 3→validated,
      ratio 2.0 blocked, ratio exactly 1.5 promoted, determinism under
      input reordering, observations unmutated, mixed-bucket and dirty
      input rejected, failure-outcome evidence excluded, 8 bucket
      dimensions separated, idle-vs-pairwise isolation, cross-machine
      isolation, verification-agreement route incl. incomparable units /
      disagreement / wrong provenance / contended verification. D5:
      declared metadata, structural feature, uncertain→unknown, unknown
      never folded into a known family, unknown promotes on its own
      evidence. Drift/uncertainty/applicability incl. acceptance (b)).
      `test_calibration_registry.py` — **+7** promotion-persistence
      tests (index, bucket_status authority, end-to-end authority
      restoration, unindexed-source rejection, idempotent re-record,
      rebuild dropping orphaned promotions, tamper detection); two
      pre-C7 tests updated because they asserted authority from a
      self-declared `validation_status`, which D4 forbids.
      `test_runtime_probe.py` — **+4** (real-child `descendant_pids`,
      child-PID exclusion, explicit `exclude_pids`, declared family on
      observations). Pseudo integration:
      `tests/integration/workflows/test_calibration_lifecycle_pseudo.py`
      — **4 tests** (candidate-only has no authority; 3 consistent
      probes promote both buckets and restore measured authority;
      contended probes persist but never promote; validated history
      cannot price an 18.4M-parameter request).
      Full `tests/unit/core/` — **685 passed, 5.9 s**; targeted ruff
      check + format clean. Full local `tests/unit` — **4931 passed, 4
      xfailed, 3 m 53 s**.

*C7 stage closure.* Commits `5150eef`, `4523681`, `3cd3605`, `63aa48e`,
`83efe86`, `46df5e8`, plus the Principle 5 follow-up `cdf91b2`. CI green
on head **`cdf91b2`** (run 30584752115): ruff check, ruff format,
strict pyright, and the full unit suite (guardrails included) all pass.

The first CI attempt (`46df5e8`) failed one guardrail — the derating-mask
comment named a specific accelerator model, which
`tests/unit/guardrails/test_no_hardcoded_device_literals.py` forbids
anywhere under `core/`. The device fact was removed from the source
rather than annotated past the allow-list; the deployment-specific
observation lives in decision 2 above. `DEFAULT_DERATING_THROTTLE_MASK`
stayed `0xF8` and the policy identity was verified byte-identical across
the fix (`calibration_policy@1.0.0+b83994605c57`).

### C8 — `refactor(runtime): wire proposer, tuner, admission, watchdog, and reporting to the shared estimator`

**Goal.** §2.3/§9-directive: every runtime consumer on the one
subsystem; private authoritative formulas removed (static producers
remain as typed priors inside the estimator).
**Scope/deps.** Proposer pre-flight → estimator (advisory per policy);
TimeEval → estimator; admission/watchdog → estimator-mediated evidence
(preserving RT2 measured semantics EXACTLY — characterization tests
first); reporting/provenance surfaces. Deps: C4-C7.
**Implementation plan.**
- [x] **C8a** Characterization suites capturing CURRENT admission/
      watchdog/TimeEval numeric behavior before rewiring
      (`tests/unit/core/test_c8_consumer_parity.py`, 18 fixtures with
      hand-derived LITERAL expectations — admission 2.0 / watchdog 3.5 /
      floor 120 / budget 7200 / TimeEval 10 % slack).
- [x] **C8b** Proposer → shared policy: the advisory note is emitted on
      `RuntimeDecisionPolicy.decide(...)` at `phase="proposal"`, not on a
      private `factor > 1.0`. A REJECT/ABORT at this stage raises —
      the advisory-only invariant is now enforced, not merely intended.
      The policy identity travels in the note.
- [x] **C8c** TimeEval → shared policy: `feasible` is DERIVED from the
      decision kind. Measured evidence keeps identical numerics
      (effective budget incl. slack is what the policy is asked about);
      prior-tier evidence can no longer gate. Formal + prior + no probe
      → REQUEST_PROBE; uninterpretable evidence → ABORT → error result.
- [x] **C8d** Watchdog → measurement-backed evidence only: the deadline
      arithmetic is untouched, but a component prediction must declare a
      measurement-backed `source` to arm it (§7.4 watchdog column:
      static `never_used`). Every RT2-written prediction already
      qualifies, so no production number moves.
- [x] **C8e** Production probe adopts the D3 windowed PID-aware
      classifier; `classify_concurrency` DELETED (no second
      authoritative path). Full raw window persisted on the result and
      into the observation.
- [x] **C8f** Authority audit
      (`tests/unit/guardrails/test_runtime_authority_audit.py`) — a
      mechanical guard that each consumer resolves the shared policy and
      that no private gate returns.
- [x] Doc sync (this record).
**Unit validation.** consumer parity (§17.4): same estimator identity,
same vocabulary, compatible workloads/units; admission/watchdog
numeric parity on recorded fixtures.
**Pseudo integration.** full pseudo chain: proposal advisory →
implementation → fake probe → estimate → decision → trial/formal →
watchdog → artifacts, with provenance asserted at every hop.
**Acceptance.** (a) grep proves no consumer computes authority outside
the policy; (b) admission/watchdog byte-parity on fixtures; (c) §17.4
parity suite green.
**Failure/edge.** mixed-version resume (handled by C9 lock); missing
probe record at admission time (explicit policy, never silent static).
**Migration/rollback.** per-consumer flags during transition; final
state removes them.
**Boundary.** Rewiring only; no policy-value changes.

**Implementation record (C8).**

*Behavior deltas — deliberate, and the point of the stage.* Numeric
parity was preserved everywhere it was required (admission, watchdog,
measured TimeEval). THREE behaviors changed, all of them removals of
authority that the §7.4 matrix never granted:

1. **A static projection can no longer skip a round.** Previously
   `evaluate_time_skill` compared its own projection to the budget and
   the tuner emitted `skipped_time_risk` on the result — including when
   the projection came from the uncalibrated static formula (no CUDA, no
   `data_dir`, or an unregistered architecture). That is the wave-1
   mechanism. The projection is still computed, still reported, still
   carries its suggestion — it simply cannot gate. Measured (warmup)
   evidence gates exactly as before.
2. **A store-reused (historical prior) projection can no longer skip a
   round** — same rule, tier 1 (`historical_observation_prior`).
   Trial-only path, since formal never reuses the store.
3. **A prior-sourced component prediction can no longer arm the watchdog
   kill deadline.** No production record is affected (every RT2
   prediction is measurement-backed by construction); the hole is
   closed structurally.

*Autonomous decisions taken during implementation.*

* **Observation vs authority were separated in TimeEval.** The verdict
  text and the improvement suggestion now key off
  `over_effective_budget` (an observation), while `feasible` keys off
  the policy decision (authority). Conflating them would have deleted
  the operator-facing overshoot warning along with the blocking power —
  the C8 mandate is to remove authority from priors, not to silence
  them. New breakdown keys: `over_effective_budget`,
  `runtime_decision`, `runtime_decision_reasons`,
  `runtime_decision_provenance`, `runtime_policy_identity`.
* **REQUEST_PROBE at the pre-flight means "proceed to the authoritative
  measurement", not "stall".** The tuner's authoritative formal evidence
  is the RT2 in-subprocess verification, and no C6 probe runs at
  pre-flight time; `probe_record_available=False` is therefore declared
  honestly and REQUEST_PROBE lets the round proceed INTO the measured
  admission path rather than pricing it from a prior.
* **An uninterpretable evidence source is ABORT, not "infeasible".** The
  adapter accepts exactly the sources production can emit; anything else
  is an evidence-channel failure surfaced as an ERROR result (the tuner
  raises), never as a candidate verdict. This also hardened
  `_query_throttle_reasons`, which previously hex-parsed any output —
  a bare decimal string would have fabricated a throttle mask.
* **The contention window runs BEFORE setup, serially.** The operator
  permits overlapping it with CPU-only setup; that optimization is
  deliberately NOT taken. Running the window first is simpler and
  strictly more correct — the probe's own CUDA context does not exist
  yet, so nothing of ours can contaminate the external-state reading.
  Cost: ~10 s per probe, the accepted price. `device_vram_gb` is a
  REQUIRED probe argument (the D3 memory threshold has no safe default);
  `probe_production.probe_device_vram_gb()` resolves it in production.
* **Policy identity changed** (expected): `EvidenceChannel` and the
  three new behavioral rules (`formal_probe_absent`,
  `infrastructure_failure`, `measured_candidate_failure`) are part of
  the identity payload, so the C4 policy hash moves. That is the
  designed signal that decision behavior changed.

*Tests changed rather than added* (each an encoding of superseded
authority, not a production regression):
`test_evaluate_time_skill.py::test_run_skill_infeasible_large_model` and
four `test_inference_hint_path.py` slack cases now assert
`over_effective_budget` + the ADVISORY decision instead of
`feasible is False`; `test_inference_hint_path.py`'s stub emitted
`ms_source="fake_stub"`, a value production cannot produce, and now uses
`static_uncalibrated`; the watchdog stubs in
`test_watchdog_admission_split.py` gained the `source` field that every
production prediction carries.

- [x] Evidence recorded: `test_c8_consumer_parity.py` — **18** (admission
      within/over/boundary/record-only/fail-closed/watchdog-override-
      independence; watchdog deadline table incl. floor clamp, budget
      clamp, factor fallback, disabled, and prior-backed evidence never
      arming a deadline; TimeEval under/over/at-budget + slack applied
      and not applied). `test_c8_timeeval_authority.py` — **15**
      (measured keeps authority incl. formal; static/store/wave-1 shape
      cannot gate; formal missing-probe REQUEST_PROBE incl. the
      within-budget case; probe-present removes it; ABORT paths).
      `test_runtime_authority_audit.py` — **6** (consumers resolve the
      shared policy; `feasible` derived from the decision by AST;
      proposer invariant present and `factor > 1.0` absent from
      executable code; watchdog measurement-backed guard;
      `classify_concurrency` gone). `test_runtime_probe.py` — windowed-
      classifier conversion + **4** new concurrency tests.
      Full `tests/unit` — **4974 passed, 4 xfailed** (the single
      `test_pr3_l2p_preflight` failure is its dirty-working-tree check,
      green on a clean checkout / in CI). Full `tests/integration` —
      **142 passed, 130 skipped** (real-API tiers skip without keys).

### C8 closure audit (operator-requested, 2026-07-30)

A read-only trace of the two residual limitations reported at C8
completion. Findings, with the evidence that produced them:

**Finding 1 — `REQUEST_PROBE` has no executor in production.**
`run_bounded_probe` has ZERO production call sites (grep over the repo,
excluding tests and the operator-gated smoke script). Likewise
`production_probe_executors`, `probe_observations` and
`CalibrationRegistry(...)`. Consequently: no probe runs, no probe record
is ever persisted, no estimate is rebuilt from one, and the C5/C7
registry is never written outside tests.

There is NO infinite-loop risk: `REQUEST_PROBE` is non-blocking at the
pre-flight seam (`feasible = kind != "REJECT"`), so the round proceeds
into training, where the RT2 in-subprocess verification produces real
measured evidence and `decide_admission` acts on it. So formal EXECUTION
is governed by measurement — but the decision vocabulary promises a
probe that nothing runs, and the pre-flight decision itself is made
without one.

Classification: **production wiring gap, not C12 validation work.**
Wiring it changes LIFECYCLE ORDERING (a bounded probe would run between
implementation and formal execution) and requires real GPU execution to
validate, both of which are operator stop conditions. Proposed for C9
scope — see the C9 entry — rather than implemented autonomously here.

**Finding 2 — consumers did not share an estimator/policy instance.**
Before this closure, `RuntimeDecisionPolicy()` was constructed
independently in two places (the proposer, cached; the TimeEval gate, per
call) and `production_estimator_factory()` had no production caller at
all. The identities matched — the policy is stateless and its identity is
a pure function of its payload — but nothing enforced that.

Fixed here (**C8g**): `estimator.shared_runtime_components()` is the
process-wide resolution point; both consumers now resolve it, and two
guardrail tests assert that they get the SAME object and that no consumer
constructs its own policy.

**Finding 3 (new, found during this audit) — admission decides outside
the policy.** `RuntimeVerificationSession.decide_admission`
(`train_engine_sandbox.py:715,829`) computes `adjusted > budget` →
reject privately, and never calls `RuntimeDecisionPolicy`. Its evidence
IS measurement-backed, so the policy would return the same verdict for
the same input, and its numerics are pinned by C8a — but "no consumer
computes authoritative runtime decisions outside the shared policy" is
not yet literally true. Routing it through the policy needs a decision on
how "verification failed → fail closed (§2.11)" maps into the decision
vocabulary, which the policy has no rule for today. **Not invented
here** — proposed as a C9 item with an explicit semantics decision.

**Why the estimator OBJECT is still not the single assembly path.**
`DefaultRuntimeEstimator.estimate()` resolves only the tier-0 static
producer. Consumers that already hold better evidence — TimeEval's
warmup measurement, RT2's verification, a probe record — assemble
through the canonical adapters in `estimate_types` instead. Routing them
through the estimator TODAY would downgrade measured evidence to a
static prior, which is the opposite of the design intent. The correct
fix is to let the estimator accept caller-supplied measured evidence and
resolve §8.4 precedence over {probe record, registry history, caller
measurement, static}. That is a factory-lifecycle change → C9.

Audit table (production paths only):

| Consumer | Policy source | Estimate assembly | Registry | Verdict |
|---|---|---|---|---|
| proposer | shared factory (C8g) | `from_proposer_preflight` | none | policy-decided |
| TimeEval gate | shared factory (C8g) | `from_time_eval_result` | none | policy-decided |
| watchdog | shared vocabulary (`MEASUREMENT_BACKED_SOURCES`) | none — sums component predictions | none | produces a DEADLINE, not a decision kind; no policy call by design |
| admission (RT2) | **none** | none — sums `RuntimePrediction` | none | **Finding 3: private comparison** |
| probe | n/a (evidence producer) | `extrapolate_probe` → `make_estimate` | writes observations — but no production caller (Finding 1) | not wired |
| reporting | none | none | none | not wired |

### C9 — scope expanded after the C8 closure audit (operator, 2026-07-30)

The audit's three findings are C9 work, not C12 validation:

```text
C9a  shared evidence assembly (measured / probe / registry / static)
C9b  REQUEST_PROBE -> probe -> persist -> re-evaluate
C9c  admission failure classification + chain-level ABORT
C9d  launch guard + run-invariant lock (against the FINAL lifecycle)
```

**C9a — shared evidence assembly.** [x]
`DefaultRuntimeEstimator.estimate(request, caller_measurement=...)`
ranks caller measurement > probe > history > static by
`evidence_rank`. Rank is a property of the EVIDENCE: a prior passed as
`caller_measurement` keeps prior authority, and a measurement is never
downgraded to static (the C8 gap). Lookups are injected and may return
None — an absent source is a recorded gap, never a fabricated estimate.
Configured producers are part of the estimator identity.
Evidence: `tests/unit/core/test_probe_lifecycle.py` (8 assembly tests).

**C9b — REQUEST_PROBE lifecycle.** [x]
`core/runtime_control/probe_lifecycle.py`. `ProbeResolver` is stateful
per attempt, which is what makes a loop structurally impossible rather
than merely unlikely: a second REQUEST_PROBE after a completed probe is
an invariant failure (ABORT), a failed probe is never retried, and a
re-decision that somehow returns REQUEST_PROBE is caught and converted
to ABORT. `resolve()` cannot return REQUEST_PROBE — asserted over every
probe status. Measured OOM / wall-cap → REJECT; load failure, executor
error, unexpected exception, or a successful measurement that cannot be
PERSISTED → ABORT (deciding from unrecorded evidence would leave a
formal decision unauditable). No static fallback on any path.
A failed probe is never extrapolated: projecting a rate measured up to
the moment of failure would invent a completion that did not happen.
Evidence: 16 lifecycle tests.

**C9c — failure classification and chain termination.** [x]

*Schema (operator decision: Option B).* `AdmissionRecord.failure_class:
Literal["candidate","infrastructure"] | None = None`. The persisted
`decision` literal is UNCHANGED — no `"aborted"` value — because three
production readers key on `== "rejected"` (two of them stop training,
one excludes from calibration) and a new value would have silently
turned an abort into "not rejected" at exactly those points. Legacy
records validate with `failure_class=None`, and every reader treats
None conservatively: an unclassified refusal is an absence of
classification, never a claim that the run was clean.

*Mapping.* ALLOW → admitted/None. Measured over budget, verification
failure under a working verifier → rejected/candidate. Evidence-channel
failure → rejected/infrastructure, via the new
`session.record_evidence_channel_failure(reason)`, which takes
precedence over EVERY other admission outcome including record-only
mode (a record-only run still depends on the channel to record).

*Propagation — the chain halts.* Reusing the mechanism the repository
already had for non-continuable states rather than inventing one:

```text
session (infrastructure)      -> sidecar admission.failure_class
sandbox_executor               -> status="aborted_infrastructure"
tuner                          -> RuntimeEvidenceChannelError (typed)
                               -> termination_reason="infrastructure_abort"
run_one_iteration.py           -> .chain_halted sentinel (reason field)
                               -> sys.exit(3)
```

The sentinel is what stops a QUEUED iteration — SDSC's `afterany`
dependency starts the next job whatever the exit code was — and exit 3
stops the foreground loop. The sentinel's `reason` field distinguishes
this from the consecutive-failure brake, so an operator can tell why the
chain stopped. The halt runs AFTER the manifest is written: the
diagnostics are exactly what a broken environment needs preserved.
`infrastructure_abort` outranks `scope_violation` in
`_compute_termination_state` — with a broken channel, this run's other
classifications are themselves untrustworthy.

Distinct from: operator stop (a kill, not exit 3), gate exhaustion
(`no_records`, exit 0, chain continues), candidate rejection
(attempt-local), and an ordinary crash (exit 1).

Evidence: `tests/unit/core/test_c9c_failure_classification.py` (17 —
schema defaults and legacy validation, the unchanged decision literal,
all four classification paths, infrastructure precedence over budget and
over record-only, sidecar persistence, calibration exclusion for both
classes AND for legacy-unclassified, executor status routing);
`tests/unit/sdsc_submission_scripts/test_c9c_chain_termination.py` (15 —
precedence incl. outranking every other reason, the untouched existing
precedence, abort detection, the four non-halting reasons, sentinel
reason/typing, exit-3-after-manifest ordering, gate exhaustion still
exiting 0). Full `tests/unit` — **5032 passed, 4 xfailed**.

**C9d — production wiring, launch guard, run-invariant lock.** [x]

*Production wiring (the point of the stage).* `probe_wiring.py` holds
the connections: `build_production_probe_runner` (real plugin, real
dataset, real device — every assembly failure raised as
`ProbeInfrastructureError`), `build_registry_persist` (real C5/C7
registry with hardware + environment profiles), and
`resolve_request_probe`, the single production entry point. The tuner's
`_resolve_time_check_probe_request` calls it when the pre-flight returns
REQUEST_PROBE and maps the outcome: ALLOW → proceed, REJECT →
attempt-local skip, ABORT → `RuntimeEvidenceChannelError` → chain halt.
The resolution is recorded on the round's breakdown
(`probe_resolution`, `probe_observation_ids`, `probe_status`,
`probe_expected_seconds`).

An environment that cannot build a real runner (CPU box, no dataset,
pseudo run) records a VISIBLY TYPED `probe_resolution="unavailable"`
with the reason instead of resolving. A real formal launch never reaches
that branch — the guard refuses to start (below).

*Launch guard.* `launch_guard.run_launch_self_test()` runs in
`run_workflow` before any LLM call or trajectory mutation. It does not
check that classes exist — existence was true throughout the wave-1
incident. It EXERCISES the lifecycle through the same entry point
production calls, with an injected fake runner:

```text
shared estimator + policy resolved once per process
static evidence cannot block
measured evidence retains blocking authority
a formal decision on a prior returns REQUEST_PROBE
REQUEST_PROBE resolves through the production entry point
the probe runs exactly once; a repeat request ABORTs
probe infrastructure failure ABORTs (no static fallback)
probe-runner availability (REQUIRED for a real launch)
```

Measured cost on the dev box: **0.67 s**, no GPU work, no network, no
LLM. `require_probe_runner` is True exactly when the launch uses real
factories.

*Run-invariant lock — legacy workspaces are REFUSED, not defaulted.*
`runtime_estimator_identity` and `runtime_policy_identity` join
`_CANONICAL`, stamped by `build_run_invariants` (the one shared path, so
workflow / chain runner / standalone tuner cannot diverge). Unlike every
earlier lock field, these have NO pre-feature state to default into: a
lock without them was written when a static formula could gate rounds
and a prior could arm the watchdog. `_reject_legacy_runtime_lock` raises
before any LLM call, names the missing fields, and requires a fresh
workspace. The Pydantic default exists ONLY so an old lock can be parsed
well enough to produce that error — parsing is not compatibility. A
legacy-vs-legacy comparison stays legal so old tooling can still read
old workspaces.

Evidence: `tests/unit/core/test_c9d_launch_guard.py` — **20 tests**
(guard passes and reports; guard is offline — asserted by making
`subprocess` raise; refuses a production launch that cannot probe;
catches a policy that lets static evidence block; catches an unwired
REQUEST_PROBE; guard and production share one entry point; the tuner
edge resolves + persists; probe REJECT stays attempt-local;
infrastructure failure asks for a chain abort; unprobeable environment
is typed not silent; other decisions untouched; assembly failure is
infrastructure; a load-failure probe ABORTs; availability never raises;
legacy lock parses; legacy resume refused BY NAME; refusal through
`ensure_run_invariants`; fresh workspace records identities; changed
policy identity is a violation; legacy tooling still reads legacy
workspaces). Full `tests/unit` — **5052 passed, 4 xfailed**; full
`tests/integration` — **142 passed, 130 skipped**.

### C9 — `feat(runtime): formal launch invariant, behavioral self-test, and run-invariant locking`

**Goal.** §12 with the typed-policy guard (NO introspection): construct
real estimator+policy at startup, run the behavioral self-test, lock
all §12 policy fields in run invariants; resume-incompatibility fails
pre-LLM.
**Scope/deps.** `run_one_iteration` startup; `core/run_invariants.py`
new fields (lock-schema change — inspect migration implications; STOP
AND ASK if legacy-lock compatibility is ambiguous). Deps: C4, C8.
**Implementation plan / validation** per §12 text; mutation evidence:
a build with static-blocking re-enabled fails launch with the named
invariant; guard cost < 1 s, no GPU/network; pseudo launches pass;
legacy workspaces without fields → explicit failure, not silent
upgrade.
**Acceptance.** §12 field list locked + behavioral self-test proven +
resume mismatch fails before LLM/training with field/locked/requested
named.
**Failure/edge.** guard failure leaves no partial iteration artifacts.
**Migration/rollback.** lock fields additive; documented legacy rule.
**Boundary.** Guard + lock + tests.
- [ ] Evidence recorded.

### C10 — `feat(runtime): user-facing calibration/bootstrap CLI and readiness self-test`

**Goal.** §12-directive workflow: `install → inspect → calibrate →
validate → launch` with no manual file edits.
**Scope/deps.** Project-native CLI (final name per repo conventions —
inspect; e.g. `python -m siderius.runtime.calibrate --device cuda:0` or
a `scripts/` entry point): the 11-step §12-directive sequence
(environment inspection → profile → data/synthetic probe validation →
bounded training probes → bounded inference probes → setup+VRAM →
contention telemetry → versioned records → registry self-validation →
consumer-parity self-test → readiness verdict). Deps: C5-C8.
**Unit validation.** each step mockable + tested; refusal paths (no
CUDA, no data) produce actionable verdicts.
**Real-GPU validation.** one full bootstrap run on the 5090 (bounded;
operator approval) — its output registry becomes the campaign baseline.
**Acceptance.** fresh-environment simulation (temp HOME + empty
registry) reaches a correct readiness verdict without editing any
source/JSON by hand.
**Failure/edge.** partial bootstrap resume; contended environment at
bootstrap time (recorded, flagged).
**Migration/rollback.** additive tool.
**Boundary.** CLI + self-tests.

**Implementation record (C10).**

*Files.* `core/runtime_control/bootstrap.py` (the eleven-step sequence
over injected seams), `scripts/runtime_bootstrap.py` (the CLI),
`docs/runtime_bootstrap.md` (operator guide).

*The eleven steps* run in the §12-directive order and each produces a
`BootstrapStep` with `ok`, a detail, and — when it fails — a REMEDY. An
unusable environment is a RESULT (NOT READY), never an exception: a
bootstrap tool that crashes teaches the operator nothing.

*Constraints kept.* Writes go through `CalibrationRegistry` only —
asserted by a test that the run creates exactly one directory and nothing
else, so there is no file for an operator to hand-edit. `--registry-dir`
isolates the registry by setting `SIDERIUS_CALIBRATION_DIR` for the
process, which is why no config file needs touching. Step 11 calls the
SAME `run_launch_self_test` the launch guard calls.

*Contention is refused, not averaged in.* A `foreign_contended` window
stops the run BEFORE the probe, and the registry stays empty — a dirty
baseline is worse than none. The classification and its reasons are
recorded on the step either way.

*Two honest limits, documented in the operator guide.* One clean
bootstrap yields a CANDIDATE observation per operation, not calibration —
under D4 a bucket needs 2 consistent observations for provisional and 3
for validated, so repeated bootstraps on an idle machine are the path to
calibration (proved by a pseudo-integration test that runs bootstrap
three times and watches the buckets promote). And C10 says nothing about
estimator ACCURACY across families and scales; that is C12.

- [x] Evidence recorded: `tests/unit/core/test_c10_bootstrap.py` — **19
      tests** (fresh environment reaches READY with an empty temp
      registry and no hand edits — the design-doc acceptance criterion;
      the eleven steps run in order; the four measured quantities are
      recorded; writes go only through the registry; hash-verified
      read-back; the verdict renders; and eight refusal paths — no
      accelerator, no dataset, contended GPU, telemetry failure,
      unbuildable model, oom/wall_cap/load_failure probes, unwritable
      registry, failing launch self-test — each asserting the remedy is
      actionable and that an environment problem is a verdict rather than
      an exception; plus the CLI surface and bounded defaults).
      `tests/integration/workflows/test_bootstrap_pseudo.py` — **5 tests**
      over the REAL probe engine, REAL D3 classifier, REAL registry and
      REAL launch guard with only the device seams faked (fresh
      environment → READY; the recorded evidence is usable by a later run
      and is correctly a PRIOR until promoted; three consistent
      bootstraps promote the buckets to validated; a contended GPU
      refuses before measuring and leaves the registry empty; bootstrap
      is idempotent — identical content is content-addressed to the same
      record).

### C11 — `feat(runtime): legacy migration and metadata/executable replay tools`

**Goal.** §17.10 two-mode replay + legacy k-table migration/adapter
finalization.
**Scope/deps.** `scripts/runtime_replay/` (metadata mode: forensic
proposals vs tiers, NO ground-truth claims; executable mode: bounded
probe+segment for LOADABLE candidates only — the preserved 18.4M/1.76M
drafts have no implementations and the report must say so). Deps:
C5-C7.
**Unit validation.** determinism; mode separation (metadata mode cannot
emit runtime-validation claims — schema-enforced report labels).
**Real-GPU validation.** executable replay only within the C12 campaign
budget.
**Acceptance.** metadata replay of all four preserved proposals with
per-tier labels; explicit "no runnable implementation" marking.
**Failure/edge.** forensic snapshot moved → clear path error.
**Boundary.** Tools + tests.
- [ ] Evidence recorded.

### C12 — `validation(runtime): multi-family, multi-scale, idle + pairwise-concurrent GPU campaign`

**Goal.** §24 campaign under §24 PRE-REGISTERED thresholds; resolves
the empirical halves of D3/D8; produces the restart evidence for
criteria 23-25.
**Scope/deps.** Campaign driver (may reuse C10 probes); ≥3 families ×
≥4 scales (~50K/500K/5M/20M) idle + pairwise subset; per-cell records
per §24; thresholds FROZEN before execution (operator approval of §24.2
values); calibration updates only via the C7 validated path. Deps:
C6-C11. **Operator approval required before any GPU execution** (exact
commands, duration, output paths shown first).
**Acceptance.** §24.2 thresholds met, or a defect-fix loop with
re-registered (operator-approved) thresholds — never post-hoc
relaxation.
- [ ] Evidence recorded (full per-cell table archived).

### C13 — `fix(v19): formal queue-runner hardening and recovery cleanup`

**Goal.** §23-directive queue requirements + the CONFIRMED respawn
defect: during the wave-1 stop, killing the iteration Python allowed
`run_chain.sh` to respawn iteration 2 (`--start_iteration 2` respawn
observed live; §15/stop record). An operator stop must terminate the
CHAIN LOOP, not one child.
**Scope/deps.** Port Gate-runner hardening to `v19_queue_runner.sh`
(stagger health check, in-session wrapper-PID self-report, marker-based
completion, summary on every exit path, wall cap, no `/tmp` full logs)
+ NEW: explicit operator-stop mechanism (stop-file or signal trap in
`run_chain.sh` that ends the iteration loop and writes a stopped-wave
state record; no automatic next-iteration respawn after an
operator-directed stop). Recovery cleanup: execute the approved
deletion inventory (stopped-wave relics) AFTER this design is approved
and re-checked (§19). Deps: none on C1-C12 (parallelizable), but part
of restart criteria 26-28.
**Unit validation.** queue-runner suite extensions (stop semantics:
kill wrapper → loop terminates, state written, no respawn); existing
23 queue tests stay green.
**Acceptance.** simulated operator stop terminates the loop with a
stopped-wave record and zero respawns; cleanup executed with
before/after proofs (paths absent, forensics hash-valid, no
references).
**Failure/edge.** stop during training vs between iterations; stop-file
races.
**Migration/rollback.** shell-only.
**Boundary.** Queue/chain stop semantics + cleanup.
- [ ] Evidence recorded.

### C14 — `docs(runtime): acceptance evidence, cold-start smoke, and V19 restart stop-and-show`

**Goal.** §26 Layers 4-5: bounded cold-start production smoke (real
candidate, real probe, real estimator, real artifacts, no trajectory
reuse — STILL NOT V19), then the complete restart report against all 33
acceptance criteria; operator authorization gate.
**Scope/deps.** Everything green first (C1-C13, CI on the exact head).
**Acceptance.** all §18 criteria evidenced item-by-item; smoke passes;
report reviewed; **explicit operator authorization received before any
restart**.
- [ ] Evidence recorded.

---

## 24. Real-GPU validation campaign (mandatory, pre-registered thresholds)

### 24.1 Matrix and records

Minimum matrix: **≥ 3 model families × ≥ 4 parameter/compute scales**
(~50K / ~500K / ~5M / ~20M), runnable and representative, under the V19
workload shape, plus a **pairwise-concurrency subset**. For every cell
record separately: setup/compile time; training probe; inference probe;
projected training runtime; projected inference runtime; projected
total; actual bounded execution runtime; peak VRAM predicted; peak VRAM
actual; hardware snapshot; contention snapshot; provenance; calibration
identity; applicability classification; under/over-prediction ratios.
No manual registry edits; updates only through the C7 validated path.
Exact commands, durations, output paths + the frozen thresholds are
shown for operator approval BEFORE any GPU execution.

### 24.2 Pre-registered acceptance thresholds (PROPOSAL — requires operator approval BEFORE execution; never revised post hoc)

Metrics emphasize underprediction separately from symmetric accuracy.
Report at minimum: median absolute percentage error; 90th-percentile
absolute percentage error; maximum underprediction ratio; maximum
overprediction ratio; training error; inference error;
setup/fixed-overhead error; VRAM underprediction; size-correlated bias;
family-correlated bias; contention-regime bias.

Proposed initial thresholds (NOT yet approved policy):

```text
median absolute percentage error <= 30%
90th-percentile underprediction <= 50%
no candidate >= 5M parameters underestimated by more than 2x
no monotonic size-dependent underprediction trend
VRAM underprediction <= max(20%, 1 GiB)
no architecture family with systematic underprediction across all sizes
```

- [ ] Final thresholds operator-approved and frozen (recorded here)
      before the campaign runs.
- [ ] Campaign executed; per-cell table archived; §18 criteria 23-25
      evidenced.

---

## 25. Required testing layers

```text
Layer 1 — deterministic unit tests
  static-cannot-block; provenance-derived authority; vocabulary
  reconciliation; evidence precedence; training/inference separation;
  realized-parameter supersession; contention classification;
  calibration compatibility + drift; registry atomicity + corruption;
  no prompt contamination; launch-policy self-test; resume invariants;
  concurrency identity; legacy migration.

Layer 2 — zero-LLM pseudo integration
  top-level launch → runtime policy construction → proposal advisory →
  implementation → fake live probe → estimate → decision → trial/formal
  control → watchdog → artifacts. Propagation edges under test are
  NEVER mocked.

Layer 3 — bounded real-GPU validation
  the §24 campaign + concurrency subset (operator-gated).

Layer 4 — cold-start production smoke
  one bounded real run: real candidate implementation, real live probe,
  real estimator, real artifacts, no trajectory reuse. STILL NOT V19
  restart.

Layer 5 — V19 restart stop-and-show
  full report against §18; explicit operator authorization.
```

---

## 26. Cleanup and recovery handling (updated)

The forensic snapshot remains read-only. The verified incomplete
active-run relics may be removed only after: this revised design is
approved; the deletion inventory is re-checked; no calibration or
diagnostic dependency points into those paths; no process or queue
entry references them (executed in C13). The stopped workspaces are
never reused or sanitized. The restarted V19 run uses fresh workspace
names with no copied proposal context, interpretations, incumbents,
constraints, retry history, plugin state, run locks, or prompt cache —
and must be provably unable to discover the stopped attempt as a resume
candidate (§17-restart-contamination test in C13/C14).

---

## 27. Document changelog

- 2026-07-30: §15 audits completed with code/artifact evidence (F-1
  calibration-loop dormancy, F-2 template-mandated ceiling); commit
  ladder and multi-scale validation campaign added. (Claude, read-only
  incident audit; no production code changed.)
- 2026-07-30 (rev 2): §1.1 audit-status classification; in-section
  precision notes (§4.1 F-1 qualification; §5.3 actual k mechanics;
  §7.3 existing records.py vocabulary).
- 2026-07-30 (rev 3, operator directive): D1/D2/D6/D7/D8 RESOLVED;
  restart requires the COMPLETE architecture (§21 replaced); F-1 split
  into F-1a/F-1b; three-layer estimator model + decomposition (§6.1);
  §7.4 decision-policy matrix; §7.3 canonical-vocabulary mapping +
  naming rule; §10.2 versioned registry requirements; §10.3 update/
  contention policy + concurrency identities; §12 typed behavioral
  launch guard (no introspection) + run-invariant fields; §13.1
  candidate lifecycle + static-validation definition; §16.6/§16.7
  elevated to requirements (separate train/inference APIs, realized
  properties); §17.10 metadata-vs-executable replay split; §18 replaced
  with the 33 restart-blocking acceptance criteria; §23 ladder expanded
  C1-C14 (incl. C1 interim-API bridge rule, C10 bootstrap CLI, C13
  queue-runner respawn-defect fix); §24 pre-registered thresholds; §25
  five testing layers; §26 cleanup gating. Markdown fence defect in §1
  fixed.
- 2026-07-30 (rev 4, C1 inspection corrections): §15.1 false "Proposer
  VRAM pre-flight" row removed — no proposer-side VRAM gate exists; the
  enforcing VRAM control is tuner-side `evaluate_vram_skill`; §23-C1
  reworded accordingly (tuner VRAM gate out of scope and unchanged; the
  proposer VRAM revision test requirement removed); D2 placement
  decided by operator: VRAM authority begins only post-implementation
  (realized properties / deterministic accounting / measured peak);
  C4/C8 place VRAM blocking after implementation, never in the proposer
  loop.
