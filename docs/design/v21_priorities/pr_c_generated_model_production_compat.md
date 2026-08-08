# PR C — Generated-model production compatibility

**Status: DESIGN APPROVED 2026-08-08 (operator), corrections applied.
Cleared to begin C1. No implementation has begun.**

| | |
|---|---|
| Plan section | `docs/design/v21_priorities.md` Part III, PR C + §E.3b |
| Gate | V21 launch blocker |
| Depends on | PR A (merged, `b9f88ae5`) |
| Audit date | 2026-08-08, against `master` `b9f88ae5` |

**Formal-promotion objective, renamed by operator decision O-C-1.** Not
"restore formal promotion" — the tail already works (§0.1). The property
PR C proves is:

> **Authoritative formal promotion from a valid generated-model trial
> winner.**

**The question PR C answers.** PR A proved the agent can *invent and run*
both kinds of model. PR C must prove that **anything the agent invents is
a first-class citizen in every isolated production surface** — not only in
the parent process where PR A's work lives.

```text
PR A   "I can invent both kinds of model correctly."
PR C   "Anything I invent executes everywhere it needs to."
```

---

## A0. Verification toolchain

Inherited from PR A §A0, verified working on this machine:

```bash
PYRIGHT_PYTHON_GLOBAL_NODE=off uv run pyright     # pyright 1.1.409
.venv/bin/python -m pytest tests/unit/ -q -m "not real_run"
.venv/bin/python -m ruff check . && .venv/bin/python -m ruff format --check .
```

**Baseline at `b9f88ae5`:** pyright `0 errors, 4 warnings` (all pre-existing,
in files PR C is not expected to touch); unit suite `7892 passed`.

Production launchers are blocked by `require_launch_approval.sh`; a
deliberate launch is prefixed `SIDERIUS_ALLOW_LAUNCH=1`. Mutating git/gh
commands are blocked by `require_commit_approval.sh`; approved mutations
are prefixed `SIDERIUS_GIT_APPROVED=1`.

---

## 0. Pre-implementation audit (performed 2026-08-08)

Five findings, each of which changes the plan. **Two make PR C smaller
than Part III assumed; one (§0.5a) makes C1 wider by one consumer.**

### 0.1 Formal promotion is ALREADY reachable for a generated model — but only via override

Part III scoped PR C as *"restore formal promotion"*. The audit shows that
is the wrong verb.

PR A's Gate 2C persisted a record whose shape proves it was **formal**.
The stamping site is unambiguous
(`ml_hyperparameter_tune_agent.py:5554`):

```python
if not trial_config.is_trial:
    final_record["scientific_authority"] = ScientificAuthority.from_context(...)
...
if trial_config.is_trial:
    final_record["is_trial"] = True
```

Gate 2C's record carries `scientific_authority` and **no** `is_trial` key,
with `formal_validity: "valid"` and a numeric
`denoising_score = -2.727240835313264`. So for a generated model, this
chain already works end to end:

```text
generated plugin -> clean measurement subprocess -> pre-formal measurement
                 -> admission -> FORMAL executes -> formal record persisted
```

**But the head of the chain was bypassed.** The same run logged:

```text
[FORMAL OVERRIDE] WARNING: no successful trial round is HealthGate-valid
in this iteration — planner's plan unchanged. Score may be unreliable.
```

Formal therefore ran on the **planner's unvalidated plan**, not on a
validated trial winner. The untested segment is the *head*, not the tail:

```text
PROVEN by PR A       measurement -> admission -> formal -> record
NOT YET PROVEN       valid trial -> winner -> pre-formal measurement
```

#### The log assertion, stated precisely — "FORMAL OVERRIDE" is a misnomer

`_apply_formal_round_strategy`
(`ml_hyperparameter_tune_agent.py:1789-1838`) emits **three different**
`[FORMAL OVERRIDE]` lines, and only one of them is the pathology. An
earlier draft of this document asserted "`[FORMAL OVERRIDE]` absent",
which is **wrong** — the healthy path prints it too. The name refers to
overriding the *planner's* plan **with the winner's parameters**, which is
precisely what PR C wants to happen.

| line | emitted when | meaning for PR C |
|---|---|---|
| `:1834` `strategy=… winner='…' score=… inherited=…` | a winner exists and its params are inherited | **the target state** |
| `:1798` `WARNING: no successful trial round is HealthGate-valid …` | `winner is None`, plan returned unchanged | **the pathology** |
| `:1795` `strategy=independent winner=none inherited=(none)` | `independent` strategy disclaims inheritance | not applicable — C5 must not use `independent` |

**Consequence.** The Gate assertion is:

```text
REQUIRED ABSENT   the :1798 WARNING line
REQUIRED PRESENT  the :1834 line, with winner=<non-none> and a numeric score=
```

`:1834` also formats `winner['denoising_score']:.4f`, so a winner with no
numeric score cannot reach that line — the assertion is self-reinforcing.

### 0.2 The `get_output_type` unknown fallback has zero current dependants

Measured at `b9f88ae5`:

```text
MODEL_REGISTRY                88 models
BUILTIN_OUTPUT_TYPES           6
PLUGIN_OUTPUT_TYPE_REGISTRY   82
models relying on the unknown -> "classifier" fallback:  0
```

Every registered model resolves explicitly. The fallback fires **only when
registration has failed** — precisely the case where returning
`"classifier"` converts an infrastructure failure into wrong scientific
semantics. Failing closed therefore has a blast radius of *zero healthy
paths*, which is much smaller than PR A assumed when deferring it.

**Five** production consumers must handle the new failure mode:
`sandbox_executor.py:1116`, `models_format_sandbox.py:584`,
`inference_single.py:243`, `evaluate_vram_skill/wrapper.py:223`, and
`agent/prompts.py:1014` — the fifth was missed on the first pass and
found by the §0.5a audit.

### 0.3 The estimator name-branches gate ADMISSION, not just throughput

The operator's rule is that a model name may key identity, logging or
registry lookup, but must not change **correctness, reachability or
scientific semantics**. Measured against that:

| site | branch | consequence for a generated model |
|---|---|---|
| `training_skill/estimator.py:136` | `act_factor = 1 if model_type == "fcnet" else 2` | activation-memory factor |
| `training_skill/estimator.py:164` | `if model_type == "transformer"` | step-time model |
| `training_skill/estimator.py:244` | `if model_type == "fcnet"` | " |
| `inference_skill/estimator.py:127` | `if model_type == "transformer"` | inference step-time |
| `inference_skill/estimator.py:185` | `if model_type == "fcnet"` | " |

These feed the **time estimate that gates admission**. A generated model
always takes the generic branch, so a mis-estimate can produce
`skipped_time_risk` — a *reachability* outcome, not a throughput one.
PR A observed `skipped_time_risk` in Gate 2R attempt 2 (from an oversized
workload, not from this), which is the same terminal state this class of
defect would produce.

**In scope for PR C** by the operator's own predicate.

### 0.4 `inference_defaults` is throughput — with one reachability edge

`inference_batch_for` falls back to 25 for an unregistered model
(throughput → **PR G**). But `is_inference_batch_registered` feeds the
planning-time estimator, which in PR A's Gates printed:

```text
!!! model_type '<generated>' has no registered inference batch — using
    runtime fallback (25). Inference-phase wall-time estimate is
    UNCALIBRATED for this novel architecture. Treat verdict as best-effort.
```

An uncalibrated inference estimate feeds the same admission decision as
0.3. **Resolved by O-C-2: the reachability consequence is PR C's, the
actual batch selection stays PR G's** — see C3 §2.

### 0.5 Audits run for the operator's corrections (2026-08-08)

Three audits requested when the design was approved. **Two changed the
plan.**

#### (a) There is a FIFTH production consumer of `get_output_type`

C1 was scoped to four. The missed one is `agent/prompts.py:1012-1014`:

```python
if force_model != "auto":
    from ml_models.plugin_loader import get_output_type
    output_type = get_output_type(force_model)
```

This runs at **prompt-rendering** time, before any execution, and its
typed refusal is unlike the other four — a planner prompt cannot be
rendered for a model whose contract is unknown. Scope corrected to five.

> This is PR A's lesson recurring verbatim: *a rule existing in source is
> not evidence that every consumer is known.* The first enumeration was
> made from the execution path and silently omitted the prompt path.

Also to invert in C1: `tests/unit/agent/test_output_contract_end_to_end.py:144`
currently **pins the defect** —
`assert get_output_type("never_registered_model_xyz") == "classifier"` —
added by PR A deliberately to make the silent default visible. C1 must
flip it, not delete it.

#### (b) The valid-trial head is controllable at RECORD level — no training

`_best_trial_winner` (`:1406-1415`) selects on a **pure predicate over a
record dict**:

```python
candidates = [r for r in memory_history
              if is_valid_candidate(r)                      # pure
              and r.get("is_trial") is True
              and (r.get("memory") or {}).get("time_mode") == "trial"]
return max(candidates, key=lambda r: r["denoising_score"])
```

`is_valid_candidate` (`execute_tools/health_checks/candidate_eligibility.py:231`)
is a total function of the record. So a HealthGate-valid trial can be
**constructed**, never trained-for. This is what makes the operator's
C5a correction implementable without new machinery.

A deterministic harness for the very function under test already exists:
`tests/unit/agent/tune_ml_hyperparam_agent/test_force_formal_round.py`
asserts on the `[FORMAL OVERRIDE]` lines. **C5a extends it; it does not
invent a mechanism.**

#### (c) Resume RE-REGISTERS plugins; the replay risk is narrower than feared

`restore_prior_state` repopulates `MODEL_REGISTRY`,
`PLUGIN_CONFIG_REGISTRY` and `PLUGIN_OUTPUT_TYPE_REGISTRY` from plugin
files in the workspace (`tests/unit/core/test_resume.py:255-274`), so a
resumed run's `get_output_type` calls happen **after** restoration, not
against a dead registry.

The residual risk is therefore specific, and C1 must audit exactly it:
*a historical record whose plugin FILE no longer exists*, where
restoration cannot repopulate the entry. **Not yet established** whether
any path then calls `get_output_type` on that name. C1 step 1.

---

## 1. Commit plan

| # | Commit | Touches | Independently reviewable |
|---|---|---|---|
| **C1** | Unknown output contract fails closed (`UnknownOutputContractError`) | `plugin_loader.py`, **5** consumers, tests | Yes |
| **C2** | Sweep the import-side-effect / two-paths-disagree class | audit + targeted fixes, guardrail | Yes |
| **C3** | Estimator name-branches that gate admission | both estimators, tests | Yes |
| **C4** | Clean-subprocess transport fixture for generated models | tests only | Yes |
| **C5a** | **HARD ACCEPTANCE** — deterministic valid-trial → formal head | tests + evidence | Yes |
| **C5b** | **CONFIRMATION** — real training on hardware; cannot fail acceptance by collapsing | evidence only | Yes |

Ordering rationale: **C1 before C4**, because the clean-subprocess fixture
should assert the *failing-closed* behaviour rather than the silent
default. **C3 before C5b**, because a mis-estimate that produces
`skipped_time_risk` would make the Gate's failure ambiguous.

### Binding principles inherited

From Part III §E.2 and PR A's additions, all in force:

1. **Gradual genericization** — in-passing, never a big-bang rewrite.
2. **Complete transport contract** — parent reachability is never evidence
   of subprocess reachability; a transport test must fail when any single
   hop is removed.
3. **The metric is frozen.**
4. **Audit BOTH production branches** (built-in vs generated plugin).
5. **A transport contract starts at the REAL producer**, not the first
   typed object — PR A learned this the expensive way.
6. **Audit consumers as consumers, not as prose** — PR A misjudged two
   surfaces by reading their comments.

---

## Commit C1 — An unknown output contract fails closed

### 1. Goal

Stop `get_output_type` converting a **registration failure** into wrong
scientific semantics. Today an unregistered model silently resolves to
`"classifier"`, so a regressor whose declaration was lost anywhere upstream
is judged — and trained, and scored — as a classifier.

**Why this commit:** it is the smallest change that removes a silent
default, and §0.2 shows the blast radius on healthy paths is zero. It must
precede C4 so the transport fixture asserts an error rather than a default.

### 2. Scope

**The shape, fixed by operator decision O-C-3 — loud internally, typed
externally.** A raw exception must not escape to kill a campaign, and an
ignorable sentinel must not exist at all:

```text
get_output_type(unregistered)
    -> raise UnknownOutputContractError(model_name)      dedicated type

each consumer catches and maps to ITS OWN layer's typed refusal:
    sandbox config validation  -> typed configuration/infrastructure refusal
    ExperimentConfig           -> explicit validation failure
    inference                  -> typed execution refusal
    VRAM probe                 -> measurement/config unavailable
    planner prompt render      -> typed prompt-construction refusal  (§0.5a)
```

Rationale, recorded: reaching a site that *needs* a concrete output
contract while the model is unregistered is an **invariant/registration
failure**, not an expected workflow outcome — so an exception is the
correct internal signal. Expected outcomes stay typed values.

**Changes**
- `ml_models/plugin_loader.py` — `get_output_type` (`:158`) unknown branch
  plus the new `UnknownOutputContractError` type.
- **Five** production consumers (§0.5a corrected this from four), each
  catching explicitly: `core/sandbox_executor.py:1116`,
  `ml_models/models_format_sandbox.py:584`,
  `execute_tools/inference_single.py:243`,
  `agent/skills/evaluate_vram_skill/wrapper.py:223`,
  `agent/prompts.py:1014`.
- `tests/unit/agent/test_output_contract_end_to_end.py:144` — inverted,
  not deleted (it is PR A's deliberate pin on the defect).
- Tests.

**Must remain unchanged**
- Resolution for every model in `BUILTIN_OUTPUT_TYPES` or
  `PLUGIN_OUTPUT_TYPE_REGISTRY` — all 88 today.
- `hybrid` semantics for `fcnet`.
- The metric, the scorer, and every score.

**Dependencies:** none (PR A merged).

**Explicit non-goal:** changing *when* registration happens. C1 makes the
failure loud; it does not make registration more reliable — that is C2.

### 3. Implementation plan

- [x] **Historical-replay boundary audit (blocking, operator-required).**
      **DONE 2026-08-08 — negative finding, see §3b.** Replay never
      performs the lookup; no replay-boundary handling implemented.
      §0.5c narrowed this to one case: a historical record whose plugin
      **file is gone**, so `restore_prior_state` cannot repopulate the
      entry. Establish whether any path then calls `get_output_type` on
      that name. If **no**: record the negative result and proceed. If
      **yes**: handle *missing contract → not established* **at the
      historical read boundary**. Under no circumstance restore the
      silent live default to serve replay — live fail-closed semantics
      are not negotiable for legacy convenience
- [x] Re-measure at `cc8a2088`: `6 builtin + 82 plugin = 88`, dependants
      **0** — unchanged from design time (§3b)
- [x] `UnknownOutputContractError(LookupError)` in `plugin_loader.py`,
      carrying `.model_type`; message blames registration and explicitly
      disclaims the classifier reading
- [x] All five consumers inspected and mapped, each in its own idiom:
      `sandbox_executor` → `ValueError("Plugin Output Contract Unavailable
      (registration defect, not a config error)")`, deliberately worded
      apart from the generic `Configuration Rejected`;
      `models_format_sandbox` → `ValueError` inside the Pydantic validator,
      surfacing as `ValidationError`;
      `inference_single` → `RuntimeError("error_inference: …")`, reusing a
      **recognised** category rather than inventing `error_infrastructure`,
      which nothing downstream handles;
      `evaluate_vram_skill` → `ValueError` (this module's idiom at `:160`,
      `:250`);
      `agent/prompts.py` → `ValueError` naming the forced model
- [x] No consumer lets it escape. Proven by mutation M2, not by reading
- [x] Implemented; 88/88 resolutions and `fcnet → hybrid` unchanged
- [x] Message asserts `REGISTRATION FAILED` and carries
      *"does NOT mean the model is a classifier"*, pinned by test

### 3b. C1 blocking-audit RESULT — 2026-08-08, at `cc8a2088`

**Verdict: NEGATIVE FINDING. Historical replay never performs the lookup.
C1 proceeds; no replay-boundary handling is needed.**

#### Re-measure (§4.1 of the mandate)

```text
builtin=6  plugin=82  total=88  fallback_dependants=0
BUILTIN_OUTPUT_TYPES = {punet: classifier, fcnet: hybrid,
                        transformer: classifier, wavenet: classifier,
                        rnn: classifier, gated_fno: classifier}
```

Unchanged from design time. No healthy registered model depends on the
fallback.

#### Equivalent-defect sweep

Searched for paths that read `PLUGIN_OUTPUT_TYPE_REGISTRY` /
`BUILTIN_OUTPUT_TYPES` **directly**, bypassing `get_output_type` — an
inlined `.get(name, "classifier")` would be the same defect wearing a
different hat. **None found in production**: the only direct production
touches are *writers* (`plugin_loader.py:151,237`,
`workflows/model_exploration.py:830`, `core/resume.py`). Every production
*reader* goes through `get_output_type`.

#### The replay question, answered empirically rather than by reading

The risk was real on paper. `restore_prior_state`'s own docstring
(`core/resume.py:1194-1199`) states that a missing plugin file emits a
`UserWarning` and **keeps the JSON record** — "`memory_history`
reconstruction only reads the JSON; only training would need the class".
This is first-class, tested behaviour
(`test_missing_plugin_file_warns_and_continues`,
`test_invalid_plugin_file_warns_and_continues`,
`test_some_plugins_present_some_missing_partial_restore`). So after a
resume, `memory_history` **can** hold records whose `model_type` is
unregistered.

The open question was whether anything then looks one up. Rather than
argue from reading, `get_output_type` was wrapped with a tracer recording
every call that reaches the fallback, and the **entire unit suite** was
run under it:

```text
7892 passed, 2 skipped, 4 xfailed in 443.21s
fallback hits: 1
```

The single hit:

```text
model_type: never_registered_model_xyz
  tests/unit/agent/test_output_contract_end_to_end.py:144
      test_registry_default_would_hide_a_dropped_declaration
```

That is PR A's deliberate pin on the defect — **no production frame
beneath it**. Every resume/replay test in the suite ran under the tracer
and none reached the fallback.

#### Instrument limitation, and how it was closed

The tracer patches the module attribute, so a consumer that binds the
function at import time would evade it. One does:
`execute_tools/inference_single.py:23`. Closed by construction rather than
by tracing: its `model_type` arrives as `-m model_type` from
`sandbox_executor.py:1518-1524`, which is the **live** execution parameter
of `execute_inference`, and it runs *after* `_validate_configs` has
already resolved the contract for that same model. It can never receive a
historical record's name.

#### Consequence for the plan

- The C1 failure-and-edge-case row *"Legacy record replay referencing a
  since-deleted plugin"* is **discharged as not-reachable**, not
  implemented. Recorded as a negative finding per the mandate.
- C1's blast radius is now **empirically** zero, not merely zero by
  registry arithmetic.
- The `-p gotcensus` tracer is reusable; the plugin lives in the session
  scratchpad and is not part of the diff.

### 4. Validation plan — RESULTS

**Unit** — `tests/unit/ml_models/test_unknown_output_contract_fails_closed.py`
- [x] All 6 built-ins resolve unchanged, including `fcnet → hybrid`
- [x] Every registered plugin resolves to its declared contract (all 82)
- [x] An **unregistered** name fails closed with a message naming the model
- [x] The error is distinguishable from "this model is a classifier"

**Negative / invalid input**
- [x] Empty string, whitespace-only, and `"PUNET"` (a case-insensitive
      "helpful" lookup would be the same silent default in disguise)
- [x] Registration *after* a failed lookup resolves — the failure is not
      cached, which the resume and `model_exploration` paths both need
- [x] The error is catchable as `LookupError`

**Backward compatibility / default parity**
- [x] Built-in contract table pinned **by value**, not read back from the
      table under test
- [x] Full unit suite: `7905 passed, 2 skipped, 4 xfailed` (was 7892)

**Integration / consumer reachability** —
`tests/unit/ml_models/test_unknown_contract_consumer_reachability.py`
- [x] `sandbox_executor` plugin branch, driven with a genuinely divergent
      registry pair (config registered, output type not)
- [x] `ExperimentConfig` validator, driven by deleting `punet` from
      `BUILTIN_OUTPUT_TYPES` so the real validator runs on the real class
- [x] `evaluate_vram_skill._build_probe_tensors`
- [x] `agent/prompts.get_planner_user_prompt`, plus a test that `auto`
      and the built-ins still render unchanged
- [x] `inference_single` — **not** unit-tested; see the honesty note below

**Real-training Gate:** none. Correct — nothing here needs one.

### 4b. C1 evidence — recorded 2026-08-08

| item | result |
|---|---|
| Targeted battery | `23 passed in 3.38s` |
| Full unit suite | `7905 passed, 2 skipped, 4 xfailed in 435.38s` |
| ruff check | `All checks passed!` |
| ruff format --check | `752 files already formatted` |
| pyright | `0 errors, 4 warnings` — unchanged from baseline |

#### Mutation battery — 4 applied, **4/4 caught**

| # | mutation | result |
|---|---|---|
| M1 | restore `return "classifier"` for an unknown model | **12 failed** |
| M2 | remove `agent/prompts.py`'s catch so the raw error escapes | **1 failed** |
| M3 | delete the sandbox's specific catch, folding the failure into the generic `Configuration Rejected` — i.e. recreate the V20 misdiagnosis | **1 failed** |
| M4 | let the VRAM probe fall through so `output_type` stays `None` and the 256-bin target is chosen silently | **1 failed** |

Each mutation was applied at exactly one asserted site, run, then reverted
and the baseline re-confirmed green.

#### One consumer is guarded but not unit-tested — stated, not glossed

`execute_tools/inference_single.py` is a subprocess `__main__` whose lookup
sits inside the inference body. It is **unreachable by construction**: its
`--denoising_model` is the live model passed by
`sandbox_executor.execute_inference:1518-1524`, after `_validate_configs`
has already resolved that same model's contract. Its guard is defence in
depth, justified because "currently unreachable" is exactly what was
believed about the registry divergence that cost V20 two PRs. **Its
reachability is established by source inspection, not by a test**, and
this document says so rather than letting a four-of-five consumer battery
read as five.

### 5. Acceptance criteria — MET

- [x] `get_output_type` raises `UnknownOutputContractError`; never returns
      `"classifier"`, never an `"unknown"` sentinel
- [x] 88-model resolution identical pre/post
- [x] Four of five consumers have a reachability+conversion test; the
      fifth is source-verified and declared above
- [x] No consumer propagates the raw exception (M2)
- [x] Mutations: 4/4 caught

### 6. Failure and edge cases

| Case | Required behaviour | Status |
|---|---|---|
| Model registered *after* an earlier lookup | Later lookup resolves; failure not cached | **tested** |
| `hybrid` (fcnet) | Unchanged | **tested** |
| Legacy record replay referencing a since-deleted plugin file | Handle at the historical read boundary | **discharged — not reachable, §3b** |
| A resumed run whose plugin file still exists | Unchanged; `restore_prior_state` repopulates all three registries | **verified, §3b** |
| `force_model` names an unregistered model at prompt-render time | Typed prompt-construction refusal | **tested** |
| Registries diverge (config present, output type absent) | Distinguishable infrastructure refusal, not "config rejected" | **tested (M3)** |

### 7. Verification commands and evidence

```bash
.venv/bin/python -m pytest tests/unit/ml_models/test_unknown_output_contract_fails_closed.py \
    tests/unit/ml_models/test_unknown_contract_consumer_reachability.py \
    tests/unit/agent/test_output_contract_end_to_end.py -q
.venv/bin/python -m pytest tests/unit -q -m "not real_run"
.venv/bin/python -m ruff check . && .venv/bin/python -m ruff format --check .
PYRIGHT_PYTHON_GLOBAL_NODE=off uv run pyright
```

All recorded in §4b. One pre-existing suite behaviour worth noting:
`tests/unit/scripts/test_pr3_l2p_preflight.py::test_preflight_all_invariants`
fails while production files are uncommitted (`no_production_file_modified`)
and passes once C1 is committed. That is the guard working, not a defect —
the same behaviour PR A saw.

### 8. Commit boundary

- [ ] Diff touches `plugin_loader.py`, the **five** consumers and their tests
- [ ] No estimator changes (C3), no Gate evidence (C5)
- [ ] Diff summary, staged files, tests and deviations shown before commit

---

## Commit C2 — Sweep the import-side-effect / two-paths-disagree class

**STATUS: DONE 2026-08-08. One production-reachable defect found and fixed
at its source, plus one latent site closed. Loss registry audited clean.**

### 1. Goal

Find and close the shape that produced V20's `CONFIG_REJECTED`: **state
reconstructed by import side effect, where a path reads the registry
without executing the populating import.**

### 2. Audit — enumeration and verdicts

**Exactly one import-side-effect site exists.** `ml_models/models_sandbox.py:749-755`
calls `extend_registries(MODEL_REGISTRY, PLUGIN_CONFIG_REGISTRY)` in its
module tail, populating all three registries. `plugin_loader` itself only
declares the empty dicts — importing it populates nothing.

Reader verdicts, each **measured** in a clean subprocess rather than read:

| reader | sees plugins without importing `models_sandbox`? | verdict |
|---|---|---|
| `models_sandbox.MODEL_REGISTRY` | 88 — it *is* the populating module | fine |
| `plugin_loader.get_output_type` | **yes, self-heals** 0 → 82 via its lazy `BUILTIN_OUTPUT_TYPES` import | fine, and now pinned |
| `models_format_sandbox.get_config_class` | **NO — 0 of 82, returns `None` silently** | **PRODUCTION DEFECT — fixed** |
| `core.sandbox_executor` (2 direct membership reads) | **NO — 0 of 82** | **latent — closed** |
| `loss_models_sandbox._load_custom_loss` | n/a — no import side effect | **audited clean** |

#### Finding 1 — `get_config_class` was never actually fixed

PR #185 is recorded as closing the V20 defect. It closed the **call site**:
`validate_candidate_configs` gained an explicit `models_sandbox` import.
The **function** was left vulnerable, so every other caller still depended
on some unrelated module happening to import `models_sandbox` first.

Measured at `f16f02fd`, a clean process importing only
`models_format_sandbox`:

```text
get_config_class("<a real plugin on disk>")  ->  None
PLUGIN_CONFIG_REGISTRY                       ->  0 entries (of 82 on disk)
```

Silently. No warning, no exception — the same silent-default class C1 had
just eliminated for output contracts, in the sibling lookup function.

**Fix:** `get_config_class` triggers the populating import before reading
the plugin registry, mirroring the pattern `get_output_type` already used.
It must stay a *lazy* import: `models_sandbox` imports
`models_format_sandbox`, so a module-level import would be circular.
Built-in lookup is returned first and is untouched.

#### Finding 2 — `sandbox_executor`'s two direct reads

`_validate_configs` (`:1096`) and the training-side validation (`:1463`)
test `model_type in PLUGIN_CONFIG_REGISTRY` **directly**, so Finding 1's
fix does not cover them. With an empty registry a plugin model fails the
membership test and falls through to the **built-in** branch, producing a
confusing config error instead of using its own config class.

**Honest reachability:** not observed in production. The parent process
always registers the current model explicitly —
`workflows/model_exploration.py:829` on generation and
`core/resume.py::_add_plugin_to_registries` on restore — so the import
side effect is a *backstop*, and the genuinely exposed case is the clean
subprocess, which is what #185 hit. Closed anyway, because "not observed"
is precisely what was believed about this shape before it cost two PRs.

**Fix:** one module-level side-effect import in `sandbox_executor`, chosen
over rewriting the two membership tests because changing which branch a
model takes is a behavioural risk and an import is not.

#### Audited and clean — recorded so it is not re-audited

`loss_models_sandbox._load_custom_loss` resolves in two explicit tiers
(in-memory `LOSS_REGISTRY`, then a filesystem fallback reading
`SIDERIUS_LOSS_DIRS` **at call time**) and raises `ValueError` naming both
surfaces on failure. It never depends on an import side effect. Not a
finding.

#### No mechanical guardrail was added — and why

C2's plan allowed one if a sound mechanical check existed. It does not:
deciding statically whether "a registry read is reachable without its
populating import" is a whole-program reachability question over lazy
imports, and any grep-level approximation would be both noisy and
bypassable. Per the plan's own instruction, this is stated rather than
faked, and the property is enforced instead by the real-subprocess tests
below and by C4's transport fixture.

### 3. Implementation plan

- [x] Enumerate registry-mutating imports — exactly one (`models_sandbox` tail)
- [x] Identify every reader and measure each in a clean subprocess
- [x] Record each finding as production-reachable / latent / clean
- [x] Fix Finding 1 at the function, not at another call site
- [x] Close Finding 2 with a bounded side-effect import
- [x] Guardrail question answered explicitly (none sound; see above)

### 4. Validation plan — RESULTS

`tests/unit/ml_models/test_registry_population_is_self_healing.py`, all in
**real spawned subprocesses** with a plugin written to `tmp_path` and
exposed via `SIDERIUS_PLUGIN_DIRS`. An in-process test cannot express this
property: by collection time the session has already imported
`models_sandbox`, so every assertion would pass vacuously. Nothing reads
`agent_generated/models`, which is gitignored and empty on CI.

- [x] `get_config_class` resolves a plugin with only `models_format_sandbox` imported
- [x] importing `core.sandbox_executor` populates the registry
- [x] `get_output_type`'s pre-existing immunity is pinned as intentional,
      asserting `"regressor"` so the value provably came from the plugin
      file rather than a built-in or a default
- [x] C1 and C2 compose: population is automatic, absence is still loud
- [x] Full unit suite `7909 passed, 2 skipped, 4 xfailed in 442.37s`
- [x] ruff clean; ruff format 753 files; pyright `0 errors, 4 warnings`

#### Mutation battery — 2 applied, **2/2 caught**

| # | mutation | result |
|---|---|---|
| M5 | remove `get_config_class`'s self-healing import — i.e. restore #185 at its source | **1 failed** |
| M6 | delete `sandbox_executor`'s side-effect import as "unused", which is exactly how it looks to a reader or an autofixer | **1 failed** |

### 5. Acceptance criteria — MET

- [x] Written enumeration of import-side-effect registries and readers,
      with a measured verdict per reader
- [x] Every reachable finding fixed with a regression test that fails
      without it (M5, M6)
- [x] Zero silent fixes

### 6. Failure and edge cases

| Case | Behaviour |
|---|---|
| No further findings | Was a legal outcome; not the outcome — two were found |
| `models_sandbox` mid-import when `get_config_class` runs | Import is a no-op; behaviour exactly as before, no worse |
| Import fails outright | `models_sandbox` already wraps `extend_registries` in try/except with a printed warning, so a bad plugin cannot break the import |
| A finding belonging to PR B/D/G | None arose |
| Global import-order redesign required | Not required — both fixes are one line each |

### 7. Verification commands and evidence

```bash
.venv/bin/python -m pytest tests/unit/ml_models/test_registry_population_is_self_healing.py -q
.venv/bin/python -m pytest tests/unit -q -m "not real_run"
```

Recorded in §4 above.

### 8. Commit boundary

- [x] Two one-line production fixes, their tests, and this audit record
- [x] No C1 rework, no estimator changes (C3), no Gate evidence

---

## Commit C3 — Estimator name-branches that gate admission

**STATUS: DONE 2026-08-08. Five name branches replaced by truthful
predicates; built-in estimates byte-identical across all 18 parity cells;
all three guardrail xfail groups converted to passing.**

### 1. Goal

Remove the model-name branches in the training and inference estimators,
because they feed the **time and VRAM estimates that gate admission** — so
a generated model's reachability depended on matching a hardcoded name.

### 2. What the five branches actually encoded — they are NOT one thing

The plan required reading each before replacing it. They fall into three
kinds, and only two of them ever harmed a generated model:

| site | encodes | harm to a generated model |
|---|---|---|
| `training:136` `act_factor = 1 if fcnet else 2` | the **output contract** (fcnet is the one hybrid) | none — a plugin took the 2x branch, same as five of six built-ins |
| `training:164`, `inference:127` `if model_type == "transformer"` | **attention matrices exist** | **REAL: charged 0** for an invented attention model — the *optimistic* direction, admit-then-OOM |
| `training:244`, `inference:185` `if fcnet: cls(cfg, loss_type=...)` | a **constructor API difference** | none — plugins take `__init__(self, config)`, so the else-branch was already right |

Replacements, each a property the model actually has:

```text
act_factor        -> _output_contract(model_type) == "hybrid"
attention term    -> attention_shape(model_type, model_config) is not None
constructor       -> inspect.signature(cls.__init__) accepts "loss_type"
```

### 3. Implementation plan

- [x] Read both estimators in full and classify each branch (table above)
- [x] Capture an 18-cell built-in parity baseline **before** touching code
- [x] Replace each name predicate with the property it stood for
- [x] Verify parity; investigate and resolve every difference
- [x] Convert the guardrail xfail groups

### 4. Two implementation-time findings that changed the work

#### FU-C-1 — the shipped transformer estimate under-counts by 2x

The parity capture caught this, not a unit test, which is why the capture
existed. `TransformerConfig` declares `nhead=4`, but the shipped code reads
`model_config.get("nhead", 2)`. So whenever the caller's dict omits the
key, production charges for **half** the attention memory the model
actually builds:

```text
train  536,592,000  ->  1,048,592,000 bytes   (at the parity fixture's shape)
infer  264,196,000  ->    520,196,000 bytes
```

Using the class default would be both more accurate **and** more
conservative. C3 did **not** make that change: the mandate requires
built-in estimates to stay value-identical unless a change is explicitly
justified *and approved*, and a calibrated built-in estimate is an operator
decision, not a refactor's prerogative. The fallback is pinned at the
pre-C3 literals with a test asserting `(2, 2)` so it cannot drift silently.

> **FU-C-1 — needs an operator decision.** Owner: PR C or PR G. Direction
> is conservative (a larger estimate), so the risk of adopting it is
> spurious rejection, and the risk of leaving it is admit-then-OOM for
> built-in transformer runs with a partial config dict.

#### The first attention predicate was wrong, and parity caught it

The initial replacement read `model_config.get("nhead")` alone. That
*dropped* the attention term whenever a caller passed a partial dict —
making the built-in estimate **more optimistic**, the one direction an
estimator must never move by accident. Corrected so the **declaration**
comes from the config class and the **value** from the caller.

### 5. The guardrail scanned comments, so "9 violations" was never 9 branches

Converting the xfail groups surfaced a defect in the guard itself. It
exempted docstrings but scanned `#` comments as live code, so the tracked
count mixed real branches with prose — `inference_defaults`' two
"violations" were **both comments** (its dict *keys* were already exempt,
correctly, since a registry keyed by name is explicitly allowed). Writing
comments that explain *which* branch was removed pushed the counts up,
4 -> 7 and 3 -> 4.

The cheapest way to clear the guard was therefore to stop explaining which
model a formula came from. That is a perverse incentive, so the guard was
made precise instead: `_code_only_lines` strips `#` comment text via
`tokenize`, keeping the code before a trailing comment so
`foo("transformer")  # note` is still caught.

**`_PENDING_CLEANUP` is now empty, and that mattered more than it looks.**
With a label present, a *reintroduced* name branch was reported `xfail`
instead of `failed` — the guard detected the regression and then tolerated
it. Verified by mutation both ways. The three reasons were also stale in
exactly the way the operator flagged during PR A's merge: they named an
"A.6 / A.7 / A.9" plan that V21 superseded.

### 6. Validation plan — RESULTS

- [x] **Built-in parity: identical across all 18 cells** (6 models x 3
      losses x {params, training estimate, inference estimate})
- [x] Exactly one built-in is charged for attention, found by property
- [x] A generated attention model is charged **without being named**
- [x] A generated model without attention is not charged — guards the lazy
      over-fix of inflating every unregistered model into `skipped_time_risk`
- [x] Only the hybrid contract gets the 1x activation factor, asserted
      through the public estimate rather than a private helper
- [x] An unresolvable model is estimated conservatively, not refused —
      C1 made `get_output_type` raise, so without this a *missing* estimate
      would become a *rejected* candidate
- [x] `loss_type` is passed only to classes whose signature accepts it
- [x] All six built-ins still instantiate for a param count
- [x] Guardrail: `4 passed`, xfail groups gone
- [x] Full unit suite `7927 passed, 2 skipped, 1 xfailed` (xfailed 4 -> 1)
- [x] ruff clean; ruff format 753 files; pyright `0 errors, 4 warnings`

#### Mutation battery — 3 applied, **3/3 caught**

| # | mutation | result |
|---|---|---|
| M7 | reintroduce `if model_type == "transformer":` in live code | guardrail **failed** (with `_PENDING_CLEANUP` emptied; **xfail-tolerated** before, which is why it was emptied) |
| M8 | reintroduce `1 if model_type == "fcnet" else 2` | guardrail **failed** |
| M9 | attention predicate reading only the caller's dict | built-in parity **CHANGED** on all 3 transformer cells |

### 7. Acceptance criteria — MET

- [x] Built-in estimates byte-identical, recorded as a captured table
- [x] Two of three xfail groups converted — in fact **all three**
- [x] No estimate became more optimistic; the attention change is strictly
      more conservative for generated models (0 -> charged)
- [x] No surrogate predicate invented. Each replacement is a property the
      model genuinely has: its declared contract, its declared attention
      parameters, its constructor signature
- [x] The one case where no truthful generic value existed (FU-C-1's
      `nhead` fallback) was **not guessed** — it was pinned to the shipped
      literal and escalated

### 8. Commit boundary

- [x] Both estimators, the guardrail's precision fix, and their tests
- [x] No `inference_defaults` change — that is C3b (O-C-2)
- [x] No C1/C2 rework, no Gate evidence

---

## Commit C3b — `is_inference_batch_registered` (O-C-2)

**STATUS: DONE 2026-08-08. NEGATIVE FINDING — the invariant O-C-2 asked PR C
to establish is already true. No production code changed; the property is
now pinned so it cannot quietly stop being true.**

### 1. Goal

Establish, per operator decision O-C-2:

```text
generated model has no hand-maintained name-table entry
     !=  uncalibrated or degraded admission semantics
```

O-C-2 also said PR C **need not delete** the predicate and that keeping it
for logging is fine — audit consumers first. That instruction is what made
the outcome a test rather than a rewrite.

### 2. Audit — measured, and the answer is "already harmless"

Two facts make the invariant hold today:

**(a) The forecast and the run use the same function.** `execute_inference`
falls back to `inference_batch_for(model_type)`
(`sandbox_executor.py:1543`) and the planning estimator calls the same
function, so an unregistered model is forecast with exactly the batch it
will run with:

```text
registered      : False
runtime batch   : 25
estimator batch : 25
CONSISTENT      : True
```

The forecast is *unhand-tuned*, not *wrong*. The flag's name overstates the
problem.

**(b) The flag reaches only observability surfaces.** It becomes a
`RuntimeEstimate.warnings` entry (`estimate_types.py:416`) and a record
field. Every use of `warnings` across `core/runtime_control/` is a
**producer** — `warnings=(...)`, `(*estimate.warnings, note)` — and none is
a predicate. Nothing decides on it.

So absence from the table changes throughput, not admission, and the whole
module stays **PR G's**.

### 3. What C3b actually did

Both facts are one edit away from becoming false, so they are pinned:

- [x] planning batch == runtime batch for an unregistered model
- [x] the flag is raised but does not change the estimate — a "safety"
      multiplier on uncalibrated models would be a name-keyed admission
      penalty wearing a different hat
- [x] the flag lands in `warnings` and leaves `provenance`, `confidence`
      and `expected_seconds` untouched
- [x] registered built-ins still report as calibrated — guards the lazy
      over-fix of deleting the table to silence the flag, which would make
      every model "calibrated" by making none of them calibrated **and**
      silently change five built-ins' real batch, including `transformer`,
      whose entry is 1 rather than 25 for a memory reason

### 4. Validation — RESULTS

- [x] `8 passed`; ruff clean; ruff format unchanged

#### Mutation battery — 2 applied, **2/2 caught**

| # | mutation | result |
|---|---|---|
| M10 | give the estimator its own fallback so the forecast diverges from what runs | **1 failed** |
| M11 | make the flag price the estimate (`total * 1.5` when uncalibrated) | **1 failed** |

### 5. Acceptance criteria — MET

- [x] The O-C-2 invariant is established **and** pinned
- [x] `inference_batch_for`'s throughput choice untouched — PR G's
- [x] The predicate was not deleted; consumers were audited first

### 6. Commit boundary

- [x] One test module. **No production change** — the finding was negative
      and manufacturing a refactor to justify the commit is exactly what
      the plan forbids

---

## Commit C4 — Clean-subprocess transport fixture for generated models

### 1. Goal

Make the generated-model transport contract **mechanically enforced**, so
the V20 class cannot return: a fixture that spawns a real subprocess and
drives the full reconstruction chain, failing if any hop is removed.

**Why a separate commit:** it is test infrastructure that outlives PR C
and must be reviewable on its own. It also becomes the standing artifact
Binding principle 2 requires.

### 2. Scope

**Changes:** tests only. No production code.

**Dependencies:** C1 (assert fail-closed, not the silent default).

### 3. Implementation plan

- [ ] Build a fixture that writes a never-before-seen generated plugin to
      a temp dir and drives, **in a real spawned subprocess**:
      ```text
      generated plugin -> plugin dir -> worker spec -> subprocess env
        -> child import -> registry reconstruction -> config lookup
        -> measurement executor
      ```
- [ ] Assert the child cannot satisfy the test using a registry inherited
      from the parent — verify by construction, not by hope
- [ ] Add a hop-deletion matrix: removing each hop must fail
- [ ] Cover **both** output contracts, per PR A's lesson

### 4. Validation plan

- [ ] Fixture passes for a novel classifier and a novel regressor
- [ ] **Hop-deletion matrix**: every hop, removed one at a time, fails
- [ ] Parent-registry contamination is impossible in the fixture
- [ ] Runtime bounded — this runs in the normal unit suite or is marked so
      it does not slow it unacceptably; **measure and record**

### 5. Acceptance criteria

- Every hop in the declared chain has a deletion case that fails.
- The fixture spawns a real subprocess; an in-process approximation is not
  acceptable evidence.
- Both contracts covered.

### 6. Failure and edge cases

| Case | Required behaviour |
|---|---|
| Fixture passes with a hop deleted | The fixture is wrong — fix it before trusting any PR C claim |
| Subprocess unavailable in CI | Skip **loudly** with a reason; never silently pass |
| Fixture slow enough to hurt the suite | Mark and record the cost; do not delete coverage to save seconds |

### 7. Verification commands and evidence

- [ ] Hop-deletion matrix results — **to record**
- [ ] Fixture wall time — **to record**

### 8. Commit boundary

- [ ] Tests only, no production code

---

## Commit C5a — HARD ACCEPTANCE: the valid-trial head, fully deterministic

### 1. Goal

Prove the segment PR A did **not** prove (§0.1): **given that a
HealthGate-valid trial exists, the winner really becomes the formal
plan** — the `:1798` no-valid-winner WARNING never fires and the `:1834`
winner line names it.

**This is a state-machine proof, not a model-quality proof.** The
proposition under test is:

```text
PROVE      "if a valid trial exists, the winner drives formal"
NOT        "this model trains well enough to produce a valid trial"
```

> **Corrected by operator decision, 2026-08-08.** The previous draft said
> *"choose the smallest workload that reliably produces a valid trial"*
> and allowed *"increase workload once"* on failure. **Both are deleted.**
> That is the V20 Case A error: whether a real model happens to train to
> HealthGate-valid is a **scientific outcome**, and a scientific outcome
> must never be a state-machine acceptance oracle. Tuning the workload
> until the science cooperates would make this Gate meaningless.

### 2. Scope

The trial's validity is **dictated by the harness**, not earned by
training. §0.5b establishes this is possible with no new machinery:
`_best_trial_winner` selects via `is_valid_candidate`, a pure predicate
over a record dict, so a valid trial record is **constructed**.

**Dependencies:** C1–C4 green on the candidate head.

**Non-goal:** any statement about whether a real generated model tends to
produce valid trials. That is C5b's observation, and it is not acceptance.

### 3. Implementation plan

- [ ] Audit the existing seam first: extend
      `tests/unit/agent/tune_ml_hyperparam_agent/test_force_formal_round.py`,
      which already drives `_apply_formal_round_strategy` and asserts on
      the `[FORMAL OVERRIDE]` lines. **Add a test-only mechanism only if
      the audit proves the existing seam cannot express a deterministic
      HealthGate-valid record for a generated model**
- [ ] Construct a valid trial record for a **generated** model name:
      `is_valid_candidate` true, `is_trial=True`,
      `memory.time_mode == "trial"`, numeric `denoising_score`
- [ ] Drive the head and assert the two-line rule
- [ ] Extend as far down the chain as the deterministic seam reaches —
      winner inheritance, pre-formal path, formal record — **recording
      exactly where determinism ends**, rather than overstating coverage

### 4. Validation plan

- [ ] At least one trial round is HealthGate-**valid**
- [ ] A winner is selected from it
- [ ] The `:1798` `WARNING: no successful trial round is HealthGate-valid`
      line is **absent**
- [ ] The `:1834` line is **present**, with `winner=` naming the valid
      trial's `exp_id`, a numeric `score=`, and a non-empty `inherited=`
- [ ] `formal_round_strategy` is **not** `independent` (that strategy
      disclaims inheritance and would make the assertion vacuous)
- [ ] Formal is entered on the winner's plan
- [ ] Pre-formal measurement succeeds for the generated model
- [ ] Admission succeeds
- [ ] A **formal** record is persisted — `scientific_authority` present and
      `is_trial` absent, per the stamping contract in §0.1

### 5. Acceptance criteria

- The `:1798` WARNING is absent **and** the `:1834` winner line is present
  naming the valid trial's `exp_id` — both conditions, not either.
- The formal record's provenance traces to that winner.
- Every assertion recorded with observed values, not "as expected".

### 6. Failure and edge cases

| Case | Required behaviour |
|---|---|
| **The controlled valid trial is not produced** | **HARNESS DEFECT — stop and audit.** Never "increase the workload". The trial's validity is dictated, so failure to produce one means the fixture is wrong, not that the model underperformed |
| The `:1798` WARNING fires despite a constructed valid trial | **Gate FAILS** — this is exactly the property under test |
| Determinism runs out partway down the chain | Legitimate; record the exact boundary and let C5b observe past it. Do **not** paper over it with a stochastic step |
| Measurement fails | Preserve evidence and diagnose; likely in-scope |

### 7. Verification commands and evidence

- [ ] Command — **to record, shown before running**
- [ ] Log excerpt: `:1798` absent, `:1834` present with the winner's
      `exp_id` — **to record verbatim, both lines**
- [ ] Formal record fields — **to record**

### 8. Commit boundary

- [ ] Evidence only

---

## Commit C5b — REAL-HARDWARE CONFIRMATION (not a stochastic hard gate)

### 1. Goal

Observe the chain on real hardware with real training and inference. This
commit **confirms**; it does not **decide**.

> **REAL-TRAINING GATE — REQUIRES EXPLICIT OPERATOR APPROVAL.**
> Cold-start (no `--seed_paths`).

### 2. Scope — the evidence hierarchy, fixed by operator decision

PR C's acceptance rests on deterministic proofs plus PR A's existing real
evidence. C5b adds live confirmation on top:

```text
HARD ACCEPTANCE
  C5a   valid trial -> winner -> formal plan        deterministic head proof
  C4    generated plugin -> clean subprocess        true transport proof
  PR A  measurement -> admission -> formal -> record   ALREADY real (Gate 2C)

CONFIRMATION ONLY
  C5b   the same chain, live, on real hardware
```

**Therefore: if the real trial collapses and never becomes
HealthGate-valid, that is a scientific outcome and NOT a PR C failure.**
PR C is still accepted on C5a + C4 + PR A's tail evidence.

> **Explicitly forbidden:** `real trial collapses → change workload →
> rerun → repeat until formal appears`. That is the V20 Case A error and
> it is what this scope note exists to prevent. **One declared
> configuration, one run, report whatever happens.**

**If the run does produce a valid trial:** the full live
`valid trial → formal` chain is confirmed — record it as a strengthening
of the evidence, not as the thing that made PR C pass.

**Ideal variant, only if it already exists.** A seam giving
*controlled pseudo trial → REAL pre-formal measurement → REAL formal
training* would control the head while genuinely exercising the tail.
**Audit whether such a seam exists; do not build one for a Gate.**

**Boundary:** reachability of the formal channel, never score quality.

**Dependencies:** C5a passed.

### 3. Implementation plan

- [ ] Audit for an existing controlled-head / real-tail seam; record the
      finding either way, and **do not construct one if absent**
- [ ] Reuse PR A's fixed typed plans
- [ ] Draft exact commands with the paired `--data_scope` /
      `--health_gate_files`, `--data_dir`, and a declared launch posture —
      the three refusals PR A hit are avoidable by construction
- [ ] Obtain explicit approval, then run cold-start **once**
- [ ] Archive records, manifests and hardware provenance

### 4. Validation plan

Observations to record — **not** pass/fail conditions unless marked:

- [ ] Whether a real trial round reached HealthGate-valid — **observation**
- [ ] If it did: the §0.1 two-line rule holds live (`:1798` absent,
      `:1834` present with the winner's `exp_id`) — **observation**
- [ ] Real training and inference complete — **required**
- [ ] Frozen scorer executed; `file_vector` persisted — **required**
- [ ] Terminal scientific status is legitimate — **required**
- [ ] No scorer file in any PR C diff — **required**

### 5. Acceptance criteria

- Real training and inference ran, the frozen scorer executed, and
  `file_vector` was persisted for a generated model.
- The run reached a **legitimate terminal scientific status**, whatever
  that status is.
- **Not acceptance criteria:** score quality; whether the real trial
  happened to be HealthGate-valid; whether formal was reached live.

### 6. Failure and edge cases

| Case | Required behaviour |
|---|---|
| **Real trial collapses; never HealthGate-valid** | **NOT a PR C failure.** Record the scientific outcome. Acceptance stands on C5a + C4 + PR A's tail. **Do not rerun with a different workload** |
| Formal HealthGate invalidates the formal round | **PASS**, if the scorer ran |
| Formal never reached because no valid winner existed | Record it; acceptance is unaffected (see the evidence hierarchy in §2) |
| `skipped_time_risk` | Diagnose against C3; if the estimate is the cause, that is an in-scope defect |
| PR B resource contention | Record and defer; run Gates sequentially |
| Poor score | Not a failure. Record it |

### 7. Verification commands and evidence

- [ ] Commands — **to record, approved before running**
- [ ] Formal record ID and fields — **to record**
- [ ] Wall time, GPU time — **to record**
- [ ] Any step not run and why — **to record; never claim a pass**

### 8. Commit boundary

- [ ] Evidence only; any defect found gets its own runtime commit

---

## 2. Merge checklist — what PR C must prove

- [ ] **1. NO SILENT DEFAULT** — an unknown output contract fails closed;
      88/88 registered models resolve unchanged
- [ ] **2. NO NAME-KEYED REACHABILITY** — the estimator branches that gate
      admission are gone; built-in estimates unchanged
- [ ] **3. SUBPROCESS TRANSPORT ENFORCED** — a real spawned subprocess
      reconstructs a novel generated plugin, and every hop deletion fails
- [ ] **4. IMPORT-SIDE-EFFECT CLASS SWEPT** — enumerated, with a
      reachability verdict per finding
- [ ] **5. AUTHORITATIVE FORMAL PROMOTION FROM A VALID TRIAL WINNER** —
      proven **deterministically by C5a** (`:1798` absent, `:1834` present
      naming the constructed winner's `exp_id`), *not* by C5b's live
      outcome. C5b confirms on real hardware and cannot fail this item by
      producing a collapsed model (§C5b evidence hierarchy)
- [ ] **6. NINE VIOLATIONS ACCOUNTED FOR** — each of the nine tracked
      name-keyed violations is either closed (C3: 7) or carries a written
      follow-up ID and a stated reason (C3: 2 → PR G, see §0.4)

### What PR C is explicitly NOT required to prove

The ledger's merge criterion is *"no unexplained name-keyed **correctness
or reachability** dependency"* — **not** "no name lookup at all". This
distinction is binding, and a reviewer must not tighten it:

```text
FINE       registry[model_name]          identity, logging, provenance,
           artifact.model_name           registry keying

FORBIDDEN  if model_type == "transformer": correctness_behaviour = X
           else:                           correctness_behaviour = Y
```

A name-keyed branch with a **throughput-only** consequence is PR G's, and
leaving it in place is not a PR C failure.

Only with all six may this be claimed:

> **Anything the agent invents is a first-class citizen in every isolated
> production surface, and the formal channel is reachable for it from a
> valid trial rather than an override.**

### Mapping to the ledger's three validation tiers

| Ledger tier (`v21_priorities.md` PR C → Validation) | Commit |
|---|---|
| **Deterministic** — the xfail groups convert or are re-scoped with an ID | C3 (+ C1, C2 regressions) |
| **Transport, clean subprocess — the primary gate** | C4 |
| **Real, bounded** — one cold-start iteration, novel name, scored trial round **and** formal promotion boundary | C5b (C5a is a cheaper pseudo rehearsal, additional to the ledger) |

---

## 3. PR-level review template

Filled at completion, per Part III §E.7 (the `v20_priorities.md` §20.11
fields plus the five V21-specific lines).

---

## 4. Operator decisions — RESOLVED 2026-08-08

- [x] **O-C-1 — YES, rescope to the head.** PR C's formal acceptance
      targets the unproven `HealthGate-valid trial → winner → winner
      inheritance → formal`. The tail is already proven by PR A. The
      objective is renamed **"prove authoritative formal promotion from a
      valid generated-model trial winner"**. C5a must make the valid
      trial **deterministic**; neither real nor pseudo *scientific
      success* may serve as the oracle, and "increase workload once" is
      deleted. C5b is real confirmation, not a stochastic hard gate.
- [x] **O-C-2 — SPLIT BY CAUSAL RESPONSIBILITY.** The
      admission/reachability consequence of `is_inference_batch_registered`
      is PR C's; actual `inference_batch_for` selection and throughput
      stay PR G's. Two PRs touching one module is acceptable — **PR
      boundaries follow causal problems, not files.** PR C need not delete
      the predicate; audit consumers first, and logging use is fine.
- [x] **O-C-3 — RAISE INTERNALLY, TYPE AT BOUNDARIES.** `get_output_type`
      raises a dedicated `UnknownOutputContractError`. Each production
      consumer explicitly catches and maps it to that layer's typed
      refusal. **No ignorable `"unknown"` sentinel**, and **no raw
      exception reaching campaign level.** Rationale: needing a concrete
      contract for an unregistered model is an invariant failure, not an
      expected workflow outcome.

### Two design corrections applied with the approval

- [x] **C5a: "no valid trial → increase workload once" DELETED.**
      Producing the controlled valid trial is a **harness
      responsibility**; failing to produce one is a harness defect that
      must stop and be audited (§C5a).
- [x] **C1: historical-replay audit is BLOCKING and precedes
      implementation.** Live unknown must fail closed without letting an
      old artifact crash on a since-deleted plugin — handled at the
      historical read boundary, never by restoring the silent default
      (§0.5c, C1 step 1).

### Confirmed unchanged by the operator

- **C2's bounded audit is approved as written**, including that
  *"no further findings"* is a legitimate outcome. Do not manufacture a
  refactor so the commit looks productive.
- **C3's "no generic predicate exists → STOP AND ASK" is retained.** Some
  branches may encode genuine empirical calibration with no simple
  property standing behind them; **inventing a surrogate predicate is
  forbidden**. A typed calibration hint might be right, but it may also
  widen scope — hence the stop.

**Status: cleared to begin C1.**
