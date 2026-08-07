# SIDERIUS V20 Pre-Launch Completion — Autonomous Execution Mandate

**Operator instruction, 2026-08-05. This supersedes the earlier "stop before
merging PR D" instruction.**

> **READ THIS DOCUMENT FIRST AFTER EVERY CONTEXT COMPACTION.**
> Before resuming any work following a compaction or session restart, read
> this file, then `before_end_memory.md`, then the active design document,
> then the V20 readiness report, then recent Git history, status, and the
> live diff. Reconstruct actual repository state from evidence. Never resume
> from a conversation summary alone.

## STATUS: CLOSED — 2026-08-07. This mandate is historical.

Both stopping rules were satisfied and the campaign has since been launched
three times. **The "Do not launch V20" instruction below is spent, not
active** — do not act on it, and do not re-derive a pre-launch readiness pass
from it.

```text
Part I  stopping rule met   V20 READY TO START at 53a71dca (2026-08-06)
Part II stopping rule met   M1-M8 closed, hardening merged as #181 (adbd435d)
launch attempt 1  d8e21d1a  ABORTED  planner crash            fixed by #183
launch attempt 2  0b9ec200  ABORTED  measurement-worker plugin fixed by #184
launch attempt 3  aea6d35e  STOPPED  operator_stop_requested 2026-08-07 06:37
```

Live campaign state, launch packages and per-attempt evidence live in
`reports/v20_20260806_{145351,165559,233242}/`; findings the campaign exposed
are recorded in `docs/design/v21_priorities.md`. Read those for current state.
This document remains authoritative only for the frozen production decisions
(§10) and the engineering principles (§2) that the campaign runs under.

---

## 0. Mandate

Continue autonomously until every condition needed to begin the real V20
campaign is complete and verified. Merging PR D and the runtime-control
follow-up is authorized through the repository's normal protected workflow.

Do not stop after intermediate phases. Do not pause to ask the operator to
choose among ordinary engineering alternatives. Audit actual code, tests,
artifacts, design documents and history; choose the smallest sound solution;
implement, validate, document, continue.

**Stop only when:**

1. the repository is fully ready to start V20, with all pre-launch conditions
   proven and recorded; or
2. the only remaining blocker is genuinely external and cannot be resolved
   through code, configuration, testing, available credentials, available
   hardware, or further investigation.

If an external blocker appears, complete all other productive work first and
report it only when nothing else useful remains.

---

## 1. Accepted state to verify (do not trust blindly)

```text
PR #173            PR D
frozen head        fc5722e4
exact-head CI      PASS
unit suite         7668 passed, 2 skipped, 4 xfailed
Gate 1             PASS
PR D integration   20 passed
transport audit    four chains closed
tracked commits after freeze: none
```

PR D establishes: valid-trial winner selection; `negative_infinity_bootstrap`;
first-valid-winner formal budget bypass; formal authority derived from the
formal record's own facts; diagnostic exclusion; persistence; resume
admission; aggregation admission; zero-valid-trial formal skip; blocking
HealthGate enforcement; strict JSON; declaration and provenance transport.

**PR D acceptance does not depend on a stochastic real-training result.**
Earlier real-training attempts are scientific observations only.

---

## 2. Immutable engineering principles

### 2.1 Audit actual reachability

Never infer behaviour from names, comments, schemas, AST substrings or
isolated producers. For every material property trace:

```text
producer -> typed schema/protocol -> transport -> persisted record
  -> artifact -> reload/resume -> real consumer -> final decision
```

Tests must fail if a required hop is deleted. Use real execution or typed
call-level tests for behavioural contracts; AST tests may supplement but never
be the sole proof of runtime compatibility.

### 2.2 Separate mechanism tests from scientific outcomes

Never use a stochastic scientific result as the pass/fail oracle for
infrastructure. Unacceptable acceptance conditions: whether a model trains
well, whether a candidate passes HealthGate, whether an LLM proposes something
compact, whether a score exceeds a threshold.

For deterministic control-flow acceptance: pseudo training, controlled trial
and formal outcomes, real production components owning the decisions, real LLM
calls only where the LLM-facing path is itself under test, and never
hand-injecting the authority verdict or aggregation decision.

Real training is reserved for V20 scientific evidence.

### 2.3 Minimum bounded validation

Use the minimum bounded workload sufficient to establish the property. Before
an expensive run write down: the exact property; why cheaper tests are
insufficient; the production path that must be reached; deterministic inputs;
phase-level limits; total wall-clock limit; cleanup; expected artifacts;
failure classification.

**A smaller policy budget does not necessarily make a test cheaper** —
runtime-control budgets can trigger additional probes. Distinguish configured
policy budgets, per-phase execution bounds, and the true outer timeout.

Never rerun a stochastic or poorly isolated harness until it turns green.

### 2.4 External GPU activity is context, not invalidity

External GPU activity must never by itself invalidate a measurement or stop
bootstrap from reaching measurement evaluation — whether it is registered,
unregistered, stable, variable, bursty, changing memory, or changing PID set.
It is observed and recorded as context and provenance.

**Validity is measurement integrity only**: candidate-owned process-tree
attribution correct; sampling complete and usable; device identity known and
consistent; telemetry supports the attribution; probe lifecycle completed;
interpretation invariants hold.

External change may indirectly expose a real attribution or telemetry
limitation — in that case validity is invalid **because attribution or
telemetry failed**, never because an external process existed or changed.

**Admission is separate**: candidate-attributed demand, current available
resources, configured safety margin, recorded external occupancy. A valid
measurement may be rejected for insufficient current resources.

**Registration is metadata only** — never required for correctness,
readiness, validity or admission.

### 2.5 Historical evidence

Historical records stay readable and are never rewritten, upgraded,
reconstructed or repaired. Missing authority means authority was not
established. Missing validity evidence means validity was not established. New
records use the corrected semantics.

### 2.6 Scope discipline

Prefer narrow typed corrections. Do not enlarge the tuner `run()`; do not do a
general DI-Protocol refactor here; do not redesign unrelated systems; do not
clean unrelated historical failures for directory greenness; do not tune tests
to the desired answer; do not register a test holder to bypass the
unregistered-workload property. The loosely typed seams are a separate
follow-up.

---

## 3. Autonomous decision policy

Classify before acting, then continue:

1. **Product defect in a required path** — root-cause, fix narrowly, add a
   regression test that detects the real failure mode, document, continue.
2. **Test/harness defect** — correct the harness, preserve the failed
   evidence, explain why it could not establish the property, never
   reinterpret a harness failure as a product failure.
3. **Pre-existing but in-scope** — fix if the required path depends on it;
   record its true origin.
4. **Pre-existing and unrelated** — establish against the correct historical
   baseline, record with evidence, do not silently exclude, do not let it
   block scoped work.
5. **External API behaviour unclear** — inspect the installed version and
   source first; consult primary documentation when useful; record the source
   and decision. Web search never substitutes for auditing the repository.
6. **Multiple viable options** — choose the smallest that satisfies the frozen
   semantics, preserves historical compatibility, is production-reachable, is
   deterministically testable, and does not enlarge scope. Record rejected
   alternatives. Ask the operator only when every option requires an external
   policy choice that cannot be inferred from these principles.

---

## 4. Execution phases

```text
verify and merge PR D
-> audit runtime-control production path
-> freeze corrected semantics in the design doc
-> implement narrow correction (checkpoints A-E)
-> deterministic validation
-> exact-head CI
-> real-GPU Case B1/B2
-> merge follow-up
-> audit merged main
-> freeze V20 production config
-> verify data, storage, GPU, services, recovery
-> produce exact launch package
-> publish final readiness record
```

### 4.1 Merge PR D

Verify `#173` still points at `fc5722e4` (or is merged), CI green, no tracked
commit changed the accepted head, PR body carries the acceptance ledger. Merge
via the normal strategy. Never bypass branch protection or force-push accepted
history. If blocked only by external review/permission, continue Phase 1 as a
stacked branch from the accepted head and rebase later.

Record the merge commit, resulting main SHA, tree cleanliness, and the
relationship to `fc5722e4`.

### 4.2 Branch

New branch from updated main, e.g. `v20-runtime-control-validity-separation`.
Do not reuse the PR D branch. Update `before_end_memory.md` with branch, base
SHA, PR D merge status, frozen semantics, remaining phases, stop condition.

### 4.3 Audit before editing

Trace the complete path:

```text
workflow launch -> runtime bootstrap -> device discovery
  -> external-process observation -> contention-window classification
  -> bootstrap readiness -> bounded probe
  -> candidate-owned process attribution -> MeasurementValidity
  -> admission -> persisted artifact -> downstream launch decision
  -> remedy text
```

Find every producer and consumer of `foreign_contended`,
`pairwise_expected_peer`, `classify_contention_window`, registered/unregistered
PID sets, external PID identity, external-memory observations, bootstrap
`ready`, bounded probe requests, `MeasurementValidity`, admission results,
runtime-control verdicts, remedy strings, serialization/reload paths, CLI and
workflow mapping, pseudo and real bootstrap injection seams, and the tests
claiming to prove these contracts.

**Audit the current `MeasurementValidity` specifically**: it currently treats
stable external identity as a validity requirement and a changing external PID
set as invalidating. That must be corrected.

Treat production code as the source of truth, above PR #175/#176/#177 intent.

### 4.4 Freeze corrected semantics (before implementing)

Update the owning design document — do not create a competing one. Separate:

* **external activity observation** — present/absent, registered and
  unregistered PIDs, observed PID-set change, external attributed-memory
  min/max/latest or nearest existing equivalent, and a descriptive marker
  (`absent` / `observed` / `stable` / `variable` / `unknown`). Descriptive
  only; never determines validity. Extend existing typed records narrowly
  rather than inventing a framework.
* **measurement validity** — integrity only, with the named failure vocabulary
  (attribution unavailable, process tree untrackable, device identity missing
  or inconsistent, samples incomplete or corrupted, telemetry cannot separate
  candidate usage, probe lifecycle incomplete, invariant failed). Never
  "external process exists / is unregistered / changed".
* **admission** — existing explicit policy and margins; `valid + admit` and
  `valid + reject_insufficient_current_resources` are both expected. No hidden
  external-stability gate. No registration requirement.
* **bootstrap readiness** — must not stop before MeasurementValidity because
  external activity is present, unregistered, variable, or churning. Preserve
  API compatibility while making typed reasons explicit.
* **remedy language** — must match the actual decision. Never instruct a user
  to stop other workloads merely because they exist.
* **registration** — provenance/labelling only; identical semantics to
  unregistered given the same facts.
* **historical compatibility** — old `foreign_contended` stays readable; new
  records do not emit it as a blocking presence verdict; no reconstruction.

Add a decision ledger: current behaviour, corrected behaviour, why the old
behaviour is wrong, alternatives considered, compatibility decisions, test
mapping, evidence mapping.

### 4.5 Implementation checkpoints

* **A — typed observation + compatibility.** Smallest typed structure to
  persist external activity independently of validity; historical
  deserialization preserved; registration as provenance; serialization and
  strict JSON; focused schema tests.
* **B — remove presence-based early refusal.** Remove/neutralize production
  early returns that make bootstrap unready solely due to an unregistered PID,
  varying external memory, or a changing PID set. Let the flow reach
  MeasurementValidity. Preserve genuine device/sampling/lifecycle/attribution
  failures. Replace dishonest remedy text.
* **C — correct MeasurementValidity.** Remove stability, registration,
  PID-constancy and presence requirements; derive validity from integrity;
  every invalid result names the real integrity failure; variable external
  activity can coexist with a valid measurement.
* **D — preserve admission separation.** Admission consumes candidate demand
  and current resources independently of validity; margins preserved; a valid
  measurement can be rejected for insufficient resources; external
  observations survive into artifacts and decision records.
* **E — reachability + documentation.** Launcher, bootstrap, bounded probe,
  artifact writer, reload path and user-facing output all consume the
  corrected fields; every affected design, node, agent, runtime, CLI, example
  and operator document updated; no doc left describing "stop the other
  workload" as a measurement requirement.

At every checkpoint: update the design doc and ledger, run the cheapest
focused tests, inspect the diff, commit a coherent milestone with
`SIDERIUS_GIT_APPROVED=1`. Never combine unrelated changes.

### 4.6 Required deterministic test matrix

1. no external workload; 2. stable unregistered; 3. variable-memory
unregistered; 4. external PID-set change; 5. registered expected peer
(provenance only); 6. valid measurement + insufficient current resources;
7. candidate-attribution failure; 8. sampling / device-identity / lifecycle
failure; 9. serialization and historical compatibility.

Do not require the whole historical integration directory to be green. Report
the configured CI scope plus the targeted runtime-control scope.

### 4.7 Mutation and reachability guards

Must fail if: the unregistered-PID early refusal returns; variability maps to
invalid; PID-set change maps to invalid; registration becomes required;
activity facts are produced but dropped before persistence; persisted facts are
ignored by the real consumer; admission rejection is mislabelled as
invalidity; resource insufficiency is ignored after a valid measurement; the
old "stop the other workload" remedy is emitted for mere presence; a test
double no longer accepts the real production call contract.

Prefer real execution and typed call-level tests.

### 4.8 Validation sequence

```text
focused schema/unit -> targeted bootstrap/runtime-control -> targeted
integration -> mutation/reachability -> pyright/static -> configured full unit
-> exact-head CI -> real-GPU Case B
```

Never call a suite "full" without stating its configured scope. Freeze the
candidate head only after all tracked documents are updated; after freezing,
create no tracked commits — if a tracked fix is required, establish a new
frozen SHA and rerun exact-head validation.

### 4.9 Revised real-GPU Case B

Only after focused validation and exact-head CI pass. No LLM, no training, no
pseudo training, no registered-peer bypass. Use `scripts/bg_gpu_holder.py` or
the current equivalent.

Record: exact SHA; device identity; pre-test GPU state; holder PID;
registration status; holder attributed memory; sample count and completeness;
candidate attribution status; external-activity observation; MeasurementValidity
and reason; admission result and separate reason; cleanup result; post-test GPU
state.

* **B1 stable unregistered** — bootstrap does not refuse on presence; probe
  completes; attribution trustworthy; validity VALID; admission evaluated
  separately (admit or reject both acceptable). ~10 min bound.
* **B2 variable unregistered** — variability recorded; no
  variability-based refusal; attribution and sampling remain trustworthy;
  validity VALID; admission separate. PID-set constancy NOT required.
  ~10 min bound.
* **B3 optional** — valid measurement with resource rejection, only if cheap
  and safe.

Always terminate holders, confirm no child remains, confirm the GPU returns to
baseline, record cleanup evidence. A failed Case B is evidence — never tune
registration, workload identity or semantics to force green. A genuine product
defect is fixed narrowly, a new exact head is established, focused validation
and CI rerun, and only the minimum real-GPU case rerun.

### 4.10 Merge the follow-up

When frozen semantics are implemented; focused, targeted-integration,
mutation/reachability and configured unit suites pass; exact-head CI passes;
B1 and B2 pass; evidence and documentation are complete; and no in-scope
product defect remains — open/update the PR with problem statement, corrected
semantics, implementation summary, compatibility statement, test results,
real-GPU evidence, exact SHA, explicit non-goals and known unrelated failures;
review the diff against base; merge normally. This mandate authorizes that
merge.

### 4.11 Final V20 pre-launch audit

On the merged main head, audit from actual code and configuration:

* **repository state** — main current, tree clean, no required PR unmerged,
  final SHA recorded, CI green, unit suite green, V20-relevant integration
  green, unrelated failures listed and classified;
* **formal-authority readiness** — declarations required; `blocking +
  scientific`; `observe_only + scientific` refused; winner selection;
  zero-valid-trial skip; `negative_infinity_bootstrap`; first-winner bypass;
  authority from record facts; diagnostic exclusion at resume and aggregation;
  strict JSON; no historical upgrade. Prove deterministically — do not rerun
  real training;
* **runtime-control readiness** — presence does not prevent evaluation;
  registration is metadata; variability and PID change recorded but not
  invalidity; validity is integrity; admission separate; honest resource
  reason; Case B evidence matches merged code;
* **V20 production configuration** — task and forward contract; LLM config;
  full agent path; HealthGate mode; result authority; gate settings; iteration
  count; max rounds; proposal attempts; epochs; trial/train/eval portions;
  trial and formal time budgets; outer timeout/supervision; device identity;
  runtime-control policy; workspace; resume policy; artifact and logging
  paths; disk requirements; dataset identity and access; registry state;
  cleanup. **Specifically confirm** the validation workload ceiling is
  DISABLED unless explicitly intended, production data portions are used,
  fixed validation plans are disabled, pseudo training is disabled, pseudo LLM
  is disabled, the normal proposer path is active, real blocking HealthGate is
  active, and scientific authority declarations are active. Never silently
  carry validation values into the scientific campaign;
* **data and storage** — dataset paths exist; permissions correct; identity or
  checksums recorded where supported; no stale workspace or validation subset;
  output paths fresh or resume-safe; sufficient disk; logs survive failure;
  cleanup understood. Cheap metadata checks before full indexing;
* **GPU and system** — correct device identity; attribution works; occupancy
  recorded as context; available memory and margin sufficient; external
  workloads do not invalidate; admission result recorded; no stale holder;
  CPU/RAM/disk/FD sane; supervision and termination known. A resource
  rejection is legitimate — resolve real insufficiency, but never require an
  otherwise shared GPU to be empty;
* **LLM and services** — credentials available without exposure; model names
  resolve; APIs respond; rate/quota assumptions recorded; literature/search
  dependencies available; failure behaviour understood. Real calls only where
  the live path must be verified;
* **launch package** — exact SHA; config paths and hashes; exact command;
  workspace; environment activation and variables; monitoring commands;
  artifact locations; graceful stop; crash recovery; resume command; rollback
  and cleanup; first-hour checklist; immediate-abort conditions. Cheap syntax,
  config-parse and dry-run checks only. **Do not execute the campaign.**

---

## 5. Final readiness record

Update the existing V20 prerequisite/readiness document; do not create
competing reports. Correct stale sections. Distinguish historical evidence,
PR D deterministic evidence, runtime-control evidence, real-GPU Case B
evidence, scientific claims NOT established, launch prerequisites, final
configuration, remaining risks, explicit non-blockers, final main SHA.

Required final conclusion format:

```text
PR D merged                        PASS
Runtime-control correction merged  PASS
Exact merged-main CI               PASS
Configured unit suite              PASS
V20-relevant integration           PASS
Formal-authority mechanism         ESTABLISHED
External-activity semantics        ESTABLISHED
Real-GPU Case B1                   PASS
Real-GPU Case B2                   PASS
Dataset and storage readiness      PASS
LLM/service readiness              PASS
GPU/resource admission             PASS
Launch configuration frozen        PASS
Launch command dry-run             PASS
Working tree                       CLEAN

V20 READY TO START
```

**Never claim V20 can beat FCNet or that a real model will pass HealthGate.**
Those are scientific outcomes for the campaign to establish.

---

## 6. Documentation and evidence discipline

**Tracked**: audited call graph; observed behaviour; frozen semantics;
decisions; rejected alternatives; compatibility decisions; test mapping; real
failures and root causes; corrections and retractions; commit checkpoints;
evidence summary. Record continuously — never reconstruct at the end. Tick a
checkbox only when the property is actually established.

**Machine evidence**: `.claude/gate2_evidence/` or the runtime-control
equivalent, with hashes and summaries referenced from tracked docs or PR
comments. Never commit large transient artifacts. Never expose secrets. After
a final head is frozen, use PR comments and ignored evidence only.

---

## 7. Context-limit continuity

Monitor context usage continuously. By ~90-95% usage, update
`before_end_memory.md`; by 95% it must be complete.

It must contain: immutable principles; current goal and final stop condition;
branch; exact base and head SHAs; tree status; merged and open PRs; completed
checkpoints; design-document paths; implementation decisions; rejected
alternatives; failures, root causes and retractions; exact test results;
evidence paths; commands already run; external processes running; cleanup
obligations; remaining tasks in order; the exact next action; any true
external blockers.

**After compaction or restart, read in this order before acting:**

1. **this document**;
2. `before_end_memory.md`;
3. the active design document;
4. the V20 prerequisite/readiness document;
5. recent Git history;
6. current Git status;
7. the active diff;
8. relevant code and tests.

Reconstruct actual repository state, then resume from the next incomplete
property. Never ask the operator to restate prior context. Repeat across as
many compactions as necessary.

---

## 8. Final stopping rule

Do not stop for routine status updates. Do not stop merely because a test
failed, a harness assumption was wrong, a pre-existing regression appeared, a
seam was mismatched, a design needs correction, a real-GPU case exposed a
defect, or context compaction occurred. Audit, correct, validate, document,
continue.

Stop only when the final report truthfully states **`V20 READY TO START`** and
the campaign has not been launched. Then report: final main SHA; merged PRs;
validation summary; Case B evidence; final launch command; artifact and
monitoring paths; remaining scientific uncertainties; and an explicit statement
that the repository is ready for the operator to begin V20.

---

# Part II — Final V20 Pre-Launch Hardening Mandate

**Operator mandate, 2026-08-06, issued after the independent launch audit of
`53a71dca9b272bafc748f1560530196f523ddb28`.** Part II supersedes Part I's
stopping rule: the repository reached `V20 READY WITH NON-BLOCKING RISKS`, and
the operator ruled that the eight audit findings are to be closed *before*
launch rather than accepted.

**Read this whole document (Parts I and II) first after every compaction.**
The §7 read order applies unchanged, with this Part now the active mandate.

## 9. Scope and stopping rule

This is the **final pre-launch engineering pass**. It is deliberately narrow.

* Close audit findings **M1–M8** and nothing else.
* Do **not** reopen general architecture work.
* Do **not** launch V20.
* Do **not** begin a fourth audit round after this one closes.

Work autonomously until the hardening PR is implemented and merged, the final
V20 launch configuration is frozen and revalidated on the merged head, and the
final report truthfully states **`V20 READY TO START`**.

Do not stop for routine design choices. Audit the actual code path, choose the
smallest production-safe implementation, record the decision in the V20
design/readiness documents, validate the semantic checkpoint, continue.

## 10. Frozen production decisions

These are operator decisions. Implement them; do not re-derive them.

### 10.1 LLM

Every formal/official SIDERIUS production campaign must **explicitly** pass:

```text
--llm_config llm_configs/openai_tiered_pro.json
```

Never rely on the parser default. The audit proved the bare command falls
through to `gemini-3.1-pro-preview` for all five nodes.

### 10.2 Scientific policy

```text
healthgate_mode                        = blocking
result_authority                       = scientific
chain-incumbent formal gates           = enabled
cross-iteration authoritative incumbent= enabled
file-sequence training                 = enabled
skip_formal_min_delta                  = -1.0
bypass_formal_time_budget_min_delta    = +0.5
```

The incumbent must be the best **authoritative scientific formal** result —
never a trial, never a diagnostic record. The no-incumbent bootstrap remains
`-inf` and must bypass the formal time-budget policy regardless of the `+0.5`
threshold.

**The `+0.5` bypass may bypass the formal time-budget decision and nothing
else.** It must never bypass HealthGate, authority checks, watchdogs,
VRAM/resource safety, measurement validity, or admission.

### 10.3 Runtime safety posture (inherited from V19)

```text
trial_time_budget_minutes              = 20
formal_time_budget_minutes             = 120
runtime_watchdog                       = ON
runtime_safety_factor                  = 1.5
runtime_trial_safety_factor            = 3.0
runtime_formal_safety_factor           = 2.25
runtime_watchdog_safety_factor         = 3.5
runtime_watchdog_floor_seconds         = 120
trial_vram_budget_gb                   = 12
formal_vram_budget_gb                  = 12
```

These are **operational safety controls, not scientific pass/fail criteria**.

### 10.4 Production workload

```text
trial_portion / train_portion / eval_portion = 0.1 / 0.1 / 0.1
formal_portion                               = 0.1
formal_train_portion                         = 1.0
formal_eval_portion                          = 1.0
formal_round_strategy                        = full_clone
```

Audit the actual V19 manifest/config and perform a parameter-by-parameter
parity comparison before freezing these.

### 10.5 Validation-only features must be absent

```text
pseudo LLM                   OFF
pseudo training              OFF
fixed validation candidate   OFF
validation workload ceiling  OFF
validation-only data overrides OFF
```

## 11. The eight findings

### M1 — runtime safety belongs to the launch posture, not to operator memory

The official V20 production launcher must carry §10.3 itself. Audit the
existing wrappers/configuration and implement the smallest
**repository-controlled** way to do it. Do not move scientific policy into
unrelated runtime internals. Verify every flag reaches its real production
consumer and is persisted in effective configuration/provenance.

### M2 — persistent campaign logging

The official launch mechanism must create a disconnect-safe persistent log.
Use the smallest existing mechanism — preferably the established
`screen -L -Logfile` posture. Do not redesign logging, and do not put logging
into the core scientific runtime. Verify: the log exists immediately after
launch; stdout and stderr are retained; monitoring documentation points at the
real file; a disconnect does not terminate the campaign. **Do not launch the
scientific campaign during acceptance.**

### M3 — recovery documentation

Replace every stale `--start_iteration` instruction with the real
`--start_iter`. Audit every V20 recovery example and verify auto-resume and
explicit-start against the actual CLI parser.

### M4 — production provider

Freeze the official launcher to pass `--llm_config
llm_configs/openai_tiered_pro.json` explicitly. Verify by dry-run that the
effective config is the pro tier and no Gemini/default fallback occurs. Use the
minimum bounded real API call needed to verify authentication and parsing.

### M5 — resource admission must be real in production

The frozen semantics are:

```text
external activity                          -> observation / provenance
measurement integrity                      -> MeasurementValidity
current resources + demand + safety policy -> Admission
```

Registration, external-process presence, variability, burstiness and PID churn
must **never** directly block execution. But once a **valid** measurement
produces an actual admission rejection for insufficient current resources,
production execution must not continue:

```text
MeasurementValidity = valid
+ Admission = rejected_insufficient_current_resources
-> candidate execution is NOT launched
```

Persist the structured reason. Do not reinterpret a resource rejection as
measurement invalidity. **Do not require an empty GPU.** Registered and
unregistered external workloads must remain semantically equivalent for both
validity and admission given identical measured facts. Add deterministic tests
and the minimum real-GPU evidence needed to prove it.

### M6 — a required probe that is unavailable must not fail open

Current unacceptable behaviour on the production path:

```text
REQUEST_PROBE -> production probe unavailable -> proceed using prior
```

For a production scientific run, if the decision requires a probe and the
production probe cannot be resolved or executed, that candidate/formal
execution must not launch. Use the smallest existing structured outcome that
honestly represents *required measurement evidence not established / probe
unavailable / execution not admitted*.

**Fail closed for that expensive execution — not necessarily for the whole
chain process.** Do not crash the campaign unless existing invariant semantics
require it. Persist the reason so resume and diagnostics can distinguish it
from a resource rejection, a HealthGate invalidity and a scientific failure.
Add a mutation/regression test that fails if `probe unavailable -> proceed`
returns.

### M7 — repair the final readiness document

Remove the stale claims that PR D is unmerged and that Case A/B are pending.
Make the document internally consistent **without** a top disclaimer telling
readers to ignore later sections. Preserve historical evidence as historical
evidence.

### M8 — correct the dataset inventory

Correct `422 H5 files` to the true source inventory. Audit the exact
source-file resolver and record the real number of production input files.
`abra_validation_denoised_*` are historical output artifacts, not source data,
and the resolver does not ingest them — the audit verified this. Use cheap
filesystem/config inspection; do not index the whole dataset.

## 12. Three required audits

### 12.1 File-sequence training

A new V20 production feature that must be **explicitly enabled**. Do not guess
the flag name. Trace: launch config -> typed runtime config -> trial training
-> formal training -> actual file ordering -> persisted
`ExperimentRecord`/provenance -> resume behaviour. Verify whether both trial
and formal training are intended to use the file sequence, and that
interruption/resume does not silently restart or alter the scientific sequence.
Use deterministic/pseudo tests — **never a stochastic training outcome as the
oracle**.

### 12.2 Cross-iteration incumbent

Trace: formal authoritative record -> artifact -> reload -> incumbent
restoration -> next-iteration delta -> skip/normal/bypass decision. Require
that diagnostic records, invalid records, trials and historical records without
established authority are all excluded; that resume restores the same
incumbent; and that `-inf` is used only when no authoritative incumbent exists.

Test the exact thresholds and confirm the inclusive/exclusive comparisons in
code match the documented policy:

```text
delta <= -1.0          skip formal (frozen boundary semantics)
-1.0 < delta < +0.5    normal formal policy
delta >= +0.5          bypass the formal TIME-BUDGET decision only
no incumbent           bootstrap bypass
```

### 12.3 V19 -> V20 launch parity

Compare the actual V19 production launch manifest/command/config against the
final V20 configuration. Produce a table of **every** differing parameter, each
classified as exactly one of:

1. intentional V20 feature;
2. deliberate production correction/hardening;
3. inherited V19 value represented differently.

**Any unexplained fourth category is a blocker until understood.** Cover: LLM
config; portions; iteration/round/attempt limits; epochs; time budgets; VRAM
budgets; watchdog controls; file-sequence behaviour; cross-iteration incumbent;
HealthGate mode; result authority; formal gates; formal delta thresholds;
resume; cleanup; output paths; logging; validation-only flags.

## 13. Validation ladder

Minimum bounded validation, in order:

```text
focused unit tests
  -> targeted integration tests
  -> mutation / reachability tests
  -> static and type checks
  -> configured full unit suite
  -> exact-head CI
  -> only the real-GPU cases needed for M5 and M6
  -> production launch dry-run
  -> final V19/V20 parity check
```

Do not run real scientific training. If a tracked fix is required after the
head is frozen, create a new frozen SHA and rerun exact-head acceptance.

After acceptance, merge through the normal repository workflow, audit the
merged main, and regenerate the exact production launch command.

## 14. Part II stopping rule

Stop only when the final report states **`V20 READY TO START`** and includes:
final main SHA; the merged hardening PR; the exact LLM config; the exact
scientific and runtime parameters; the M1-M8 disposition; the exact launch
command; the logfile path; the recovery command; first-hour monitoring and
abort rules; the V19->V20 parameter diff; and confirmation that no
pseudo/validation posture is active.

**Do not launch V20.**
