# PR E — Proposal-scale funnel instrumentation

**Status: DESIGN DRAFT 2026-08-08 — NOT approved, no implementation begun.
No production code, test, schema, launcher or scorer file is touched by
this document.** Three operator decisions are required before D-day; they
are listed at the end and two of them change the commit plan.

| | |
|---|---|
| Plan section | `docs/design/v21_priorities.md` — PR E section + §E.3d (binding) |
| Gate | **V21 global checkpoint 5** — the last one before a campaign may start |
| Depends on | A (`b9f88ae5`), C (`cac86c94`), B (`0aae3f4b`) merged; D (#189) approved |
| Audit date | 2026-08-08, against `4d608902` (PR D branch head) |

---

## A0. Verification toolchain

```bash
PYRIGHT_PYTHON_GLOBAL_NODE=off uv run pyright     # pyright 1.1.409
.venv/bin/python -m pytest tests/unit -q -m "not real_run" > /tmp/pytest.log 2>&1; echo $?
.venv/bin/python -m ruff check . && .venv/bin/python -m ruff format --check .
```

**Baseline at `4d608902`:** unit suite `8146 passed, 2 skipped, 1 xfailed`;
pyright `0 errors, 4 warnings`; ruff clean.

Per CLAUDE.md the full suite runs **only from a clean tree**, and the
verdict is taken from pytest's own exit code, never from a pipe's.

---

## 0. Pre-design audit (performed 2026-08-08 against `4d608902`)

The ledger's PR E note gives one binding instruction before anything is
built: *"Check what already exists first (§E.3d.1)."* That audit changes
the shape of this PR substantially, so it comes first and in detail.

### 0.A The five funnel stages, as they exist in code

The stage sequence is `workflows/model_exploration.py::run_workflow`:

```text
:2327   proposal   = _propose_agent.run(propose_input)
:2375   impl_input = local_full_spec(proposal, attempt_storage)
:2412   valid_input= local_all_fields(...)
:2428   validation = _valid_agent.run(valid_input)
:2569   tune_input = local_validated_model(...)          <- PR D's hop
:2665   tune_output= _tune_agent.run(tune_input)
```

**PR E's transport rides exactly the hops PR D just wired and proved.**
`local_validated_model` is the same protocol; the same AST-based
call-site test architecture applies (§E.3d.9). This is the single largest
reason PR E is smaller than the ledger's scope note implies.

### 0.B What each stage already measures — and what it drops

| # | Stage | Parameter count available? | Persisted? | Status |
|---|---|---|---|---|
| 1 | proposal | **YES** — `ProposalOutput.parameter_count_estimate` (`agent/schemas/proposal.py:1042`), LLM-emitted, `int \| None` | on the proposal record | **PRODUCED, NOT FORWARDED.** The field exists on **no** downstream schema. `grep parameter_count_estimate agent/ nodes/ workflows/ core/ execute_tools/` returns the proposer, its prompt text, and nothing else |
| 2 | implementation | **NO** — `ImplementorOutput` carries no count; the implementor emits source, never instantiates | — | genuinely absent |
| 3 | validation | **YES, AND DISCARDED.** `_check_instantiation_and_gradient` instantiates the real model at `ml_code_validator_agent.py:371` (`model = module.PLUGIN_MODEL_CLASS(config)`) and returns only four booleans. `ValidatorOutput` has no numeric field at all | no | **MEASURED FOR FREE, THROWN AWAY** — §E.3d.1 again |
| 4 | preflight / admission | **YES**, two independent surfaces: `ProposalOutput.preflight_estimated_minutes` / `preflight_factor`, and PR B's `HyperparamTuningOutput.physical_rejections` (`PhysicalRejection.binding_cap: Literal["vram","compute_intensity","vram+compute_intensity"]`) | partially | see §0.E |
| 5 | trained | **YES** — `ExperimentRecord.model_params: int \| None` (`hyperparam_tuning.py:371`), populated from `train_engine_sandbox.py:664,1089` | on every record | **already complete** |
| 5b | HealthGate valid | **YES** — gate results on the record; PR D's `scientific_authority` block now also lands there | yes | already complete |

Two further realized-count surfaces exist and are **not** funnel stages,
recorded so a later reader does not mistake them for one:
`isolated_probe.realized_parameter_count` (`agent/skills/evaluate_vram_skill/isolated_probe.py:261`)
and `core/runtime_control/estimate_types.py:208 parameter_count` +
`parameter_count_realized`. Both are **resource-estimation** inputs owned
by PR B, on a different axis from proposal scale. Conflating them would
repeat the `authoritative`-vs-GPU-measurement-authority confusion PR D
had to disentangle in its §0.A.

**Consequence.** Of the five stages, **three already carry the number**
(1, 3-as-instantiation, 5) and one measures it and throws it away. PR E's
real content is therefore *not* "build instrumentation". It is:

```text
1. a join key that does not exist
2. forward stage 1's number past ProposalOutput
3. stop discarding stage 3's number
4. a typed disposition where a candidate is dropped
```

### 0.C Candidate identity — re-verified, still absent

```bash
grep -rn "candidate_id\|proposal_id\|lineage_id\|candidate_uid" \
    agent/schemas/*.py agent/schemas/protocols/*.py
# -> no matches
```

Re-verified at `4d608902`, after PRs A, C and D landed. The ledger's
2026-08-07 finding stands: **no immutable candidate identity exists
anywhere in `agent/schemas/`.**

The funnel cannot be joined on `model_name`, and this is not a
hypothetical: P6.2 established that generated identity and registration
are the fragile region, and PR C had to prove name-keyed reachability
separately. A name is neither guaranteed unique across iterations nor
stable across the five stages.

`exp_id` is **not** a substitute. It identifies an experiment *round
inside the tuner*, is minted long after the proposal, and one candidate
produces many. It cannot label a candidate that died at validation.

### 0.D The narrowest shared transport

Identical in shape to PR D §0.D, and the same answer:

```text
propose -> local_full_spec        -> ImplementorInput
        -> local_all_fields       -> ValidatorInput
        -> local_validated_model  -> HyperparamTuningInput  <- PR D's hop
        -> ExperimentRecord
```

Four protocol hops, all in `agent/schemas/protocols/`, all already
carrying flat scalar fields. The established pattern is a flat optional
field per schema plus a parameter per protocol — exactly what PR D did
for `healthgate_mode` / `result_authority` and what `health_gate_enabled`
did before it.

**A `CandidateProvenance` object is deliberately NOT proposed.** Two
fields (`candidate_id`, and the proposed count being forwarded) do not
warrant a new nested type crossing four boundaries, and §7 of the ledger
rules out repository-wide redesign inside an instrumentation PR.

### 0.E Disposition — what "dropped" means at each stage, in code

This is the least settled part of the audit and the reason **Q-E-2**
exists. Each stage fails differently and there is no single existing
typed vocabulary:

| stage | how a candidate dies today | typed? |
|---|---|---|
| proposal preflight | `preflight_factor` over budget → LLM revision loop; skip conditions add a `PREFLIGHT_SKIPPED:` string to `memo_consistency_notes` | **string prose** |
| implementation | implementor retries, then gives up | exception / retry count |
| validation | `ValidatorOutput.passed=False` plus six booleans naming *which* check failed | **booleans — effectively typed** |
| admission | `PhysicalRejection.binding_cap` `Literal[...]` | **typed** (PR B) |
| tuner round | `ExperimentRecord.failure_stage` / `failure_type` (`:335-336`), `status` `Literal[...]` (`:297`) | **typed** |
| HealthGate | gate results + `formal_validity` | **typed** |

So four of six are already typed and two are not. A new global
disposition enum would create a **second source of truth** beside
`failure_stage` / `failure_type` / `binding_cap` — the exact mistake PR D
avoided by refusing to duplicate `validate_formal_launch`'s refusal
inside the transport.

**Recommended (subject to Q-E-2): record the stage at which the candidate
stopped, and carry the existing typed reason from that stage verbatim.**
Do not invent a new vocabulary.

### 0.F Semantics-neutral naming — the ledger's explicit constraint

> *"Undersizing" is a verdict. Record the measured quantities and let the
> analysis interpret them.*

Binding on every field name in this PR:

```text
ALLOWED    proposed_parameter_count      realized_parameter_count
           parameter_count_delta         stopped_at_stage
FORBIDDEN  undersized  too_small  scale_deficit  size_violation
           is_undersized  severity
```

B2's precedent is exact: it recorded `realized − estimated` and
`realized − threshold` as two separate quantities rather than collapsing
them into one judged number.

### 0.G Where the funnel lives — and why this is an operator decision

Three options, none obviously correct, which is why it is **Q-E-3**:

| option | mechanism | cost |
|---|---|---|
| **A. join-on-read (recommended)** | every stage writes its fields onto records that **already persist**; a read-side helper assembles the funnel by `candidate_id` | no new artifact kind; nothing new to version, migrate or resume |
| B. new per-iteration funnel artifact | `{workspace}/funnel_{run_name}.json` | a new persistent record kind — §15 says that is the operator's call, not the implementer's |
| C. manifest extension | add funnel keys to `run_one_iteration`'s manifest | manifest is a launch/iteration record, not a per-candidate one; one iteration can hold several candidates |

**A is recommended** because it introduces no new artifact and no new
failure mode, and because the ledger's requirement — *"queryable across
iterations without log parsing"* — is satisfied by joining persisted
records, which is what "without log parsing" actually asks for.

### 0.H A stale merge criterion in the ledger — needs resolving (Q-E-1)

The ledger's PR E **Merge criteria** reads:

> Complete funnel on a live iteration; **prompt contradiction resolved**;
> no corrective change to advice or thresholds in the diff.

But the ledger's own **Correction, 2026-08-07** three paragraphs above
says there **is no contradiction** (an encouraged 10-100M range and a
~100M upper bound are consistent), that the real question is a
search-space policy question, and that it is *"not this PR's to answer"*.
The Scope section then explicitly forbids editing the `~100M` prior.

The merge criteria therefore require resolving something the same section
says is not a defect and must not be touched. **Recorded, not
unilaterally deleted** — the ledger is append-only and this is the
operator's to settle.

---

## 1. Objective

> **Make every proposed candidate joinable across all five stages, and
> record the two parameter counts that already exist or are free to
> obtain, so "the agent systematically undersizes" can become a measured
> statement — without correcting anything.**

Explicitly:

- PR E ships the **capability to measure**. Per §E.3d.6 it may **not**
  report a funnel distribution, because none has been collected.
- PR E changes **no** proposer prompt, no advice text, no threshold, no
  admission rule and no size floor.

## 2. Non-goals

```text
NO  corrective action of any kind
NO  edit to the ~100M proposal prior (ledger Scope, explicit)
NO  change to advice text, thresholds, admission or a size floor
NO  scorer / metric / HealthGate-semantic change
NO  new disposition vocabulary competing with failure_stage / binding_cap
NO  CandidateProvenance / RunContext object
NO  claiming a funnel distribution (§E.3d.6)
NO  planner exposure of any new field  (separate evidence + approval)
NO  production-default change            (separate evidence + approval)
```

The last two are called out because the operator's brief names them
explicitly: **planner exposure and production-default changes are outside
the implementation commits.**

## 3. Complete transport contract (post-design)

```text
proposer mints candidate_id
  -> ProposalOutput.candidate_id                        NEW field
     ProposalOutput.parameter_count_estimate            EXISTS :1042
  -> local_full_spec        -> ImplementorInput/Output  NEW param + field
  -> local_all_fields       -> ValidatorInput/Output    NEW param + field
                               + realized_parameter_count  NEW (free at :371)
  -> local_validated_model  -> HyperparamTuningInput     NEW param + field
  -> tuner                  -> ExperimentRecord.candidate_id  NEW
                               ExperimentRecord.model_params  EXISTS :371
```

Per hop, with the failure semantics if the value is absent:

| hop | producer | consumer | ownership | absent ⇒ |
|---|---|---|---|---|
| 1 | proposer | `ProposalOutput` | proposal schema | `None` — a legacy record predating PR E. Must stay distinguishable, per §E.3d.4 |
| 2 | `local_full_spec` | `ImplementorInput` | protocol | `None` propagates |
| 3 | `local_all_fields` | `ValidatorInput` | protocol | `None` propagates |
| 4 | `local_validated_model` | `HyperparamTuningInput` | protocol | `None` propagates |
| 5 | tuner | `ExperimentRecord` | record | `None` — the funnel row is incomplete and **says so** |

**Binding principle 2:** deleting any hop must fail a test. Structurally,
not by substring — §E.3d.9.

**Absence is never defaulted.** A missing `candidate_id` means "this
record predates PR E or the chain was severed", and must never be
replaced by a synthesised id, which would silently create a join that
looks valid and is not.

## 4. Commit plan

| # | Commit | Blocked on | Independently reviewable |
|---|---|---|---|
| **E0** | Audit + design synchronisation (this document) | — | Yes (docs only) |
| **E1** | Pin the current five-stage behaviour before any field is added | — | Yes |
| **E2** | Mint and transport the immutable candidate identity | E1 | Yes |
| **E3** | Stop discarding the realized parameter count at validation | E2 | Yes |
| **E4** | Forward the proposed count and record the stop-stage | E2 | Yes |
| **E5** | Funnel assembly, completeness invariant, backfill evidence | E3, E4 | Yes |

> **Two clauses of the commit template do not apply to PR E, recorded as
> deliberately not-applicable rather than silently skipped.** The
> ordering-specific requirements — *"validate the actual visited
> sample/file sequence"* and *"for the default `shuffle` path, prove that
> selection, random-seed behavior, visited sequence and step count remain
> unchanged"* — belong to a data-ordering feature. PR E touches no
> sampling, ordering, seeding, `file_order` or step-count surface; it adds
> optional scalar fields and a read-side join. **The analogous parity
> obligation for PR E is E1's five-stage behavioural pin plus the
> `None`-everywhere legacy path** (§6). Similarly, the template's
> *"invalid `file_order`, missing files, duplicate files, scope
> mismatches"* edge cases are replaced in §6 of each commit by the
> failure cases PR E actually has: duplicate `candidate_id`, severed
> transport, legacy `None`, and multi-candidate iterations.

---

### Commit E1 — Pin the five-stage behaviour before adding any field

#### 1. Goal

Turn the current end-to-end behaviour of the propose → implement →
validate → tune chain into a regression fixture **before** any new field
exists, so "PR E added instrumentation and changed nothing else" is a
measured claim rather than an assertion made afterwards.

**Why this commit and not another.** Exactly D1's argument, and D1 is the
precedent: a parity claim written *after* a change cannot distinguish
"unchanged" from "changed, and the expectations were written to match the
new behaviour". It must not live in E2, because a test added in the same
commit as the change it guards proves nothing about the before-state.

#### 2. Scope

**Changes**
- `tests/` — one new module pinning the pre-PR-E stage contract.

**Must remain unchanged**
- Every production file. **This commit has no production diff.**

**Non-goals**
- Any new field or transport (E2+).

**Dependencies:** none.

#### 3. Implementation plan

- [ ] Re-read `run_workflow` `:2262-2665` and record the exact call order
      and the protocol function used at each hop
- [ ] Enumerate the **existing** field set of `ProposalOutput`,
      `ImplementorOutput`, `ValidatorOutput`, `HyperparamTuningInput` and
      `ExperimentRecord` and pin each as an **exact key set**, so E2-E4
      adding a field is a deliberate, visible edit to this test
- [ ] Pin `ValidatorOutput`'s current shape explicitly as *"no numeric
      field"* — the fact E3 changes
- [ ] Pin that `parameter_count_estimate` appears on `ProposalOutput` and
      on **no** downstream schema — the fact E4 changes
- [ ] Hardcode every expectation; never read a value back from the schema
      under test (CLAUDE.md)

#### 4. Validation plan

**Unit**
- [ ] Exact-key-set assertions for the five schemas
- [ ] A test naming the two absences E3 and E4 will close

**Integration / pseudo** — none required; these are schema facts.

**Negative / invalid input** — none applicable; no new input is accepted.

**Backward-compatibility / default parity**
- [ ] The existing protocol test modules pass **unmodified**

**Real-training Gate:** none. A GPU cannot evaluate a schema key set.

#### 5. Acceptance criteria

- Five exact key-set assertions exist, written as literals.
- Adding any field in E2-E4 makes **this** module fail until its
  expectation is deliberately updated in that same commit.
- `git diff --name-only` for this commit contains **zero** production files.
- Every pre-existing protocol/schema test passes unmodified.

#### 6. Failure and edge cases

| Case | Required behaviour |
|---|---|
| An existing test already pins part of a key set | Keep both; do not delete the older one to avoid duplication |
| A schema turns out to have a field the audit missed | **Record it as-is and stop.** E1 documents the truth; it never "fixes" a schema |
| A key set is large and churns for unrelated reasons | Record the churn risk; if a set proves unstable, pin only the funnel-relevant subset and say so explicitly rather than silently narrowing |

#### 7. Verification commands and evidence

```bash
.venv/bin/python -m pytest tests/unit/agent/schemas tests/unit/agent/protocols -q
.venv/bin/python -m ruff check . && .venv/bin/python -m ruff format --check .
```

- [ ] New module test count and wall time — **to record**
- [ ] Pre-existing schema/protocol suites unmodified — **to record**
- [ ] Mutations: flip one pinned key set → must fail — **to record**

#### 8. Commit boundary

- [ ] Diff contains test files only; zero production files
- [ ] No new field, no transport
- [ ] Diff summary, staged file list, tests and deviations shown before committing

---

### Commit E2 — Mint and transport the immutable candidate identity

#### 1. Goal

Give every proposed candidate an immutable id at the moment of proposal
and carry it, unchanged, to the persisted experiment record — so the five
stages can be joined at all.

**Why this commit and not another.** It is the enabler: E3, E4 and E5
each write a number that is meaningless without a join key. It is
separated from E3/E4 because identity transport fails for a different
reason than a missing measurement, and a red test should name which.

#### 2. Scope

**Changes**

```text
agent/schemas/proposal.py            ProposalOutput.candidate_id      NEW, optional
agent/schemas/implementor.py         ImplementorInput/Output          NEW, optional
agent/schemas/validator.py           ValidatorInput/Output            NEW, optional
agent/schemas/hyperparam_tuning.py   HyperparamTuningInput            NEW, optional
                                     ExperimentRecord.candidate_id    NEW, optional
agent/schemas/protocols/*.py         four protocol functions          NEW parameter each
nodes/ml_model_proposal_agent/…      mint the id
nodes/ml_hyperparameter_tune_agent/… stamp it onto the record
tests/                               reachability + mutations
```

**Must remain unchanged**
- Every scorer, metric and HealthGate file.
- `core/scientific_authority.py` and PR D's transport.
- Model naming, registration and `MODEL_REGISTRY` behaviour — the id is
  **additive** and must not become a second identity used for lookup.

**Non-goals**
- Any use of `candidate_id` for registration, dispatch or file naming.
  It is a **label**, never a key into behaviour. This is the single most
  important boundary in the PR: P6.2 is about name-keyed fragility, and
  PR E must not add a second name-keyed dependency (the §E.7 review line
  *"Name-keyed dependency added: must be none"* applies literally).

**Dependencies:** E1.

#### 3. Implementation plan

- [ ] Re-read each of the four protocol files immediately before editing
      (CLAUDE.md rule) and follow the flat-optional-parameter pattern PR D
      established at `ml_model_valid_to_ml_model_tune.py:54-55,275-276`
- [ ] Decide the id's generation site and format after inspecting the
      proposer — **do not invent it here.** Requirements: unique per
      proposal, stable across retries of the *same* candidate, and not
      derived from `model_name`
- [ ] Add the field to the five schemas as `str | None = None`, with a
      docstring stating that `None` means "predates PR E or transport was
      severed", never "unknown, substitute one"
- [ ] Add one parameter per protocol function, `default=None`
- [ ] Stamp onto `ExperimentRecord` at the tuner
- [ ] Verify no launcher, registry or file path consumes it

#### 4. Validation plan

**Unit**
- [ ] A minted id arrives unchanged at `ExperimentRecord`
- [ ] An omitted id arrives as `None` at every hop
- [ ] The id is not used in any registry lookup or path construction

**Integration / pseudo**
- [ ] Drive the **real** protocol functions, not a reimplementation —
      B1b's P2 and PR D's M-D3 both survived exactly that mistake

**Negative / invalid input**
- [ ] Two candidates in one iteration receive **different** ids
- [ ] A retried/revised proposal's id behaviour is asserted explicitly
      against whatever Q-E-4 decides (same id vs new id)

**Backward-compatibility / default parity**
- [ ] A record with no `candidate_id` still loads, still scores, still
      resumes — the legacy path
- [ ] E1's key-set pins updated **in this commit**, deliberately

**Real-training Gate:** none proposed. **Not to be launched without
operator approval.**

#### 5. Acceptance criteria

- Given a minted id at the proposer, the persisted `ExperimentRecord`
  carries that exact string.
- Deleting the parameter at **any one** of the four hops makes a test
  fail, and the failure is detected by an **AST call-site assertion**,
  not a substring search (§E.3d.9).
- Given no id, every hop reports `None`; no id is synthesised anywhere.
- `grep` proves `candidate_id` appears in no registry lookup, no
  `MODEL_REGISTRY` access and no filesystem path.
- Two candidates produced in one iteration have distinct ids.

#### 6. Failure and edge cases

| Case | Required behaviour |
|---|---|
| Duplicate `candidate_id` within a run | Must be impossible by construction; if it can occur, **fail loudly at mint time** — a duplicated join key silently merges two candidates' funnels, which is worse than no funnel |
| Legacy record with `candidate_id=None` | Load normally; the funnel row is marked incomplete. **Never** synthesise an id |
| Transport severed at one hop | `None` reaches the record; caught by the hop mutation, not by a runtime error |
| Resume of a pre-PR-E iteration | Unchanged behaviour; no retroactive id (the direct analogue of PR D's non-retroactivity rule) |
| Proposal retried after validation failure | Behaviour set by **Q-E-4**; assert whichever is chosen |
| Multi-candidate iteration | Each candidate distinct; assert with two candidates, not one |

#### 7. Verification commands and evidence

```bash
.venv/bin/python -m pytest tests/unit/agent tests/unit/workflows -q
.venv/bin/python -m pytest tests/unit -q -m "not real_run" > /tmp/pytest.log 2>&1; echo $?
PYRIGHT_PYTHON_GLOBAL_NODE=off uv run pyright
```

- [ ] Reachability module count / wall time — **to record**
- [ ] Four hop-deletion mutations, one per protocol — **to record**
- [ ] Mutation: synthesise an id when absent → must fail — **to record**
- [ ] pyright vs baseline — **to record**

#### 8. Commit boundary

- [ ] Diff touches the five schemas, four protocols, two nodes, tests
- [ ] No scorer, metric or HealthGate file
- [ ] No corrective change to any prompt or threshold
- [ ] Diff summary, staged file list, tests, mutations and deviations shown before committing

---

### Commit E3 — Stop discarding the realized parameter count at validation

#### 1. Goal

Record the parameter count of the model the validator **already
instantiates**, so proposed-vs-realized becomes comparable for every
candidate that reaches validation — including those that never train.

**Why this commit and not another.** It is a distinct causal fact (a
measurement is discarded) from E2's missing join key, and it is the only
stage where the number is available *before* training. Candidates that die
at validation or admission are precisely the ones a funnel needs, and
`ExperimentRecord.model_params` cannot cover them because they never
produce a record.

#### 2. Scope

**Changes**

```text
nodes/ml_code_validator_agent/…   _check_instantiation_and_gradient returns the count
agent/schemas/validator.py        ValidatorOutput.realized_parameter_count  NEW, optional
agent/schemas/protocols/ml_model_valid_to_ml_model_tune.py   forward it
agent/schemas/hyperparam_tuning.py                            carry + stamp
tests/
```

**Must remain unchanged**
- The validator's **verdict**. `passed`, and all six check booleans, must
  be bit-identical for every input. E3 adds an observation; it must not
  become a gate. A model whose parameter count is surprising still passes
  or fails on exactly the criteria it does today.
- The instantiation and gradient logic itself.

**Non-goals**
- Any threshold, warning or rejection based on the count.
- Counting parameters anywhere the model is not already instantiated —
  no new instantiation for measurement.

**Dependencies:** E2 (the count needs the join key to be useful).

#### 3. Implementation plan

- [ ] Re-read `ml_code_validator_agent.py:336-400` immediately before
      editing; the model is instantiated at `:371`
- [ ] Widen the helper's return to include the count, or return a small
      typed result — decide after reading its call site at `:633`
- [ ] Count with `sum(p.numel() for p in model.parameters())`, matching
      the convention already used at `train_engine_sandbox.py:664` and
      `probe_production.py:202`. Record whether total or trainable-only,
      and use the **same** convention as `ExperimentRecord.model_params`
      so the two are comparable — verify which that is before choosing
- [ ] Return `None` when instantiation fails; never `0`
- [ ] Assert the verdict booleans are unchanged for every existing case

#### 4. Validation plan

**Unit**
- [ ] A plugin with a known parameter count reports exactly that count
- [ ] Instantiation failure → `None`, not `0`
- [ ] The convention matches `model_params` (total vs trainable), asserted
      against a plugin containing a **frozen** parameter so the two
      conventions differ observably

**Integration / pseudo**
- [ ] The count survives the protocol into the tuner input

**Negative / invalid input**
- [ ] Import error / config error paths still return the same verdict and
      a `None` count

**Backward-compatibility / default parity**
- [ ] **Verdict parity is the acceptance signal**: every existing
      validator test passes unmodified
- [ ] E1's `ValidatorOutput` key-set pin updated deliberately

**Real-training Gate:** none. The count is available without training.

#### 5. Acceptance criteria

- For a fixture plugin of known size, `ValidatorOutput.realized_parameter_count`
  equals that exact integer.
- Every pre-existing validator test passes **unmodified** — the verdict
  did not move.
- Instantiation failure yields `None`; no code path can produce `0` for a
  model that failed to instantiate.
- The counting convention is documented and **asserted** to match
  `ExperimentRecord.model_params`, proven with a frozen-parameter fixture
  where the two conventions would otherwise disagree.
- No branch anywhere reads the count to make a decision.

#### 6. Failure and edge cases

| Case | Required behaviour |
|---|---|
| Model instantiates, `.parameters()` raises | `None` + the existing verdict unchanged; never crash the validator |
| Model has zero parameters | Record `0` — a real measurement, distinct from `None` (§E.3d.4) |
| Counting is slow for a very large model | Measure it; `numel()` is metadata, not allocation. If it is ever non-trivial, record the measurement rather than adding a cap |
| The count contradicts `parameter_count_estimate` wildly | **Record both. Emit no warning, no verdict.** This is the entire point of the PR |

#### 7. Verification commands and evidence

```bash
.venv/bin/python -m pytest tests/unit/agent/ml_code_validator_agent -q
.venv/bin/python -m pytest tests/unit -q -m "not real_run" > /tmp/pytest.log 2>&1; echo $?
```

- [ ] Validator suite unmodified, count and wall time — **to record**
- [ ] Mutation: return trainable-only instead of total → must fail — **to record**
- [ ] Mutation: return `0` instead of `None` on failure → must fail — **to record**

#### 8. Commit boundary

- [ ] Diff touches the validator node, its schema, one protocol, the tuner, tests
- [ ] No verdict logic changed
- [ ] No decision reads the new number
- [ ] Diff summary, staged file list, tests and deviations shown before committing

---

### Commit E4 — Forward the proposed count and record where a candidate stopped

#### 1. Goal

Carry `parameter_count_estimate` past `ProposalOutput` so it can be
compared with the realized count on the same record, and record **which
stage** a candidate stopped at using each stage's existing typed reason.

**Why this commit and not another.** E3 supplies the realized number;
this supplies the proposed number and the drop reason. Separated because
forwarding an existing field and capturing a disposition fail for
different reasons.

#### 2. Scope

**Changes**

```text
agent/schemas/{implementor,validator,hyperparam_tuning}.py
    proposed_parameter_count            NEW, optional (forwarded, not recomputed)
    stopped_at_stage / stop_reason      NEW, optional — shape depends on Q-E-2
agent/schemas/protocols/*.py            forward both
tests/
```

**Must remain unchanged**
- The proposer's prompt, the `~100M` prior, all advice text — **ledger
  Scope, explicit and absolute.**
- `ProposalOutput.parameter_count_estimate` itself: forwarded verbatim,
  never recomputed, clamped or corrected.
- Every existing typed failure vocabulary — `failure_stage`,
  `failure_type`, `binding_cap`, the validator booleans.

**Non-goals**
- A new disposition enum competing with the above (see §0.E).
- Any judgement field. §0.F's forbidden-names list is binding here.

**Dependencies:** E2. Independent of E3.

#### 3. Implementation plan

- [ ] Forward `parameter_count_estimate` through the same four hops as
      E2, under a name that says what it is (`proposed_parameter_count`)
- [ ] Assert it is **byte-identical** to the proposer's value at every hop
- [ ] Implement the disposition per **Q-E-2**; if the recommendation
      stands, record `stopped_at_stage` plus the existing typed reason
      from that stage, and **do not** define a new reason vocabulary
- [ ] Verify no code path recomputes or adjusts the proposed count

#### 4. Validation plan

**Unit**
- [ ] Proposed count arrives unchanged at the record
- [ ] A candidate stopped at validation records `stopped_at_stage="validation"`
      and the validator's own failure detail
- [ ] A candidate stopped at admission records the existing `binding_cap`

**Integration / pseudo**
- [ ] A pseudo-mode iteration produces one complete row and one row that
      stops early, and both are distinguishable

**Negative / invalid input**
- [ ] `parameter_count_estimate=None` (the documented `PREFLIGHT_SKIPPED`
      case) forwards as `None` and is **not** replaced by an estimate

**Backward-compatibility / default parity**
- [ ] Legacy records with neither field still load and resume
- [ ] The proposer's own behaviour is byte-identical — assert the prompt
      text is unchanged in the diff

**Real-training Gate:** none. **Not to be launched without operator
approval.**

#### 5. Acceptance criteria

- The integer at `ProposalOutput.parameter_count_estimate` and the one on
  the persisted record are **equal**, asserted as the same value, for a
  candidate that completes.
- A candidate that dies at each of validation and admission produces a
  row naming that stage and carrying that stage's **existing** typed
  reason — no new vocabulary appears in the diff.
- `git diff` contains **no** change to any prompt, advice file or
  threshold. Asserted by diff, as PR B and PR D did for the scorer.
- No field name in the diff appears on §0.F's forbidden list.

#### 6. Failure and edge cases

| Case | Required behaviour |
|---|---|
| Proposer omits `parameter_count_estimate` | Forward `None`. The documented skip path already exists; do not fabricate |
| A candidate stops at a stage with no typed reason (implementation) | Record the stage and mark the reason absent. **Do not invent one** |
| A candidate stops at two stages (retry then final failure) | Record the terminal one; assert the behaviour rather than leaving it emergent |
| Proposed and realized differ by orders of magnitude | Record both, judge nothing |

#### 7. Verification commands and evidence

```bash
.venv/bin/python -m pytest tests/unit/agent tests/unit/workflows -q
.venv/bin/python -m pytest tests/unit -q -m "not real_run" > /tmp/pytest.log 2>&1; echo $?
git diff --name-only <base>..HEAD | grep -E 'prompt|advice' || echo "no prompt/advice file touched"
```

- [ ] Forwarding tests count / wall time — **to record**
- [ ] Hop mutations for the proposed count — **to record**
- [ ] Prompt/advice freeze proof — **to record**

#### 8. Commit boundary

- [ ] No prompt, advice or threshold file in the diff
- [ ] No new disposition vocabulary
- [ ] Diff summary, staged file list, tests and deviations shown before committing

---

### Commit E5 — Funnel assembly, completeness invariant, backfill evidence

#### 1. Goal

Provide the read-side join that turns per-stage fields into a funnel, and
prove completeness — no candidate reaches a terminal state with a silently
missing stage.

**Why this commit and not another.** It consumes E2-E4 and adds no
transport. Its failure mode (a join that silently drops rows) is different
from a transport gap, and separating them means a red test names which.

#### 2. Scope

**Changes**
- A read-side assembly helper (location decided by **Q-E-3**).
- `tests/` — completeness and backfill.
- This design document.

**Must remain unchanged**
- Every producer touched by E2-E4. **A diff in one is a finding, not a
  task.**

**Dependencies:** E3, E4.

#### 3. Implementation plan

- [ ] Implement assembly per Q-E-3 (option A recommended: join persisted
      records on `candidate_id`, no new artifact)
- [ ] A candidate with a missing stage is reported as **incomplete with
      the stage named** — never dropped, never defaulted
- [ ] Backfill check: run the assembler over **stored** attempt-3 records
      and confirm it reproduces the parameter distribution the ledger
      already records (663,488 - 12,772,096), **without** claiming any new
      distribution (§E.3d.6)
- [ ] Add no aggregate, mean, ratio or verdict to the output

#### 4. Validation plan

**Unit**
- [ ] Complete candidate → all five stages present
- [ ] Candidate missing a stage → reported incomplete, stage named
- [ ] Two candidates in one iteration do not merge

**Integration / pseudo**
- [ ] One pseudo-mode iteration yields a complete funnel row

**Negative / invalid input**
- [ ] Records with `candidate_id=None` are grouped as **unjoinable**, not
      merged into one pseudo-candidate — the most dangerous possible bug
      in this commit

**Backward-compatibility / default parity**
- [ ] Backfill over stored records changes nothing on disk (read-only)

**Real-training Gate:** the ledger asks for *"one iteration produces a
complete funnel record"*. **Pseudo-mode is sufficient and is what this
design proposes**; a real iteration is listed as optional strengthening
evidence and **must not be launched without operator approval.**

#### 5. Acceptance criteria

- For a fixture of three candidates — one complete, one stopped at
  validation, one legacy with `candidate_id=None` — the assembler returns
  exactly three rows: complete, incomplete-named-at-validation, and
  unjoinable. **Not two, and never one merged row.**
- The backfill reproduces the ledger's recorded attempt-3 range from
  stored records.
- The output contains no aggregate and no judgement field.
- No producer file appears in the diff.

#### 6. Failure and edge cases

| Case | Required behaviour |
|---|---|
| Several records share a `candidate_id` (retry rounds) | Expected — one candidate has many tuner rounds. The funnel row is per **candidate**; assert the fan-in explicitly |
| `candidate_id=None` on several legacy records | Each stays separate and unjoinable. Merging them is the failure this commit must make impossible |
| Stage present but its number absent | Distinguish "stage not reached" from "stage reached, number absent" — §E.3d.4's four-state rule |
| Zero candidates | Empty result, not an error |

#### 7. Verification commands and evidence

```bash
.venv/bin/python -m pytest tests/unit/execute_tools tests/unit/agent -q
.venv/bin/python -m pytest tests/unit -q -m "not real_run" > /tmp/pytest.log 2>&1; echo $?
```

- [ ] Completeness tests count / wall time — **to record**
- [ ] Backfill result vs the ledger's recorded range — **to record**
- [ ] Mutation: merge `None`-id records → must fail — **to record**
- [ ] Clean-tree full suite, pytest rc, counts — **to record**

#### 8. Commit boundary

- [ ] Read-side + tests + this document only
- [ ] No producer file in the diff
- [ ] No aggregate, distribution claim or corrective change
- [ ] Diff summary, staged file list, tests and deviations shown before committing

---

## 5. Validation ladder

| Layer | Commit | What it proves |
|---|---|---|
| A | E1 | five-stage behaviour pinned **before** any field exists |
| B | E2 | identity reaches the record through the **real** protocols |
| C | E2-E4 | every hop is load-bearing — AST call-site assertions, not substring (§E.3d.9) |
| D | E3-E4 | the two numbers are recorded, and no decision reads them |
| E | E5 | the join is complete, and unjoinable rows stay unjoinable |
| F | all | PR-level mutation account, by category, never a percentage |

**Layer G — production-boundary evidence.** Assessment: **no GPU or LLM
Gate is required.** Every property is reachable deterministically —
identity transport is in-process typed plumbing, the validator count needs
no training, and the join is read-side. The residual, stated rather than
papered over: no deterministic fixture drives a *real* proposer, so the
mint site is covered by a call-site test plus a mutation. A pseudo-mode
iteration is the cheapest sufficient live confirmation and is proposed as
**optional**, exactly as PR D's O-D-2 concluded.

**The scientific outcome is never the oracle.** A candidate proposing
600k parameters is not a test failure.

## 6. Backward compatibility / parity

| invariant | how it is preserved |
|---|---|
| pre-PR-E records | all new fields optional, `None`; no retroactive id — the direct analogue of PR D's non-retroactivity rule |
| validator verdicts | E3's acceptance signal is that every existing validator test passes **unmodified** |
| proposer behaviour | no prompt, advice or threshold file in the diff, proved by diff |
| scoring | no scorer/metric/SNR file in the diff, proved by diff |
| HealthGate | untouched |
| model registration | `candidate_id` is a label, never a lookup key — grep-proved |

## 7. Genericization review

- **Does the touched code treat one task or campaign as the framework?**
  No. `candidate_id` and parameter counts are task-agnostic.
- **Literals.** No model name, campaign name or size constant is
  introduced. The `~100M` prior stays exactly where it is, untouched.
- **Bounded genericization performed:** none required — the change
  follows the flat-optional-field-plus-protocol-parameter pattern PR D
  established in the same protocol files.
- **Deliberately deferred:** a `CandidateProvenance` object carrying
  identity, lineage and scale together. Justified only if a third or
  fourth per-candidate fact needs the same route.

## 8. Acceptance and merge criteria

1. Every candidate that reaches the proposer receives an immutable id
   that arrives unchanged at the persisted record.
2. All four transport hops are load-bearing, proved by AST-anchored
   mutations.
3. The realized parameter count is captured where the model is already
   instantiated, and the validator's verdict is bit-identical.
4. The proposed count is forwarded verbatim and never recomputed.
5. A candidate stopped at any stage records that stage and its existing
   typed reason; no new vocabulary is introduced.
6. The funnel assembles per candidate, names incomplete stages, and never
   merges unjoinable records.
7. **No distribution is claimed** (§E.3d.6). PR E delivers the capability.
8. No prompt, advice, threshold, scorer, metric or HealthGate file is in
   the diff.
9. Full configured CI passes **in addition to** PR E's own reachability
   and mutation evidence.

### V21 review fields

```text
Metric-frozen proof:      to be verified by diff at merge — PR E touches no
                          scoring path

Name-keyed dependency
added:                    MUST BE NONE. candidate_id is a label, never a key
                          into registration, dispatch or paths. Grep-proved in
                          E2's acceptance — this is the review line PR E is
                          most at risk of violating

Transport contract:       field:    candidate_id, proposed_parameter_count,
                                    realized_parameter_count, stopped_at_stage
                          producer: ml_model_proposal_agent (mint)
                          boundaries: local_full_spec -> local_all_fields
                                      -> local_validated_model -> ExperimentRecord
                          consumers: read-side funnel assembly only
                          branches: complete / stopped-early / legacy-None

Subprocess evidence:      to be determined — the validator's instantiation and
                          the tuner's training both cross process boundaries;
                          confirm during E3 whether the count crosses one

Acceptance evidence:      Layers A-F deterministic; Layer G argued unnecessary
                          with the residual stated
```

---

## Operator decisions required — NONE RESOLVED, implementation blocked

### Q-E-1 — The ledger's PR E merge criteria contradict its own Scope

**Question.** Merge criteria say *"prompt contradiction resolved"*; the
Correction three paragraphs above says there is no contradiction and the
`~100M` prior must not be edited (§0.H).

**Options.** (a) Strike the clause as superseded by the 2026-08-07
correction — my recommendation, since the correction is the later and
more specific statement. (b) Keep it and define what "resolved" means
without editing the prior. (c) Re-open the search-space policy question
as its own PR.

**Recommendation: (a)**, recorded as a dated correction in the
append-only ledger, exactly as §E.3e was.

### Q-E-2 — Disposition vocabulary

**Question.** Four of six stages already have typed failure reasons
(`failure_stage`, `failure_type`, `binding_cap`, the validator booleans);
two do not (proposal preflight uses prose in `memo_consistency_notes`;
implementation uses exceptions).

**Options.** (a) Record `stopped_at_stage` and carry each stage's existing
reason verbatim — my recommendation; no second source of truth.
(b) Define a new global disposition enum — competes with three existing
vocabularies. (c) Type the two untyped stages as part of PR E — real
scope growth into the proposer and implementor.

**Recommendation: (a).** (c) is a defensible follow-up but would enlarge
an instrumentation PR into a refactor of two nodes.

### Q-E-3 — Where the funnel lives

**Question.** Join-on-read over existing records, a new per-iteration
artifact, or a manifest extension (§0.G).

**Recommendation: A, join-on-read.** B introduces a new persistent record
kind, which §15 of the working rules makes an operator decision rather
than an implementer's, and adds a resume/versioning surface for no
measurement benefit.

### Q-E-4 — Identity across proposal revisions

**Question.** The proposer has a preflight revision loop and the
implementor retries. Is a revised draft the **same** candidate (same id,
funnel shows revisions) or a **new** one (new id, funnel shows N attempts)?

**Why this is genuinely the operator's.** It determines what "a candidate"
*means* in the eventual distribution — whether the funnel counts drafts or
accepted proposals. That is a measurement-definition question, and getting
it wrong makes the data uninterpretable in a way no test can catch.

**No recommendation offered.** I can supply the code facts about where
revisions occur, but the definition should be the operator's.

---

**Nothing in this document is implemented.** On approval the sequence is
E0 (this document) → E1 → E2 → E3 → E4 → E5, and Q-E-2, Q-E-3 and Q-E-4
must be answered first because they change E4, E5 and E2 respectively.
