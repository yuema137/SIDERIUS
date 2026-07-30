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
| §20 decisions | D1/D2/D6/D7/D8 [RESOLVED — operator 2026-07-30]; D3/D4/D5 [OPEN, must resolve before the §24 campaign] |
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
D4 thresholds still open):

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

### D3. Contention threshold — OPEN (must be resolved before the §25 real-GPU campaign)

What telemetry thresholds define a contended probe?

### D4. Calibration update policy — OPEN (baseline policy in §21-policy below; thresholds must be resolved before the §25 campaign)

Which observations may update persistent calibration automatically?

### D5. Unknown model families — OPEN (must be resolved before the §25 real-GPU campaign)

When no similar history exists, should the system:

* run a generic bounded probe;
* run family-identification probes;
* use a broad conservative prior before probing?

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
- [ ] Inspect the template contract for the parameter-count-limit
      bullet's coupling to the VRAM gate; STOP AND ASK if removal
      breaks a validated expectation.
- [ ] §11.1 advisory wording verbatim (provenance, confidence, "do not
      infer a permanent parameter-count ceiling").
- [ ] Label every persisted runtime number with provenance+confidence.
- [ ] Doc sync + fixture updates.
**Unit validation.** Rendered prompts with/without advisory: label
present, ceiling-mandate absent; ProposalOutput schema unchanged.
**Pseudo integration.** §17.2 contamination guard end-to-end; mutation
check recorded (guard fails when label stripped).
**Acceptance.** (a) no template-mandated parameter ceiling (VRAM bullet
retained); (b) all runtime numbers to the LLM carry provenance +
confidence; (c) guard + mutation evidence recorded.
**Failure/edge.** Restored legacy contexts already containing ceilings
(out of scope — fresh workspaces only); legacy fixtures.
**Migration/rollback.** Template-text change; revert restores old text.
**Boundary.** Prompt/persistence only.
- [ ] Evidence recorded.

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
- [ ] Vocabulary reconciliation audit (records.py, total_assembly.py,
      provenance.py) → final single-source table here.
- [ ] Pydantic models; eligibility derivation function; validator
      rejects static+blocking.
- [ ] `evidence_rank()` per §8.4 (pure, total order).
- [ ] Adapters, tested against REAL forensic fixtures.
- [ ] Doc sync (§7 concrete field list).
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
- [ ] Evidence recorded.

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
- [ ] Inspect existing assembly (`total_assembly.py`, session,
      verifier) — the estimator must WRAP these, not duplicate.
- [ ] `RuntimeEstimateRequest` finalized against actual typed inputs.
- [ ] Factory (per-run identity, hardware profile handle, registry
      handle, policy handle).
- [ ] Decision policy = §7.4 matrix, table-driven + unit-proven cell by
      cell.
- [ ] Doc sync.
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
- [ ] Evidence recorded.

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
- [ ] Inspect O1a fields vs §9.1 list; extend collection.
- [ ] Registry schema (all §10.2 fields), atomic IO, hash identity.
- [ ] Compatibility checker (hardware/software/dtype/schema) — explicit
      verdicts, never silent reuse.
- [ ] Legacy k-table read-only adapter (extends the existing
      `to_legacy_prior_entries` seam).
- [ ] Doc sync.
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
- [ ] Evidence recorded.

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
- [ ] F-1a audit + single-source dataset resolution.
- [ ] F-1b: verified load of a newly implemented plugin in the probe
      process; realized parameter/trainable/dtype-memory recomputation.
- [ ] Bounded probe: setup timing, N warmup + M timed train steps,
      K timed inference batches (unit-explicit), peak VRAM, contention
      snapshot with §21-policy identity.
- [ ] Probe → `RuntimeEstimate` (provenance live-probe tier) → tuner
      context (C2-labeled) + persisted record.
- [ ] Doc sync (tuner `.md`, §8/§13).
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
- [ ] Evidence recorded.

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
- [ ] Update-eligibility enforcement (§10.3 table) at the single write
      seam.
- [ ] Uncertainty per component (empirical error distributions from
      history).
- [ ] Applicability labels + confidence/eligibility downgrade on
      unsupported extrapolation.
- [ ] Drift/staleness rules (software-stack identity comparison).
- [ ] Concurrency buckets (idle vs pairwise never cross-written).
- [ ] Doc sync.
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
- [ ] Evidence recorded.

### C8 — `refactor(runtime): wire proposer, tuner, admission, watchdog, and reporting to the shared estimator`

**Goal.** §2.3/§9-directive: every runtime consumer on the one
subsystem; private authoritative formulas removed (static producers
remain as typed priors inside the estimator).
**Scope/deps.** Proposer pre-flight → estimator (advisory per policy);
TimeEval → estimator; admission/watchdog → estimator-mediated evidence
(preserving RT2 measured semantics EXACTLY — characterization tests
first); reporting/provenance surfaces. Deps: C4-C7.
**Implementation plan.**
- [ ] Characterization suites capturing CURRENT admission/watchdog
      numeric behavior before rewiring (byte-parity requirement).
- [ ] Rewire consumer by consumer, each with its own parity proof.
- [ ] Remove/deprecate private formula call sites (grep-audited).
- [ ] Doc sync.
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
- [ ] Evidence recorded.

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
- [ ] Evidence recorded.

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
