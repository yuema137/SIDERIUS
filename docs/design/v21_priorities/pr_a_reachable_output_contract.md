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
| **A1** | Delete the dead, contradictory `check_compatibility` — **DONE** (`452b1022`) | `models_format_sandbox.py`, one test | Yes |
| **A2** | Validator reads the declared contract before applying shape expectations | `ml_code_validator_agent.py`, tests | Yes |
| **A2b** | Shared pair-compatibility rule reaches the **plugin** production branch | `models_format_sandbox.py`, `sandbox_executor.py`, tests | Yes |
| **A3** | Explicit output contract, proposal → live gate | `proposal.py`, protocol, `ml_model_implementor.py`, tests | Yes |
| **A4** | Symmetric contract in the proposer-facing prompt surface | prompt templates, docs | Yes |
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

- [ ] Read `PLUGIN_TEMPLATE` and its `.format(...)` call site fully;
      record the current parameter set before editing
- [ ] Inspect `agent/schemas/proposal.py` and the proposal → implementor
      protocol; record the exact insertion points **before** editing
- [ ] Add the typed field with a `Literal["classifier", "regressor"]`
      annotation; **legacy read only:** absent → `"classifier"`
- [ ] Thread it through the protocol to the implementor input
- [ ] Parameterize `PLUGIN_OUTPUT_TYPE` in the template
- [ ] **Generate the matching HEAD, not only the metadata.** The emitted
      network's forward must actually return `[B, T]` for `regressor` and
      `[B, C, T]` for `classifier`. A plugin declaring `regressor` whose
      forward still returns `[B, 256, T]` is the defect A2 check 2 exists
      to catch — this commit must not produce it in the first place
- [ ] Make the forward-contract comment (`:259`) match the emitted contract
- [ ] Add a hop-deletion test per the transport contract above
- [ ] Confirm the new production path always sets the field explicitly —
      a *new* candidate must never rely on the legacy default

### 4. Validation plan

**Unit**
- [ ] Classifier generation is byte-identical to pre-change for a fixed
      proposal fixture (**string equality on the generated file**)
- [ ] Regressor generation emits `PLUGIN_OUTPUT_TYPE = "regressor"` and a
      matching forward-contract comment
- [ ] Unspecified contract → classifier (legacy read)

**Transport (required — Binding principle 2)**
- [ ] `output_type` survives proposal → protocol → implementor input
- [ ] Dropping the field at the protocol hop **fails** a test rather than
      silently yielding a classifier plugin
- [ ] The generated literal matches the declared field for both contracts
- [ ] The registered `PLUGIN_OUTPUT_TYPE_REGISTRY` entry matches the
      declared field after `plugin_loader` registration
- [ ] `get_output_type(<generated>)` returns the declared contract — not
      the `"classifier"` default

**Integration / pseudo**
- [ ] Implementor → validator in pseudo mode: a generated regressor
      passes A2's validator through the production path
- [ ] Implementor → validator: a generated classifier passes, unchanged

**Negative / invalid input**
- [ ] Unknown/invalid contract value → rejected by the `Literal`
      annotation at schema construction, never reaching generation
- [ ] `output_type=regressor` + `loss_type=ce` → rejected by the **live
      gate**, unchanged, proving A3 did not duplicate that rule

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
| New production proposal omits the field | Treat as a defect: assert in test that the production path always sets it |
| Proposal declares regression but a classification loss | **Leave it to the live gate.** Do not duplicate the rule in the implementor — one authority only |
| Protocol drops the field | Test must fail (transport contract) |
| Template placeholder collision | Generation-time error, never a malformed plugin |
| Historical proposal fixture | Byte-identical regeneration |

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

- [ ] Enumerate every place the forward contract is stated as a literal;
      record the full list before editing
- [ ] Restate the contract symmetrically: classification **and**
      regression, neither presented as the unexamined default
- [ ] Keep the change textual — no schema or control-flow edits
- [ ] Update the affected node/skill `.md` files as the last step

### 4. Validation plan

**Unit**
- [ ] Prompt-render tests assert both contracts appear, **with their legal
      loss families** — `classifier: ce/focal/focal_cw`,
      `regressor: smooth_l1`
- [ ] A guardrail test asserts the contract is not restated as a
      hardcoded classifier-only literal in production code

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

- [ ] Advice fixture diff — **to record**
- [ ] Case C: prompts, `ProposalOutput`, generated plugin, verdicts — **to record**
- [ ] Case R: same — **to record**
- [ ] Rerun budget declared, and whether used — **to record**
- [ ] LLM call count and cost — **to record**
- [ ] Any step not run and why — **to record; never claim a pass**

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

- [ ] Launch commands — **to record, operator-approved before running**
- [ ] Gate 2C record ID, score, output type — **to record**
- [ ] Gate 2R record ID, score, output type — **to record**
- [ ] Negative-control results — **to record**
- [ ] Wall time, GPU time, cost — **to record**
- [ ] Any step not run and why — **to record; never claim a pass**

### 8. Commit boundary

- [ ] No production code in the diff — documentation and archived
      evidence only
- [ ] Formal promotion is **not** attempted or claimed

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
