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

- [ ] **Historical-replay boundary audit (blocking, operator-required).**
      §0.5c narrowed this to one case: a historical record whose plugin
      **file is gone**, so `restore_prior_state` cannot repopulate the
      entry. Establish whether any path then calls `get_output_type` on
      that name. If **no**: record the negative result and proceed. If
      **yes**: handle *missing contract → not established* **at the
      historical read boundary**. Under no circumstance restore the
      silent live default to serve replay — live fail-closed semantics
      are not negotiable for legacy convenience
- [ ] Re-measure the fallback dependency count at the implementation head;
      **abort and escalate if it is no longer 0**
- [ ] Define `UnknownOutputContractError` carrying the model name
- [ ] Inspect each of the **five** consumers and record, per site, the
      typed refusal it maps to — **decide from the call site; the five
      layers do not share one answer**
- [ ] Confirm no consumer lets the exception escape uncaught to campaign
      level — the "raw exception crashes the campaign" failure the
      operator ruled out
- [ ] Implement, keeping `hybrid` and all 88 registered resolutions intact
- [ ] Ensure the error names the model and says *registration failed*,
      not *the model is a classifier*

### 4. Validation plan

**Unit**
- [ ] All 6 built-ins resolve unchanged, including `fcnet → hybrid`
- [ ] A registered plugin resolves to its declared contract
- [ ] An **unregistered** name fails closed with a message naming the model
- [ ] The error is distinguishable from "this model is a classifier"

**Negative / invalid input**
- [ ] Empty string, `None`, and a name registered with an illegal contract

**Backward compatibility / default parity**
- [ ] **All 88 currently registered models** resolve to exactly the same
      contract as before the change — asserted as a captured table, the
      same technique PR A used for the 6 × 5 matrix
- [ ] The 6 × 5 built-in accept/reject matrix stays byte-identical

**Integration / pseudo**
- [ ] Each of the **five** consumers reached with an unregistered model
      produces its layer's typed refusal, not a silent classifier path
      and not an uncaught `UnknownOutputContractError`
- [ ] Replay/resume: whatever §0.5c's audit establishes, pinned by a test

**Real-training Gate:** none.

### 5. Acceptance criteria

- `get_output_type("<never registered>")` raises
  `UnknownOutputContractError` naming the model; it never returns
  `"classifier"` and never returns an `"unknown"` sentinel.
- The captured 88-model resolution table is identical pre/post.
- Each of the **five** consumers has a test proving it reaches the new
  failure path **and converts it** — reachability plus conversion, not
  just the helper in isolation.
- No consumer propagates the raw exception to campaign level.
- **Mutation, three sites:** (i) restoring the `"classifier"` default,
  (ii) removing any one consumer's catch so the raw error escapes, and
  (iii) widening the catch to a bare `except Exception` each turn a test
  red.

### 6. Failure and edge cases

| Case | Required behaviour |
|---|---|
| Model registered *after* an earlier lookup | Later lookup resolves normally; no caching of the failure |
| `hybrid` (fcnet) | Unchanged |
| Plugin registered with a contract outside the legal set | Fail closed, naming the illegal value |
| A consumer that legitimately probes before registration | **Inspect for this during the consumer pass.** If one exists, it needs an explicit "may be unknown" call form rather than a silent default |
| Legacy record replay referencing a **since-deleted plugin file** | Handle at the *historical read boundary* as **contract not established**. Must not crash replay; must not restore the live silent default (§0.5c, blocking audit) |
| A resumed run whose plugin file still exists | Unchanged — `restore_prior_state` repopulates all three registries first (§0.5c) |
| `force_model` names an unregistered model at prompt-render time | Typed prompt-construction refusal, not a crash and not a classifier prompt (§0.5a) |

### 7. Verification commands and evidence

```bash
.venv/bin/python -m pytest tests/unit/ml_models/ tests/unit/core/ -q
.venv/bin/python -m pytest tests/unit/agent/ -q -k "vram or inference or validator"
```

- [ ] 88-model resolution table, pre/post — **to record**
- [ ] Tests: counts + wall time — **to record**
- [ ] Mutation result — **to record**
- [ ] pyright / ruff — **to record**

### 8. Commit boundary

- [ ] Diff touches `plugin_loader.py`, the **five** consumers and their tests
- [ ] No estimator changes (C3), no Gate evidence (C5)
- [ ] Diff summary, staged files, tests and deviations shown before commit

---

## Commit C2 — Sweep the import-side-effect / two-paths-disagree class

### 1. Goal

Find and close remaining instances of the shape that produced V20's
`CONFIG_REJECTED`: **state reconstructed by import side effect, where two
paths in the same process disagree about whether a model exists.**

### 2. Scope

**Bounded audit** of the six surfaces Part III names — model-name lookup
tables, config registries, inference defaults, hardcoded compatibility
predicates, subprocess plugin loading and environment propagation,
model-specific branching — looking **only** for what makes a generated
model non-executable or silently mis-resolved.

**Must remain unchanged**
- Registration timing and ordering unless a defect requires it.
- `core/subprocess_env.py` as the single source of the child environment.

**Out of scope**
- Repository-wide refactor; renaming schemas; anything affecting only
  throughput (PR G).

**Dependencies:** C1 (so a mis-resolution surfaces as an error the audit
can see, rather than a silent default).

### 3. Implementation plan

- [ ] Enumerate every module whose import has a **registry-mutating side
      effect**; record the list before changing anything
- [ ] For each, identify all paths that read that registry and check
      whether any can run without the populating import — the exact #185
      shape
- [ ] Record each finding as: reachable-in-production / unreachable /
      test-only, with evidence
- [ ] Fix only the reachable ones, smallest scope each
- [ ] Add a guardrail that fails when a registry read is reachable without
      its populating import, if a mechanical form of that check exists —
      **inspect first; if no sound mechanical check exists, say so and
      rely on the C4 fixture instead**

### 4. Validation plan

**Unit**
- [ ] One regression test per reachable finding, each naming the defect

**Transport**
- [ ] Covered by C4's clean-subprocess fixture

**Backward compatibility**
- [ ] Full unit suite unchanged; no registration-order behaviour altered

**Real-training Gate:** none.

### 5. Acceptance criteria

- A written enumeration of import-side-effect registries and their readers,
  with a reachability verdict for each.
- Every reachable finding either fixed with a regression test, or recorded
  with a follow-up ID and a reason it is not reachable in production.
- **Zero silent fixes:** anything changed has a test that fails without it.

### 6. Failure and edge cases

| Case | Required behaviour |
|---|---|
| No further findings | A legitimate outcome — record the audit and its negative result rather than manufacturing a fix |
| A finding is test-only | Record, do not fix production for it |
| A finding belongs to PR B/PR D | Record and defer; do not widen PR C |
| Fixing one would reorder registration globally | **Stop and ask** — that is an architecture change, not a bounded fix |

### 7. Verification commands and evidence

- [ ] Registry/reader enumeration — **to record**
- [ ] Findings with verdicts — **to record**
- [ ] Tests: counts + wall time — **to record**

### 8. Commit boundary

- [ ] Audit record plus only the fixes it justifies
- [ ] No C1 or C3 work

---

## Commit C3 — Estimator name-branches that gate admission

### 1. Goal

Remove the five model-name branches in the training and inference
estimators (§0.3), because they feed the **time estimate that gates
admission** — so a generated model's reachability currently depends on
matching a hardcoded name.

**Why this commit:** it is the only remaining tracked name-keyed group
that changes reachability rather than throughput, and it must land before
C5b so a Gate failure cannot be ambiguous between "the chain is broken"
and "the estimate was wrong".

### 2. Scope

**Changes**
- `agent/skills/training_skill/estimator.py` (`:136`, `:164`, `:244`)
- `agent/skills/inference_skill/estimator.py` (`:127`, `:185`)
- `tests/unit/guardrails/test_no_model_name_branches.py` — the
  `training_estimator` and `inference_estimator` xfail groups
- Tests.

**Must remain unchanged**
- Estimates for the six built-ins must not move — these are calibrated
  numbers and changing them silently would alter admission for existing
  models.
- The runtime-control authority model: static estimates remain **prior
  producers**, never verdicts.

**`inference_defaults` — split by causal responsibility (O-C-2, decided).**
The same module is touched by two PRs, and that is correct: **PR
boundaries follow causal problems, not files.**

| surface | causal question | owner |
|---|---|---|
| `is_inference_batch_registered` | does absence from a hand-maintained name table degrade the **admission** estimate? | **PR C** |
| `inference_batch_for` | what is the **best actual** inference batch? | **PR G** |

The invariant PR C must establish:

```text
generated model has no hand-maintained name-table entry
        !=
uncalibrated or degraded admission semantics
```

**PR C need not delete `is_inference_batch_registered`** — audit its
consumers first. Keeping it for **logging** (`registered = false`) is
fine. What is forbidden is:

```text
unknown name -> admission estimate degraded -> skipped_time_risk
```

**Dependencies:** none, but sequenced before C5b.

### 3. Implementation plan

- [ ] Read both estimators fully and record what each branch actually
      encodes — an activation-memory factor, a step-time model, or
      something else. **Do not assume the five are the same kind of thing**
- [ ] For each, determine the generic predicate the name is standing in
      for (measured parameter count, declared output contract, module
      introspection, or a plugin-declared hint)
- [ ] Replace name equality with that predicate
- [ ] Capture built-in estimates before and after; they must be identical
      or the difference must be justified in writing
- [ ] Convert the two guardrail xfail groups to passing

### 4. Validation plan

**Unit**
- [ ] Built-in estimate parity: all six models, both estimators, identical
      values pre/post — captured as a table
- [ ] A generated model gets an estimate derived from its own properties,
      not the generic fallback
- [ ] `fcnet`'s hybrid-specific behaviour preserved

**Negative**
- [ ] A model with no usable properties still produces a typed,
      conservative estimate — never a crash and never an optimistic one

**Backward compatibility**
- [ ] `test_no_model_name_branches` — `training_estimator` and
      `inference_estimator` groups pass; `inference_defaults` remains
      xfail (PR G)

**Real-training Gate:** none. Real behaviour is observed in C5b.

### 5. Acceptance criteria

- Built-in estimates byte-identical, recorded as a table.
- Two of the three xfail groups converted to passing (7 of the 9 tracked
  violations closed).
- The remaining `inference_defaults` group (2 violations) is **re-scoped
  in the guardrail itself** — its xfail reason must be rewritten from
  *"A.9 deletes core/inference_defaults"* to a **PR G follow-up ID** with
  the throughput-vs-reachability reason from §0.4. An xfail left pointing
  at a superseded plan is a stale directive, which is the failure mode
  PR A's merged-header fix addressed.
- **Mutation:** restoring any one name branch turns a test red.
- No estimate becomes *more* optimistic for any model — an estimator that
  under-predicts is the V18 failure class.

### 6. Failure and edge cases

| Case | Required behaviour |
|---|---|
| No generic predicate exists for a branch | **Stop and ask.** Deleting a calibration without a replacement would change admission silently |
| A built-in estimate does move | Justify in writing or revert; never accept a silent shift |
| Generated model has no parameter count yet | Conservative estimate, typed, never optimistic |

### 7. Verification commands and evidence

```bash
.venv/bin/python -m pytest tests/unit/agent/ -q -k "estimator or time or vram"
.venv/bin/python -m pytest tests/unit/guardrails/ -q
```

- [ ] Built-in estimate parity table — **to record**
- [ ] Tests: counts + wall time — **to record**
- [ ] Mutation results — **to record**

### 8. Commit boundary

- [ ] Diff touches the two estimators, the guardrail and tests
- [ ] No `inference_defaults` changes (PR G)

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
