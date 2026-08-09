# PR D — Make the existing scientific-authority contract reachable

**Status: IMPLEMENTED AND VALIDATED 2026-08-08 — approved by the operator,
CI green, READY FOR OPERATOR MERGE. Not merged.** Design was
approved 2026-08-08 subject to the recorded decisions O-D-1 and O-D-2
below; Q-D-1 is RESOLVED and the launcher census is FROZEN. D0-D3 are
complete on `feat/pr-d-scientific-authority-reachable`; the production
diff is **three files, ten wiring lines** (+36/-1 with imports and
comments), exactly the three hops the audit predicted. Final evidence is
in **§PR-D final validation**. GitHub CI (`Lint + Type + Unit Tests`) is
**SUCCESS on `dbf8a29a`** — run `31295064064`, `headSha` verified rather
than inferred from the branch. PR **#189**.

> An earlier run, `31294679925` on `e832df26`, shows `cancelled`. That is
> GitHub's concurrency group superseding it when the next commit was
> pushed — **not a failure**, and not evidence about the code.

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

**Reconciled against the final tree, 2026-08-08.** Line numbers above are
the audit-time ones; D2 added 12 lines to `model_exploration.py`, so its
`__main__` call moved `:2994 -> :3006`. The classification is what matters
and it holds exactly:

```text
scripts/run_comparison.py                   0 authority mentions   undeclared
sdsc_submission_scripts/run_exploration_test.py
                                            0 authority mentions   undeclared
scripts/bg_admission_validation.py          0 authority mentions   undeclared
workflows/model_exploration.py              4 mentions  = the two run_workflow
                                            parameters and the two forwarded
                                            to the protocol. Its own __main__
                                            call at :3006 passes NEITHER, so
                                            the dev entry point stays
                                            undeclared as frozen
```

Three of the four files do not appear in the PR diff at all.

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

**Binding for this PR: the fix is transport, never a default.** Two
distinct harms, kept distinct because conflating them produced a wrong
mutation description on the first pass (corrected 2026-08-08 on operator
review):

```text
default ONE axis      e.g. healthgate_mode="blocking", result_authority=None
  -> still legacy_authority_unknown, authoritative=False
  -> does NOT manufacture authority
  -> but CORRUPTS ABSENCE SEMANTICS: an undeclared axis no longer reads
     as undeclared, and the record's stored facts now misdescribe the run

default BOTH axes     "blocking" + "scientific"
  -> a valid formal round becomes authoritative=True
  -> MANUFACTURES AUTHORITY nobody declared     <- the dangerous case
```

The asymmetry follows from the frozen matrix (§0.A):
`legacy_authority_unknown` fires when **either** axis is `None`, so a
single-axis default cannot reach `authoritative=True` on its own.

Both are out of scope by definition. Any default is forbidden — the
one-axis case because absence must stay information (§8 of the working
rules), the two-axis case because it fabricates a scientific claim. The
mutations that police them are **M-D5a** and **M-D5b** respectively.

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

- [x] Read `core/scientific_authority.py:96-180`; blockers confirmed at
      `:130-141`, precedence at `:64-70`, unchanged
- [x] Enumerated the full cross-product
      `{None, blocking, observe_only} × {None, scientific, diagnostic} ×
      {valid, invalid, unknown}` = 27 cases
- [x] **Option A (chosen).** For each of the 27 cases assert the COMPLETE
      downstream-visible result against **hardcoded** expectations — never
      values read back from the module under test (CLAUDE.md rule). The
      `model_dump()` surface is 8 fields:

      ```text
      echoed inputs   healthgate_mode, declared_result_authority, formal_validity
      derived         blocking_reasons (ORDERED list), authoritative,
                      primary_basis, enters_incumbent_selection,
                      enters_scientific_aggregation
      ```

- [x] Pin `blocking_reasons` as an **ordered** list per row, not a set —
      the order is `_BLOCKER_PRECEDENCE` and is itself semantic (an
      operator reads the first one). Multi-blocker rows such as
      `observe_only + diagnostic + invalid` must pin all three in order
- [x] Assert the three echoed inputs equal the inputs supplied — a
      transform there would be a silent semantic change
- [x] Assert exactly **one** case is `authoritative`, named explicitly as
      `blocking + scientific + valid`
- [x] Assert `enters_incumbent_selection` and
      `enters_scientific_aggregation` per row rather than asserting they
      merely track `authoritative` — they are separate computed fields
      today and a future divergence must show up as a failing row
- [x] Assert the dump has **exactly** these 8 keys, so a new
      downstream-visible field cannot appear unpinned
- [x] Verified: no monkeypatch of `core.scientific_authority` anywhere in
      the new module

#### 4. Validation plan

**Unit**
- [x] 27 parametrized cases green (32 tests total incl. the property tests)
- [x] `authoritative` count == 1

**Integration / pseudo** — none required; this is a pure-function matrix.

**Negative / invalid input**
- [x] **Recorded, not changed.** `FormalValidity` is a `Literal` *type alias*,
      not an enum, and `from_context` does not validate it — an unrecognised
      string simply matches no blocker branch and yields the same result as
      `valid`. Left exactly as-is: PR D changes no semantics, and this is a
      pre-existing property of a frozen function. Filed as **FU-D21-1**
- [x] A caller attempting to pass `authoritative=` directly is refused
      (`extra="forbid"`, `:86`) — `test_a_caller_cannot_supply_a_conclusion`

**Backward-compatibility / default parity**
- [x] Existing `tests/unit/core/test_scientific_authority.py` passes
      **unmodified**: `49 passed`. No conflict

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

- [x] `32 passed in 0.13s` (`tests/unit/core/test_authority_matrix_frozen.py`)
- [x] `49 passed in 0.10s`, file unmodified
- [x] **4 attempted, 4 behaviour-changing, 4 caught, 0 equivalent:**
      `N1` either-axis→both-axis; `N2` drop `non_blocking_mode`;
      `N3` precedence reordered; `N4` `declared_diagnostic` stops blocking

#### 8. Commit boundary

- [x] Diff contains one test file; **zero** production files
- [x] No transport wiring
- [x] Diff summary, staged file list, test counts and deviations recorded below

#### D1.R — Result, 2026-08-08

**Implemented as** `tests/unit/core/test_authority_matrix_frozen.py`
(one new file, **zero production diff**).

```text
32 passed in 0.13s        the new matrix module
49 passed in 0.10s        pre-existing test_scientific_authority.py, UNMODIFIED
mutations                 4 attempted, 4 behaviour-changing -> 4 caught,
                          0 equivalent
```

**What was expected vs what the code did.** Expected: the hand-derived
table would need reconciling against the implementation. Observed: all 27
rows matched on the first run. That is the intended outcome of deriving
expectations from the *rule* rather than from the module — had I generated
them by calling `from_context`, the table would have agreed by
construction and proved nothing.

**Implementation choice.** Option A: the complete 8-field `model_dump()`
per row, plus an exact key-set assertion so a future downstream-visible
field cannot appear unpinned. `blocking_reasons` is compared as an
**ordered list**, because `primary_basis` is literally `blocking_reasons[0]`
and a set comparison would let precedence drift while every row still
passed — mutation `N3` exists to prove that assertion is load-bearing.

**Alternatives rejected.** (a) Asserting only `authoritative` +
`primary_basis` — the narrower claim the design originally made; rejected
on operator review because `resolve_record_authority` re-derives and
compares **every key present** on a stored verdict
(`core/scientific_authority.py:320-325`), so any drifting field changes how
historical records are judged. (b) Asserting
`enters_* == authoritative` as a relationship rather than per row —
rejected as a tautology that would survive both fields being wrong
together.

**Negative finding, recorded not fixed — FU-D21-1.** `FormalValidity` is a
`Literal` *type alias*, not an enum, and `from_context` performs no
validation on it: an unrecognised `formal_validity` string matches no
blocker branch and therefore behaves exactly like `"valid"`. This is
pre-existing, is not reachable from PR D's transport (the tuner passes
`formal_validity_of(...)`, which returns one of the three), and changing
it would be a semantics change PR D is forbidden to make. Filed as a
follow-up, deliberately untouched.

**Deviation from the plan:** none.

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

- [x] Re-read `model_exploration.py:1349-1353`; DS6b block confirmed
- [x] Added both parameters to `run_workflow` (`:1360-1361`), typed to match the schema
      (`HealthGateMode | None`, `ResultAuthority | None`), `default=None`
- [x] Forwarded at the `local_validated_model(...)` call (`:2579-2580`)
      (`model_exploration.py:2560` region)
- [x] Added both parameters to `local_validated_model` (`:54-55`)
      (`ml_model_valid_to_ml_model_tune.py:38-46` region), `default=None`
- [x] Set both on the returned `HyperparamTuningInput` (`:275-276`)
      (`:252` region) — the fields already exist at
      `hyperparam_tuning.py:1749/:1761`; **no schema change**
- [x] Passed both at the launcher call site
      (`run_one_iteration.py:1846`) from `args.*`
- [x] **No cycle.** Both files already imported from
      `agent.schemas.hyperparam_tuning`, so `HealthGateMode` /
      `ResultAuthority` were added to the existing import lists. The
      design's fallback to `str | None` was not needed
- [x] Verified: `run_exploration_test.py`, `model_exploration.__main__`
      and `bg_admission_validation.py` are **not in the diff**

#### 4. Validation plan

**Unit**
- [x] A declared posture arrives unchanged
- [x] An omitted posture yields `None` on both fields
- [x] Exact strings, all three legal postures

**Integration / pseudo**
- [x] Drove the **real** transport functions (not a local
      reimplementation — B1b's P2 mutation survived exactly that mistake):
      declared → `from_context` receives the declaration; undeclared →
      `from_context` receives `None/None` → `legacy_authority_unknown`

**Negative / invalid input**
- [x] Rejected by Pydantic at `HyperparamTuningInput` construction inside
      the protocol — `"enforcing"` and `"Scientific"` both raise
- [x] Transport does **not** duplicate the check; the illegal pair is
      deliberately absent from the carried-verbatim parametrization
- [x] Only one axis declared → still `legacy_authority_unknown`

**Backward-compatibility / default parity**
- [x] Unchanged — `None` defaults; those files are not in the diff
- [x] Both pre-existing parity guards pass **unmodified** (`22 passed`):
      `tests/unit/core/test_watchdog_admission_split.py:317` (launcher →
      `run_workflow` kwargs) and
      `tests/unit/sdsc_submission_scripts/test_launch_surface_parity.py`
      (shell → CLI → `run_workflow` → protocol → schema)
- [x] D1's 27-row matrix re-run and identical (`32 passed`)

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
| An undeclared launcher is accidentally given a default | **Stop.** This is mutation M-D5a/M-D5b and the wrong fix; the undeclared test must fail |
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

- [x] `17 passed in 1.51s`
- [x] `22 passed`, neither file modified
- [x] **6 attempted, 6 behaviour-changing → 6 caught, 0 equivalent** (after two test-architecture fixes, §D2.R)
- [x] `agent+core+workflows+sdsc`: `6623 passed, 2 skipped`, pytest rc=0,
      0 FAILED/ERROR, 458s
- [x] pyright `0 errors, 4 warnings` — baseline held

#### 8. Commit boundary

- [x] Diff touches exactly three production files plus one test file
- [x] No semantics file, no tuner file, no schema field addition
- [x] No edit to the three deliberately-undeclared launchers
- [x] No `run_comparison.py` change — deliberately undeclared per **O-D-1**
- [x] Diff summary, staged files, tests, mutations and deviations recorded in §D2.R

#### D2.R — Result, 2026-08-08

**Production diff: three files, exactly as designed.**

```text
sdsc_submission_scripts/run_one_iteration.py     +2 kwargs at the run_workflow call
workflows/model_exploration.py                   +2 params (:1360-1361), +2 forwarded (:2579-2580)
agent/schemas/protocols/ml_model_valid_to_ml_model_tune.py
                                                 +2 params (:54-55), +2 set (:275-276)
tests/unit/agent/schemas/test_authority_transport_reachable.py   new, 17 cases
```

No schema field added; `HealthGateMode` / `ResultAuthority` came from the
import both files already had.

```text
17 passed   new reachability module
22 passed   the two pre-existing parity guards, UNMODIFIED
32 passed   D1's matrix, identical
6623 passed, 2 skipped   agent+core+workflows+sdsc, pytest rc=0, 0 FAILED/ERROR
pyright 0 errors, 4 warnings   baseline held
mutations   6 attempted, 6 behaviour-changing -> 6 caught, 0 equivalent
```

**Two mutations survived the first round, and both were defects in MY
TESTS, not gaps in luck.** Recorded because each is a distinct way a
reachability test can be decoration:

- **M-D3 (drop the forwarding inside `run_workflow`) SURVIVED.** The
  module asserted `run_workflow` *accepts* the keywords and separately
  drove the protocol directly — so the hop existed at both ends and could
  be severed in the middle with nothing observing it. **This is the PR
  A/B/C defect shape reproduced inside the test suite**: signature
  presence is not forwarding. Fixed with an AST assertion that the call
  forwards the *parameter* (`ast.Name` of the same id), which also
  catches forwarding a literal.
- **M-D1/M-D2 (drop the launcher's kwargs) SURVIVED.** The call-site test
  used a substring search, and `healthgate_mode=args.healthgate_mode`
  appears **seven times** in `run_one_iteration.py` — the crash-path
  `write_manifest(...)` calls use identical text. Deleting the one
  occurrence that matters left six others and the assertion stayed green.
  Fixed by locating the `run_workflow(...)` call by AST and asserting the
  value is `args.<field>`.

Both fixes changed the test architecture rather than the mutation, per
the standing rule. A third harness bug surfaced alongside — the mutation
anchors themselves matched seven sites and correctly reported
`NOT-APPLIED` rather than a false pass, which is the `count == 1`
discipline working.

**Deviation from the plan:** none in production. The design predicted
three production files and three hops; that is exactly what changed. The
only deviations were the two test corrections above, both discovered by
the mutations the design required.

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

- [x] Build a formal record carrying a `blocking/scientific/valid`
      verdict through the real `ScientificAuthority.from_context`
      — built through the real protocol → input → `from_context`
      (`_formal_record`, mirroring tuner `:5745-5752`)
- [x] Drive `core/resume.py`'s authority predicate on it and assert
      admission; drive the undeclared case and assert refusal with the
      recorded exclusion reason
      — **superseded, already covered.** `test_resume_incumbent.py`
      drives the real predicate in both directions
      (`test_an_authoritative_record_becomes_the_incumbent`,
      `test_a_non_authoritative_record_never_becomes_the_incumbent`);
      mutation **M-D6** proves that module load-bearing (12 failures).
      A duplicate here would name no defect only it can catch
- [x] Drive `partition_for_aggregation` on both and assert
      included/excluded counts — asserted in the new module
      (`included_count == 1` / `all_excluded is True`); also pre-covered
      by `test_pr_d_positive_path_deterministic.py`
- [x] Assert a historical record with **no** stored verdict, resumed with
      a *declared* current-iteration output, still resolves
      `unreconstructable_legacy` (§0.F) — pinning that PR D confers no
      retroactive authority
      — asserted, plus a provenance guard on `resume.py:299`
      (`TestPRDConfersNoRetroactiveAuthority`)
- [x] Publish the §0.C census in this document with each path's
      classification **and the reason for every deliberate exclusion**
      — published and frozen at §0.C / §0.C.1
- [x] Consider extending
      `test_launch_surface_parity.py::test_tuning_input_covers_gate_launch_critical_fields`
      to name the two fields — currently it does not
      — **done.** Both added to the launch-critical set with the reason
      recorded inline: an undeclared launch stamps
      `legacy_authority_unknown` on every formal record

#### 4. Validation plan

**Unit**
- [x] Incumbent predicate: authoritative → admitted; undeclared → refused
      — pre-covered by `test_resume_incumbent.py` (`39 passed` within the
      71-test consumer run); M-D6 proves it load-bearing
- [x] Aggregation: authoritative → `included=1`; undeclared →
      `excluded=1`, `all_excluded=True` — asserted end to end **from a
      launcher declaration**, which is the hop no existing test crossed

**Integration / pseudo**
- [ ] Optional and explicitly not required for merge: a pseudo-mode chain
      iteration asserting the persisted record's
      `scientific_authority.primary_basis`. No GPU, no real LLM. Listed as
      the cheapest available live confirmation if the operator wants one
      — **DELIBERATELY NOT RUN**, per O-D-2, which classifies it as
      optional strengthening evidence and explicitly not a merge
      requirement. Left unchecked rather than marked done, because it was
      not performed. Tracked as **FU-D21-2**

**Negative / invalid input**
- [x] A record whose stored verdict contradicts its own facts still
      resolves `verdict_inconsistent_with_its_facts` — unchanged;
      pre-covered by `test_scientific_authority.py`, which passes
      unmodified
- [x] A malformed verdict still resolves `malformed_verdict` — unchanged;
      same module, unmodified

**Backward-compatibility / default parity**
- [x] Historical no-verdict record → `unreconstructable_legacy`
      — asserted directly, and the reconstruction ladder's *source* is
      pinned separately so a future change to `resume.py:299` cannot
      silently start feeding it the current run's declaration
- [x] Trial records still carry **no** authority block — asserted on the
      guard itself; **M-D8** catches its removal

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

None occurred. The second was a live risk and was handled: the
retroactivity test supplies a **declared** current-iteration output and
asserts the record still resolves `unreconstructable_legacy`, so it is
not vacuous.

#### 7. Verification commands and evidence

```bash
.venv/bin/python -m pytest tests/unit/core/test_resume_incumbent.py \
    tests/unit/execute_tools/test_scientific_aggregation.py \
    tests/integration/workflows/test_pr_d_positive_path_deterministic.py -q
.venv/bin/python -m pytest tests/unit/core/test_authority_end_to_end_and_history.py \
    tests/unit/sdsc_submission_scripts/test_launch_surface_parity.py -q
.venv/bin/python -m pytest tests/unit -q -m "not real_run" > /tmp/pytest.log 2>&1; echo $?
```

- [x] Downstream-decision results: the three consumer suites named above
      `71 passed in 1.90s`, pytest rc=0, **neither consumer file modified**
- [x] Historical-record non-reinterpretation result:
      `unreconstructable_legacy` preserved under a declared current run;
      provenance guard on `resume.py:299` green
- [x] Census published — §0.C, frozen at §0.C.1
- [x] New module `10 passed`; extended parity harness `4 passed`
- [x] Clean-tree full suite: recorded in **§PR-D final validation**

#### 8. Commit boundary

- [x] Tests + this document only
- [x] No production file in the diff
- [x] No unrelated cleanup, no follow-up work pulled forward
- [x] Diff summary, staged file list, tests and deviations recorded in
      §D3.R below before committing

---

#### D3.R — Result, 2026-08-08

**Zero production diff.** Two test files: one new module, plus two fields
added to the pre-existing launch-critical list.

```text
10 passed   tests/unit/core/test_authority_end_to_end_and_history.py   (new)
 4 passed   test_launch_surface_parity.py (list extended)
mutations   3 attempted, 3 behaviour-changing -> 3 caught by the suite,
            0 equivalent  (M-D6 by its owning module - see the table)
```

**The plan called for downstream-consumer tests; the audit showed they
already exist, so D3 is deliberately SMALL.** Duplicating them would
violate CLAUDE.md's rule that a test must name a defect only it can
catch. Already covered and not re-written: resume's real predicate (both
directions), `unreconstructable_legacy`, `reconstructed_legacy`, trial
exclusion, and aggregation include/exclude with reasons.

Two properties were genuinely uncovered, because PR D created the seam
they cross:

1. **The joint** — every existing test starts from a hand-built verdict;
   none starts from a *launcher declaration* and follows it through the
   real transport into the consumers' admission rule.
2. **History is not rewritten** — PR D makes new iterations declare a
   posture, and must not thereby confer authority on records that
   recorded none.

**Mutations, with one classification worth reading:**

| # | mutation | result |
|---|---|---|
| M-D6 | resume's predicate ignores `authoritative` | **CAUGHT — by the module that owns it.** It survived *this* module (which drives `resolve_record_authority`, not the predicate) and produced **12 failures** in `test_resume_incumbent.py`. Recorded as caught-by-owner rather than "fixed" with a duplicate test |
| M-D7 | a verdict-less legacy record reconstructs as `reconstructed_legacy` unconditionally | CAUGHT |
| M-D8 | the trial stamp guard `if not trial_config.is_trial` removed | CAUGHT |

**Deviation from the plan:** D3 is smaller than designed, for the reason
above. Classified as §14 category 2 ("an existing test already covers a
planned new test") — proceeded autonomously and recorded.

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
production functions. Three further mutations police the properties D3
owns:

```text
M-D6  core/resume.py's predicate ignores `resolution.authoritative`
M-D7  a verdict-less legacy record reconstructs as `reconstructed_legacy`
      unconditionally, instead of only when its OWN iteration declared
M-D8  the tuner's `if not trial_config.is_trial` stamp guard is removed
```

**M-D6's classification is worth reading rather than tallying.** It
survived D3's own module and was caught by `test_resume_incumbent.py`
(12 failures) — the module that owns the predicate. D3 drives
`resolve_record_authority`, not `_formal_candidate_is_authoritative`, so
the correct response was to record it as caught-by-owner, **not** to add
a duplicate test that names no defect only it can catch. A mutation
caught anywhere in the suite is caught; which module catches it is
evidence about test ownership, not about coverage.

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

### Layer F — PR-level mutation account

Reported by category, never as a percentage:

```text
13 attempted
13 behaviour-changing -> all caught
 0 equivalent / unreachable / invalid

  D1  4   N1 either-axis->both-axis; N2 drop non_blocking_mode;
          N3 precedence reordered; N4 declared_diagnostic stops blocking
  D2  6   M-D1/M-D2 launcher call-site kwargs; M-D3 forwarding inside
          run_workflow; M-D4 assignment in local_validated_model;
          M-D5a default ONE axis; M-D5b default BOTH axes
  D3  3   M-D6 predicate ignores authoritative (caught by its owning
          module); M-D7 unconditional legacy reconstruction;
          M-D8 trial stamp guard removed
```

Three survivors occurred during development — M-D3, M-D1/M-D2 in D2 —
and **every one was a defect in the test, not a gap in the mutation set**.
Each is recorded at §D2.R with the specific way a reachability test can be
decoration. A fourth apparent survivor was the harness reporting
`NOT-APPLIED` when an anchor matched seven sites, which is the `count == 1`
discipline working rather than a result.

## 6. Backward compatibility / parity

| invariant | how it is preserved |
|---|---|
| every declared posture's verdict | matrix pinned before the change (D1) |
| undeclared → `legacy_authority_unknown` | `None` defaults at hops 7-8; M-D5a/M-D5b guard the wrong fix |
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
Metric-frozen proof:      VERIFIED BY DIFF at the final head — no scorer,
                          metric, SNR, loss, health-check or authority-semantics
                          file appears in `git diff 57087ed9..HEAD` outside
                          docs/. The complete non-doc diff is 3 production
                          files (ten wiring lines) + 4 test files. Command and
                          output recorded in §PR-D final validation

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
                          with the residual stated (FU-D21-2). Full configured
                          CI equivalent from a clean tree: 8146 passed,
                          2 skipped, 1 xfailed, pytest rc=0, 0 FAILED/ERROR;
                          ruff + format clean; pyright 0 errors / 4 warnings at
                          baseline. Mutations 13 attempted / 13 behaviour-
                          changing -> 13 caught / 0 equivalent (Layer F)
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
`run_comparison` a default `blocking + scientific` posture would
manufacture authority (mutation **M-D5b**), and adding two CLI flags purely for
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

**Precision on what "undeclared" means here** (operator correction,
2026-08-08). `run_comparison` must remain undeclared on **both** axes.
Note the two failure modes are not interchangeable:

```text
giving it ONE axis      -> still legacy_authority_unknown
                        -> does NOT confer authority
                        -> but its records would then carry a declaration
                           the launcher never made
giving it BOTH axes     -> confers authority this launcher has no
                           campaign posture to justify
```

So the reason for leaving it alone is **not** "one axis would be enough
to confer authority" — it would not. It is that `run_comparison` declares
no campaign posture at all, and neither a partial nor a complete
declaration would be truthful.

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

## PR-D final validation

Run from a **clean tracked tree** at `6030be59`, per CLAUDE.md — the
PR3-L2 preflight refuses uncommitted production edits, so a full-suite
verdict from a work-in-progress tree means nothing. Commits after this
point are **documentation only** (`git diff --name-only 6030be59..HEAD`
returns paths under `docs/` alone), so the verdict still holds at the
final head.

```text
pytest tests/unit -q -m "not real_run"
    8146 passed, 2 skipped, 1 xfailed        497.25s
    PYTEST_RC=0                              (pytest's own status, not a pipe's)
    grep -cE "^(FAILED|ERROR)"  ->  0

ruff check .                                 All checks passed!
ruff format --check .                        768 files already formatted
pyright (1.1.409)                            0 errors, 4 warnings   [baseline held]

GitHub CI, run 31295064064, headSha dbf8a29a
    Lint + Type + Unit Tests                 SUCCESS   10m38s
```

Documentation-only commits followed the clean-tree suite and followed CI;
`git diff --name-only dbf8a29a..HEAD` returns paths under `docs/` alone,
so neither verdict is stale. The configured CI is unit + static **by
design**, which is why §E.4's "acceptance evidence complete" requires this
PR's own transport and mutation evidence *in addition to* a green CI —
never CI alone.

**The test-count delta is itself a check.** Baseline at `57087ed9` was
`8087 passed, 2 skipped, 1 xfailed`. The final run is `8146` — exactly
`+59`, which is `32` (D1 matrix) `+ 17` (D2 transport) `+ 10` (D3
consumers). No pre-existing test was deleted, renamed away or silently
skipped to reach green.

### Metric / scorer / HealthGate freeze — proved by diff, not asserted

```bash
git diff --name-only 57087ed9..HEAD -- . ':(exclude)docs' \
  | grep -E 'scoring|score|snr|metric|health_check|healthgate|loss_models|scientific_authority'
# -> no matches
```

The complete non-documentation diff is **seven files — 3 production, 4
tests**. (Corrected on operator review 2026-08-08: this line read "six",
and the block below was headed "TESTS (3 files)" while listing four
paths. `test_launch_surface_parity.py` is the fourth — modified rather
than new, which is exactly how it went uncounted twice.)

```text
PRODUCTION (3 files, ten wiring lines, +36/-1 with imports and comments)
  sdsc_submission_scripts/run_one_iteration.py            2 arguments passed
  workflows/model_exploration.py                          2 params + 2 forwarded
  agent/schemas/protocols/ml_model_valid_to_ml_model_tune.py
                                                          2 params + 2 fields set

TESTS (4 files — 3 new, 1 modified)
  tests/unit/core/test_authority_matrix_frozen.py             new, 32
  tests/unit/agent/schemas/test_authority_transport_reachable.py  new, 17
  tests/unit/core/test_authority_end_to_end_and_history.py    new, 10
  tests/unit/sdsc_submission_scripts/test_launch_surface_parity.py
                                                              +2 field names
```

`core/scientific_authority.py`, every scorer and SNR module,
`configs/health_checks.yaml` and every health-check skill are absent from
the diff. **`scripts/run_comparison.py` is absent**, which is O-D-1
holding rather than an omission.

### Pre-review audit of this document and the ledger

Performed 2026-08-08 before opening the PR, and it found eleven defects —
recorded because "the design doc is the live ledger" is only true if the
ledger is audited like code. The three that mattered:

| # | defect | why it mattered |
|---|---|---|
| 1 | a `[x]` on "clean-tree full suite" that had **not been run**, pointing at a `§PR-D final validation` section that did not exist | the PR's terminal validation claimed as done. Marking a checkbox falsely is a workflow violation, not untidiness |
| 2 | D3's checklist items **overwritten by their own evidence**, destroying the record of what was planned | D1 and D2 keep `[x] <plan item>` + evidence. D3 lost its before-state — the exact thing an append-only ledger exists to preserve. Restored from `c2664f8b` |
| 3 | `FU-D-1` collided with V20 PR D's live `FU-D-1 … FU-D-12`, two of which are operator-facing flags in `docs/running_chain_test.md:114,117` | two distinct open items under one label. Renamed `FU-D21-*` before any external reference existed |

Also corrected: a stale status header claiming no implementation had
begun; a §7 command block whose commands were never the ones actually
run (the three named consumer suites have now been run — `71 passed`);
three `M-D5` references surviving the M-D5a/M-D5b split; D3's mutations
missing from the validation ladder; no PR-level mutation account; both
follow-ups unregistered in the ledger; and in `v21_priorities.md`, an
overview table still advertising PR D's **withdrawn** premise
("Per-file evidence to reflector and planner", gated "Before V21") plus a
PR A row reading "awaiting merge" three PRs after it merged.

One further defect surfaced from *running* the checks rather than reading
the text: `ruff format --check` had been reporting `1 file would be
reformatted` and I recorded the ruff line without chasing which file. It
was D3's own module, so the commit would have failed CI on formatting
alone. Fixed in `6030be59`.

---

## Follow-ups filed by PR D — none launch-blocking

**Naming.** V20's PR D already owns `FU-D-1` … `FU-D-12`, two of which
(`FU-D-11`, `FU-D-12`) are cited as live operator-facing flags in
`docs/running_chain_test.md:114,117`. Reusing `FU-D-1` here would have put
two distinct open items under one label. V21 PR D therefore files under
**`FU-D21-*`**. Caught during the pre-review audit of this document; the
originally-filed `FU-D-1` was renamed before any external reference to it
existed.

| ID | Item | Why not in this PR | Blocking? |
|---|---|---|---|
| **FU-D21-1** | `FormalValidity` is a `Literal` *type alias*, not an enum, and `from_context` does not validate it — an unrecognised string matches no blocker branch and therefore behaves exactly like `"valid"` | Pre-existing property of a **frozen** function (§7 of the working rules). Not reachable from PR D's transport: the tuner passes `formal_validity_of(...)`, which returns one of the three. Fixing it would be a semantics change PR D is forbidden to make | No |
| **FU-D21-2** | No deterministic fixture executes `run_one_iteration.__main__` end to end, so hop 7's call site is covered by an AST call-site assertion plus mutations M-D1/M-D2 rather than by execution | O-D-2 classifies a pseudo-mode chain iteration as **optional strengthening evidence, explicitly not a merge requirement**. Recorded rather than closed, and deliberately left as an unchecked box in D3 §4 so the ledger does not claim work that was not done | No |

## Remaining operator decisions

**None — implementation and validation are COMPLETE and CI is green; PR D
is READY FOR OPERATOR MERGE.** Q-D-1 was resolved by O-D-1 and the census is frozen at
§0.C.1; the Gate question was resolved by O-D-2. No design decision
remains open.

Operator review 2026-08-08: **implementation APPROVED**, subject only to
two documentation reconciliations — the diff-file count above, and this
paragraph, which still read *"implementation may begin"* long after it
had. Both applied. No additional Gate, code change or validation run was
required. **FU-D21-1 was explicitly confirmed as correctly deferred**:
real, but pre-existing, unreachable from PR D's transport, and fixable
only by changing frozen authority semantics.

Two boundaries remain the operator's, not the implementer's, should they
arise later:

- moving any launcher between census categories (§0.C.1 is closed);
- any change to the 27-row verdict matrix (frozen by §0.A and pinned by
  D1) — which would no longer be PR D.
