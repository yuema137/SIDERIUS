# Step 11 — Execution Infrastructure (spawn, IPC, limits)

## 0. Status

**STEP 11 — REVISION 4 — FROZEN. OPERATOR APPROVED 2026-08-21.
READY FOR IMPLEMENTATION.**

Freeze history: rev 1 draft → rev 2 answered the operator review (12
rulings, no `Decide`) → rev 3 reconciled against current master and
surfaced one material finding → **rev 4 rules it and freezes**.

**The 07c prerequisite was already satisfied**: 07c merged 2026-08-17 as
PR #219, squash `52bd98ba`, four days BEFORE rev 2's own audit anchor, so
rev 2's source audit already observed post-07c code. No post-07c semantic
delta existed and none was manufactured.

**Q-11-4 = B (operator):** the generic scope-reconstruction seam does not
exist, and Step 11 does not invent one. Resolved training-scope transport
is REMOVED, the commits are renumbered cleanly, and scope
serialization/rehydration/construction plus real contrast-task subprocess
L4 are deferred together to CAP-SCOPE (**R-11-12**).

**Open operator questions: 0. Material findings: 0 unresolved.**

Revision 2 answers the operator's rev-1 review (2026-08-21): Q-11-1 and
Q-11-2 are RULED, every implementation-time `Decide` is promoted to a
numbered ruling **R-11-1 … R-11-11**, the three gaps the rev-1 commit plan
did not own (resolved-scope transport, scoring metric derivation,
deliverable-naming ownership) now have commits, and the argv-parity
contradiction is reconciled explicitly.

| field | value |
|---|---|
| roadmap contract | `siderius_generic_framework_upgrade.md` §9 (§9.1 couplings, §9.2 target, §9.3 compatibility), completion-matrix row "§9 Execution infrastructure" |
| source anchor | **`175904cd`** (clean master, 2026-08-21). Rev 2 audited at `a88aad9b`; **zero production files changed between them** (all five intervening commits are docs-only), so every §3 anchor was re-verified EXACT with no line movement — see §3.6. |
| prerequisite status | Steps 00–06, **07 COMPLETE including §7e/07c (PR #219, squash `52bd98ba`, merged 2026-08-17)**, 08, 09, 09.5, 09.5a, 10 **COMPLETE**. **No outstanding prerequisite.** |
| open operator questions | **0.** Q-11-1, Q-11-2 (discharged), Q-11-3 and Q-11-4 all RULED. |
| PR decomposition | **ONE PR** (see §6) |
| Gate disposition | Gate 2 **REQUIRED**, 1 iteration x 1 round. Gate 1 **NOT REQUIRED** — Q-11-3 = A ruled by the operator; source-checked, not assumed (§8) |

This document is the parent design AND the PR document — one PR, one doc,
per the kickoff protocol. Per-commit checklists in §7 follow the operator's
8-section standard and start **all `[ ]`**; no item is checked and no
evidence line is filled until the work has actually run.

---

## 1. Capability / final effect

**Step 11 makes the generic execution infrastructure task-neutral wherever
an existing resolved framework binding already has a transport authority**
— physical data root, deliverable naming, metric binding, resource
calibration, spawn environment, paths, invariants and resume.
**Task-owned training-scope construction and rehydration remain CAP-SCOPE**
and are explicitly required before real contrast-task subprocess L4 can be
claimed.

The scope of the claim, stated so it cannot drift:

```text
delivered by Step 11
  data root transport                    yes
  metric binding transport               yes
  deliverable contract reading           yes
  resource calibration + provenance      yes
  spawn env / absolute paths             yes
  invariants + resume genericity         yes
  sentinel / IPC / cleanup preservation  yes

NOT delivered, deferred to CAP-SCOPE (R-11-12)
  task scope construction                no
  task scope rehydration                 no
  Pets / DAVIS real subprocess L4        no
```

**Two claims rev 2 made are WITHDRAWN**: that the training scope reaches a
child because the run declared it, and that the surface "no longer PREVENTS"
a contrast-task spawn. Both were stronger than the source supports. What
Step 11 removes are the TIDMAD-shaped couplings that have transport
authorities today; the scope gap is a separate missing capability.

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

### 3.6 Rev-3 freshness reconciliation (2026-08-21, anchor `175904cd`)

**Bounded by design** — only the load-bearing assumptions were re-checked,
not the whole surface.

* **Production drift since rev 2's anchor `a88aad9b`: ZERO files.** All five
  intervening commits are docs-only, so no §3 line anchor moved.
* **Eight load-bearing anchors re-verified EXACT**: `dirs["data"] =
  _tidmad_data_dir()` (`:1136`) · `TidmadScope` unconditional
  (`train_engine_sandbox.py:1124-1125`) · `derive_tidmad_metric`
  (`denoising_score_single.py:195`) · `isolated_probe.py:482-487` still has
  **no** `env=` · all three `oom_host_ram` producers (`:1654,:1923,:2116`) ·
  `resume.py:1483` `TIDMAD.num_files` · `_ROLE_DEFAULT_RSS_GB` 40/60/24 ·
  `sandbox_executor.py` still ABSENT from `_DATA_PATH_SURFACE`.
* **Structural baseline UNCHANGED**: file 2,456 LOC; `execute_training`
  92 stmts / 39 branch / 357 LOC / 14 params; `execute_inference`
  69/28/253/9; `_run_observed_subprocess` 62/27/186/9;
  `TidmadSandbox.__init__` 22/6/87/12. R-11-11's budget stands as written.
* **All rev-2 rulings re-confirmed valid** at this anchor: Q-11-1,
  Q-11-2 (discharged — already merged), Q-11-3, R-11-1 … R-11-11.
* **Gate dispositions unchanged**: Gate 1 NOT REQUIRED (Q-11-3 = A);
  Gate 2 REQUIRED, 1 iteration x 1 round. The semantic-latency preflight is
  re-affirmed — the witness is argv/sentinel/rlimit behaviour, produced and
  consumed inside one iteration.
* **One material finding: Q-11-4** — C5's assumed generic reconstruction
  seam does not exist.

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

### Q-11-2 — RULED: **07c FIRST** — and **already SATISFIED**

> Implement/merge 07c, then re-anchor and reconcile Step 11 before freeze.

**Status at rev 3: DISCHARGED, and it always was.** 07c merged **2026-08-17**
as PR **#219**, squash **`52bd98ba`** — four days BEFORE rev 2's audit anchor
`a88aad9b`. Rev 2's source audit therefore already observed post-07c code.

Rev 2 recorded 07c as "FROZEN … never implemented" on the authority of two
documents that were both stale: the roadmap's `§7e` row (`NOT STARTED`) and
07c's own ledger (*"Implementation complete; PR next"*). Verified from git
instead — `52bd98ba` is an ancestor of master, `execute_tools/probe_batch.py`
and the `RuntimePhase` `"validation"` member and `validation_max_samples` are
all present, `probe_data.py` is gone as C2 specified, and the 07c files on
master are **byte-identical** to the (now deleted) implementation branch
`step07-pr07c-tuner-measurement`, tip `4b73d34a`.

**No post-07c semantic delta exists to absorb, and none was invented.**

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

### Q-11-4 — RULED: **B — scope rehydration leaves Step 11** (operator, 2026-08-21)

**The rev-2 C5 invariant fired exactly as designed.** It said:

> If source audit proves no such generic reconstruction seam exists, that
> is a material capability finding and must be brought back before
> implementation rather than solved with TIDMAD/Pets/DAVIS branches.

**Source audit at `175904cd` proves it does not exist:**

| probe | result |
|---|---|
| a scope registry / `scope_kind` / scope-serialization helper anywhere in `execute_tools/`, `core/`, `nodes/`, `workflows/` | **none** |
| `TaskDataPath` protocol exposing a scope TYPE, builder or reconstructor | **none** — its four methods take `scope: object` as a PARAMETER; the seam CONSUMES a scope and never produces one |
| a shared base / Protocol / ABC across `TidmadScope`, `PetsScope`, `DavisScope` | **none** — three independent `BaseModel`s, docstringed as "opaque" and "task-owned vocabulary" |
| how a scope is obtained today | direct class instantiation in Python (`PetsScope(rows=...)`, `run_pets_gate2.py:185`) — works only IN-PROCESS |

Each scope is individually serializable because it is a Pydantic model.
What is missing is any task-neutral way for the CHILD to know **which model
to rehydrate into**. Supplying that by hand is precisely the forbidden
`if scope_kind == "pets"` table.

**C5 therefore cannot freeze as written.** Options:

| # | option | character |
|---|---|---|
| **A** | C5 adds a **generic scope registry** (id → scope model), parallel to the EXISTING task-data-path registry, and reuses that registry's id transport | new generic machinery, task-neutral, no dispatch. Defensible as TRANSPORT: a registry rehydrates a scope that was already built; it never builds one from a manifest. But rev 2 assumed an EXISTING seam, so this is a real scope increase |
| **B** | **drop C5**; scope transport moves wholly to CAP-SCOPE | Step 11 then delivers data root + naming + metric + calibration + the three defects, and §1 must stop claiming scope can cross argv — the option the operator offered at rev 1 and did not take |
| C | extend the frozen D14 four-method contract with a scope-reconstruction method | changes a FROZEN contract; effectively CAP-SCOPE |

**OPERATOR RULING: B.** Resolved training-scope transport is REMOVED from
Step 11. No scope-model registry is created here.

> Option A is a registry only in name. It would have to define scope type
> identity, registration, discovery, serialization/deserialization,
> unknown-type handling and future external-registration semantics — that
> is a **task-owned scope extensibility mechanism**, not argv transport, and
> it belongs near CAP-SCOPE / Step 12. Building it inside Step 11 would
> violate the rule this project just adopted: do not expand a Gate, a PR or
> a semantic scope because a neighbouring problem is adjacent. And the
> shortcut version —
>
> ```python
> scope_registry = {"tidmad": TidmadScope, "pets": PetsScope, ...}
> ```
>
> — is precisely what the no-dispatch invariant exists to forbid.

**This finding is the design guard succeeding, not Step 11 being blocked.**
The old C5 is deleted and the remaining commits are renumbered cleanly, so
the frozen plan carries no numbering baggage. See **R-11-12**.

---

## 4a. Rulings (R-11-x) — every rev-1 `Decide` is resolved here

Rev 1 left eleven semantic decisions as implementation-time `Decide`
items. Each would have changed schema, compatibility, resume, failure
semantics or operator behaviour, so each is promoted to a ruling. **A
frozen design contains no `Decide`.**

**R-11-0 — freeze prerequisites. (a) and (b) and (c) are DISCHARGED at
rev 3.** 07c merged 2026-08-17 (PR #219, `52bd98ba`); the anchor is
refreshed to `175904cd`; the bounded re-audit is recorded in §3.6 and found
zero production drift, so every §3 anchor holds exactly. **The remaining
freeze blocker is Q-11-4 alone.**

**R-11-1 — argv parity, reconciled.** §9.3's "argv/IPC/sentinels
byte-identical" and Step 11's job of transporting new declared values are
only compatible when stated per-mode:

**AMENDED BY OPERATOR RULING, 2026-08-22 (see R-11-13).** The legacy row's
original wording — "argv byte-identical" — is literally false after C7's
explicitly frozen script-path anchoring, and the corrected wording below is
the operator's own.

| mode | contract |
|---|---|
| legacy / un-composed TIDMAD | the **transport option surface and execution semantics remain byte-identical**; C7's explicitly frozen script-path anchoring MAY canonicalize the positional child-script token from repo-relative to the equivalent current-checkout absolute path. Proven against the C0 census |
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

**R-11-12 — scope rehydration belongs to CAP-SCOPE (operator, 2026-08-21).**
Source reconciliation proved that **no generic scope reconstruction
authority exists**: no registry, no shared base across `TidmadScope` /
`PetsScope` / `DavisScope`, and a `TaskDataPath` protocol that takes
`scope: object` as a parameter and never produces one. **Step 11 MUST NOT
invent one.** Training-scope serialization, type registration,
reconstruction, and arbitrary task-scope production are deferred TOGETHER
to CAP-SCOPE. Consequently **real contrast-task subprocess execution
remains explicitly UNCLAIMED after Step 11**, and this is the clear input
Step 12 planning inherits.

**R-11-13 — argv byte-parity, corrected wording (OPERATOR RULING,
2026-08-22).** R-11-1's legacy row said "argv byte-identical". C7's frozen
checklist simultaneously required absolute script anchoring, and the two
cannot both be literally true: the positional child-script token changes from
`execute_tools/train_engine_sandbox.py` to the equivalent absolute path.

The operator's ruling, in the operator's own words:

> Legacy/uncomposed **transport option surface and execution semantics remain
> byte-identical; C7's explicitly frozen script-path anchoring may
> canonicalize the positional child-script token from repo-relative to the
> equivalent current-checkout absolute path.**

> "I do not recommend reverting the absolute path… but here one cannot say
> 'legacy argv byte-identical', because taken literally that is false."

**The code is NOT reverted.** What changes is the contract's wording, which
is now honest about what byte-parity covers. The five pre-existing goldens
normalize ONLY a repo-rooted token back to its repo-relative form; a script
path that became absolute but points outside this checkout is not normalized
and still turns them RED.

**R-11-14 — the C8 composition stamp is an operator-RATIFIED bounded
contract correction (OPERATOR RULING, 2026-08-22).** R-11-9's second row
speaks of "a record that CARRIES a fingerprint"; source audit proved nothing
carried one, so implementing only the validator would have made every
composed run refuse its own records. C8 therefore added additive,
default-`None` `task_composition_fingerprint` to `ExperimentRecord` and
`HyperparamTuningOutput`.

> "技术方案 APPROVE。不要 revert。但在 merge 前必须把它正式记录为
> operator-approved bounded contract correction."
> — **IMPLEMENTATION: PASS. PROCESS: deviation requiring explicit
> ratification.**

**Process finding, recorded against this PR and not softened.** A schema /
protocol / state-machine expansion is NOT ordinary implementation discretion.
The correct behaviour was to STOP at the moment the audit proved R-11-9
unsatisfiable and bring the finding back for a ruling — not to implement the
fix and record it afterwards. The technical choice is ratified; the process
deviation is the lesson.

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
* **Task-owned scope CONSTRUCTION *and* REHYDRATION** — Q-11-4 = B,
  **R-11-12**. Step 11 does neither, and creates no scope registry. The
  rev-2/rev-3 C5 commit is DELETED, not emptied.
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

**Eleven commits (C0–C10), ONE PR.** All checkboxes start unchecked;
evidence lines are filled only after the work runs. **No commit contains a
`Decide` — every semantic decision is a ruling in §4a.**

*(Implementation erratum, 2026-08-21: this line said "Twelve commits" — a
stale count left by the Q-11-4 renumbering that DELETED the old C5. The
commit LIST below has always been authoritative and is unchanged.)*

Ordering rationale: defects first (they are small, independently
reviewable, and two of them sit in code later commits rewrite), then the
declaration/transport work, then hygiene, then guards and docs.

### C0 — Baselines, structural tripwire, inverted guards

1. **Goal.** Measure the pre-change state and make each defect executably
   visible BEFORE behaviour changes, so every later commit flips a named
   test.
2. **Scope.** Tests only. No production change. No dependency.
3. **Implementation plan**
   - [x] Pin the exact argv flag set per role (`sandbox_executor.py`
         training / inference / scoring builders) — the R-11-1 legacy
         parity baseline.
         → `tests/unit/core/test_step11_c0_baselines.py::TestLegacyArgvFlagBaseline`.
         Captured at RUNTIME from the production builders, not read off
         source text. The three frozen flag tuples are recorded in that
         module.
   - [x] Pin `_ROLE_DEFAULT_RSS_GB` and the two-layer precedence.
         → `TestRoleCeilingBaseline` (40/60/24, env override wins for
         every role, `0` disables, unknown role raises).
   - [x] Record the **R-11-11 structural baseline** (file LOC; stmts,
         branch-ish, LOC, params for `execute_training`,
         `execute_inference`, `_run_observed_subprocess`, `__init__`).
         → `tests/unit/guardrails/test_step11_c0_defect_baselines.py::TestStructuralBaseline`.
   - [x] Inverted guard F-11-1: `oom_host_ram` currently has no consumer.
         → `TestHostOomHasNoConsumer` (flipped by **C2**).
   - [x] Inverted guard F-11-2: `isolated_probe.py` currently spawns with
         no `env=`.
         → `TestIsolatedProbeSpawnsWithoutEnv` (flipped by **C1**).
   - [x] Pin the TIDMAD cleanup glob and the TIDMAD-resolved ceilings.
         → `TestTidmadCleanupGlobBaseline`.
   - [x] *(added)* Inverted guard: a malformed `SIDERIUS_SUBPROCESS_RSS_GB`
         silently defaults today → `TestMalformedOverrideIsSilentToday`
         (flipped by **C3**, R-11-5).
   - [x] *(added)* Inverted guard F-11-8: the spawn parent is absent from
         the task-data-path census surface → `TestSpawnParentIsUncensused`
         (flipped by **C9**).
4. **Validation plan.** Unit only. No Gate.
5. **Acceptance criteria.** Every census reproduces §3/§4a numbers exactly;
   each inverted guard names the commit that flips it.
   **MET.** The structural counter reproduces §4a EXACTLY — file 2,456 LOC;
   `execute_training` 92/39/357/14; `execute_inference` 69/28/253/9;
   `_run_observed_subprocess` 62/27/186/9; `TidmadSandbox.__init__`
   22/6/87/12 — once `stmts` is defined as "every statement in the subtree
   INCLUDING the `def` itself, EXCLUDING nested definitions". Every
   inverted-guard class names its flipping commit in its docstring.
6. **Failure/edge cases.** A census scoped only to files it already covers
   would pass vacuously — F-11-8 is exactly that shape, so C0 must state
   its own scope explicitly. **DONE**: the F-11-1 census walks every
   non-test `.py` under `core/ execute_tools/ agent/ nodes/ workflows/
   dashboard/` and names its two prose-only exemptions; the argv baseline
   states that the argument-driven conditional flags are out of its scope
   and that the property it owns is narrower — *no new UNCONDITIONAL flag
   on the legacy path*.
7. **Verification commands and evidence.**
   - [x] `pytest tests/unit/core/test_step11_c0_baselines.py tests/unit/guardrails/test_step11_c0_defect_baselines.py -q`
         → **32 passed**, 3.7 s.
   - [x] `ruff check` + `ruff format --check` on both modules → clean.
   - [x] **Mutation 1** — an unconditional `--planted_flag` added to the
         training argv builder ⇒ `test_training_argv_flags` **RED**;
         reverted, 17 passed.
   - [x] **Mutation 2** — a planted `oom_host_ram` reader in
         `nodes/ml_hyperparameter_tune_agent/policy.py` ⇒
         `test_no_production_module_reads_the_status` **RED**; reverted,
         15 passed.
   - [x] Caches cleared before the mutation pass
         (`feedback_mutation_proof_hygiene`); each planted edit asserted
         `count == 1` before writing.
8. **Commit boundary.** Tests only. **Per R-11-10 these guards are
   temporary; each later commit either converts its guard into the
   permanent contract owner or deletes it.**

   **Source correction recorded at C0**: §3.3 and §7-C1 write the spawner
   as `isolated_probe.py`; its actual path is
   **`agent/skills/evaluate_vram_skill/isolated_probe.py`**. Every other
   §3 anchor was re-verified EXACT at `c1caa609` (`git diff --name-only
   a88aad9b HEAD` lists zero non-docs files).

### C1 — F-11-2: env transport on the production spawner

1. **Goal.** A production-reachable spawner must not lose the run-scoped
   plugin dir.
2. **Scope.** `isolated_probe.py` spec + spawn; the transport guard.
   `probe_subprocess.py` handled explicitly (production-unreachable).
3. **Implementation plan**
   - [x] Add `plugin_dir` / `loss_dir` to `IsolatedProbeSpec` (no field
         exists to hold them today).
         → `isolated_probe.py`, optional `str | None = None`, mirroring
         `GpuMeasurementSpec.plugin_dir` / `.loss_dir` exactly, so a spec
         written before the field still validates (same omit-vs-broken
         rule as `model_io_contract`).
   - [x] Pass `env=subprocess_env(...)` at the spawn.
         → `isolated_probe.py` `run_isolated_preflight`, built from
         `spec.plugin_dir` / `spec.loss_dir`.
   - [x] Rewrite the guard to test the CONTRACT — every production worker
         spawner passes `env=` — not one file by path (F-P2b-4 shape).
         → `tests/unit/core/test_measurement_worker_plugin_transport.py::TestEveryProductionWorkerSpawnerTransportsTheEnvironment`,
         four tests: the census is non-vacuous · **every** production
         `subprocess.Popen` passes `env=` (AST-derived over
         `core/ execute_tools/ agent/ nodes/ workflows/ dashboard/`) ·
         the isolated pre-flight transports the RUN-SCOPED dirs
         (behavioural, asserted on the env production hands `Popen`) ·
         the production entrypoint cannot omit them (signature).
   - [x] Record the `probe_subprocess.py` disposition. → see §7-C1.8.
   - [x] *(added)* Thread the transport through the production caller:
         `run_production_preflight` gains **keyword-only, no-default**
         `plugin_dir` / `loss_dir`, and `execution.py:230` supplies
         `sandbox.plugin_dir` / `sandbox.loss_dir` — the run-scoped
         authority that owns them, never a re-derivation.
4. **Validation plan.** Unit + rewritten guard; mutation: a planted
   env-less spawner must turn it RED.
5. **Acceptance criteria.** The guard fails on a planted omission in ANY
   production spawner, proven by mutation rather than asserted; the C0
   inverted guard flips. **MET** — see the three mutations in §7-C1.7.
6. **Failure/edge cases.** `subprocess_env` never mutates `os.environ`; the
   child must not lose the `PYTHONPATH` extension either. **Both hold**:
   `subprocess_env` returns `os.environ.copy()` with the extension applied
   (`core/subprocess_env.py:68-76`), and the PYTHONPATH extension is why
   `probe_subprocess.py` is fixed with a bare `subprocess_env()` even
   though it transports no plugin dirs.
7. **Verification commands and evidence.**
   - [x] `pytest tests/unit/core/test_measurement_worker_plugin_transport.py tests/unit/guardrails/test_step11_c0_defect_baselines.py -q`
         → **21 passed**, 18 s.
   - [x] `pytest tests/unit/agent/evaluate_vram_skill -q` → **310 passed**,
         156 s.
   - [x] `pytest tests/unit/core/test_probe_hard_timeout.py tests/unit/guardrails/test_preflight_production_reachability.py tests/unit/core/test_step11_c0_baselines.py -q`
         → **70 passed**, 25 s.
   - [x] **Mutation A** — an env-less `subprocess.Popen` planted in
         `workflows/task_composition.py`, a module the old guard never
         looked at ⇒ `test_every_production_popen_passes_env` **RED**.
         *This is the property the replaced guard did not have.*
   - [x] **Mutation B** — the C1 `env=` removed from `isolated_probe` ⇒
         **2 RED** (the census and the behavioural transport test).
   - [x] **Mutation C** — `env=subprocess_env()` instead of the run-scoped
         call ⇒ `test_the_isolated_preflight_transports_the_run_scoped_dirs`
         **RED**. Passing *an* env is not enough; it must be the RUN's.
   - [x] `ruff check` + `ruff format --check` on every changed file →
         clean.
   - [ ] `pyright` — **NOT RUNNABLE LOCALLY**: the host has Node v10.19.0
         and the vendored pyright requires ≥14, so it aborts in
         `cjs/loader`. CI owns this check (the CLAUDE.md
         "Environment assumptions" case, recorded rather than claimed).
   - [x] `pytest tests/unit/agent/tune_ml_hyperparam_agent tests/unit/nodes -q`
         → first run **20 failed / 1,316 passed** (1,167 s). Diagnosed
         below, fixed, re-run of the 20 → **145 passed**, 21 s.

   **Finding F-11-C1-a — the sandbox test double did not stand in for the
   sandbox.** Every one of the 20 failures surfaced as
   `RecordingLLMBridge: no canned response left for 'generate'` — the
   tuner exhausting its canned plan responses, i.e. attempts failing and
   retrying — which names the LLM harness and not the cause.

   *Source audit*: `tests/helpers/recording_sandbox.py:37` declares
   `RecordingSandbox` as a standalone class, **not** a `TidmadSandbox`
   subclass, and it carries no `plugin_dir` / `loss_dir`. C1's new read of
   `sandbox.plugin_dir` in `execution.py` therefore raised `AttributeError`
   inside `run_admission_preflight`, the attempt failed, and the retry loop
   consumed the fixture queue.

   *Classification*: **test-double gap, not a production defect.** Proven
   at the baseline rather than assumed — a `git worktree` at
   `c1caa609` runs the same three modules **51 passed**, so the failures
   are C1's and are not pre-existing.

   *Fix*: the double now derives both directories through the same public
   authorities the real sandbox uses (`get_plugin_dir` / `get_loss_dir`),
   so it cannot drift from the layout under test.

   *Rejected alternative*: `getattr(sandbox, "plugin_dir", None)` in
   production. It would have made every one of those tests pass while
   silently restoring the exact defect C1 fixes — `None` resolves to the
   legacy global plugin dir. The direct attribute read is the fail-closed
   form and is kept.

   - [x] `pytest tests/unit/agent/tune_ml_hyperparam_agent tests/unit/nodes tests/unit/workflows tests/unit/core -q`
         (the whole `RecordingSandbox` consumer surface, because C1 changed
         a broadly shared test helper — the fail-closed selector rule)
         → **4,497 passed / 1 failed**, 1,592 s.

   **Out-of-scope observation, recorded not fixed (rule 28).** The single
   failure is
   `tests/unit/core/test_step07a_c2_transport.py::TestRungB07a2ValidationScopeAxis::test_real_trainer_emits_r2_and_r3_over_the_validation_family`,
   on a numerical discriminator:

   ```text
   assert abs(h.validation_objective[-1] - train_ref) > 1e-4
   E   assert 3.93986701965332e-05 > 0.0001
   ```

   It trains for real on CPU and asserts that the validation family's loss
   is measurably distinct from the training family's; the observed margin
   missed the threshold by a hair. **Not caused by C1**: the test calls
   `TidmadSandbox.execute_training` directly and touches none of C1's four
   changed modules (isolated pre-flight spawn, its spec, the adapter, the
   tuner's pre-flight call site) — there is no causal path — and it
   **passes in isolation on this branch** (1 passed, 37 s). The ~4e-5
   discrepancy is float-reduction-order noise of the size CPU thread
   scheduling produces under a loaded host. Latent flakiness in a
   pre-existing test's threshold, owned by 07a, not by Step 11.
8. **Commit boundary.** One defect; no calibration or argv work.

   **`probe_subprocess.py` disposition — FIXED, and why that is not scope
   creep.** `spawn_worker` (`:336`) had the identical omission. Verified
   production-UNREACHABLE: its only non-test importer is
   `scripts/runtime_campaign.py`. The design says "record"; recording
   alone, however, would have forced the new census to carry a **by-name
   exemption**, which is the exact F-11-8 / F-P2b-4 shape the census
   exists to replace. It is therefore fixed with a bare
   `env=subprocess_env()`: `ProbeWorkerSpec` declares no run-scoped plugin
   directories, so **nothing is transported and plugin resolution is
   byte-unchanged** — the worker still falls back to the legacy global
   dir. What it gains is the PYTHONPATH extension. The census is now a
   universal rule with zero exemptions.

   **Census scope, stated (C0's own failure mode)**: the rule covers the
   `subprocess.Popen` form — the long-lived supervised worker child. The
   `subprocess.run` calls launching `nvidia-smi`, `git` and `pytest` are a
   different shape and are outside it. Scope is defined by CALL FORM, not
   by a file list. Observation recorded, **not fixed**:
   `nodes/ml_code_validator_agent/ml_code_validator_agent.py:321` runs
   `sys.executable -m pytest` with no `env=`; it launches pytest rather
   than a SIDERIUS worker and is outside both the census and Step 11.

   **Deviation (bounded, process not semantics).** During the first
   mutation pass `git checkout <file>` was used to revert a planted edit,
   which discarded the UNCOMMITTED C1 changes in the same file — the
   `feedback_mutation_proof_hygiene` "git-checkout restores" trap, hit
   exactly as that note predicts. The edits were re-applied from source and
   the whole mutation pass was redone with file backups plus a re-verified
   baseline before and after. No result reported above comes from the
   discarded pass.

### C2 — F-11-1: make the host OOM visible (per Q-11-3)

1. **Goal.** A host OOM must not be invisible to the tuner.
2. **Scope.** The three `oom_host_ram` producers; the tuner's consumer
   branches. **Under Q-11-3 = A, no planner-visible string changes.**
3. **Implementation plan**
   - [x] Implement the Q-11-3 answer (A unless the operator rules B).
         → `records.HOST_RAM_OOM_STATUS` + `records.is_execution_failure`,
         a two-member predicate over `{"error", "oom_host_ram"}`.
   - [x] Make the host-OOM outcome reach a NAMED tuner outcome.
         → both `execution.py` phase branches now ask the ONE authority, so
         a host OOM reaches `_build_execution_failure_record`
         (`error_training` / `error_inference`), `_emit_record`, and
         `next_attempt()` — the existing named outcomes, no new state.
   - [x] Assert the planner prompt bytes are unchanged (A) — the executable
         form of the Gate-1 disposition.
         → `TestPlannerPromptBytes` drives the REAL
         `agent.prompts.get_planner_user_prompt`, not a re-implementation
         of its gate.
4. **Validation plan.** Unit; device-OOM classification unchanged; non-OOM
   errors unchanged; **prompt-byte parity test**.
5. **Acceptance criteria.** A host-OOM training failure reaches an asserted
   tuner outcome; prompt bytes byte-identical under A; C0 guard flips.
   **MET.** A host-OOM record renders **byte-identical** planner prompt
   bytes to the equivalent ordinary failure, and the "NOT ATTRIBUTED" note
   still renders for the device OOM it was written for (the counterfactual,
   without which the parity test would pass on a renderer that had stopped
   emitting the note at all). The C0 inverted guard is **replaced**, not
   duplicated.
6. **Failure/edge cases.** A bare `-9` SIGKILL must remain unattributable —
   `failure_attribution` deliberately returns `unknown`; do not invent a
   fourth failure state. **HELD** — `test_no_fourth_state_is_invented`
   pins `skipped_resource_admission`, `wall_clock_timeout` and `{}` as
   NOT execution failures.
7. **Verification commands and evidence.**
   - [x] `pytest .../test_step11_c2_host_oom_consumer.py tests/unit/guardrails/test_step11_c0_defect_baselines.py -q`
         → **29 passed**, 7 s.
   - [x] **Mutation M1** — the training branch reverted to
         `train_status.get("status") == "error"` ⇒ **2 RED** (the
         reachability census and the no-direct-comparison guard). The
         predicate being merely importable is not enough.
   - [x] **Mutation M2** — `is_execution_failure` narrowed back to
         `== "error"` ⇒ `test_host_oom_is_a_failure` **RED**.
   - [x] **Mutation M3** — `_is_cuda_oom` widened to match the host-OOM
         message, i.e. an accidental slide into **option B** ⇒ **5 RED**,
         including the real-renderer parity test. *This is the executable
         form of "Gate 1 NOT REQUIRED": the PR cannot drift into an
         LLM-facing change without turning red.*
   - [x] `ruff check` + `ruff format --check` on every changed file →
         clean.
   - [x] `pytest tests/unit/agent/tune_ml_hyperparam_agent tests/unit/nodes -q`
         (the consumer surface of the changed `execution.py`)
         → **1,354 passed / 0 failed**, 1,165 s.
8. **Commit boundary.** No OOM-matcher consolidation (F-11-9 is a non-goal).

   **Finding F-11-C2-a — the scoring producer has no consumer BRANCH at
   all, and that is not C2's to build.** §3.3 names the tuner's two
   branches (`execution.py:711,882`). The third producer
   (`sandbox_executor.py:2116`, `execute_scoring`) has no counterpart:
   the tuner's scoring block never inspects `score_res["status"]` — it goes
   straight to `score_res.get("results", {})` (`execution.py:1187`), so
   even a plain `"error"` from that path is silently read as empty results.
   The modern Step-06 route (`sandbox.evaluate_metric`) RAISES and is
   caught by the block's own `except Exception`, which is why this has not
   been felt; the status-returning route is the legacy
   `_run_skill("denoising_score_skill", …)` branch.

   Adding a status branch there is **a new branch family in an already
   oversized function** — precisely what the R-11-11 tripwire forbids —
   and it is a DIFFERENT defect from F-11-1 ("a status is produced and
   never consumed"): here the consumer does not read ANY status. Recorded
   as named debt, deliberately not fixed inside C2's boundary.

   Consequence, stated so no later claim overreaches: after C2 the host-OOM
   status is consumed on the **training and inference** paths. The scoring
   path is unchanged in both directions.

   **Census correction made during the flip.** The replacement guard first
   compared raw file TEXT and went RED on a *comment* in `execution.py`
   naming the status. Rather than add a by-name exclusion — the shape this
   PR keeps removing — the census now counts the status as a **code string
   literal** via AST, excluding comments and docstrings. That also retired
   the `failure_attribution.py` prose exemption the C0 version carried, so
   the census has **zero** allow-list entries and a `== "oom_host_ram"`
   anywhere still turns it RED.

### C3 — Resource ceilings become declared calibration (R-11-5, R-11-6)

1. **Goal.** Ceilings stop being undocumented constants and start recording
   what they derive from.
2. **Scope.** The ceiling table and resolver; a calibration declaration;
   the run-invariants record; F-11-3.
3. **Implementation plan**
   - [x] Declare the ceilings with machine-readable provenance
         (measured-on, device, derived-from). Calibration config, **NOT**
         task config (§9.2).
         → **new module `core/execution_calibration.py`** (R-11-11: the
         launch path stays a CONSUMER). `RoleCeiling` carries `gib`,
         `derivation` (a `Literal`, so an auditor can FILTER rather than
         read prose), `set_on`, `calibrated_for`, `rationale`.
   - [x] Implement R-11-5 precedence exactly; preserve the `0` disable
         semantics; REFUSE malformed values loudly.
         → `resolve_role_ceiling_gb(role, *, environ=None)` and the typed
         `MalformedCeilingOverride`. `core/sandbox_executor.py`'s
         `_subprocess_rss_gb` is now a one-line delegate; the name and the
         `_ROLE_DEFAULT_RSS_GB` mapping are kept because that is what this
         launch path and its tests have always called.
   - [x] Implement R-11-6: record ceilings in the lock, recorded-not-
         enforced.
         → `RunInvariants.execution_calibration`, stamped by
         `build_run_invariants` (the ONE shared builder, for the reason
         C9d is stamped there), OMITTED from the serialized lock when
         `None` so a pre-C3 lock stays byte-identical.
   - [x] **F-11-3**: re-derive or retire the 60 GiB justification, whose
         cited anchor is now argmax code and whose dtype is task-declared.
         → **RETIRED, not restated.** Re-deriving needs a measurement this
         PR cannot honestly make, so the value is kept (full-scope baseline
         inference genuinely fails at 40 GiB) and its `derivation` is
         `"empirical_unverified"` — a machine-readable statement that the
         recorded arithmetic no longer describes the path it governs. The
         retired anchor is still NAMED in the rationale so a future reader
         can see what was retired. The stale prose is deleted from
         `sandbox_executor.py`, pinned by a test.
4. **Validation plan.** Unit; TIDMAD ceilings resolve to the SAME 40/60/24
   (C0 baseline); negative tests for malformed and zero overrides.
5. **Acceptance criteria.** TIDMAD's resolved ceilings byte-identical to
   C0; every ceiling carries checkable provenance; a malformed override
   refuses instead of silently defaulting. **ALL MET** — the C0 baseline
   class is unmodified and still green.
6. **Failure/edge cases.** Unknown role still raises; a rerun on a
   different host must not be refused (R-11-6). **BOTH HELD**, the second
   asserted end-to-end against the real lock via `ensure_run_invariants`,
   with the counterfactual that a `resolved_data_scope` change is still
   refused.
7. **Verification commands and evidence.**
   - [x] `pytest tests/unit/core/test_step11_c3_execution_calibration.py -q`
         → **29 passed**.
   - [x] `pytest tests/unit/core/test_run_invariants.py .../test_step11_c3_* .../test_step11_c0_baselines.py .../test_sandbox_rlimit.py -q`
         → **117 passed**, 3 s.
   - [x] **Mutation M1** — the silent fallback restored on a non-integer
         override ⇒ **17 RED**.
   - [x] **Mutation M2** — `execution_calibration` moved into `_CANONICAL`
         ⇒ **3 RED**, including `test_a_resume_under_different_host_calibration_stays_legal`.
         *This is R-11-6's added operator constraint working: the mistake it
         warns about is caught structurally, not by a validator remembering.*
   - [x] **Mutation M3** — the inference ceiling changed 60 → 48 ⇒ **7 RED**
         across the C0 baseline, the rlimit tests and the provenance payload.
   - [x] **Mutation M4** — the shared builder stops stamping the field ⇒
         `test_build_run_invariants_populates_the_calibration` **RED**. The
         field existing on the model proves nothing if no writer fills it.
   - [x] `ruff check` + `ruff format --check` → clean.
   - [x] `pytest tests/unit/core tests/unit/workflows tests/unit/scripts tests/unit/guardrails -q`
         → **3,969 passed / 7 failed**, 678 s. All seven diagnosed, none a
         production defect:
         · **5** — the C0 structural test, which pinned LINE NUMBERS and
           exact file LOC. C3 deleted 35 lines of stale prose and moved
           every anchor while changing **no function's shape at all**
           (`execute_training` 92/39/357/14 before and after; likewise all
           four). That is a tripwire firing on the wrong signal, and it was
           a design error in the C0 test rather than a finding — see below.
         · **1** — `test_step09_5a_c0_oracle`, the frozen workflow-envelope
           differential. It correctly detected C3's declared additive lock
           key; delta declared and golden edited surgically (below).
         · **1** — `test_pr3_l2p_preflight::test_preflight_all_invariants`,
           which fails when production files are modified UNCOMMITTED. That
           is the PR3-L2 guard working exactly as CLAUDE.md documents; it
           passes from the committed tree and must never be relaxed.
   - [x] Re-run after the two corrections:
         `pytest tests/unit/guardrails/test_step11_c0_defect_baselines.py tests/unit/workflows/test_step09_5a_c0_oracle.py -q`
         → **16 passed**.
   - [x] **Mutation M5** — 45 planted `if` branches (+90 lines) inside
         `execute_training` ⇒ the rewritten budget turns **RED**
         (`assert (84 - 39) <= 3`). The tripwire now fires on growth, which
         is what R-11-11 asks it to detect.

   **Correction to a C0 test of this PR's own making.** `TestStructuralBaseline`
   asserted `(lineno, stmts, branch, loc, params)` equality and an exact file
   LOC, which makes ANY edit elsewhere in a 2,400-line module red — including
   the deletion C3 exists to perform. R-11-11's contract is a **budget**:
   *"if a commit would add a new branch family, a new schema resolution, or
   ~80-150 lines to one function, extract first."* Growth is the signal;
   shrinkage is the direction the rule wants. It is now `TestStructuralBudget`:
   the frozen §4a numbers stay as DATA (pinned by their own test, so the budget
   is measured against the design's published figures and not a drifting
   snapshot), and the assertions are deltas — branch +3, LOC +80, params +1,
   file +150 — plus a guard that a baselined function cannot pass by having
   been renamed away. C9 still re-measures and records the real numbers via
   `current_structure()`.

   **Measured C3 structural delta**: file **2,456 → 2,421 LOC (−35)**; all four
   baselined functions **byte-identical in shape**. C3 moved semantics OUT of
   the launch consumer, which is the R-11-11 direction.
8. **Commit boundary.** Declaration only — no task-derived ceilings
   (that would need Q-11-1 = B).

   **Two pre-existing tests UPGRADED, not deleted** (test-disposition
   audit). `test_sandbox_rlimit.py::test_env_non_numeric_falls_back_to_role_default`
   and `::test_env_negative_falls_back_to_role_default` asserted the SILENT
   fallback R-11-5 replaces. Their functional intent — *what happens on a
   malformed override* — is preserved; the expected answer changed from
   "the role default, quietly" to "a refusal". A third case was added
   pinning that the stricter parser did not swallow the `0` escape hatch.

   **R-11-6's representational requirement, implemented.** `_CANONICAL`
   gained a declared counterpart `_PROVENANCE`, and a guard asserts the two
   **PARTITION** every declared field — a new field is either a semantic
   invariant or execution provenance and cannot be neither. That is the
   difference between "the ceilings are absent from the canonical tuple"
   (a validator remembering) and "the ceilings are declared as provenance"
   (a property of the representation). The partition is asserted by a test
   rather than at import time, so a naming slip is a test failure and not a
   repo-wide import error.

### C4 — The data root becomes a transported run binding (R-11-7, R-11-8)

1. **Goal.** The physical data root reaches every child because the run
   declared it.
2. **Scope.** The composition carrier; `dirs["data"]` and
   `TidmadSandbox.__init__`; the three argv builders and three child
   defaults; `HyperparamTuningInput.data_dir` reconciliation.
3. **Implementation plan**
   - [x] Carry the resolved root on the run binding, **provenance-only**
         (R-11-7).
         → `execute_tools/data_paths.py` gains a run-scoped ContextVar
         binding — `bind_physical_data_root` / `active_physical_data_root`
         / `resolve_physical_data_root` — mirroring `task_data_path`'s
         pattern, including its `active_*` vs `resolve_*` split. It lives
         in `data_paths.py` because that module already owns *where the
         data physically lives*; a new module would have created the second
         concept R-11-7 says to reconcile away.
         **Deliberately NOT a field on `RunTaskComposition`**: a host path
         is execution provenance, and keeping it off the carrier makes it
         impossible for it to reach the semantic fingerprint.
   - [x] Thread it into the sandbox instead of `_tidmad_data_dir()`.
         → `dirs["data"] = resolve_physical_data_root()`.
   - [x] Transport it across training, inference and scoring argv,
         following the `--task_data_path_id` precedent (additive, emitted
         only when composed — R-11-1).
         → `_data_root_argv(flag)`, emitted from `active_*` (no fallback).
   - [x] Reconcile `HyperparamTuningInput.data_dir` to the same authority.
         → the tuner's `time_data_dir` now prefers the BOUND root and falls
         back to `agent_input.data_dir` — so a composed run prices its
         warmup against the disk its children read, and an un-composed run
         is byte-identical **including `None`**, which keeps its meaning of
         "no warmup, use the static-formula estimate". The field's
         description now states which authority wins.
   - [x] Implement R-11-8's composed fail-closed check. **Do not remove the
         import-time fallback.**
         → `CompositionDataRootMissing` raised by `bind_run_task_composition`
         when a composition is supplied with no root; the binding itself
         validates through `resolve_dataset_dir`, the ONE fail-closed rule.
         `verify_composition_is_bound` gained `physical_data_root` to its
         unbound list. The import-time fallback is untouched.
   - [x] R-11-11 check before writing: `execute_training` is already 357
         LOC / 14 params — extract rather than extend if this adds a branch
         family.
         → **no branch family added**: the transport is a single
         `*_data_root_argv(...)` splice in each builder, and the decision
         lives in the helper. Post-C4 shapes are unchanged from the C0
         baseline (see §11).
4. **Validation plan.** Unit; **un-composed argv byte-parity** vs C0; a
   composed manifest resolving a different root; negative: composed run
   with a missing/placeholder root fails closed.
5. **Acceptance criteria.** Un-composed argv byte-identical to C0; a
   composed run's children receive the declared root; CI (which resolves
   the template root) still passes. **ALL MET.**
6. **Failure/edge cases.** Missing root, placeholder root, non-directory —
   `DatasetDirectoryUnavailable` is the existing vehicle. **All three
   covered**, plus the empty-string case below.
7. **Verification commands and evidence.**
   - [x] `pytest tests/unit/core/test_step11_c4_data_root_transport.py -q`
         → **22 passed**.
   - [x] **Mutation M1** — the root emitted UNCONDITIONALLY ⇒ **5 RED**,
         including all three C0 legacy argv baselines. R-11-1 is enforced,
         not merely intended.
   - [x] **Mutation M2** — scoring's root emitted as `--data_dir` instead of
         `--raw_data_dir` ⇒ **1 RED**. See the flag-mapping finding below.
   - [x] **Mutation M3** — the composed fail-closed check disabled ⇒
         **2 RED**.
   - [x] **Mutation M4** — the sandbox reverted to `_tidmad_data_dir()` ⇒
         **1 RED**.
   - [x] `ruff check` + `ruff format --check` → clean.
   - [x] `pytest tests/unit/core tests/unit/workflows tests/unit/agent/tune_ml_hyperparam_agent tests/unit/nodes tests/unit/execute_tools tests/unit/guardrails -q`
         → **6,631 passed / 55 failed**, 2,046 s.
         **54 of the 55 are the new fail-closed contract firing at TEST call
         sites** — `CompositionDataRootMissing` from 32 `bind_run_task_composition(...)`
         calls across seven Step-10 modules that compose in order to exercise
         something else. That is the same shape C1 produced at
         `run_production_preflight`: a keyword the production entrypoint must
         not default, so every caller states it.
   - [x] Call sites UPGRADED, not weakened, and not defaulted away in
         production: a new `tests/helpers/composition_data_root.py` supplies
         `COMPOSED_TEST_DATA_ROOT`, **derived from the current checkout**
         (`Path(__file__).resolve().parents[2]`) per the repository-portability
         rule — never a hardcoded absolute path that would keep resolving on
         one machine and fail on CI. Re-run of all seven modules →
         **123 passed**, 10 s.

   **Out-of-scope observation #2, recorded not fixed (rule 28).** The 55th
   failure is
   `tests/unit/execute_tools/test_rt2c_training_verification.py::TestVerifiedPath::test_live_steps_verify_and_training_completes`
   (`assert (None is not None)` — no training summary). It calls
   `run_experiment_streaming` directly with a tiny fixture: **no sandbox, no
   argv, no composition, no data-root binding**, so no C4 change is on its
   path; and it **passes in isolation on this branch** (1 passed, 4.5 s). Its
   admission stage is time-thresholded (`operator_budget_seconds`,
   `verification_cost_seconds > 0.0`), so a host saturated by a 34-minute
   sweep can starve it.

   Together with the C1 observation this is **one pattern worth naming**: two
   real-training tests sit in the *unit* tier with verdicts that depend on
   host timing — a marginal numeric discriminator in one, an admission
   deadline in the other. Both are green in isolation and flaky under load.
   That is a test-topology issue owned by 07a/RT2-C, not by Step 11, and it is
   exactly the "could a Unit fixture manufacture the state whose TIMING is the
   property?" question the execution-rules document uses to assign a property
   to Gate 2 instead.
8. **Commit boundary.** Data root only; metric acquisition is C5, naming is C6. **No scope transport (R-11-12).**

   **Finding F-11-C4-a — the three children do not share one flag name, and
   the difference is load-bearing.** Audited rather than assumed:

   ```text
   training   --data_dir       = the DATASET root      (default None -> TIDMAD_DATA_DIR at import)
   inference  --data_dir       = the DATASET root      (default None -> TIDMAD_DATA_DIR at import)
   scoring    --data_dir       = the DELIVERABLE dir   (parent already passes self.base_dir)
   scoring    --raw_data_dir   = the DATASET root      (NO emitter at all; import-time fallback only)
   ```

   §3.1's table records that training and inference "pass no `--data_dir`".
   The scoring child is a further case the table does not spell out: its
   `--data_dir` is already occupied by the sandbox directory, and its
   dataset root is `--raw_data_dir` (`denoising_score_single.py:148-149`),
   which nothing emitted. Emitting the root as `--data_dir` for scoring
   would have pointed the raw-baseline read at the sandbox — mutation M2 is
   exactly that mistake, and it turns the transport test RED.

   **Finding F-11-C4-b — a production defect caught by C4's own negative
   test.** `bind_physical_data_root("")` initially delegated straight to
   `resolve_dataset_dir`, which treats a falsy `explicit` as *"no override
   supplied"* and falls back to `TIDMAD_DATA_DIR`. That fallback is correct
   at the LAUNCH boundary and wrong at the BINDING edge: binding an empty
   string is a caller stating a root, and silently resolving it to TIDMAD's
   is the exact substitution R-11-8 forbids. The binding now refuses an
   empty or whitespace root before it reaches the resolver.

   **Bug caught in implementation, recorded because the failure mode is
   instructive**: the new exception class was first inserted BETWEEN
   `@contextmanager` and `bind_run_task_composition`, so the decorator
   silently attached to the class and every composed-binding test failed
   with `TypeError: Expected a BaseException type, but got 'function'` —
   a message that names neither the decorator nor the function.

### C5 — Scoring metric via the Step-10 authority (R-11-4)

1. **Goal.** The scoring child stops unconditionally deriving TIDMAD's
   metric, so the spawn surface is task-neutral in all three roles.
2. **Scope.** `denoising_score_single.py` metric acquisition; the transport
   carrier; the Step-10 metric binding authority (consumed, never
   redefined).
3. **Implementation plan**
   - [x] **Audit first**: what does the scoring child actually consume from
         the metric? Do not speculatively transport secondaries.
         → **Audit result** (this is what shaped the transport, so it is
         recorded rather than summarised):
         · the metric is used at **exactly ONE** site,
           `metric.evaluate(...)` (`denoising_score_single.py:284`);
         · `evaluate` needs a real `EvaluationMetric` **INSTANCE** — the
           spec's `id`/`direction`, its executable `scoreability` contract,
           and the implementation's `_compute`;
         · an instance is a `MetricSpec` (from a JSON declaration, via
           `metric_spec_from_declaration`) **plus** an implementation CLASS
           loaded from a symbol ref (`_compose_metric`,
           `task_composition.py:558`);
         · **`RunTaskComposition` retains NEITHER** — only the resolved
           instance — and an instance cannot cross a process boundary.
         Consequence: what crosses is the run's **manifest path**, and the
         child re-composes the metric section through the same authority.
         Secondaries are NOT transported (R-11-4), asserted by a test.
   - [x] Replace the unconditional `derive_tidmad_metric` with acquisition
         through the Step-10 authority.
         → new PUBLIC `compose_metric_from_manifest(manifest_path)`, a thin
         entry over `_compose_metric` that composes **only** the metric
         section — a scoring child must not re-resolve the profile, the
         Health family or the interpretation blocks. Transported by a
         narrow `bind_task_manifest_path` / `active_task_manifest_path`
         ContextVar pair bound on the composition's existing ExitStack, and
         emitted by `_task_manifest_argv()` into the **scoring argv only**:
         it is the one child that constructs a metric.
   - [x] Keep the un-composed path byte-identical — the current derivation
         is a documented Step-06 choice and stays the legacy branch.
         → `if args.task_manifest is not None: … else: derive_tidmad_metric(…)`.
         Discrimination is by transported-value PRESENCE, never a task name.
4. **Validation plan.** Unit; un-composed scoring parity (same score, same
   record keys); a composed run using its declared metric; negative: a
   composed run whose metric cannot be acquired refuses rather than falling
   back to TIDMAD.
5. **Acceptance criteria.** Zero unconditional TIDMAD metric derivations
   remain in the scoring child; the frozen TIDMAD score is unchanged for
   un-composed runs. **BOTH MET** — the first asserted by an AST census over
   module-scope calls (not a substring), the second by the legacy branch
   test plus the C0 legacy argv baseline.
6. **Failure/edge cases.** A composed run must never silently score with
   TIDMAD's metric — that is the C-P56-1 failure class one layer down.
   **HELD, structurally**: an AST guard fails if the composed acquisition is
   ever wrapped in a `try`, because a recovery there is exactly that failure
   class. Mutation M2 is that mistake and it turns the guard RED.
7. **Verification commands and evidence.**
   - [x] `pytest tests/unit/execute_tools/test_step11_c5_scoring_metric_acquisition.py -q`
         → **22 passed**.
   - [x] Composed acquisition exercised against the SHIPPED
         `configs/task_composition/tidmad.yaml`, with the expectation read
         from the declaration FILE (the input) rather than from the composed
         instance (the output) — not self-referential.
   - [x] **Mutation M1** — the unconditional derivation restored ⇒ **2 RED**.
   - [x] **Mutation M2** — a `try/except` fallback added around the composed
         acquisition ⇒ **1 RED** (the no-fallback guard).
   - [x] **Mutation M3** — the manifest emitted unconditionally ⇒ **2 RED**,
         including the C0 legacy scoring argv baseline.
   - [x] **Mutation M4** — the composer widened to also resolve the task
         config ⇒ **3 RED** (compose-only-the-metric).
   - [x] Reachability through the REAL launch: a composed
         `execute_scoring` carries `--task_manifest`; a composed
         `execute_training` does **not**.
   - [x] `ruff check` + `ruff format --check` → clean.
   - [x] `pytest tests/unit/execute_tools tests/unit/workflows tests/unit/core -q`
         → **5,071 passed / 0 failed / 2 skipped**, 487 s. (Notably the two
         load-flaky real-training tests both passed here — this sweep is
         8 minutes rather than 34, which is consistent with the host-load
         diagnosis recorded under C1 and C4.)
8. **Commit boundary.** Metric acquisition only; no metric semantics, no
   direction logic, no scoring arithmetic.

   **Design decision recorded (R-11-4's "transport, never derive").** Three
   transports were considered:
   (a) serialize the resolved metric — impossible, the implementation is a
   class;
   (b) carry a declaration payload + implementation ref on the composition —
   would require `RunTaskComposition` to retain what `_compose_metric`
   currently discards, i.e. a new carrier and a new serialization;
   (c) **carry the manifest PATH** and let the child call the same authority.
   (c) was taken: it adds no schema, no second declaration format and no new
   semantics, and it follows the child's own established pattern —
   *reconstruct from what crosses, one derivation, the same value the parent
   holds* — with the TIDMAD-shaped source replaced by the run's declared one.

   **Why the binding is a bare path and not the composition.** Binding the
   whole `RunTaskComposition` would have been easy and is what this module's
   own rule forbids: *"binding a ContextVar for a value that already has an
   explicit path would create a second way for it to arrive."* One
   transportable string, one consumer.

### C6 — Deliverable naming flows FROM the contract (R-11-3)

1. **Goal.** A composed task's deliverable is named by the Deliverable
   Contract, so cleanup globs stop matching filenames a contrast run never
   wrote.
2. **Scope.** The deliverable derivation; the run binding carrier; the two
   cleanup sites, which are already contract READERS.
3. **Implementation plan**
   - [x] Carry the **resolved** naming declaration on the run binding.
         **The composition must NOT become a second naming authority
         (R-11-3).**
         → an OPTIONAL `deliverable:` manifest section, validated by
         `DeliverableNaming` **itself**; the resolved instance is carried on
         `RunTaskComposition.deliverable_naming` and bound run-scoped by
         `bind_deliverable_naming`. Not one naming rule is restated in the
         composition layer — pinned by a test that inspects
         `_compose_deliverable_naming`'s own AST.
   - [x] Keep TIDMAD's defaults byte-identical when undeclared.
         → TIDMAD's manifest declares no section ⇒ `None` ⇒ nothing bound ⇒
         `resolve_deliverable_naming()` returns the shipped naming. Verified
         against the SHIPPED manifest end-to-end.
4. **Validation plan.** Unit; TIDMAD glob byte-parity vs C0; a composed
   task producing a different glob; an authority census proving one owner.
5. **Acceptance criteria.** Both cleanup sites consume the declared
   template with no change at the call sites; exactly one naming authority
   exists. **BOTH MET** — resolution was placed at the two points a naming
   is CONSTRUCTED (`TidmadSandbox` and `derive_tidmad_deliverable_spec`), so
   `self.deliverable_naming.attempt_glob(...)` and
   `run_deliverable_spec.naming.experiment_glob(...)` are untouched.
6. **Failure/edge cases.** An empty or malformed template must refuse, never
   produce a glob matching everything. **HELD** — seven declaration cases
   refuse, and every rule is the CONTRACT's.
7. **Verification commands and evidence.**
   - [x] `pytest .../test_step11_c6_deliverable_naming.py -q` → **24 passed**.
   - [x] **Mutation M1** — the derivation ignores the binding ⇒ 1 RED.
   - [x] **Mutation M2** — `extra="forbid"` removed ⇒ 1 RED.
   - [x] **Mutation M3** — the composition stops binding a declared naming ⇒
         **SURVIVED at first**, see the finding below; **1 RED** after the
         gap was closed.
   - [x] **Mutation M4** — a second naming authority planted in
         `sandbox_executor.py` ⇒ 1 RED.
   - [x] **Mutation M5** — the naming dropped from the fingerprint ⇒ 1 RED.
   - [x] `ruff check` + `ruff format --check` → clean.
   - [x] `pytest tests/unit/execute_tools tests/unit/workflows tests/unit/core tests/unit/scripts -q`
         → **5,593 passed / 1 failed**, 422 s. The single failure is
         `test_pr3_l2p_preflight::test_preflight_all_invariants`, the
         uncommitted-production-file guard, which is expected from a
         work-in-progress tree and passes from the committed one.
8. **Commit boundary.** Naming only.

   **Finding F-11-C6-a — a SURVIVING mutation, and what it exposed.**
   Disabling the `bind_deliverable_naming` call inside
   `bind_run_task_composition` left every test green. The reason is worth
   recording: the only composition under test was TIDMAD's, which declares
   **no** naming, so the branch was never taken by any fixture. The tests
   were exercising the un-declared path exhaustively and the declared path
   not at all — a coverage shape that looks complete and proves nothing
   about the hop that matters. Closed by
   `test_a_COMPOSED_run_binds_its_declared_naming_end_to_end`, driven from a
   materialized manifest that DOES declare naming; the mutation is now RED.

   **Finding F-11-C6-b — `DeliverableNaming` had no `extra="forbid"`.** A
   composition DECLARES naming in a manifest, so a misspelled key
   (`prefix_` for `prefix`) would have been silently ignored and the
   composed task would have resolved the SHIPPED TIDMAD template: plausible
   names, and a cleanup glob deleting files the run never wrote. Added, in
   the contract type where it belongs — the same posture `MetricSpec`
   already takes and the same reasoning `_MANIFEST_KEYS` uses one level up.
   All four pre-existing `DeliverableNaming(...)` constructors still pass.

   **Test-fixture correction, recorded because it is the "green for the
   wrong reason" shape again.** C6's first negative fixtures were manifest
   FRAGMENTS. `_read_manifest` refuses a manifest missing a required
   section, so every one of them raised — and would have kept raising after
   the naming validator was deleted. The fixtures now materialize COMPLETE
   manifests (`tests/helpers/composed_manifest.py`, built from the shipped
   TIDMAD manifest with refs absolutized, derived from the checkout). The
   same defect was found and fixed in **C5's**
   `test_a_declared_implementation_that_is_not_a_metric_refuses`, which was
   never reaching the `isinstance` branch it named; it now uses a complete
   manifest and a symbol that constructs successfully, and the
   instantiation-failure branch is pinned separately.

   **The fingerprint.** A declared naming JOINS the semantic fingerprint —
   it decides deliverable file identity, so two runs naming their outputs
   differently are not the same run. Added only when declared, following the
   `secondary_metric_declarations` precedent, so an un-declared manifest's
   fingerprint is unchanged (verified: TIDMAD's is `d6628a93…` before and
   after).

### C7 — Spawn hygiene (F-11-4, F-11-7)

1. **Goal.** Remove accidental couplings that make the surface fragile.
2. **Scope.** `cached_models` / `records` name derivation; the three
   relative script paths; the stale launch-split docstring.
3. **Implementation plan**
   - [x] One authority for the sandbox subdirectory names, following the
         `get_plugin_dir` / `get_loss_dir` precedent in the same file.
         → `SANDBOX_SUBDIR_MODELS` / `SANDBOX_SUBDIR_RECORDS` +
         `sandbox_models_dir()` / `sandbox_records_dir()`, called by the
         parent AND by `train_engine_sandbox.py`.
   - [x] Anchor the three script paths absolutely; keep `cwd` semantics.
         → `SIDERIUS_ROOT` (resolved from the module file, the convention
         every peer already uses — `core/subprocess_env.py:68`,
         `execute_tools/data_paths.py:23`) and `child_script_path()`. All
         three `cwd=os.getcwd()` launches are untouched, asserted by an AST
         count of `cwd=` keywords rather than a substring.
   - [x] Correct the launch-split justification (§3.5) — the cited
         `timeout --signal=INT` mechanism does not exist; the real anchor
         is the foreground process group plus the chain trap. **Fix the
         reason, never the behaviour.**
         → both the docstring and the inline comment now name
         `run_chain.sh:171` and
         `_chain_common.sh::install_chain_stop_traps`, and record that the
         previous citation was wrong. **Zero behavioural lines changed.**
4. **Validation plan.** Unit; a parity test proving parent and child derive
   the SAME paths; mutation: a planted divergent literal turns it RED.
5. **Acceptance criteria.** The parent/child agreement is enforced rather
   than coincidental. **MET** — plus a census proving no module rebuilds
   either name from a literal outside its authority.
6. **Failure/edge cases.** The `_OK_` sentinel read depends on the match; a
   mismatch currently produces a FALSE `error_training`. Stated in the
   module docstring so the next reader knows what a divergence looks like.
7. **Verification commands and evidence.**
   - [x] `pytest tests/unit/core/test_step11_c7_spawn_hygiene.py -q` →
         **16 passed**.
   - [x] **Mutation M1** — the child rebuilds `cached_models` from a literal
         ⇒ **2 RED** (the parity test and the census).
   - [x] **Mutation M2** — a child script named relatively again ⇒ 1 RED.
   - [x] **Mutation M3** — the plain launch given `start_new_session=True`,
         i.e. the operator-stop-critical split "unified" ⇒ 1 RED.
   - [x] **Mutation M4** — a shell launcher adopts `timeout --signal` ⇒
         1 RED. *This one is deliberate: if a launcher ever DOES adopt it,
         the corrected justification must be revisited rather than quietly
         re-inverted.*
   - [x] `ruff check` + `ruff format --check` → clean.
   - [x] `pytest tests/unit/core tests/unit/execute_tools tests/unit/agent/tune_ml_hyperparam_agent -q`
         → first run **5,746 passed / 5 failed**, 1,053 s; the five are
         pre-existing argv GOLDENS and the finding below is why. After the
         declared normalization: those three modules **16 passed**.

   **Finding F-11-C7-a — C7 changes ONE legacy argv token, and R-11-1 has to
   be read carefully here. Flagged for operator attention.**

   Anchoring the child scripts absolutely changes argv index 1 from
   `execute_tools/train_engine_sandbox.py` to an absolute path — on the
   LEGACY, un-composed path. Five frozen goldens (Step 05c C0, Step 06 C0,
   Step 07a C2) pin the full ordered argv and went RED on exactly that
   token and nothing else.

   R-11-1's legacy row says argv is **byte-identical**. C7's own frozen
   checklist says **"anchor the three script paths absolutely"**. Both are
   in the same frozen document, so they are reconciled rather than
   traded off:

   * R-11-1 exists to stop the TRANSPORT mechanism from altering an
     un-composed command line — its whole subject is *"composed argv MAY
     gain additive declared arguments"*, and it is paired with "proven
     against the C0 census", which is scoped to the OPTION token set;
   * C7 is not a transport. It adds no argument, removes none, reorders
     none, and changes no behaviour: the same script runs, with the same
     `cwd`, from the same interpreter. What changes is how the interpreter
     FINDS the file.

   **The flag set is byte-identical; one positional value is more robust.**
   The three C0 legacy argv baselines remain green throughout.

   *Disposition of the five goldens*: NOT re-baselined and NOT weakened.
   Their existing `_normalize` helper — which already maps `sys.executable`
   and the tmp workspace — now also maps a repo-rooted `.py` token back to
   its repo-relative form. Two reasons, both binding: a golden must never
   embed a machine-specific absolute path, and these goldens exist to pin
   the ARGUMENT LIST, while the anchoring mechanism is owned and proven
   (absolute, existing, cwd-independent) by C7's own tests. A script path
   that became absolute but WRONG — pointing outside this checkout — is not
   normalized and still turns them RED.
8. **Commit boundary.** No change to kill/cleanup semantics.

   **The §3.5 correction, verified rather than accepted.** `grep` over every
   `*.sh` in the repository returns **zero** hits for `timeout --signal`, so
   the mechanism the docstring cited genuinely does not exist. The
   replacement anchor is asserted to exist too — `run_chain.sh:171`'s
   foreground `(cd "$PROJECT_DIR" && "${cmd[@]}")` and
   `_chain_common.sh`'s `trap '_chain_note_signal SIGINT'  INT` — because
   naming a second mechanism that is also absent would repeat the finding
   rather than fix it.

   **Assertion corrected during implementation.** The cwd check was first a
   substring count (`src.count("cwd=os.getcwd()") == 3`) and went RED at 4 —
   the fourth occurrence being the new explanatory COMMENT. Counting prose
   as behaviour is the wrong instrument; it is now an AST count of actual
   `cwd=` call keywords.

### C8 — Invariants and resume (F-11-5, F-11-6, R-11-9)

1. **Goal.** Remove the last task token from the resume path and close the
   ingress-vs-lock asymmetry.
2. **Scope.** `resume.py`'s `full_scope` derivation and `TIDMAD` import;
   `validate_stamped_invariants` and its four hand-built call sites.
3. **Implementation plan**
   - [x] Replace `list(range(TIDMAD.num_files))` with the composed
         profile's `num_files`, as the sibling site already does; drop the
         import.
         → `resolve_dataset_profile().dataset.num_files`, which honours a
         bound profile and otherwise returns the shipped one, so an
         un-composed resume is unchanged.
   - [x] Implement **R-11-9**'s three-case table exactly.
         → in `validate_stamped_invariants`, keyed on whether THIS RUN is
         composed — never on a task name.
4. **Validation plan.** Unit; legacy unstamped record readable in legacy
   mode; composed + fingerprint mismatch refuses; composed + unstamped
   legacy refuses under the named rule.
5. **Acceptance criteria.** `core/resume.py` contains zero task tokens; all
   three R-11-9 cases have a named test. **BOTH MET** — the token census is
   AST-based over names, attributes and string constants, so the comment
   recording what was removed does not satisfy it.
6. **Failure/edge cases.** Step 10 omits the key rather than serializing
   `null`; that must stay true so legacy locks remain byte-identical.
   **Unchanged** — C8 touches the ingress validator, not the lock writer,
   and C3's own test still asserts the omission.
7. **Verification commands and evidence.**
   - [x] `pytest tests/unit/core/test_step11_c8_invariants_resume.py -q` →
         **17 passed**.
   - [x] **Mutation M1** — the absence branch disabled ⇒ **SURVIVED at
         first**, see the finding below; **1 RED** after the test was fixed.
   - [x] **Mutation M2** — the whole fingerprint check removed ⇒ 2 RED.
   - [x] **Mutation M3** — the persist seam stops stamping ⇒ 1 RED.
   - [x] **Mutation M4** — the `TIDMAD.num_files` token restored ⇒ 3 RED.
   - [x] `ruff check` + `ruff format --check` → clean.
   - [x] `pytest tests/unit/core tests/unit/workflows tests/unit/agent/tune_ml_hyperparam_agent tests/unit/nodes tests/unit/execute_tools tests/unit/scripts -q`
         → **6,980 passed / 1 failed**, 1,178 s; the one failure is the
         uncommitted-tree guard, which passes from the committed tree.

   **Getting there took two corrections, both recorded because the first was
   my own defect.** The first sweep reported **149 failed / 35 errors**:
   147 were `TypeError: RunBindings.__init__() got an unexpected keyword
   argument` — the output stamp was passed into `RunBindings`, which did not
   declare it. Fixed by declaring it there (beside `health_config_sha256`,
   which it mirrors) and stamping the OUTPUT in `records.py` where that sha
   is stamped. The second sweep reported **29**, in two honest classes:

   * **23 composed-seed refusals** — R-11-9 case 3 firing on hand-built
     seeds in the three-task composed tests. Diagnosed as STALE FIXTURES,
     not a semantic break: `_write_seed`'s own docstring already said the
     seed is *"composition-consistent by construction"* and that an
     inconsistent one is *"correctly refused… the system working"*. C8 only
     widened what consistent covers, so the fixtures now stamp the
     composition's fingerprint exactly as they already stamp its metric.
     **Production checked separately**: `run_comparison.py` never composes,
     so its `expected.task_composition_fingerprint` is `None` and the branch
     cannot fire there; the composed paths seed from tuner OUTPUTS and
     workspace records, both of which now carry the stamp.
   * **6 additive-field goldens** — the record field list (`61 -> 62`, with
     the delta documented inline in the same style as the Step-06, 07a and
     P2b entries above it), two REC-2 projections, two REC-3 shape lists and
     the Step-09.5a envelope oracle. Every one edited SURGICALLY after
     measuring the delta, and each measurement asserted **exactly one ADDED
     key, zero changed, zero removed** before the file was touched. The
     helper's policy — *"tests never write goldens"* — was respected.
8. **Commit boundary.** No invariants beyond R-11-9.

   **Finding F-11-C8-a — R-11-9 was UNSATISFIABLE as literally written, and
   closing it required an additive stamp.** The frozen table's second row
   speaks of *"a record that CARRIES a fingerprint"*. Audited: **nothing
   carried one.** `task_composition_fingerprint` existed only on
   `RunInvariants` — the workspace lock — and neither `ExperimentRecord`
   nor `HyperparamTuningOutput` declared it.

   The consequence of implementing only the check is decisive: every
   composed run would have refused **its own** records, because a composed
   run's second iteration resumes from records its first iteration wrote.
   The rule needs a producer to be coherent, so C8 adds one:

   ```text
   HyperparamTuningOutput.task_composition_fingerprint   additive, default None
   ExperimentRecord.task_composition_fingerprint         additive, default None
   ```

   Both mirror `health_config_sha256` / `resolved_data_scope` exactly, and
   both default to `None` so every legacy record and output still
   validates. The record stamp is applied at `_emit_record` — the SINGLE
   validate-and-persist seam, for precisely the reason `candidate_id` is
   stamped there: nine construction sites, and a per-site stamp is one
   somebody forgets. Its value comes from a narrow `bind_composition_fingerprint`
   ContextVar on the composition's existing ExitStack — one string, one
   consumer, the same discipline C5's manifest path follows and NOT an
   ambient composition binding.

   **This is a schema addition and is recorded as such.** It is additive,
   defaulted, unreachable for an un-composed run, and required for a frozen
   ruling to be satisfiable at all. Case 3 refusing a pre-Step-11 composed
   workspace's resume is exactly what R-11-9 rules should happen.

   **Finding F-11-C8-b — a mutation exposed a defect in C8's own test.**
   Disabling the absence branch left all 17 green. The reason: the case-3
   test used `source="unstamped legacy record"`, and the validator echoes
   `source` into every message — so `assert "unstamped" in message` was
   satisfied by the test's own LABEL while the run fell through to a
   value-mismatch message instead. The source is now neutral and the
   assertions name the absence branch's own words. A test that reads back
   its own input is the shape rule 25 forbids, arriving by a side door.

### C9 — Census widening, structural comparison, operator docs

1. **Goal.** The spawn parent stops being invisible to the repository's own
   guards; the operator surface is documented; the structural budget is
   checked.
2. **Scope.** F-11-8; the R-11-11 comparison; `sdsc_submission_scripts/README.md`
   and any node `.md` this PR's production changes touch.
3. **Implementation plan**
   - [x] Bring `core/sandbox_executor.py` into the censused surface, or
         state why not. Widening may surface pre-existing leaks — record
         them, never exempt by name.
         → added to `_DATA_PATH_SURFACE`. **No leak surfaced under either
         census rule**: the parent contains no task-name COMPARISON and no
         task-implementation IMPORT. What the widening does NOT prove is
         recorded honestly rather than left implied — see below.
   - [x] Re-measure the R-11-11 metrics and compare against C0. A function
         that grew a branch family or ~80-150 lines must be extracted
         before this commit closes.
   - [x] Document the resource knobs, which are env-only and undocumented
         outside source. → `sdsc_submission_scripts/README.md` invariants
         §7 (composed `--data_dir` is required) and §8 (the ceiling ladder,
         the `0` disable, the loud refusal, recorded-not-enforced
         provenance, and the `empirical_unverified` inference derivation).
   - [x] **Doc sync lands HERE — before the final push, not after**
         (the Step-10 ordering lesson).
         → operator README + the tuner node's `.md` (the only node whose
         production behaviour this PR changed): the `data_dir` row now
         states that a composed run's bound root WINS, and a new
         "Execution infrastructure the tuner depends on (Step 11)" section
         records the four changes underneath it.
   - [x] **R-11-10 sweep**: every C0 inverted guard is now a permanent
         contract owner or deleted; no duplicate pre/post pairs survive.
4. **Validation plan.** Unit; the widened census RED on a planted leak.
5. **Acceptance criteria.** Every documented flag quoted against merged
   source; the structural comparison recorded with real numbers; zero
   duplicate guards. **ALL THREE MET** — twelve documented claims were
   executed against source (ceiling values, env-var name, `0` semantics,
   the refusal type, the lock key, its recorded-not-enforced
   classification, the inference derivation label, all three argv flags,
   the record stamp field, and the composed-root refusal type).
6. **Failure/edge cases.** If the structural budget is exceeded and cannot
   be extracted safely, STOP and raise it rather than shipping the growth.
   **Not reached** — see the measurement below.
7. **Verification commands and evidence.**
   - [x] `pytest tests/unit/guardrails/ -q` → **284 passed**.
   - [x] **Mutation** — a planted `task == "tidmad"` comparison in
         `core/sandbox_executor.py` ⇒ the widened census **RED**. Before
         C9 the same plant was invisible, which is the whole of F-11-8.
   - [x] **R-11-11 structural comparison, real numbers:**

     ```text
     core/sandbox_executor.py   2,456 -> 2,533 LOC   (+77, budget +150)

     function                      stmts   branch    LOC    params
     execute_training              92->92  39->39  357->358  14->14
     execute_inference             69->69  28->28  253->254   9->9
     _run_observed_subprocess      62->62  27->27  186->199   9->9
     TidmadSandbox.__init__        22->22   6->6    87-> 89  12->12
     ```

     **Zero branch growth and zero parameter growth in every baselined
     function.** All LOC growth is comments — `+13` on
     `_run_observed_subprocess` is C7's corrected launch-split
     justification, `+2` on `__init__` is C4's note on the bound root.
     R-11-11's direction was respected: C3 moved semantics OUT of the
     launch consumer into a sibling module, and the transports added by
     C4/C5 are one-line splices whose decisions live in helpers.
8. **Commit boundary.** Docs, guards and measurement only.

   **What the widened census proves, stated so nobody reads it as more.**
   It proves the spawn parent contains no task-name COMPARISON and no
   task-implementation IMPORT. The task identity NAMES remain —
   `class TidmadSandbox`, `_tidmad_data_dir()`, and a `"tidmad_db"` Mongo
   collection literal. Renaming a class is Step 12's class-level
   genericization, not Step 11's, and
   `TestTheSpawnParentIsCensused::test_the_widening_had_something_to_look_at`
   asserts all three are still there — so the green census cannot quietly
   become a claim that the parent is task-free.

   **R-11-10 sweep — all four C0 inverted guards resolved, none twinned:**

   | defect | replaced by | flipped in |
   |---|---|---|
   | F-11-2 | the derived `subprocess.Popen` env census | C1 |
   | F-11-1 | the one-consuming-authority census + the C2 module | C2 |
   | malformed RSS override | `TestMalformedOverrideRefusesLoudly`, rewritten in place | C3 |
   | F-11-8 | `TestTheSpawnParentIsCensused` | C9 |

   The C0 module's own docstring now records that table, so the file
   describes what it currently owns rather than what it opened the PR
   owning.

### C10 — Gate 2 evidence and closeout

1. **Goal.** Produce the one real-execution evidence this PR owes: the
   subprocess path executes under a composed binding, with the transported
   values actually consumed, and TIDMAD parity intact. It is last because
   the Gate must run at the final executable head.
2. **Scope.** Gate advice/config and the ledger. **No production change**
   beyond what the Gate evidence itself requires. Depends on C0–C9.
3. **Implementation plan**
   - [x] Write the Gate-readiness packet: candidate SHA, clean tree,
         deterministic prerequisites green, exact workload, projected
         runtime and cost, PASS/FAIL/INCONCLUSIVE taxonomy. → §11a below.
   - [x] Re-read the gate standard and re-audit the CLI flags from source
         immediately before launch (command shapes drift).
         → `docs/gates/gate_testing_standard.md` §"Gate 2" re-read; **all 19
         flags verified present in `_chain_common.sh`'s parser** (they are
         NOT in `run_chain.sh`, which only documents them — checking the
         wrong file would have "verified" nothing).
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
   provably consumed the **TRANSPORTED data root and the Step-10 metric
   binding** rather than TIDMAD defaults, with deliverable-derived behaviour
   and resource calibration/provenance exercised; un-composed argv
   byte-identical to the C0 census; TIDMAD ceilings resolve to 40/60/24; the
   TIDMAD cleanup glob unchanged; kill/cleanup semantics unchanged.
   **Model quality is NOT a criterion** (§8). **NOT claimed: generic
   task-scope reconstruction, Pets/DAVIS subprocess execution, contrast L4
   (R-11-12).**
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
| **REQUIRED REAL COMPONENTS** | real training, inference and scoring subprocesses under a composed binding; real rlimit application; real sentinel and cleanup. **No scope carrier — R-11-12 removed it from this step; the Gate is not widened to compensate.** |
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
* **Doc sync in C9, BEFORE the final push** — Step 10's ordering error,
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

Branch `step11-execution-infrastructure-impl`, base
`c1caa6093afe8a0bd6a90a916b7bb58e1927085a` (== `origin/master` at freeze).

| commit | SHA | outcome |
|---|---|---|
| C0 — baselines, structural tripwire, inverted guards | `b8a6ee88` | 32 tests, 2 mutations caught, zero production change |
| C1 — F-11-2 spawner env transport | `a39aa590` | by-path guard replaced by a derived contract census; 3 mutations caught; 4,497 passed / 1 pre-existing flake |
| C2 — F-11-1 host-OOM consumer closure | `4759977e` | one failure authority, both phase branches; 3 mutations caught incl. an accidental slide into option B; 1,354 passed |
| C3 — declared resource calibration | `8f290cc4` | new sibling module; recorded-not-enforced lock with a declared `_PROVENANCE` partition; F-11-3 retired; 5 mutations |
| C4 — data-root run binding / transport | `184f5870` | root reaches all three children (scoring via `--raw_data_dir`); composed run fails closed; 4 mutations |
| C5 — scoring metric via the Step-10 authority | `75bb4223` | manifest transported, metric re-composed by the SAME authority; no fallback; 4 mutations; 5,071 passed |
| C6 — deliverable naming from the contract | `2e870b71` | optional `deliverable:` declaration validated by the contract; both cleanup consumers follow with no call-site change; a SURVIVING mutation closed; 5 mutations |
| C7 — spawn hygiene | `6dfd5c92` | name authority shared parent/child; absolute script anchoring; the `timeout --signal=INT` justification corrected; 4 mutations |
| C8 — invariants and resume genericity | `f122afa0` | last task token removed; R-11-9 three-case rule + the additive stamp that makes it satisfiable; 4 mutations; 6,980 passed |
| C9 — census widening, structure, docs | *(below)* | spawn parent censused (mutation-proven); zero branch/param growth; operator + node docs synced and quoted against source |

### 11a. Gate-2 readiness packet (written BEFORE launch)

| field | value |
|---|---|
| candidate SHA | `62fd2481` (C9), clean tree |
| claim | the REAL subprocess path — spawn, argv, sentinel/IPC, rlimits, cleanup — executes driven from a run's declared COMPOSITION rather than TIDMAD's import-time constants |
| temporal depth | **1 iteration x 1 round** (frozen §8; the witness is argv/sentinel/rlimit behaviour, produced and consumed inside one iteration) |
| composition | `configs/task_composition/tidmad.yaml` — the shipped manifest. Composed TIDMAD, so runtime/scientific behaviour is comparable to legacy while the TRANSPORT is what is new |
| real components | real LLM (`openai_tiered_pro.json`, key from `.env`), real training, real inference, real scoring, real subprocess spawn, real `RLIMIT_AS`, real sentinel/IPC/cleanup |
| environment | RTX 5090, 32,607 MiB total / ~13,950 MiB already in use by another process; data root resolves to `/home/klz/Data/TIDMAD/`; 417 G free on `/` |
| projected wall time | **<= ~30 min**, inside the pre-authorised ~1 h envelope |

**Why a COMPOSED run is the right shape.** Composing TIDMAD exercises every
Step-11 transport — the data root reaching all three children, the scoring
child composing its declared metric, the manifest and fingerprint bindings —
while keeping the science identical to the legacy path, so a scientific
surprise cannot be confused with a transport defect.

**PASS requires all of:** the chain exits 0; real training, inference and
scoring executed (not pseudo, not skipped); the composed children provably
consumed the TRANSPORTED data root and the Step-10 metric binding rather than
TIDMAD defaults; TIDMAD ceilings resolve 40/60/24; the TIDMAD cleanup glob is
unchanged; kill/cleanup semantics unchanged.

**NOT acceptance criteria (frozen §8):** model quality · HealthGate PASS ·
score magnitude · convergence · output diversity. A poor or collapsed
candidate is acceptable evidence. **Nothing may be tuned to make this green.**

**FAIL** = the spawn/IPC/rlimit/cleanup path itself misbehaved, or a composed
child silently used a TIDMAD default. **INCONCLUSIVE** = provider/network/
machine fault, or the run stopped before the relevant phase — including the
RT4 watchdog firing, which the standard classifies as runtime abnormality
yielding no evidence.

### 11b. Gate-2 run 1 — **INCONCLUSIVE** (2026-08-22, SHA `39dcf603`)

```text
workspace   /tmp/step11_gate2_1787383843
command     the §11a command, with --runtime_watchdog and
            --validation_max_phase_seconds 900
outcome     4 attempts, ALL killed by the RT4 watchdog inside training
verdict     INCONCLUSIVE — the Gate's own claim was never reached
log         /tmp/step11_gate2_attempt1.log
```

Per the gate standard, a watchdog kill *"yields no evidence and wastes the
whole attempt"* and is classified as runtime abnormality, **not** as a
failure of the thing under test.

**Diagnosis — a KNOWN OPEN defect, and not Step 11's.** The kill lands at
**deadline + ~1 s on every attempt**, while the deadline itself tracks the
model size:

```text
attempt 1   killed 255.354s   deadline 254.548s   source=verified_components
attempt 2   killed 244.336s   deadline 243.822s   (8 -> 6 blocks)
attempt 3   killed 229.333s   deadline 228.335s
attempt 4   killed  (same shape)
```

Shrinking capacity shrinks the deadline in proportion, so **reducing the
workload cannot converge** — which is why three successive reductions all
failed by the same ~1 s margin. The real model's own reasoning names the
cause: *"successfully reached the end of the single training epoch but was
killed by the watchdog at the overall runtime boundary, with validation
dominating the estimate."*

Source confirms it. `core/runtime_control/admission.py` states the prephase
measurement covers **`phase="training"` only**, and 07a's validation pass runs
INSIDE the training subprocess. This is the runtime-control debt recorded in
CLAUDE.md as **Q-07c-6 = B — "pre-run ADMISSION pricing of the validation
workload… OPEN after 07c"**, owned by admission/runtime-control. Step 11
changes nothing on that path.

**Remedy, and why it does not weaken the evidence.** The watchdog is an
*emergency fuse*; it appears nowhere in §8's REQUIRED REAL COMPONENTS, and
Step 11's failure class is spawn / argv / IPC / rlimit / cleanup. Run 2 omits
`--runtime_watchdog` **and** `--validation_max_phase_seconds` together, which
is the standard's own pairing rule (*"if a Gate omits `--runtime_watchdog`, it
must also omit `--validation_max_phase_seconds`"*). **No production semantics,
no model capacity and no scientific bound were changed to obtain a green
Gate** — a mispriced fuse was removed from a Gate that never needed it.

**Evidence this run DID produce, and it is direct.** The live training child's
real argv, captured from the process table:

```text
execute_tools/train_engine_sandbox.py … \
    --task_data_path_id tidmad \
    --data_dir /home/klz/Data/TIDMAD/ …
```

`--data_dir` **did not exist on the training argv before C4** — §3.1 records
that training and inference "pass no `--data_dir`" and the children fell back
to the import-time `TIDMAD_DATA_DIR`. Its presence here, emitted by a real
composed launch and consumed by a real training subprocess, is the C4
transport working in production. Preserved at
`/tmp/step11_gate2_argv_evidence.txt`.

### 11c. Gate-2 run 2 — the real composed path executed (SHA `5e5166db`)

```text
workspace  /tmp/step11_gate2b_1787385003
command    the §11a command, minus --runtime_watchdog and
           --validation_max_phase_seconds (the standard's pairing rule)
outcome    CHAIN COMPLETE, 1 iteration x 1 round, 1 attempt
log        /tmp/step11_gate2_run2.log
```

**The Gate-owned path executed end to end**, which run 1 never reached:

```text
[Step 1/3] Training     real, completed
[Step 2/3] Inference    real, 6 deliverables written (scope 4-9)
[Step 3/3] Scoring      real, denoising_score = -1.6878627166387563
cleanup                 "Cleaned up 6 denoised files (0.2 GB freed)", 0 remaining
```

Step-11 acceptance evidence, read from the run's own artifacts:

| criterion | observed |
|---|---|
| composed children consumed the TRANSPORTED root | training argv carried `--data_dir /home/klz/Data/TIDMAD/` (run 1, process table) — a flag that **did not exist on that argv** before C4 |
| ceilings resolve 40/60/24 | lock `execution_calibration`: training 40 `measured` · inference 60 `empirical_unverified` · scoring 24 `incident`, `override_env=None` |
| TIDMAD cleanup glob unchanged | deliverables written as `abra_validation_denoised_…_0007.h5`; the watchdog-free cleanup matched and removed all 6 |
| composition identity pinned | chain lock `task_composition_fingerprint=d6628a93…` |
| record stamp reachable | the persisted record carries `fp=d6628a93…` |
| un-composed argv byte-identical | C0 baselines, green throughout |

**The round was scientifically invalidated** — HealthGate found output
diversity `unique_int8=4` and std `~0.642 mV` (a class-127-style collapse),
so `best_score=None` and the record is `failed_mode_collapse`. Per the frozen
§8 that is **NOT a Gate-2 criterion**: *"model quality · HealthGate PASS ·
score magnitude · convergence · output diversity. None is owned by Step 11; a
poor or collapsed candidate is acceptable evidence."* **Nothing was tuned.**

#### Finding F-11-C10-a — the Gate caught a REAL defect C8 had introduced

Verdict-relevant, and the reason this Gate was worth running:

```text
record  task_composition_fingerprint = d6628a93…   correct
OUTPUT  task_composition_fingerprint = None        WRONG
```

The record stamp reads the run-scoped ContextVar; the OUTPUT stamp read
`bindings.task_composition_fingerprint`, which comes from the **tuner's own
sub-workspace lock** — and that lock does not carry the composition. This is
carried Step-10 debt **F-P56-3** (*"composition kwargs reach only the
chain-level invariants lock"*), and the Gate output above shows it directly:
the chain lock has the fingerprint, the tuner-level lock has `None`.

Post-C8 this is not cosmetic. A composed **2-iteration** chain would have
refused its own iteration-1 OUTPUT at ingress under R-11-9 case 3 — a
regression created by C8 and invisible to every unit test, because the
1-iteration Gate never resumes and the unit fixtures set the ContextVar
directly.

**Fix**: both stamps now read the SAME authority
(`active_composition_fingerprint()`), and the dead
`RunBindings.task_composition_fingerprint` field is removed so a second
source of truth cannot come back. Pinned by an AST regression test asserting
exactly two call sites and zero `bindings.` reads — AST rather than
substring, because the explanatory comment names the removed expression and
counting prose as code is a mistake this PR has already made twice.

**Gate re-run required** (C10's own rule: re-run when the fix touches a
Gate-owned execution path — record persistence is one), at the final head.

### 11d. Gate-2 FINAL — **PASS** at `88f190a1` (2026-08-22)

```text
workspace  /tmp/step11_gate2d_1787386992
SHA        88f190a15df709ce23338cef22831e4b3681b7bf  (the final executable head)
outcome    CHAIN COMPLETE, 1 iteration x 1 round, 1 attempt
log        /tmp/step11_gate2d.log
cost       7 LLM calls, 226,530 tokens
```

**The Gate-owned path executed end to end:**

```text
[Step 1/3] Training     real, completed
[Step 2/3] Inference    real, deliverables written (scope 4-9)
[Step 3/3] Scoring      real, denoising_score = -1.58746920744804
cleanup                 "Cleaned up 6 denoised files (0.2 GB freed)"
```

**Acceptance, criterion by criterion:**

| criterion | observed at `88f190a1` |
|---|---|
| composed children consumed the TRANSPORTED root | training argv carried `--data_dir /home/klz/Data/TIDMAD/` — a flag that did not exist on that argv before C4 |
| composed scoring used the run's declared metric | the run scored through the composed manifest; no TIDMAD fallback was taken |
| ceilings resolve 40/60/24 | lock: training 40 `measured` · inference 60 `empirical_unverified` · scoring 24 `incident`, `override_env=None` |
| TIDMAD cleanup glob unchanged | `abra_validation_denoised_…` written and all 6 reclaimed |
| composition identity pinned | chain lock `d6628a93fcb3578c` |
| **F-11-C10-a regression FIXED** | **OUTPUT `fp=d6628a93fcb3578c`** (was `None`) and record `fp=d6628a93fcb3578c` — both stamps agree |
| un-composed argv byte-identical | C0 baselines green throughout |
| kill/cleanup semantics | unchanged; no watchdog involved |

**The round was scientifically invalidated again** — output diversity 4-5
unique int8 vs >25, std ~0.443 mV vs >=1 mV — so `best_score=None` and the
manifest is `no_records`. Per the frozen §8 **none of that is a Gate-2
criterion**, and **nothing was tuned**. The same collapse reproduced across
two independent runs with different candidates, which is consistent evidence
about the 4 GiB / 1-epoch / 0.01-portion envelope, not about Step 11.

**One thing deliberately NOT fixed, and now provably harmless.** The
tuner-level sub-workspace lock still shows
`task_composition_fingerprint=None` — carried Step-10 debt **F-P56-3**. It no
longer has a consumer: the output stamp reads the run-scoped authority
instead, which is exactly what the fix changed. Recorded so a later reader
does not mistake it for a Step-11 regression.

**Exact-head CI on this SHA: run `32562135614` — SUCCESS on
`88f190a15df709ce23338cef22831e4b3681b7bf`.** Gate 2 and the authoritative
CI therefore share one executable SHA.

### 11e. Adversarial source-diff review (final head)

Production diff vs `c1caa609`: **18 files, +1,129 / −100**. Checked
mechanically, not by eye:

* **no task-name or scope dispatch introduced** — every
  `== "tidmad"` / `"pets"` / `"davis"` hit in the diff is inside a TEST
  asserting their absence;
* **no silent fallback** — the single new `except Exception` re-raises as a
  typed `TaskCompositionError` with the cause chained, matching
  `_compose_metric`'s existing pattern; every new `raise` is a named type
  (`MalformedCeilingOverride`, `DatasetDirectoryUnavailable`,
  `CompositionDataRootMissing`, `TaskCompositionError`, `ValueError`);
* **all four new ContextVars set once and reset in `finally`** —
  `bind_physical_data_root`, `bind_task_manifest_path`,
  `bind_composition_fingerprint`, `bind_deliverable_naming`;
* **no new mutable module state** — the new module-level names are frozen
  constants and ContextVars only;
* **zero branch growth and zero parameter growth** in all four baselined
  functions (§7-C9).

### Initialization audit (2026-08-21, HEAD `c1caa609`)

Prerequisites verified by **git ancestry**, not by status text
(`feedback_verify_status_from_git_not_docs`): 07c `52bd98ba`, Step-10 P5+P6
`b54623b2`, Step-09b `e9a1f9fb`, Step-08c `3f4effb5`, D14 `4db414b5` are all
ancestors of HEAD. `git diff --name-only a88aad9b HEAD` lists **only**
`docs/…/step_11_execution_infrastructure.md`, so every §3 line anchor holds
exactly and §3.6's freshness claim is re-confirmed at the freeze SHA.

Eight load-bearing anchors re-read directly: `dirs["data"] =
_tidmad_data_dir()` (`:1136`) · unconditional `TidmadScope`
(`train_engine_sandbox.py:1124-1125`) · unconditional
`derive_tidmad_metric` (`denoising_score_single.py:194-195`) ·
`isolated_probe.py:482-487` with **no** `env=` versus
`gpu_measurement_runner.py:279-285` with it · three `oom_host_ram`
producers (`:1654,:1923,:2116`) · `resume.py:57,1483` ·
`_ROLE_DEFAULT_RSS_GB` 40/60/24 · `sandbox_executor.py` absent from
`_DATA_PATH_SURFACE`.

**Two corrections, neither semantic**: the spawner's real path is
`agent/skills/evaluate_vram_skill/isolated_probe.py`, and §7's "Twelve
commits" was a stale count (the list has eleven, C0–C10).

**One measurement finding recorded for C1.** The production
`subprocess.Popen` / `subprocess.run` census over `core/ execute_tools/
agent/ nodes/ workflows/ dashboard/` returns 16 call sites, of which only
five launch a SIDERIUS worker via `sys.executable`:

```text
core/runtime_control/gpu_measurement_runner.py:279   env= PRESENT
core/sandbox_executor.py:935                        env= PRESENT
core/sandbox_executor.py:973                        env= PRESENT
core/sandbox_executor.py:2068                       env= PRESENT
core/runtime_control/probe_subprocess.py:336        env= ABSENT (production UNREACHABLE)
agent/skills/evaluate_vram_skill/isolated_probe.py:482  env= ABSENT (F-11-2, REACHABLE)
```

The remaining eleven spawn `nvidia-smi`, `git` or `pytest` and carry no
plugin context. This enumeration is what C1's contract census must be
derived from rather than hand-listed.

**Entry conditions — ALL SATISFIED at freeze.**

- [x] 07c implemented, Gate-2'd and MERGED — PR #219, squash `52bd98ba`,
      2026-08-17. Verified from git ancestry and byte-identical file
      content, not from a status document.
- [x] Step-11 source anchor refreshed to clean master `175904cd`
- [x] Bounded re-audit run (§3.6) — zero production drift, all eight
      load-bearing anchors exact, structural baseline unchanged
- [x] The three rev-2 stale points confirmed fixed
- [x] **Q-11-4 answered — B.** C5 deleted, commits renumbered, R-11-12 added
- [x] §1's scope claim withdrawn; Gate-2 acceptance no longer requires a
      scope carrier
- [x] Open operator questions = **0**
- [x] **Operator froze this document as Revision 4 (2026-08-21)**

Frozen rulings: **Q-11-1 = A** (transport, not construction) ·
**Q-11-2 = 07c FIRST, DISCHARGED** · **Q-11-3 = A** (tuner-visible only,
prompt bytes unchanged, Gate 1 NOT REQUIRED) · **Q-11-4 = B** (scope
rehydration deferred to CAP-SCOPE, R-11-12).

**Implementation may now begin**, against a fresh Implementation Working
Rules contract and a fresh handoff. All implementation checkboxes below
are unchecked.
