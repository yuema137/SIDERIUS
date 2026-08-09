# PR E — Proposal-scale funnel instrumentation

**Status: DESIGN REVISION 2 — 2026-08-08, returned for operator review.
Not approved; no implementation begun. No production code, test, schema,
launcher or scorer file is touched by this document.**

Revision 2 applies operator decisions **O-E-1 … O-E-5** and the
persistence audit they required. The result is **materially smaller than
revision 1**: two of revision 1's five commits disappear entirely, because
the audit proved the measurements they would have copied downstream are
already persisted by the stage that owns them.

| | |
|---|---|
| Plan section | `docs/design/v21_priorities.md` — PR E section + §E.3d (binding) |
| Gate | **V21 global checkpoint 5** — the last one before a campaign may start |
| Depends on | A (`b9f88ae5`), C (`cac86c94`), B (`0aae3f4b`) merged; D (#189) approved |
| Audit date | 2026-08-08, against `16c0a1b8` |

---

## A0. Verification toolchain

```bash
PYRIGHT_PYTHON_GLOBAL_NODE=off uv run pyright     # pyright 1.1.409
.venv/bin/python -m pytest tests/unit -q -m "not real_run" > /tmp/pytest.log 2>&1; echo $?
.venv/bin/python -m ruff check . && .venv/bin/python -m ruff format --check .
```

**Baseline:** unit suite `8146 passed, 2 skipped, 1 xfailed`; pyright
`0 errors, 4 warnings`; ruff clean.

Per CLAUDE.md the full suite runs **only from a clean tree**, and the
verdict is taken from pytest's own exit code, never from a pipe's.

---

## 0. Pre-design audit

### 0.A What revision 2 changed, and why

| O-E | Decision | Effect on the design |
|---|---|---|
| **O-E-1** | the "prompt contradiction" merge criterion is SUPERSEDED | §0.H closed; a dated correction goes in the ledger. Search-space policy stays shut |
| **O-E-2** | no new global disposition vocabulary; `stopped_at_stage` is **read-side derived** | revision 1's cross-schema `stopped_at_stage` field is **deleted** |
| **O-E-3** | join-on-read; measurements stay with their **native owner** | revision 1's **Commit E4 (forward the proposed count) is deleted entirely** — see §0.C |
| **O-E-4** | one candidate = one proposer-emitted proposal; a revision is a **new** candidate | maps exactly onto the existing outer attempt loop — see §0.D |
| **O-E-5** | `candidate_id` MAY be an observational join key; MUST NOT be a behavioural key | §0.F restates the invariant correctly; revision 1's "never a lookup key" was wrong |

### 0.B The five stages, as they exist in code

Stage sequence, `workflows/model_exploration.py::run_workflow`:

```text
:2214   for attempt in range(1, max_proposal_attempts + 1):
:2220     attempt_dir = {iter_dir}/attempt_{NNN}
:2327     proposal   = _propose_agent.run(propose_input)
:2333     attempt_dir renamed -> {iter_dir}/attempt_{NNN}_{model_name}
:2338     --- Implement -> Validate (inner retry loop per proposal) ---
:2428     validation = _valid_agent.run(valid_input)
:2569     tune_input = local_validated_model(...)        <- PR D's hop
:2665     tune_output= _tune_agent.run(tune_input)
```

| # | Stage | Parameter count | Native owner | Status |
|---|---|---|---|---|
| 1 | proposal | `ProposalOutput.parameter_count_estimate` (`agent/schemas/proposal.py:1042`) | `proposal_{run_name}.json` | **already persisted natively** |
| 2 | implementation | none — the implementor emits source, never instantiates | `implementor_{run_name}.json` | genuinely absent, and **out of scope** (§0.E) |
| 3 | validation | **instantiated at `ml_code_validator_agent.py:371`, count discarded** | `validation_{run_name}.json` | **the one real measurement gap** |
| 4 | preflight | `preflight_estimated_minutes`, `preflight_factor` on `ProposalOutput` | same file as stage 1 | **advisory only** — see §0.E |
| 5 | trained | `ExperimentRecord.model_params` (`hyperparam_tuning.py:371`) | the record | already complete |
| 5b | HealthGate / authority | gate results + PR D's `scientific_authority` | the record | already complete |

Two realized-count surfaces are **not** funnel stages and must not be
conflated with them: `isolated_probe.realized_parameter_count` and
`core/runtime_control/estimate_types.py:208 parameter_count`. Both are
**resource-estimation** inputs owned by PR B. Conflating them would repeat
the `authoritative`-vs-GPU-measurement-authority confusion PR D had to
disentangle.

### 0.C Native persistence audit — the audit O-E-3 required

**Every pre-tuner stage already persists its own output, per candidate.**

```text
nodes/ml_model_proposal_agent/…:1340   {workspace}/proposal_{run_name}.json
nodes/ml_model_implementor/…:1821      {workspace}/implementor_{run_name}.json
nodes/ml_code_validator_agent/…:683    {workspace}/validation_{run_name}.json
```

The filenames are fixed per `run_name`, which would be last-writer-wins —
**except that `workspace` is per-attempt**:

```text
:2220  attempt_dir = os.path.join(iter_dir, f"attempt_{attempt:03d}")
:2222  attempt_storage = _make_storage(attempt_dir, run_name)
:2333  named_dir = os.path.join(iter_dir, f"attempt_{attempt:03d}_{proposal.model_name}")
:2334  os.rename(attempt_dir, named_dir)
```

So each proposal attempt gets its own directory, and the three files live
inside it. **A candidate that dies at validation still has its proposal,
implementor and validation records on disk**, discoverable at
`{iter_dir}/attempt_*/`.

Two properties worth stating because the join depends on them:

- **Discovery is not name-dependent.** The rename *prefixes* with
  `attempt_{NNN}_`, so a glob finds every attempt regardless of what the
  model was called. This matters: P6.2 is about name-keyed fragility, and
  a funnel that could only find candidates by name would inherit it.
- **The inner implement→validate retry loop overwrites within one
  attempt dir.** Under O-E-4 those retries are the *same* candidate, so the
  terminal outcome survives and that is what the funnel needs. Intermediate
  retry attempts are not recoverable. **Recorded as a known limitation, not
  a defect to fix in PR E.**

**Binding consequence, per O-E-3.** Because stage-native evidence is
available for every candidate, **no measurement is copied downstream.**
Revision 1's plan to forward `parameter_count_estimate` through four hops
into `ExperimentRecord` is **withdrawn**: it would have created a second
copy of a number whose canonical owner already persists it, for the sole
purpose of making one row look complete.

```text
WITHDRAWN   proposal count -> Implementor -> Validator -> Tuner -> record
KEPT        proposal count stays in proposal_{run_name}.json, joined on read
```

### 0.D Candidate identity — absent, and O-E-4 maps cleanly onto the code

```bash
grep -rn "candidate_id\|proposal_id\|lineage_id\|candidate_uid" \
    agent/schemas/*.py agent/schemas/protocols/*.py
# -> no matches
```

Re-verified after A, C and D landed. `exp_id` is not a substitute: it is
minted inside the tuner, long after the proposal, one candidate produces
many, and it cannot label a candidate that died at validation.

**O-E-4 maps exactly onto the existing outer loop**, which is the reason
the definition is implementable without new control flow:

```text
one iteration
  attempt 1  -> _propose_agent.run(...) -> ProposalOutput  -> candidate A
      inner implement/validate retries on the SAME proposal -> still A
  attempt 2  -> _propose_agent.run(...) -> ProposalOutput  -> candidate B
  attempt 3  -> ...                                        -> candidate C
```

The outer `for attempt in range(1, max_proposal_attempts + 1)` re-runs the
**proposer**, so each attempt emits a new `ProposalOutput` — a new
candidate — and each already has its own directory. Inner retries reuse
the same `ProposalOutput` and therefore the same id. **This is precisely
O-E-4's definition, already expressed in the control flow.**

**A finding that resolves a tension revision 1 could not.** Revision 1
worried that preflight-rejected drafts would be invisible attrition with
no id. They do not exist: the proposer's preflight is **advisory only**
(`ml_model_proposal_agent.py:165-168`):

> *"C1 contract: the result is ADVISORY ONLY (static_uncalibrated
> provenance). Callers must not request proposal revision, inject
> rejection text into prompts, or otherwise derive blocking behavior from
> it."*

So no draft is ever rejected or revised by preflight, and every proposer
run emits exactly one `ProposalOutput`. **One proposer run ⇔ one
candidate**, with no hidden population.

**This corrects the ledger's own funnel description.** The ledger's scope
lists stage 3 as *"preflight disposition (admitted / rejected + typed
reason)"*. Preflight admits nothing and rejects nothing today; it records
an advisory factor. The funnel must record `preflight_factor` as a
**measurement**, never as a disposition. Recorded here rather than
silently reinterpreted.

### 0.E What has no native reason, and what PR E does about it

Per O-E-2, each stage's existing reason is the authority for that stage:

| stage | native reason | typed? |
|---|---|---|
| proposal | emitted, or the attempt produced nothing | n/a |
| preflight | `preflight_factor` — a number, **not** a disposition | measurement |
| implementation | **none** — retries then gives up | **absent** |
| validation | `passed` + six booleans naming which check failed | effectively typed |
| admission | `PhysicalRejection.binding_cap` `Literal[...]` | typed (PR B) |
| tuner round | `failure_stage`, `failure_type`, `status` `Literal[...]` | typed |
| HealthGate | gate results + `formal_validity` | typed |

**Implementation is the only stage with no typed reason. PR E does not
add one** (O-E-2). A candidate that stops there is reported as
`stopped_at_stage="implementation"` with the reason **absent** — absence
preserved as information, per §E.3d.4. Typing the implementor's failures
is a legitimate follow-up and is explicitly not this PR.

### 0.F `candidate_id` usage boundary — corrected per O-E-5

Revision 1 said *"a label, never a lookup key"*. That was wrong, and the
correct invariant is narrower and more useful:

```text
ALLOWED     observational correlation / join.
            A read-side dict keyed by candidate_id is EXPECTED and valid.

FORBIDDEN   any behavioural or correctness key:
            model registration, dispatch, execution, compatibility,
            admission, scoring, scientific decisions, filesystem routing.
```

The acceptance test is therefore **not** "the string never appears in a
dict key" but "no production branch changes behaviour because of it".
E2 §5 states how that is proved.

### 0.G Semantics-neutral naming — binding

```text
ALLOWED    parameter_count_estimate      realized_parameter_count
           model_params                  preflight_factor
           stopped_at_stage (derived)    reason_absent
FORBIDDEN  undersized  too_small  scale_deficit  size_violation
           is_undersized  severity
```

B2's precedent: record `realized − estimated` and `realized − threshold`
as separate quantities rather than one judged number.

### 0.H Ledger merge criterion — CLOSED by O-E-1

The PR E merge criteria's *"prompt contradiction resolved"* clause is
**superseded**: the ledger's own 2026-08-07 correction establishes there
is no contradiction between the encouraged 10M-100M range and the ~100M
prior, and PR E is forbidden from changing that prior. A dated
append-only correction goes into `v21_priorities.md`. **Search-space
policy is not reopened.**

---

## 1. Objective

> **Give every proposer-emitted candidate an immutable id, capture the one
> parameter count that is currently measured and discarded, and assemble
> the funnel by joining stage-native records on read — without correcting
> anything and without claiming a distribution.**

Per §E.3d.6, PR E ships the **capability to measure**. It may not report
a funnel distribution, because none has been collected.

## 2. Non-goals

```text
NO  corrective action of any kind
NO  edit to the ~100M prior, advice text, thresholds, or a size floor
NO  new disposition / reason vocabulary                       (O-E-2)
NO  copying a measurement downstream past its native owner    (O-E-3)
NO  new persistent funnel artifact or manifest extension      (O-E-3)
NO  parent_candidate_id / lineage structure                   (O-E-4)
NO  behavioural use of candidate_id                           (O-E-5)
NO  typing the implementor's failure reasons
NO  scorer / metric / HealthGate-semantic change
NO  claiming a funnel distribution                            (§E.3d.6)
NO  planner exposure or production-default change  (separate approval)
```

## 3. Transport contract — one field, and only one

**`candidate_id` is the only cross-stage transport in PR E.** Every
measurement stays with its native owner and is joined on read.

```text
proposer mints candidate_id
  -> ProposalOutput.candidate_id            NEW   -> proposal_{run}.json
  -> local_full_spec    -> ImplementorInput/Output  NEW -> implementor_{run}.json
  -> local_all_fields   -> ValidatorInput/Output    NEW -> validation_{run}.json
  -> local_validated_model -> HyperparamTuningInput NEW
  -> tuner -> ExperimentRecord.candidate_id NEW   -> the record
```

| hop | producer | consumer | absent ⇒ |
|---|---|---|---|
| 1 | proposer | `ProposalOutput` | `None` — predates PR E |
| 2 | `local_full_spec` | `ImplementorInput` | `None` propagates |
| 3 | `local_all_fields` | `ValidatorInput` | `None` propagates |
| 4 | `local_validated_model` | `HyperparamTuningInput` | `None` propagates |
| 5 | tuner | `ExperimentRecord` | `None` — row unjoinable, and **says so** |

Measurement ownership, per O-E-3 — **none of these move**:

```text
parameter_count_estimate   proposal stage   proposal_{run_name}.json
preflight_factor           proposal stage   proposal_{run_name}.json
realized_parameter_count   validator stage  validation_{run_name}.json   (E3 adds)
model_params               tuner            ExperimentRecord
stop stage / reason        DERIVED ON READ  no schema field at all
```

**Binding principle 2:** deleting any of the five hops must fail a test,
proved by an **AST call-site assertion**, not a substring search
(§E.3d.9 — PR D's M-D1/M-D2 survived a substring search that matched seven
identical call sites).

**Absence is never defaulted.** A missing `candidate_id` means "predates
PR E, or the chain was severed". Synthesising one would manufacture a join
that looks valid and is not — the direct analogue of PR D's rule that
absence must not become a declaration.

## 4. Commit plan

| # | Commit | Blocked on | Independently reviewable |
|---|---|---|---|
| **E0** | Audit + design synchronisation (this document) | — | Yes (docs only) |
| **E1** | Pin the current stage contract and persistence layout | — | Yes |
| **E2** | Mint and transport `candidate_id` | E1 | Yes |
| **E3** | Stop discarding the validator's realized parameter count | E1 | Yes |
| **E4** | Read-side funnel assembly, derived stop-stage, completeness | E2, E3 | Yes |

Revision 1 had five commits; **its E4 (forward the proposed count) is
deleted** by O-E-3, and its `stopped_at_stage` schema field is deleted by
O-E-2. E3 is now independent of E2 — it adds a field to one schema and
forwards nothing.

> **Two clauses of the commit template are deliberately not applicable.**
> The ordering-specific requirements — *"validate the actual visited
> sample/file sequence"* and *"for the default `shuffle` path, prove that
> selection, random-seed behavior, visited sequence and step count remain
> unchanged"* — belong to a data-ordering feature. PR E touches no
> sampling, ordering, seeding, `file_order` or step-count surface.
> **The analogous parity obligations for PR E are E1's behavioural pin and
> E3's verdict parity.** Likewise the template's *"invalid `file_order`,
> missing files, duplicate files, scope mismatch"* edge cases are replaced
> in each §6 by the ones PR E actually has: duplicate `candidate_id`,
> severed transport, legacy `None`, multi-candidate iterations, and the
> inner-retry overwrite.

---

### Commit E1 — Pin the stage contract and the persistence layout

#### 1. Goal

Turn the audit's two load-bearing facts into regression fixtures **before**
anything changes: the schema key sets, and the per-attempt persistence
layout the entire join-on-read design rests on.

**Why this commit and not another.** D1's argument exactly — a parity
claim written after a change cannot distinguish "unchanged" from "changed,
and the expectation was written to match". It must not live in E2/E3,
because a test added in the same commit as the change it guards proves
nothing about the before-state. The persistence pin belongs here rather
than in E4 because **if the layout is not what the audit says, the whole
join-on-read decision is wrong and E4 must not be written**.

#### 2. Scope

**Changes**
- `tests/` — one module pinning schema key sets; one pinning the layout.

**Must remain unchanged**
- Every production file. **Zero production diff.**

**Non-goals** — any new field, transport or assembly.

**Dependencies:** none.

#### 3. Implementation plan

- [ ] Re-read `run_workflow` `:2214-2428` and record the attempt-loop
      structure and the rename at `:2333`
- [ ] Pin exact key sets for `ProposalOutput`, `ImplementorOutput`,
      `ValidatorOutput`, `HyperparamTuningInput`, `ExperimentRecord`, so
      E2/E3 adding a field is a deliberate visible edit to this module
- [ ] Pin `ValidatorOutput` as having **no numeric field** — the fact E3
      changes
- [ ] Pin the persistence layout as behaviour, not documentation: drive
      the three nodes against a `tmp_path` workspace and assert
      `proposal_`, `implementor_`, `validation_{run_name}.json` are each
      written where the audit says
- [ ] Pin that two attempts write into **different** directories and do
      not overwrite each other — the property join-on-read depends on
- [ ] Pin that the inner retry loop **does** overwrite within one attempt
      dir, so the known limitation is recorded as tested behaviour rather
      than an assumption
- [ ] Hardcode every expectation; never read a value back from the thing
      under test (CLAUDE.md)

#### 4. Validation plan

**Unit**
- [ ] Five exact key-set assertions
- [ ] `ValidatorOutput` has no numeric field

**Integration / pseudo**
- [ ] Two simulated attempts produce two directories, both discoverable by
      a `attempt_*` glob, neither overwriting the other

**Negative / invalid input**
- [ ] A workspace with no attempt dirs yields an empty discovery, not an error

**Backward-compatibility / default parity**
- [ ] All pre-existing schema and protocol suites pass **unmodified**

**Real-training Gate:** none. A GPU cannot evaluate a key set or a path.

#### 5. Acceptance criteria

- Five key-set assertions exist as literals; adding any field in E2/E3
  fails **this** module until deliberately updated in that commit.
- A test writes two attempts to a `tmp_path` and asserts **two distinct
  directories**, each containing the stage files, both matched by
  `attempt_*` — the exact property E4's join relies on.
- A test asserts discovery does **not** depend on `model_name`, by
  globbing on the `attempt_{NNN}_` prefix with an arbitrary name.
- `git diff --name-only` contains **zero** production files.

#### 6. Failure and edge cases

| Case | Required behaviour |
|---|---|
| The layout is **not** per-attempt as audited | **Stop and report.** Join-on-read's premise fails and E4 must be redesigned before it is written |
| A node's persistence is conditional on `storage.backend == "local"` | Record the condition explicitly; the join must handle a non-local backend as "not discoverable", never as "no candidate" |
| A key set churns for unrelated reasons | Pin only the funnel-relevant subset **and say so**; never silently narrow |
| An existing test already pins part of a key set | Keep both |

#### 7. Verification commands and evidence

```bash
.venv/bin/python -m pytest tests/unit/agent/schemas tests/unit/agent/protocols -q
.venv/bin/python -m pytest tests/unit/workflows -q
.venv/bin/python -m ruff check . && .venv/bin/python -m ruff format --check .
```

- [ ] New module counts and wall time — **to record**
- [ ] Pre-existing suites unmodified — **to record**
- [ ] Mutation: make two attempts share a directory → must fail — **to record**

#### 8. Commit boundary

- [ ] Tests only; zero production files
- [ ] No field, no transport, no assembly
- [ ] Diff summary, staged file list, tests and deviations shown before committing

---

### Commit E2 — Mint and transport `candidate_id`

#### 1. Goal

Give every proposer-emitted proposal an immutable id and carry it,
unchanged, to the persisted experiment record — so stage-native records
can be joined at all.

**Why this commit and not another.** It is the only transport in PR E and
the enabler for E4. Separated from E3 because identity transport fails for
a different reason than a missing measurement, and a red test should name
which.

#### 2. Scope

**Changes**

```text
agent/schemas/proposal.py            ProposalOutput.candidate_id    NEW, optional
agent/schemas/implementor.py         ImplementorInput/Output        NEW, optional
agent/schemas/validator.py           ValidatorInput/Output          NEW, optional
agent/schemas/hyperparam_tuning.py   HyperparamTuningInput          NEW, optional
                                     ExperimentRecord.candidate_id  NEW, optional
agent/schemas/protocols/             ml_model_propose_to_ml_model_impl.py
                                     ml_model_impl_to_ml_model_valid.py
                                     ml_model_valid_to_ml_model_tune.py
nodes/ml_model_proposal_agent/…      mint
nodes/ml_hyperparameter_tune_agent/… stamp onto the record
tests/
```

**Must remain unchanged**
- Every scorer, metric and HealthGate file; `core/scientific_authority.py`
  and PR D's transport.
- Model naming, registration, `MODEL_REGISTRY`, dispatch, admission,
  scoring, filesystem routing — **O-E-5's forbidden list**.
- The attempt-loop control flow. The id labels the existing structure; it
  does not create or alter one.

**Non-goals**
- `parent_candidate_id` / lineage (O-E-4 — future follow-up if needed).
- Any behavioural branch on the id.

**Dependencies:** E1.

#### 3. Implementation plan

- [ ] Re-read each protocol file immediately before editing and follow the
      flat-optional-parameter pattern PR D established at
      `ml_model_valid_to_ml_model_tune.py:54-55,275-276`
- [ ] Mint the id in the proposer at the point one `ProposalOutput` is
      emitted — **exact site and format decided after reading the emit
      path**, not invented here. Requirements: unique per emitted
      proposal; **new id on every proposer run** (O-E-4); not derived from
      `model_name`
- [ ] Add `candidate_id: str | None = None` to the five schemas, each
      documenting that `None` means "predates PR E or transport severed",
      never "unknown, substitute one"
- [ ] Add one parameter per protocol function, `default=None`
- [ ] Stamp onto `ExperimentRecord` at the tuner
- [ ] Grep-verify no registration, dispatch, admission, scoring or path
      construction reads it

#### 4. Validation plan

**Unit**
- [ ] A minted id arrives unchanged at `ExperimentRecord`
- [ ] An omitted id arrives as `None` at every hop; nothing is synthesised
- [ ] Two proposer runs in one iteration mint **different** ids (O-E-4)
- [ ] Inner implement/validate retries on one `ProposalOutput` keep the
      **same** id (O-E-4)

**Integration / pseudo**
- [ ] Drive the **real** protocol functions, not a reimplementation —
      B1b's P2 and PR D's M-D3 both survived exactly that mistake

**Negative / invalid input**
- [ ] A duplicate id within one run is impossible by construction, or
      fails loudly at mint (§6)

**Backward-compatibility / default parity**
- [ ] A record with no `candidate_id` loads, scores and resumes unchanged
- [ ] No retroactive id on resumed pre-PR-E iterations — the analogue of
      PR D's non-retroactivity rule
- [ ] E1's key-set pins updated **in this commit**, deliberately

**Real-training Gate:** none proposed. **Not to be launched without
operator approval.**

#### 5. Acceptance criteria

- Given a minted id at the proposer, the persisted `ExperimentRecord`
  carries that exact string.
- Deleting the parameter at **any one** of the five hops fails a test,
  detected by an **AST call-site assertion** (`ast.Name` of the same id),
  not a substring search.
- Given no id, every hop reports `None`; no synthesis anywhere.
- **O-E-5 boundary, proved as behaviour not as grep:** a test runs the
  production path twice with two *different* `candidate_id` values and
  asserts every behavioural output is identical — same registration, same
  dispatch, same admission decision, same score, same paths. Only the
  recorded label differs. A grep for `candidate_id` in registry/path code
  is kept as a **supporting** check, because grep cannot prove absence of
  behaviour.
- Two proposer runs mint different ids; inner retries keep one.

#### 6. Failure and edge cases

| Case | Required behaviour |
|---|---|
| Duplicate `candidate_id` in one run | **Fail loudly at mint.** A duplicated join key silently merges two candidates' funnels — worse than no funnel |
| Legacy record, `candidate_id=None` | Load normally; the row is unjoinable and reported as such. **Never** synthesise |
| Transport severed at one hop | `None` reaches the record; caught by that hop's mutation, not by a runtime error |
| Resume of a pre-PR-E iteration | Unchanged; no retroactive id |
| Proposer emits a revised proposal | **New id** (O-E-4). Asserted, because it is the definition the eventual measurement depends on |
| Inner implement/validate retry | **Same id** (O-E-4). Asserted |
| Multi-candidate iteration | Distinct ids; assert with two candidates, never one |

#### 7. Verification commands and evidence

```bash
.venv/bin/python -m pytest tests/unit/agent tests/unit/workflows -q
.venv/bin/python -m pytest tests/unit -q -m "not real_run" > /tmp/pytest.log 2>&1; echo $?
PYRIGHT_PYTHON_GLOBAL_NODE=off uv run pyright
```

- [ ] Reachability module count / wall time — **to record**
- [ ] Five hop-deletion mutations, one per hop — **to record**
- [ ] Mutation: synthesise an id when absent → must fail — **to record**
- [ ] Mutation: reuse one id across two proposer runs → must fail — **to record**
- [ ] pyright vs baseline — **to record**

#### 8. Commit boundary

- [ ] Diff touches five schemas, three protocols, two nodes, tests
- [ ] No scorer, metric, HealthGate or registration file
- [ ] No measurement forwarded — this commit moves **only** the id
- [ ] Diff summary, staged file list, tests, mutations and deviations shown before committing

---

### Commit E3 — Stop discarding the validator's realized parameter count

#### 1. Goal

Record the parameter count of the model the validator **already
instantiates**, on the validator's own output, so proposed-vs-realized is
comparable for every candidate that reaches validation — including those
that never train.

**Why this commit and not another.** It is a distinct causal fact — a
measurement computed and thrown away — from E2's missing join key, and it
is the only stage where the number exists *before* training.
`ExperimentRecord.model_params` cannot cover candidates that die at
validation or admission, because they never produce a record.

**Independent of E2** in revision 2: it adds one field to one schema and
forwards nothing. It is ordered after E1 only for the key-set pin.

#### 2. Scope

**Changes**

```text
nodes/ml_code_validator_agent/…   _check_instantiation_and_gradient returns the count
agent/schemas/validator.py        ValidatorOutput.realized_parameter_count  NEW, optional
tests/
```

**No protocol changes. No downstream schema changes.** Per O-E-3 the
validator is the canonical owner and `validation_{run_name}.json` is where
the number lives.

**Must remain unchanged**
- **The validator's verdict.** `passed` and all six check booleans must be
  bit-identical for every input. E3 adds an observation; it must not
  become a gate.
- The instantiation and gradient logic itself.

**Non-goals**
- Any threshold, warning or rejection based on the count.
- Instantiating a model anywhere it is not already instantiated.
- Forwarding the count anywhere.

**Dependencies:** E1.

#### 3. Implementation plan

- [ ] Re-read `ml_code_validator_agent.py:336-400` and its call site at
      `:633` immediately before editing; the model is instantiated at `:371`
- [ ] Widen the helper's return, or return a small typed result — decide
      after reading the call site, not before
- [ ] **Determine and match the convention used by
      `ExperimentRecord.model_params`.** `train_engine_sandbox.py:664`
      uses `sum(p.numel() for p in model.parameters() if p.requires_grad)`
      — trainable-only — while `probe_production.py:202` counts all. The
      two must be comparable or the funnel's central comparison is
      meaningless. **Verify the exact expression before choosing**
- [ ] Return `None` when instantiation fails; never `0`
- [ ] Assert the verdict booleans are unchanged for every existing case

#### 4. Validation plan

**Unit**
- [ ] A plugin of known size reports exactly that integer
- [ ] Instantiation failure → `None`, not `0`
- [ ] **Convention parity:** a fixture plugin containing a **frozen**
      parameter, where total and trainable-only differ observably, asserts
      the validator's count matches `model_params`' convention exactly

**Integration / pseudo**
- [ ] The count is present in the persisted `validation_{run_name}.json`

**Negative / invalid input**
- [ ] Import error and config error paths return the same verdict and a
      `None` count

**Backward-compatibility / default parity**
- [ ] **Verdict parity is the acceptance signal:** every existing
      validator test passes **unmodified**
- [ ] E1's `ValidatorOutput` key-set pin updated deliberately

**Real-training Gate:** none. The count needs no training.

#### 5. Acceptance criteria

- For a fixture plugin of known size,
  `ValidatorOutput.realized_parameter_count` equals that exact integer,
  and the value is present in the persisted JSON.
- Every pre-existing validator test passes **unmodified**.
- Instantiation failure yields `None`; no path can produce `0` for a model
  that failed to instantiate.
- The convention **provably matches** `ExperimentRecord.model_params`,
  proved with a frozen-parameter fixture where the conventions would
  otherwise disagree.
- No branch anywhere reads the count.

#### 6. Failure and edge cases

| Case | Required behaviour |
|---|---|
| Model instantiates but `.parameters()` raises | `None`, verdict unchanged; never crash the validator |
| Model has zero parameters | Record `0` — a real measurement, distinct from `None` (§E.3d.4) |
| The two conventions disagree | **Stop and report.** Choosing silently would make the funnel's central comparison wrong in a way no later test catches |
| Count contradicts `parameter_count_estimate` wildly | Record it. **No warning, no verdict** — that is the point of the PR |

#### 7. Verification commands and evidence

```bash
.venv/bin/python -m pytest tests/unit/agent/ml_code_validator_agent -q
.venv/bin/python -m pytest tests/unit -q -m "not real_run" > /tmp/pytest.log 2>&1; echo $?
```

- [ ] Validator suite unmodified, count and wall time — **to record**
- [ ] Mutation: switch total ↔ trainable-only → must fail — **to record**
- [ ] Mutation: return `0` instead of `None` on failure → must fail — **to record**
- [ ] Mutation: let the count influence `passed` → must fail — **to record**

#### 8. Commit boundary

- [ ] Diff touches the validator node, its schema, tests — nothing else
- [ ] No protocol, no downstream schema, no verdict logic
- [ ] Diff summary, staged file list, tests and deviations shown before committing

---

### Commit E4 — Read-side funnel assembly, derived stop-stage, completeness

#### 1. Goal

Assemble the funnel by joining stage-native records on `candidate_id`,
derive where each candidate stopped from the native outcomes, and prove
no candidate is silently dropped or merged.

**Why this commit and not another.** It consumes E2 and E3 and adds no
transport and no schema field. Its failure mode — a join that silently
merges or drops rows — is different from a transport gap.

#### 2. Scope

**Changes**
- A read-side assembly helper. Location decided by inspection; it is a
  **reader**, so it must not live inside a producer node.
- `tests/` — completeness, derivation, backfill.
- This design document.

**Must remain unchanged**
- Every producer touched by E2/E3. **A diff in one is a finding, not a
  task.**
- Nothing is written to disk. The assembler is **read-only** (O-E-3).

**Non-goals**
- Any new persistent artifact or manifest key.
- Any aggregate, mean, ratio, distribution or verdict.
- Any new reason vocabulary — `stopped_at_stage` is **derived**, not stored.

**Dependencies:** E2, E3.

#### 3. Implementation plan

- [ ] Discover candidates by globbing `{iter_dir}/attempt_*/` and reading
      whichever of `proposal_`, `implementor_`, `validation_{run}.json`
      exist, plus the tuner's records
- [ ] Join on `candidate_id`; records with `None` are **unjoinable**, each
      kept separate
- [ ] **Derive** `stopped_at_stage` from which native outcomes exist and
      what they say — no stored field (O-E-2)
- [ ] Carry each stage's **native** reason verbatim; where a stage has
      none (implementation, §0.E), mark the reason **absent**
- [ ] Report a candidate with a missing stage as **incomplete, stage
      named** — never dropped, never defaulted
- [ ] Record `preflight_factor` as a **measurement**, never a disposition
      (§0.D)
- [ ] Backfill: run over **stored** attempt-3 records and confirm the
      parameter distribution the ledger already records
      (663,488 - 12,772,096) is reproduced, **without claiming any new
      distribution** (§E.3d.6)
- [ ] Emit no aggregate, mean, ratio or verdict

#### 4. Validation plan

**Unit**
- [ ] Complete candidate → every reached stage present
- [ ] Candidate stopped at validation → derived stage + the validator's
      own booleans as the reason
- [ ] Candidate stopped at implementation → stage named, reason **absent**
- [ ] Two candidates in one iteration do not merge

**Integration / pseudo**
- [ ] One pseudo-mode iteration yields a complete row end to end

**Negative / invalid input**
- [ ] Several records with `candidate_id=None` stay **separate and
      unjoinable** — never merged into one pseudo-candidate. This is the
      most dangerous possible bug in this commit
- [ ] A malformed / truncated stage JSON is reported as unreadable, not
      silently treated as a missing stage
- [ ] Non-local storage backend → "not discoverable", never "no candidate"

**Backward-compatibility / default parity**
- [ ] Backfill is **read-only**; assert nothing on disk changes

**Real-training Gate:** the ledger asks for *"one iteration produces a
complete funnel record"*. **Pseudo-mode is sufficient and is what this
design proposes.** A real iteration is optional strengthening evidence and
**must not be launched without operator approval.**

#### 5. Acceptance criteria

- For a fixture of four candidates — one complete, one stopped at
  validation, one stopped at implementation, one legacy with
  `candidate_id=None` — the assembler returns **exactly four rows**:
  complete; incomplete-named-at-validation with the native booleans;
  incomplete-named-at-implementation with reason **absent**; and one
  unjoinable. **Not three, and never one merged row.**
- With two legacy `None` records, the result has **two** unjoinable rows,
  not one.
- The backfill reproduces the ledger's recorded attempt-3 range from
  stored records, and the test asserts the **range**, not a new claim.
- The output contains no aggregate and no field on §0.G's forbidden list.
- No producer file appears in the diff; no file is written.

#### 6. Failure and edge cases

| Case | Required behaviour |
|---|---|
| Several tuner records share one `candidate_id` | **Expected** — one candidate has many rounds. The row is per candidate; assert the fan-in explicitly rather than assuming one-to-one |
| Multiple `None` ids | Each stays separate. Merging them is the failure this commit must make impossible |
| Stage reached but its number absent | Distinguish "stage not reached" from "reached, number absent" — §E.3d.4's four-state rule |
| Inner-retry overwrite (§0.C) | Only the terminal implement/validate outcome exists. Report it as such; **do not** infer retry count from its absence |
| Attempt dir exists but holds no proposal | The proposer emitted nothing, so there is **no candidate** (§0.D). Report the directory as "no candidate emitted", not as a stopped candidate |
| Zero candidates | Empty result, not an error |

#### 7. Verification commands and evidence

```bash
.venv/bin/python -m pytest tests/unit/execute_tools tests/unit/agent tests/unit/workflows -q
.venv/bin/python -m pytest tests/unit -q -m "not real_run" > /tmp/pytest.log 2>&1; echo $?
```

- [ ] Completeness tests count / wall time — **to record**
- [ ] Backfill result vs the ledger's recorded range — **to record**
- [ ] Mutation: merge `None`-id records → must fail — **to record**
- [ ] Mutation: drop an incomplete row instead of naming it → must fail — **to record**
- [ ] Clean-tree full suite, pytest rc, counts — **to record**

#### 8. Commit boundary

- [ ] Read-side + tests + this document only
- [ ] No producer file; nothing written to disk
- [ ] No aggregate, distribution claim or corrective change
- [ ] Diff summary, staged file list, tests and deviations shown before committing

---

## 5. Validation ladder

| Layer | Commit | What it proves |
|---|---|---|
| A | E1 | schema and persistence layout pinned **before** anything changes |
| B | E2 | identity reaches the record through the **real** protocols |
| C | E2, E3 | every hop is load-bearing — AST call-site assertions (§E.3d.9) |
| D | E3 | the discarded measurement is captured, verdict bit-identical |
| E | E4 | the join is complete; unjoinable rows stay unjoinable |
| F | all | PR-level mutation account, by category, never a percentage |

**Layer G — production-boundary evidence.** Assessment: **no GPU or LLM
Gate is required.** Identity transport is in-process typed plumbing; the
validator count needs no training; the assembler is read-only. The
residual, stated rather than papered over: no deterministic fixture drives
a *real* proposer, so the mint site is covered by a call-site test plus a
mutation — as PR D covered hop 7 and B1b covered its clamp. A pseudo-mode
iteration is the cheapest sufficient live confirmation and is **optional**.

**The scientific outcome is never the oracle.** A candidate proposing 600k
parameters is not a test failure.

## 6. Backward compatibility / parity

| invariant | how it is preserved |
|---|---|
| pre-PR-E records | all new fields optional and `None`; no retroactive id |
| validator verdicts | E3's acceptance signal is that every existing validator test passes **unmodified** |
| proposer behaviour | no prompt, advice or threshold file in the diff, proved by diff |
| scoring | no scorer/metric/SNR file in the diff, proved by diff |
| HealthGate | untouched |
| behavioural independence | two different `candidate_id`s produce identical behaviour, proved by execution (O-E-5), with grep as support only |
| on-disk artifacts | E4 writes nothing; the assembler is read-only |

## 7. Genericization review

- **Does the touched code treat one task or campaign as the framework?**
  No. `candidate_id` and parameter counts are task-agnostic.
- **Literals.** No model name, campaign name or size constant introduced.
  The `~100M` prior is untouched.
- **Bounded genericization performed:** none required — the change follows
  the flat-optional-field-plus-protocol-parameter pattern PR D established
  in the same protocol files.
- **Deliberately deferred:** `parent_candidate_id` / revision lineage
  (O-E-4 names it a possible future follow-up); typing the implementor's
  failure reasons (§0.E).

## 8. Acceptance and merge criteria

1. Every proposer-emitted proposal receives an id that arrives unchanged
   at the persisted record; a revision gets a **new** id, an inner retry
   keeps the **same** one.
2. All five transport hops are load-bearing, proved by AST-anchored
   mutations.
3. Two different `candidate_id` values produce **identical behaviour** —
   O-E-5's invariant, proved by execution.
4. The validator's realized count is captured where the model is already
   instantiated, with the verdict bit-identical and the convention
   provably matching `model_params`.
5. **No measurement is copied past its native owner** (O-E-3).
6. `stopped_at_stage` exists only as a derived read-side value; **no new
   reason vocabulary appears in the diff** (O-E-2).
7. The funnel assembles per candidate, names incomplete stages, and never
   merges unjoinable records.
8. **No distribution is claimed** (§E.3d.6).
9. No prompt, advice, threshold, scorer, metric or HealthGate file is in
   the diff; no new persistent artifact exists.
10. Full configured CI passes **in addition to** PR E's own reachability
    and mutation evidence.

### V21 review fields

```text
Metric-frozen proof:      to be verified by diff at merge — PR E touches no
                          scoring path

Name-keyed dependency
added:                    MUST BE NONE in the behavioural sense (O-E-5).
                          candidate_id is a valid observational join key; a
                          read-side dict keyed by it is expected. It must never
                          key registration, dispatch, admission, scoring or
                          filesystem routing. Proved by running the production
                          path under two different ids and asserting identical
                          behaviour — the line PR E is most at risk of violating

Transport contract:       field:    candidate_id  (the ONLY cross-stage field)
                          producer: ml_model_proposal_agent (mint, one per run)
                          boundaries: local_full_spec -> local_all_fields
                                      -> local_validated_model -> ExperimentRecord
                          consumers: read-side funnel assembly only
                          measurements: NOT transported — native owners per O-E-3
                          branches: complete / stopped-early / legacy-None

Subprocess evidence:      to be determined in E3 — confirm whether the
                          validator's instantiation runs in-process or in a
                          sandbox subprocess, and whether the count crosses it

Acceptance evidence:      Layers A-F deterministic; Layer G argued unnecessary
                          with the residual stated
```

---

## Operator decisions

### Recorded and applied — O-E-1 … O-E-5

All five are applied throughout revision 2; §0.A maps each to what it
changed. O-E-1 additionally requires a **dated append-only correction in
`v21_priorities.md`**, retiring the "prompt contradiction resolved" merge
criterion.

### Open — one, surfaced by the revision-2 audit

**Q-E-5 — parameter-count convention (E3 §3, blocking E3 only).**

`ExperimentRecord.model_params` is written from
`train_engine_sandbox.py:664` as **trainable-only**
(`if p.requires_grad`), while `probe_production.py:202` counts **all**
parameters. The validator's new count must match whichever convention the
funnel's proposed-vs-realized comparison is meant to use.

This is flagged rather than decided because it is a **measurement-
definition** question like O-E-4: a model with frozen layers reports two
different truths, and choosing silently would make the funnel's central
comparison wrong in a way no later test catches.

**My recommendation: match `ExperimentRecord.model_params`
(trainable-only), and record the choice explicitly in the design.** The
funnel's comparison is proposed-vs-realized-vs-trained, so the two
realized numbers must agree with the trained one, not with the probe.
E3 §3 requires verifying the exact expression before implementing, so this
can also be settled at that point if you prefer.

**No other decision is open. E1 is not to be implemented until this
revision is approved.**
