# Step 11 — Execution Infrastructure (spawn, IPC, limits)

## 0. Status

**STEP 11 REV 2 — DESIGN SEMANTICS APPROVED (operator, 2026-08-21).
PENDING THE 07c PREREQUISITE AND POST-07c RECONCILIATION.
DO NOT FREEZE YET. Implementation MUST NOT start.**

This is no longer "the design is unsettled". The semantics are approved;
what remains is waiting for 07c to change the shared substrate, then
re-anchoring against the resulting master and freezing as Revision 3.

Revision 2 answers the operator's rev-1 review (2026-08-21): Q-11-1 and
Q-11-2 are RULED, every implementation-time `Decide` is promoted to a
numbered ruling **R-11-1 … R-11-11**, the three gaps the rev-1 commit plan
did not own (resolved-scope transport, scoring metric derivation,
deliverable-naming ownership) now have commits, and the argv-parity
contradiction is reconciled explicitly.

| field | value |
|---|---|
| roadmap contract | `siderius_generic_framework_upgrade.md` §9 (§9.1 couplings, §9.2 target, §9.3 compatibility), completion-matrix row "§9 Execution infrastructure" |
| source anchor | audited at **`a88aad9b`**. **STALE FOR FREEZE — master is already ahead, and Q-11-2 requires 07c to land first. The anchor MUST be refreshed and a bounded re-audit run before freeze (R-11-0).** |
| prerequisite status | Steps 00–06, 07a/07b/07d, 08, 09, 09.5, 09.5a, 10 **COMPLETE**. **§7e (07c) NOT STARTED — see Q-11-2** |
| open operator questions | **0.** Q-11-1, Q-11-2 and Q-11-3 are all RULED by the operator (§4). Rev 3 must re-confirm zero after the post-07c re-audit. |
| PR decomposition | **ONE PR** (see §6) |
| Gate disposition | Gate 2 **REQUIRED**, 1 iteration x 1 round. Gate 1 **NOT REQUIRED** — Q-11-3 = A ruled by the operator; source-checked, not assumed (§8) |

This document is the parent design AND the PR document — one PR, one doc,
per the kickoff protocol. Per-commit checklists in §7 follow the operator's
8-section standard and start **all `[ ]`**; no item is checked and no
evidence line is filled until the work has actually run.

---

## 1. Capability / final effect

**A task's process execution is bound from its composition, not from
TIDMAD's import-time constants.**

Concretely, after Step 11 the sandbox spawn surface carries no task
identity of its own: the physical data root, the deliverable naming
template and the training scope reach a child because the RUN declared
them, and the per-role resource ceilings are declared values with recorded
provenance rather than undocumented module constants.

**What this step does NOT claim** — see Q-11-1. Under the recommended
disposition it does not claim that a contrast task really executes as a
subprocess; it claims the surface no longer PREVENTS one.

---

## 2. The binding contract (quoted from the roadmap)

§9.2 target: *"data dir wiring flows from §4; the cleanup globs' TEMPLATE
flows from the Deliverable Contract (§3.1/§14 — §9 is a READER of that
contract), §4 supplying only input-identity indexing; per-role resource
ceilings become explicit calibration config with recorded provenance (NOT
task config); the rest stays framework."*

§9.3 compatibility: *"argv/IPC/sentinels byte-identical; per-role rlimits
resolve to the SAME VALUES for the TIDMAD profile — and any calibration
config must define its precedence against the EXISTING override seam
(`SIDERIUS_SUBPROCESS_RSS_GB` wins over `_ROLE_DEFAULT_RSS_GB`; finding 14:
a third layer with unstated ordering is not acceptable); kill/cleanup
semantics untouched (operator-stop-critical plain-vs-session launch split
preserved)."*

§9.2 also names one **UNKNOWN** the detailed design must resolve: whether
the probe worker's missing-`env` asymmetry is deliberate. **§3.3 resolves
it: it is a latent defect, not a choice.**

Completion-matrix acceptance: *"argv/IPC/sentinels byte-identical;
contrast tasks spawn with zero infra edits (L2/L3 as available)"*.

**Both clauses are AMENDED, not merely quoted.** The first is reconciled
per-mode by **R-11-1** (legacy byte-identical; composed argv may gain
additive declared arguments — that transport is the mechanism being
introduced). The second was unsatisfiable under current CAP-SCOPE
maturity, and **Q-11-1 / R-11-2 supply the bounded corrected Step-11
acceptance**: the boundary must TRANSPORT a resolved scope, not CONSTRUCT
one. Neither is an open blocker.

---

## 3. Source audit (three parallel read-only audits at `a88aad9b`)

Every anchor below was re-verified by the design author against source, not
accepted on report. Line numbers are as of `a88aad9b`.

### 3.1 The genericity gap is narrower, and lower, than §9 assumes

§9 frames this step as "data dir wiring + calibration". The audit shows the
real blocker is **the argv boundary**: two composed values never cross it.

| composed value | crosses to child? | anchor |
|---|---|---|
| task data path **id** | **yes** (the only one) | `sandbox_executor.py:839-862` `_task_data_path_argv()`, emitted only when a composition is bound |
| dataset profile | yes (content) | `--dataset_profile_json` |
| model-io contract | yes (content, conditional) | `--model_io_json` |
| **physical data root** | **NO** | training argv `sandbox_executor.py:1401-1421` and inference argv `:1752-1778` pass no `--data_dir`; children default to `TIDMAD_DATA_DIR` (`train_engine_sandbox.py:1920-1923`, `inference_single.py:436-439`) |
| **training scope** | **NO** | `run_experiment_streaming` accepts `task_scope`, but `main()` never passes it (`train_engine_sandbox.py:1989-2006`), so `:1124-1125` builds `TidmadScope` unconditionally |
| primary / secondary metric | **NO** | the scoring child re-derives TIDMAD's metric unconditionally: `denoising_score_single.py:195` |

`RunTaskComposition` has **zero** data-directory fields and
`_MANIFEST_KEYS` (`workflows/task_composition.py:93-103`) has no
data-directory and no `deliverable:` section.

**Consequence, verified:** `dirs["data"] = _tidmad_data_dir()`
(`sandbox_executor.py:1136`); `TidmadSandbox.__init__` (`:1089-1102`) has
no parameter for it; the tuner's construction site supplies none. That
value is passed as `raw_data_dir=` into **every** metric evaluation
(`:2007`), including a composed run's.

**The whole spawn surface has only ever been executed by TIDMAD.** Pets and
DAVIS reach the trainer **in-process** — `scripts/run_pets_gate2.py:122,185`
calls `run_experiment_streaming(task_scope=PetsScope(...))` directly. No
non-TIDMAD task has ever crossed the spawn, sentinel or cleanup boundary.

### 3.2 Resource calibration is undeclared and self-inconsistent

`_ROLE_DEFAULT_RSS_GB = {"training": 40, "inference": 60, "scoring": 24}`
(`sandbox_executor.py:135-139`); resolution `_subprocess_rss_gb(role: str)`
at `:142-173`. The full ladder is two layers: the global env var
`SIDERIUS_SUBPROCESS_RSS_GB` (`:166-173`), then the role default.

* **No machine-readable provenance.** A bare `dict[str, int]`; no schema,
  no config file, no CLI flag. `core/run_invariants.py` carries no memory
  term, so **a run does not record which ceilings it executed under.**
* **Task-shaped derivation, task-blind application.** The justifying
  arithmetic is explicitly TIDMAD (`:123-133`), but the function takes only
  a role string. A composed Pets/DAVIS chain inherits TIDMAD's 60 GiB
  inference headroom, because `TidmadSandbox` is constructed
  unconditionally (`ml_hyperparameter_tune_agent.py:419,746`).
* **Two unreconciled mechanisms.** Sandbox children get `RLIMIT_AS`; probe
  workers get a parent tree-RSS watchdog, with a *measured* rationale for
  rejecting `RLIMIT_AS` (`preflight_worker_main.py:11-24`). Both cannot be
  right for the same host.
* **The D14 runners have NO ceiling at all** — in-process, so no
  `RLIMIT_AS` applies (`run_pets_gate2.py:122,162`).

### 3.3 Three defects found, none of them genericity work

**F-11-1 — `oom_host_ram` is produced and never consumed.** Set at
`sandbox_executor.py:1654` (training), `:1923` (inference), `:2116`
(scoring). Verified: every other occurrence repo-wide is the message text
or a comment. The tuner branches only on `status == "error"`
(`execution.py:711,882`), so a host-OOM training failure falls through as a
normal outcome and its classification is lost. The tag-selecting matcher
`_is_cuda_oom` (`records.py:205-207`) is device-OOM-only and
case-sensitive, so no `_oom` status tag is ever produced for a host OOM.

**F-11-2 — a production spawner is missing `env=`.** Verified side by side:

```text
isolated_probe.py:482-487        Popen(argv, stdout, stderr, start_new_session=True)      # no env=
gpu_measurement_runner.py:279-285 Popen(..., start_new_session=True,
                                        env=subprocess_env(plugin_dir=..., loss_dir=...))
```

The child therefore inherits the tuner's own environ, which carries no
`SIDERIUS_PLUGIN_DIRS`, and falls back to the legacy global
`agent_generated/models/` instead of the run-scoped plugin dir. This is the
PR #184 failure shape, one directory along, and it is **production
reachable**: `execution.py:230` → `preflight_adapter.py:215`
(`run_production_preflight`) on the tuner's per-attempt path.
`probe_subprocess.py:336-341` has the same omission but is production
UNREACHABLE (only `scripts/runtime_campaign.py`).

*Why the existing guard missed it*: `test_measurement_worker_plugin_transport.py:161-175`
asserts `"env=subprocess_env("` appears **in one file, by path**. Same
**F-P2b-4** shape recorded in Step 10 — a census that is green for the
wrong reason.

**F-11-3 — the 60 GiB calibration cites code that no longer exists.** The
comment at `sandbox_executor.py:123-133` justifies the ceiling by "four
~1.86 GiB int8 numpy arrays at `inference_single.py:325-331`". Verified:
`:325-331` is now argmax/trace code. The dtype is task-declared
(`_storage_dtype`, `:389`) and the four-array peak applies only to
baseline/`fix` mode (`:1005-1013`), because agent-mode writes go through
the D14 seam. **The arithmetic no longer describes the path it governs.**

### 3.4 Smaller, verified findings

| id | finding | anchor |
|---|---|---|
| F-11-4 | `cached_models` / `records` are independent string literals in parent and child with no shared authority and no parity test; sentinel and checkpoint reads depend on the match | `sandbox_executor.py:1134-1135` vs `train_engine_sandbox.py:1928-1929`; the in-file precedent is `get_plugin_dir`/`get_loss_dir` (`:1152,:1161`) |
| F-11-5 | `core/resume.py:1483` hardcodes `list(range(TIDMAD.num_files))` — the only TIDMAD token in a 1,772-line file — while the sibling call site `model_exploration.py:1857` is already composition-aware | `resume.py:57,1483` |
| F-11-6 | `validate_stamped_invariants` validates three keys and never `task_composition_fingerprint`, though `_CANONICAL` includes it for the workspace lock. A cross-composition seed can pass ingress | `run_invariants.py:461-519` vs `:142-154` |
| F-11-7 | Relative script paths + `cwd=os.getcwd()` for all three children; no `SIDERIUS_ROOT` anchor in this module, while every peer module has one | `sandbox_executor.py:1403,1754,2071` |
| F-11-8 | `core/sandbox_executor.py` is **not** in `_DATA_PATH_SURFACE`, so the spawn parent's task identity (`TidmadSandbox`, `_tidmad_data_dir`, `"tidmad_db"`) is uncensused | `test_task_data_path_census.py:52-60` |
| F-11-9 | Five independent OOM matchers with different vocabularies | `sandbox_executor.py:205`; `failure_attribution.py:71`; `probe.py:320-340`; `probe_budgets.py:245-275`; `records.py:205-207` |
| F-11-10 | Device index 0 hardcoded in four production sites; no operator flag anywhere in production | `hardware_context.py:355,358-362`; `inference_single.py:65`; `probe_production.py:150` |
| F-11-11 | CI resolves the data root from the tracked TEMPLATE (`/path/to/TIDMAD/`); `.github/workflows/ci.yml` never creates a real config, and `data_paths.py` binds at IMPORT | `data_paths.py:20-60` |

### 3.5 What must NOT move (verified invariants)

* **The plain-vs-session launch split** (`sandbox_executor.py:903-911,
  921-943, 971-982`). A child in its own session does not receive a
  terminal SIGINT; a child in the caller's group does. **Correction the
  design records**: the docstring justifies this with `timeout --signal=INT`,
  and no launcher uses `timeout`. The real anchor is `run_chain.sh:171`
  (foreground child in the caller's process group) plus the
  `_chain_common.sh:755-759` trap. **Fix the stated reason, never the
  behaviour.**
* `core/subprocess_env.py` — **zero** task-identity hits. Genuinely
  framework-shaped; leave it alone.
* The W3 built-ins bootstrap in the three children is legitimate and
  guard-pinned; out-of-tree plugin availability is Step 12's.

---

## 4. Rulings and remaining questions

### Q-11-1 — RULED: **A, with the transport/construction correction**

Operator ruling, 2026-08-21:

> Step 11 does not implement task-owned scope construction or claim real
> Pets/DAVIS subprocess execution. It DOES make the execution boundary
> task-neutral enough to **transport an already-resolved task execution
> scope/binding when supplied**. CAP-SCOPE remains responsible for
> CONSTRUCTING such a scope for arbitrary contrast tasks and for real
> contrast-loop L4 execution.

The distinction is the whole ruling:

```text
CAP-SCOPE   "how do I BUILD a correct scope for an arbitrary task?"   -> deferred
Step 11     "if a resolved scope is HANDED to me, can the subprocess
             boundary transport / reconstruct / consume it?"          -> owned here
```

**Rev-1 defect this closes**: rev 1's §1 and Option A both claimed scope
"CAN cross argv" while **no commit implemented scope transport** — C4 did
the data root, C5 did naming, and nothing owned the scope. Rev 2 gives it
an owner (**C5**) and keeps the claim; the alternative the operator allowed
— deleting the claim — is NOT taken, because §3.1 shows the scope gap is
the reason the surface is TIDMAD-only.

### Q-11-2 — RULED: **07c FIRST**

> Implement/merge 07c, then re-anchor and reconcile Step 11 before freeze.

07c (`pr_07c_tuner_measurement.md`) is FROZEN Revision 3, operator-approved
2026-08-17, Q-07c-1…9 closed, Gate 2 REQUIRED, never implemented; it edits
`sandbox_executor.py:446-481`, `:944-953`, `:952-953` — the timing and
resource paths Step 11 restructures. Sequence:

```text
07c -> merge -> refresh Step-11 source anchor -> bounded re-audit
    -> update this design -> operator freeze -> Step-11 implementation
```

### Q-11-3 — RULED: **A** (operator, 2026-08-21)

**Source-checked, not assumed.** The planner's OOM note is gated on
`str(r.get("status", "")).endswith("_oom")` (`agent/prompts.py:1265-1270`).
`"oom_host_ram"` ends in `_ram`, so it does **not** match today — a host
OOM renders no planner bytes at all.

| option | C2 does | LLM-facing? | Gate 1 |
|---|---|---|---|
| **A (recommended)** | make the host OOM visible to the TUNER only, without producing an `_oom`-suffixed status | no prompt byte changes | **NOT REQUIRED** |
| B | route host OOM into an `_oom` status so the "NOT ATTRIBUTED" note also covers it | the note newly renders for host-OOM attempts | **REQUIRED** |

**Operator ruling — A.** Host-RAM OOM enters the tuner's structured
runtime/resource failure handling and **does not change planner-facing
prompt bytes**. **Gate 1 NOT REQUIRED.**

> Step 11's failure class is execution infrastructure, not planner
> feedback. Fixing a producer/consumer runtime bug is not a reason to
> change what the LLM sees.

B is arguably better science — a host-RAM ceiling genuinely is *not*
evidence about model capacity, which is exactly what that note protects
against — and is recorded as **named debt, explicitly NOT Step 11's**.
C2's prompt-byte parity test is what pins this boundary.

---

## 4a. Rulings (R-11-x) — every rev-1 `Decide` is resolved here

Rev 1 left eleven semantic decisions as implementation-time `Decide`
items. Each would have changed schema, compatibility, resume, failure
semantics or operator behaviour, so each is promoted to a ruling. **A
frozen design contains no `Decide`.**

**R-11-0 — freeze prerequisites.** This document may not be frozen until
(a) 07c has merged, (b) the source anchor is refreshed to the resulting
master, and (c) a bounded re-audit re-verifies every §3 anchor. Line
numbers in §3 are `a88aad9b` and WILL move.

**R-11-1 — argv parity, reconciled.** §9.3's "argv/IPC/sentinels
byte-identical" and Step 11's job of transporting new declared values are
only compatible when stated per-mode:

| mode | contract |
|---|---|
| legacy / un-composed TIDMAD | argv **byte-identical**, proven against the C0 census |
| IPC / sentinels / cleanup semantics | **unchanged in every mode** |
| composed run | argv MAY gain **additive, declared** binding arguments — that is the mechanism being introduced |
| composed TIDMAD | runtime and scientific behaviour **parity required**; literal argv byte-identity is NOT required, because the new transport is the point |

The existing `--task_data_path_id` is the precedent: emitted only when a
composition is bound, so legacy argv is already untouched.

**R-11-2 — transport, never construction.** Step 11 may serialize,
transport and reconstruct a resolved binding. It may not construct a
task's scope, derive a task's semantics, or infer identity from a name.

**R-11-3 — the Deliverable Contract remains the naming owner.** The
composition carries a **resolved declaration/reference**; it does not
become a second naming authority.

```text
DeliverableSpec / Deliverable Contract   <- owns the naming rule
        |
        v
resolved run binding / composition carrier   <- carries the resolved value
        |
        v
Step 11 spawn / cleanup consumer             <- READER only
```

Rev-1's C5 wording ("allow a composition to declare the naming template")
is withdrawn — it would have created the second authority §9.2 forbids.

**R-11-4 — metric information comes from the Step-10 authority.** Any
metric information the scoring subprocess requires must arrive through the
**already-existing Step-10 metric binding authority**. Step 11 may
transport it; it must not derive, redefine or infer it. `MetricSpec` has
zero reachability in that child today, and
`denoising_score_single.py:190-195` documents the current derivation as a
deliberate Step-06 choice ("no spec or metric is serialized, no argv is
added") — that choice is what makes it TIDMAD-only, and it is superseded
here. C6 first audits what the child actually consumes; it does not
speculatively transport every secondary metric.

**R-11-5 — RSS precedence and the zero case.** The effective ceiling is
`SIDERIUS_SUBPROCESS_RSS_GB` (global) → `_ROLE_DEFAULT_RSS_GB[role]`. **No
third layer** (§9.3 finding 14). `0` currently DISABLES the ceiling and a
negative/non-numeric value falls back **silently**; the declared form must
preserve the disable semantics explicitly and must REFUSE a malformed
value loudly rather than silently defaulting.

**R-11-6 — the run-invariants lock RECORDS the ceilings (APPROVED,
operator 2026-08-21).** A run must be able to say which ceilings it
executed under. The pin is **recorded, not equality-enforced**: ceilings
are execution-HOST calibration, not task semantics, so the same scientific
run resumed on a differently-calibrated host must not be refused the way a
composition, metric or dataset-semantics change is.

**Added operator constraint — recorded-only must not be representationally
confusable with the equality-enforced set.** Do not drop the ceilings into
the canonical equality set and rely on a validator "remembering" not to
compare them. The two concepts must be distinguishable in the
representation:

```text
semantic invariants          -> equality ENFORCED
execution provenance /
  host calibration           -> RECORDED, equality NOT enforced
```

A new schema is not required — express it with the minimum the existing
structure allows. **A test must prove**: same scientific run + different
recorded host calibration ⇒ **resume remains legal**. Without that test a
future generic invariant validator will comparison-sweep it by accident.

**R-11-7 — the data root is run binding, provenance-only.** It is a
host path, and the semantic fingerprint deliberately excludes host paths
(`task_composition.py:838-843`). It therefore joins **provenance**, never
the fingerprint. `HyperparamTuningInput.data_dir` — which today reaches
only the GPU measurement worker — is reconciled to the same authority
rather than left as a second concept.

**R-11-8 — fail-closed is a SEMANTIC change, decoupled from the import-time
MECHANISM.** A composed run whose declared data root is missing or a
placeholder FAILS CLOSED (`DatasetDirectoryUnavailable` is the existing
vehicle). The import-time template fallback (`data_paths.py:26-34`) is NOT
removed in this step: CI resolves the root from the tracked template and
`.github/workflows/ci.yml` creates no real config, so removing it breaks
collection repo-wide. Decoupling first (resolution behind a call) is the
prerequisite; the removal is named debt.

**APPROVED (operator, 2026-08-21), with this wording pinned: the
import-time template fallback is LEGACY-ONLY after Step 11 and must NEVER
be consulted as a fallback for a composed run.** It is an isolated,
named legacy debt — not a safety net the generic path may lean on. This
follows the standing migration pattern: make the new generic path stop
depending on the legacy fallback FIRST, retire the fallback SECOND, and
never dismantle a repo-wide initialization assumption inside a
high-blast-radius PR for tidiness.

**R-11-9 — composed vs unstamped legacy records on resume.**

| case | behaviour |
|---|---|
| legacy / un-composed run reading an unstamped record | **readable**, unchanged |
| composed run reading a record that CARRIES a fingerprint | must **match**, else refuse |
| composed run reading an unstamped legacy record | **refuse**, under a named rule — a record produced before composition existed cannot be certified as belonging to this composition |

`_reject_legacy_runtime_lock` (`run_invariants.py:244-279`) is the
precedent for refusing rather than defaulting. This closes rev-1's C7
contradiction, which asserted both "a cross-composition seed must not pass
ingress" and "a legacy unstamped record must remain readable" with no mode
distinction.

**R-11-10 — inverted guards must not become test debt.** Once a C0
defect-baseline assertion flips, it is either **transformed into the
permanent contract owner or removed**. The pre-fix census and a second
post-fix test proving the same behaviour must not both survive.

**R-11-11 — `sandbox_executor.py` stays the launch consumer.** New
declaration parsing, calibration/provenance ownership and reusable binding
resolution belong in responsibility-specific sibling modules. The file must
not become the owner of every new semantic. Measured baseline at
`a88aad9b` (C0 re-measures, C10 compares):

```text
file                       2,456 LOC
execute_training :1315     92 stmts · 39 branch · 357 LOC · 14 params
execute_inference :1686    69 stmts · 28 branch · 253 LOC ·  9 params
_run_observed_subprocess   62 stmts · 27 branch · 186 LOC ·  9 params
TidmadSandbox.__init__     22 stmts ·  6 branch ·  87 LOC · 12 params
```

`execute_training` is already 357 LOC with 14 parameters. If a commit would
add a new branch family, a new schema resolution, or ~80-150 lines to one
function, extract first.

---

## 5. Scope and non-goals

**In scope**: the data root as a composed, transported value · the
deliverable naming template as a composed value · per-role ceilings as
declared calibration with provenance and a stated precedence · the three
defects F-11-1/2/3 · spawn hygiene F-11-4/7 · invariants/resume F-11-5/6 ·
census widening F-11-8 · operator surface docs.

**Explicit non-goals**
* **Task-owned scope CONSTRUCTION** — Q-11-1/R-11-2. Step 11 transports a
  resolved scope (C5); it never builds one for an arbitrary task, and it
  makes no claim that a contrast task can produce one.
* **Real contrast-task subprocess execution / contrast-track L4** — remains
  CAP-SCOPE's, and Step 12 may not claim L4 while CAP-SCOPE is open.
* Retiring the D14 in-process runners — Step 10 Q-10-5 = B already gave
  them a retention contract.
* Out-of-tree plugin availability in children — Step 12.
* Changing the frozen TIDMAD score formula, or any metric semantics.
* Device SELECTION (F-11-10) — recorded, NOT fixed here unless the
  operator adds it; it is an operator-surface feature, not a genericity
  blocker.
* Consolidating all five OOM matchers (F-11-9) — the design states why
  five exist; only F-11-1's dead status is fixed.

---

## 6. PR decomposition — ONE PR

Per the operator's ruling (2026-08-21): **a PR split point is a Gate 1 +
Gate 2 boundary; work that needs no such Gate is a COMMIT, not a PR.**

The six work clusters — data-root transport · deliverable naming ·
calibration declaration · spawn hygiene · defects · invariants/resume —
**share one Gate**. None has an independent real-training failure class:
they all become observable in the same composed chain run, through the same
sandbox. Splitting would buy six review/CI/closeout cycles for one Gate
boundary, which is precisely what Step 10 did and what the ruling forbids.

Review granularity is served by §7's per-commit checklists, not by extra
PRs.

---

## 7. Commit plan

Twelve commits, ONE PR. All checkboxes start unchecked; evidence lines are
filled only after the work runs. **No commit contains a `Decide` — every
semantic decision is a ruling in §4a.**

Ordering rationale: defects first (they are small, independently
reviewable, and two of them sit in code later commits rewrite), then the
declaration/transport work, then hygiene, then guards and docs.

### C0 — Baselines, structural tripwire, inverted guards

1. **Goal.** Measure the pre-change state and make each defect executably
   visible BEFORE behaviour changes, so every later commit flips a named
   test.
2. **Scope.** Tests only. No production change. No dependency.
3. **Implementation plan**
   - [ ] Pin the exact argv flag set per role (`sandbox_executor.py`
         training / inference / scoring builders) — the R-11-1 legacy
         parity baseline.
   - [ ] Pin `_ROLE_DEFAULT_RSS_GB` and the two-layer precedence.
   - [ ] Record the **R-11-11 structural baseline** (file LOC; stmts,
         branch-ish, LOC, params for `execute_training`,
         `execute_inference`, `_run_observed_subprocess`, `__init__`).
   - [ ] Inverted guard F-11-1: `oom_host_ram` currently has no consumer.
   - [ ] Inverted guard F-11-2: `isolated_probe.py` currently spawns with
         no `env=`.
   - [ ] Pin the TIDMAD cleanup glob and the TIDMAD-resolved ceilings.
4. **Validation plan.** Unit only. No Gate.
5. **Acceptance criteria.** Every census reproduces §3/§4a numbers exactly;
   each inverted guard names the commit that flips it.
6. **Failure/edge cases.** A census scoped only to files it already covers
   would pass vacuously — F-11-8 is exactly that shape, so C0 must state
   its own scope explicitly.
7. **Verification commands and evidence.** `[ ]` pending.
8. **Commit boundary.** Tests only. **Per R-11-10 these guards are
   temporary; each later commit either converts its guard into the
   permanent contract owner or deletes it.**

### C1 — F-11-2: env transport on the production spawner

1. **Goal.** A production-reachable spawner must not lose the run-scoped
   plugin dir.
2. **Scope.** `isolated_probe.py` spec + spawn; the transport guard.
   `probe_subprocess.py` handled explicitly (production-unreachable).
3. **Implementation plan**
   - [ ] Add `plugin_dir` / `loss_dir` to `IsolatedProbeSpec` (no field
         exists to hold them today).
   - [ ] Pass `env=subprocess_env(...)` at the spawn.
   - [ ] Rewrite the guard to test the CONTRACT — every production worker
         spawner passes `env=` — not one file by path (F-P2b-4 shape).
   - [ ] Record the `probe_subprocess.py` disposition.
4. **Validation plan.** Unit + rewritten guard; mutation: a planted
   env-less spawner must turn it RED.
5. **Acceptance criteria.** The guard fails on a planted omission in ANY
   production spawner, proven by mutation rather than asserted; the C0
   inverted guard flips.
6. **Failure/edge cases.** `subprocess_env` never mutates `os.environ`; the
   child must not lose the `PYTHONPATH` extension either.
7. **Verification commands and evidence.** `[ ]` pending.
8. **Commit boundary.** One defect; no calibration or argv work.

### C2 — F-11-1: make the host OOM visible (per Q-11-3)

1. **Goal.** A host OOM must not be invisible to the tuner.
2. **Scope.** The three `oom_host_ram` producers; the tuner's consumer
   branches. **Under Q-11-3 = A, no planner-visible string changes.**
3. **Implementation plan**
   - [ ] Implement the Q-11-3 answer (A unless the operator rules B).
   - [ ] Make the host-OOM outcome reach a NAMED tuner outcome.
   - [ ] Assert the planner prompt bytes are unchanged (A) — the executable
         form of the Gate-1 disposition.
4. **Validation plan.** Unit; device-OOM classification unchanged; non-OOM
   errors unchanged; **prompt-byte parity test**.
5. **Acceptance criteria.** A host-OOM training failure reaches an asserted
   tuner outcome; prompt bytes byte-identical under A; C0 guard flips.
6. **Failure/edge cases.** A bare `-9` SIGKILL must remain unattributable —
   `failure_attribution` deliberately returns `unknown`; do not invent a
   fourth failure state.
7. **Verification commands and evidence.** `[ ]` pending.
8. **Commit boundary.** No OOM-matcher consolidation (F-11-9 is a non-goal).

### C3 — Resource ceilings become declared calibration (R-11-5, R-11-6)

1. **Goal.** Ceilings stop being undocumented constants and start recording
   what they derive from.
2. **Scope.** The ceiling table and resolver; a calibration declaration;
   the run-invariants record; F-11-3.
3. **Implementation plan**
   - [ ] Declare the ceilings with machine-readable provenance
         (measured-on, device, derived-from). Calibration config, **NOT**
         task config (§9.2).
   - [ ] Implement R-11-5 precedence exactly; preserve the `0` disable
         semantics; REFUSE malformed values loudly.
   - [ ] Implement R-11-6: record ceilings in the lock, recorded-not-
         enforced.
   - [ ] **F-11-3**: re-derive or retire the 60 GiB justification, whose
         cited anchor is now argmax code and whose dtype is task-declared.
4. **Validation plan.** Unit; TIDMAD ceilings resolve to the SAME 40/60/24
   (C0 baseline); negative tests for malformed and zero overrides.
5. **Acceptance criteria.** TIDMAD's resolved ceilings byte-identical to
   C0; every ceiling carries checkable provenance; a malformed override
   refuses instead of silently defaulting.
6. **Failure/edge cases.** Unknown role still raises; a rerun on a
   different host must not be refused (R-11-6).
7. **Verification commands and evidence.** `[ ]` pending.
8. **Commit boundary.** Declaration only — no task-derived ceilings
   (that would need Q-11-1 = B).

### C4 — The data root becomes a transported run binding (R-11-7, R-11-8)

1. **Goal.** The physical data root reaches every child because the run
   declared it.
2. **Scope.** The composition carrier; `dirs["data"]` and
   `TidmadSandbox.__init__`; the three argv builders and three child
   defaults; `HyperparamTuningInput.data_dir` reconciliation.
3. **Implementation plan**
   - [ ] Carry the resolved root on the run binding, **provenance-only**
         (R-11-7).
   - [ ] Thread it into the sandbox instead of `_tidmad_data_dir()`.
   - [ ] Transport it across training, inference and scoring argv,
         following the `--task_data_path_id` precedent (additive, emitted
         only when composed — R-11-1).
   - [ ] Reconcile `HyperparamTuningInput.data_dir` to the same authority.
   - [ ] Implement R-11-8's composed fail-closed check. **Do not remove the
         import-time fallback.**
   - [ ] R-11-11 check before writing: `execute_training` is already 357
         LOC / 14 params — extract rather than extend if this adds a branch
         family.
4. **Validation plan.** Unit; **un-composed argv byte-parity** vs C0; a
   composed manifest resolving a different root; negative: composed run
   with a missing/placeholder root fails closed.
5. **Acceptance criteria.** Un-composed argv byte-identical to C0; a
   composed run's children receive the declared root; CI (which resolves
   the template root) still passes.
6. **Failure/edge cases.** Missing root, placeholder root, non-directory —
   `DatasetDirectoryUnavailable` is the existing vehicle.
7. **Verification commands and evidence.** `[ ]` pending.
8. **Commit boundary.** Data root only; scope is C5, metric is C6.

### C5 — Resolved training-scope transport (the Q-11-1 owner)

1. **Goal.** If a resolved task scope is supplied, the subprocess boundary
   can transport and reconstruct it. **This is the commit rev 1 was
   missing.**
2. **Scope.** The training argv builder; `train_engine_sandbox.main()`,
   which today never passes `task_scope` so `:1124-1125` builds
   `TidmadScope` unconditionally.
3. **Implementation plan**
   - [ ] Audit what a resolved scope must carry to survive serialization.
   - [ ] Add an additive, composed-only argv carrier (R-11-1).
   - [ ] Have `main()` reconstruct and pass `task_scope` when supplied,
         falling back to today's `TidmadScope` path when not.
   - [ ] **R-11-2 boundary test**: the child RECONSTRUCTS a supplied scope
         and never CONSTRUCTS one for an arbitrary task.
4. **Validation plan.** Unit; legacy path unchanged (no carrier ⇒
   `TidmadScope`, byte-identical); a supplied non-TIDMAD scope reconstructs
   in the child; negative: a malformed carrier refuses.
5. **Acceptance criteria.** With no carrier, training behaviour is
   byte-identical to C0. With a carrier, the child provably consumes the
   supplied scope. **No claim is made that any contrast task can PRODUCE
   one — that is CAP-SCOPE.** An executable census proves **zero**
   task-identity or scope-kind dispatch was added to generic execution
   infrastructure (the §6 invariant).
6. **Failure/edge cases.** Malformed carrier, carrier naming an unknown
   scope kind, carrier present on an un-composed run — all refuse.

   **BINDING INVARIANT (operator, 2026-08-21) — no identity dispatch.**
   C5 must NOT introduce a task-identity or built-in-scope-kind dispatch
   table into generic execution infrastructure. This is forbidden:

   ```python
   if scope_kind == "tidmad": ...
   elif scope_kind == "pets": ...      # <- CAP-SCOPE smuggled into Step 11
   ```

   Scope reconstruction must use an EXISTING generic
   serialization/registration/interface authority, or a task-neutral
   carrier. **If the source audit proves no such generic reconstruction
   seam exists, that is a material capability finding: STOP and bring it
   back before implementation — do not solve it with TIDMAD/Pets/DAVIS
   branches.**

   ```text
   transport serialization              -> Step 11
   generic registered reconstruction    -> Step 11, IF the seam exists
   switch on task / scope identity      -> FORBIDDEN
   invent task scope semantics          -> CAP-SCOPE
   ```
7. **Verification commands and evidence.** `[ ]` pending.
8. **Commit boundary.** Transport only. No task-owned scope construction,
   no D14-runner rerouting.

### C6 — Scoring metric via the Step-10 authority (R-11-4)

1. **Goal.** The scoring child stops unconditionally deriving TIDMAD's
   metric, so the spawn surface is task-neutral in all three roles.
2. **Scope.** `denoising_score_single.py` metric acquisition; the transport
   carrier; the Step-10 metric binding authority (consumed, never
   redefined).
3. **Implementation plan**
   - [ ] **Audit first**: what does the scoring child actually consume from
         the metric? Do not speculatively transport secondaries.
   - [ ] Replace the unconditional `derive_tidmad_metric` with acquisition
         through the Step-10 authority.
   - [ ] Keep the un-composed path byte-identical — the current derivation
         is a documented Step-06 choice and stays the legacy branch.
4. **Validation plan.** Unit; un-composed scoring parity (same score, same
   record keys); a composed run using its declared metric; negative: a
   composed run whose metric cannot be acquired refuses rather than falling
   back to TIDMAD.
5. **Acceptance criteria.** Zero unconditional TIDMAD metric derivations
   remain in the scoring child; the frozen TIDMAD score is unchanged for
   un-composed runs.
6. **Failure/edge cases.** A composed run must never silently score with
   TIDMAD's metric — that is the C-P56-1 failure class one layer down.
7. **Verification commands and evidence.** `[ ]` pending.
8. **Commit boundary.** Metric acquisition only; no metric semantics, no
   direction logic, no scoring arithmetic.

### C7 — Deliverable naming flows FROM the contract (R-11-3)

1. **Goal.** A composed task's deliverable is named by the Deliverable
   Contract, so cleanup globs stop matching filenames a contrast run never
   wrote.
2. **Scope.** The deliverable derivation; the run binding carrier; the two
   cleanup sites, which are already contract READERS.
3. **Implementation plan**
   - [ ] Carry the **resolved** naming declaration on the run binding.
         **The composition must NOT become a second naming authority
         (R-11-3).**
   - [ ] Keep TIDMAD's defaults byte-identical when undeclared.
4. **Validation plan.** Unit; TIDMAD glob byte-parity vs C0; a composed
   task producing a different glob; an authority census proving one owner.
5. **Acceptance criteria.** Both cleanup sites consume the declared
   template with no change at the call sites; exactly one naming authority
   exists.
6. **Failure/edge cases.** An empty or malformed template must refuse, never
   produce a glob matching everything.
7. **Verification commands and evidence.** `[ ]` pending.
8. **Commit boundary.** Naming only.

### C8 — Spawn hygiene (F-11-4, F-11-7)

1. **Goal.** Remove accidental couplings that make the surface fragile.
2. **Scope.** `cached_models` / `records` name derivation; the three
   relative script paths; the stale launch-split docstring.
3. **Implementation plan**
   - [ ] One authority for the sandbox subdirectory names, following the
         `get_plugin_dir` / `get_loss_dir` precedent in the same file.
   - [ ] Anchor the three script paths absolutely; keep `cwd` semantics.
   - [ ] Correct the launch-split justification (§3.5) — the cited
         `timeout --signal=INT` mechanism does not exist; the real anchor
         is the foreground process group plus the chain trap. **Fix the
         reason, never the behaviour.**
4. **Validation plan.** Unit; a parity test proving parent and child derive
   the SAME paths; mutation: a planted divergent literal turns it RED.
5. **Acceptance criteria.** The parent/child agreement is enforced rather
   than coincidental.
6. **Failure/edge cases.** The `_OK_` sentinel read depends on the match; a
   mismatch currently produces a FALSE `error_training`.
7. **Verification commands and evidence.** `[ ]` pending.
8. **Commit boundary.** No change to kill/cleanup semantics.

### C9 — Invariants and resume (F-11-5, F-11-6, R-11-9)

1. **Goal.** Remove the last task token from the resume path and close the
   ingress-vs-lock asymmetry.
2. **Scope.** `resume.py`'s `full_scope` derivation and `TIDMAD` import;
   `validate_stamped_invariants` and its four hand-built call sites.
3. **Implementation plan**
   - [ ] Replace `list(range(TIDMAD.num_files))` with the composed
         profile's `num_files`, as the sibling site already does; drop the
         import.
   - [ ] Implement **R-11-9**'s three-case table exactly.
4. **Validation plan.** Unit; legacy unstamped record readable in legacy
   mode; composed + fingerprint mismatch refuses; composed + unstamped
   legacy refuses under the named rule.
5. **Acceptance criteria.** `core/resume.py` contains zero task tokens; all
   three R-11-9 cases have a named test.
6. **Failure/edge cases.** Step 10 omits the key rather than serializing
   `null`; that must stay true so legacy locks remain byte-identical.
7. **Verification commands and evidence.** `[ ]` pending.
8. **Commit boundary.** No invariants beyond R-11-9.

### C10 — Census widening, structural comparison, operator docs

1. **Goal.** The spawn parent stops being invisible to the repository's own
   guards; the operator surface is documented; the structural budget is
   checked.
2. **Scope.** F-11-8; the R-11-11 comparison; `sdsc_submission_scripts/README.md`
   and any node `.md` this PR's production changes touch.
3. **Implementation plan**
   - [ ] Bring `core/sandbox_executor.py` into the censused surface, or
         state why not. Widening may surface pre-existing leaks — record
         them, never exempt by name.
   - [ ] Re-measure the R-11-11 metrics and compare against C0. A function
         that grew a branch family or ~80-150 lines must be extracted
         before this commit closes.
   - [ ] Document the resource knobs, which are env-only and undocumented
         outside source.
   - [ ] **Doc sync lands HERE — before the final push, not after**
         (the Step-10 ordering lesson).
   - [ ] **R-11-10 sweep**: every C0 inverted guard is now a permanent
         contract owner or deleted; no duplicate pre/post pairs survive.
4. **Validation plan.** Unit; the widened census RED on a planted leak.
5. **Acceptance criteria.** Every documented flag quoted against merged
   source; the structural comparison recorded with real numbers; zero
   duplicate guards.
6. **Failure/edge cases.** If the structural budget is exceeded and cannot
   be extracted safely, STOP and raise it rather than shipping the growth.
7. **Verification commands and evidence.** `[ ]` pending.
8. **Commit boundary.** Docs, guards and measurement only.

### C11 — Gate 2 evidence and closeout

1. **Goal.** Produce the one real-execution evidence this PR owes: the
   subprocess path executes under a composed binding, with the transported
   values actually consumed, and TIDMAD parity intact. It is last because
   the Gate must run at the final executable head.
2. **Scope.** Gate advice/config and the ledger. **No production change**
   beyond what the Gate evidence itself requires. Depends on C0–C10.
3. **Implementation plan**
   - [ ] Write the Gate-readiness packet: candidate SHA, clean tree,
         deterministic prerequisites green, exact workload, projected
         runtime and cost, PASS/FAIL/INCONCLUSIVE taxonomy.
   - [ ] Re-read the gate standard and re-audit the CLI flags from source
         immediately before launch (command shapes drift).
   - [ ] Launch bounded and autonomously inside the pre-authorised
         envelope, per §8.
   - [ ] Record the result against its EXACT SHA in §11.
4. **Validation plan.** This commit IS the validation. **Gate 2 REQUIRED —
   listed separately here and NOT to be launched without the standing
   pre-authorisation actually applying.** Gate 1 NOT REQUIRED (Q-11-3 = A),
   pinned executably by C2's prompt-byte parity test rather than by
   assertion.
5. **Acceptance criteria.** Chain exits 0; real training, inference and
   scoring executed (not pseudo, not skipped); the composed run's children
   provably consumed the TRANSPORTED data root, scope carrier and metric
   rather than TIDMAD defaults; un-composed argv byte-identical to the C0
   census; TIDMAD ceilings resolve to 40/60/24; the TIDMAD cleanup glob
   unchanged. **Model quality is NOT a criterion** (§8).
6. **Failure/edge cases.** A failure in the spawn/IPC/rlimit/cleanup path
   is a REAL Step-11 regression — fix it, do not work around it. A failure
   caused only by model quality, HealthGate output or score magnitude is
   **not** a Gate failure and is **not** grounds to tune anything. A
   provider/network/machine fault is INCONCLUSIVE per the standard.
7. **Verification commands and evidence.** `[ ]` pending — record the
   workspace, the exact SHA, and the CI id alongside it. Never claim a run
   that did not happen.
8. **Commit boundary.** Evidence and ledger only. If the Gate exposes a
   production defect, that fix is its own commit with its own checklist,
   and the Gate re-runs at the new head only if the fix touches a
   Gate-owned execution path.

---

## 8. Gate disposition

| field | value |
|---|---|
| **FAILURE CLASS UNDER TEST** | the real subprocess execution path — spawn, argv, sentinel/IPC, rlimits, cleanup — driven from a run's declared composition rather than TIDMAD's import-time constants |
| **REQUIRED REAL COMPONENTS** | real training, inference and scoring subprocesses under a composed binding; real rlimit application; real sentinel and cleanup |
| **NON-REQUIRED SCIENTIFIC QUALITY** | **model quality · HealthGate PASS · score magnitude · convergence · output diversity.** None is owned by Step 11; a poor or collapsed candidate is acceptable evidence |
| **MAXIMUM TEMPORAL DEPTH** | **1 iteration × 1 round** (the standard's default) |
| **EXTRA DEPTH JUSTIFICATION** | none required — Step 11's witness is observable within a single iteration. **Semantic-latency preflight: the witness is argv/sentinel/rlimit behaviour, which is produced and consumed inside one iteration, so no carried-state latency applies.** |
| **ISOLATION** | if a quality subsystem would block the path on a criterion Step 11 does not own, isolate it with the existing production switch, changing no semantics |

**Gate 1 — resolved from source, pending only the Q-11-3 answer.** The
planner's OOM note is gated on `str(r.get("status", "")).endswith("_oom")`
(`agent/prompts.py:1265-1270`). `"oom_host_ram"` ends in `_ram`, so it does
**not** match today and a host OOM renders no planner bytes.

* **Q-11-3 = A (recommended)** — C2 keeps the status out of the `_oom`
  family, prompt bytes are unchanged, **Gate 1 NOT REQUIRED**. C2 carries
  an executable prompt-byte parity test, so this is asserted rather than
  assumed.
* **Q-11-3 = B** — the note newly renders for host-OOM attempts, which is
  an LLM-facing change: **Gate 1 REQUIRED**.

This was checked before freeze precisely so it is not discovered during C2.

**Gate 2 — REQUIRED**, once, at the final executable head.

---

## 9. Evidence economy

* Targeted tests per commit; no full local suite (validation-economy rule).
* ONE authoritative exact-head CI at the final head.
* **Doc sync in C10, BEFORE the final push** — Step 10's ordering error,
  now a standing rule.
* Byte-parity is the workhorse: un-composed argv, TIDMAD ceilings and the
  TIDMAD glob must all be provably unchanged.

---

## 10. Risks

| risk | mitigation |
|---|---|
| `sandbox_executor.py` is the highest-blast-radius file in the repo; the roadmap itself calls this step "highest blast radius, smallest genericity gain" | byte-parity gates on argv, ceilings and globs; kill/cleanup semantics explicitly out of scope |
| 07c collides on the same file | Q-11-2 |
| The ORIGINAL roadmap criterion was unsatisfiable under current CAP-SCOPE maturity | **RESOLVED** — Q-11-1 / R-11-2 supply the bounded corrected Step-11 acceptance (transport, not construction). Not an open blocker |
| Removing the import-time fallback breaks CI at collection | C4 separates the fail-closed SEMANTIC decision from the import-time MECHANISM |

---

## 11. Implementation ledger

*(empty — implementation has not started.)*

**Entry conditions, in order.** Implementation MUST NOT start until all of
these hold:

- [ ] 07c implemented, Gate-2'd and MERGED (Q-11-2)
- [ ] Step-11 source anchor refreshed to the resulting master (R-11-0)
- [ ] Bounded re-audit re-verifies every §3 anchor and line number, and
      reconciles any semantics 07c changed — re-auditing ONLY the affected
      source assumptions, not the whole surface again
- [ ] The three rev-2 stale points confirmed fixed (this revision)
- [ ] C5 confirmed to have no task/scope identity dispatch seam problem —
      if no generic reconstruction seam exists, STOP and raise it
- [ ] Open operator questions = **0**
- [ ] Operator freezes as **Revision 3**

All three questions are RULED as of rev 2: **Q-11-1 = A** (transport, not
construction) · **Q-11-2 = 07c FIRST** · **Q-11-3 = A** (tuner-visible
only, prompt bytes unchanged, Gate 1 NOT REQUIRED).
