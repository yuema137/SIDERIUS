# PR A — Make the existing output contract reachable

**Status: DESIGN, awaiting operator approval. No implementation has begun.**

| | |
|---|---|
| Plan section | `docs/design/v21_priorities.md` Part III, PR A |
| Gate | V21 launch blocker |
| Depends on | none |
| Blocks | the first V21 experiment (classification vs regression ablation) |
| Audit date | 2026-08-07, against `master` |

---

## A0. Verification toolchain (established 2026-08-07)

**pyright DOES run on this machine.** An earlier draft of this document
recorded it as unrunnable because the *system* Node is v10.19.0. That was
wrong: the project's own pyright/nodeenv path works, and the V20 hardening
already used it.

```bash
PYRIGHT_PYTHON_GLOBAL_NODE=off uv run pyright     # pyright 1.1.409
```

**Baseline on the PR A candidate head: `0 errors, 4 warnings`.** All four
warnings are pre-existing and in files this PR does not touch
(`core/runtime_control/bootstrap.py` ×2,
`core/runtime_control/gpu_requirement.py`,
`scripts/legacy_fcnet_timing.py`).

Type checking must therefore be run **locally before the final
checkpoint**, not deferred to CI — A3 changes a schema, and a typing
defect there should not first surface in CI.

Other commands used throughout:

```bash
.venv/bin/python -m pytest tests/unit/ -q -m "not real_run"
.venv/bin/python -m ruff check . && .venv/bin/python -m ruff format --check .
```

---

## 0. Scope correction that produced this document

This PR was originally scoped as *"build a capability-based output/loss
compatibility contract"*. **Code inspection showed that contract already
exists and is live.** The audit is recorded in Part I §P1 "Correction,
2026-08-07" and summarised here because it defines the whole PR.

**Already correct — do not rebuild:**

- `ExperimentConfig.validate_architecture_loss_match`
  (`ml_models/models_format_sandbox.py:484-515`) is the **single live
  production compatibility authority**, constructed at
  `core/sandbox_executor.py:1116`. It resolves output type and rejects
  `classifier + smooth_l1` and `regressor + ce/focal/focal_cw`;
  `hybrid` (fcnet) accepts any loss.
- `ml_models/plugin_loader.py` reads `PLUGIN_OUTPUT_TYPE` from a plugin
  module (`:81`), registers it (`:151`, `:237`), and `get_output_type`
  (`:158`) resolves `BUILTIN_OUTPUT_TYPES` → `PLUGIN_OUTPUT_TYPE_REGISTRY`.
- Verified empirically 2026-08-07: after registration,
  `get_output_type("my_generated_regressor")` returns `"regressor"`.

**The actual defect chain:**

```text
implementor hardcodes PLUGIN_OUTPUT_TYPE = "classifier"
    (ml_model_implementor.py:264, inside PLUGIN_TEMPLATE at :232)
  -> no regressor plugin is ever emitted
  -> and the validator would reject one anyway: the (1,256,64) shape gate
     (ml_code_validator_agent.py:346-355) runs BEFORE the declared type
     is read (:359), so the regressor branch (:375) is unreachable
  -> nothing ever registers as "regressor"
  -> get_output_type falls through to its "classifier" DEFAULT
  -> the live gate CORRECTLY rejects smooth_l1
```

The live gate is not the defect. It is behaving correctly on metadata the
producer chain can never generate.

**Therefore the objective is:** make the producer chain able to emit and
validate the metadata the existing contract already consumes.

---

## 1. Commit plan

| # | Commit | Touches | Independently reviewable |
|---|---|---|---|
| **A1** | Delete the dead, contradictory `check_compatibility` | `models_format_sandbox.py`, one test | **DONE** `452b1022` |
| **A2** | Validator reads the declared contract before applying shape expectations | `ml_code_validator_agent.py`, tests | **DONE** `5f97984d` |
| **A2b** | Shared pair-compatibility rule reaches the **plugin** production branch | `models_format_sandbox.py`, `sandbox_executor.py`, tests | **DONE** `625b0159` |
| **A3** | Explicit output contract, proposal → live gate | `proposal.py`, protocol, `ml_model_implementor.py`, tests | **DONE** `be8d4d46` |
| **A3b** | Producer's own smoke test and generated test honour the declaration | `ml_model_implementor.py`, tests | **DONE** `a4bede52` |
| **A4** | Symmetric contract in the proposer-facing prompt surface | prompt templates, docs | **DONE** `3d39dfe7` |
| **A4b** | The proposer is *asked* for `output_type`, and the parser *reads* it | `ml_model_proposal_agent.py`, `proposing_stage.md`, tests, gate advice | **DONE** `187d02ac` — **found by Gate 1R** |
| **A3c** | VRAM probe target shape follows the declared contract | `evaluate_vram_skill/wrapper.py`, tests | **DONE** `e70a60dd` — **found by Gate 2R** |

**Two commits were added mid-PR because the Gates found real defects.**
Both are numbered against the commit whose property they complete (A4b
completes A4's prompt surface; A3c completes A3's transport), not against
the Gate that exposed them — a defect belongs to the commit that fixes it.
Neither was foreseeable from the deterministic suite; see their entries
below.

> **Commit-boundary rule (operator, 2026-08-07).** A3b exists as its own
> commit because it changes **runtime behaviour**, and it was discovered
> during A4's doc-sync. A defect must be attributed to the commit that
> fixes it, never to the commit that happened to reveal it. Git history
> must answer cleanly: *which commit changed runtime behaviour, and which
> only changed what the agent is told?* A4 stays prompt-and-docs only.
| **A5a** | **Gate 1** — real LLM, no expensive training: both formulations expressible and implementable | gate advice fixtures (evidence only) | Yes |
| **A5b** | **Gate 2** — real training: both formulations reach a scored trial | none (evidence only) | Yes |

Ordering rationale: **A2 and A2b before A3.** If the implementor could
emit a regressor before the validator accepted one, every generated
regressor would fail validation and consume a retry — a live regression.
And **before the implementor starts generating regressors at all, an
illegal pair must already be cleanly refusable on the production path**;
otherwise PR A would open the hypothesis space while the one rule
separating legal from illegal pairs still did not run for generated
models. A1 is independent and first because it removes a rule that
contradicts the one A2 relies on.

### Binding principle — audit BOTH production branches

**Added 2026-08-07 after the §4b discovery.**

> **When production branches on built-in vs generated plugin, acceptance
> must audit both branches independently. A rule existing on one branch is
> never evidence that it governs the other.**

This is the same shape as the V20 lesson, one level up:

```text
V20   parent can load the plugin   != subprocess can load the plugin
V21   built-in path has the check  != generated-plugin path has the check
```

Both were invisible to a green test suite because the test exercised the
branch that already worked.

### Correction to "single authority"

The §0 audit said `ExperimentConfig.validate_architecture_loss_match` is
"the single production compatibility authority". §4b shows that is wrong:
it governs **built-ins only**. The corrected model, implemented by A2b:

```text
shared output/loss compatibility rule      <- THE authority
        ↑                        ↑
ExperimentConfig            plugin branch
(built-in consumer)         (generated-model consumer)
```

The authority is the **rule**, not either consumer. A2b extracts it once
and gives the plugin branch a call site — it must **not** re-implement
`if regressor and ce: ...` in `sandbox_executor.py`, which would recreate
the two-authorities defect A1 just deleted.

### Acceptance ladder

```text
A1-A4 deterministic tests
        ↓
Gate 1 (A5a)   real LLM, NO expensive training
        ↓
Gate 2 (A5b)   real GPU / training, controlled formulation
        ↓
full CI on the candidate head + per-commit acceptance
        ↓
merge PR A
```

Each rung proves a different property, so none is redundant GPU spend:

| Rung | Proves | Costs |
|---|---|---|
| A1-A4 | the mechanism is reachable **in code** | nothing |
| Gate 1 | a **real agent** can express and implement both formulations | LLM calls only |
| Gate 2 | both formulations **actually execute** to a scored record | GPU time |

**Neither gate is a merge step.** A1-A4 are commits within this PR; both
gates run against the candidate head and gate acceptance. A prompt or
schema defect must be caught in Gate 1, before any GPU is spent.

---

## Commit A1 — Delete the dead, contradictory compatibility rule

### 1. Goal

Remove `LossConfig.check_compatibility`, a name-literal compatibility rule
that has **zero production callers**, whose logic conflicts with the live
gate, and whose docstring falsely claims the Executor calls it.

**Why this commit and not another:** it is pure deletion with no
behavioural coupling to A2/A3. Doing it first means every later commit
reasons about exactly one compatibility authority. Leaving it until last
risks a reviewer "restoring" it while reading A2.

### 2. Scope

**Changes**
- `ml_models/models_format_sandbox.py` — delete `check_compatibility`
  (`:372-386`, including the `custom` deferral comment).
- `tests/unit/ml_models/test_loss_functions.py` — delete or rewrite the
  isolated test at `:268-279` that calls it.

**Must remain unchanged**
- `ExperimentConfig.validate_architecture_loss_match` — untouched, and
  becomes the sole documented authority.
- Every `LossConfig` field, default and validator.
- All existing accept/reject outcomes for built-in models.

**Dependencies:** none.

### 3. Implementation plan

- [x] Re-confirm zero production callers immediately before deleting —
      **confirmed 2026-08-07**: only the definition
      (`models_format_sandbox.py:372`) and three lines in one test
      (`test_loss_functions.py:268,275,279`). No non-test caller
- [x] Delete the method and its docstring — replaced with a NOTE recording
      why it was removed and pointing at the single authority
- [x] Rewrite the isolated unit test to target the live gate —
      `TestCheckCompatibilityCustom` → `TestCustomLossDefersToPlugin`,
      now constructing `ExperimentConfig` instead of calling a dead method
- [x] Add a comment on `validate_architecture_loss_match` naming it the
      single production compatibility authority
- [ ] Update `ml_models/` docs if the method is referenced — **open**:
      `docs/design/enable_loss_inventory.md:559,576,605` references it as
      completed historical work. Historical design records are not
      rewritten; a correction note is pending the §A1b decision below

### 4. Validation plan

**Unit**
- [x] `tests/unit/ml_models/` — **166 passed in 3.96 s**, zero failures
- [x] `test_model_configs.py` passes unchanged
- [x] `test_loss_functions.py` passes after the retarget

**Negative / invalid input**
- [x] `classifier + smooth_l1` still rejected via the live gate (matrix)
- [x] `hybrid` (fcnet) + every loss type still accepted (matrix row)
- [ ] `regressor + ce` — **not assertable for built-ins**: no built-in
      model declares `regressor` (`BUILTIN_OUTPUT_TYPES` is five
      classifiers + `fcnet: hybrid`). Deferred to A2/A3 fixtures

**Backward compatibility / default parity**
- [x] **6 × 5 accept/reject matrix byte-identical before and after** —
      `diff matrix_before.json matrix_after.json` empty:

      | model | focal | focal_cw | ce | smooth_l1 | custom |
      |---|---|---|---|---|---|
      | punet | ACCEPT | ACCEPT | ACCEPT | REJECT | ACCEPT |
      | fcnet | ACCEPT | ACCEPT | ACCEPT | ACCEPT | ACCEPT |
      | transformer | ACCEPT | ACCEPT | ACCEPT | REJECT | ACCEPT |
      | wavenet | ACCEPT | ACCEPT | ACCEPT | REJECT | ACCEPT |
      | rnn | ACCEPT | ACCEPT | ACCEPT | REJECT | ACCEPT |
      | gated_fno | ACCEPT | ACCEPT | ACCEPT | REJECT | ACCEPT |

**Static**
- [x] `ruff check` — All checks passed
- [x] `ruff format --check` — 12 files already formatted
- [x] `pyright` — **0 errors, 4 warnings** (all pre-existing, in files this
      PR does not touch). See §A0 for the correct invocation

**Real-training Gate:** none required.

### 4b. DISCOVERY — plugin models bypass the live compatibility gate

**Found while retargeting the A1 test, 2026-08-07. Material; see the
operator question at the end of this document.**

`SandboxExecutor._validate_configs` (`core/sandbox_executor.py:1085-1101`)
branches on registration, and its own docstring states it:

> *"Plugin models bypass ExperimentConfig (which has hardcoded Literals
> for core model types) and are validated directly against their own
> config class."*

```python
if model_type in PLUGIN_CONFIG_REGISTRY:          # :1093
    validated_m = PLUGIN_CONFIG_REGISTRY[model_type](**m_cfg).model_dump()
    validated_t = TrainConfig(**t_cfg).model_dump()
    validated_l = LossConfig(**l_cfg).model_dump()
    return ...                                     # never touches ExperimentConfig
# Core model: use the strict ExperimentConfig with cross-validation
exp_config = ExperimentConfig(**full_payload)      # :1116
```

**So `validate_architecture_loss_match` never runs for an agent-generated
model** — the only kind the agent produces. Verified empirically: a
registered plugin declaring `classifier` paired with `smooth_l1` is
**ACCEPTED** by the plugin branch (77 plugins in the registry; sampled
`acausal_dualpath_wavenet`, declared `classifier`).

This contradicts an approved premise of this PR — that the live gate is
the authority enforcing pair legality for generated models — and it
affects A5's negative controls, which assume `regressor + ce` is refused
for generated models. It is **not**.

### 5. Acceptance criteria

- `grep -rn "check_compatibility"` over non-test production code returns
  **zero** matches.
- The 6 × 5 built-in accept/reject matrix is byte-identical pre/post,
  recorded in this document as an explicit table.
- No test asserts against `check_compatibility`.
- `validate_architecture_loss_match` is unmodified (verified by diff:
  the function body must not appear in the diff).

### 6. Failure and edge cases

| Case | Required behaviour |
|---|---|
| A production caller is found during re-confirmation | **Stop.** Escalate — the audit was wrong and this PR's premise changes |
| `loss_type="custom"` | Previously a documented no-op deferral; the live gate treats it by output type. Confirm `custom` remains accepted for both contracts, or record the change explicitly |
| A downstream module imports the method by name | Import error surfaces at collection; must be fixed in this commit, not deferred |

### 7. Verification commands and evidence

```bash
.venv/bin/python -m pytest tests/unit/ml_models/test_loss_functions.py \
                          tests/unit/ml_models/test_model_configs.py -q
.venv/bin/python -m ruff check ml_models/ && .venv/bin/python -m ruff format --check ml_models/
```

- [ ] Tests: _count_ passed, _count_ failed, _wall time_ — **to record**
- [ ] Ruff: **to record**
- [x] pyright: **0 errors, 4 warnings** (pre-existing, untouched files)

### 8. Commit boundary

- [ ] Diff touches only `models_format_sandbox.py` and one test file
- [ ] No unrelated cleanup, no A2/A3 work
- [ ] Diff summary, staged file list, test output and any deviation shown
      to the operator **before** committing

---

## Commit A2 — Validator reads the declared contract first

### 1. Goal

Make `_check_instantiation_and_gradient` read `PLUGIN_OUTPUT_TYPE`
**before** applying a shape expectation, and derive the expected shape
from the declared contract — so a plugin declaring `regressor` and
emitting `[B, T]` can pass validation.

**Three distinct checks — do not collapse them.**

| # | Question | Owner |
|---|---|---|
| 1 | Is the declaration legal? (`output_type ∈ {classifier, regressor}`) | **this commit** |
| 2 | Does the built model match **its own declaration**? | **this commit** |
| 3 | Is the (contract, loss) **pair** legal? | **existing live gate** — must NOT be duplicated here |

Check 2 is the one that catches the dangerous case: a plugin declaring
`PLUGIN_OUTPUT_TYPE = "regressor"` whose forward still returns
`[B, 256, T]`. Metadata alone is not evidence of shape.

**Why this commit:** it is the single change that makes the regressor
branch reachable. It must land before A3, or generated regressors would
fail validation and burn retries.

### 2. Scope

**Changes**
- `nodes/ml_code_validator_agent/ml_code_validator_agent.py` —
  `_check_instantiation_and_gradient` (`:313`, called at `:452`):
  read the declared type first; derive the expected shape; keep the
  gradient check unchanged.
- `tests/unit/agent/ml_code_validator_agent/test_validator_agent.py` —
  new fixtures.

**Must remain unchanged**
- The `(instantiation_ok, gradient_ok, output_type_ok, error)` 4-tuple
  contract and every caller expectation at `:452`.
- Classifier validation outcomes, error strings included, for every
  existing plugin.
- The dead-parameter warning semantics (`:390-400`) — a warning, never a
  failure.
- The probe batch/length (`(1, 64)`) unless inspection shows it must
  change; if it must, record why.

**Dependencies:** A1 (so only one compatibility rule exists).

### 3. Implementation plan

- [x] Read the full function and its caller before editing — control flow
      recorded in §3b below
- [ ] **Class-count source — conditional rule (operator decision,
      2026-08-07).** Apply this test and record which branch was taken:

      > **Wire `configs/task_config.yaml:25 num_classes`** (today
      > prompt-only, read at `workflows/task_config.py:209`) **if** the
      > validator's existing production caller already holds a typed task
      > config, **or** it can be threaded through **one existing typed
      > boundary**.
      >
      > **Otherwise keep the `256` literal** and file a follow-up. Do not
      > add a global config singleton, change agent constructors broadly,
      > or introduce a new multi-layer transport for this — the causal
      > clarity of "regression reachability" outweighs an opportunistic
      > genericization of the class count.

- [x] **Branch taken: KEEP the `256` literal.** Evidence:
      `ml_code_validator_agent.py` contains **zero** references to
      `task_config` / `TaskConfig` / `num_classes`, and its production
      caller (`:452`) passes only `inp.model_file_path`. Threading the
      config would be a **new transport**, not "one existing typed
      boundary" — the conditional rule's "otherwise" branch. Recorded in
      code as follow-up **FU-A-1** on `_PROBE_NUM_CLASSES`
- [x] Read `PLUGIN_OUTPUT_TYPE` (default `"classifier"`) before the
      forward probe
- [x] Derive the expected shape from the declared contract:
      `classifier -> (1, 256, 64)`, `regressor -> (1, 64)`
- [x] Keep a declared-vs-actual mismatch as a **typed, specific** error —
      names both the actual shape and the shape the declaration requires
- [x] Leave the gradient check and its warning path untouched
- [x] Additive: fail closed on an unknown declaration; typed failure on a
      non-tensor output

### 3b. Control flow, before and after

```text
BEFORE                                AFTER
  probe with randint(0,256,(1,64))      read PLUGIN_OUTPUT_TYPE
  require shape == (1,256,64)  <-.      reject if not in {classifier,regressor}
  ...only then read declaration   |     derive expected shape from it
  check declared vs actual dims --'     probe
                                        reject non-tensor
                                        require shape == expected
```

**Discovery: BOTH arms of the old declared-vs-actual check were dead
code.** The `regressor` arm was unreachable because a `[B, T]` output was
rejected by the shape gate first — the defect this PR exists to fix. But
the `classifier` arm was equally unreachable: a shape equal to
`(1, 256, 64)` is 3-dimensional by construction, so `actual_dims != 3`
could never be true once the gate had passed. The check appeared to
enforce declaration/reality agreement and enforced nothing in either
direction. The new derivation is the first version that actually does.

**Error-string parity is exact.** For a declared classifier the message
formats `expected_shape = (1, 256, 64)` as `"(1, 256, 64)"` — byte-identical
to the previous hardcoded text, so existing failure-path expectations are
unchanged.

### 4. Validation plan

**Unit** — new class `TestDeclaredOutputContract`, 7 cases
- [x] Classifier fixture emitting `[1, 256, 64]` → PASS (parity)
- [x] Regressor fixture emitting `[1, 64]` → **PASS**
- [x] Classifier declared but emitting `[1, 64]` → FAIL, specific error
- [x] Regressor declared but emitting `[1, 256, 64]` → FAIL, specific error
- [x] Plugin with **no** `PLUGIN_OUTPUT_TYPE` → treated as classifier
      (legacy-read compatibility)

**Mutation proof — the acceptance signal, recorded**
- [x] With the production change stashed and the tests kept, **3 of 7 fail**:
      `test_declared_regressor_with_2d_output_passes`,
      `test_declared_regressor_but_3d_output_is_refused`,
      `test_unknown_declaration_fails_closed`.
      Pre-change error recorded verbatim:
      `Forward output shape (1, 64) does not match expected (1, 256, 64)`.
      Restored, re-verified green. This proves the tests bind to the
      production change rather than passing vacuously

**Negative / invalid input**
- [x] `PLUGIN_OUTPUT_TYPE = "nonsense"` → rejected with a specific error
      naming the bad value and both legal values; never coerced
- [x] Forward raises → existing "Forward pass failed" path unchanged
- [x] Model returns a non-tensor → typed failure, no traceback escape

**Backward compatibility / default parity**
- [ ] Every plugin currently in `agent_generated/models/` that validates
      today still validates, with identical `(inst_ok, grad_ok, otype_ok)`
      and identical error strings where applicable
- [ ] Sample at least 10 existing plugins; record the count actually run

**Integration / pseudo**
- [ ] `MLCodeValidatorAgent` end-to-end in pseudo mode over both fixtures
      via the production call path at `:452` — not the helper directly
      (reachability requirement)

**Real-training Gate:** none required.

### 5. Acceptance criteria

- A plugin declaring `PLUGIN_OUTPUT_TYPE = "regressor"` returning
  `[B, T]` returns `(True, True, True, None)` from the production call
  path at `:452`.
- The identical fixture fails on `master` with the recorded pre-change
  error `"Forward output shape (1, 64) does not match expected (1, 256, 64)"`
  — **both results recorded in §7 as the before/after pair.**
- Every sampled existing classifier plugin returns a byte-identical
  4-tuple and error string to pre-change.
- No caller of `_check_instantiation_and_gradient` is modified.
- The declared-vs-actual mismatch cases produce distinct, specific errors
  naming both the declared type and the actual dimensionality.

### 6. Failure and edge cases

| Case | Required behaviour |
|---|---|
| Missing `PLUGIN_OUTPUT_TYPE` | Default `"classifier"` — **stay silent**. See the legacy note below |
| Unknown `PLUGIN_OUTPUT_TYPE` value | **Fail closed** with a specific error. Never coerce to classifier |
| Declared/actual mismatch | Fail with an error naming declared type and actual dims |
| Class count differs from 256 | Out of scope here; if the probe reads config, a mismatch must be a typed error, not a silent pass |
| Plugin import fails | Existing path unchanged |
| Non-tensor output | Typed failure |

> **The `missing -> classifier` default is LEGACY-READ COMPATIBILITY, not
> a supported production path.** It exists so historical plugins in
> `agent_generated/models/` keep validating. **A3's producer must always
> declare the contract explicitly.** A newly generated plugin that relies
> on this default is a defect, not a convenience — if metadata is ever
> dropped again, the system must not silently "still look like it works".
> PR C decides whether the analogous fallback in `get_output_type` should
> fail closed.

### 7. Verification commands and evidence

```bash
.venv/bin/python -m pytest tests/unit/agent/ml_code_validator_agent/ -q
.venv/bin/python -m pytest tests/unit/agent/ -q -k validator
```

- [ ] Regressor fixture on `master` (expected FAIL) — **error string to
      record verbatim**
- [ ] Regressor fixture after change (expected PASS) — **to record**
- [ ] Existing-plugin parity: _n_ plugins sampled, _n_ identical — **to record**
- [ ] Tests: counts + wall time — **to record**
- [ ] pyright: **to record** (see §A0 for the invocation)

### 8. Commit boundary

- [ ] Diff touches the validator and its tests only
- [ ] No implementor changes (that is A3), no prompt changes (that is A4)
- [ ] Diff summary, staged files, test output, deviations shown before
      committing

---

## Commit A2b — Shared pair rule reaches the plugin production branch

### 1. Goal

Give the **generated-model** production branch a call site for the
model/loss compatibility rule. Without it, PR A would open regression
while the rule separating legal from illegal pairs still did not run for
the only kind of model the agent invents.

**Why this commit, before A3:** the implementor must not start emitting
regressors until an illegal pair can be cleanly refused on the production
path.

### 2. Scope

**Changes**
- `ml_models/models_format_sandbox.py` — extract
  `validate_output_loss_compatibility(output_type, loss_type, *, model_type)`
  plus `CLASSIFICATION_LOSSES` / `REGRESSION_LOSSES`.
- `ExperimentConfig.validate_architecture_loss_match` — delegate to it.
- `core/sandbox_executor.py` — the plugin branch of `_validate_configs`
  calls it.
- `tests/unit/core/test_plugin_loss_compatibility.py` — new.

**Must remain unchanged**
- The 6 × 5 built-in matrix, and the exact error strings.
- `custom` remains permitted for every contract.

**Dependencies:** A1 (one rule), A2 (declaration is trustworthy).

### 3. Implementation plan

- [x] Extract the rule as a module-level function, documented as **the**
      authority with both consumers named in its docstring
- [x] `ExperimentConfig` delegates — inline logic removed
- [x] Plugin branch resolves `get_output_type(model_type)` and calls the
      shared function **before** returning
- [x] No pair logic re-implemented in `sandbox_executor.py`

### 4. Validation plan

**Unit — 9 cases, all passing**
- [x] classifier plugin + `ce` / `focal` / `focal_cw` → ACCEPT
- [x] classifier plugin + `smooth_l1` → **REFUSE** (the case silently
      accepted before A2b)
- [x] regressor plugin + `smooth_l1` → ACCEPT
- [x] regressor plugin + `ce` / `focal` / `focal_cw` → **REFUSE**
- [x] `custom` still permitted for both contracts
- [x] Refusal happens at **config validation** — asserted via the
      `"Plugin Experiment Configuration Rejected"` wrapper, not a deep
      training/broadcast error

**Reachability + single authority**
- [x] Tests call the real `TidmadSandbox._validate_configs`, not the
      helper, so they exercise the production branch
- [x] Guardrail: the executor source (comments/docstrings stripped by
      `tokenize`, mirroring `test_runtime_authority_audit.py`) must
      contain the call and **no** inlined loss literals
- [x] Both-branch parity: `classifier + smooth_l1` refused on the
      built-in path **and** the plugin path

**Mutation proof**
- [x] Removing the call from the plugin branch turns **6 tests red**
      (3 regressor REFUSE cases, the classifier REFUSE case, the
      reachability guardrail, the both-branch parity test). Restored and
      re-verified green. This is the evidence the rule is *delivered*,
      not merely defined

**Backward compatibility**
- [x] 6 × 5 built-in matrix re-captured after A2b — still **identical to
      the pre-A1 baseline**
- [x] `tests/unit/core/` + `ml_models/` + validator: **280 passed**

**Static**
- [x] `ruff check` — All checks passed (one RUF059 found and fixed)
- [x] `ruff format --check` — clean
- [x] `pyright` — **0 errors, 4 warnings** (pre-existing, untouched files)

### 5. Acceptance criteria

- [x] The compatibility rule exists **once**; both branches are consumers.
- [x] Every illegal pair is refused on the generated-model branch at
      config-validation time.
- [x] Mutation proof recorded.
- [x] Built-in behaviour byte-identical.

### 6. Failure and edge cases

| Case | Behaviour |
|---|---|
| `custom` loss | Permitted for every contract — in neither loss family, so the rule falls through by construction. Deferral to the plugin preserved |
| Unregistered model name | `get_output_type` returns its `"classifier"` default. **Known gap, deferred to PR C** by operator decision — a registration failure still silently acquires classifier semantics |
| `hybrid` (fcnet) | Accepts any loss, unchanged |
| Plugin config invalid | Existing `"Plugin Experiment Configuration Rejected"` path, unchanged |

### 7. Verification commands and evidence

```bash
.venv/bin/python -m pytest tests/unit/core/test_plugin_loss_compatibility.py -q
.venv/bin/python -m pytest tests/unit/core/ tests/unit/ml_models/ \
                          tests/unit/agent/ml_code_validator_agent/ -q
```

- [x] New tests: **9 passed in 0.96 s**
- [x] Combined targeted: **280 passed in 4.78 s**
- [x] Mutation: **6 failed** with the call removed; restored green
- [x] Matrix: `diff matrix_before.json matrix_after_a2b.json` empty

### 8. Commit boundary

- [x] Touches the shared rule, its two consumers, and one new test file
- [x] No A3 work (no schema, no implementor changes)

---

## Commit A3 — Explicit output contract, proposal through to the live gate

### 1. Goal

Carry the output contract as an **explicit typed field** from the
proposal schema through to the generated plugin, so the implementor emits
`PLUGIN_OUTPUT_TYPE` from a declared decision rather than a literal.

**Operator decision, 2026-08-07 — do NOT infer the contract from the
loss.** A rule such as

```python
smooth_l1 -> regressor        # FORBIDDEN
ce / focal -> classifier      # FORBIDDEN
```

would re-couple output representation to loss family, merely relocating
the binding this PR exists to remove. The whole point is three
independent dimensions:

```text
proposal:
    output_type = regressor      <- declared
    loss_type   = smooth_l1      <- declared
                                 -> the live gate independently checks
                                    that the PAIR is legal
```

**Why this commit:** it is the producer half. Separated from A2 so a
later misbehaviour is attributable to producer or validator, not both.

### 2. Scope

**Changes**
- Proposal schema (`agent/schemas/proposal.py`) — add a typed output
  contract field, `Literal["classifier", "regressor"]`.
- `nodes/ml_model_implementor/ml_model_implementor.py` —
  `PLUGIN_TEMPLATE` (`:232`, applied at `:1220`): make
  `PLUGIN_OUTPUT_TYPE` (`:264`) and the forward-contract comment (`:259`)
  contract-dependent rather than literal.
- The protocol mapping proposal → implementor input.
- Tests under `tests/unit/agent/`.

**Must remain unchanged**
- Classifier generation output — **byte-identical** for an unchanged
  classifier proposal.
- `LOSS_PLUGIN_TEMPLATE` (`:471`) and the loss path.
- `ExperimentConfig.validate_architecture_loss_match` — still the sole
  authority deciding whether the (contract, loss) pair is legal.

**Dependencies:** A2 (validator must accept a regressor first).

**Explicit non-goal:** deciding *when* the agent chooses regression. This
commit makes it **possible**, not preferred. Prompt symmetry is A4.

### 2b. Transport contract (Binding principle 2)

This commit **does** cross typed boundaries, so the full chain is
declared and every hop is tested:

```text
proposal schema  (typed output_type field)
  -> protocol mapping to implementor input
  -> implementor PLUGIN_TEMPLATE rendering
  -> generated plugin's PLUGIN_OUTPUT_TYPE literal
  -> ml_code_validator_agent (A2 reads it)
  -> plugin_loader registration (:81, :151, :237)
  -> get_output_type (:158)
  -> ExperimentConfig.validate_architecture_loss_match  (live consumer)
```

**Deleting any single hop must fail a test.** In particular, a proposal
declaring `regressor` whose field is dropped by the protocol must not
silently produce a classifier plugin — that is precisely the
"produced but not delivered" class V20 kept hitting.

No process boundary is crossed here (that is PR C), so no clean-subprocess
proof is required for A3.

### 3. Implementation plan

- [x] Read `PLUGIN_TEMPLATE` (`:232`) and its `.format(...)` call site
      (`_assemble_plugin`, `:1211`) fully before editing
- [x] Inspect `agent/schemas/proposal.py` and the proposal → implementor
      protocol; insertion points recorded in §3b below
- [x] Add the typed field with a `Literal["classifier", "regressor"]`
      annotation; **legacy read only:** absent → `"classifier"`
- [x] Thread it through `local_full_spec` to `ImplementorInput`
- [x] Parameterize `PLUGIN_OUTPUT_TYPE` in the template, plus the
      forward-contract comment, via `_render_output_contract`
- [x] **Generate the matching HEAD, not only the metadata.** Resolved by
      inspection: `PLUGIN_TEMPLATE` carries `{init_body}`/`{forward_body}`
      placeholders — the *LLM* writes the head, the template wraps it. So
      this commit owns the **declaration and the documented contract**;
      that the head actually matches is (a) driven by the prompt in A4 and
      (b) **enforced** by A2's declared-vs-actual check. Defence in depth,
      as designed — the producer states the contract, the validator
      refuses a model that does not honour it

### 3b. Insertion points and the discovery about ForwardContract

```text
agent/schemas/proposal.py        ProposalOutput.output_type      (new)
agent/schemas/implementor.py     ImplementorInput.output_type    (new)
protocols/ml_model_propose_to_ml_model_impl.py
                                 local_full_spec: one mapped hop
ml_model_implementor.py:232      PLUGIN_TEMPLATE parameterized
ml_model_implementor.py:1211     _assemble_plugin passes the contract
ml_model_implementor.py          _render_output_contract (new helper)
```

**Discovery — `ImplementorInput` already carries a typed `ForwardContract`**
(`agent/schemas/task_config.py:31`), sourced from `configs/task_config.yaml`
with fields `input_shape`, `output_shape`, `num_classes`, `task_type`.

It is **not** the right home for `output_type`, and the distinction matters:

```text
ForwardContract   TASK-level, from config      "what this task looks like"
output_type       PER-PROPOSAL agent decision  "what THIS model commits to"
```

Putting a per-proposal choice into the task contract would make one
proposal's decision look like a property of the task. They stay separate.

**Known tension, handed to A4:** `ForwardContract.output_shape` currently
renders `"[B, 256, T] float32"` for every proposal, so a regressor
proposal's *prompt* still describes the classifier contract. That is a
rendering concern, and A4 already owns "every place the contract is stated
as a literal". Recorded here so the handoff is explicit rather than
forgotten.
- [ ] Make the forward-contract comment (`:259`) match the emitted contract
- [ ] Add a hop-deletion test per the transport contract above
- [ ] Confirm the new production path always sets the field explicitly —
      a *new* candidate must never rely on the legacy default

### 4. Validation plan

**Unit** — `TestOutputContractRendering`, 4 cases
- [x] Classifier rendering: declaration + contract comment unchanged
- [x] Regressor rendering: `PLUGIN_OUTPUT_TYPE = "regressor"`, comment
      states `[B, T]`, and **`[B, 256, T]` does not appear at all**
- [x] Unspecified contract → classifier (legacy read)
- [x] Unknown contract → `ValueError` at generation, not downstream

**Transport (Binding principle 2)** — `TestOutputContractTransport` +
`test_output_contract_end_to_end.py`
- [x] `output_type` survives proposal → protocol → implementor input
- [x] **Mutation: deleting `output_type=output.output_type` from
      `local_full_spec` fails `…survives_the_hop[regressor]`.** Note the
      classifier case still passes — the schema default makes this hop
      *silently lossy*, which is precisely why it is asserted rather than
      assumed
- [x] Transport must not "fix" an inconsistent proposal in transit:
      `output_type=classifier` + `smooth_l1` arrives unchanged, to be
      refused by the shared rule rather than quietly rewritten
- [x] End-to-end, **both contracts**, no LLM and no GPU:
      proposal → protocol → implementor → generated literal → **validator
      PASS** → `register_model_in_memory` → `get_output_type` returns the
      declared contract → shared rule accepts the legal pair and refuses
      the illegal one
- [x] A companion test pins *why* each hop is asserted individually:
      `get_output_type` returns `"classifier"` for an unregistered model,
      so a declaration dropped anywhere upstream would not raise — it
      would silently acquire classifier semantics

**Negative / invalid input**
- [x] Invalid contract value rejected by the `Literal` annotation at
      schema construction
- [x] `regressor + focal/ce` refused by the **shared rule**, unchanged —
      A3 did not duplicate it

**Backward compatibility / default parity**
- [ ] Regenerate a fixed historical classifier proposal; output is
      byte-identical to the committed artifact

**Real-training Gate:** none required.

### 5. Acceptance criteria

- For a fixed classifier proposal fixture, the generated plugin file is
  **byte-identical** to pre-change output (string equality, not "looks
  the same").
- For a regressor proposal fixture, the generated plugin declares
  `PLUGIN_OUTPUT_TYPE = "regressor"`, the forward-contract comment states
  `[B, T]`, **and the instantiated model's forward actually returns
  `[B, T]`** — asserted by running it, not by reading the template.
- The generated regressor passes the A2 validator **through
  `MLCodeValidatorAgent`**, not the helper directly.
- `get_output_type(<generated regressor>)` returns `"regressor"` after
  registration — proving the contract reached the live consumer.
- Every hop-deletion test fails when its hop is removed.
- **No inference from loss appears anywhere in the diff** — grep for
  `smooth_l1` in the implementor and protocol returns no
  contract-deciding branch.
- `LOSS_PLUGIN_TEMPLATE` does not appear in the diff.

### 6. Failure and edge cases

| Case | Required behaviour |
|---|---|
| Legacy proposal with no output-contract field | Default classifier — **legacy read only**; a new production proposal must set it explicitly |
| Proposal declares regression but a classification loss | **Left to the shared rule.** The implementor does not duplicate it; transport carries the inconsistency through unchanged so one authority refuses it |
| Protocol drops the field | Test fails — mutation-proven |
| Unknown contract reaches the implementor | `ValueError` at generation, before a plugin is written |
| Historical proposal fixture | Default keeps existing fixtures working; classifier rendering unchanged |

### 6b. Collision with an existing deferral guard — resolved

`test_implementor_prompt.py::TestDeferredScope` guards three hardcoded
contract strings against **accidental** removal, deferring them to
`enable_global_task_config.md` § Commit T2. A3 legitimately removes one of
them: the plugin-stub comment
`"forward contract: input [B, T] int64 → output [B, 256, T] float32"`.

Resolution, recorded in the test itself: that phrase was dropped from the
guard list because **a fixed literal there is now incorrect by
construction** — a regressor plugin must document `[B, T]`. Guarding its
presence would guard a defect. Coverage moved to
`TestOutputContractRendering`, which asserts *both* contracts render
correctly.

The other two phrases remain guarded and untouched. The `description.md`
one is an explicit **A3 → A4 handoff**: A4 owns making every rendered
contract statement symmetric.

### 7. Verification commands and evidence

```bash
.venv/bin/python -m pytest tests/unit/agent/ -q -k implementor
.venv/bin/python -m pytest tests/unit/agent/ml_code_validator_agent/ -q
```

- [ ] Classifier byte-identity check — **to record**
- [ ] Regressor generation + validation — **to record**
- [ ] Tests: counts + wall time — **to record**

### 8. Commit boundary

- [ ] Diff touches the implementor and its tests only
- [ ] No validator changes (A2), no prompt-contract changes (A4)
- [ ] Diff summary, staged files, tests, deviations shown before committing

---

## Commit A4 — Symmetric contract on the proposer-facing surface

### 1. Goal

Stop the prompt surface from stating classification as *the* task
contract, so regression is a visible, legal option rather than a hidden
one.

**Why this commit:** it changes what the agent is *told*, not what the
system *permits*. Keeping it separate means a behaviour change in agent
proposals is attributable to this commit alone.

### 2. Scope

**Changes**
- Contract statements in the proposer/implementor prompt surface,
  confirmed present at `ml_model_proposal_agent.py:330`,
  `ml_model_implementor.py:1726`, and the `proposing_stage.md` template.
- Node/skill `.md` docs per the repo's doc-sync rule.

**Must remain unchanged**
- Any advice-file text about model **scale** (that is PR E's territory,
  and PR E is measurement-only).
- The `~100M` proposal prior — explicitly **not** touched here.
- Loss inventory and Branch A/B reuse semantics.

**Dependencies:** A2 + A3 (do not advertise a capability before it works).

### 3. Implementation plan

- [x] Enumerate every place the forward contract is stated as a literal —
      full census in §3b below
- [x] Restate the contract symmetrically on the **agent-facing** surfaces
- [x] Keep the change textual — no schema or control-flow edits
- [x] Update the affected node/skill `.md` files (doc-sync rule):
      `ml_model_implementor.md` — the shape-contract bullet now shows the
      per-`output_type` table and names the three sites that must stay in
      step; `ml_model_proposal_agent.md` — new `output_type` row in the
      Output table naming the single authority and the transport.
      `ml_code_validator_agent.md:52` was **already** symmetric and needed
      no change

### 3a. Defect found during A4's census — the plugin's own tests

The doc-sync step surfaced a real A3 gap, not a documentation one.
`ml_model_implementor.md` claimed the shape contract was *"hardcoded into
`TEST_TEMPLATE.test_forward_shape` and asserted in `_smoke_test_plugin`"*.
It was, and both would have **rejected a correct regressor**:

```text
TEST_TEMPLATE.test_forward_shape   assert out.shape == (2, 256, seg)
_smoke_test_plugin                 expected = (1, 256, T)
```

So A3 could emit a plugin declaring `regressor`, and then the implementor's
own smoke check — and the plugin's own generated test file, which the
validator runs — would fail it. The producer would have been generating
artifacts it then rejected.

Both now derive the expected shape from the declaration:
`TEST_TEMPLATE` imports `PLUGIN_OUTPUT_TYPE` from the generated plugin and
branches on it; `_smoke_test_plugin` reads it off the module.

**This is the "audit both branches" principle applying to a surface I had
not counted as a branch.** A2 fixed the validator's shape check; the
producer had two more shape checks of its own.

Covered by `test_generated_test_file_matches_the_declared_contract`, which
writes the plugin and its generated test to disk and **runs pytest on
them** — the assertion is that the real artifact passes, not that a
template contains a string. Mutation-proven: reverting `TEST_TEMPLATE` to
the classifier-only shape fails the regressor case.

### 3b. Census of literal contract statements, and what A4 changed

`grep -rn "B, 256, T"` over `agent/ nodes/ workflows/ configs/`, classified:

**Changed — agent-facing, would mislead a regression proposal**

| site | what it said |
|---|---|
| `ml_model_proposal_agent.py:363` | *"The forward contract is fixed: … [B, 256, T]"* — a **hard constraint** in the proposal prompt |
| `ml_model_proposal_agent.py:330` | Golden-Paragraph spec: cite the contract verbatim; *"256 denoising bins … contract-fixed"* |
| `agent/schemas/proposal.py` | `mathematical_definition` field description |
| `proposing_stage.md` | new **Output contract** section: the two contracts, their legal losses, and that neither is the default |
| `ml_model_implementor.py` description.md | the validator's LLM reviewer reads this file as the model spec |
| `ml_code_validator_agent.py:72` | LLM review prompt: *"Wrong output shape that breaks the [B, 256, T] contract"* → judge against the **declared** contract |

**Already symmetric — no change needed**

- `agent/prompts.py:1010-1030` — the **tuner** prompt already branches on
  `get_output_type` and states both contracts with their legal losses.
  Evidence that the tuner surface was contract-aware all along; only the
  *proposer* surface hardcoded classification.
- `agent/schemas/validator.py:163` — already documents both.

**Deliberately left alone — not agent-facing**

Internal comments in `training_skill/estimator.py`,
`evaluate_vram_skill/{batch_resolver,wrapper}.py`, and stub-mode fixtures
in `llm_bridge.py`. These describe VRAM arithmetic for the current task,
not the contract offered to the agent. Changing them is genericization
work belonging to `enable_global_task_config.md` § T2, not A4.

### 4. Validation plan

**Unit**
- [x] `test_commit_prompt_still_carries_io_contract_line` **broadened**:
      asserts the input contract, **both** output contracts, and both legal
      loss families. Strictly stronger than the single sentence it replaced
- [x] New `test_commit_prompt_does_not_present_one_contract_as_fixed` —
      fails if *"forward contract is fixed"* returns, which would silently
      close the regression space at the prompt layer while schema and
      runtime still permit it
- [x] `test_description_documents_declared_contract` — both contracts,
      each asserting the other's shape is **absent**

**Integration / pseudo — behavioural, not string presence**
- [ ] Deterministic pseudo fixture: a **legal classification proposal** is
      accepted by the proposal schema and renders end to end
- [ ] Deterministic pseudo fixture: a **legal regression proposal** is
      accepted by the proposal schema and renders end to end

> String presence is insufficient evidence that the surface works. The
> two fixtures test the thing that matters — that a proposal of either
> kind is expressible and survives rendering.

**Negative**
- [ ] No prompt path renders a contract contradicting the live gate
- [ ] An illegal pair in a fixture is refused by the schema or the live
      gate, not silently rendered

**Descriptive only — never a gate**
- [ ] *(Optional)* 1-3 real proposer calls to observe whether the agent
      understands the symmetric prompt. Recorded as evidence about
      comprehension. **It must never be required that the LLM chooses
      regression for this PR to pass.**

**Backward compatibility**
- [ ] Token-count delta recorded; a large increase is a review flag

**Real-training Gate:** none required.

### 5. Acceptance criteria

- Every enumerated literal contract statement is symmetric, and the list
  is recorded in §7 with before/after.
- No production string states `[B,256,T]` as the *only* legal contract.
- Prompt token delta recorded per template.
- Advice files and the `~100M` prior do not appear in the diff.

### 6. Failure and edge cases

| Case | Required behaviour |
|---|---|
| A doc restates the old contract | Must be updated in this commit (doc-sync rule) |
| Prompt grows materially | Record the delta; flag for review |
| A pseudo fixture pins exact prompt text | Update the fixture and say so explicitly |

### 7. Verification commands and evidence

```bash
.venv/bin/python -m pytest tests/unit/agent/ -q -k "prompt or proposal"
```

- [ ] Enumerated contract sites, before/after — **to record**
- [ ] Token deltas — **to record**
- [ ] Tests: counts + wall time — **to record**

### 8. Commit boundary

- [ ] Diff is prompt text + docs only
- [ ] No schema, control-flow, or advice-file changes
- [ ] Diff summary, staged files, tests, deviations shown before committing

---

## A5-0 — Gate-harness discovery pass (pseudo LLM + pseudo training)

**Operator-authorized 2026-08-07.** Zero API cost, zero GPU training. This is
**discovery of the Gate harness, not acceptance of PR A.**

Recorded **before** running, per the mandate:

| field | value |
|---|---|
| **Property** | Which production components a bounded single iteration actually invokes, in what order, and what it emits |
| **Expected call path** | `run_one_iteration.py` → workflow → interpretation → proposal → implementor → validator → tuner (StubSandbox) → records |
| **Why static evidence is insufficient** | Unit tests exercise each node in isolation. Neither the *ordering*, the *real* per-stage LLM call count, nor the emitted artifact set can be read reliably from source — and Gate 1/2 bounds must be grounded in measurement, not estimate. V20's lesson is that source-level reasoning about production paths is exactly what failed |
| **Max iterations** | 1 |
| **Max rounds** | 1 |
| **Max epochs** | 1 |
| **Data fraction** | trial/train/eval 0.02, formal 0.02 (smallest that still exercises the path) |
| **Outer timeout** | 900 s hard kill |
| **Pseudo flags** | `--is_pseudo_llm --is_pseudo_training` (no API, no GPU training) |
| **Expected artifacts** | `{workspace}/iter_001/...` manifest, generated plugin + test under the run's plugin dir, `validation_*.json`, experiment records, `*_hardware.json` |
| **Baseline** | HEAD `1b391cf7`, tree `66d37db9`, working tree clean apart from untracked `slide/` |

**Stop condition.** If this pass exposes a wiring defect that source
inspection should have caught, stop, audit why the readiness review missed
it, fix the audit, then continue.

### A5-0 RESULTS (executed 2026-08-07, HEAD `1b391cf7`)

Three runs. **No PR A defect found.** Total cost: $0, no GPU training.

| run | posture | wall | exit | outcome |
|---|---|---|---|---|
| 1 | (none declared) | — | **2** | **REFUSED** by launch policy |
| 2 | `observe_only` + `diagnostic` | — | **2** | **REFUSED** by launch policy |
| 3 | `blocking` + `diagnostic` | 7 s | 0 | ran; stub-name collision |
| 4 | same, stale artifact moved aside | 5 s | 0 | reached the tuner |
| 5 | same + relaxed §5 guardrails | 21 s | 0 | tuner ran 5 attempts |

**Two launch-policy refusals, both correct** — PR D's fail-closed guard
working, and worth recording as positive evidence:

1. *"a formal launch must declare `--healthgate_mode` and
   `--result_authority`. There is no default: defaulting to
   blocking/scientific would let this run claim enforcement and scientific
   standing that nobody configured."*
2. *"healthgate_mode=observe_only, but these gates still invalidate:
   `['amplitude_collapse_blocking', 'output_diversity_blocking',
   'output_std_blocking']`. An observe-only run must not be able to
   invalidate a round."* — i.e. the declared posture must match the
   **effective** config, not merely be a legal enum value.

**Measured stage ordering** (the production call path Gate 1 will drive):

```text
interpretation
  -> proposal   stage 'comparison'        1 LLM call
                stage 'causal_reasoning'  1 LLM call
                stage 'proposing'         1-3 LLM calls (structural retry)
  -> implementor  reasoning + code        2 LLM calls (+ up to 3 repairs)
  -> validator    7 deterministic checks + 1 LLM review
  -> tuner        1 planner LLM call per attempt (max 5/round)
  -> records / manifest
```

**Artifacts emitted per attempt** (Gate PASS evidence comes from these):

```text
{ws}/iter_NNN/iteration_NNN/attempt_NNN/proposal_iter_NNN.json
{ws}/iter_NNN/iteration_NNN/attempt_NNN_<model>/models/<model>.py
{ws}/iter_NNN/.../models/<model>/description.md
{ws}/iter_NNN/.../tests/test_<model>.py
{ws}/iter_NNN/.../implementor_iter_NNN.json
{ws}/plugin_source_sentinel/<model>.py
{ws}/plugins/iter_NNN/<model>.py
{ws}/iter_NNN/manifest.json , workflow_iter_NNN.json , *_hardware.json
```

**Runtime-control bounds discovered — these bind Gate 2:**

```text
min_formal_batch_size    4        (default; batch 1 is REFUSED)
max_steps_per_attempt    150_000  (default; 200_000 was REFUSED)
```

The stub plan proposes `batch_size=1`, so every attempt was refused with
*"[Guardrails §5] SKIPPED"*. **Not a PR A defect** — V18 runtime-control
doing its job. Gate 2's fixed plan must satisfy both, or the run produces
no records.

**Non-defect classified: stub-name collision.** `stub_arch_001_a` is a
**gitignored local artifact dated 2026-08-02** left by an earlier pseudo
run, and the stub proposer always emits that fixed name, so registration
collides. Reproduced and removed by moving the file aside; restored
afterwards, so the environment is as found. Real-LLM and fixed-plan paths
generate unique names and cannot hit this. **No fix made** — changing a
stub fixture would not improve any production property.

**Positive PR A evidence from this pass:** the validator reported
*"All 7 checks passed"* on the generated classifier plugin through the
real production path. A2/A3/A3b did not regress classifier validation.

**Environment confirmed for Gate 2:** RTX 5090, 32607 MiB total; TIDMAD
data present at `/home/klz/Data/TIDMAD/`; `OPENAI_API_KEY` supplied via
`.env`, which `agent/llm_bridge.py:323` loads through `load_dotenv()`.

---

## Commit A3c — VRAM probe target shape follows the declared contract

**Found by Gate 2R on real hardware (2026-08-07). Committed `e70a60dd`.**

### The defect

`_build_probe_tensors` (`agent/skills/evaluate_vram_skill/wrapper.py`)
derived the target **shape** from the target **dtype**:

```python
long  -> [B, T]
float -> [B, 256, T]
```

Right for `fcnet` (`hybrid`), which emits `[B, 256, T]` and broadcasts a
float target against its logits. Wrong for a `regressor`, which emits
`[B, T]`. A generated regressor + `smooth_l1` therefore died in the VRAM
pre-flight with

```text
RuntimeError: The size of tensor a (4) must match the size of tensor b (256)
              at non-singleton dimension 1
```

**before any capacity question was reached** — a contract defect wearing a
resource-error costume.

### The fix

Shape and dtype are independent questions:

```text
dtype  <- the loss   (PLUGIN_LOSS_TARGET_DTYPE, unchanged)
shape  <- the model's declared output contract

classifier      -> [B, T]       long        unchanged
regressor       -> [B, T]       float       WAS [B, 256, T]
hybrid          -> [B, 256, T]  float       unchanged
model_type=None -> legacy dtype-derived shape, unchanged
```

### Scope audit — is this systemic?

`grep` for a hardcoded `(batch_size, 256, seg)` target across `agent/`,
`execute_tools/` and `core/` returns **only this site**. The **training**
path was already correct: `train_engine_sandbox:626,985` casts a `[B, T]`
target to the loss's dtype, so `smooth_l1` receives `[B, T]` float against
a `[B, T]` prediction.

### Why the A4 census missed it — dated correction

`wrapper.py:90` and `:189` **were** inspected during A4's census and
classified *"internal VRAM arithmetic, not agent-facing"*. That was correct
about the **text** and wrong about the **behaviour**: the lines were read
as comments rather than asking whether the code was contract-aware.

**This is the same blind spot as `TEST_TEMPLATE` in A3b — a consumer
audited as prose instead of as a consumer.** Two instances of one mistake,
both caught by Gates rather than by the census.

> **Rule added:** when auditing a contract change, every site that
> *constructs a tensor whose shape must match the model's output* is a
> consumer, whatever file it lives in. Reading its comments is not
> auditing it.

### Validation

- [x] 4 shape cases + 2 loss-compatibility cases, `273 passed` in
      `tests/unit/agent/evaluate_vram_skill/`
- [x] **Mutation:** reverting to the dtype-derived shape fails exactly the
      two regressor cases; hybrid, classifier and legacy stay green
- [x] The loss-compatibility test actually runs
      `smooth_l1_loss(pred, target).backward()`, so it fails on the real
      shape error rather than on an assertion about shapes
- [x] ruff check + format clean

---

## Commit A5a — Gate 1: real LLM, no expensive training

### 1. Goal

Prove the **real production LLM path** can express and implement **both**
formulations end to end. A1-A4's deterministic tests prove the mechanism
is reachable in code; they do not prove a real agent, driven through the
real proposer and implementor, produces a matching
`(backbone, output_type, loss_type)` triple that survives to a validated,
registered plugin.

**Why separate from A5b:** it costs LLM calls but **no GPU training**, so
it can fail cheaply. A prompt/schema defect must be found here, not after
a training gate.

> **REAL-LLM GATE — REQUIRES EXPLICIT OPERATOR APPROVAL.**

### 1b. Two validation-only advice fixtures

Author two advice fixtures whose **only material difference is the
formulation**:

```text
gate_pr_a_classifier_advice        gate_pr_a_regressor_advice
    output_type = classifier           output_type = regressor
    loss family = focal (or ce)        loss        = smooth_l1
    output      = [B, C, T]            output      = [B, T]

identical in both: task, band, resource bounds, compact-model
requirement, implementation freedom
```

Two rules:

- **Do not modify the real V21 scientific advice to suit a test.** These
  are gate-only fixtures.
- They state the **scientific contract**, not a Python implementation.
  The agent must still design and implement the model itself; otherwise
  the gate tests our own template, not the agent.

The minimal diff between the two fixtures must be recorded in §7 — if
they differ in more than formulation, the comparison loses meaning.

### 2. Scope

Two advice fixtures plus recorded evidence. **No production code changes.**

**Dependencies:** A1-A4 implemented and green on the PR A candidate head.

### 3. Implementation plan

- [ ] Author both advice fixtures; record their diff and confirm it is
      formulation-only
- [ ] Obtain operator approval for real LLM calls
- [ ] **Case C** — run the real path with the classifier advice:
      real proposer → `ProposalOutput` → real implementor → generated
      plugin → real validator → `plugin_loader` → `get_output_type` →
      `ExperimentConfig` live gate
- [ ] **Case R** — same path with the regressor advice
- [ ] Archive every prompt, response, generated plugin and verdict
- [ ] No training is run in this gate

### 4. Validation plan

**Case C — classification, must observe:**
- [ ] `proposal.output_type == "classifier"`
- [ ] `proposal.loss_type == "focal"` (or the chosen classification loss)
- [ ] generated plugin declares `PLUGIN_OUTPUT_TYPE = "classifier"`
- [ ] the instantiated model's **actual forward** returns `[B, C, T]`
- [ ] validator **PASS**
- [ ] `get_output_type(<generated name>) == "classifier"`
- [ ] live compatibility gate **PASS**

**Case R — regression, must observe:**
- [ ] `proposal.output_type == "regressor"`
- [ ] `proposal.loss_type == "smooth_l1"`
- [ ] generated plugin declares `PLUGIN_OUTPUT_TYPE = "regressor"`
- [ ] the instantiated model's **actual forward** returns `[B, T]`
- [ ] validator **PASS**
- [ ] `get_output_type(<generated name>) == "regressor"`
- [ ] live compatibility gate **PASS**

**Two-layer acceptance — the real LLM is never the sole oracle**

```text
deterministic pseudo fixture   HARD ACCEPTANCE   must pass
real LLM advice case           PRODUCTION CONFIRMATION
```

A single real-LLM non-compliance does **not** mean PR A is broken.

### 4b. Failure policy for the real-LLM cases

- [ ] Save the full response verbatim
- [ ] Classify the failure:
      **(a) random non-compliance** — the agent could have complied and
      did not, versus
      **(b) inexpressible** — the prompt or schema cannot represent the
      requested combination
- [ ] **At most ONE pre-specified bounded rerun.** Declare the rerun
      budget *before* running. **"Rerun until green" is forbidden.**
- [ ] If both attempts systematically produce the wrong combination —
      e.g. advice says `regressor + smooth_l1` and the proposal
      consistently returns `classifier + focal` — that is a **real A4
      prompt defect** and must be fixed in A4, not reran away

### 5. Acceptance criteria

- Both cases satisfy every assertion in §4, recorded with the observed
  values (not "as expected").
- The advice diff is formulation-only, recorded verbatim.
- Any non-compliance is classified (a) or (b) with the response archived,
  and the rerun budget declared in advance was not exceeded.
- No training was run in this gate.

### 6. Failure and edge cases

| Case | Required behaviour |
|---|---|
| Agent proposes a legal but different backbone | **Acceptable** — backbone is free; only the contract/loss pair is under test |
| Agent proposes an illegal pair | Live gate must refuse it. Record as evidence about A4, not a mechanism failure |
| Implementor emits metadata not matching its own forward | **Validator must catch it.** This is A2 check 2 firing correctly — record as a success of the check, and as an implementor defect to fix |
| Case C fails but Case R passes | Regression opened while classification broke — **stop, treat as a PR A regression** |
| LLM quota / transport failure | Infrastructure, not evidence. Re-run is not a "rerun until green" violation; record it |

### 7. Verification commands and evidence

**Advice fixtures** (new, gate-only; official V21 advice untouched):

```text
advice/gate/gate_pr_a_classifier_advice.json
advice/gate/gate_pr_a_regressor_advice.json
```

- [x] **Diff is formulation-only** — 4 differing lines, all naming the
      contract, the loss, the required forward shape and the head note.
      `mindset`, `tune`, scale bounds and "this is not a scientific test"
      framing are byte-identical.

**Exact command** (both cases identical except the advice file):

```bash
SIDERIUS_ALLOW_LAUNCH=1 timeout 1800 .venv/bin/python \
  sdsc_submission_scripts/run_one_iteration.py \
  --workspace "$WS" --run_name pra_gate1{c,r} --start_iteration 1 \
  --max_rounds 1 --max_epochs 1 \
  --trial_portion 0.02 --train_portion 0.02 --eval_portion 0.02 \
  --formal_portion 0.02 --formal_train_portion 0.02 --formal_eval_portion 0.02 \
  --healthgate_mode blocking --result_authority diagnostic \
  --min_formal_batch_size 1 --max_steps_per_attempt 500000 \
  --advice advice/gate/gate_pr_a_{classifier,regressor}_advice.json \
  --llm_config llm_configs/openai_tiered_v1.json \
  --is_pseudo_training
```

`--is_pseudo_training` swaps **only** the sandbox: every LLM call is real,
no GPU training occurs, so no scientific outcome can decide acceptance.

#### Gate 1C — classification: **PASS** (2026-08-07)

Real proposer chose `small_wavenet_classifier_focal_coldstart`. Evidence
extracted from the on-disk artifacts by
`scratchpad/gate_evidence.py`:

| assertion | observed |
|---|---|
| `proposal.output_type` | `classifier` |
| proposal `loss_type` | `focal` |
| generated `PLUGIN_OUTPUT_TYPE` | `classifier` |
| **actual forward shape** | `(1, 256, 64)` — 3-dim |
| validator `passed` | `True` |
| validator `output_type_valid` | `True` |
| `get_output_type(<generated>)` | `classifier` |
| shared rule, legal pair | **accepts** `classifier + focal` |
| shared rule, illegal pair | **refuses** `classifier + smooth_l1` |

No rerun needed; the first attempt complied with the advice.

#### Gate 1R attempt 1 — **FAIL**, and it found a real defect (2026-08-07)

Real proposer chose `small_residual_conv_regressor_v1`, set
`loss_type=smooth_l1` — and still produced `output_type=classifier` with a
`(1, 256, 64)` head.

| assertion | observed | expected |
|---|---|---|
| `proposal.output_type` | **`classifier`** | `regressor` |
| proposal `loss_type` | `smooth_l1` | `smooth_l1` ✓ |
| generated `PLUGIN_OUTPUT_TYPE` | **`classifier`** | `regressor` |
| actual forward shape | **`(1, 256, 64)`** | `(1, T)` |
| validator | PASS | — (correctly consistent: declared classifier, built classifier) |
| shared rule | **refused** `classifier + smooth_l1` | — (correct) |

**Classified: systematic defect, NOT stochastic noncompliance.** The agent
did comply with everything it was actually asked for. Two causes, both in
PR A's own work:

1. **`output_type` was absent from BOTH JSON skeletons** the proposer must
   emit (`ml_model_proposal_agent.py:328`, `proposing_stage.md:40`). A4
   added the constraint *prose* but never added the *field* to the object
   the model is told to return.

2. **Worse — the parser would have dropped it anyway.** Both
   `ProposalOutput.model_validate({...})` sites (`:1388`, `:1977`) build
   from an **explicit key allow-list**. `output_type` was not in either
   list, so a fully compliant LLM response would still have been silently
   discarded and the schema default `"classifier"` applied.

**Why the A3 transport contract missed this hop — the honest audit.**
A3 declared the chain as starting at `ProposalOutput.output_type` and
treated that as the source. It is not. The real producer is the **LLM's
raw JSON**, with a lossy parse step before any typed object exists. I
audited *downstream from the schema* instead of *upstream to the
producer*, so the one genuinely lossy hop sat outside the contract I
wrote — inside the PR whose entire purpose is to close that class of hole.

> **Rule added: a transport contract must start at the REAL producer, not
> at the first typed object in the chain.**

This is also why Gate 1 exists. Every deterministic test passed; only a
real LLM driving the real prompt surface could expose it, because the
defect lived precisely in the gap between "the schema supports it" and
"the agent is asked for it, and the parser reads it".

**Fix (narrow):** add `output_type` to both parser allow-lists and both
JSON skeletons. No schema, protocol or runtime change.

**New tests** (`TestRawProposalJsonCarriesOutputContract`):
- a `ProposalOutput` built the way the agent builds it preserves a
  declared contract;
- **both** construction sites read the key — one fixed and one missed is
  the same silent-default defect;
- both JSON skeletons request the field, since the agent cannot emit what
  it is never asked for.

Fixed in `187d02ac` (**A4b**), committed as runtime/prompt work separate
from the docs commit, per the standing commit-boundary rule.

#### Gate 1R attempt 2 — **PASS** (2026-08-07, after `187d02ac`)

Real proposer chose `small_dilated_residual_regressor_v2`.

| assertion | observed |
|---|---|
| `proposal.output_type` | `regressor` |
| proposal `loss_type` | `smooth_l1` |
| generated `PLUGIN_OUTPUT_TYPE` | `regressor` |
| **actual forward shape** | `(1, 64)` — 2-dim |
| validator `passed` | `True` |
| validator `output_type_valid` | `True` |
| `get_output_type(<generated>)` | `regressor` |
| shared rule, legal pair | **accepts** `regressor + smooth_l1` |
| shared rule, illegal pair | **refuses** `regressor + focal` |

**This is the first regression model to traverse the SIDERIUS production
path.** One rerun used, and it was a post-fix repeat of the affected case
— not a rerun-until-green: attempt 1's failure was classified as a
systematic defect, fixed, and only Gate 1R was repeated. Gate 1C was not
re-run.

**Gate 1 verdict: PASS (both cases).** LLM cost: 2 completed runs +
1 failed run, ~132 s wall each, `openai_tiered_v1` (gpt-5.4 tier).

### 8. Commit boundary

- [ ] Diff contains gate advice fixtures and archived evidence only
- [ ] No production code, no changes to real V21 scientific advice
- [ ] Diff summary, fixture diff and evidence shown to the operator

---

## Commit A5b — Gate 2: real training, both formulations

### 1. Goal

Prove that **both** formulations complete a full production execution:
generated → validated → trained → inferred → scored by the frozen
scorer → persisted as an `ExperimentRecord`.

**Why separate from A5a:** this is the only step that spends GPU time. It
runs after the cheap gate has already proven the contract is expressible.

> **REAL-TRAINING GATE — REQUIRES EXPLICIT OPERATOR APPROVAL.**
> Cold-start per the operator rule (**no `--seed_paths`**).

### 1b. Fixed typed plans, everything else real

To keep a random LLM choice out of the acceptance decision, Gate 2 uses
**fixed typed proposals**; the implementor, validator, training,
inference and scoring are all real.

```text
Gate 2C                              Gate 2R
  small bounded WaveNet                small bounded WaveNet
  output_type = classifier             output_type = regressor
  loss_type   = focal                  loss_type   = smooth_l1
  1 epoch                              1 epoch
  tiny validation workload             SAME tiny workload
```

Same backbone family and comparable scale on both sides, so a difference
in outcome is attributable to formulation rather than capacity.

### 1c. What counts as success — and what does not

Success is **complete, correct production execution**, not score:

```text
generated successfully
validated correctly
trained
inferred
scored with the FROZEN metric
record persisted
```

- A `failed_mode_collapse` outcome is still a **mechanism PASS**, provided
  the execution completed correctly.
- **Never reroll a model because regression collapsed.** Rerolling on an
  unwanted scientific outcome converts a mechanism gate into a fishing
  expedition.
- Neither side "winning" is required, or meaningful here.

### 1d. Why classification must be re-run on real hardware

PR A modifies the validator, the implementor and the prompt contract.
Proving only that regression works would leave open the possibility that
the **existing** classifier path silently regressed. A1-A4 assert
byte-parity of *generated files*; Gate 2C raises that to **production
execution parity**.

```text
old capability   classifier + CE/focal      STILL WORKS
new capability   regressor  + SmoothL1      NOW WORKS
```

### 2. Scope

Evidence only. **No production file changes.** If a defect appears, the
fix is a new commit with its own plan.

**Boundary — Gate 2 does not prove formal promotion.** Reaching a **real
scored trial** is sufficient for PR A. The chain

```text
generated model -> clean isolated measurement subprocess
                -> pre-formal measurement -> admission -> formal
```

is exactly the seam V20 failed to check, and it belongs to **PR C's Gate
2**, not here.

**Dependencies:** A1-A4 green on the candidate head, and A5a passed.

### 3. Implementation plan

- [ ] Author the two fixed typed plans (2C, 2R), matched in scale
- [ ] Draft the exact launch commands and show them to the operator
      **before** running
- [ ] Obtain explicit approval
- [ ] Run Gate 2C cold-start, single band, minimal rounds
- [ ] Run Gate 2R cold-start, same band, same workload
- [ ] Archive records, manifests and hardware provenance for both

### 4. Validation plan

**Gate 2C — classification**
- [ ] Plugin generated and validated
- [ ] `get_output_type(<generated>) == "classifier"`
- [ ] Live gate accepts with `focal`
- [ ] Training and inference complete
- [ ] `ExperimentRecord` persisted with a numeric `denoising_score`,
      `is_trial: true`

**Gate 2R — regression**
- [ ] Plugin generated and validated
- [ ] `get_output_type(<generated>) == "regressor"` — not the default
- [ ] Live gate accepts with `smooth_l1`
- [ ] Training and inference complete
- [ ] `ExperimentRecord` persisted with a numeric `denoising_score`,
      `is_trial: true`

**Frozen-metric proof**
- [ ] No scorer file appears in any PR A diff
- [ ] The scoring path used is byte-identical to `master`

**Negative controls — deterministic, no GPU needed**
- [ ] `classifier + smooth_l1` → REFUSE
- [ ] `regressor + ce` → REFUSE
- [ ] `regressor + focal` → REFUSE
- [ ] declared `classifier`, actual `[B, T]` → validator REFUSE
- [ ] declared `regressor`, actual `[B, C, T]` → validator REFUSE

> These prove that *freedom* is not *anything goes*: the agent may choose
> the formulation, and the system enforces contract consistency.

### 5. Acceptance criteria

- Both gates produce a persisted `ExperimentRecord` with a numeric
  `denoising_score` and `is_trial: true`.
- Each record carries the **declared** output type, never the default.
- Both runs used the **fixed typed plans**, recorded verbatim in §7.
- All five negative controls refuse, with reasons recorded.
- No scorer file in any diff.
- No model was rerolled because of an unwanted scientific outcome.

### 6. Failure and edge cases

| Case | Required behaviour |
|---|---|
| Either side collapses / diverges | **Mechanism PASS** if execution completed. Record the outcome; do not reroll |
| HealthGate invalidates the round | Not a PR A failure — a scored round is the bar |
| Regressor fails at measurement/subprocess | **Expected** if PR C has not landed. Record as PR C evidence; do not widen PR A |
| OOM / resource refusal | Record; may be PR B evidence |
| Gate 2C fails while 2R passes | **Stop.** PR A regressed the existing capability |
| Scores differ wildly between formulations | Not a finding here. That is the first V21 experiment |

### 7. Verification commands and evidence

**Fixed typed plans** (validated against the production loader; the seam
accepts `output_type` because A3 added it to `ProposalOutput.model_fields`,
so **no new injection mechanism was needed**):

```text
scratchpad/gate2_plans/pra_gate2_classifier.json   output_type=classifier  loss=focal
scratchpad/gate2_plans/pra_gate2_regressor.json    output_type=regressor   loss=smooth_l1
```

Both use the same tiny backbone (Embedding(256,32) -> 2 dilated residual
blocks -> head), `batch_size=8`, `segmentation_size=16000`, 1 epoch, so the
output/loss contract is the principal changed variable.

**Exact command** (differs only in the plan file):

```bash
SIDERIUS_ALLOW_LAUNCH=1 timeout 3600 .venv/bin/python \
  sdsc_submission_scripts/run_one_iteration.py \
  --workspace "$WS" --run_name pra_gate2{c,r} --start_iteration 1 \
  --max_rounds 1 --max_epochs 1 \
  --data_dir /home/klz/Data/TIDMAD/ \
  --data_scope 19 --health_gate_files 19 \
  --trial_portion P --train_portion P --eval_portion P \
  --formal_portion P --formal_train_portion P --formal_eval_portion P \
  --healthgate_mode blocking --result_authority diagnostic \
  --validation_fixed_candidate_plan "$PLAN" --validation_max_portion P \
  --llm_config llm_configs/openai_tiered_v1.json \
  --trial_time_budget_minutes 20 --formal_time_budget_minutes 30
```

#### Three refusals before the first successful launch — all correct

Every one was an operator error in my command, none a defect. Recorded as
positive evidence that the guards work:

| # | My error | The refusal |
|---|---|---|
| 1 | no posture declared | *"a formal launch must declare `--healthgate_mode` and `--result_authority`. There is no default: defaulting to blocking/scientific would let this run claim enforcement and scientific standing that nobody configured."* |
| 2 | `--data_scope 19` without `--health_gate_files 19` | DS8 paired-scope rule, naming all six offending gates **and** the exact remediation |
| 3 | `data_dir` unset | worker: *"dataset directory unavailable for the measurement: None (no silent synthetic fallback — F-1a)"* |

Refusal 3 deserves emphasis: the worker could trivially have fallen back to
synthetic data and produced a plausible measurement. It refused instead.

#### A V20 defect confirmed CLOSED (evidence for PR C)

Refusal 3 surfaced as `STOP_INFRASTRUCTURE_FAILURE` — the **same signature**
as V20 attempt 3. Checked whether PR #185's fix was incomplete. It is not:

```bash
SIDERIUS_PLUGIN_DIRS=<run plugin dir> python -c "..."
  registry has it: True
  get_config_class: <class '...PraGate2ClassifierConfig'>
```

A generated plugin resolves correctly in a clean subprocess. Recorded so
PR C does not re-chase a fixed bug; the surface signature is shared by
several distinct causes.

#### Gate 2C — classification: **PASS** (2026-08-07, 102 s)

| requirement | observed |
|---|---|
| generated plugin | PASS (fixed plan; proposer bypassed, `candidate_source=fixed_validation_plan`, sha256 `1aac07d853ae…`) |
| validator | **All 7 checks passed** |
| real training | completed |
| real inference | completed |
| frozen scorer | executed |
| `ExperimentRecord` persisted | `pra_gate2_classifier_iter_001_001.json` |
| **numeric `denoising_score`** | **`-2.727240835313264`** |
| `status` | `success` |
| `file_vector` | present, length 20 |
| HealthGate | passed — `n_unique_int8=130`, `output_std_mv=17.64`, `dominant_mode_fraction=0.175` |

Score quality is **not** an acceptance criterion; the run's own reflection
attributes it to `training_psd_segments=4`.

#### Gate 2R — regression, attempt 1: execution established, score withheld

After `e70a60dd` the pre-flight passed and the regressor **trained**:

```text
train_time_s 3.0 | inference_time_s 2.4 | scoring_time_s 3.7
file_vector present (len 20)   status failed_mode_collapse
denoising_score None   final_loss 124.95 (smooth_l1)
```

The whole chain executed — train, infer, **frozen scorer**, record
persisted. `denoising_score` is null **by gate policy**: blocking
`output_diversity_blocking` fired (`n_unique_int8=19` vs threshold 25) and
discarded the score.

**Not a defect, and verified as such.** `train_engine_sandbox:626,985`
casts a `[B, T]` target to the loss dtype, so `smooth_l1` received
`[B, T]` float against a `[B, T]` prediction — the training path is
contract-correct. `final_loss=124.95` on targets spanning 0-255 is a
near-constant prediction, i.e. genuine undertraining on 4 PSD segments.

Under the Gate 2 outcome rule this already passes: *"HealthGate-invalid
scientific output after a correctly completed scored run"* does not fail
the Gate, and *"do not reroll a candidate because the score is poor"*.

#### Gate 2R attempt 2 — same plan, adequate data

Because the acceptance list also asks for a **numeric** score, one further
run of the **identical fixed plan** at `portion=0.30`,
`train_portion=1.0`. **This is a workload correction, not a candidate
reroll** — the candidate, contract, loss, backbone and epochs are
unchanged; only the data volume differs. The forbidden move would be
swapping the model to chase a better number.

Declared in advance: **one** attempt. If it collapses again, the §7 outcome
rule is accepted and the result reported as-is rather than escalating data
until green.

**Attempt 2 result: REFUSED at admission, no evidence produced.** All 15
attempts returned `skipped_time_risk` — runtime control judged
`portion=0.30, train_portion=1.0` (a 50x step multiplier over attempt 1)
unaffordable inside the 30-minute formal budget. Wall 317 s, zero training.

Not a defect: this is V18 runtime control doing its job, and the third
independent guard to refuse me in this Gate.

**An admission refusal is not a result.** Attempt 2 never trained, so it
produced no evidence about whether more data avoids collapse — the
question it was run to answer. It is therefore *replaced*, not
supplemented: attempt 3 is the one properly-sized run of the same fixed
plan, `portion=0.10` with a 60-minute formal budget, sized from attempt
1's measured 78 train steps at `portion=0.02`.

Declared before running: **this is the last Gate 2R execution attempt,
whatever the outcome.** If it collapses, the §7 outcome rule is accepted
and reported as-is.

**Attempt 3 (supplementary): completed, 317 s.** Same fixed plan,
`portion=0.10`, 60-minute budget.

```text
denoising_score  -2.478960664489376
HealthGate       PASSED (n_unique_int8=225, output_std_mv=10.08,
                 dominant_mode_fraction=0.018)
```

**This is NOT what made Gate 2R pass.** Attempt 1 already did, under the
corrected criterion below. Attempt 3 is recorded as additional evidence
that a regressor can also reach a *gate-valid* numeric score; it is
explicitly not the basis of the verdict, and no further attempt was made.

---

### OPERATOR CORRECTION, 2026-08-07 — A5b acceptance was self-contradictory

The Gate 2 criteria as originally written demanded two incompatible things:

```text
§7 outcome rule:  HealthGate-invalid output does NOT fail the Gate
acceptance list:  a numeric denoising_score MUST be present
```

Under a **blocking** HealthGate those cannot both hold: invalidation
withholds the scalar *by design*. Chasing a non-null score would mean
adding data, changing the model, or repeating training until the gate
happened to pass — precisely the behaviour the mandate forbids.

**Corrected Gate 2 hard requirement:**

```text
scorer actually executed
+ per-file scoring evidence (file_vector) persisted
+ record reached a legitimate terminal scientific status
```

Both outcomes are a **PASS for the PR A mechanism**:

| HealthGate | expected record |
|---|---|
| valid | numeric `denoising_score` present |
| invalid | scalar withheld by blocking policy; scorer evidence + `file_vector` present; typed terminal status |

`denoising_score = null` on attempt 1 was never a scorer failure — the
scorer ran (`scoring_time_s=3.7`, `file_vector` len 20) and the blocking
gate then withheld the scalar. **That is production policy working, and it
is evidence for the mechanism rather than against it.**

#### Gate 2R — regression: **PASS** (attempt 1, 2026-08-07)

| corrected requirement | observed |
|---|---|
| generated plugin | PASS (fixed plan, proposer bypassed) |
| validator | PASS |
| real pre-flight | passed after `e70a60dd` |
| real training | completed — `train_time_s=3.0`, `final_loss=124.95` (smooth_l1) |
| real inference | completed — `inference_time_s=2.4` |
| **frozen scorer executed** | **yes — `scoring_time_s=3.7`** |
| **`file_vector` persisted** | **yes, length 20** |
| legitimate terminal status | `failed_mode_collapse` (typed, blocking gate fired: `n_unique_int8=19` < 25) |
| `ExperimentRecord` persisted | `pra_gate2_regressor_iter_001_001.json` |
| scalar | withheld by policy — **PASS under the corrected criterion** |
- [ ] Wall time, GPU time, cost — **to record**
- [ ] Any step not run and why — **to record; never claim a pass**

### 8. Commit boundary

- [ ] No production code in the diff — documentation and archived
      evidence only
- [ ] Formal promotion is **not** attempted or claimed

---

## 1a. Gate results summary (2026-08-07)

```text
Gate 1C   PASS   real LLM, classifier advice
                 small_wavenet_classifier_focal_coldstart
                 output_type=classifier, forward (1,256,64),
                 validator PASS, registry classifier,
                 rule accepts focal / refuses smooth_l1

Gate 1R   PASS   real LLM, regressor advice (after D1 fix)
                 small_dilated_residual_regressor_v2
                 output_type=regressor, forward (1,64),
                 validator PASS, registry regressor,
                 rule accepts smooth_l1 / refuses focal

Gate 2C   PASS   real classifier execution
                 denoising_score = -2.727240835313264
                 HealthGate valid (n_unique_int8=130)

Gate 2R   PASS   real regression execution (after D2 fix)
                 scorer executed (scoring_time_s=3.7)
                 file_vector persisted (len 20)
                 HealthGate correctly invalidated a collapse
                 final scalar withheld by policy
                 [supplementary attempt 3: score -2.478960664489376,
                  HealthGate valid — NOT the basis of the verdict]
```

### The two defects the Gates found — both real, both PR A's own

**D1 — the proposal path could not carry the output contract.**
Fixed `187d02ac`. Root cause, in full: `output_type` was absent from
**both** JSON skeletons the proposer must emit
(`ml_model_proposal_agent.py:328`, `proposing_stage.md:40`), *and* both
`ProposalOutput.model_validate({...})` sites (`:1388`, `:1977`) build from
an **explicit key allow-list** that omitted it — so even a fully compliant
LLM response would have been silently discarded and the schema default
`"classifier"` applied. Gate 1R exposed it: the agent set
`loss_type=smooth_l1` and named its model `..._regressor_v1`, and the
proposal still arrived as `classifier`. The deeper audit finding is that
A3's transport contract **started at `ProposalOutput` and treated it as
the source**; the real producer is the LLM's raw JSON, with a lossy parse
step before any typed object exists.

**D2 — the VRAM probe retained a classifier-only target shape.**
Fixed `e70a60dd`. `_build_probe_tensors` derived target **shape** from
**dtype**, so every float target became `[B, 256, T]` — correct for
`fcnet` (hybrid), wrong for a regressor emitting `[B, T]`. The regressor
died in pre-flight with a tensor mismatch **before any capacity question**,
i.e. a contract defect wearing a resource-error costume, which would
easily be misread as "the model is too large".

Both are the same species: **after adding an output contract, a downstream
consumer still treated the classifier contract as universal.** A3b's
`TEST_TEMPLATE` / `_smoke_test_plugin` was the third instance, found by
doc-sync rather than by a Gate.

> **The conclusion that matters:** the deterministic checkpoints proved the
> contract's trunk, and the real Gates still found two production consumers
> the census had missed. Unit and integration evidence was necessary and
> not sufficient — which is the argument for Gate 1 and Gate 2 existing.

### Guard refusals encountered — five, all correct, none a defect

Every one was an operator error in a Gate command, and each is recorded as
positive evidence that the production guards work: undeclared launch
posture; `observe_only` contradicting a blocking config; `--data_scope`
without the paired `--health_gate_files`; `data_dir` unset (refused with
*"no silent synthetic fallback — F-1a"* rather than measuring against
synthetic data); and a `skipped_time_risk` admission refusal at an
oversized workload.

---

## 1b. Final consumer audit on the `output_type` axis (2026-08-07)

**Operator-scoped: not a general code review.** One question only — for
every production surface that consumes a tensor *shape* or *target dtype*,
is classifier-specific shape confined to a classifier branch, regressor
shape to a regressor branch, and shared code branching on the **declared**
contract?

| surface | contract-aware? | evidence |
|---|---|---|
| proposal | **yes** | `output_type` typed field; both parser allow-lists read it (A3, A4b) |
| implementor template | **yes** | `_render_output_contract` drives the declaration and comment (A3) |
| producer smoke check | **yes** | reads `PLUGIN_OUTPUT_TYPE` off the module (A3b) |
| generated test artifact | **yes** | imports `PLUGIN_OUTPUT_TYPE` and branches (A3b) |
| external validator | **yes** | expected shape derived from the declaration (A2) |
| VRAM / pre-flight probe | **yes** | target shape from contract, dtype from loss (A3c) |
| training target construction | **yes** | `train_engine_sandbox:626,985` casts a `[B, T]` target to the loss dtype — `smooth_l1` gets `[B, T]` float |
| inference output decoding | **yes, pre-existing** | `inference_single.py:243-256` resolves `get_output_type` and branches `is_regression` vs `argmax` |
| scorer input | **n/a** | reads the decoded waveform from HDF5 channels; never sees a class-shaped prediction |

Two sites deliberately left as-is, verified non-contract:

- `train_engine_sandbox:126,196` — `np.bincount(target + 128, minlength=256)`
  builds `class_count`, consumed **only** by `FocalLoss1DCW`
  (`loss_models_sandbox.py:176`). Class-frequency bookkeeping, not target
  shaping; harmless for a regressor, which never requests class weights.
- `evaluate_vram_skill/{wrapper:210,387, batch_resolver:89}` and
  `ml_model_implementor:120,323` — all construct the **input** `[B, T]`
  int64, which is fixed for both contracts.

**Result: no further in-scope defect.** The only contract-dependent target
construction in `agent/`, `execute_tools/` and `core/` is the one A3c
fixed.

---

## 2. Merge checklist — the five layers PR A must prove

PR A is complete only when all five hold. Each layer proves a different
property; none substitutes for another.

- [ ] **1. SCHEMA** — a proposal can explicitly express
      `classifier | regressor`, with `output_type` independent of
      `loss_type`
- [ ] **2. PROPOSER** — both real advice cases traverse the real
      LLM-facing proposal path, and a legal combination is expressible
      (A5a)
- [ ] **3. IMPLEMENTOR + VALIDATOR** — `classifier → [B,C,T]`,
      `regressor → [B,T]`; declared metadata matches the actual forward;
      mismatches in **both** directions are refused
- [ ] **4. RUNTIME** — plugin registry, `get_output_type` and the
      `ExperimentConfig` live gate all see the correct contract
- [ ] **5. REAL EXECUTION** — classification Gate 2C and regression
      Gate 2R each reach a scored trial; scorer untouched and
      byte-identical

Only with all five may this claim be made:

> **PR A proves SIDERIUS lets the agent choose freely between
> classification and regression hypotheses, and that a proposal's intent
> reaches real execution unaltered.**

## 3. PR-level review template

Per Part III §E.7, filled at PR completion:

```
Problem statement:            the existing output contract is unreachable
                              from the producer chain
Confirmed evidence:           Part I §P1 Correction, 2026-08-07
Scope:                        A1-A5 above
Out of scope:                 live gate rebuild; get_output_type unknown
                              semantics (PR C); class-count redesign
Production callers:
Persistent schema impact:
Backward compatibility:
Implementation checkpoints:
Deterministic tests:
Layer-2 evaluation:           n/a
Bounded real validation:      A5, operator-gated
Failure classification:
Attribution:
Genericization impact:        §1.4.5 seven questions
Hardcoding introduced:
Hardcoding removed/deferred:
Artifacts:
Stop conditions:
Merge criteria:
Dependencies:
Operator decisions:           2026-08-07 — delete check_compatibility;
                              defer unknown-output-type to PR C
Metric-frozen proof:          no scorer file in any diff
Name-keyed dependency added:  must be "none"
Transport contract:           A3 REQUIRED — proposal schema -> protocol ->
                              implementor -> generated literal -> validator
                              -> registry -> get_output_type -> live gate.
                              Every hop tested; hop deletion must fail.
                              A1/A2/A4 cross no typed boundary.
Subprocess evidence:          no process boundary in A1-A4; clean-subprocess
                              proof for generated models is PR C's
Acceptance evidence:          full CI + per-commit tests + A5 on the
                              candidate head BEFORE merge
```

## 4. Operator decisions, 2026-08-07

Both open questions resolved before implementation:

| Question | Decision |
|---|---|
| **A2 class count** | **Conditional.** Wire `task_config.yaml num_classes` **only if** the validator's existing production caller already holds a typed task config, or it threads through **one** existing typed boundary. Otherwise keep `256` and file a follow-up. Never add a config singleton or broad constructor changes for it |
| **A3 contract source** | **Explicit typed schema field**, `Literal["classifier","regressor"]`. **Inference from the loss family is forbidden** — it would re-couple the two dimensions this PR exists to separate |
| **Dead `check_compatibility`** | **Delete** (A1). Zero production callers, conflicts with the live authority, misleading docstring |
| **`get_output_type` unknown default** | **Deferred to PR C** — blast radius covers every model absent from both registries |
| **A5 acceptance** | **Deterministic.** Fixed typed regressor proposal; the LLM is never the oracle. Real proposer calls are descriptive evidence only |
| **A5 sequencing** | A1-A4 green on the candidate head → A5 → acceptance → **then** merge. Never merge A1-A4 first |

## 5. Standing constraints carried into implementation

- Inspect the relevant code before finalizing each commit; do not guess
  paths, interfaces or behaviour.
- If inspection reveals ambiguity or larger scope than assumed, **stop and
  ask** rather than widening the plan.
- Planner exposure and production-default changes are outside these
  commits and need separate evidence and operator approval.
- Do not design the future empirical comparison campaign here — only the
  validation needed to land the capability safely.
- Update this document immediately after each implementation or test
  checkpoint; record any test that could not be run and why. **Never claim
  a pass that was not observed.**
