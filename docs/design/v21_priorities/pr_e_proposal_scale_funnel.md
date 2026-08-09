# PR E — Proposal-scale funnel instrumentation

**Status: DESIGN APPROVED 2026-08-08 (operator) — O-E-6 resolved as (c),
FINAL text in §0.I. No further design review required. Implementation
authorized as E0 → E1 → E2 → E3 → E4, to begin only after PR #189 is
restored to its D-only branch, merged, and this branch is updated onto
the merged master. Nothing implemented yet.**

Revision 2 applied operator decisions **O-E-1 … O-E-5** and the
persistence audit they required, shrinking the PR to four commits with
`candidate_id` as the only cross-stage transport. Revision 3 applied the
operator's three design corrections (DC-1 … DC-3); its O-E-6 pre-E3 audit
hit the STOP condition (the proposal contract explicitly says
"trainable"), and the operator resolved it as **option (c): record both
conventions at validation**, frozen below.

Branch note: PR E work lives on `feat/pr-e-proposal-scale-funnel`,
split off the PR D branch per the operator's operational requirement.

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
| **O-E-6 FINAL** | record **BOTH** conventions at validation (option c); proposal contract (trainable estimate) authoritative and unchanged; `model_params` unchanged; no cross-convention delta/ratio anywhere | E3 unblocked and rewritten for two fields with unambiguous names; frozen text in §0.I |
| **DC-1** | every persisted `candidate_id` producer must be proved, not assumed | audit done (§0.J): **no generic echo exists**; the implementor (2 construction sites) and validator (1) must explicitly echo — both nodes added to E2's scope. Mint rule frozen (§0.J) |
| **DC-2** | one pseudo-mode complete iteration is a **MERGE REQUIREMENT** | E4 §4 and Layer G reconciled — the contradiction is resolved in favour of required |
| **DC-3** | legacy attempt-3 check is a **stage-local sanity check**, never a "reconstructed funnel"; no name-keyed join ever | E4 renamed and reworded; a mutation polices the name-join |

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
ALLOWED    parameter_count_estimate      realized_total_parameter_count
           realized_trainable_parameter_count
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

### 0.I O-E-6 pre-E3 audit — the STOP condition fired

O-E-6 required auditing `parameter_count_estimate`'s actual semantic
contract before E3, with: *"If that contract explicitly means
trainable-only, STOP and report the evidence."* **It does, in two places.**

| source | wording | verdict |
|---|---|---|
| schema description, `agent/schemas/proposal.py:1044` | *"LLM-emitted estimate of the **total trainable** parameter count for baseline_config"* | explicit "trainable" |
| proposer prompt hard constraint, `ml_model_proposal_agent.py:378-380` | *"your best estimate of the **total trainable** parameter count at the baseline_config"* | explicit "trainable" |
| consumer, `agent/utils/proposer_preflight.py:118-121` | static formula `num_params × seg × bs × 6e-10`, order-of-magnitude | **convention-insensitive** |
| `docs/reliable_resource_proposer.md` Decision 5 | no convention language at all (`grep trainable` → empty) | unspecified |
| FCNet ~323M reference; recorded attempt ranges 663,488-12,772,096 | from-scratch models: every parameter is trainable, so **total == trainable** on all recorded values | indistinguishable |

**Honest characterisation:** the word "trainable" is explicit but appears
incidental, not load-bearing — the only consumer is order-of-magnitude
insensitive, the design doc that introduced the field specifies no
convention, and on every model the system has ever produced the two
conventions are numerically identical (the difference is observable only
with frozen parameters). But O-E-6 drew the line at *explicit*, so this
returns to the operator rather than being decided here.

**Options** (PR E may not edit the prompt, so re-wording the constraint is
out of scope regardless):

```text
(a) O-E-6 stands: validator records TOTAL. The proposal estimate stays
    nominally trainable; the funnel labels both conventions explicitly
    and never computes a cross-convention delta. The nominal mismatch is
    honest and, on from-scratch models, numerically vacuous.
(b) Validator records TRAINABLE-only — matching the PROPOSAL contract
    (grounds independent of model_params, which O-E-6 rightly rejected
    as a reason). Architecture size is then not measured anywhere.
(c) Validator records BOTH totals: realized_parameter_count (total) AND
    realized_trainable_parameter_count. Two sums over one already-
    instantiated model; each funnel column then has a like-for-like
    partner: proposal-estimate <-> trainable; architecture <-> total;
    model_params stays untouched.
```

**Recommendation: (c).** It implements O-E-6's own reasoning — *"these
can simultaneously both be real measurements"* — at the cost of one extra
optional field, and dissolves the conflict instead of picking a side.

**RESOLVED — operator chose (c), 2026-08-08. O-E-6 FINAL, frozen:**

```text
ProposalOutput.parameter_count_estimate
    = estimated TRAINABLE parameter count      [existing contract; UNCHANGED]

ValidatorOutput.realized_total_parameter_count
    = TOTAL parameters of the instantiated implementation
    = sum(p.numel() for p in model.parameters())

ValidatorOutput.realized_trainable_parameter_count
    = TRAINABLE parameters of the instantiated implementation
    = sum(p.numel() for p in model.parameters() if p.requires_grad)

ExperimentRecord.model_params
    = TRAINABLE parameters                     [existing semantics; UNCHANGED]
```

The ambiguous name `realized_parameter_count` is **not used** — the
convention is in the field name, so no future reader needs this document
to know it. All four are distinct stage-native observations; nothing is
forwarded downstream to make one record complete. The read-side assembler
exposes convention-explicit labels (display labels only — **no schema
rename** of the existing proposal field):

```text
proposed_trainable_parameter_count_estimate    <- ProposalOutput.parameter_count_estimate
implemented_total_parameter_count              <- validator total
implemented_trainable_parameter_count          <- validator trainable
trained_trainable_parameter_count              <- ExperimentRecord.model_params
```

Like-for-like relations: proposed-trainable ↔ implemented-trainable, and
implemented-trainable ↔ trained-trainable; implemented-total stands alone
as architecture size. **PR E computes no delta or ratio across unlike
conventions** — a future analysis may, explicitly, on same-convention
quantities.

### 0.J DC-1 producer audit — no generic echo exists; two nodes join E2

The operator's suspicion is **confirmed**: a schema field would not have
reached the persisted JSONs. Every output is explicitly constructed, and
no `model_copy`/generic-echo mechanism exists in either node:

```text
ProposalOutput      built by model_validate(raw-LLM-dict) at
                    ml_model_proposal_agent.py:1389 (legacy) and the
                    pipeline equivalent (:1998); persisted at :1341
ImplementorOutput   explicitly constructed at ml_model_implementor.py:1657
                    (Branch B plugin-reuse) AND :1804 (normal path);
                    persisted at :1821
ValidatorOutput     explicitly constructed at ml_code_validator_agent.py:625
                    (echoes model_type=inp.model_type by hand — the
                    pattern candidate_id follows); persisted at :683
```

Consequences, binding on E2:

- **The implementor and validator nodes are IN E2's scope.** Each must
  explicitly echo `candidate_id` from its input to its output — the
  implementor at **both** construction sites, including Branch B reuse
  (a reused plugin still belongs to the current candidate).
- **The transport test starts at the real system-generated mint and ends
  at every persisted native artifact** — all three stage JSONs plus the
  `ExperimentRecord` — not at schema construction.
- Each echo site is a mutation target: dropping any one must fail a test.

**Mint rule — FROZEN (operator, 2026-08-08):**

> `candidate_id` is SYSTEM-GENERATED, after the LLM proposal JSON has been
> parsed and before `ProposalOutput` is persisted. It is never
> LLM-generated and never derived from `model_name`.

The audit adds the implementation consequence: `run()` at
`ml_model_proposal_agent.py:1333` (`output = self._run_pipeline(inp) if
has_pipeline else self._run_legacy(inp)`, then persist) is the **single
site covering both modes** — minting there covers legacy and pipeline
paths with one edit and cannot be bypassed by either. A test must assert
the id is absent from the raw LLM dict's accepted keys, so a
prompt-injected id can never survive parsing.

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
parameter_count_estimate              proposal stage   proposal_{run_name}.json
preflight_factor                      proposal stage   proposal_{run_name}.json
realized_total_parameter_count        validator stage  validation_{run_name}.json  (E3)
realized_trainable_parameter_count    validator stage  validation_{run_name}.json  (E3)
model_params                          tuner            ExperimentRecord
stop stage / reason                   DERIVED ON READ  no schema field at all
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

- [x] Re-read `run_workflow` `:2214-2428`; attempt loop `:2215`, temp dir
      `:2220`, rename `:2333-2335`; `iter_dir =
      {workspace}/{run_name}/iteration_{NNN}` (`:1690`, `:2050`)
- [x] Key sets pinned in
      `tests/unit/agent/schemas/test_pr_e_stage_contract_pins.py` —
      **exact literal sets** for the five proposal-chain schemas
      (`ProposalOutput` 17, `ImplementorInput` 17, `ImplementorOutput` 10,
      `ValidatorInput` 13, `ValidatorOutput` 22). **Deviation, recorded:**
      `HyperparamTuningInput` (68 fields) and `ExperimentRecord` (53) are
      pinned on funnel-relevant presence/absence facts only, invoking the
      §6 churn clause explicitly — a full pin there would tax every
      unrelated PR. Also pinned: `candidate_id` absent from all seven
      schemas (the E2 before-state); `stopped_at_stage` stored nowhere
      (O-E-2); `parameter_count_estimate` on `ProposalOutput` only and
      `model_params` on the record (O-E-3 ownership)
- [x] `ValidatorOutput` pinned as having **no numeric field** (exact
      22-key set + a type-level scan), plus explicit absence pins for
      both E3 field names
- [x] Persistence pinned as behaviour in
      `tests/integration/workflows/test_pr_e_persistence_layout_pseudo.py`:
      all three nodes driven through their REAL `run()` with bridge-level
      mocks (canonical fixtures imported from the owning node test
      modules, the established cross-import pattern); each writes
      `{stage}_{run_name}.json` into the given workspace
- [x] Two attempts (validation fail → new proposal via
      `max_impl_attempts=1`) produce `attempt_001_alpha_net` +
      `attempt_002_beta_net`, neither overwritten, both matched by a
      name-blind `attempt_*` glob
- [x] Inner-retry overwrite pinned: two implementor runs with one storage
      leave exactly one `implementor_{run}.json` holding the TERMINAL
      outcome — E4 must never infer retry counts from artifacts
- [x] Every expectation hardcoded; nothing read back from the thing under
      test

#### 4. Validation plan

**Unit**
- [x] Five exact key-set assertions + the ownership pins — 16 tests
      across the two modules, `16 passed in 2.10s`
- [x] `ValidatorOutput` has no numeric field

**Integration / pseudo**
- [x] Two simulated attempts produce two directories, both discoverable by
      a `attempt_*` glob, neither overwriting the other

**Negative / invalid input**
- [x] **Moved to E4, recorded as a deviation** — "empty workspace yields
      empty discovery" is a property of the assembler, which does not
      exist until E4 (already listed in E4 §6 as "zero candidates").
      Cannot be tested before the reader exists
- [x] Two fixture defects found against real shapes and fixed:
      `LLMCodeReview.spec_alignment` is a bool (my mock said `"ok"`), and
      `run_workflow` Step 0 loads
      `{data_dir}/{model}/{source}/agent/run_output_{source}_agent.json`
      BEFORE any (mocked) agent runs — the layout test must seed it

**Backward-compatibility / default parity**
- [x] Neighbouring suites pass unmodified: schemas + all three node
      suites `1112 passed in 4.66s`

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

- [x] `16 passed in 2.10s` (both modules)
- [x] Neighbouring suites unmodified: `1112 passed in 4.66s`
- [x] Mutations — **5 attempted, 4 behaviour-changing → 4 caught,
      1 equivalent → classified**:

      | # | mutation | result |
      |---|---|---|
      | M-E1-1 | `ValidatorOutput` silently gains `candidate_id` | CAUGHT (2 failures) |
      | M-E1-2 | `ValidatorOutput` silently gains a numeric field | CAUGHT (2 failures) |
      | M-E1-3 | temp `attempt_dir` collapsed to a constant | **EQUIVALENT** — the rename target (`attempt_{N:03d}_{name}`) owns the final layout; the temp name is renamed away every attempt |
      | M-E1-3v2 | the RENAME's attempt numbering collapsed to a constant | CAUGHT |
      | M-E1-4 | rename drops the name-blind `attempt_` prefix | CAUGHT |

#### 8. Commit boundary

- [x] Tests only; zero production files (commit `337b9945`)
- [x] No field, no transport, no assembly
- [x] Two new test modules; deviations in §3/§4. **Process slip,
      recorded:** the ledger update aborted on a stale anchor and E1's
      commit landed with these boxes still open; fixed in the next docs
      commit rather than by history rewrite. Root cause was editing this
      document from memory instead of re-reading it — the exact rule-5
      violation the mandate names

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
nodes/ml_model_proposal_agent/…      mint (single site in run(), §0.J)
nodes/ml_model_implementor/…         explicit echo, BOTH construction
                                     sites (:1657 Branch B reuse, :1804)
nodes/ml_code_validator_agent/…      explicit echo (:625)
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

- [x] Re-read every file immediately before editing. **Deviation
      (smaller, category: mechanism already exists):** the protocols take
      the WHOLE upstream objects, so the design's "one parameter per
      protocol function" was unnecessary — the id travels inside the
      objects and each protocol maps it field→field
      (`candidate_id=output.candidate_id`) from its **immediate**
      upstream, so severing any echo is visible end to end. Zero new
      protocol parameters; zero `run_workflow` changes
- [x] Minted in `run()` after `_run_legacy`/`_run_pipeline` return,
      before the persist: `output.candidate_id = f"cand_{uuid.uuid4().hex}"`
      — UNCONDITIONAL assignment, so even a value smuggled past a parser
      whitelist is overwritten. uuid4 makes duplicates impossible by
      construction (no explicit collision check needed)
- [x] Asserted: a `candidate_id` in the raw LLM commit JSON does not
      survive (`test_the_llm_cannot_supply_the_id`) — both parser
      whitelists (`:1401` legacy, `:2010` pipeline) exclude it AND the
      mint overwrites
- [x] Implementor echoes at BOTH sites — normal (`:1804` region) and
      Branch-B plugin reuse (`:1657` region, "a reused plugin still
      belongs to the CURRENT candidate"). **M-E2-7 initially SURVIVED**
      because no test drove Branch B; fixed by adding
      `TestBranchBReuseEcho` (test architecture, not the mutation), after
      which it is caught
- [x] Validator echo at `:625`, beside the hand-echoed `model_type`
- [x] Schemas: **eight** fields, not five — the five planned
      (`ProposalOutput`, `ImplementorInput/Output`,
      `ValidatorInput/Output`) plus `HyperparamTuningInput`,
      `ExperimentRecord`, and — bounded extension, recorded —
      `HyperparamTuningOutput`, echoed on BOTH exit paths exactly like
      the `healthgate_mode` echo it sits beside, because the degraded
      exit would otherwise make crashed candidates silently unjoinable
- [x] Superseded (see first item): no protocol parameters exist to add
- [x] Stamped at the `_emit_record` validate-and-persist seam — the
      structural choke point (13 callers, one function) — via a new
      keyword `candidate_id: str | None = None`; all 12 production call
      sites pass it explicitly (8 in `run()` directly; 2 helpers already
      held `agent_input`; `_handle_admission_refusal` and
      `_handle_in_subprocess_rejection` gained a threaded parameter).
      Also echoed in the run-provenance stamp dict (`run_config`), same
      cannot-disagree argument as D-C1a
- [x] Verified by grep AND by behaviour: no registration, dispatch,
      admission, scoring or path construction reads it;
      `TestNoBehaviouralKeyUsage` pins five sensitive files, and the
      behavioural-inertness tests prove identical outputs under two ids

#### 4. Validation plan

**Unit**
- [x] The minted id reaches `HyperparamTuningInput` AND all three
      persisted stage JSONs (`test_minted_id_reaches_the_tuner_input_and_every_artifact`);
      `_emit_record` stamps it onto the record
      (`test_emit_record_stamps_the_id_before_validate_and_persist`)
- [x] `None` propagates at every hop; `_emit_record(candidate_id=None)`
      keeps `None` — nothing synthesised (mutation M-E2-9 police this)
- [x] Two proposer runs mint different ids (O-E-4)
- [x] Same-`ProposalOutput` retries keep the id trivially — it rides
      inside the object; the Branch-B test and the E4 Gate exercise it

**Integration / pseudo**
- [x] Every hop is the REAL production function: real proposer/implementor/
      validator `run()` bodies (bridge-level mocks) + the three real
      protocols. **A new finding this surfaced:** the fixed-plan seam
      (`load_validation_fixed_candidate_plan`) computes its unknown-key
      refusal from `ProposalOutput.model_fields`, so adding the field
      SILENTLY REMOVED `candidate_id` from that refusal — an operator
      plan could then have smuggled an identity nobody minted. Closed
      with an explicit refusal in the loader (same-causal-scope
      discovery; mutation M-E2-12), and a clean plan now loads with
      `candidate_id=None` — a fixed-plan candidate is deliberately
      id-less, per O-E-4

**Negative / invalid input**
- [x] Duplicates impossible by construction (uuid4); no collision branch
      exists to test — recorded as the §6 resolution

**Backward-compatibility / default parity**
- [x] A record with no `candidate_id` loads (`test_a_pre_pr_e_record_still_loads`);
      the broad sweep (below) proves scoring/resume paths unchanged
- [x] No retroactive id: nothing writes the field outside the mint, the
      echoes and the stamp — all forward-only
- [x] E1's key-set pins updated in this commit, deliberately (each set
      +`candidate_id`; the absence test became
      `TestTheFactsE2Changed.test_candidate_id_present_on_every_hop_schema`,
      which also pins `default=None` on all eight schemas)

**Real-training Gate:** none proposed. **Not to be launched without
operator approval.**

#### 5. Acceptance criteria

- Given a minted id at the proposer, that exact string is present in
  **all four persisted artifacts**: `proposal_{run}.json`,
  `implementor_{run}.json`, `validation_{run}.json` and the
  `ExperimentRecord` — the transport test starts at the real mint and
  ends on disk (§0.J), not at schema construction.
- Deleting the parameter at any protocol hop, **or the echo at any of the
  three node construction sites** (implementor ×2 incl. Branch B,
  validator ×1), fails a test — AST call-site assertions
  (`ast.Name` of the same id), not substring searches.
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

- [x] `tests/unit/agent/protocols/test_pr_e_candidate_id_transport.py`:
      `16 passed in 2.33s`; all three PR E modules together
      `31 passed in 2.93s`
- [x] Mutations — **13 attempted, 13 behaviour-changing → 13 caught,
      0 equivalent** (M-E2-7 caught only after a test-architecture fix):

      | # | mutation | result |
      |---|---|---|
      | M-E2-1 | mint removed | CAUGHT (4 failures) |
      | M-E2-2 | mint derived from `model_name` | CAUGHT |
      | M-E2-3 | propose→impl hop severed | CAUGHT |
      | M-E2-4 | impl→valid hop severed | CAUGHT |
      | M-E2-5 | valid→tune hop severed | CAUGHT |
      | M-E2-6 | implementor normal echo severed | CAUGHT |
      | M-E2-7 | implementor **Branch-B** echo severed | **SURVIVED round 1** — no test drove the reuse path; `TestBranchBReuseEcho` added; **CAUGHT on rerun**. The exact §0.J prediction: every explicit echo is its own mutation target |
      | M-E2-8 | validator echo severed | CAUGHT (2 failures) |
      | M-E2-9 | record stamp synthesises when absent (`or "cand_synth"`) | CAUGHT |
      | M-E2-10 | record stamp removed | CAUGHT |
      | M-E2-11 | one `_emit_record` call site forgets the id | CAUGHT (the AST all-12-sites test) |
      | M-E2-12 | fixed-plan `candidate_id` refusal removed | CAUGHT |
      | M-E2-13 | output echo dropped from the healthy dict | CAUGHT |

- [x] Synthesise-when-absent = M-E2-9, caught
- [x] Id reuse across runs is structurally impossible (fresh uuid4 per
      `run()`); the two-runs test pins distinctness; a "reuse" mutation
      would be M-E2-2's shape and is covered by it — recorded rather
      than duplicated
- [x] LLM-supplied id = M-E2-1/M-E2-2 territory plus the dedicated
      `test_the_llm_cannot_supply_the_id`; the parser whitelists never
      accepted the key (verified at `:1401` and `:2010`)
- [x] pyright `0 errors, 4 warnings` — baseline held
- [x] **Collateral suite repair, classified (rule 15):** the broad sweep
      (`tests/unit/{agent,sdsc,nodes,core}`: `6446 passed` after fixes)
      surfaced 14 failures, ALL test-fixture defects from E2's new
      surface, none production: (a) `test_prephase_measurement_reachability`'s
      stub `_Input` lacked `candidate_id` (13 tests) — field added to the
      stub; its `_emit_record` stub lambda widened to accept `**kw`;
      (b) `test_realized_vs_admitted_memory` anchored on the exact old
      call text `_emit_record(sandbox, final_record)` — a brittle
      substring of the §E.3d.9 kind; relaxed to the stable prefix so the
      guarded property (attach-before-emit) stays pinned

#### 8. Commit boundary

- [x] Diff: 4 schema files (8 fields), 3 protocols, 3 nodes (proposer
      mint, implementor ×2 echoes, validator echo), the tuner
      (`_emit_record` + 12 sites + 2 helper signatures + 3 dict echoes),
      the fixed-plan loader guard, tests
- [x] No scorer, metric, HealthGate or registration file
- [x] No measurement forwarded — this commit moves **only** the id
- [x] Recorded in §3/§4/§7 above

---

### Commit E3 — Capture both parameter-count views of the instantiated model

#### 1. Goal

Record **both parameter-count views** available from the model the
validator **already instantiates** — total (architecture size) and
trainable (training exposure) — on the validator's own output, per
O-E-6 FINAL. Two sums over one `.parameters()` traversal; no new
instantiation. Every candidate that reaches validation gets both numbers,
including candidates that never train.

**Why this commit and not another.** It is a distinct causal fact — a
measurement computed and thrown away — from E2's missing join key, and it
is the only stage where the number exists *before* training.
`ExperimentRecord.model_params` cannot cover candidates that die at
validation or admission, because they never produce a record.

**Independent of E2**: it adds two fields to one schema and forwards
nothing. It is ordered after E1 only for the key-set pin.
**UNBLOCKED — O-E-6 FINAL (option c), frozen in §0.I.**

#### 2. Scope

**Changes**

```text
nodes/ml_code_validator_agent/…   _check_instantiation_and_gradient returns both counts
agent/schemas/validator.py        ValidatorOutput.realized_total_parameter_count      NEW, optional
                                  ValidatorOutput.realized_trainable_parameter_count  NEW, optional
tests/
```

**No protocol changes. No downstream schema changes.** Per O-E-3 the
validator is the canonical owner and `validation_{run_name}.json` is where
both numbers live.

**Must remain unchanged**
- **The validator's verdict.** `passed` and all six check booleans must be
  bit-identical for every input. E3 adds an observation; it must not
  become a gate.
- The instantiation and gradient logic itself.

**Non-goals**
- Any threshold, warning or rejection based on either count.
- Instantiating a model anywhere it is not already instantiated.
- Forwarding either count anywhere.
- Any delta/ratio between unlike conventions, anywhere.

**Dependencies:** E1.

#### 3. Implementation plan

- [ ] Re-read `ml_code_validator_agent.py:336-400` and its call site at
      `:633` immediately before editing; the model is instantiated at `:371`
- [ ] Widen the helper's return, or return a small typed result — decide
      after reading the call site, not before
- [ ] Compute both counts per O-E-6 FINAL, on the SAME traversal of the
      already-instantiated model:
      `realized_total_parameter_count = sum(p.numel() for p in model.parameters())`;
      `realized_trainable_parameter_count = sum(... if p.requires_grad)`.
      `ExperimentRecord.model_params` is untouched and un-redefined. No
      code computes a delta or ratio across unlike conventions
- [ ] Return `None` for both when instantiation fails; never `0`
- [ ] Assert the verdict booleans are unchanged for every existing case

#### 4. Validation plan

**Unit**
- [ ] A plugin of known size reports exactly those integers (both fields)
- [ ] Instantiation failure → both `None`, never `0`
- [ ] **Frozen-parameter fixture (required by O-E-6 FINAL):** a plugin
      with a frozen parameter, where total and trainable observably
      differ, pins **both fields independently** — total counts the
      frozen parameter, trainable does not — and asserts nothing anywhere
      computes a delta or ratio across unlike conventions

**Integration / pseudo**
- [ ] Both counts are present in the persisted `validation_{run_name}.json`

**Negative / invalid input**
- [ ] Import error and config error paths return the same verdict and
      `None` for both counts

**Backward-compatibility / default parity**
- [ ] **Verdict parity is the acceptance signal:** every existing
      validator test passes **unmodified**
- [ ] E1's `ValidatorOutput` key-set pin updated deliberately

**Real-training Gate:** none. The count needs no training.

#### 5. Acceptance criteria

- For a fixture plugin of known size, `realized_total_parameter_count`
  and `realized_trainable_parameter_count` each equal their exact
  hand-computed integer, and both are present in the persisted JSON.
- The frozen-parameter fixture pins the two fields **independently**:
  total includes the frozen parameter, trainable excludes it.
- Every pre-existing validator test passes **unmodified**.
- Instantiation failure yields `None` for both; no path can produce `0`
  for a model that failed to instantiate.
- `ExperimentRecord.model_params` is untouched and un-redefined.
- No code path computes a cross-convention delta or ratio.
- No branch anywhere reads either count.

#### 6. Failure and edge cases

| Case | Required behaviour |
|---|---|
| Model instantiates but `.parameters()` raises | `None`, verdict unchanged; never crash the validator |
| Model has zero parameters | Record `0` for both — a real measurement, distinct from `None` (§E.3d.4) |
| A model with frozen parameters makes the conventions diverge | Both remain true measurements of different things (O-E-6). Report each under its own name; never reconcile them into one number |
| Count contradicts `parameter_count_estimate` wildly | Record it. **No warning, no verdict** — that is the point of the PR |

#### 7. Verification commands and evidence

```bash
.venv/bin/python -m pytest tests/unit/agent/ml_code_validator_agent -q
.venv/bin/python -m pytest tests/unit -q -m "not real_run" > /tmp/pytest.log 2>&1; echo $?
```

- [ ] Validator suite unmodified, count and wall time — **to record**
- [ ] Mutation: swap the two fields' expressions → must fail (the
      frozen-parameter fixture is what makes this observable) — **to record**
- [ ] Mutation: derive trainable from total (or vice versa) instead of
      counting → must fail on the frozen fixture — **to record**
- [ ] Mutation: return `0` instead of `None` on failure → must fail — **to record**
- [ ] Mutation: let either count influence `passed` → must fail — **to record**

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
- [ ] Expose the four parameter columns under O-E-6 FINAL's
      convention-explicit display labels (§0.I) — labels only, no schema
      rename, and no delta/ratio across unlike conventions
- [ ] Report a candidate with a missing stage as **incomplete, stage
      named** — never dropped, never defaulted
- [ ] Record `preflight_factor` as a **measurement**, never a disposition
      (§0.D)
- [ ] **Legacy stage-local sanity check** (DC-3 — deliberately NOT
      called a backfill): run the *stage-local reader* over stored
      attempt-3 records and confirm the already-recorded trained
      parameter-count range (663,488 - 12,772,096) is reproduced. This is
      a read of ONE stage's native records. It is **not** a reconstructed
      cross-stage funnel and must never be described as one: pre-PR-E
      records have `candidate_id=None`, are unjoinable by rule, and **no
      identity may be inferred from `model_name` or anything else** to
      join them
- [ ] Emit no aggregate, mean, ratio or verdict

#### 4. Validation plan

**Unit**
- [ ] Complete candidate → every reached stage present
- [ ] Candidate stopped at validation → derived stage + the validator's
      own booleans as the reason
- [ ] Candidate stopped at implementation → stage named, reason **absent**
- [ ] Two candidates in one iteration do not merge

**Integration / pseudo — MERGE REQUIREMENT (DC-2)**
- [ ] One bounded deterministic/pseudo-mode iteration produces the
      on-disk stage artifacts, and the assembler builds a complete row
      from them. **This is a PR E merge requirement, not optional**: it
      is the only evidence layer that exercises
      `persistence -> filesystem discovery -> id join -> tuner fan-in ->
      derived row` as one path. No GPU, no real LLM, and the scientific
      outcome is never the oracle

**Negative / invalid input**
- [ ] Several records with `candidate_id=None` stay **separate and
      unjoinable** — never merged into one pseudo-candidate. This is the
      most dangerous possible bug in this commit
- [ ] A malformed / truncated stage JSON is reported as unreadable, not
      silently treated as a missing stage
- [ ] Non-local storage backend → "not discoverable", never "no candidate"

**Backward-compatibility / default parity**
- [ ] The legacy sanity check is **read-only**; assert nothing on disk changes

**Real-training Gate:** the ledger asks for *"one iteration produces a
complete funnel record"*. **The pseudo-mode iteration above satisfies it
and is REQUIRED (DC-2).** A real-GPU/real-LLM iteration adds no property
the pseudo path does not exercise, remains optional strengthening
evidence, and **must not be launched without operator approval.**

#### 5. Acceptance criteria

- For a fixture of four candidates — one complete, one stopped at
  validation, one stopped at implementation, one legacy with
  `candidate_id=None` — the assembler returns **exactly four rows**:
  complete; incomplete-named-at-validation with the native booleans;
  incomplete-named-at-implementation with reason **absent**; and one
  unjoinable. **Not three, and never one merged row.**
- With two legacy `None` records, the result has **two** unjoinable rows,
  not one.
- The legacy sanity check reproduces the ledger's recorded attempt-3
  trained-count range from ONE stage's stored records, asserts the
  **range**, and its output is labelled stage-local — it never appears as
  a funnel row.
- A mutation that joins legacy records via `model_name` must fail — the
  name-keyed join is the P6.2 regression this commit must make impossible.
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
- [ ] Legacy stage-local sanity check vs the ledger's recorded range — **to record**
- [ ] Mutation: join legacy records on `model_name` → must fail — **to record**
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

**Layer G — production-boundary evidence (revised by DC-2).** **One
bounded deterministic/pseudo-mode iteration producing a complete on-disk
funnel, successfully assembled, is a MERGE REQUIREMENT.** No real GPU and
no real LLM are required — but unlike PR D, whose change was two `Literal`
strings crossing pure in-process functions, E4's claim spans
`native persistence -> filesystem discovery -> candidate_id join ->
multi-record tuner fan-in -> derived row`, which unit and schema tests
cannot exercise as one path. Revision 2 said "optional" here while E4's
validation plan said required; the contradiction is resolved in favour of
**required**, because the evidence is genuinely new and cheap. The
remaining residual: no deterministic fixture drives a *real* LLM proposer,
so the mint site is additionally covered by a call-site test plus a
mutation, as PR D covered hop 7.

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
4. Both validator counts (total + trainable) are captured where the model
   is already instantiated, pinned independently by a frozen-parameter
   fixture, with the verdict bit-identical, `model_params` untouched, and
   no cross-convention delta computed anywhere (O-E-6 FINAL).
5. **No measurement is copied past its native owner** (O-E-3).
6. `stopped_at_stage` exists only as a derived read-side value; **no new
   reason vocabulary appears in the diff** (O-E-2).
7. The funnel assembles per candidate, names incomplete stages, and never
   merges unjoinable records.
8. **No distribution is claimed** (§E.3d.6); the legacy attempt-3 check
   is stage-local, never a reconstructed funnel, and no identity is ever
   inferred from `model_name` (DC-3).
8b. One bounded pseudo-mode iteration produces a complete on-disk funnel
   and is assembled — **merge requirement** (DC-2).
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

Acceptance evidence:      Layers A-F deterministic; Layer G is a REQUIRED
                          bounded pseudo-mode complete-iteration confirmation
                          (persistence -> discovery -> join -> fan-in ->
                          derived row); no real GPU or real LLM required
```

---

## Operator decisions

### Recorded and applied — O-E-1 … O-E-5

All five are applied throughout revision 2; §0.A maps each to what it
changed. O-E-1 additionally requires a **dated append-only correction in
`v21_priorities.md`**, retiring the "prompt contradiction resolved" merge
criterion.

### Open — NONE

Q-E-5's lineage closed as **O-E-6 FINAL** (§0.I): the operator resolved
the STOP condition as option (c) on 2026-08-08. The design is **APPROVED**;
no further design review is required. Implementation proceeds
E0 → E1 → E2 → E3 → E4 autonomously once PR #189 is merged from its
restored D-only branch and this branch is updated onto the merged master.
**PR E is not to be merged by the implementer.**
