# Step 11 — Execution Infrastructure (spawn, IPC, limits)

## 0. Status

**DRAFT — Revision 1. NOT FROZEN. Implementation MUST NOT start.**

| field | value |
|---|---|
| roadmap contract | `siderius_generic_framework_upgrade.md` §9 (§9.1 couplings, §9.2 target, §9.3 compatibility), completion-matrix row "§9 Execution infrastructure" |
| source anchor | merged master **`a88aad9b`** (Step 10 complete; all 7 children merged) |
| prerequisite status | Steps 00–06, 07a/07b/07d, 08, 09, 09.5, 09.5a, 10 **COMPLETE**. **§7e (07c) NOT STARTED — see Q-11-2** |
| open operator questions | **2 — Q-11-1, Q-11-2. Both block freeze.** |
| PR decomposition | **ONE PR** (see §6) |
| Gate disposition | Gate 2 **REQUIRED**; Gate 1 **UNDECIDED pending §7.9's source check** |

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
contrast tasks spawn with zero infra edits (L2/L3 as available)"*. **The
second clause is not satisfiable as written — see Q-11-1.**

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

## 4. Open operator questions (BOTH block freeze)

### Q-11-1 — Is CAP-SCOPE in Step 11's scope?

The frozen acceptance says *"contrast tasks spawn with zero infra edits"*.
§3.1 proves contrast tasks cannot spawn **at all**: no argv can carry a
non-TIDMAD scope, so `train_engine_sandbox.py:1124-1125` always builds
`TidmadScope`. That gap is exactly **CAP-SCOPE**, which Step 10 froze as
the REQUIRED prerequisite for contrast-track L4.

The criterion is therefore **unsatisfiable as written** — structurally the
same class as F-P56-4, where a frozen Gate contract could not be met by the
architecture as built.

| option | Step 11 delivers | Gate 2 shape |
|---|---|---|
| **A (recommended)** — amend acceptance, defer CAP-SCOPE | the surface no longer PREVENTS a non-TIDMAD spawn: data root, deliverable naming and scope CAN cross argv; TIDMAD parity byte-identical | single-track TIDMAD composed chain |
| **B** — include CAP-SCOPE | additionally task-owned scope construction, so Pets/DAVIS genuinely spawn; D14 runners routed through the sandbox | multi-track: TIDMAD parity **plus** a real contrast subprocess run |

Recommendation **A**: fix the unsatisfiable criterion deliberately rather
than discover it mid-implementation. B roughly doubles scope and pulls in
the capability Step 12 also wants.

### Q-11-2 — Does 07c (§7e) implement before Step 11?

`pr_07c_tuner_measurement.md` is **FROZEN Revision 3, operator-approved
2026-08-17, Q-07c-1…9 all closed, Gate 2 REQUIRED — and never
implemented.** It edits `core/sandbox_executor.py` at `:446-481` (the
measurement provider), `:944-953` (phase timing) and `:952-953` (the
`elapsed <= deadline` comparison) — the same file Step 11 restructures.

Recommendation: **07c first.** It is already approved; landing Step 11
first would force re-reconciliation of a 198 KB frozen design against a
file whose timing and resource paths Step 11 just moved.

---

## 5. Scope and non-goals

**In scope**: the data root as a composed, transported value · the
deliverable naming template as a composed value · per-role ceilings as
declared calibration with provenance and a stated precedence · the three
defects F-11-1/2/3 · spawn hygiene F-11-4/7 · invariants/resume F-11-5/6 ·
census widening F-11-8 · operator surface docs.

**Explicit non-goals**
* CAP-SCOPE / task-owned scope construction — Q-11-1 option A.
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

All checkboxes start unchecked. Evidence lines are filled only after the
work runs.

### C0 — Baseline census and inverted guards

1. **Goal.** Measure the current state and make each defect executably
   visible BEFORE any behaviour changes, so every later commit has a
   named test that flips.
2. **Scope.** New tests only. No production file changes. Depends on
   nothing.
3. **Implementation plan**
   - [ ] Census: enumerate every argv flag per role from
         `sandbox_executor.py:1401-1421`, `:1752-1778`, `:2068-2089`, and
         pin the current set exactly.
   - [ ] Inverted guard for F-11-1: assert `oom_host_ram` currently has no
         consumer (the defect), so C2 turns it red.
   - [ ] Inverted guard for F-11-2: assert `isolated_probe.py` currently
         spawns without `env=`.
   - [ ] Record `_ROLE_DEFAULT_RSS_GB` values and the two-layer precedence
         as a pinned baseline.
4. **Validation plan.** Unit only. No Gate.
5. **Acceptance criteria.** Every census reproduces the §3 numbers exactly;
   each inverted guard names the commit that will flip it.
6. **Failure/edge cases.** A census that cannot see the spawn parent is the
   F-11-8 blind spot — C8 widens it; C0 must not silently pass by scoping
   itself to files it already covers.
7. **Verification commands and evidence.** `[ ]` pending.
8. **Commit boundary.** Tests only; independently reviewable.

### C1 — F-11-2: env transport on the production spawner

1. **Goal.** A production-reachable spawner must not lose the run-scoped
   plugin dir.
2. **Scope.** `agent/skills/evaluate_vram_skill/isolated_probe.py`
   (spec + spawn), the guard test. `probe_subprocess.py` decided
   explicitly (it is production-unreachable — fix or record, not both).
3. **Implementation plan**
   - [ ] Add `plugin_dir` / `loss_dir` to `IsolatedProbeSpec` (it has
         nowhere to put the value today, `:158-195`).
   - [ ] Pass `env=subprocess_env(...)` at `:482-487`.
   - [ ] Rewrite the guard to test the CONTRACT — *every* production
         spawner of a worker passes `env=` — not one file by path.
   - [ ] Decide and record `probe_subprocess.py:336-341`.
4. **Validation plan.** Unit + the rewritten guard. Negative: a planted
   env-less spawner must turn it red.
5. **Acceptance criteria.** The guard fails on a planted omission in ANY
   production spawner, proven by mutation, not asserted.
6. **Failure/edge cases.** `subprocess_env` never mutates `os.environ`;
   the child must not lose the `PYTHONPATH` extension either.
7. **Verification commands and evidence.** `[ ]` pending.
8. **Commit boundary.** One defect; no calibration or argv work.

### C2 — F-11-1: make `oom_host_ram` actionable, or delete it

1. **Goal.** A host OOM must not be invisible to the tuner.
2. **Scope.** `sandbox_executor.py:1654,1923,2116` producers;
   `execution.py:711,882` consumers; `records.py:150,173-174,205-207` tags.
3. **Implementation plan**
   - [ ] Decide: route `oom_host_ram` into the existing resource-failure
         path, or delete the status and let it be a plain error. **Do not
         invent a fourth failure state.**
   - [ ] Implement the decision at all three producer sites.
   - [ ] Ensure the planner-visible tag behaviour is stated explicitly —
         **if this changes prompt-visible strings it triggers Gate 1
         (§7.9).**
4. **Validation plan.** Unit; negative test that a device OOM is still
   classified as before; parity test that non-OOM errors are unchanged.
5. **Acceptance criteria.** A host-OOM training failure reaches a named,
   asserted tuner outcome; the C0 inverted guard flips.
6. **Failure/edge cases.** A `-9` SIGKILL cannot be attributed
   (`failure_attribution.py` deliberately returns `unknown`) — that must
   remain true.
7. **Verification commands and evidence.** `[ ]` pending.
8. **Commit boundary.** No OOM-matcher consolidation (F-11-9 is a non-goal).

### C3 — Resource ceilings become declared calibration with provenance

1. **Goal.** The per-role ceilings stop being undocumented module
   constants and start recording what they are derived from.
2. **Scope.** `sandbox_executor.py:75-173`; a calibration declaration;
   `core/run_invariants.py` (pin what a run executed under);
   `_ROLE_DEFAULT_RSS_GB` value-pinning tests.
3. **Implementation plan**
   - [ ] Declare the ceilings with machine-readable provenance
         (measured-on, device, derived-from). **Calibration config, NOT
         task config** (§9.2).
   - [ ] State precedence explicitly against the EXISTING override seam;
         §9.3 forbids a third layer with unstated ordering.
   - [ ] **F-11-3**: re-derive or retire the 60 GiB justification — its
         cited anchor is gone and the dtype is task-declared.
   - [ ] Decide whether the run-invariants lock pins the ceilings.
4. **Validation plan.** Unit; parity test that TIDMAD resolves to the SAME
   40/60/24; negative tests for a malformed env override (today a negative
   or non-numeric value falls back **silently** — decide and test).
5. **Acceptance criteria.** TIDMAD's resolved ceilings are byte-identical
   to the pre-change values, proven by the C0 baseline, and each ceiling
   carries provenance a reader can check.
6. **Failure/edge cases.** `SIDERIUS_SUBPROCESS_RSS_GB=0` currently
   DISABLES the ceiling — preserve or refuse deliberately, never by
   accident.
7. **Verification commands and evidence.** `[ ]` pending.
8. **Commit boundary.** Declaration only; no task-derived ceilings unless
   Q-11-1 = B.

### C4 — The data root becomes a composed, transported value

1. **Goal.** The physical data root reaches every child because the run
   declared it.
2. **Scope.** `workflows/task_composition.py` (manifest key + field);
   `sandbox_executor.py:1136` `dirs["data"]` and `TidmadSandbox.__init__`;
   the three argv builders; the three child defaults;
   `data_paths.py` import-time binding; `run_one_iteration.py:1760`.
3. **Implementation plan**
   - [ ] Decide the owner of the data root and whether it joins the
         semantic fingerprint (it is a host path; the fingerprint
         deliberately excludes those — likely provenance-only).
   - [ ] Thread it into `TidmadSandbox` rather than `_tidmad_data_dir()`.
   - [ ] Transport across training, inference and scoring argv, following
         the `--task_data_path_id` pattern.
   - [ ] Reconcile the two existing data-dir concepts —
         `HyperparamTuningInput.data_dir` reaches only the GPU measurement
         worker today.
   - [ ] Decide the fail-closed disposition for the import-time template
         fallback (F-11-11) — **note CI currently runs on
         `/path/to/TIDMAD/`**, so removing it naively breaks collection.
4. **Validation plan.** Unit; un-composed argv byte-parity; a composed
   non-TIDMAD manifest resolving a different root; negative: a composed run
   with no declared root fails closed.
5. **Acceptance criteria.** Un-composed argv is **byte-identical** to C0's
   census; a composed run's children receive the declared root.
6. **Failure/edge cases.** Missing root, placeholder root, root that is not
   a directory — `DatasetDirectoryUnavailable` already exists as the
   vehicle.
7. **Verification commands and evidence.** `[ ]` pending.
8. **Commit boundary.** Data root only; naming is C5.

### C5 — Deliverable naming flows from the contract

1. **Goal.** A composed task names its own deliverable, so cleanup globs
   stop matching TIDMAD filenames a contrast run never wrote.
2. **Scope.** `deliverable_spec.py:355-356`; the composition manifest key
   set; the two cleanup sites (already contract READERS).
3. **Implementation plan**
   - [ ] Allow a composition to declare the naming template.
   - [ ] Keep TIDMAD's defaults byte-identical when undeclared.
4. **Validation plan.** Unit; TIDMAD glob byte-parity; a composed task
   producing a different glob.
5. **Acceptance criteria.** Both cleanup sites use the declared template
   with no code change at the call sites.
6. **Failure/edge cases.** An empty or malformed template must refuse, not
   produce a glob matching everything.
7. **Verification commands and evidence.** `[ ]` pending.
8. **Commit boundary.** Naming only.

### C6 — Spawn hygiene

1. **Goal.** Remove the accidental couplings that make the spawn surface
   fragile.
2. **Scope.** F-11-4 (`cached_models`/`records` single authority),
   F-11-7 (absolute script paths).
3. **Implementation plan**
   - [ ] One authority for the sandbox subdirectory names, following the
         `get_plugin_dir`/`get_loss_dir` precedent in the same file.
   - [ ] Anchor the three script paths absolutely; keep `cwd` semantics.
   - [ ] Record the §3.5 launch-split docstring correction (stale
         `timeout --signal=INT` justification).
4. **Validation plan.** Unit; a parity test proving parent and child derive
   the SAME paths — the guarantee that is coincidental today.
5. **Acceptance criteria.** Planting a divergent literal turns the parity
   test red.
6. **Failure/edge cases.** The `_OK_` sentinel read depends on the match;
   a mismatch currently produces a FALSE `error_training`.
7. **Verification commands and evidence.** `[ ]` pending.
8. **Commit boundary.** No behaviour change to kill/cleanup semantics.

### C7 — Invariants and resume

1. **Goal.** Remove the last TIDMAD token from the resume path and close
   the ingress-vs-lock asymmetry.
2. **Scope.** F-11-5 (`resume.py:1483`), F-11-6
   (`validate_stamped_invariants`).
3. **Implementation plan**
   - [ ] Replace `list(range(TIDMAD.num_files))` with the composed
         profile's `num_files`, as the sibling site already does; drop the
         `TIDMAD` import.
   - [ ] Decide whether outputs are stamped with
         `task_composition_fingerprint` and what a `None` stamp means
         (`_reject_legacy_runtime_lock` is the precedent for refusing
         rather than defaulting).
4. **Validation plan.** Unit; legacy-record compatibility; negative: a
   cross-composition seed must not pass ingress if the decision says so.
5. **Acceptance criteria.** `core/resume.py` contains zero task tokens.
6. **Failure/edge cases.** A legacy unstamped record must remain readable —
   Step 10 deliberately omits the key rather than serializing `null`.
7. **Verification commands and evidence.** `[ ]` pending.
8. **Commit boundary.** No new invariants beyond the decided one.

### C8 — Census widening and operator docs

1. **Goal.** The spawn parent stops being invisible to the repository's own
   guards, and the operator surface is documented.
2. **Scope.** F-11-8; `sdsc_submission_scripts/README.md`; any node `.md`
   this PR's production changes touch.
3. **Implementation plan**
   - [ ] Bring `core/sandbox_executor.py` into the censused surface, or
         state why not.
   - [ ] Document the resource knobs — `SIDERIUS_SUBPROCESS_RSS_GB` and
         `SIDERIUS_PREFLIGHT_WORKER_MEM_GIB` are env-only and undocumented
         outside source.
   - [ ] **Doc sync lands HERE — before the final push, not after.**
4. **Validation plan.** Unit; the widened census must be RED on a planted
   leak.
5. **Acceptance criteria.** Every documented flag quoted against merged
   source.
6. **Failure/edge cases.** Widening the census may surface pre-existing
   leaks — record them, do not silently exempt by name.
7. **Verification commands and evidence.** `[ ]` pending.
8. **Commit boundary.** Docs + guards only.

### C9 — Gate 2

Gate section per the standard's required fields — see §8.

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

**Gate 1 — UNDECIDED.** §7.9 check: `agent/prompts.py:1265-1285` renders an
OOM note keyed on the status string. If C2 changes planner-visible tags,
Gate 1 becomes REQUIRED. **This must be resolved from source before freeze,
not assumed.**

**Gate 2 — REQUIRED**, once, at the final executable head.

---

## 9. Evidence economy

* Targeted tests per commit; no full local suite (validation-economy rule).
* ONE authoritative exact-head CI at the final head.
* **Doc sync in C8, BEFORE the final push** — Step 10's ordering error,
  now a standing rule.
* Byte-parity is the workhorse: un-composed argv, TIDMAD ceilings and the
  TIDMAD glob must all be provably unchanged.

---

## 10. Risks

| risk | mitigation |
|---|---|
| `sandbox_executor.py` is the highest-blast-radius file in the repo; the roadmap itself calls this step "highest blast radius, smallest genericity gain" | byte-parity gates on argv, ceilings and globs; kill/cleanup semantics explicitly out of scope |
| 07c collides on the same file | Q-11-2 |
| The acceptance criterion is unsatisfiable as written | Q-11-1 |
| Removing the import-time fallback breaks CI at collection | C4 separates the fail-closed SEMANTIC decision from the import-time MECHANISM |

---

## 11. Implementation ledger

*(empty — implementation has not started and MUST NOT start before the two
open questions are answered and the operator freezes this document)*
