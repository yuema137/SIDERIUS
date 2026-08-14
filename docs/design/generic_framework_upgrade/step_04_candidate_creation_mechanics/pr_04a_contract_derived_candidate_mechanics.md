# PR 04a — Contract-derived candidate mechanics — detailed design (child)

Parent: [`../step_04_candidate_creation_mechanics.md`](../step_04_candidate_creation_mechanics.md)

| Field | Value |
|---|---|
| Design base | `e802b810` |
| Depends on | Step 01 (#199/#201), Step 02 (#202/#203/#204), Step 03 (#205) |
| Blocks | nothing — 04b is independent |
| Status | **COMPLETE — MERGED 2026-08-14.** PR [#207](https://github.com/Galileo-Sandbox/SIDERIUS/pull/207), squash-merged as `6458dd95`. Design was frozen at `c3d29e73`; implemented from `3e9728c8`; final executable head `d019f94b`. Live ledger: §17. Context CLOSED |
| Frozen contract | §1 capability · §5 Stage-A parity · §6 ladder (6.5-A / 6.5-C / 6.5-D) · §7 PR-level definition of done (AUTHORITATIVE) · §11 Gates (1 and 2 REQUIRED) · §15.1 caller-path semantics |
| NOT frozen | exact Git commit count, helper structure, source line numbers, test-command decomposition (§16) |

---

## 1. Capability / final effect

> Every **contract-owned fact** used by candidate generation and
> validation derives from the Step-03 `ModelIOContract`. A
> declared-regressor candidate with a custom loss can be generated and
> **accepted by the validator**, which is impossible today.

**Contract-owned facts** (derive — never restate):

- class cardinality;
- semantic rank and ordered axis roles;
- fixed dimension constraints;
- dtype requirement / admissibility;
- canonical output semantic;
- any other machine-checkable Model-I/O fact actually consumed.

**Step-04-owned validation-instance choices** (remain probe recipes):

- the concrete realization of a **symbolic** extent such as `T`;
- probe batch size;
- other validation-convenience extents.

**The frozen acceptance property is:**

> No candidate-creation consumer independently restates a
> **contract-owned** semantic.

It is **not** "no numeric literal exists in a probe". Moving recipe
constants into task config to remove literals is explicitly wrong (§10
of the parent).

Observable difference: change the declared cardinality or output
semantic, and candidate generation *and* validation follow — with no
edit inside `nodes/ml_model_implementor/` or
`nodes/ml_code_validator_agent/`.

## 2. Source-owned surfaces

| File:line | Today | Change |
|---|---|---|
| `agent/schemas/validator.py:45` | `ValidatorInput` has no contract | add the typed contract field (**the FU-A-1 transport**) |
| `agent/schemas/implementor.py:219` | `forward_contract: ForwardContract` (prose) | additionally carry the normalized contract |
| `agent/schemas/protocols/ml_model_impl_to_ml_model_valid.py` | maps `ImplementorOutput → ValidatorInput` | must map the contract; no silent default |
| `ml_code_validator_agent.py:333` | `_PROBE_NUM_CLASSES: int = 256` | derive from `class_cardinality`; delete the constant |
| `ml_code_validator_agent.py:326-332` | FU-A-1 deferral comment | delete — the deferral is discharged |
| `ml_code_validator_agent.py:431-432,437` | `(1, 256, 64)` / `(1, 64)`; `randint(0, 256, (1,64))` | derive rank/axes/range; `64` stays a Step-04 recipe |
| `ml_model_implementor.py:118-131` in `_smoke_test_plugin` (`:82`) | `T = 64`; `randint(0,256,(1,T))`; `expected=(1,256,T)` | derive the class count; `T=64` stays a recipe |
| `TEST_TEMPLATE` `:309` — body `:323`, `:328-331`, `:340` | generated **test file** text; `256` hardcoded, `T` already from `config.segmentation_size` | derive the class count via a render-time placeholder (**not** a separate self-check — earlier revision mislabelled these lines) |
| `ml_model_implementor.py:279-288` `_OUTPUT_CONTRACT_COMMENTS` + `_render_output_contract` (`:291`) | static dict keyed by `output_type`, `256` baked into both strings | `_render_output_contract` takes the contract; render from `TensorContract.render_shape()` |
| `ml_model_implementor.py:785-870` | classifier-only loss probe | recipe keyed by output semantic (§4) |
| `ml_model_implementor.py:85` | docstring shape literal | derive/reword |
| `ml_model_implementor.py:363` | `<10 GB VRAM, <100M parameters` | derive from live `[HARDWARE CONTEXT]` — **OD-S4-1 APPROVED**; the only intentional LLM-visible golden delta |
| `ml_code_validator_agent.py:73` | validator prompt `[B, 256, T]` | render from the contract |
| **generated candidate description artifact** — `ml_model_implementor.py:1776-1796`, written to `agent_generated/models/{model_name}/description.md` | `:1783` already guards a regressor claiming `[B, 256, T]` | KEEP the existing guard; ensure no contract fact is restated. **This is 04a's description surface — distinct from 04b's static builtin `ml_models/{model_type}/description.md`** (parent §2.3.1) |

### 2.1 The transport is smaller than FU-A-1's wording suggests

Verified at `e802b810`: the contract is **already resolved in
production** at the task-config layer —
`workflows/task_config.py:172` calls
`agent.schemas.model_io_resolution.resolve_model_io_contract(...)`,
the same layer that already supplies `ForwardContract` to
`ImplementorInput`. And a **serialization precedent already exists**:
`execute_tools/train_engine_sandbox.py:1360` and
`execute_tools/inference_single.py:330` both accept `--model_io_json`
and call `load_model_io_contract(...)` across the real subprocess
boundary.

So 04a does **not** build a resolution path. It:

- reuses the existing resolution for the implementor (the value is
  already available where `forward_contract` is populated), and
- adds one typed field plus its protocol mapping for the validator.

This is the "reuse one existing typed boundary" condition the FU-A-1
comment said was missing — Step 03 created it. The A2 conditional that
justified deferring the literal no longer holds.

**Explicitly NOT changed**: `ml_model_implementor.py:447` (`le=256` in an
illustrative Pydantic config-field example — a bound, not a contract
fact); `_DEFAULT_OUTPUT_TYPE` (legacy-read compatibility, §8);
`agent/prompts.py:1037` (Step 07a).

## 3. First production consumer

The production validator's in-process shape probe
(`_check_instantiation_and_gradient`) and the production implementor's
self-check + artifact emission — both on the real chain path, both
exercised by every candidate.

## 4. The custom-loss recipe (the capability, not a literal sweep)

Separate two things that today are fused:

```text
"is this loss legal for this output semantic?"   -> Step-03 authority (UNCHANGED)
"how do I build a probe instance to test it?"    -> Step-04 recipe (NEW)
```

The recipe is keyed by the **declared output semantic**:

| Output semantic | `inputs` | `targets` |
|---|---|---|
| classifier | `[B, C, T]` float, `C` from `class_cardinality` | `[B, T]` int64 in `[0, C)` |
| regressor | `[B, T]` float | `[B, T]` float |

Do **not** introduce a second `LossContract`. The legality question is
answered by the existing Step-03 authority; only construction is new.

## 5. Stage-A parity

| Surface | Criterion | Status |
|---|---|---|
| `pb5_*` implementor goldens (13) | EXACT bytes, **except** the declared OD-S4-1 set, which may move ONLY by deltas mechanically attributable to the capacity-authority correction | existing |
| `pb6_*` validator goldens (3) | EXACT bytes | existing |
| kwargs reaching `LLMBridge` | unchanged | existing |
| generated plugin for a fixed TIDMAD spec | byte-identical | **CAPTURE FIRST** |
| validator verdicts on fixture plugins | identical | **CAPTURE FIRST** |
| prior on-disk plugin loadability | **all still load and register** (OD-S4-3: preserve; no workspace boundary). Corpus at design time: **89 examined, 89 declare `PLUGIN_OUTPUT_TYPE`, 0 lacking, 0 legacy-fallback, 0 malformed** (86 classifier / 3 regressor). Re-enumerate at implementation time — this is a live gitignored directory | **CAPTURE FIRST** |

The three "CAPTURE FIRST" baselines must land **before** any production
edit (Checkpoint 0).

## 6. Stage-B atomic rungs

Each rung varies exactly one axis **against its own declared baseline**,
holds all other authorities fixed, and must **red** if its consumer
re-hardcodes the legacy assumption. The baselines differ — this is
explicit, because 6.5-D is **cumulative**:

| Rung | Baseline | Varies ONLY | Reds when |
|---|---|---|---|
| **6.5-A** cardinality | the TIDMAD declaration | class cardinality | any `256` survives in a probe, a self-check, a generated comment or a rendered prompt |
| **6.5-C** output semantic | the TIDMAD declaration | canonical output semantic (classifier → regressor) | generation or validation still assumes the classifier form |
| **6.5-D** custom-loss capability | **the regressor declaration already established by 6.5-C** | custom-loss capability only | the loss probe still builds the classifier-shaped tensors — i.e. today's behaviour |

**6.5-D must not claim to vary output semantic and loss capability at
once.** Its baseline is 6.5-C's established regressor; the single axis
it varies is *"same regressor, now with a custom loss"*. Atomicity
machinery therefore diffs 6.5-D against the 6.5-C declaration, not
against TIDMAD.

6.5-D is the capability rung: **it fails on current master by
construction**, which is what makes it worth writing.

### 6.1 Rung 6.5-B — RESOLVED: removed from the required ladder

The roadmap proposed a *"shape/T only"* rung. It is **not** a semantic
rung, resolved from source rather than deferred:

`Dimension` (`agent/schemas/model_io_contract.py:94-125`) is exactly one
of `fixed`, `symbolic`, `dynamic`. TIDMAD's time axis is **symbolic**
(`T`), and a symbolic dimension declares **alignment** — two axes with
the same symbol are the same extent — **not a magnitude**. Cardinality
is `fixed: 256`, a concrete declared extent, which is why 6.5-A *is*
semantic and 6.5-B is not.

`T = 64 → 128` therefore varies no declared task or model semantic:
both satisfy the same symbolic constraint, and no upstream authority
changes. Such a rung would pass whether or not the consumer
re-hardcodes its literal — the exact weakness §6's criteria forbid.

**Disposition: NOT a required Stage-B semantic rung** (parent §10.1).
It MAY be kept as **probe-recipe robustness evidence** — the probe
builds correctly at a second length — but must never be reported as a
generic semantic contrast.

**Required semantic ladder for 04a: 6.5-A, 6.5-C, 6.5-D.**

### 6.2 6.5-D closes at the CANDIDATE-VALIDATION boundary

Helper-level evidence is necessary but **not sufficient**. A finite
scalar loss and a finite `inputs.grad` prove the probe was built; they
do not prove the capability.

**PR-level acceptance property (frozen):**

> Given a declared-regressor `ModelIOContract` and a valid custom loss,
> the production-equivalent candidate-generation + validation path
> produces the candidate and the **validator ACCEPTS it**.

- Deterministic / recorded candidate and spec inputs are acceptable.
- A stochastic real LLM call is **not** required for this assertion.
- But the evidence **must cross the real candidate-generation /
  validation boundary** — helper-only evidence cannot discharge it.

The lower-level finite-gradient and broken-loss negative tests are
**retained**: they protect distinct failure semantics (a severed graph,
a NaN gradient) that the capability assertion does not cover.

## 7. PR-level definition of done — AUTHORITATIVE

The C1-C8 acceptance criteria in §16 are **milestone** detail. **This
table is the final acceptance contract.** Where the two ever appear to
disagree, this table governs.

### CHECKPOINT 0 — BASELINE
- [x] generated-plugin parity baseline captured — §17.2, 3 goldens
- [x] validator-verdict baseline captured — §17.2, 5 verdict classes
- [x] current prior-plugin loadability baseline captured — §17.2, 89/89 registered
- [x] **all captured BEFORE any production edit** — milestone diff is `tests/`-only

### CHECKPOINT A — TIDMAD PARITY
*Closed mechanically at the final head — evidence in §17.10.*
- [x] `pb5_*` exact, **except** the explicitly authorized OD-S4-1 attributed delta — **one file, one line**
- [x] `pb6_*` exact — untouched in `git diff e802b810..HEAD`
- [x] same kwargs reach `LLMBridge` — no call-site signature changed; `pb5_*`/`pb6_*` captured through the real boundary recorder
- [x] fixed-spec generated-artifact compatibility — plugin goldens byte-identical, both output types
- [x] validator-verdict compatibility — 5 verdict classes unchanged
- [x] prior-plugin loadability preserved — **91/91** register (§17.9.9)

### CHECKPOINT B — GENERIC CAPABILITY
- [x] 6.5-A PASS — atomic against the TIDMAD declaration (§17.8)
- [x] 6.5-C PASS — atomic against the TIDMAD declaration (§17.8)
- [x] 6.5-D PASS — atomic against **6.5-C's established regressor declaration**, closing at the validator boundary (§17.6.1)
- [x] mutation / adversarial evidence: 8 mutations, each rung reds — mapping in §17.8.1

### CHECKPOINT C — LIVE PRODUCTION
- [x] the real production implementor receives and uses the resolved contract (§17.9.5 (i))
- [x] the real production validator receives and uses the same semantic declaration (§17.9.5 (iii))
- [x] run artifacts prove **both** generated-candidate derivation **and** a contract-derived validation probe (§17.9.5)

**A required Gate run MAY discharge Checkpoint C** when the same
final-head run produces all required C evidence. Do **not** run a
duplicate real chain merely because "Checkpoint C" and "Gate" are
different names.

### CHECKPOINT D — REGRESSION
- [x] directly affected deterministic tests (§17.9.8)
- [x] focused integration (§17.9.8)
- [x] independent mutation classes — 8, one survivor found and closed
- [x] required static / lint clean; **pyright is CI-only** in this environment (§17.9.2)
- [x] **exact-final-head CI** — run `31774858601` on `d019f94b`, all four steps success (§17.11)
- [x] **no local full suite by default** (§11) — honoured

### GATES
- [x] **Gate 1 — REQUIRED** — PASS (§17.9.4)
- [x] **Gate 2 — REQUIRED** — PASS (§17.9.7)

### READY FOR OPERATOR REVIEW — **ALL MET; MERGED**
- [x] Checkpoints 0 / A / B / C / D complete
- [x] required Gates complete — Gate 1 PASS, Gate 2 PASS
- [x] PR open / updated — #207
- [x] exact-final-head CI green — run `31774858601` on `d019f94b`: ruff, ruff-format, **pyright strict**, pytest all success
- [x] local HEAD == PR `headRefOid` == successful CI `headSha` == `d019f94b` (verified mechanically)
- [x] working tree clean

---

## 8. Checkpoint C — live integration

In one real chain iteration: the production implementor emits a
candidate whose contract comments and self-check came from the resolved
contract, and the production validator probes it with a contract-derived
tensor. Evidence from run artifacts (generated plugin + validator
report), not unit mocks.

## 9. Failure classes this PR must protect

1. Contract silently dropped by the protocol → probe falls back to a
   default and validates against the wrong shape.
2. A derived value that silently defaults to `256` when the contract is
   required by an EXPLICITLY supplied contract is missing — must fail
   closed, not guess (§15.1 row 3). Mere absence of a contract is the
   legacy path and must NOT raise (row 1).
3. Regressor custom loss rejected for the wrong reason (probe shape
   rather than genuine illegality).
4. Prior on-disk plugin becomes unloadable.
5. Probe recipe treated as task semantics (leaks `64` into task config).
6. A rendered prompt drifts from the contract it claims to state.

## 10. Test disposition

| Test | Verdict |
|---|---|
| `_PROBE_NUM_CLASSES` / `256` value pins | **REWRITE** → profile-parameterized pins on derived output |
| template-internal regex pins on contract comments | **REWRITE** → assert derivation, not template text |
| `test_output_contract_end_to_end.py` | **KEEP / UPGRADE** — already `output_type`-parameterized |
| `test_baseline_self_check.py` | **UPGRADE** to contract-derived expectations |
| `test_loss_generation_e2e.py` | **UPGRADE** — add the regressor path (6.5-D) |
| ABSENCE pins proving the template layer carries no task literal | **KEEP template-scoped** |
| `test_step00_prompt_goldens.py` (pb5/pb6) | **KEEP** — the parity oracle |

Nothing is deleted for failing.

## 11. Gates

| Gate | Decision |
|---|---|
| **Gate 1** | **REQUIRED — unconditionally.** The standard's row *"Loss function generation (L4) → Gate 1 (dummy-tensor) + Gate 2 at Checkpoint L"* applies on its own, because §4 changes the loss dummy-tensor probe. OD-S4-1 (approved) does not gate whether Gate 1 runs — it governs only the declared `pb5_*` delta. No flip condition removes Gate 1 from this PR |
| **Gate 2** | **REQUIRED** — this is a Checkpoint commit. Current bounded canonical command, `openai_tiered_pro.json` |

## 12. Validation budget

Deterministic contract-derivation tests + the **three required
semantic rungs** (6.5-A / 6.5-C / 6.5-D, plus optional robustness
evidence if implementation finds it useful) + existing goldens; Gate 1
and Gate 2 at the assembled head.

**Exact-final-head CI is the broad regression authority.** A local full
suite is **NOT PLANNED**. It may be run only if, *before* launch, the
implementation ledger records: the exact unique evidence gap, why
targeted tests cannot provide it, why exact-head CI cannot provide it,
and the expected runtime. Never run one "just to be safe".

## 13. Rollback boundary

Self-contained: two node modules, two schemas, one protocol, their
tests. Reverting restores the module constants; no other step depends on
this transport.

## 14. Stop conditions

Parent §19 applies, plus: if the probe recipe cannot be expressed
without a semantic the Step-03 contract does not carry, STOP rather than
growing Model-I/O to suit candidate code.

## 14.1 Operator decisions

- **OD-S4-1 — APPROVED**: derive the capacity prose from the live
  Hardware Context; the declared `pb5_*` set may move ONLY by
  mechanically attributable deltas. The only intentional LLM-visible
  golden delta in Step 04.
- **OD-S4-2 — APPROVED**: TWO PRs, `04a → 04b`; independence
  re-verified (parent §2.3.1).
- **OD-S4-3 — APPROVED**: preserve prior-plugin loadability; no
  workspace boundary. Corpus re-audited (§5).
- **OD-S4-4 — APPROVED**: convergence is record-only; 04a implements no
  convergence abstraction and does not merge `ForwardContract` with
  `ModelIOContract`.

**Remaining operator questions for 04a: NONE.**

## 15. The two caller paths — frozen semantics

**Terminology note.** These are **implementation paths**, not roadmap
regimes. The roadmap reserves *Regime A* for the legacy/migration
adapter and *Regime B* for explicit generic task binding through the
Step-12 composition mechanism, with per-module missing-binding behaviour
landing at Step 12. Nothing here claims that shipped TIDMAD is roadmap
Regime B. 04a uses source-accurate names only:

- **normalized-contract-present path** — the caller supplies a
  `ModelIOContract`;
- **legacy prose-only compatibility path** — no normalized contract is
  supplied.

Established by inspection: `ForwardContract.model_io: ModelIOContract | None`
(`agent/schemas/task_config.py:112`) **already exists** and, when
present, is already THE authority — the prose fields are derived from it
by `_derive_prose_from_the_normalized_contract`. **Consequence: the
implementor needs no new transport**; it already receives
`inp.forward_contract.model_io`. Only the validator does.

### 15.1 Frozen behavioural contract

| # | Situation | Required behaviour |
|---|---|---|
| **1** | Legacy caller, **no** normalized contract supplied | **Preserve today's behaviour exactly.** Absence alone must **never** raise |
| **2** | Normalized contract **explicitly supplied** | It is **authoritative for every semantic it declares**; no consumer may restate or override those |
| **3** | Explicit contract present, but a semantic **required by its own declared input/output form** is missing, contradictory or unusable | **Typed fail-closed.** Never a guess, never a silent default |
| **4** | Caller holds an explicit contract, but transport **drops or substitutes** it | **Forbidden, and test-detectable** — a focused test must red |

Row 3 examples: a declared classifier whose contract carries no class
cardinality → typed failure; an explicit contract requiring a semantic
the probe cannot realize → typed failure / STOP per parent §19.

**Rows 1 and 3 are different situations and must not be collapsed.**
"Contract absent ⇒ fail closed" is **wrong**: absence is the legacy
path (row 1); it is an *explicitly supplied but incomplete* contract
that fails closed (row 3).

---

## 16. Commit plan

**Current planned semantic milestones** — C1…C8 below. `[ ]` = not
done, `[x]` = done **and** verified with recorded evidence.

**What is frozen**: the semantic capability, acceptance criteria, parity
surfaces, atomic rungs, checkpoints and Gate requirements, plus the
milestone ordering where it is semantically necessary (baselines before
production edits; transport before the probe derives from it; rungs
after the consumers they exercise).

**What is NOT frozen**: the exact Git commit count, helper structure,
source line numbers, and test-command decomposition. Line references
here are design-time reading aids, not contracts. At implementation
time, after re-reading the touched source, milestones **may be merged or
split** where that is cleaner — provided everything in the frozen list
above is unchanged. Engineering choreography is not the contract.

**A note on the template's ordering/`shuffle` clauses**: those examples
(`file_order`, visited sample/file sequence, default-`shuffle` parity)
belong to a data-ordering feature and have **no surface in 04a** — this
PR changes no selection, sampling, seeding or ordering path. The
*principle* is carried over instead, and it is binding: **assert the
observable artifact, never the configuration value** — the tensor
actually built, the bytes actually rendered, the file actually
generated. "The contract field is set" is never an acceptance criterion
here.

---

### C1 — Checkpoint 0: capture the three missing Stage-A baselines

**1. Goal.** Create the oracles that every later commit is measured
against. Nothing can be shown to be behaviour-preserving until they
exist.

**Why here**: §5 lists three baselines as MISSING. Capturing them after
a production edit would bake the edit into the baseline.

**2. Scope.**
- Adds: baseline tests + fixtures for (a) generated plugin bytes for a
  fixed spec, (b) validator verdicts on fixture plugins, (c)
  prior-plugin loadability.
- **Non-goals**: zero production files change in this commit.
- Depends on: nothing.

**3. Implementation plan.**
- [x] Re-enumerate the on-disk corpus mechanically and record the counts in §5 — **89/89/0/0/0, 86 classifier / 3 regressor: identical to the design-time audit** (§17.2).
- [x] Capture the generated-plugin byte baseline for a fixed recorded spec (pseudo/recorded LLM output, not a live call).
- [x] Capture validator verdicts for a fixture set covering classifier and regressor plugins — five distinct verdict classes, not two.
- [x] Capture a loadability baseline asserting every currently present plugin imports and registers.
- [x] Add a synthetic fixture plugin that OMITS `PLUGIN_OUTPUT_TYPE`, to protect the `_DEFAULT_OUTPUT_TYPE` fallback that no on-disk plugin exercises — plus its mirror negative, so the fallback's *value* is pinned and not merely its side effect.

**4. Validation plan.**
- Unit: the three baselines run green on unmodified master.
- Negative: the synthetic no-declaration fixture resolves via the fallback.
- Backward-compat: this commit IS the compat oracle.
- Gate: none.

**5. Acceptance criteria.**
- [x] `git diff --name-only` for this commit contains **no** file outside `tests/`.
- [x] The loadability baseline names an exact count and fails if any plugin stops importing — see the reconciliation note below.
- [x] The generated-plugin baseline is byte-exact and reproducible twice in a row from the same recorded spec.

> **Reconciliation — criterion 2 vs §6's edge case.** Criterion 2 asks the
> baseline to *"name an exact count"*; §6 (and parent §18) requires it to
> *"enumerate at run time, never pin a literal count"*. Read literally the
> two conflict. Resolved in favour of §6, whose reason is concrete: the
> directory is live and gitignored, so a pinned literal fails the day after
> the next chain run. The oracle satisfies both readings — it asserts
> `len(registered) == len(corpus)`, an exact-count assertion whose operand is
> enumerated at run time, and prints the exact numbers for the ledger.
> No frozen semantic changed; this is a wording conflict inside one
> milestone's own criteria.

**6. Failure and edge cases.**
- A plugin that already fails to import on master → record it as a
  pre-existing exclusion with its name; do **not** silently drop it and
  do **not** fix it here.
- Corpus count drifts between capture and use (live gitignored dir) →
  the oracle must enumerate at run time, never pin a literal count.

**7. Verification commands and evidence.**
- [x] `.venv/bin/python -m pytest tests/unit/agent/ml_code_validator_agent tests/unit/agent/ml_model_implementor -q` → **327 passed in 3.03s**, rc=0 read from the log.
- [x] Record: test count, wall time, exact corpus counts → §17.2.

**8. Commit boundary.** Test-only; independently reviewable; no
production behaviour touched.

---

### C2 — Validator contract transport (no behaviour change)

**1. Goal.** Give `ValidatorInput` the normalized contract, so the probe
can later derive from it. Behaviour is deliberately unchanged here.

**Why separate**: this is the FU-A-1 seam. Landing it alone keeps the
schema/protocol/workflow diff reviewable apart from the probe rewrite,
and it is consumed by C3 in the same PR (so it is not a consumer-less
seam).

**2. Scope.**
- `agent/schemas/validator.py:45` `ValidatorInput` — add the contract field (optional; `None` = legacy prose-only path).
- `agent/schemas/protocols/ml_model_impl_to_ml_model_valid.py:25` `local_all_fields` — carry it; `database_all_fields:65` keeps its `NotImplementedError` placeholder.
- `workflows/model_exploration.py:2419` — the `local_all_fields(...)` call site.
- **Non-goals**: `_PROBE_NUM_CLASSES` still governs the probe after this commit; no verdict changes.
- Depends on: C1.

**3. Implementation plan.**
- [x] Inspect `ImplementorOutput` to decide whether the contract rides the implementor's output or is passed by the orchestrator; choose the one that does not duplicate authority, and record which. → **rides `ImplementorOutput`**; reasoning in §17.3.
- [x] Add the optional contract field to `ValidatorInput` with a docstring naming Step 03 as the authority.
- [x] Thread it through `local_all_fields`; keep the `database_*` placeholder.
- [x] ~~Update the workflow call site at `:2419`~~ — **not required** under the chosen route: the protocol reads the field off `ImplementorOutput`, so the orchestrator call is unchanged. Bounded deviation, recorded in §17.3.
- [x] Update the protocol's docstring field inventory (it enumerates the mapped fields explicitly).

**4. Validation plan.**
- Unit: protocol maps the contract; absent contract → `None`, no crash.
- Negative: a contract present upstream but dropped by the protocol must **fail a test**, not default silently.
- Backward-compat: all existing validator tests pass **unchanged**.
- Gate: none.

**5. Acceptance criteria.**
- [x] Validator verdicts from C1's baseline are **byte-identical** before and after this commit.
- [x] A test asserts the contract object arriving at `ValidatorInput` is the same declaration the workflow resolved — compared by value, not by "field is not None".
- [x] `pb6_*` goldens unchanged.

**6. Failure and edge cases.**
- Legacy prose-only path (no contract supplied) → field is `None`, everything behaves as today. **Must not raise** (§15.1 row 1).
- Protocol silently defaulting the contract → forbidden; a dropped contract must surface as a typed failure.

**7. Verification commands and evidence.**
- [x] Widened to include the implementor and schema directories (the producer end and the key-set pin live there): **810 passed in 7.57s**, rc=0.
- [x] Record counts + wall time → §17.3.

**8. Commit boundary.** Schema + protocol + one call site. No probe
change. Independently revertible.

---

### C3 — Validator probe derives from the contract

**1. Goal.** Discharge FU-A-1: the probe's class range and expected
shape come from the declaration instead of `_PROBE_NUM_CLASSES`.

**2. Scope.**
- `ml_code_validator_agent.py:336` `_check_instantiation_and_gradient` — signature gains the contract.
- `:333` `_PROBE_NUM_CLASSES` and the `:326-332` FU-A-1 comment — **deleted**.
- `:431-432`, `:437` — derive expected shape and value range.
- `:547` — the single production call site.
- `nodes/ml_code_validator_agent/__init__.py:25,38` — re-export unchanged in name.
- **~13 test call sites** across `test_validator_agent.py`, `test_pr_e_realized_parameter_counts.py`, `test_output_contract_end_to_end.py` must be updated.
- **Non-goals**: `T = 64` stays; `_DEFAULT_OUTPUT_TYPE` stays.
- Depends on: C2.

**3. Implementation plan.**
- [x] Change the signature to accept the contract (optional; `None` = legacy prose-only path).
- [x] Derive the class extent from `ModelIOContract.class_cardinality`; derive expected rank/axes from the output `TensorContract`.
- [x] Keep `T = 64` as an explicit, commented recipe constant → `PROBE_SYMBOLIC_EXTENT`.
- [x] Legacy-path fallback: when no contract is supplied, reproduce today's behaviour exactly (§15.1 row 1).
- [x] Delete `_PROBE_NUM_CLASSES` and the FU-A-1 deferral comment.
- [x] Update the production call site; **test call sites needed no change** — the parameter is optional, so every existing caller keeps the legacy path (§17.4.5).

**4. Validation plan.**
- Unit: probe builds the correct tensor for a declared cardinality (assert the **tensor's** dtype/shape/value range, not the config).
- Integration: `test_output_contract_end_to_end.py` still green for both `output_type` values.
- Negative: a model violating the declared output shape is still rejected, with an error naming the declared shape.
- Backward-compat: legacy prose-only path byte-identical to master.
- Gate: none.

**5. Acceptance criteria.**
- [x] `grep -rn "_PROBE_NUM_CLASSES" nodes/` returns **nothing**.
- [x] Under a declared `{fixed: 16}` contract the probe input's max admissible value is `15` and the expected shape's class axis is `16` — asserted on the constructed tensor.
- [x] Validator verdicts on C1's fixture set are unchanged under TIDMAD.
- [x] A legacy no-contract fixture produces the identical verdict and identical error text to master.

**6. Failure and edge cases.**
- Contract present but carrying no class axis (a declared regressor) → expected shape has no class axis; must not synthesize one.
- No contract supplied (legacy path) → fallback, **no raise** (§15.1 row 1).
- Contract explicitly supplied but cardinality `None` while the declared semantic is classifier → **typed failure**, not a guess (§15.1 row 3).

**7. Verification commands and evidence.**
- [x] Run recorded in §17.4; **132 passed** in the validator directory after the reachability gap was closed.
- [x] Record counts + wall time; updated call-site count: **1 production site**, 0 test sites.

**8. Commit boundary.** Validator only. No implementor change.

---

### C4 — Implementor self-check and generated artifacts derive

**1. Goal.** The implementor's own self-check and the artifacts it
writes stop restating the class count.

**Why separate from C3**: different node, different failure surface, and
it needs no transport work — it already has `inp.forward_contract.model_io`.

**2. Scope.**
- `ml_model_implementor.py:118-131` inside `_smoke_test_plugin` (`:82`).
- `:279-288` `_OUTPUT_CONTRACT_COMMENTS` and `:291` `_render_output_contract`.
- `TEST_TEMPLATE` `:309` (body `:323`, `:328-331`, `:340`) and its render site `:1289`.
- **Non-goals**: `:447` (`le=256` channels bound) untouched; `T`/`segmentation_size` derivation untouched; the `:1783` regressor description guard untouched.
- Depends on: C1. Independent of C2/C3.

**3. Implementation plan.**
- [x] Inspect how `_smoke_test_plugin` is reached and whether the contract is in scope there; threaded from `inp.forward_contract.model_io`.
- [x] Derive the class extent in the self-check; `T` stays a recipe.
- [x] Give `_render_output_contract` the contract and render the comment strings from the declared output tensor.
- [x] Added `{num_classes}` and `{index_extent}` placeholders to `TEST_TEMPLATE`; `_assemble_test` updated. `{{...}}` escaping preserved — asserted with `ast.parse` on the rendered file.
- [x] Legacy-path fallback for all three (§15.1 row 1), each pinned by a two-path equality test.

**4. Validation plan.**
- Unit: generated plugin's contract comment matches the declared contract.
- Integration: the **generated test file executes and passes** against a generated plugin — not merely string-compared.
- Negative: unknown/unsupported output semantic still raises (preserve `_render_output_contract`'s deliberate `ValueError`).
- Backward-compat: generated plugin bytes identical to C1's baseline under TIDMAD.
- Gate: none.

**5. Acceptance criteria.**
- [x] Generated plugin file for the fixed spec is **byte-identical** to C1's baseline (both output types).
- [x] Under `{fixed: 16}`, the generated test's assertion references 16, and **executing** that generated test against a 16-class plugin passes.
- [x] `_render_output_contract` still raises on an unrecognised semantic — on both the contract and the legacy path.

**6. Failure and edge cases.**
- Template placeholder collision with existing `{{ }}` escaping → generated file must still parse; assert with `ast.parse`.
- Legacy prose-only path → template renders exactly today's text.
- A declared regressor → no class count appears in the generated test at all.

**7. Verification commands and evidence.**
- [x] Run recorded in §17.5 — **461 passed in 6.96s**, rc=0, across the implementor, validator, protocol and end-to-end directories.
- [x] Record counts + wall time → §17.5.5.

**8. Commit boundary.** Implementor only. No prompt bytes change here —
prompts are C6.

---

### C5 — Custom-loss probe recipe keyed by output semantic

**1. Goal.** Close the real capability gap: a declared-regressor custom
loss currently cannot pass, because `:859-860` builds classifier-shaped
tensors unconditionally.

**2. Scope.**
- `ml_model_implementor.py:785-870` `_dummy_tensor_validate_loss` (docstring `:792-794`, construction `:859-860`, message `:867`).
- **Non-goals**: no second `LossContract`; no change to loss legality; no change to frozen loss math.
- Depends on: C4 (same module, contract already in scope).

**3. Implementation plan.**
- [x] Added `build_loss_probe_pair`, keyed by declared output semantic per §4's table.
- [x] `C` derived from the contract; `B = 2` and `T = 100` kept as recipe constants.
- [x] Docstring and failure message now name the pair actually built.
- [x] Confirmed from source (`models_format_sandbox.py:592`): `custom` is deliberately legal for every contract; no legality rule was touched.

**4. Validation plan.**
- Unit: recipe returns the right shapes/dtypes per semantic.
- Integration: `test_loss_generation_e2e.py` extended with a regressor custom loss that **passes** (rung 6.5-D, baseline = 6.5-C's regressor declaration).
- **Capability closure**: the production-equivalent generation + validation path produces the candidate and the validator **ACCEPTS** it (§6.2) — helper-only evidence does not discharge this.
- Negative: a genuinely broken loss (detached graph / NaN) is still rejected under **both** semantics — the backward() and finiteness checks must not weaken.
- Backward-compat: classifier custom-loss verdicts unchanged.
- Gate: **Gate 1 (dummy-tensor) REQUIRED** for this behaviour (§11). Exact launch timing and authorization are governed by the implementation contract and the current Gate standard.

**5. Acceptance criteria.**
- [x] A declared-regressor custom loss is accepted — and closes at the VALIDATOR, not the helper (§17.6.1).
- [x] The same loss is still **rejected** on the legacy pair — the exact before/after strings are in §17.6.
- [x] A detached-graph loss is rejected under both semantics; non-finite too.
- [x] Classifier verdicts identical to C1's baseline.

**6. Failure and edge cases.**
- No contract supplied (legacy path) → classifier recipe, i.e. today's behaviour (§15.1 row 1).
- Explicit contract, declared classifier, `class_cardinality is None` → typed failure, not a `256` guess (§15.1 row 3).
- A loss legal for one semantic but probed under the other → must fail for the *legality* reason, not a shape accident.

**7. Verification commands and evidence.**
- [x] Widened to the whole implementor directory (the capability rung crosses into the validator): **230 passed in 5.03s**, rc=0.
- [x] Record counts + wall time → §17.6.4.

**8. Commit boundary.** Loss probe only. Does not touch model probes.

---

### C6 — Prompt surfaces derive (includes the OD-S4-1 golden delta)

**1. Goal.** The implementor/validator prompts state the contract from
the declaration, and the stale capacity prose derives from the live
Hardware Context.

**Why last among the production commits**: it is the only commit that
may move LLM-visible bytes, so it is isolated for review and for Gate 1
attribution.

**2. Scope.**
- `ml_code_validator_agent.py:73` — validator prompt contract text.
- `ml_model_implementor.py:85` — docstring shape literal.
- `ml_model_implementor.py:363` — `- GPU budget: <10 GB VRAM, <100M parameters …` → derived (**OD-S4-1**).
- Declared golden set: the affected `pb5_*` files.
- **Non-goals**: no new task-config field for capacity; `pb6_*` and `pb9_*` must not move.
- Depends on: C3, C4.

**3. Implementation plan.**
- [x] Inspected `_render_hardware_context_block` and reused it — by EXTRACTING `HardwareContext.effective_cap_gb` so both nodes call one rule (§17.7.1), rather than copying the arithmetic.
- [x] Repointed the capacity bullet at it, via a `{CAPACITY_BUDGET}` placeholder.
- [x] Validator prompt's two shape tokens rendered from the declaration (§17.7.4).
- [x] Reused Step 01's `_numeric_capacity_literals` over the implementor scan set; one legitimate hit scoped by content, not weakened (§17.7.3).
- [x] Regenerated ONLY `pb5_reasoning_system.txt`; the complete diff is one line (§17.7.2).

**4. Validation plan.**
- Unit: rendered prompt contains the derived capacity text and no literal.
- Golden: `pb6_*` exact; `pb9_*` exact; `pb5_*` changed **only** in the attributed block.
- Negative: the capacity-literal detector reds if a literal is reintroduced.
- Backward-compat: kwargs reaching `LLMBridge` unchanged.
- Gate: **Gate 1 REQUIRED** (§11). Exact launch timing and authorization are governed by the implementation contract and the current Gate standard.

**5. Acceptance criteria.**
- [x] Every `pb5_*` diff line is attributable — one line, one file, proven mechanically by `test_only_the_capacity_bullet_moved_in_the_pb5_golden_set`.
- [x] `pb6_*` and `pb9_*` byte-identical.
- [x] The concept detector fails when `<10 GB VRAM` is reintroduced (mutation G), and its reachability is separately pinned.
- [x] The rendered capacity text reflects the live hardware value — asserted on TWO different machines, plus both budget regimes.

**6. Failure and edge cases.**
- Hardware context unavailable at render time → must degrade to a defined, tested string, never a stale literal and never a crash mid-prompt.
- An unattributable `pb5_*` delta → **STOP** (parent §19).

**7. Verification commands and evidence.**
- [x] Run recorded in §17.7.6.
- [x] Changed golden files: **`pb5_reasoning_system.txt` only**.

**8. Commit boundary.** Prompt/golden only. Carries the single
authorized byte delta and nothing else.

---

### C7 — Stage-B contrast rungs

**1. Goal.** Prove the abstraction is real: 6.5-A, 6.5-C, 6.5-D.

**2. Scope.** Contrast fixtures + rung tests. **Non-goals**: no
production change; **6.5-B is not implemented as a semantic rung**
(§6.1). Depends on: C3, C4, C5.

**3. Implementation plan.**
- [x] 6.5-A: cardinality only; atomicity diff is literally the single path `output.axes.1.fixed`.
- [x] 6.5-C: output semantic only; input declaration asserted identical.
- [x] 6.5-D: diffed against 6.5-C's regressor declaration (diff == `[]`); the capability half is referenced in C5's module, not duplicated.
- [x] Machine-checked atomicity via the `_diff_paths` precedent.
- [x] Unvaried consumers asserted unchanged — 6.5-A diffs the exact SET that moved.
- [x] `T = 64 → 128` added as probe-recipe robustness, explicitly labelled not-a-semantic-rung.

**4. Validation plan.**
- Unit: each rung reds when its consumer re-hardcodes the legacy literal (prove by temporary mutation, with cache cleared and the mutation count asserted == 1).
- Negative: residue assertions are **block-scoped**, never whole-prompt.
- Gate: none.

**5. Acceptance criteria.**
- [x] Each rung varies exactly one axis against its own baseline, proven mechanically (§17.8).
- [x] Each rung reds under its mutation and greens without it — mapping in §17.8.1.
- [x] No rung required a second axis.

**6. Failure and edge cases.**
- A rung passing with the literal still present → the rung is too weak; fix or delete it, never keep it.
- A whole-prompt absence assertion → invalid by construction (Step-01 residue lesson).

**7. Verification commands and evidence.**
- [x] `test_step04a_stage_b_ladder.py` → 11 passed in 1.20s; mutation results mapped in §17.8.1.

**8. Commit boundary.** Test-only.

---

### C8 — Checkpoint C, doc sync, closeout

**1. Goal.** Prove the capability live in production and leave the docs
true.

**2. Scope.** Node `.md` docs (`ml_model_implementor.md`,
`ml_code_validator_agent.md`), this design's ledger, evidence records.
Depends on: C1-C7.

**3. Implementation plan.**
- [ ] Run one real chain iteration; capture the generated plugin and validator report as Checkpoint-C evidence.
- [ ] Verify from artifacts that probe and artifacts came from the resolved contract.
- [ ] Update both node `.md` files (doc-sync rule) and quote each documented default against merged source.
- [ ] Re-enumerate the plugin corpus and record final counts.
- [ ] Fill §16 with real results.

**4. Validation plan.**
- Gate 1 and Gate 2 — **both REQUIRED** (§11), bounded canonical command, `openai_tiered_pro.json`. Exact launch timing and authorization are governed by the implementation contract and the current Gate standard.
- Terminal: **exact-final-head CI green** — the broad regression authority. No local full suite is planned (§12).

**5. Acceptance criteria.**
- [ ] Checkpoint-C evidence comes from run artifacts, not unit mocks.
- [ ] Every plugin present at implementation time still loads and registers.
- [ ] Node `.md` flags/defaults verified against merged source.
- [ ] Local HEAD == PR head == green CI head.

**6. Failure and edge cases.**
- Gate 2 fails on model quality → **not** a failure (parent §14 / standard).
- A plugin stops loading → OD-S4-3 says preserve; if impossible without material scope growth, **STOP and report**.

**7. Verification commands and evidence.**
- [ ] Record Gate 1 / Gate 2 outcomes, wall time, final suite counts, CI run id.

**8. Commit boundary.** Docs + evidence only.

---

## 17. Implementation ledger

**Status**: IMPLEMENTATION IN PROGRESS.
Branch `feat/generic-framework-step-04a-contract-derived-candidate-mechanics`,
based on `3e9728c8` (the freeze marker). Frozen design content `c3d29e73`
verified present; `e802b810` verified as the exact merge-base with
`origin/master`; the only diff between them is docs (4 files, +1573/-1), so
no production change had landed on the design branch.

### 17.1 Milestone status

| Milestone | Status |
|---|---|
| C1 — Checkpoint 0 baselines | **DONE** (§17.2) |
| C2 — validator contract transport | **DONE** (§17.3) |
| C3 — validator probe derivation | **DONE** (§17.4) |
| C4 — implementor derivation | **DONE** (§17.5) |
| C5 — custom-loss probe recipe | **DONE** (§17.6) |
| C6 — prompt / capacity authority | **DONE** (§17.7) |
| C7 — Stage-B rungs | **DONE** (§17.8) |
| C8 — Checkpoint C, docs, closeout | **DONE** (§17.9, §17.11) |

### 17.2 C1 — Checkpoint 0: the three missing Stage-A baselines

Captured from the **unmodified production base**, before any production
edit. `git status` for the milestone contains no file outside `tests/`,
satisfying C1 acceptance criterion 1.

**Files added**

| File | Role |
|---|---|
| `tests/helpers/step04a_fixtures.py` | the one frozen TIDMAD spec both oracles render from — normalized contract, prose-only legacy variant, frozen LLM code contribution, frozen model names |
| `tests/unit/agent/ml_model_implementor/test_step04a_generated_artifact_baseline.py` | generated-plugin + generated-test byte baseline |
| `tests/unit/agent/ml_model_implementor/goldens/s04a_generated_plugin_{classifier,regressor}.txt` | 1126 / 1123 bytes |
| `tests/unit/agent/ml_model_implementor/goldens/s04a_generated_test.txt` | 1266 bytes |
| `tests/unit/agent/ml_code_validator_agent/test_step04a_validator_compat_baseline.py` | validator verdicts, legacy-fallback reachability, prior-plugin loadability, corpus census |
| `tests/unit/agent/ml_code_validator_agent/goldens/s04a_validator_verdicts.json` | five verdict classes |

**Baseline 1 — generated-artifact bytes.** `_assemble_plugin` and
`_assemble_test` are fully deterministic given `(ImplementorInput, code
dict)`; the LLM's contribution is frozen in `CODE_BY_OUTPUT_TYPE`, which
is what makes parent §8's byte criterion meaningful rather than a snapshot
of model behaviour. Reproducibility is asserted separately
(`test_generated_plugin_bytes_are_reproducible`) so the golden pins a
function, not a lucky run — C1 acceptance criterion 3.

**Baseline 2 — validator verdicts.** Five fixture plugins, each a distinct
verdict class rather than a variation on one:

| Case | Verdict |
|---|---|
| `classifier_ok` | `(True, True, True, None)`, 4352 params |
| `regressor_ok` | `(True, True, True, None)`, 2057 params |
| `legacy_no_declaration` | `(True, True, True, None)` — via `_DEFAULT_OUTPUT_TYPE` |
| `illegal_declaration` | fail-closed: `PLUGIN_OUTPUT_TYPE='regression' is not a legal output contract (expected one of: classifier, regressor)` |
| `declaration_shape_mismatch` | `Forward output shape (1, 64) does not match expected (1, 256, 64)` |

The error strings carry no filesystem path, so the golden is portable
across checkouts (CLAUDE.md portability rule).

**The synthetic legacy fixture, and why the golden alone was not enough.**
The corpus declares `PLUGIN_OUTPUT_TYPE` universally, so nothing on disk
exercises `_DEFAULT_OUTPUT_TYPE`. `legacy_no_declaration` in the golden
proves the *verdict*; `test_legacy_undeclared_plugin_still_resolves_through_the_fallback`
proves the *reason* — it asserts the module genuinely declares nothing, and
adds the mirror negative (an undeclared plugin emitting the **regressor**
shape must be rejected). Without the mirror, "the fallback is classifier"
and "the fallback is whatever the model emits" would be indistinguishable.

**Baseline 3 — prior-plugin loadability (OD-S4-3).** Enumerated
mechanically at run time from `agent_generated/models/`; **no count is
pinned**, because the directory is live and gitignored and grows with every
chain run (parent §18). Observed at Checkpoint 0:

```text
plugin corpus: 89 files, 89 registered, 0 failed
census: 89 examined, 89 declare PLUGIN_OUTPUT_TYPE, 0 lacking,
        0 unparseable, classifier 86 / regressor 3
```

This **matches the design-time audit exactly** (§5: 89/89/0/0/0, 86/3), so
the corpus has not drifted between freeze and implementation. The oracle
skips with an explicit reason when the corpus is absent — CI runners have
none, and the requirement is declared rather than papered over.

**Validation.**

```text
command: .venv/bin/python -m pytest tests/unit/agent/ml_code_validator_agent \
                                    tests/unit/agent/ml_model_implementor -q
result:  327 passed in 3.03s   (rc=0, read from the log)
```

No pre-existing failure in either directory; the 327 includes the whole
existing implementor/validator suite, so the new baselines coexist with
`pb5_*`/`pb6_*` and `test_output_contract_end_to_end.py` unchanged.

### 17.3 C2 — validator contract transport (no behaviour change)

**The open question C2 posed, and how source answered it.** The design left
one decision to implementation: *"whether the contract rides the
implementor's output or is passed by the orchestrator"*.

```text
Previous assumption:
  either route is acceptable; pick whichever is smaller.

Audit evidence:
  CLAUDE.md's node-communication rule: every field a downstream node needs
  must be present in an upstream node's OUTPUT schema and mapped by the
  protocol; the protocol is the ONLY place field mapping happens.
  workflows/model_exploration.py:2419 builds ValidatorInput purely from
  ImplementorOutput plus orchestrator scalars.

Corrected understanding:
  the orchestrator route would create a second path into the validator that
  the protocol cannot see — precisely the hidden edge the triad forbids.
  It is also the WEAKER property: it hands the validator a second read of
  the task config, where the output-echo hands it the declaration the
  implementor ACTUALLY generated against.

Implementation consequence:
  ImplementorOutput gains the field; the protocol maps it; the workflow call
  site at :2419 needs NO change (a bounded deviation from C2's plan, which
  listed it).

Validation consequence:
  the transport is provable by value at both ends — producer echo and
  protocol hop — and a severed hop reds at whichever end broke.
```

**Files changed**

| File | Change |
|---|---|
| `agent/schemas/implementor.py` | `ImplementorOutput.model_io_contract: ModelIOContract \| None`, default `None` |
| `agent/schemas/validator.py` | `ValidatorInput.model_io_contract: ModelIOContract \| None`, default `None` |
| `agent/schemas/protocols/ml_model_impl_to_ml_model_valid.py` | `local_all_fields` maps it verbatim; docstring field inventory updated; `database_all_fields` placeholder untouched |
| `nodes/ml_model_implementor/ml_model_implementor.py` | **both** `ImplementorOutput(...)` sites echo `inp.forward_contract.model_io` — the main path (`:1808`) and the **Branch-B reuse path** (`:1657`) |

**The Branch-B site is not incidental.** A reused plugin is still validated
against this run's declaration. Echoing only on the main path would have
dropped the validator to the legacy path for every reuse iteration — a
TIDMAD-invisible defect, because there the legacy fallback and the
derivation agree.

**Production reachability confirmed, not assumed.** `workflows/task_config.py:161-190`
returns the RESOLVED contract (`contract.model_dump(mode="json")`), and
`workflows/model_exploration.py:2398` rebuilds it as
`ForwardContract(**_task_cfg["forward_contract"])`. Executed against the
shipped config:

```text
model_io present: True   cardinality: 256   semantic: categorical
input [B, T] int64   ->   output [B, 256, T] float32
```

So `inp.forward_contract.model_io` is genuinely populated in production —
this is not a seam waiting for a future caller.

**Tests added**

- `tests/unit/agent/protocols/test_step04a_model_io_transport.py` — §15.1
  rows 1, 2 and 4. Assertions are **by value**, never `is not None`: "a
  contract is present" is satisfied by a substituted one.
- `TestOutputCorrectness::test_step04a_emits_the_contract_it_generated_against`
  and `..._legacy_prose_only_input_emits_no_contract` in
  `test_implementor_agent.py` — the PRODUCER end, run through the real node
  with a mocked bridge.

Both use a declared cardinality of **16**, not 256, for a specific reason:
the legacy fallback produces 256 anyway, so a TIDMAD-valued assertion could
not distinguish a working transport from a severed one.

**A pin fired, and was edited rather than relaxed.**
`tests/unit/agent/schemas/test_pr_e_stage_contract_pins.py` failed on both
new fields. Diagnosis: **the guard working as designed** — its own docstring
requires the hardcoded key sets to be edited in the same commit as any field
addition, so that a silently added downstream-visible field is impossible.
Both literals were updated with an attributing comment and the module
docstring records the Step-04a addition. No assertion was weakened.

**Mutation evidence** (caches cleared; site counts asserted before each
mutation; restored from a file copy, **not** `git checkout` — the first
attempt used `git checkout` and reverted the uncommitted production edit
along with the mutation):

| # | Mutation | Sites | Expected | Observed |
|---|---|---|---|---|
| 1 | delete `model_io_contract=output.model_io_contract` from `local_all_fields` | 1 | transport tests red | **3 failed, 1 passed** — the row-1 legacy test correctly stayed green |
| 2 | delete the producer echo from both `ImplementorOutput(...)` sites | 2 | producer test red | **1 failed, 59 passed** |

Both behaviour-changing. Baseline restored and re-verified green.

**Validation.**

```text
command: .venv/bin/python -m pytest tests/unit/agent/protocols \
           tests/unit/agent/ml_code_validator_agent \
           tests/unit/agent/ml_model_implementor tests/unit/agent/schemas \
           tests/unit/agent/test_output_contract_end_to_end.py -q
result:  810 passed in 7.57s, rc=0
```

C2 acceptance: Checkpoint-0 validator verdicts **byte-identical** (the C0
golden test is inside that run); `pb6_*` unchanged; the contract is
compared by value, not by presence. `_PROBE_NUM_CLASSES` still governs the
probe — behaviour is deliberately unchanged at this milestone.

### 17.4 C3 — the validator probe derives from the contract

**FU-A-1 is discharged.** `grep -rn "_PROBE_NUM_CLASSES" nodes/ agent/ tests/`
returns nothing.

#### 17.4.1 A shared recipe module, not two copies

New: `agent/skills/model_io_probe_skill.py` — the Step-04 probe-recipe
authority, consumed by the validator now and by the implementor at C4/C5.
Placed as a flat module under `agent/skills/` following the
`forbidden_pattern_skill.py` precedent the validator already imports.

Why shared rather than one copy per node: the implementor generates the
artifact the validator validates. Two copies of "how do I realize this
declaration" are two authorities, and the way that fails is silent — the
implementor emits a candidate its own generated test accepts and the
validator then rejects.

Contents, split strictly along the design's boundary:

| Symbol | Kind |
|---|---|
| `realize_shape` | DERIVE — rank, axis order, fixed extents |
| `expected_output_shape` | DERIVE + the fail-closed of §15.1 row 3 |
| `input_index_extent` | DERIVE from `class_cardinality` |
| `build_model_input` | DERIVE shape + dtype; reuses the EXISTING dtype authority |
| `PROBE_BATCH = 1`, `PROBE_SYMBOLIC_EXTENT = 64` | DECLARE — Step-04 recipes |

The dtype is resolved through
`execute_tools.model_input_dtype.resolve_model_input_dtype` with this
site's historical `int64` preference — **not** a second dtype mapping.
`nodes/ -> execute_tools/` is established (four existing nodes import it).

#### 17.4.2 The design question C3 did not pre-answer, and how it was resolved

```text
Previous assumption:
  "derive the expected output shape from the contract" is unambiguous.

Audit evidence:
  the shipped probe derives the FORM from the PLUGIN's own
  PLUGIN_OUTPUT_TYPE (ml_code_validator_agent.py:415-433, the V21 PR-A2
  correction), which parent §2.2 explicitly records as a Stage-A precedent
  ("already name-blind"). Three plugins in the live corpus declare
  `regressor` while the shipped task contract is categorical, and they
  validate today.

Corrected understanding:
  deriving the FORM from the task contract would start rejecting those
  three — a verdict change under TIDMAD, i.e. a breach of the frozen §5
  parity row "validator verdicts on fixture plugins: identical".
  So: the plugin's DECLARATION selects the form; the CONTRACT supplies
  every fact inside it.

Confirmation from the design itself:
  C3 §6's third edge case — "contract explicitly supplied but cardinality
  None while the declared semantic is classifier -> typed failure" — is
  only reachable under this reading. If the contract chose the form, a
  classifier declaration under a continuous contract would simply produce
  the continuous shape and no typed failure could ever arise.

Implementation consequence:
  the resolution table below.

Validation consequence:
  `test_a_regressor_candidate_still_passes_under_a_categorical_task` pins
  the precedent that forced it.
```

| Contract semantic | Declared form | Expected shape |
|---|---|---|
| categorical | `classifier` | the declared output shape |
| categorical | `regressor` | the same, class axis dropped |
| continuous | `regressor` | the declared output shape |
| continuous | `classifier` | **`ProbeConstructionError`** (§15.1 row 3) |

#### 17.4.2a Authority reconciliation with Step-03 §8b — OPERATOR AUDIT

**The question** (operator, 2026-08-14, raised as the one merge-blocking
semantic check): for an explicitly supplied `ModelIOContract`, is a
candidate's `PLUGIN_OUTPUT_TYPE`

- **(A)** a derived projection that must AGREE with
  `ModelIOContract.output_semantic` — in which case the table above is a
  semantic bug and its tests pin the wrong behaviour; or
- **(B)** an intentionally independent per-candidate formulation choice that
  the contract only parameterizes?

**Answer: (B)** — and it is not a Step-04 invention. It is Step-03's own
documented precedence pattern, which Step 03 states explicitly and anchors on
the very lookup that returns `PLUGIN_OUTPUT_TYPE`.

**What §8b actually forbids.** Read at
`step_03_model_loss_contract.md:599-616`:

> *"Legacy `Proposal.output_type` and the plugin-loader field may persist as
> **compatibility views** during migration. What must not exist is normalized
> tensor semantics **plus** an independent competing `output_type` authority.
> Exactly one authority must answer **"what output semantics does this model
> have"**."*

The scope is **one model**. It forbids two competing answers *for the same
model*, not a per-model declaration differing from the task's.

**Step 03 states the precedence itself** (`:1795-1810`), for dtype:

> *"A6 shows `fcnet` is fed float32 while every other builtin is fed an
> integer, **under the SAME task**. One task-level contract cannot express
> both… Admissibility is resolved with a documented PRECEDENCE, **mirroring
> `plugin_loader.get_output_type`'s builtin-then-registry lookup**: 1. the
> model's OWN declaration, when it has one — a model whose requirement
> genuinely differs; 2. otherwise the TASK contract… **Not two authorities:
> one lookup, and the task contract answers for every model that does not
> override.**"*

Three things follow, and the third is decisive:

1. Step 03 already accepts that a model's own declaration may differ from the
   task contract *under the same task*.
2. It classifies that as **one lookup with precedence**, explicitly *"not two
   authorities"*.
3. It names **`plugin_loader.get_output_type`** — the lookup that returns
   `PLUGIN_OUTPUT_TYPE` — as the **pattern it is mirroring**. Step 03 treats
   per-model output-type lookup as the established precedent, not as the
   violation.

**Corroborating source**: §8c keeps builtin `fcnet` at `hybrid` under the
shipped categorical task and forbids inventing tensor semantics for it. If the
task contract dictated every model's output semantics, `fcnet` would be a
standing contradiction Step 03 chose to preserve rather than resolve.

**Where each authority is sole, in this PR's implementation:**

| Question | Sole authority |
|---|---|
| what output semantics does **this task** declare? | `ModelIOContract.output_semantic` — nothing else answers it |
| what output semantics does **this model** have? | that model's own `PLUGIN_OUTPUT_TYPE` (or `_DEFAULT_OUTPUT_TYPE`) — the contract never overrides it |
| cardinality, rank, axis order, dtype, extents | `ModelIOContract` — the declaration never supplies any of these |

So `output_type` is **not** a competing answer to a contract-owned question:
it selects *which form of the declared contract applies*, and every fact
inside that form still comes from the contract. The boundary is enforced, not
merely asserted: a declared form the contract cannot supply the facts for
(`classifier` under a continuous contract) **fails closed** rather than being
guessed — which is precisely what keeps this a precedence rather than an
independent authority.

**Machine-checked, not prose-only.**
`test_step04a_stage_b_ladder.py::TestOutputSemanticsAuthority` pins both
halves — the contract never supplies the FORM, the declaration never supplies
a CONTRACT-OWNED FACT — plus the fail-closed boundary between them. The
operator's own point applies here: a green suite cannot prove authority
assignment, so the rule is now named in a test rather than left implicit in
behaviour.

**Consequence: no code change.** The implementation stands as written; this
subsection is the required reconciliation.

**Recorded limitation (out of 04a scope, deliberately).** Nothing checks that
a candidate's chosen form is *scientifically appropriate* for the task — a
`regressor` candidate under a categorical task is accepted, as it is on
master. That is an admission/composition question, and roadmap Step 12 owns
generic bound-task semantics. 04a neither introduces nor worsens it.

#### 17.4.3 A limitation, recorded rather than papered over

Under a **continuous-output** contract with an **integral** input, the
contract carries no value-range fact: cardinality is derived from the
output class axis, and `AxisRole` describes extents, not value domains.
There is nothing to derive.

Considered and rejected: falling back to `256` (reintroduces the literal
this PR removes) and failing closed (would make rung 6.5-C unimplementable).
Chosen: `_UNIVERSAL_INDEX_EXTENT = 1`, i.e. index `0` only — the single
extent admissible under *every* vocabulary size. The probe still proves
shape and gradient flow; it does not exercise index-dependent behaviour for
such a task. **This is not a §14 stop condition** — the probe IS expressible
without growing Model-I/O — but it is a real limitation and is carried in
§17.7.

Where a class alphabet IS declared, the probe draws indices from it. That
is the shipped behaviour (today's `randint(0, 256, ...)` uses the output
class count as the input index range) and the Dataset Profile's
`ValueEncoding.num_classes` is cross-validated against the same cardinality
(Step-03 §4b), so the two are one fact rather than two.

#### 17.4.4 Mutation evidence — including one that SURVIVED

Caches cleared before each; site counts asserted; restored from file copies.

| # | Mutation | Result |
|---|---|---|
| A | `realize_shape` ignores the declared `fixed` extent, re-hardcodes `256` | **4 failed, 6 passed** |
| B | replace the row-3 fail-closed with a fall-through | **1 failed, 9 passed** — and instructively: the candidate was then rejected as `Forward output shape (1, 256, 64) does not match expected (1, 64)`, i.e. **for the wrong reason** (design §9 failure class 3) |
| C | `run()` stops forwarding `inp.model_io_contract` | **SURVIVED — 130 passed** |

**C is the finding of this milestone.** Every other test in the directory
calls `_check_instantiation_and_gradient` directly, so none crossed the
production wiring: the helper could be perfect and never reached. This is
exactly the reachability evidence CLAUDE.md requires for an extracted
boundary.

Closed by `TestTheProductionPathActuallyUsesTheContract`, which runs the
real `MLCodeValidatorAgent.run()` against a **16-class** candidate — it
validates only if the declaration travelled from `ValidatorInput` to the
probe, because the legacy geometry feeds indices up to 255 into a
16-symbol embedding and raises. Its negative twin asserts that same
candidate is rejected with no contract, so the positive cannot pass by
luck.

Mutation C re-run after the fix: **1 failed, 131 passed**, with the
diagnostic `Forward pass failed: index out of range in self`. Restored:
**132 passed**.

#### 17.4.5 Deviations

- **Test call sites did not need updating.** C3's plan expected "~13 test
  call sites" to change. The new parameter is optional and defaults to
  `None`, which IS §15.1 row 1, so every existing caller keeps the legacy
  path with no edit. Fewer churned tests, and the legacy path gains real
  coverage from callers that were not written for it.
- **`_PROBE_NUM_CLASSES` renamed, not simply deleted.** The legacy geometry
  must survive for row 1, so the constant lives on as
  `_LEGACY_CLASSIFIER_PROBE_CLASSES` / `_LEGACY_PROBE_TIME_STEPS`. Renamed
  rather than kept so C3's acceptance grep is literally satisfied and the
  constant cannot be mistaken for an authority.

### 17.5 C4 — implementor self-check and generated artifacts derive

Three surfaces inside the implementor restated the class count. Because all
three said `256` and the task said `256`, nothing could distinguish agreement
from coincidence.

| Surface | Now |
|---|---|
| `_smoke_test_plugin` self-check | probe input + expected shape from the shared recipe module |
| `_OUTPUT_CONTRACT_COMMENTS` / `_render_output_contract` | both comment strings RENDERED from the declaration |
| `TEST_TEMPLATE` | `{num_classes}` and `{index_extent}` render-time placeholders |

**One rule, two renderings.** `expected_output_shape` was refactored to sit on
a new `declared_output_tensor(contract, declared_form) -> TensorContract`.
The validator realizes that tensor into a concrete probe shape; the
implementor renders the same tensor into the prose comment it writes into
every generated plugin. That is what makes "documents one contract, validated
against another" structurally impossible rather than merely tested for.

**Call sites threaded** (all read `inp.forward_contract.model_io`, which
already existed — no new transport, per design §15):
`_assemble_plugin`, `_assemble_test`, `_smoke_test_plugin`, and the
`description.md` writer.

#### 17.5.1 Stage-A parity result

- **Generated plugin bytes: byte-identical** under TIDMAD, for both
  `classifier` and `regressor` — C4 acceptance criterion 1 met, verified by
  the Checkpoint-0 goldens which were NOT regenerated.
- **Generated test file: one delta, comment-only.** The golden was
  regenerated in the same commit; the complete diff is two added comment
  lines. Every numeric value is unchanged:

  ```diff
   # Expected shape follows the plugin's DECLARED contract, so a regressor
  -# is not judged against the classifier shape (V21 PR A3).
  +# is not judged against the classifier shape (V21 PR A3). The class count
  +# is rendered from the task's Model-I/O contract (Step 04a), not fixed.
   expected = (
       (2, 256, config.segmentation_size)
  ```

  Additionally pinned by
  `test_the_legacy_path_renders_the_same_test_file_under_tidmad`, which
  compares the two PATHS to each other — stronger than comparing each to the
  golden, because it also catches both drifting together.

#### 17.5.2 Two existing pins fired; both were resolved by editing, not relaxing

**1. `TestDeferredScope::test_deferred_hardcodes_still_present`.** It guarded
the self-check docstring's `"[1, 64] int64 → expected [1, 256, 64] float32"`
as a *deliberately deferred* hardcode. Step 04a is the PR that deferral was
waiting for (design §2 row `ml_model_implementor.py:85`), so the entry was
removed exactly as A3 and A4 removed theirs — with the reason recorded inline.

Disposition: **REWRITE**, not delete. The class now asserts the property that
REPLACED the deferral: the self-check body contains no bare class-count
literal, and `build_model_input` / `expected_output_shape` are genuinely
wired. Scoped to the function body, so the two sanctioned
`_LEGACY_SELF_CHECK_*` constants (which implement §15.1 row 1) do not trip it.

**2. `test_generated_test_file_matches_the_declared_contract`** called
`TEST_TEMPLATE.format(model_name=...)` directly and broke on the new
placeholder. Diagnosis: the test reached past the production renderer into
the raw template, so it was testing a string the node never emits.
Disposition: **UPGRADE** — it now renders through `_assemble_test`, the
function the implementor actually calls, which is where the derivation
happens.

#### 17.5.3 Mutation evidence

| # | Mutation | Result |
|---|---|---|
| D | `_render_output_contract` re-hardcodes `"256-class classification"` | **1 failed, 220 passed** |
| E | `_assemble_test` re-hardcodes `num_classes = 256` | **1 failed, 220 passed** |

Restored: **221 passed**.

#### 17.5.4 A note on the generated test's `{num_classes}` under a continuous task

`num_classes` and `index_extent` differ only for a task declaring no class
alphabet. There the generated test's classifier branch is **unreachable by
construction**: `_render_output_contract` has already refused to assemble a
classifier plugin under such a contract (§15.1 row 3), so no plugin exists
whose `PLUGIN_OUTPUT_TYPE` could select that branch.

#### 17.5.5 Validation

```text
command: .venv/bin/python -m pytest tests/unit/agent/ml_model_implementor \
           tests/unit/agent/ml_code_validator_agent tests/unit/agent/protocols \
           tests/unit/agent/test_output_contract_end_to_end.py -q
result:  461 passed in 6.96s, rc=0
```

A wider run (`tests/unit/agent tests/unit/execute_tools tests/unit/ml_models`)
reported **4984 passed, 1 skipped** in 324s at the C3 state, but it overlapped
the first C4 edits, so it is recorded as context and **not** quoted as
milestone evidence. Checkpoint D re-establishes it from a clean head.

### 17.6 C5 — the custom-loss probe recipe, and rung 6.5-D

**The capability gap, measured.** `_dummy_tensor_validate_loss` built
`torch.randn(2, 256, 100)` against `torch.randint(0, 256, (2, 100))`
unconditionally. Executed on a valid regressor custom loss
(`beta * F.mse_loss(inputs, targets)`), the before/after is:

```text
LEGACY  : forward(inputs, targets) raised on dummy tensors: RuntimeError:
          The size of tensor a (256) must match the size of tensor b (2) at
          non-singleton dimension 1. The forward must accept
          inputs=[2, 256, 100] float32 and targets=[2, 100] int64.
DERIVED : None
```

That is C5 acceptance criterion 2 — *"the same loss is still rejected on
master; 6.5-D reds without this commit"* — recorded as the literal strings
rather than as a claim. Note the failure reason: a **shape accident**, not
anything about the loss (design §9 failure class 3).

**What changed, and what deliberately did not.**
`build_loss_probe_pair(contract)` keys the pair on the declared output
semantic per design §4's table. `B = 2` and `T = 100` remain recipe
constants. The failure message now names the pair actually built, so it
cannot go stale against the tensors.

**Loss LEGALITY is untouched.** Verified at source
(`ml_models/models_format_sandbox.py:592`): `custom` is deliberately
permitted for every output contract, because the plugin's own forward raises
at training time if its shape contract is violated. No second `LossContract`
was created and `validate_semantic_loss_compatibility` was not modified.

#### 17.6.1 The rung closes at the validator, per §6.2

`test_a_regressor_custom_loss_candidate_is_generated_and_ACCEPTED` drives:

```text
regressor ModelIOContract + valid custom loss
  -> real MLModelImplementor.run()      (bridge mocked, recorded responses)
  -> real local_all_fields protocol
  -> real MLCodeValidatorAgent.run()
  -> ACCEPT   (instantiation, gradient, output_type, passed)
```

**Nothing on the validator side is stubbed** — its pytest subprocess really
executes the generated test file, so the candidate's own test is part of the
evidence rather than something the rung assumes away. An earlier draft
stubbed `_run_tests`; that stub was removed once the unstubbed path was
confirmed to work, because the weaker version would have hidden a broken
generated test.

**Atomicity.** `test_the_declaration_is_6_5_c_s_baseline_unchanged` asserts
mechanically that the contract this rung runs under IS
`regressor_model_io()` — 6.5-C's established declaration — and that the only
other axis differing is the custom loss. §6 forbids 6.5-D from varying output
semantic and loss capability at once, and this makes "somebody fixed the rung
by also changing the declaration" a test failure.

#### 17.6.2 Negatives retained under BOTH semantics (§6.2)

The lower-level negatives protect failure semantics the capability assertion
does not cover, and are now parameterized over both semantics:

| Case | Detector |
|---|---|
| detached graph (finite scalar, `requires_grad=False`) | only `backward()` catches it |
| non-finite scalar | the finiteness check |
| classifier custom loss | unchanged — asserted between the two paths |

#### 17.6.3 Mutation evidence

| # | Mutation | Result |
|---|---|---|
| F | revert `build_loss_probe_pair` to the classifier-only pair (pre-Step-04a behaviour) | **3 failed, 6 passed** — including the capability rung itself |

Restored: **230 passed** in the implementor directory.

#### 17.6.4 Validation

```text
command: .venv/bin/python -m pytest tests/unit/agent/ml_model_implementor -q
result:  230 passed in 5.03s, rc=0
```

### 17.7 C6 — prompt surfaces derive; the ONE authorized golden delta

#### 17.7.1 OD-S4-1 — the capacity authority

The shipped bullet read
`- GPU budget: <10 GB VRAM, <100M parameters for initial exploration.`
while the proposer has quoted the **live** cap since Step 01. Two nodes in one
pipeline were sizing for machines ~2.5x apart, and the parameter ceiling had
no authority behind it at all.

**One rule, not two.** `HardwareContext.effective_cap_gb(vram_budget_gb)` was
extracted into `core/hardware_context.py` and BOTH consumers now call it — the
proposer's `[HARDWARE CONTEXT]` block and the implementor's new bullet. The
three regimes collapse to `min(budget, usable)`:

| regime | effective cap |
|---|---|
| PHYSICAL (no budget) | `usable_cap_gb` |
| BUDGET (budget <= usable) | `vram_budget_gb` |
| PHYSICAL VETO (budget > usable) | `usable_cap_gb` |

The proposer refactor is **byte-neutral** — verified before proceeding:
`tests/unit/agent/ml_model_proposal_agent tests/unit/core` → **2997 passed,
2 skipped**, `pb3_*`/`pb4_*` unmoved.

**Transport**: `ImplementorInput` gains `hardware_context` and
`vram_budget_gb`, mirroring `ProposalInput`'s fields exactly, wired at the
same workflow site that already sets the proposer's. **No task-config field
for capacity** — machine capacity is a property of the machine (parent §5).

**Degradation**: no manifest or `device_available=False` → a defined,
magnitude-free bullet. A literal there would be the stale ceiling
reintroduced through the back door, so the test asserts the *absence of any
magnitude*, not a specific alternative string.

#### 17.7.2 The attributed golden delta

**Exactly one golden file, exactly one line:**

```diff
--- tests/unit/agent/ml_model_implementor/goldens/pb5_reasoning_system.txt
@@ -10,7 +10,7 @@
 Task type: classification (per-timestep 256-class).
-- GPU budget: <10 GB VRAM, <100M parameters for initial exploration.
+- GPU budget: size the initial architecture conservatively. The VRAM engine
+  rejects any configuration whose predicted peak exceeds this run's effective
+  cap, and a rejection consumes a tuner attempt with no scored round.
```

(rendered as a single line in the file). `git status` over the golden
directories confirms **`pb5_reasoning_system.txt` is the only modified
golden**; `pb6_*` and `pb9_*` are untouched.

The golden captures the **magnitude-free** form because its fixture supplies
no hardware — which is correct and deliberate: a golden carrying a live GB
value would be host-dependent, and CLAUDE.md forbids a test whose result
depends on which machine ran it.

`test_only_the_capacity_bullet_moved_in_the_pb5_golden_set` makes the
attribution mechanical rather than a reviewer's promise: it enumerates the
`pb5_*` set and asserts the capacity bullet appears in exactly one file.

#### 17.7.3 The detector fired on a legitimate case — scoped, not weakened

Reusing Step 01's `_numeric_capacity_literals` over the implementor templates
flagged one surviving snippet:

> *"a `[T, T]` buffer at `T=16000` costs 1 GB of RAM; 4 layers × optimizer
> moments = >10 GB — the process will be OOM-killed BEFORE training starts"*

Diagnosis: **not a capacity claim.** It is worked arithmetic about an
ALGORITHM's growth — true on any host, and it does not tell the LLM how large
a model it may build. The detector is a deliberate over-approximation
(a magnitude near capacity words) and cannot make that distinction.

Rejected: rewording the prompt — that would be a **second** LLM-visible delta,
and OD-S4-1 authorizes exactly one. Chosen: allowlist the snippet **by
content**, so a new literal appearing beside it still fails, plus a companion
test asserting the allowlisted snippet is still present and still *singular*
— otherwise the exemption could silently widen.

#### 17.7.4 The validator prompt

`VALIDATOR_REVIEW_SYSTEM_PROMPT`'s two shape tokens are now placeholders
filled by `_build_review_system_prompt(contract)`, using the same
`declared_output_tensor` rule the probe uses. A prompt naming `[B, 256, T]`
for a 16-class task would instruct the reviewer to reject every correct
candidate, and nothing else would catch it: the deterministic probe would
pass the candidate and the reviewer would fail it, looking exactly like a
model-quality judgement (§9 failure class 6).

A continuous task renders `(not declared by this task)` for the classifier
form rather than inventing an alphabet — the probe fails closed on that case,
and the prompt must not promise what the probe would refuse.

`pb6_*` stays **byte-identical**: its fixture supplies no contract, so it
exercises the legacy path, and TIDMAD is separately asserted equal to the
legacy path.

#### 17.7.5 Mutation evidence

| # | Mutation | Result |
|---|---|---|
| G | re-bake `<10 GB VRAM, <100M parameters` into the template | **3 failed, 8 passed** |
| H | reviewer prompt ignores the contract and keeps the shipped shapes | **2 failed, 134 passed** |

Restored: 11 passed / 136 passed respectively.

#### 17.7.6 Validation

```text
tests/unit/agent/ml_model_implementor            -> 241 passed
tests/unit/agent/ml_code_validator_agent         -> 136 passed
tests/unit/agent/ml_model_proposal_agent + core  -> 2997 passed, 2 skipped
```

### 17.8 C7 — CHECKPOINT B: the Stage-B ladder

`tests/unit/agent/test_step04a_stage_b_ladder.py`.

**Why a rung is more than a parameterized test.** A test that a 16-class task
produces 16-class artifacts proves the code reads a number. A rung proves
that varying exactly one declared axis moves exactly the consumers that axis
owns **and nothing else** — otherwise it would keep passing if a second axis
silently changed with it.

Each rung therefore (1) varies one axis against its own baseline, (2)
**machine-checks** atomicity with the 02b/02c `_diff_paths` precedent rather
than asserting it in prose, and (3) asserts the unvaried consumers are
unchanged.

| Rung | Baseline | Atomicity check | Result |
|---|---|---|---|
| **6.5-A** cardinality | TIDMAD | diff == `["output.axes.1.fixed"]` — literally one path | **PASS** |
| **6.5-C** output semantic | TIDMAD | every differing path is under `output.axes.`; the input declaration is asserted *identical* | **PASS** |
| **6.5-D** loss capability | **6.5-C's regressor** | diff against `regressor_model_io()` == `[]` — the baseline IS 6.5-C's, not TIDMAD | **PASS** |

**The consumer set is diffed, not spot-checked.** 6.5-A asserts the exact SET
of consumers that moved:

```text
{expected_output_shape, probe_index_extent, plugin_forward_comment,
 plugin_output_comment, generated_test, review_prompt}
```

and that `probe_input_shape` did **not** — the input carries no class axis, so
a cardinality change moving it would mean the derivation reads the class
extent for something it does not own.

**Residue assertions are block-scoped**, per Step 01's lesson: `256` is
checked absent from the contract-derived outputs only, never from a whole
prompt (the shipped `task_description` legitimately contains `[B, 256, T]`,
so a whole-prompt assertion is unsatisfiable and is a test-design error).

**6.5-D is referenced, not duplicated.** Its capability half lives in
`ml_model_implementor/test_step04a_regressor_custom_loss_capability.py`
because it must run the real implementor and the real validator (§6.2). This
module owns only its atomicity obligation — the one rung whose baseline is
another rung rather than TIDMAD.

**6.5-B is present but labelled NOT a rung.** `PROBE_SYMBOLIC_EXTENT 64 → 128`
is retained as probe-recipe robustness: it checks the realizer honours the
recipe length at input and output *simultaneously*, so a realizer that
hardcoded 64 on one side would desynchronise them. It is explicitly not a
semantic contrast and must never be reported as one — it would pass whether
or not a consumer re-hardcoded its literal, which is exactly why §6.1 removed
it from the required ladder.

#### 17.8.1 Rung mutation coverage

Each rung's "reds when its consumer re-hardcodes the old assumption"
obligation is discharged by the mutations already recorded, which are the
same consumers the rungs diff:

| Rung | Mutation that reds it | Recorded |
|---|---|---|
| 6.5-A | `realize_shape` re-hardcodes `256` (A); plugin comment (D); generated test (E); reviewer prompt (H) | §17.4.4, §17.5.3, §17.7.5 |
| 6.5-C | row-3 fail-closed removed (B); reviewer prompt (H) | §17.4.4, §17.7.5 |
| 6.5-D | loss pair reverted to classifier-only (F) | §17.6.3 |

**Validation**: `tests/unit/agent/test_step04a_stage_b_ladder.py` → **11 passed
in 1.20s**, rc=0.

### 17.9 C8 — node docs, Gates, Checkpoint C

#### 17.9.1 Node documentation (doc-sync rule)

Both node `.md` files described a fixed `[1, 256, 64]` probe and a fixed
`[B, 256, T]` contract — no longer what either node does.

- `ml_code_validator_agent.md`: protocol inventory now lists
  `model_io_contract` (mapped verbatim, never re-resolved);
  `instantiation_passed` / `output_type_valid` describe the derived shape and
  the declaration-selects-form rule including the fail-closed case; check #6
  names the probe skill and separates contract-owned facts from Step-04
  recipes.
- `ml_model_implementor.md`: workflow-populated table gains
  `task_description`, `forward_contract` (with `model_io` as the authority),
  `hardware_context`, `vram_budget_gb`; output table gains
  `model_io_contract`; smoke-test and output-contract sections describe
  derivation; the GPU note clarifies `hardware_context` is read only to
  render the capacity bullet, never to select a device.

Every documented default was quoted against the merged schema source.

#### 17.9.2 Static / type validation — an environment limitation, recorded

`ruff check` and `ruff format --check` are green repo-wide.

**`pyright` cannot run in this environment.** The local Node is
**v10.19.0**; the vendored pyright bundle requires a modern Node and dies with
`SyntaxError: Unexpected token =` before analysing anything. Per CLAUDE.md's
environment-assumptions rule this is recorded rather than claimed:

> **pyright is NOT validated locally for this PR. Exact-head CI is the only
> environment that runs it, and it is a blocking CI step.**

No attempt is made to describe the local run as a pass.

#### 17.9.3 Planned Gates — recorded BEFORE launch

| Gate | Command shape | Question it answers | Expected |
|---|---|---|---|
| **Gate 1** | `run_one_iteration.py --is_pseudo_training --llm_config llm_configs/openai_tiered_pro.json --max_rounds 1 --max_proposal_attempts 3 --max_epochs 1 --data_scope 4-9 --health_gate_files 4,5,6,7,8,9`, cold-start | does a REAL LLM, given the changed implementor/validator prompts, produce a candidate that compiles and passes the (now contract-derived) dummy-tensor and probe checks? | ~2-5 min |
| **Gate 2** | the standard's canonical bounded chain command, `openai_tiered_pro.json` | does the real path execute end to end — real LLM, real candidate, real training, real inference, real scoring, a finite result? | bounded |

**Gate 2 is expected to discharge Checkpoint C** in the same run (§7): it
produces the resolved contract, the production implementor's artifacts and
the production validator's report. No duplicate chain will be launched merely
because the two have different names.

#### 17.9.4 Gate 1 — **PASS**

Three argv-level guards were cleared first. **None was a defect**; each is a
governance declaration the chain refuses to default:

| Refusal | Resolution |
|---|---|
| `one of --start_iteration / --iteration is required` | supplied `--start_iteration 1` |
| `a formal launch must declare --healthgate_mode and --result_authority` | declared both explicitly |
| `healthgate_mode=observe_only, but these gates still invalidate` | used `blocking` / `scientific` — `_chain_common.sh:67-68`'s own defaults, i.e. what the standard's canonical command uses |

**A harness caveat worth recording**: the background-task notification reported
*"exit code 0"* for the two runs whose real exit status was **2**. The verdict
was taken from the captured `GATE1_RC=` line, never from the wrapper — the same
failure mode CLAUDE.md records for `pytest | tail`.

```text
command: run_one_iteration.py --workspace /tmp/s04a_gate1_<ts> \
           --run_name s04a_gate1 --start_iteration 1 --max_rounds 1 \
           --max_proposal_attempts 3 --max_epochs 1 \
           --data_scope 4-9 --health_gate_files 4,5,6,7,8,9 \
           --healthgate_mode blocking --result_authority scientific \
           --is_pseudo_training \
           --llm_config llm_configs/openai_tiered_pro.json
cold-start: yes (no --seed_paths)
model:      gpt-5.5 across every role
```

**Live hardware in this run**: `NVIDIA GeForce RTX 5090`, 31.34 GB total,
**25.07 GB usable cap** — recorded in `iter_001_hardware.json`. This is the
OD-S4-1 finding made concrete: the removed literal (`<10 GB VRAM`) understated
the actual machine by **2.5x**, and the implementor was being told to build for
it.

**Pass criteria (standard §"Gate 1"), all met:**

| Criterion | Evidence |
|---|---|
| LLM call completes without error | 8 real gpt-5.5 calls, `status: ok` throughout, incl. `implementor.reasoning`, `implementor.code`, `validator.code_review` |
| Output passes Pydantic schema validation | `implementor_iter_001.json` and `validation_iter_001.json` written as validated records |
| Generated code compiles + passes dummy-tensor check | `instantiation_passed=True`, `gradient_check_passed=True`, `output_type_valid=True`, `tests_passed=True`, `llm_review_passed=True`, **`passed=True`**, `error_message=None` |

Candidate: `fullspectrum_spectral_gated_tcn_v1`, 1,309,542 parameters,
registered post-validation and promoted to `agent_generated/models/`.

#### 17.9.5 CHECKPOINT C — the live production chain

All three obligations are discharged by **artifacts from this run**, not unit
mocks:

**(i) the real production implementor receives and uses the resolved contract.**
`implementor_iter_001.json` carries the echoed declaration:

```json
"model_io_contract": {
  "output": {"axes": [
      {"role": "batch",    "dimension": {"symbolic": "B"}},
      {"role": "class",    "dimension": {"fixed": 256}},
      {"role": "temporal", "dimension": {"symbolic": "T"}}]},
  "input":  {"dtype": {"admissible": ["int64", "int32"]}}
}
```

**(ii) generated artifacts derive from it.** The written plugin carries

```text
# forward contract: input [B, T] int64 → output [B, 256, T] float32
PLUGIN_OUTPUT_TYPE = "classifier"  # [B, 256, T] → 256-class classification
```

and the written test carries `torch.randint(0, 256, ...)` /
`(2, 256, config.segmentation_size)` **plus the new Step-04a comment** — i.e.
the live artifact is byte-identical to the regenerated golden.

**(iii) the real production validator receives the same declaration and probes
with it.** The candidate reached the validator through the production protocol
and `instantiation_passed=True` — the contract-derived probe built its input
and expected shape from that declaration and the model matched. `tests_passed=True`
additionally means the generated test file really executed and passed.

**CHECKPOINT C: COMPLETE.** Gate 2 will add the real-training half; it does not
need to re-prove candidate creation.

#### 17.9.6 A pre-existing infrastructure defect found by Gate 1 — OUT OF SCOPE

After the validator accepted the candidate, the tuner's pre-phase GPU
measurement failed:

```text
Pre-phase GPU MEASUREMENT FAILED (STOP_INFRASTRUCTURE_FAILURE)
detail: setup failed: RuntimeError: dataset directory unavailable for the
        measurement: None (no silent synthetic fallback — F-1a)
```

**Root cause**, traced rather than assumed:

```text
_chain_common.sh:92        DATA_DIR=""            # --data_dir is OPTIONAL, unset by default
  -> run_one_iteration      --data_dir omitted
  -> ml_hyperparameter_tune_agent.py:787
                            data_dir=getattr(agent_input, "data_dir", None)  -> None
  -> prephase spec           data_dir: null
  -> gpu_measurement_worker_main.py:249
                            fails CLOSED (correctly — F-1a forbids a synthetic fallback)
```

The dataset itself is present and readable (`/home/klz/Data/TIDMAD/`, 423
files); the chain's own launch self-test even reported *"measurable on NVIDIA
GeForce RTX 5090 ... dataset at /home/klz/Data/TIDMAD/"*. The value simply
never reaches the measurement worker unless `--data_dir` is passed, and the
Gate standard's canonical command does not pass it.

**Proven out of scope.** Every file on that path is untouched by this PR:

```text
git diff --name-only e802b810..HEAD  ->  11 production files, none of which is
  core/runtime_control/gpu_measurement_worker_main.py       UNTOUCHED
  nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py  UNTOUCHED
  sdsc_submission_scripts/_chain_common.sh                  UNTOUCHED
  core/runtime_control/probe_production.py                  UNTOUCHED
```

The failure also occurs strictly downstream of everything 04a changes — the
candidate had already been generated, validated and registered.

**Effect on Gate 1: none.** The standard's Gate-1 pass criteria are *"LLM call
completes / output passes schema validation / generated code compiles + passes
dummy-tensor check"*. All three were met and recorded (§17.9.4) before the
tuner ran; Gate 1 explicitly does **not** require training.

**Action taken**: Gate 1 was stopped after its criteria were met rather than
left to burn planner LLM calls on four more rounds of an identical, diagnosed,
non-retryable failure. Gate 2 supplies `--data_dir /home/klz/Data/TIDMAD/`,
which is exactly what that flag exists for — a launch parameter, not a
production change.

**Follow-up for the operator (NOT fixed here, out of 04a's frozen scope)**: the
Gate standard's canonical Gate-2 command omits `--data_dir`, so any Gate-2 run
that reaches pre-phase measurement fails this way. Either the standard's
canonical command should carry `--data_dir`, or the tuner should resolve the
dataset directory from the same authority the launch self-test already uses.

**A second environment note**: the GPU is shared. Nine processes belonging to
other users held 11.3 GB at 91% utilization during this run. That did not cause
the failure above, but it is why Gate wall-times here are not comparable to a
dedicated host.

#### 17.9.7 Gate 2 — **PASS**

```text
command: bash sdsc_submission_scripts/run_chain.sh --mode lilab \
           --workspace /tmp/s04a_gate2_<ts> --run_name s04a_gate2 \
           --num_iterations 1 --max_rounds 1 --max_proposal_attempts 3 \
           --max_epochs 1 --data_scope 4-9 --health_gate_files 4,5,6,7,8,9 \
           --data_dir /home/klz/Data/TIDMAD/ \
           --validation_max_portion 0.01 --validation_max_train_samples 2000 \
           --validation_max_phase_seconds 900 --runtime_watchdog \
           --no-force_formal_round \
           --trial_vram_budget_gb 24 --formal_vram_budget_gb 24 \
           --llm_config llm_configs/openai_tiered_pro.json
cold-start: yes (no --seed_paths)
result:     CHAIN COMPLETE — 1 iterations
```

The standard's Gate-2 purpose is *"verify that the REAL path executes end to
end — real LLM, real candidate, real training, real inference, real scoring, a
finite result … functional validation, **not** an assessment of model
quality."* Each element, with its evidence:

| Element | Evidence |
|---|---|
| real LLM | gpt-5.5 across proposer → implementor → validator → planner → interpreter |
| real candidate | `compact_bidir_gated_dilated_tcn_hf` generated, **validated**, registered, promoted |
| real training | 500 steps, **129.9 s**, `Epoch 0 \| Avg Loss: 3.142136`, checkpoint written |
| real inference | **6 denoised HDF5 files** for files 4-9 (the declared scope), **208.9 s** |
| real scoring | **12.5 s**; per-file score table over the 6 sampled files + aggregate |
| a finite result | `denoising_score = -0.3020596014709346` — finite |

**The candidate collapsed, and that is NOT a Gate-2 failure.** The interpreter
recorded *"all sampled validation files collapsed to only 7 unique int8 values
with output std around 0.331 mV, below the 1 mV threshold"*, the HealthGates
invalidated the round, and the record's status is `failed_mode_collapse`. The
standard and parent §14 are explicit that model quality is out of Gate 2's
scope — a 1-epoch run at `trial_portion 0.01` collapsing is a scientific
outcome. The gate **detecting** it is the framework working, which is what
Gate 2 exists to check.

**The pre-phase measurement succeeded this time**, confirming §17.9.6's
diagnosis: supplying `--data_dir` was the whole difference.

#### 17.9.8 CHECKPOINT D and validation economy

| Item | Status |
|---|---|
| directly affected deterministic tests | green at every milestone (§17.2-§17.8) |
| focused integration | `test_output_contract_end_to_end.py`, the 6.5-D capability rung through the real implementor+protocol+validator |
| independent mutation classes | **8**, one of which SURVIVED and exposed a real reachability gap (§17.4.4) |
| required lint / format | `ruff check` + `ruff format --check` clean repo-wide |
| required type check | **pyright NOT run locally** — Node v10.19.0 cannot execute it (§17.9.2). CI is the only environment, and it is a blocking step |
| exact-final-head CI | see §17.9.9 |
| no local full suite | honoured — none was run (§12) |

**Real-validation budget**: Gate 1 ≈ 9.5 min + Gate 2 ≈ 12.5 min ≈ **22 min
total**, comfortably inside the ~1 hour envelope. Two Gate-1 relaunches were
argv-level refusals costing seconds and no LLM calls.

#### 17.9.9 Prior-plugin loadability — final re-enumeration (OD-S4-3)

| Point | Corpus |
|---|---|
| Checkpoint 0 (pre-edit) | 89 files, 89 registered, 0 failed — 86 classifier / 3 regressor |
| after Gate 1 | 90 / 90 registered |
| **after Gate 2 (final)** | **91 files, 91 registered, 0 failed** — 88 classifier / 3 regressor, 0 lacking `PLUGIN_OUTPUT_TYPE`, 0 unparseable |

The corpus grew by exactly the two candidates this PR's own pipeline produced,
and **every plugin still loads and registers** — including the two generated
through the new contract-derived path. That is OD-S4-3 satisfied on live
evidence, not on a claim.

#### 17.9.10 Exact-head CI — first run RED, and what it caught

Run `31773904920` on `12275662`: **1 failed, 9094 passed, 26 skipped**.

```text
ruff check              success
ruff format --check     success
pyright (strict)        SUCCESS   <- the check with no local signal
pytest                  FAILED    <- 1 test
```

**pyright strict passed**, which is the result §17.9.2 could not obtain
locally. The single failure was:

```text
tests/unit/guardrails/test_no_hardcoded_device_literals.py::...[nodes]
  nodes/ml_model_implementor/ml_model_implementor.py:1066:
    RTX 5090 since Step 01 — so the implementor was being told to build for a
```

**Diagnosis: the guardrail working, and the irony is the point.** The PR whose
whole purpose is removing a stale hardware literal from the implementor's
prompt introduced a hardware literal — a device NAME — into that same module's
docstring, while narrating the removal. `nodes/` is inside the Principle-5
scan set.

**Fix**: the device name and the measured capacity were **removed**, not
annotated. The guardrail does offer an `e.g.`/provenance escape hatch, but
using it here would have kept a device literal in the module, which is exactly
what this PR argues against. The docstring makes its point without naming a
machine, and a note now says why. Guardrail suite re-run locally: **96 passed**.

**Why targeted runs did not catch it**: `tests/unit/guardrails/` is not in the
implementor/validator/protocol/schema set the milestones exercised. This is
the design's own §12 position vindicated on a live example — exact-head CI is
the broad regression authority precisely because a targeted set cannot know
what an unrelated guardrail scans.

---

## 17.10 CHECKPOINT A — mechanical closure at the final head

Every parity row re-verified against the production ancestor `e802b810`, not
against an intermediate state.

**Golden files changed by this PR, in full** (`git diff --name-only e802b810..HEAD -- '*goldens*'`):

```text
tests/unit/agent/ml_code_validator_agent/goldens/s04a_validator_verdicts.json   NEW (Checkpoint 0)
tests/unit/agent/ml_model_implementor/goldens/pb5_reasoning_system.txt          1 line (OD-S4-1)
tests/unit/agent/ml_model_implementor/goldens/s04a_generated_plugin_classifier.txt  NEW (Checkpoint 0)
tests/unit/agent/ml_model_implementor/goldens/s04a_generated_plugin_regressor.txt   NEW (Checkpoint 0)
tests/unit/agent/ml_model_implementor/goldens/s04a_generated_test.txt          NEW; 2 comment lines since
```

Exactly **one pre-existing golden** moved, by exactly the authorized delta.
`git diff e802b810..HEAD -- '*pb6_*' '*pb9_*'` is **empty**.

**Final targeted parity run** (implementor, validator, protocols, schemas,
proposer, lit-review, end-to-end contract, Stage-B ladder, core):

```text
3951 passed, 2 skipped in 73.14s, rc=0
```

**No production change after either Gate.** `git log --name-only e802b810..HEAD`
shows the last commit touching production is `8ed92886` (C6); every commit
after it is tests, docs or ledger, except `efde2b9d`, which changes only a
**docstring** inside `nodes/ml_model_implementor/` (a device name removed for
the Principle-5 guardrail — no behaviour). Neither Gate needs re-running.

---

## 17.11 CHECKPOINT E — PR 04a CLOSED

| Field | Value |
|---|---|
| PR | [#207](https://github.com/Galileo-Sandbox/SIDERIUS/pull/207) |
| Frozen design | `c3d29e73` |
| Implementation base | `3e9728c8` |
| Production ancestor | `e802b810` |
| **Final executable head** | **`d019f94b`** |
| **Merge SHA** | **`6458dd95`** (squash) |
| Exact-head CI | run `31774858601` on `d019f94b` — **success**: ruff · ruff-format · **pyright strict** · pytest |
| Gate 1 | **PASS** (§17.9.4) |
| Gate 2 | **PASS** (§17.9.7) |
| Checkpoint 0 / A / B / C / D | **all complete** (§17.2, §17.10, §17.8, §17.9.5, §17.9.8) |
| Context state | **CLOSED** |

### 17.11.1 What landed

The frozen capability, verified end to end on the live chain:

```text
explicit normalized ModelIOContract
  -> production implementor uses it for every contract-owned Model-I/O fact
  -> generated candidate/artifacts agree with it
  -> production validator receives the SAME declaration via the protocol
  -> probe derives contract-owned facts from it
  -> candidate validated against that declaration
```

plus the capability that was previously impossible: a declared-regressor
custom loss is generated and **ACCEPTED** at the validator.

FU-A-1 discharged — `grep -rn "_PROBE_NUM_CLASSES"` returns nothing.

### 17.11.2 Interfaces and authorities this PR leaves behind

Consumers of 04a's seams — including PR 04b, which should be re-scoped from
post-04a master rather than from its pre-04a draft:

| Surface | State after 04a |
|---|---|
| `ImplementorOutput.model_io_contract` | NEW — the normalized contract, echoed from `forward_contract.model_io` at **both** construction sites |
| `ValidatorInput.model_io_contract` | NEW — mapped verbatim by `local_all_fields`; never re-resolved |
| `agent/skills/model_io_probe_skill.py` | NEW — the Step-04 probe-recipe authority, consumed by BOTH nodes |
| `HardwareContext.effective_cap_gb()` | NEW — one capacity rule, quoted by proposer and implementor alike |
| `ImplementorInput.hardware_context` / `.vram_budget_gb` | NEW — mirrors `ProposalInput`; wired at the same workflow site |
| `IMPLEMENTOR_REASONING_PROMPT` | now carries `{CAPACITY_BUDGET}`; `{TASK_BACKGROUND}` unchanged |
| `VALIDATOR_REVIEW_SYSTEM_PROMPT` | now carries `{CLASSIFIER_SHAPE}` / `{REGRESSOR_SHAPE}`, filled by `_build_review_system_prompt(contract)` |
| `_render_output_contract`, `_assemble_test`, `_smoke_test_plugin`, `_dummy_tensor_validate_loss` | all take an optional contract; `None` = legacy path, byte-identical |

**Authority left standing**: Step-03 `ModelIOContract` is the sole normalized
Model-I/O authority and the sole answer to *what this TASK declares*; a
model's own `PLUGIN_OUTPUT_TYPE` remains the sole answer to *which form THIS
MODEL emits*, under Step-03's own documented precedence (§17.4.2a). No second
Model-I/O contract, no second `LossContract`, no capacity config.

### 17.11.3 Findings worth carrying forward

1. **A survived mutation exposed a production reachability gap** (§17.4.4):
   every validator test called the helper directly, so severing `run()`'s
   contract forwarding left the directory green. Closed by a real-`run()`
   reachability test plus its negative twin. *Lesson: a helper can be perfect
   and never reached.*
2. **Three existing pins fired and all three were edited, none relaxed** —
   the PR-E key-set pin (twice), `TestDeferredScope` (whose last deferred
   hardcode this PR discharges, REWRITTEN to assert the replacement property),
   and a test that formatted `TEST_TEMPLATE` directly (UPGRADED to render
   through `_assemble_test`).
3. **CI caught a device literal this PR itself introduced** (§17.9.10) — into
   the docstring narrating the removal of device literals. Removed rather than
   annotated. *Lesson: targeted suites cannot know what an unrelated guardrail
   scans; exact-head CI is the broad authority, as §12 says.*
4. **`--data_dir` is optional but the pre-phase GPU measurement fails closed
   without it** (§17.9.6) — a pre-existing defect that makes the Gate
   standard's canonical Gate-2 command fail. Deliberately NOT fixed here.
   **Operator follow-up, recommended before 04b.**

### 17.11.4 Deliberately NOT done

- PR 04b — untouched and not started.
- `ForwardContract` / `ModelIOContract` convergence — **record only** per
  OD-S4-4. 04a is the first PR in which a single consumer holds both, which is
  the §14 evidence the ledger wanted; it does not authorize a merge of them.
- Any check that a candidate's chosen output form is *scientifically*
  appropriate for the task — admission/composition, owned by Step 12.
