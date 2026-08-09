# PR D — Make the existing scientific-authority contract reachable

**Status: DESIGN APPROVED 2026-08-08 (operator), subject to the recorded
decisions O-D-1 and O-D-2 below. Q-D-1 is RESOLVED and the launcher census
is FROZEN. No implementation has begun; no production code, test, schema,
launcher or scorer file is touched by this document.**

| | |
|---|---|
| Plan section | `docs/design/v21_priorities.md` §E.3e + the re-scoped PR D section |
| Gate | **V21 scientific-campaign launch blocker** (global checkpoint 4) |
| Depends on | PR A (`b9f88ae5`), PR C (`cac86c94`), PR B (`0aae3f4b`) — all merged |
| Audit date | 2026-08-08, against `master` `57087ed9` |

> **Precedence.** The ledger is append-only. §E.3e and the re-scoped PR D
> section are authoritative. The original *"Per-file evidence to reflector
> and planner"* section is `SUPERSEDED BY AUDIT`; its premise was
> **withdrawn** and must not leak back into this scope.

---

## A0. Verification toolchain

```bash
PYRIGHT_PYTHON_GLOBAL_NODE=off uv run pyright     # pyright 1.1.409
.venv/bin/python -m pytest tests/unit -q -m "not real_run" > /tmp/pytest.log 2>&1; echo $?
.venv/bin/python -m ruff check . && .venv/bin/python -m ruff format --check .
```

**Baseline at `57087ed9`:** unit suite `8087 passed, 2 skipped, 1 xfailed`;
pyright `0 errors, 4 warnings`; ruff clean.

Per CLAUDE.md, the full suite runs **only from a clean tree** (the PR3-L2
preflight refuses uncommitted production edits) and the verdict is taken
from pytest's own exit code, never from a pipe's.

---

## 0. Pre-design audit (performed 2026-08-08 against `57087ed9`)

### 0.A Canonical semantics — one owner, verified

`core/scientific_authority.py` is the **sole** authority-semantics owner.
No competing rule exists: the only production importers are
`core/resume.py:48`, `execute_tools/scientific_aggregation.py:42` and the
tuner's producer import at `ml_hyperparameter_tune_agent.py:73`. A
repository-wide search for `authoritative` / `primary_basis` outside that
module returns only `core/runtime_control/*`, which is **GPU-measurement
authority** — a different concept, deliberately not conflated here.

The verdict is derived, never assembled by callers:
`authoritative = not blocking_reasons` (`:145-152`), with blockers at
`:124-141`.

**The complete matrix, generated from the module — 27 combinations, of
which exactly ONE is authoritative. PR D must preserve every
downstream-visible field of this result, for all 27 rows** (D1 pins them;
see the scope note there for exactly which fields that means).

| healthgate_mode | declared_result_authority | formal_validity | authoritative | primary_basis |
|---|---|---|---|---|
| `None` | any (incl. `None`) | any | `False` | `legacy_authority_unknown` |
| any (incl. `None`) | `None` | any | `False` | `legacy_authority_unknown` |
| `blocking` | `scientific` | `valid` | **`True`** | **`blocking_scientific_formal_valid`** |
| `blocking` | `scientific` | `invalid` | `False` | `gate_invalidated` |
| `blocking` | `scientific` | `unknown` | `False` | `formal_validity_unknown` |
| `blocking` | `diagnostic` | any | `False` | `declared_diagnostic` |
| `observe_only` | `scientific` | any | `False` | `non_blocking_mode` |
| `observe_only` | `diagnostic` | any | `False` | `declared_diagnostic` |

Two properties worth stating because a careless fix would break them:
`legacy_authority_unknown` fires when **either** axis is `None`
(`:130-131`), and it has **highest precedence** in `_BLOCKER_PRECEDENCE`
(`:64-70`), so an undeclared run is reported as out-of-scope rather than
as "invalid".

### 0.B Real producer → persisted record: the full transport contract

Traced for **both** fields. The chain does **not** start at
`HyperparamTuningInput`.

| # | Hop | Boundary / type | Present? | Status | Evidence |
|---|---|---|---|---|---|
| 1 | campaign shell | literal flags | yes | produced | `launch_v20_campaign.sh:156-157` |
| 2 | chain arg parse | shell vars | yes | preserved | `_chain_common.sh:290-291` |
| 3 | app args | CLI flags | yes | preserved | `_chain_common.sh:431-432` |
| 4 | launcher parse | `args.healthgate_mode` / `.result_authority`, `str|None`, `default=None`, `choices` constrained | yes | preserved | `run_one_iteration.py:1012-1029` |
| 5 | launch policy | consumed by `validate_formal_launch` | yes | consumed (refuses omission, refuses `observe_only+scientific`) | `run_one_iteration.py:1557`; `execute_tools/health_checks/launch_policy.py:83,116,127` |
| 6 | manifest | `manifest["healthgate_mode"]` / `["result_authority"]` | yes | **preserved** — caller's declaration wins, `tune_output` only a fallback | `run_one_iteration.py:620-629` |
| 7 | **`run_workflow(...)`** | — | **NO** | **❌ DROPPED — the defect** | call site `run_one_iteration.py:1846`; `workflows/model_exploration.py` contains **zero** occurrences of either name |
| 8 | **valid→tune protocol** | `local_validated_model(...)` | **NO** | **❌ absent** — 63 parameters, neither field | `agent/schemas/protocols/ml_model_valid_to_ml_model_tune.py:33`, constructs the input at `:252` |
| 9 | tuner input | `HyperparamTuningInput.healthgate_mode` / `.result_authority`, `HealthGateMode|None` / `ResultAuthority|None`, `default=None` | **field EXISTS** | defaulted to `None` | `agent/schemas/hyperparam_tuning.py:1749`, `:1761` |
| 10 | stamp | `ScientificAuthority.from_context(...)`, formal only | yes | receives `None/None` | `ml_hyperparameter_tune_agent.py:5744-5752` |
| 11 | record | `ExperimentRecord.scientific_authority: dict|None` | yes | `legacy_authority_unknown` | `hyperparam_tuning.py:432` |
| 12 | tuner output echo | `HyperparamTuningOutput.healthgate_mode` / `.result_authority` | **field EXISTS, already echoed from the input on BOTH branches** | `None` today | `:2381`, `:2389`; echoes at tuner `:6086-6087` (healthy) and `:6191-6192` (failure) |
| 13 | consumers | see §0.F | — | act on `legacy_authority_unknown` | — |

**No new schema field is required at any hop.** Hops 9 and 12 already
declare the fields; hops 7 and 8 need parameters, which is wiring.

**Consequence of hop 12 (this is what makes the change small):** because
the output already echoes the input, populating the **input** alone fixes
(a) the record stamp, (b) the output echo, and (c) `resume`'s legacy
reconstruction source. There is no separate output wiring to do.

### 0.C Launcher census, re-verified against `57087ed9`

Every row re-checked. `Can create a formal record?` means the path can
reach the `if not trial_config.is_trial` stamp at tuner `:5744`.

| path | formal record? | declaration available at entry? | authority required by intended semantics? | classification |
|---|---|---|---|---|
| `run_one_iteration.py:1846` → `run_workflow` | **yes** | **yes** — `args.healthgate_mode`, validated at `:1557` | **yes** — this is the production scientific chain | **WIRE** |
| `scripts/run_comparison.py:690` → tuner CLI subprocess | **yes** | **no** — no authority CLI arg exists on this launcher | **no** — diagnostic comparison harness; formal execution does not imply authority | **DELIBERATELY UNDECLARED** (**O-D-1**) |
| `sdsc_submission_scripts/run_exploration_test.py:151` → `run_workflow` | yes | no | **no** — self-described *"Standalone Tier 3 integration test runner"* | **DELIBERATELY UNDECLARED** |
| `workflows/model_exploration.py:2994` `__main__` → `run_workflow` | yes | no | **no** — developer entry point | **DELIBERATELY UNDECLARED** |
| `scripts/bg_admission_validation.py:571` → `HyperparamTuningInput(...)` | yes | no | **no** — self-described validation harness that deliberately *"enters below `run_chain.sh`"* | **DELIBERATELY UNDECLARED** |
| hand-invoked `ml_hyperparameter_tune_agent.py` CLI | yes | **yes** | yes | **ALREADY CORRECT** — `:6669-6688` → `input_dict` `:6722-6723` |

The `DELIBERATELY UNDECLARED` paths are **correct as they stand**: each
is a test/dev/diagnostic surface, and under §0.E an undeclared run
*should* yield `legacy_authority_unknown`. Wiring them would be
mechanical census-following, which the ledger's Requirement 2 forbids.

#### 0.C.1 CENSUS FROZEN — operator, 2026-08-08

```text
WIRE
  run_one_iteration -> run_workflow -> protocol -> HyperparamTuningInput

ALREADY WIRED
  manual tuner CLI, when explicit flags are supplied

DELIBERATELY UNDECLARED
  run_comparison                (see O-D-1)
  run_exploration_test
  model_exploration __main__
  bg_admission_validation
```

This census is closed. A path may only move category by a written
operator decision, not by a later implementer's judgement.

### 0.D The narrowest shared transport

There is **no** existing generic run-posture or execution-context object
to reuse; `run_workflow` takes flat keyword parameters.

The closest analogue is exact and in the **same subsystem** —
`health_gate_enabled`, also a launch-time declaration:

```text
run_one_iteration.py:1859   health_gate_enabled=args.health_gate_enabled
model_exploration.py:1351   health_gate_enabled: bool = True        (parameter)
ml_model_valid_to_ml_model_tune.py:42   health_gate_enabled: bool = True
                                  :260  health_gate_enabled=health_gate_enabled
```

**Conclusion: one shared boundary, not five launcher-specific changes.**
All `run_workflow` callers converge on the same protocol at
`ml_model_valid_to_ml_model_tune.py:252`, so the transport is added once
on that path and every `run_workflow` caller may then declare or not
declare, per §0.C.

Following the established pattern is also the correct genericization
answer: introducing a `RunContext`/`RunPosture` object for two fields
would be a repository-wide redesign that §7 explicitly rules out.

### 0.E Absence semantics — audited, and structurally safe today

**No production defaulting site exists.** A repository search for
`"blocking"` / `"scientific"` literals assigned to these fields returns
matches **only in tests**. The three states are distinguishable at every
hop:

```text
declared blocking/scientific  -> both axes set        -> authoritative iff valid
declared other posture        -> both axes set        -> its own blocker
undeclared                    -> either axis None     -> legacy_authority_unknown
```

Three existing guards keep it that way, and PR D must not weaken any:

- both CLI parsers use `default=None` with an explicit "no default,
  because defaulting would silently claim authority" rationale
  (`run_one_iteration.py:1016-1020`, tuner `:6669-6688`);
- `validate_formal_launch` **refuses** a formal launch that omits either
  axis (`launch_policy.py:116`) and refuses `observe_only+scientific` as
  a contradiction (`:127`);
- the schema fields are optional *only* so historical replays still load
  (`hyperparam_tuning.py:1753-1758`).

**Binding for this PR:** the fix is transport, never a default. Adding
`default="blocking"` anywhere would manufacture authority and is
out of scope by definition.

### 0.F Downstream consumers — re-verified, no new ones

| consumer | class | behaviour at `legacy_authority_unknown` | evidence |
|---|---|---|---|
| chain incumbent admission | **decision-bearing** | returns `False`; the record *"cannot become the chain incumbent"* | `core/resume.py:677-694` |
| scientific aggregation | **decision-bearing** | `included=0`; `per_model_formal` filtered to **empty** | `result_interpretation_agent.py:1052-1056`; summary populated from the record at `:2120` |
| `final_record["scientific_authority"]` | persistence-only | stores the verdict | tuner `:5745` |
| `InterpretationOutput.scientific_aggregation` | persistence/observability | dumps the scope | `result_interpretation_agent.py:1602`, `:1694` |
| `prov["authority_basis"]` | observability-only | records *how* authority was established | `core/resume.py:727` |
| `ProposalOutput` | **guarded absence** | a test asserts authority must **not** appear here | `test_fixed_candidate_plan_seam.py:181` |

No production consumer has been added since the earlier audit.

**Backward-compatibility finding (§6).** `resolve_record_authority`
already has an explicit reconstruction ladder (`:290-302`): a record with
no stored verdict is reconstructed from the **output-level** declaration.
`core/resume.py:299` loads that output with
`HyperparamTuningOutput.model_validate_json(text)` **from the resumed
iteration's own persisted artifact** — not from the current run. So old
artifacts keep `healthgate_mode: null` and remain
`unreconstructable_legacy`. **PR D cannot retroactively confer authority
on historical records**, and a test must pin that.

---

## 1. Objective

> **Make the existing scientific-authority contract reachable from
> launcher declaration to formal record, so existing authority-bearing
> downstream decisions operate on the declared posture rather than
> `legacy_authority_unknown`.**

Explicitly:

- **Authority semantics already exist** and are correct
  (`core/scientific_authority.py`, matrix in §0.A).
- **PR D does not redesign them.** No blocker, precedence, basis or
  verdict changes.
- **This is a transport/reachability PR**, the same shape as PR A
  ("make the existing output contract reachable") and B3 Stage B.

## 2. Non-goals

```text
NO  scorer / metric / aggregation / normalization changes
NO  HealthGate semantic changes
NO  authority verdict-table changes (all 27 rows frozen)
NO  per-file evidence work (premise withdrawn, §E.3e.1-3)
NO  trial-authority redesign — trials carry no block, by design
NO  manufactured default authority
NO  generic RunContext / execution-context refactor
NO  unrelated launcher cleanup
NO  retroactive reinterpretation of historical records
```

## 3. Complete transport contract (post-design)

```text
launch_v20_campaign.sh:156-157        --healthgate_mode / --result_authority
  -> _chain_common.sh:290-291,431-432 shell vars -> APP_ARGS
  -> run_one_iteration.py:1012-1029   args.*            str|None, choices-constrained
  -> validate_formal_launch           refuses omission / contradiction   [unchanged]
  -> write_manifest :620-629          manifest declaration               [unchanged]
  -> run_workflow(...)                ** NEW parameters **               HOP 7
  -> local_validated_model(...)       ** NEW parameters **               HOP 8
  -> HyperparamTuningInput            EXISTING fields :1749/:1761        HOP 9
  -> ScientificAuthority.from_context tuner :5746-5747                   [unchanged]
  -> final_record["scientific_authority"]                                [unchanged]
  -> HyperparamTuningOutput echo      tuner :6086-6087 / :6191-6192      [unchanged]
       -> core/resume.py:678          incumbent admission                [unchanged]
       -> result_interpretation_agent:1052  aggregation partition        [unchanged]
```

Per hop:

| hop | producer | consumer | type | ownership | failure semantics if absent |
|---|---|---|---|---|---|
| 7 | `run_one_iteration` | `run_workflow` | `HealthGateMode|None`, `ResultAuthority|None` | workflow | `None` propagates → `legacy_authority_unknown`. **Correct** for undeclared callers (§0.C) |
| 8 | `run_workflow` | `local_validated_model` | same | protocol | same |
| 9 | protocol | `HyperparamTuningInput` | existing fields | schema | same |

**Binding Principle 2:** deleting any of hops 7, 8, 9 must make a test
fail — covered by Layer C.

Note the failure semantics are deliberately *not* "raise". An absent
declaration is a legitimate state for the three undeclared paths; the
launch-time refusal for scientific runs already lives in
`validate_formal_launch`, and duplicating it inside the transport would
be a second source of truth.

## 4. Commit plan

The audit found **one causal problem** and **one shared boundary**, so the
natural decomposition is small. A docs-only audit commit precedes
production work, matching PR B's Stage A pattern.

| # | Commit | Blocked on | Independently reviewable |
|---|---|---|---|
| **D0** | Audit + design synchronization (this document) | — | Yes (docs only) |
| **D1** | Pin the existing authority matrix **before** touching transport | — | Yes |
| **D2** | Wire the declaration through the shared boundary | D1 | Yes |
| **D3** | Downstream-decision evidence + published launcher census | D2 | Yes |

> **Note on two clauses of the commit template.** The standard's
> ordering-specific requirements — *"validate the actual visited
> sample/file sequence"* and *"for the default `shuffle` path, prove that
> selection, random-seed behavior, visited sequence and step count remain
> unchanged"* — **do not apply to PR D**. PR D touches no sampling,
> ordering, seeding or step-count surface; the transported values are two
> `Literal` strings consumed only by `ScientificAuthority.from_context`.
> Recorded as deliberately not-applicable rather than silently skipped.
> The analogous parity obligation for PR D is the 27-row verdict matrix
> (D1) and the undeclared-path behaviour (D2).

---

### Commit D1 — Pin the existing authority semantics before transport changes

#### 1. Goal

Turn the 27-row verdict matrix into a regression fixture **before** any
wiring exists, so "semantics unchanged" becomes a measured claim rather
than an assertion made after the fact.

**Why this commit and not another.** B1 learned this concretely: a parity
claim written *after* a change cannot distinguish "unchanged" from
"changed, and the test was written to match the new behaviour". Pinning
first inverts that. It also must not live in D2, because a test added in
the same commit as the change it guards proves nothing about the
before-state.

#### 2. Scope

**Changes**
- `tests/unit/core/` — one new test module pinning the exhaustive matrix,
  **complete downstream-visible result per row** (option A, §5 correction
  3): all 8 `model_dump()` fields, with `blocking_reasons` ordered.

**Must remain unchanged**
- `core/scientific_authority.py` — not one character.
- Every production file. This commit has **no production diff**.

**Non-goals**
- Any transport wiring (D2).
- Any new blocker, basis, precedence or field.

**Dependencies:** none.

#### 3. Implementation plan

- [ ] Read `core/scientific_authority.py:96-180` and confirm the blocker
      set and precedence order are still `:124-141` / `:64-70` at
      implementation time
- [ ] Enumerate the full cross-product
      `{None, blocking, observe_only} × {None, scientific, diagnostic} ×
      {valid, invalid, unknown}` = 27 cases
- [ ] **Option A (chosen).** For each of the 27 cases assert the COMPLETE
      downstream-visible result against **hardcoded** expectations — never
      values read back from the module under test (CLAUDE.md rule). The
      `model_dump()` surface is 8 fields:

      ```text
      echoed inputs   healthgate_mode, declared_result_authority, formal_validity
      derived         blocking_reasons (ORDERED list), authoritative,
                      primary_basis, enters_incumbent_selection,
                      enters_scientific_aggregation
      ```

- [ ] Pin `blocking_reasons` as an **ordered** list per row, not a set —
      the order is `_BLOCKER_PRECEDENCE` and is itself semantic (an
      operator reads the first one). Multi-blocker rows such as
      `observe_only + diagnostic + invalid` must pin all three in order
- [ ] Assert the three echoed inputs equal the inputs supplied — a
      transform there would be a silent semantic change
- [ ] Assert exactly **one** case is `authoritative`, named explicitly as
      `blocking + scientific + valid`
- [ ] Assert `enters_incumbent_selection` and
      `enters_scientific_aggregation` per row rather than asserting they
      merely track `authoritative` — they are separate computed fields
      today and a future divergence must show up as a failing row
- [ ] Assert the dump has **exactly** these 8 keys, so a new
      downstream-visible field cannot appear unpinned
- [ ] Verify the module is not imported anywhere in the test with a
      monkeypatch that could mask a real change

#### 4. Validation plan

**Unit**
- [ ] 27 parametrized cases green
- [ ] `authoritative` count == 1

**Integration / pseudo** — none required; this is a pure-function matrix.

**Negative / invalid input**
- [ ] An unrecognised `formal_validity` string is rejected or handled as
      the module currently does — record which, do not change it
- [ ] A caller attempting to pass `authoritative=` directly is refused
      (`extra="forbid"`, `:86`)

**Backward-compatibility / default parity**
- [ ] Existing `tests/unit/core/test_scientific_authority.py` passes
      **unmodified** — if any existing assertion conflicts, stop and
      report rather than editing it

**Real-training Gate:** none. A GPU cannot evaluate a truth table.

#### 5. Acceptance criteria

- All 27 rows assert the **complete 8-field** `model_dump()` — the three
  echoed inputs plus `blocking_reasons` (ordered), `authoritative`,
  `primary_basis`, `enters_incumbent_selection`,
  `enters_scientific_aggregation` — against literals written in the test.
  **No expected value is derived from the implementation**, including by
  calling the module and reusing its output.
- The key set is asserted exactly, so an added downstream-visible field
  fails the test rather than passing unpinned.
- Exactly one row is `authoritative`, and it is `blocking/scientific/valid`.
- `core/scientific_authority.py` does not appear in the diff.
- The pre-existing authority test module passes unmodified.

With this, the document's claim and its acceptance signal are the same
statement: *every downstream-visible field of the verdict is frozen for
all 27 rows*. The earlier wording ("byte-for-byte") promised more than
the planned assertions delivered and was corrected on operator review.

#### 6. Failure and edge cases

| Case | Required behaviour |
|---|---|
| An existing test already pins part of the matrix | Keep both; do **not** delete the older one to avoid duplication — it may cover a case the new matrix does not |
| A row's current behaviour surprises us | **Record it as-is and stop.** D1 documents the frozen truth; it never "fixes" a row |
| `formal_validity` accepts a value outside the three | Record the actual behaviour; do not add validation in this PR |

#### 7. Verification commands and evidence

```bash
.venv/bin/python -m pytest tests/unit/core/test_scientific_authority.py <new-module> -q
.venv/bin/python -m ruff check . && .venv/bin/python -m ruff format --check .
```

- [ ] Matrix test count + wall time — **to record**
- [ ] Existing authority module result (unmodified) — **to record**
- [ ] Mutation: invert one blocker condition → matrix fails — **to record**

#### 8. Commit boundary

- [ ] Diff contains test files only; **zero** production files
- [ ] No transport wiring
- [ ] Diff summary, staged file list, test counts and any deviations shown
      before committing

---

### Commit D2 — Wire the declaration through the shared boundary

#### 1. Goal

Close transport hops 7-9 so a launcher's declared posture reaches
`ScientificAuthority.from_context` unchanged, and an undeclared caller
continues to reach it as `None`.

**Why this commit and not another.** It is the single causal defect. It
is separated from D1 because D1 must exist first to prove semantics did
not move, and from D3 because D3 asserts *consumer* behaviour, which
fails for a different reason than transport.

#### 2. Scope

**Changes**

```text
workflows/model_exploration.py
    run_workflow(...)                two parameters, default None, placed in the
                                     existing "DataScope + HealthGate subsystem
                                     (DS6b)" block beside health_gate_enabled (:1351)
    local_validated_model(...) call  forward both (:2560 region, beside :2568)
agent/schemas/protocols/ml_model_valid_to_ml_model_tune.py
    local_validated_model(...)       two parameters, default None (:42 region)
    HyperparamTuningInput(...)       set both (:252 region, beside :260)
sdsc_submission_scripts/run_one_iteration.py
    run_workflow(...) call site      pass args.healthgate_mode / .result_authority (:1846)
tests/                               reachability + mutations
```

**Must remain unchanged**
- `core/scientific_authority.py`, the tuner stamp (`:5744-5752`), the
  output echo (`:6086-6087`, `:6191-6192`), the manifest (`:620-629`),
  `validate_formal_launch`.
- The three `DELIBERATELY UNDECLARED` launchers — **no edit at all**;
  `None` defaults preserve their behaviour.
- `scripts/run_comparison.py` — **deliberately authority-undeclared per
  O-D-1; MUST remain unchanged.** Its formal records continue to resolve
  `legacy_authority_unknown`, which is the intended outcome, not a defect.
- Every score, HealthGate behaviour, trial records.

**Non-goals**
- Any default other than `None` at hops 7-8.
- Any validation inside the transport — refusal already lives in
  `validate_formal_launch`, and a second copy would be a second source of
  truth.

**Dependencies:** D1 (the matrix must be pinned first).

#### 3. Implementation plan

- [ ] Re-read `workflows/model_exploration.py:1346-1356` and confirm the
      DS6b parameter block is still the right insertion point
- [ ] Add both parameters to `run_workflow`, typed to match the schema
      (`HealthGateMode | None`, `ResultAuthority | None`), `default=None`
- [ ] Forward both at the `local_validated_model(...)` call
      (`model_exploration.py:2560` region)
- [ ] Add both parameters to `local_validated_model`
      (`ml_model_valid_to_ml_model_tune.py:38-46` region), `default=None`
- [ ] Set both on the returned `HyperparamTuningInput`
      (`:252` region) — the fields already exist at
      `hyperparam_tuning.py:1749/:1761`; **no schema change**
- [ ] Pass both at the launcher call site
      (`run_one_iteration.py:1846`) from `args.*`
- [ ] Confirm no import cycle is introduced by the type imports; if the
      `Literal` aliases are awkward to import, record the choice made
- [ ] Verify the three undeclared launchers still call `run_workflow`
      without the new kwargs and are untouched

#### 4. Validation plan

**Unit**
- [ ] A declared posture passed to `local_validated_model` appears
      unchanged on the returned `HyperparamTuningInput`
- [ ] An omitted posture yields `None` on both fields
- [ ] The values are the exact strings supplied — no normalisation,
      lower-casing or mapping

**Integration / pseudo**
- [ ] Drive the **real** transport functions end to end (not a local
      reimplementation — B1b's P2 mutation survived exactly that mistake):
      declared → `from_context` receives the declaration; undeclared →
      `from_context` receives `None/None` → `legacy_authority_unknown`

**Negative / invalid input**
- [ ] An invalid string is rejected by the existing `Literal` schema
      validation, not silently coerced — record where the rejection occurs
- [ ] `observe_only + scientific` is still refused **at the launcher** by
      `validate_formal_launch`, and the transport does **not** duplicate
      that check
- [ ] Only one axis declared → still `legacy_authority_unknown`

**Backward-compatibility / default parity**
- [ ] The three undeclared launchers produce byte-identical
      `HyperparamTuningInput` field values before and after
- [ ] The two pre-existing parity guards pass **unmodified**:
      `tests/unit/core/test_watchdog_admission_split.py:317` (launcher →
      `run_workflow` kwargs) and
      `tests/unit/sdsc_submission_scripts/test_launch_surface_parity.py`
      (shell → CLI → `run_workflow` → protocol → schema)
- [ ] D1's 27-row matrix re-run and identical

**Real-training Gate:** none proposed. See §5 Layer E for the argument
that a GPU/LLM run adds no evidence here. **Not to be launched without
operator approval.**

#### 5. Acceptance criteria

- Given `healthgate_mode="blocking"`, `result_authority="scientific"` at
  `run_one_iteration.py:1846`, the object reaching
  `ScientificAuthority.from_context` carries exactly those two strings.
- Given no declaration, both arrive as `None` and the verdict's
  `primary_basis` is `legacy_authority_unknown`.
- `HyperparamTuningInput.model_fields` gains **no new field**.
- `core/scientific_authority.py` is not in the diff.
- D1's matrix is value-identical.
- Both pre-existing parity guards pass without modification.

#### 6. Failure and edge cases

| Case | Required behaviour |
|---|---|
| Launcher passes a kwarg `run_workflow` does not accept | Already caught by `test_watchdog_admission_split.py:317` — the Gate 0 attempt-1 failure mode. Must stay green |
| Protocol accepts the kwarg but never sets it on the schema | Caught by `test_no_silently_dropped_constructor_kwarg` in the parity harness. Must stay green |
| Only one of the two fields is wired | Still `legacy_authority_unknown` (either-axis rule, §0.A). A test must assert this rather than assuming symmetry |
| An undeclared launcher is accidentally given a default | **Stop.** This is mutation M-D5 and the wrong fix; the undeclared test must fail |
| Invalid literal reaches the schema | Pydantic refuses at `HyperparamTuningInput` construction. Fail loudly; do not coerce |
| A historical record is resumed under a declared run | Must stay `unreconstructable_legacy` (§0.F). Asserted in D3 |
| Import cycle from the type aliases | Fall back to `str | None` at the transport hops **only if** the schema still enforces the `Literal`; record the decision |

#### 7. Verification commands and evidence

```bash
.venv/bin/python -m pytest tests/unit/core/test_watchdog_admission_split.py     tests/unit/sdsc_submission_scripts/test_launch_surface_parity.py -q
.venv/bin/python -m pytest tests/unit/agent tests/unit/core tests/unit/workflows -q
.venv/bin/python -m ruff check . && .venv/bin/python -m ruff format --check .
PYRIGHT_PYTHON_GLOBAL_NODE=off uv run pyright
```

- [ ] Reachability test result — **to record**
- [ ] Parity guards (both, unmodified) — **to record**
- [ ] Mutations M-D1..M-D4, M-D5a, M-D5b by category — **to record**
- [ ] Test counts + wall time — **to record**
- [ ] pyright error/warning counts vs the `0 errors, 4 warnings` baseline —
      **to record**

#### 8. Commit boundary

- [ ] Diff touches exactly three production files plus tests
- [ ] No semantics file, no tuner file, no schema field addition
- [ ] No edit to the three deliberately-undeclared launchers
- [ ] No `run_comparison.py` change — deliberately undeclared per **O-D-1**
- [ ] Diff summary, staged file list, tests, mutations and deviations
      shown before committing

---

### Commit D3 — Downstream-decision evidence and the published census

#### 1. Goal

Prove the two decision-bearing consumers actually change behaviour once
the declaration arrives, and publish the launcher classification the
ledger's Requirement 2 demands.

**Why this commit and not another.** D2 proves the value *arrives*; that
is a different property from the consumers *acting* on it, and the two
fail for different reasons. Separating them means a red test names which
one broke.

#### 2. Scope

**Changes**
- `tests/` — downstream-decision tests.
- This design document — the census with reasons.

**Must remain unchanged**
- `core/resume.py` and
  `nodes/result_interpretation_agent/result_interpretation_agent.py` —
  both are already correct. **A diff in either is a finding, not a task.**

**Dependencies:** D2.

#### 3. Implementation plan

- [ ] Build a formal record carrying a `blocking/scientific/valid`
      verdict through the real `ScientificAuthority.from_context`
- [ ] Drive `core/resume.py`'s authority predicate on it and assert
      admission; drive the undeclared case and assert refusal with the
      recorded exclusion reason
- [ ] Drive `partition_for_aggregation` on both and assert
      included/excluded counts
- [ ] Assert a historical record with **no** stored verdict, resumed with
      a *declared* current-iteration output, still resolves
      `unreconstructable_legacy` (§0.F) — pinning that PR D confers no
      retroactive authority
- [ ] Publish the §0.C census in this document with each path's
      classification **and the reason for every deliberate exclusion**
- [ ] Consider extending
      `test_launch_surface_parity.py::test_tuning_input_covers_gate_launch_critical_fields`
      to name the two fields — currently it does not

#### 4. Validation plan

**Unit**
- [ ] Incumbent predicate: authoritative → admitted; undeclared → refused
- [ ] Aggregation: authoritative → `included=1`; undeclared →
      `excluded=1`, `all_excluded=True`

**Integration / pseudo**
- [ ] Optional and explicitly not required for merge: a pseudo-mode chain
      iteration asserting the persisted record's
      `scientific_authority.primary_basis`. No GPU, no real LLM. Listed as
      the cheapest available live confirmation if the operator wants one

**Negative / invalid input**
- [ ] A record whose stored verdict contradicts its own facts still
      resolves `verdict_inconsistent_with_its_facts` — unchanged
- [ ] A malformed verdict still resolves `malformed_verdict` — unchanged

**Backward-compatibility / default parity**
- [ ] Historical no-verdict record → `unreconstructable_legacy`
- [ ] Trial records still carry **no** authority block

**Real-training Gate:** none. **Not to be launched without operator
approval.**

#### 5. Acceptance criteria

- With a `blocking+scientific+valid` record, `core/resume.py`'s predicate
  returns `True` and `partition_for_aggregation(...).included_count == 1`.
- With an undeclared record, the predicate returns `False` and
  `all_excluded is True`.
- A historical no-verdict record resumed under a declared run resolves
  `unreconstructable_legacy`.
- The census appears in this document with a reason for every exclusion.
- Neither consumer file appears in the diff.

#### 6. Failure and edge cases

| Case | Required behaviour |
|---|---|
| A consumer needs editing to make the test pass | **Stop and report.** Both are already correct; an edit means the audit was wrong |
| The historical-record test goes green only because the fixture lacks a declaration | Construct the fixture with a *declared* current-iteration output, or the test is vacuous |
| Trial record acquires an authority block | Regression — the stamp guard at tuner `:5744` was disturbed |
| Extending the launch-critical field list breaks an unrelated test | Report it; do not weaken the other test |

#### 7. Verification commands and evidence

```bash
.venv/bin/python -m pytest tests/unit/core/test_resume_incumbent.py     tests/unit/execute_tools/test_scientific_aggregation.py     tests/integration/workflows/test_pr_d_positive_path_deterministic.py -q
.venv/bin/python -m pytest tests/unit -q -m "not real_run" > /tmp/pytest.log 2>&1; echo $?
```

- [ ] Downstream-decision results — **to record**
- [ ] Historical-record non-reinterpretation result — **to record**
- [ ] Census published — **to record**
- [ ] Clean-tree full suite: pytest rc, counts, zero FAILED/ERROR — **to record**

#### 8. Commit boundary

- [ ] Tests + this document only
- [ ] No production file in the diff
- [ ] No unrelated cleanup, no follow-up work pulled forward
- [ ] Diff summary, staged file list, tests and deviations shown before
      committing

---

## 5. Validation ladder

### Layer A — semantics parity (D1)

The 27-row matrix, pinned before and re-run after. Identical.

### Layer B — transport reachability (D2)

Driven through the **real** production transport functions — not a local
reimplementation. (B1b's P2 mutation survived precisely because a test
re-implemented the production expression; that lesson applies here.)

```text
declared blocking+scientific
  -> reaches HyperparamTuningInput unchanged
  -> reaches ScientificAuthority.from_context unchanged
undeclared
  -> remains undeclared -> legacy_authority_unknown
```

### Layer C — hop deletion / mutation (D2)

Real production-path edits, not string cosmetics:

```text
M-D1  drop healthgate_mode at the launcher call site (run_one_iteration:1846)
M-D2  drop result_authority at the launcher call site
M-D3  drop the forwarding inside run_workflow
M-D4  drop the assignment in local_validated_model
M-D5a default ONE axis (healthgate_mode="blocking") instead of None
M-D5b default BOTH axes to "blocking" + "scientific" instead of None/None
```

**M-D5b is the one that matters, and the earlier single-mutation form of
this design described it wrongly.** Corrected 2026-08-08 after the
operator caught it, and verified against the frozen matrix:

```text
blocking + None        -> legacy_authority_unknown, authoritative=False
None     + scientific  -> legacy_authority_unknown, authoritative=False
blocking + scientific  -> authoritative=True          <- the dangerous fix
```

Because `legacy_authority_unknown` fires when **either** axis is `None`
(§0.A), defaulting only `healthgate_mode` **cannot** manufacture
authority. It is still a real defect — it destroys "an undeclared axis
stays `None`" — but it is a *different* failure from the one the old
wording claimed. The two are therefore separated:

| mutation | what it breaks | caught by |
|---|---|---|
| **M-D5a** | an undeclared axis no longer stays `None` | the assertion that **both** fields are `None` for an undeclared caller |
| **M-D5b** | **authority is fabricated** — an undeclared run with a valid formal round becomes `authoritative=True` | the assertion that an undeclared caller's verdict is `legacy_authority_unknown` |

M-D5b is the acceptance-critical one: it is the only mutation in this PR
that would make a record claim scientific authority nobody declared.

Reported by category, per the standing rule:

```text
N attempted
N-k behaviour-changing -> all caught
  k equivalent/unreachable -> classified, no missing acceptance signal
```

never as a percentage.

### Layer D — downstream decisions (D3)

As in D3's acceptance. Both consumers exercised through their real
production functions.

### Layer E — production-boundary evidence

**Assessment: no GPU or LLM Gate is required, and one would add no
evidence.**

Every property PR D asserts is reachable deterministically:

| property | cheapest sufficient layer |
|---|---|
| semantics unchanged | pure unit (Layer A) |
| declaration survives each hop | real transport functions, no I/O (Layer B) |
| each hop is load-bearing | mutation (Layer C) |
| consumers change behaviour | real consumer functions on constructed records (Layer D) |

The transported values are two `Literal` strings. Nothing about their
propagation depends on CUDA, on a model, on training, or on an LLM
response — a GPU run would exercise the same functions with more
expensive inputs and a noisier oracle.

**One residual is stated rather than papered over:** no deterministic
test executes `run_one_iteration.py`'s `__main__` end to end, so the
argument-passing at `:1846` is covered by a call-site test plus a
mutation, as B1b covered its clamp inside `run()`. If the operator wants
live confirmation, the cheapest sufficient form is a **pseudo-mode chain
iteration** asserting the persisted record's
`scientific_authority.primary_basis`, which needs no GPU and no real LLM.
Recorded as an option, not proposed as a requirement.

The scientific outcome is never the oracle.

## 6. Backward compatibility / parity

| invariant | how it is preserved |
|---|---|
| every declared posture's verdict | matrix pinned before the change (D1) |
| undeclared → `legacy_authority_unknown` | `None` defaults at hops 7-8; M-D5 guards the wrong fix |
| trial records unchanged | the stamp is guarded by `if not trial_config.is_trial` (tuner `:5744`); PR D does not touch it |
| scoring | no scorer file in the diff — verified by diff, as PR B did |
| HealthGate behaviour | untouched; `healthgate_mode` is a *declaration*, and enforcement already reads config, not this field |
| unrelated launcher behaviour | only one call site in one launcher changes |
| **historical records** | `resume.py:299` loads each iteration's **own** output; old artifacts keep `null` → `unreconstructable_legacy`. Pinned by a D3 test |

**No design question remains open here** — §0.F resolved the historical
question from source, and the existing §12A ladder is the "already-existing
explicit reconstruction rule" the operator's constraint allows.

## 7. Genericization review

Applied only to touched surfaces.

- **Does the touched code treat one launcher or campaign as the
  framework?** No. Hops 7-9 are already task-generic; the two fields are
  typed `HealthGateMode` / `ResultAuthority`, not TIDMAD-specific.
- **Literals.** `"blocking"` / `"scientific"` must **not** be written into
  any launcher by this PR. They stay where they belong: the campaign
  shell script that actually declares the posture
  (`launch_v20_campaign.sh:156-157`), constrained by `choices` at the
  parser and by `Literal` types at the schema.
- **Bounded genericization performed:** none required — the change follows
  the existing `health_gate_enabled` parameter pattern in the same
  subsystem.
- **Deliberately deferred:** a generic run-posture/`RunContext` object
  that would carry declaration, data scope, health-gate switches and
  authority together. Justified only if a third or fourth declaration
  needs the same route; two fields do not warrant it, and §2 rules it out
  for this PR.

## 8. Acceptance and merge criteria

1. Every authority-bearing launcher path is **classified** and either
   wired or deliberately left undeclared **with the reason published**.
2. A declared posture survives every transport hop **unchanged**.
3. `blocking + scientific + valid` reaches the existing authority rule and
   produces an authoritative formal record.
4. That record is accepted by the existing incumbent rule **and** the
   existing scientific-aggregation rule.
5. A genuinely undeclared posture still produces
   `legacy_authority_unknown`.
6. Existing authority semantics are value-identical before and after — all
   27 rows.
7. Trial records are unchanged.
8. No scorer / metric / HealthGate-semantic file is in the diff.
9. Every behaviour-changing transport mutation is caught; equivalents are
   classified.
10. Full configured CI passes, **in addition to** PR-D-specific
    reachability evidence.

### V21 review fields

```text
Metric-frozen proof:      no scorer/metric/SNR file in `git diff base..HEAD`;
                          PR D touches no scoring path (to be re-verified at merge)

Name-keyed dependency
added:                    none. No model name, campaign name or launcher name
                          gains correctness or reachability meaning

Transport contract:       field:    healthgate_mode, result_authority
                          producer: launch_v20_campaign.sh:156-157
                          boundaries: run_workflow -> local_validated_model
                                      -> HyperparamTuningInput (existing fields)
                          persistence: ExperimentRecord.scientific_authority;
                                      HyperparamTuningOutput echo
                          consumers: core/resume.py:678 (incumbent),
                                     result_interpretation_agent.py:1052 (aggregation)
                          branches: declared / undeclared / trial / historical record

Subprocess evidence:      not applicable — the transport is in-process up to the
                          tuner. The tuner's own CLI path (a real subprocess) is
                          already correct and is not modified

Acceptance evidence:      Layers A-D deterministic; Layer E argued unnecessary
                          with the residual stated
```

---

## Operator decisions — RECORDED 2026-08-08

### O-D-1 — `run_comparison.py` remains authority-undeclared

Recorded verbatim:

> **`run_comparison.py` remains authority-undeclared. It is a diagnostic
> comparison harness, not a scientific-campaign authority source. A formal
> execution does not imply scientific authority. If a future workflow
> intends its records to participate in incumbent selection or scientific
> aggregation, that workflow must introduce an explicit authority
> declaration rather than inheriting one by default.**

**The reasoning is about the semantics of authority, not about the
script's name.** `scientific_authority` does not answer *"did this run
execute formally?"* — it answers *"has the current scientific campaign
explicitly declared this result eligible for incumbent selection and
scientific aggregation?"* Wiring a launcher merely because it is a
production entry point that can run formal rounds would introduce
exactly the inference the contract exists to forbid:

```text
FORBIDDEN   formal execution   -> therefore scientific authority
CONTRACT    explicit declaration -> and only that -> authority
```

This is also why the alternative fixes were rejected: giving
`run_comparison` a default `scientific` posture would manufacture
authority (mutation **M-D5**), and adding two CLI flags purely for
surface symmetry would imply a campaign posture the harness does not have.

**Supporting code fact** (observed, not load-bearing for the decision):
`run_comparison.py:1415` writes `campaign_manifest.json`, not the
`iter_NNN/manifest.json` layout that `restore_prior_state` scans
(`core/resume.py:1051-1066`), so its records already sit outside chain
resume discovery. The decision and the artifact layout agree. This is a
layout observation, not a guarantee — the decision stands on the
semantics above.

**Consequence to hold in review:** formal records produced by
`run_comparison` may carry valid measurements and scores, and will
continue to resolve `legacy_authority_unknown`. That is the intended
outcome, not a defect, and D2 must not "fix" it.

### O-D-2 — No GPU/LLM Gate for PR D

The operator accepted §5 Layer E. PR D changes only:

```text
Literal declaration -> in-process typed transport -> existing deterministic
authority function -> persisted record -> deterministic downstream predicates
```

with no subprocess reconstruction, GPU-dependent state, LLM-dependent
producer, model implementation, or training/inference semantics involved.
A real run would exercise the same functions with more expensive inputs
and a noisier oracle.

**Contrast recorded, because the two cases are easy to conflate:** PR C
*required* a real spawn because its property was clean-subprocess registry
reconstruction — a genuine process boundary. **PR D has no process
boundary among the hops it changes.** The chain does cross one earlier
(shell → `run_one_iteration.py`), but that hop already works — the
manifest receives the correct declaration today — and PR D does not touch
it.

**The residual, stated rather than closed:** no deterministic fixture
executes `run_one_iteration.__main__` end to end, so hop 7's call site is
covered by a call-site test plus mutations M-D1/M-D2, as B1b covered its
clamp inside `run()`. A pseudo-mode chain iteration traversing the real
launcher wiring is **optional strengthening evidence, explicitly not a
merge requirement**. It must not be escalated into a real scientific
campaign to close a wiring gap.

---

## Remaining operator decisions

**None — implementation may begin.** Q-D-1 is resolved by O-D-1 and the
census is frozen at §0.C.1; the Gate question is resolved by O-D-2.

Two boundaries that remain the operator's, not the implementer's, if they
arise during implementation:

- moving any launcher between census categories (§0.C.1 is closed);
- any change to the 27-row verdict matrix (frozen by §0.A and pinned by
  D1) — which would no longer be PR D.
