# Test Architecture and Suite Pruning Plan

**STATUS — DESIGN / OBSERVATION ONLY. No test was added, deleted, consolidated
or modified to produce this document.** Audited read-only at `4b73d34a`
(branch `step07-pr07c-tuner-measurement`), 2026-08-17.

**This file is deliberately untracked on the 07c branch.** It belongs to the
Test Architecture & Pruning PR, which follows 07c's merge. Nothing here is
mixed into 07c.

Method: whole-suite `--collect-only`, AST scans, greps, and **body-level reads**
of every family named below. Three read-only sub-agents covered non-overlapping
areas (`tests/unit/agent`, `tests/unit/core`, and the remaining ten
directories); every load-bearing claim was then re-verified directly against
the source before it was allowed into this document. **Four of their claims did
not survive that check and are corrected in place** — see §0.

---

## 0. Corrections applied during verification

Recorded because the corrections change recommendations, not just wording.

| Claim as reported | What the source says | Effect |
|---|---|---|
| `scripts/bg_gpu_sampler.sh` "has no caller anywhere in the repo" | It has no *code* caller, but `docs/design/v20_priorities/pr_e_campaign_scoped_control_state.md` D-E-8 documents its `STOP` file as a deliberate, operator-facing contract that PR E chose **not** to change | It is a documented diagnostic tool, not dead code. Retiring it is an operator call, not a cleanup |
| Retire `scripts/c2_prephase_validation.py` together with its 104 tests | `tests/unit/core/test_environment_stability.py:33` and `test_formal_stability_controller.py:32` both `ast.parse()` that script as their **reachability oracle** (5 sites) | Deleting the script breaks 77 cases in two files the same audit independently classified as must-keep. The retirement needs a re-homing plan first |
| `sdsc_submission_scripts/run_one_iteration.py` references `bg_admission_validation` | Line 1618 is a **comment**, not a call | Production genuinely does not depend on it — the retirement case stands on its own merits |
| `test_step03_a6`'s dtype tables are production tables | They are defined *in the test file* at line 108 | Confirms the six cases at `:314-325` are self-referential; the table itself stays (line 228 uses it as the expectation for an **observed** dtype) |

Additionally verified before use: the 55-cell banned-vocabulary cross-product;
the `test_pr07c_validation_pricing.py:701` tautology; the
`test_observed_subprocess_seam.py:422` schema-self-comparison; the 10-row vs
27-row authority supersession; the absent `FocalLoss1D` numeric oracle; and the
`v19_queue_runner.sh` / `launch_v20_campaign.sh` question (§18.6), which is
**not** the contradiction it first appears to be.

---

## 1. Executive summary

### The headline is not the number

The suite is **9,980 collected cases**, and the working target discussed was
5,500–6,500. After a body-level audit of every large family, the
**evidence-backed** reduction is:

| Area | Cases | Evidence-backed reduction | Rate |
|---|---:|---:|---:|
| `tests/unit/agent` | 4,210 | −270 | −6.4 % |
| `tests/unit/core` | 2,507 | −82 | −3.3 % |
| ten other directories | 3,186 | −276 | −8.7 % |
| unaudited remainder | ~77 | — | — |
| **total** | **9,980** | **≈ −630** | **−6.3 %** |

Extrapolating the *same families* into the sub-modules that were counted but
not read body-by-body plausibly reaches **−1,200 to −1,600 (−12 % to −16 %)**,
landing at **8,400–8,800**.

**Reaching 5,500–6,500 by removing redundancy is not achievable.** The gap is
about 2,500 cases, and this audit could not find 2,500 cases that own no
failure class. Getting there requires a *policy* decision — retiring a whole
category on grounds other than redundancy (§18) — and the honest statement is
that such a decision deletes coverage rather than duplication.

This is the opposite of the finding the audit was commissioned to produce, and
it is the finding.

### Why the suite is large

Not carelessness. Read at the body level, the suite is unusually disciplined:

* **`or True`: one genuine instance repo-wide** (`test_runtime_decision_policy.py:269`,
  a harmless keys-only note). The other seven are lambda idioms, comments, or
  guards asserting the anti-pattern is *absent from production*.
* **Comparing a value to a default read from the model under test: zero
  harmful instances** across all three audited areas. Every `model_fields[…]`
  read is either a hardcoded pin, a cross-*model* comparison, or paired with a
  negative hardcode. One exception, `test_observed_subprocess_seam.py:422`.
* **`test_no_test_executes_a_launcher.py` is already fixed** — 31 cases, list
  iterated *inside* the test. The old "383 wasted cells" lead is dead and must
  not be carried forward.
* Several files carry docstrings recording the consolidation they have
  *already* been through, and one (`test_authority_end_to_end_and_history.py`)
  documents which tests it **declined** to write and where that coverage lives.
* Several explicitly warn against the merge a future pruning pass is most
  likely to propose — `test_refusal_lane_distinctness.py` says so in its own
  docstring.

The 2026-08-02 cleanup held. What remains is mostly real.

### Where the leverage actually is

Reordered by value, which is *not* the order of case counts:

1. **One recurrence of the motivating defect, found live** (§9.1). It is in a
   test written during this very PR. Fix, do not delete.
2. **~45 redundant real-subprocess launches removable by fixture scoping,
   zero cases deleted** (§9.3) — a wall-clock win with no coverage cost.
3. **~136 cases restating Pydantic declarations**, with per-file tables (§6).
4. **~230 cross-product cells sharing one failure class**, with the retained
   class named for each (§7).
5. **~250 cases guarding merged, closed campaign harnesses** (§10.2) — the
   single largest block, and the one carrying the coupling caveat from §0.
6. **Four genuine coverage gaps, one of them serious** (§12).

### Confidence

| Wave | Confidence | Basis |
|---|---|---|
| 1 — mechanical | HIGH | per-file tables, bodies read |
| 2 — superseded | MEDIUM-HIGH | replacement authority named per row; two rows carry open couplings |
| 3 — matrices | MEDIUM | retained classes named; needs mutation proof per row |
| 4 — Gate ownership | **withdrawn as a deletion wave** | see §9 — it is a re-labelling and fixture-scoping wave |
| 5 — additions | HIGH | gaps verified against source |

---

## 2. Why the current suite is unhealthy

The problem is **not** CI wall time (~15 min) and it is **not**, as expected,
mass redundancy. It is that ~630 decorative claims and one structurally
misleading family are camouflaged among 9,300 real ones — and the misleading
family is the dangerous part.

**PR-07c is the proof.** 9,967 unit cases were green — including a
purpose-written cold-start *temporal* test for the exact mechanism that failed.
Gate 2 then found that the first validation prediction was computed but not
**persisted** until the whole validation pass returned, so the watchdog kept
enforcing a deadline with no validation term and killed the attempt 26 s into
validation.

```text
the unit test drove the deadline provider over a HAND-WRITTEN sidecar
    -> it proved the arithmetic AFTER the value was present
    -> it could not observe WHEN production writes

the real-trainer test used a fixture whose validation pass finishes in ms
    -> the deferred write always landed in time
    -> the bug was invisible by construction
```

A more elaborate fake would not have helped. **A fixture that manufactures the
exact intermediate state whose *arrival time* is the property under test can
never test that property.** That is a structural limit of the layer.

---

## 3. Target testing architecture

```text
Ruff      syntax, style, import order, lint rules it deterministically enforces
Pyright   static types and type relationships it deterministically enforces
Pydantic  ordinary field typing, Literal/enum rejection, range and default parsing
Unit      cheap DETERMINISTIC LOCAL semantics + precise failure localisation
Gate 1    the real LLM boundary
Gate 2    the real execution lifecycle
```

The layers must be **complementary**, not stacked. **Unit keeps the
deterministic INPUTS to the Gate boundaries** — rendered prompt bytes where
byte-stability is intentional, renderer structure, schema/protocol semantics,
fail-closed parsing. It does not keep a second, fake copy of the boundary
itself.

One refinement the audit forced: *"real subprocess in the unit tier"* is **not**
a synonym for *"Gate impersonation"*. `test_probe_hard_timeout.py` enumerates 4
signals × 3 phases of worker death with fake worker scripts, no GPU and no
data; Gate 2 gives you exactly one lifecycle. The test that matters is not
"does it spawn a process" but "**could a fake have manufactured the property**".

---

## 4. Current inventory

### By directory

| Directory | Files | Cases | Share |
|---|---:|---:|---:|
| `tests/unit/agent` | 254 | 4,210 | 42.2 % |
| `tests/unit/core` | 108 | 2,507 | 25.1 % |
| `tests/unit/execute_tools` (incl. `health_checks/`) | 81 | 1,160 | 11.6 % |
| `tests/unit/sdsc_submission_scripts` | 25 | 563 | 5.6 % |
| `tests/unit/scripts` | 25 | 542 | 5.4 % |
| `tests/unit/ml_models` | 14 | 272 | 2.7 % |
| `tests/unit/workflows` | 16 | 255 | 2.6 % |
| `tests/unit/tools` | 7 | 140 | 1.4 % |
| `tests/unit/guardrails` | 8 | 100 | 1.0 % |
| `tests/unit/examples` | 6 | 80 | 0.8 % |
| `tests/unit/dashboard` | 2 | 44 | 0.4 % |
| `tests/unit/nodes` | 3 | 30 | 0.3 % |
| others (`agent_generated`, root) | — | ~77 | 0.8 % |
| **total** | **535** | **9,980** | |

### `tests/unit/agent` internal split

| Subdirectory | Cases |
|---|---:|
| `tune_ml_hyperparam_agent/` | 1,225 |
| `ml_model_proposal_agent/` | 602 |
| `schemas/` | 388 |
| `evaluate_vram_skill/` | 310 |
| `result_interpretation_agent/` | 263 |
| root files | 258 |
| `ml_model_implementor/` | 241 |
| `llm_bridge/` | 177 |
| `prompt_templates/` | 167 |
| `ml_code_validator_agent/` | 136 |
| `protocols/` 110 · `skills/` 83 · `ml_literature_review/` 82 · `cache/` 67 · `utils/` 46 · `inference_skill/` 32 · `training_skill/` 16 · `denoising_score_skill/` 7 | 443 |

### Largest files

| Cases | File |
|---:|---|
| 105 | `agent/prompt_templates/test_literature_review_prompts.py` |
| 104 | `scripts/test_c2_prephase_validation.py` |
| 91 | `core/test_failure_attribution.py` |
| 89 | `workflows/test_model_exploration.py` |
| 78 | `scripts/test_bg_validation_harness.py` |
| 77 | `agent/evaluate_vram_skill/test_isolated_preflight.py` |
| 74 | `sdsc/test_run_one_iteration.py` |
| 71 | `agent/tune_ml_hyperparam_agent/test_tuning_agent.py` |
| 71 | `agent/ml_code_validator_agent/test_validator_agent.py` |
| 70 | `core/test_resume.py` · `agent/…/test_attribution_gating.py` |
| 69 | `agent/ml_model_proposal_agent/test_phase_b_schemas.py` |
| 67 | `core/test_gpu_admission_wiring.py` |
| 65 | `sdsc/test_launch_v20_campaign.py` |

---

## 5. Historical growth

| Step marker | Files | Test functions |
|---|---:|---:|
| step00 28 · step01 10 · step02 34 · step03 18 | 90 | 384 |
| step04 18 · step05 40 · step06 18 | 76 | 287 |
| step07 26 · pr07* 12 | 38 | 266 |
| **total** | **204** | **937** |

**Correction to the obvious reading.** The audit looked specifically for
"later `stepNN` authority dominates an earlier one" and **found none** in
`tests/unit/agent`, and none among the small `stepNN` files in `core`.

The step files are a deliberate **capture-first ladder**: each Checkpoint-0
baseline was written *before* the migration it certifies, precisely so it could
not be back-fitted. `test_step00_numeric_baselines.py` declares zero production
diff by construction; `test_step03_a2` and `test_step03_a6` say the same;
`test_step02a_c1_baselines.py` pins what the dataset serves, which
`test_step03_a6` documents as *upstream* of the engine cast it observes.

**Do not treat the `stepNN` prefix as an obsolescence signal.** Whether the
ladder is retired once its step merges is §18.3 — a policy question, not a
redundancy finding.

---

## 6. Static-tool duplication — per-file, bodies read

An AST pass for test functions whose entire body is one
`pytest.raises(ValidationError)` around one model construction returns 41 in
`core` alone. **Most are genuine cross-field validators.** Only the rows below
survived a body read.

### `tests/unit/core` — 47 → 4

| File:line | Test | Cases | Owner |
|---|---|---:|---|
| `test_measurement_capability.py:83` | `test_no_identity_field_may_be_blank` | 8 | `min_length=1` — consolidate to **1** concept-spanning case |
| `test_measurement_identity_and_envelope.py:134` | `test_no_dimension_may_be_blank` | 8 | same — consolidate to **1** |
| `test_scientific_authority.py:134` | `test_a_caller_supplying_a_conclusion_is_refused` | 5 | `extra="forbid"`, **and** duplicated at `test_authority_matrix_frozen.py:209` |
| `test_failure_attribution.py:577` | `test_the_vocabulary_is_closed` | 4 | `Literal` |
| `test_server_configs.py:77/83/87/97` | nonpositive / empty hostname / extra / frozen | 4 | `gt=0`, `min_length`, `extra`, `frozen` |
| `test_gpu_admission_wiring.py:79/87/105` | frozen / unknown posture / negative ceiling | 3 | declaration |
| `test_pair_admission.py:172/192/196` | negative ceiling / blank provenance / zero prediction | 3 | declaration |
| `test_runtime_session.py:46/52` · `test_v20_slot_scheduler.py:71/173` | positivity / frozen / `Literal` / `ge=1` | 4 | declaration |
| `test_probe_hard_timeout.py:212/246` | `ge=0`; `SIGTERM==15, SIGKILL==9` | 2 | Pydantic; **stdlib** |
| `test_measurement_identity_and_envelope.py:127` · `test_measurement_capability.py:91` | `extra="forbid"` ×2 | 2 | declaration |
| `test_hardware_context.py:44` · `test_gpu_accounting.py:334` · `test_calibration_quarantine.py:63` · `test_runtime_decision_policy.py:276` | frozen / required / blank reason / semver | 4 | declaration |

### `tests/unit/agent` — ~122 → ~73

* `ml_model_implementor/test_implementor_schemas.py` **26 → ~12** — includes
  two literal instances of the "declared type accepting its own type"
  anti-pattern (`test_model_description_present`), four `test_missing_*_raises`,
  three defaults-to-`None`, and a nested-model JSON round-trip with no custom
  serializer.
* `ml_model_proposal_agent/test_phase_b_schemas.py` **69 → ~42** — `Literal`
  accept/reject pairs, three `max_length=` cases, four `test_missing_*_raises`,
  `test_optional_fields_default_empty`.
* `ml_code_validator_agent/test_validator_schemas.py` **25 → ~18** — two
  `test_missing_required_field_raises` families (6 + 6).
* `tune_ml_hyperparam_agent/test_validation_workload_ceiling.py:214` **2 → 1** —
  dominated by its own sibling at `:224`: with the field undeclared,
  `extra="ignore"` drops it and the serialisation test already fails.

### ten other directories — ~40 → 0

* `execute_tools/health_checks/test_schemas.py` **29 → ~21** — five
  required/optional/`Literal` cases. **Keep** `test_expected_members`,
  `test_string_values`, `test_no_record_score`: those pin the four-member
  alphabet the severity resolver (`SKIP_ITER > SKIP_TO_FORMAL >
  INVALIDATE_ROUND > CONTINUE`) depends on and operators type into YAML.
* `workflows/test_llm_config.py` **34 → ~22** — three scalar JSON round-trips,
  provider/model assignment readbacks, `Literal` rejection. **Keep** all three
  `test_defaults` (audit finding M4 was "every node fell through to
  `gemini-3.1-pro-preview`"), both `*_are_independent_objects` (mutable shared
  default — a real runtime class), and `TestShippedJsonConfigsParse`.
* `ml_models/test_model_configs.py` **−9** — six `test_valid_custom` assignment
  round-trips, three pure `Field(ge=…)` cases.

### NOT redundant — do not touch

Verified as genuine cross-field `model_validator` semantics no declaration can
express:

`ResolvedMeasurementCapability` "unavailable must explain itself" (three
directions) · `admitted=True` may not carry a `reason_code` · a refusal must
say why · `may_recommend_resource_reduction` refusable **and** not
disclaimable · source ↔ `formal_execution_eligible` · `telemetry_available=False`
may not carry figures (asserted on three separate snapshot models) ·
`headroom_gib` must follow from its inputs · soft budget < hard deadline ·
`_prediction_differs_from_current` (an unfalsifiable prediction) ·
`_validate_source_id_format` (regex applies only for two of three
`source_type`s) · `coerce_status` (`mode="before"` — rewrites LLM-invented
statuses; **not** `Literal` rejection) · whitespace-only `causal_hypothesis` ·
`ProposalOutput._validate_custom_loss_spec_consistency` (three-way round-trip) ·
all ~17 cross-field validators in `test_model_configs.py` (even kernel size,
depth-vs-segmentation, `embedding_dim % nhead`, static-v length).

**The model to copy:** `agent/schemas/test_cross_schema_invariants.py` and
`test_hyperparam_schemas.py`'s `TestProductionDefaults` /
`TestDeclaredBoundsStillHold` have already been through this pass — their
docstrings record it. Do not re-prune them; use them as the template.

**Total: ~209 → ~77 (−132).**

---

## 7. Cross-product parametrisation

The rule applied: **cells sharing one failure class collapse; cells each
catching a different deleted line do not.**

### Collapse — retained class named

| Site | Now | → | The single property retained |
|---|---:|---:|---|
| `agent/test_prompt_banned_vocabulary.py::test_banned_vocabulary_absent` | **55** | **1** | "no V9-banned token appears in any production prompt" — one matrix loop collecting **all** violations. Today you see only the first cell that trips. Its parametrize IDs also embed multi-kilobyte prompt text into node IDs |
| `prompt_templates/test_proposal_prompts.py::…::test_forbidden_phrase_absent` | 27 | 1 | "no prompt file names an agent to set trust; calibration flows via `AgentCard.trust_level`" |
| same file, `TestModeFilesRedirectSynthesis` | 12 | 2 | "every mode file redirects to the base prompt and never mentions the dead 'Advice JSON'" |
| `ml_model_implementor/…::TestFileAssembly::test_generated_file_contains_token` | 11 | 1 | 11 full `agent.run()` calls → one run + 11 asserts |
| `test_tuning_agent.py::TestHyperparamTuningAgentRun` | ~20 | ~9 | six cells (`status`, `best_score`, `best_config`, `all_records`, `model_type`, `run_name`) are one property |
| `test_literature_review_prompts.py` per-render greps | ~90 | ~45 | collapse cells sharing one `render_*` call; **keep every distinct fixture shape** (Tier1 / Tier2 / abstract_only / unresolved / no-extract) |
| `test_prompt_context_surfacing.py` (2 classes) | 18 | ~8 | keep the (feature/capability) × (dict/pydantic) 4-cell matrix; drop single-vs-multiple duplicates |
| `test_interpretation_agent.py` (2 classes) | 15 | ~6 | "every populated field surfaces; `None` fields are skipped"; "expert advice precedes human advice" |
| `test_proposal_helpers.py::TestIterIndexFromSource` | 9 | 3 | six are one class: "any unparseable `source` falls back" |
| `test_pipeline_runner.py::TestScoreSummaryLine` None-cells | 4 | 1 | "insufficient inputs → `None`, never a fabricated line" |
| `test_vocab_feedback.py::TestUpdateVocabLinkConfirmations` | 3 | 1 | "only outcome `confirmed` increments" |
| `test_time_calibration.py` lookup/clip | 6 | 2 | precedence chain; clip to `[kmin,kmax]` |
| `workflows/test_model_exploration.py::TestOrchestrationParamForwarding` | ~13 | ~11 | one parametrised `(param, value, path)` table — every param keeps its own case and its own failure; 2 default-is-`None` members go to Pydantic |
| `test_step03_a6` self-referential table cases `:314-325` | 6 | 0 | **verified**: the tables are defined in the test file at `:108`; these compare literals to literals. The table stays — `:228` uses it as the expectation for an *observed* dtype |

**Subtotal: ~289 → ~91 (−198), plus −6 self-referential = −204.**

### Do NOT collapse — verified per-cell value

* **`sdsc/test_launch_v20_campaign.py::test_flag_reaches_the_runner`, 31
  cells.** Each catches a *different deleted line* in `launch_v20_campaign.sh`.
  The file documents why a static grep is insufficient (`_chain_common.sh` can
  silently decline to forward) and why substring matching failed
  (`"--runtime_watchdog" in argv` is True when only
  `--runtime_watchdog_safety_factor` is present — `_argv_contains` tokenises
  for that reason).
* **`core/test_authority_matrix_frozen.py`, 32 cells.** The 27 rows are the
  complete 3×3×3 input space, hand-derived from the documented rule, asserting
  the **whole `model_dump()`** per row, pinned *before* the transport work so
  parity could not be written to match new behaviour. Cost is nil.
* **`sdsc/test_c14_gate_v19_parity.py`, 32 cells.** Per-flag, and it caught a
  real divergence (VRAM 24 vs 16, 2026-07-31). Its *reference* is the open
  question in §18.6 — the cells are fine.
* **`execute_tools/test_step07a_c1_training_history.py:87`, 11 cells.** One
  hand-written `TrainingHistory` consistency rule per cell, none Pydantic-owned.
* **`ml_models/test_step03_m6_cardinality_derivation.py`, 31 cells.** Class
  count is observed at a **constructed model's output shape** and at
  `model.embedding.num_embeddings`, deliberately — `assert cfg.num_classes == 10`
  would pass with 256 still hardcoded.
* **`core/test_admission_join_contract.py`, 30 cells.** Do not delete the phase
  axis; **fixture-scope it** — see §9.3.

---

## 8. Gate-1 overlap — smaller than assumed

The earlier estimate was 150–300 cases. **Body-level reading finds ~10.**

| Family | Cases | Property that belongs to Gate 1 |
|---|---:|---|
| `test_validator_agent.py::TestMLCodeValidatorAgentRun` all-pass cells | 4 | "the review round-trips end-to-end and reaches `passed=True`" |
| `test_pipeline_runner.py` — produces-valid-output / calls-bridge-3× / file-written | 3 | "three real stage calls yield a schema-valid `ProposalOutput`" |
| `ml_literature_review/test_node.py` — full_run_mocked / storage round-trip | 2 | "a real search → extract → synthesise loop completes" |
| `test_tuning_agent.py::test_output_validates_against_schema` | 1 | the plan → train → reflect chain with a real planner |

Outside `tests/unit/agent`, Gate-1 overlap is **essentially zero**. The only
LLM-adjacent surface in the other ten directories is
`workflows/test_llm_config.py::TestShippedJsonConfigsParse` (1 case) — a Gate-1
*precondition*, correctly placed in unit.

**What must remain, and why it makes the move safe:** `test_llm_bridge.py::TestGenerate`
(~11) is the salvage layer — markdown-fenced JSON, trailing prose after a valid
object, a second object after the first, non-dict first token, empty-then-retry,
malformed-then-valid. It is what makes "the real LLM returns valid output"
safe to delegate.

**`llm_bridge/test_stub_llm_bridge.py` (26) is NOT Gate-1 overlap.** It
validates that the *stub's* canned responses conform to production schemas
across all 14 cognitive labels — it guards the zero-cost smoke harness against
drift, which Gate 1 cannot do. Keep whole.

---

## 9. Gate-2 overlap — the most important section, and not a deletion wave

Expected: 400–700 cases to migrate. **Found: zero.** What was found instead is
more valuable.

### 9.1 The motivating defect recurs — in a test written during this PR

`tests/unit/core/test_pr07c_validation_pricing.py::TestColdStartTemporalUpdate::test_the_refreshed_deadline_arrives_strictly_before_the_old_one_fires`
(`:309-346`). The class docstring correctly names the trap. Lines 324-330 are:

```python
first_batch_seconds = VALIDATION_ACTUAL_S * (500 / 15_000)
elapsed_when_prediction_lands = TRAIN_ACTUAL_S + first_batch_seconds
assert elapsed_when_prediction_lands < old_deadline
```

That is **arithmetic over three constants the test itself chose**. It cannot
observe when production writes the validation component — the same shape as the
original defect, one level up.

**Action: fix, do not delete.** Drop the three modelled-timing lines, keep the
refresh-observation half, and record "the term arrives before the stale
deadline fires" as **Gate-2-owned** (Gate 2 is already REQUIRED at 07c's final
head and is where `--runtime_watchdog` meets real elapsed time).

**Second, verified tautology — same file, `:701-703`:**

```python
assert components["training"]["actual_seconds"] < (
    components["training"]["actual_seconds"] + validation_total
)
```

`x < x + positive`, and `validation_total > 0` was established at `:695`. The
comment claims it proves the training actual was *reduced* by the validation
seconds. It proves nothing. **This one is load-bearing** — it is the only guard
that the per-optimizer-step cost model stays pure. Replace with
`training_actual + validation_total == approx(total_wall)`, or compare against
the pre-reduction figure.

**Third — a labelling defect.**
`agent/tune_ml_hyperparam_agent/test_trial_formal_safety_split.py::TestWatchdogDeadlineUsesPhaseFactor`
hand-writes a complete sidecar and then proves `100 × 2.0 = 200` and
`100 × 1.5 = 150`. The arithmetic is legitimate local semantics; the **class
name** invites readers to count it as watchdog coverage. Rename (e.g.
`TestSafetyFactorArithmeticGivenAnObservation`) and state in the docstring that
deadline-vs-real-elapsed is Gate 2's. Same caution for
`test_rt3_trigger_policy.py::_seed_store` and `test_inference_aggregator.py`.

### 9.2 Real subprocesses in the unit tier that EARN it

| File | Cases | Verdict |
|---|---:|---|
| `core/test_step06_c0_two_route_oracle.py` | 4 | **Earns it.** Route (i) in-process vs route (ii) the real `denoising_score_single.py` child, then exact float equality between them. Two routes cannot be compared without running both |
| `core/test_step07a_c2_transport.py` | 9 | **Earns it.** The real trainer emits R2+R3 over a *distinct* validation scope; only `--data_dir` is injected |
| `core/test_probe_hard_timeout.py` | 42 | **Keep.** Fake worker scripts (sleep / self-signal / malformed / chatty), no GPU, no data. 4 candidate signals × 3 phases, TERM→KILL escalation, orphan-free `killpg`, PIPE-deadlock avoidance. Gate 2 gives *one* lifecycle; this gives the matrix. Carries the `transformer@8M-ceiling` incident (never returned at 900 s then 2400 s; host-OOM SIGKILL; a 30 GiB quota-watchdog SIGTERM at 31.27 GiB on a 31.34 GiB card) — misclassifying any of these ABORTS a whole chain instead of rejecting one model |
| `agent/evaluate_vram_skill/test_isolated_preflight.py` | 77 | **Keep, do not migrate.** Real `sys.executable` workers that allocate against a 512 MiB RLIMIT, ignore SIGTERM, and self-`SIGKILL`. The only executable proof the 2026-07-31 host-OOM regression cannot return; no GPU, no data. Gate 2 is too expensive a place to prove "a SIGTERM-ignoring descendant is reaped" |
| `agent/…/test_host_memory_chain.py` · `evaluate_vram_skill/test_preflight_ipc_composition.py` | 34 | Same class. Keep |
| `core/test_watchdog.py::TestKillTree` | 5 | **Must not be deleted.** The *only* unit-level place where a deadline is enforced against real elapsed wall time with a real process group (`bash -c "sleep 60 & sleep 60 & wait"`, `trap '' TERM`, `survivors_detected is False`). It is the reachability half the sidecar tests lack |

**What they need is a marker**, not migration: `@pytest.mark.slow` (or the
existing `allow_real_subprocess` convention) so a fast inner-loop run can
exclude them. **111 cases re-labelled, 0 deleted.**

### 9.3 ~45 redundant subprocess launches, removable with zero coverage loss

| Site | Launches now | After | How |
|---|---:|---:|---|
| `core/test_gpu_measurement_runner.py` `_GOOD_WORKER` | **20** | 1 | `scope="module"` fixture. 0.15 s + 0.25 s of sleeps + interpreter start, ×20, no caching at all. ~12 s recovered |
| `core/test_admission_join_contract.py` `_joined(phase)` | **14** | 2 | `@pytest.fixture(params=PHASES, scope="class")`. Only 2 of 11 functions have a genuine phase axis (the shrink strings differ); per-phase requirement lookup is already owned by `TestPhaseSpecificRequirement`. All 22 assertions retained |
| `core/test_pr07c_validation_pricing.py::TestTheRealTrainerEmitsAValidationComponent` | **5** | 2 | `run_name="c5"/"c5short"/"c5excl"` all pass `runtime_policy={}` (identical); `"c5stab"`/`"c5once"` pass the same bounded policy. Two class-scoped fixtures keep all 5 tests and all assertions. Nothing here depends on process isolation |
| minor sites | ~6 | ~2 | same pattern |

**~45 fewer real subprocess launches, zero cases deleted.** This is the single
best runtime-per-risk trade in the audit.

### 9.4 Plugin registration

`workflows/test_model_exploration.py`'s `TestRegisterPlugin` /
`TestAddPluginToRegistries` / `TestL6cPromoteLossToGlobal` (~30) register into
in-memory registries from `tmp_path`, never through the real sandbox
subprocess. **Keep** — they test copy/skip/idempotency branch logic cheaply —
but they must **not** be cited as the Gate-2 registration lifecycle.

---

## 10. Superseded authorities — replacement named per row

### 10.1 Verified supersessions

| Superseded | Cases | Replacement authority | Verified how |
|---|---:|---|---|
| `core/test_scientific_authority.py::TestTheTruthTable::test_each_row` | **10** | `test_authority_matrix_frozen.py::test_row` — **27 rows** (complete space vs 10 hand-picked) asserting the entire `model_dump()` incl. `enters_incumbent_selection` / `enters_scientific_aggregation`, which the 10-row version never checks | both files read; row counts confirmed (`len(MATRIX) == 27` at `:112`) |
| same file, `test_exactly_one_combination_is_authoritative` | **1** | Same function name, same claim, at `test_authority_matrix_frozen.py:156`, derived over 27 rows | both bodies read |
| same file, `test_a_caller_supplying_a_conclusion_is_refused` | **5** | `test_authority_matrix_frozen.py:209` (`extra="forbid"`, 1 case) | reported; matrix-file site confirmed present |
| `core/test_pr07c_validation_pricing.py::TestDeadlineParityWhenNoValidationEvidenceExists` | **3 of 5** | `core/test_watchdog.py::TestDeadlineFormula` (`:96-159`) — same three rows (operator budget tightens; `max_phase` tightens; floor raises) but driving a **real `RuntimeVerificationSession`** rather than a hand-written sidecar. Keep the 2 rows it does not cover | both read |
| `agent/…/test_validation_workload_ceiling.py:214` | **1** | its own sibling at `:224` | read |
| `execute_tools/test_step03_a6` `:314-325` | **6** | the three boundary tables + the two executed tests already carry F-1 | tables confirmed test-local |
| `core/test_observed_subprocess_seam.py:422` | **1** | Pyright + the declaration — the exact CLAUDE.md-forbidden schema-self-comparison | read |
| `core/test_probe_hard_timeout.py:138` | **1** | `:122` already asserts `elapsed < 10.0` in the same regime | read |
| `core/test_pr07c_validation_pricing.py:373` | **1** | doc-text assertion; `:348` owns the behaviour. Low priority | read |

`test_scientific_authority.py` **49 → 33.** Everything else in it is unique and
stays: `TestRecordAuthorityIsFailClosed` (a flipped stored conclusion refused;
an older verdict missing a newer field is **not** condemned; a stored validity
contradicting commit-time evidence refused), `TestRecordAuthorityLegacyLadder`,
`TestLaunchHistoryCannotReachTheVerdict` (AST proof that `no_valid_trial` /
`force_formal_round` cannot become blocking reasons).

**Subtotal: −29.**

### 10.2 The closed-campaign harness family — largest block, with a coupling

| File | Cases | → | Basis |
|---|---:|---:|---|
| `scripts/test_c2_prephase_validation.py` | 104 | ~3 | PR C2 **MERGED 2026-08-04** (`pr_c_measured_evidence_admission.md:7`); `core/inference_defaults.py:26` calls the target a *"legacy validation script"* (verified verbatim). Keep only `TestItDrivesTheProductionBoundary::test_the_tuner_calls_the_same_three` — a live claim about the tuner — and move it to `tests/unit/guardrails/` beside `test_preflight_production_reachability.py` |
| `scripts/test_bg_validation_harness.py` | 78 | 0 | PR B **MERGED 2026-08-02** (`pr_b_gpu_aggregation_attribution.md:3`, PR #153, `4472f15`); targets untouched since. Also hardcodes `/home/klz/Data/SIDEREIS_DATA/bg0_evidence_20260802/bg0_fixture.json` at `:273` and `:414`, and six of its assertions are bare `is not None` on a refusal message |
| `scripts/test_c2_documentation_sync.py` | 57 | 28 | **Split.** Retire `TestTheGateInvariantsAreStated` (26) + `TestEveryDocumentedFlagExists` (3) — prose pins on a merged design doc. **Keep** `TestTheNodeDocDescribesTheCurrentProductionPath` (12 — the operator doc-sync rule made executable against the live `ml_hyperparameter_tune_agent.md`), `TestValidationOnlyFlagsStayOutOfProductionDocs` (15), `TestDocumentedDefaultsMatchTheCode` (1) |
| `scripts/test_bg_gpu_sampler.py` | 12 | ? | **Corrected (§0).** `bg_gpu_sampler.sh` has no code caller, but PR-E D-E-8 documents its `STOP` contract as deliberately unchanged. Operator call |
| **subtotal** | **251** | **~31** | **−220, conditional** |

**The coupling that must be resolved first (§0).**
`tests/unit/core/test_environment_stability.py:33` and
`test_formal_stability_controller.py:32` both `ast.parse()`
`scripts/c2_prephase_validation.py` as their **reachability oracle** — five
sites across the two files. Those 77 cases were independently classified as
must-keep (`test_environment_stability.py` carries real sealed artifacts
`c2_lite_a20_7f8e9ffabdef_c12a__sub1.json`, six formal arms, a neighbour
oscillating 692–844 MiB, and the note that "the rule has been wrong twice in
the same direction"). The production component
(`core/runtime_control/formal_stability_controller.py`) is unaffected — only the
*caller* the reachability proof points at.

```text
BEFORE retiring scripts/c2_prephase_validation.py
  -> re-home the reachability oracle in test_environment_stability.py
     and test_formal_stability_controller.py onto a live caller
  -> otherwise 77 must-keep cases break at collection
```

Retire the tests **together with** the scripts, in one commit, after the
re-homing. Leaving a 1,647-line untested script in `scripts/` is strictly worse
than either keeping both or removing both.

---

## 11. High-value tests that MUST remain

Each owns an independent failure class. Named concretely so a future wave
cannot reach them by accident.

### Frozen numeric / identity oracles

* **`execute_tools/test_step00_numeric_baselines.py` (14) — the single most
  valuable file in scope.** Every formula routes *through* its production
  implementation, so deleting or rewriting production aggregation reds it:
  `s_max = 295715680.14248306`, 20×200 shape, sha256 `db806ecd…` of the anchor
  map; ground truth derivable from the committed anchors; every per-file
  artifact satisfying `score == _grand_mean_log_scalar(...)`; `LOG_BASE == 5.27`
  agreeing bit-for-bit across three modules; grand-mean-not-mean-of-means under
  unequal counts; `-inf` on empty; the `noise <= 1e-10` NaN-drop (with a written
  mutation-hygiene note explaining why the earlier all-constant fixture was
  EQUIVALENT); the frozen `abra_validation_{i:04d}.h5` literal.
* `core/test_gpu_measurement_data.py:73-88` — `GOLDEN_BATCH_SHA256_BY_GEOMETRY`
  over four geometries + `GOLDEN_FIXTURE_INPUT_SHA256` + a `GOLDEN_CAPTURED_AT`
  commit SHA. Also carries Gate-2-Lite-A (24.10 GiB host RSS before the model
  was built).
* `core/test_measurement_identity_and_envelope.py:74` — 8 dimensions × (`!=`
  and `identity_key !=`). The `measurement_kind` row specifically prevents a
  promoted **duration** being handed to a **memory** gate — an error the PR-C
  audit made in its own first draft.
* `core/test_calibration_context.py:66` — writer/reader drift by one key makes
  every lookup miss, indistinguishable from "no calibration exists".
* `core/test_pr07c_validation_pricing.py:113` — `calibration_key("validation",…)`
  is a *new* namespace, byte-identical after the `phase=` segment across all six
  phases.
* `core/test_run_invariants*.py` (51 across 3 files).
* `execute_tools/test_scoring_utils.py` (16) — **closed-form** anchor-weighted
  arithmetic with SNR mocked. NUM-6 is mechanism replay with no closed form;
  these are complements, and NUM-6's docstring says so. Includes the `1e-10`
  boundary at `0.5e-10 / 1.0e-10 / 1.5e-10` — the `<=` vs `<` mutation dies only
  here.
* `execute_tools/test_phase67_scoring_precision.py` (23) — seven records from
  run `v4_pr61_20260425_222622` that all collapsed to `-2.7708098959837675`.
* `ml_models/test_step03_a2_loss_compatibility_matrix.py` (22) — all 15 cells
  hardcoded from `models_format_sandbox.py:374-437`, including `hybrid`
  (unconditional early return) and `custom`, asserted nowhere else.

### Fail-closed negatives

* `core/test_failure_attribution.py::TestEvidenceQualityGate` (~20) — thin
  coverage, observer error, join timeout, missing baseline, UUID disagreement,
  missing policy, unrecorded timing, stale sample, `used > total`. Each returns
  `unknown` **and asserts the reason string** — an outcome-only assertion passes
  for any unrelated bug.
* `core/test_prephase_admission.py::TestIdentityIntegrityIsCheckedBeforeAuthority`
  (7) — **ordering** is the property.
* `core/test_calibration_read_authority.py` (21) — a matching bucket is **not**
  applicability. The only thing between the observability-only decision and
  history silently regaining authority.
* `agent/evaluate_vram_skill` authority partition (~70) — four outcome
  partitions closed and disjoint; a host-memory kill never phrased as a VRAM
  verdict; an inconclusive result carrying *no* authority.

### The three refusal lanes — protected from consolidation

`agent/…/test_refusal_lane_distinctness.py` (24) + `test_attribution_gating.py`
(70) + `test_preflight_outcome_consumption.py` (21) +
`test_m6_probe_unavailable_fails_closed.py` (13) = **128 cases**:

```text
Lane 1  pre-flight ESTIMATE refusal   skipped_oom_risk           phase never ran   shrink advice LEGITIMATE
Lane 2  runtime ADMISSION refusal     skipped_resource_admission phase never ran   shrink advice NEVER legitimate
Lane 3  post-hoc OOM                  error_{phase}_oom          phase ran, died   authority from failure_attribution
```

The V19 incident was lane 2 read as lane 3: a neighbour's occupancy became
"reduce model size" and the campaign shrank to toy models.
`test_refusal_lane_distinctness.py`'s own docstring calls itself "the merge a
future test-consolidation pass is most likely to propose."

The same distinctness holds across `core`'s eight admission-adjacent modules —
pre-flight measurement refusal (51) · runtime admission (51) ·
enforcement-vs-telemetry (12, the 2026-08-06 `WOULD BE REFUSED`-and-continued
finding) · graded pre-phase evidence (21) · post-hoc realized memory (24,
semantics-neutral, decides nothing) · post-hoc attribution (91) · host-aggregate
quota (35, units are the primary risk) · admission-vs-watchdog safety factors
(18, setting the watchdog to 3.5 must not move formal admission off 2.0).

### Architectural guardrails — all 100 in `tests/unit/guardrails/`, preserved

| File | Cases | Dated incident |
|---|---:|---|
| `test_no_test_executes_a_launcher.py` | 31 | 2026-07-31: a test executed `v19_gate0_pair_runner.sh`; two chains launched and made real API calls |
| `test_validation_posture_transport.py` | 16 | 2026-08-14, **twice in one afternoon**: `TypeError: run_workflow() got an unexpected keyword argument` after both ends were tested |
| `test_gate_standard_contract.py` | 14 | pre-2026-08-13 unbounded Gate-2 command surviving in the doc operators copy from |
| `test_preflight_production_reachability.py` | 13 | V20 PR A: two components built, tested, never called |
| `test_no_model_name_dtype_routing.py` 9 · `test_runtime_authority_audit.py` 9 · `test_no_model_name_branches.py` 5 · `test_no_hardcoded_device_literals.py` 3 | 26 | Step 03 §4a.1 A-1 · V19 wave-1 · Phase 6.6 §5.4 · §5.1 |

Two structural facts that answer the "they inflate the count" worry. The scans
**do not scale with the repo** — the launcher guard is deliberately one case
over all files (reasoning written at `:205`). And **27 of its 31 cases are
detector self-tests**, positive/negative pairs proving the scanner catches an
interpolated path, an argv list and a spawn call while permitting reads and
sources. That is precisely the fix for the 2026-08-02 finding that "a guardrail
blind to the most common `subprocess` calling form" passed review.

Also in this class: `core/test_failure_attribution.py::TestGenericity` (4) —
an **allowlist** of every numeric constant (`{1,2,3,1024}`), because the
previous denylist form could not have seen a `* 2` safety factor;
`test_live_timing_is_the_sole_runtime_evidence.py` (14) +
`test_historical_duration_is_observability_only.py` (9), deliberately split so a
green suite says *which* history system is still isolated;
`nodes/test_node_public_boundary.py` (16) — the 2026-08-16 operator
architecture rule made executable; all 80 in `tests/unit/examples/`, where
`test_tidmad_projection.py` regenerates every tracked snapshot from the owning
production accessor and deep-compares, which is what stops `examples/tidmad/`
becoming a second authority.

### Reachability and isolation

* `execute_tools/test_step07a_c1_validation_pass.py` (22) — the strongest
  reachability+isolation file present. It ships its own **negative control**:
  `test_with_the_fork_a_stochastic_forward_keeps_the_oracle_green` **and**
  `test_without_the_fork_the_same_model_moves_the_trajectory`. Plus
  `TestStateCensus` (model/optimizer/objective/mode/all RNGs unchanged; mode
  restored even when the pass raises) and
  `test_r3_equals_the_per_sample_reference_and_not_the_mean_of_batch_means` —
  the unequal-last-batch weighting a mean-of-batch-means implementation
  silently gets wrong.
* `execute_tools/test_pr07c_validation_envelope.py` (42) — clamp arithmetic
  rounding **down**, refusing a sub-segment ceiling instead of zeroing, numeric
  ordering under mixed str/int keys, `comparability` byte-identical with and
  without a clamp, and the ceiling never reaching the planner.
* `agent/…/test_step07b_c2_order_consumers.py` (35) + `test_step07b_c3_scale_rules.py`
  (28) — flip `MetricSpec.direction` and every ordinal consumer inverts
  *exactly*, with **literal** expectations (a test that asked `MetricOrder` for
  the answer would pass for any implementation) — while `same_loss_loss_rank`
  deliberately does **not** move. Plus a recording-double proof that a consumer
  left on a bare `max()` would give the right answer under TIDMAD and never
  call the authority.
* `agent/…/test_control_boundary.py` (43) — the seven per-round transients are
  still bound and released; no extracted helper owns a cleanup-owned object; no
  helper captures a patchable name as a default argument; `_emit_record`
  validates before saving. Pyright cannot see any of this.
* `sdsc/test_launch_surface_parity.py` — **4 cases**, best cases-per-defect
  ratio in the suite: *"the schemas do not set `extra="forbid"`, so Pydantic v2
  SILENTLY DROPS unknown constructor kwargs."*
* `agent/…/test_step07a_c3_tuner_boundary.py` (18) — expected-validation-without-R3
  → `error_training`, never a silent success with `validation_state="absent"`.
* `core/test_pr07c_validation_pricing.py:233::test_the_07a_regime_survives_the_fix_and_would_not_have_before`
  — replays the measured 9 s / 26.45 s Gate-2 numbers **and asserts the pre-fix
  deadline would have killed it**, so the replay cannot pass vacuously.
* `agent/schemas/test_cross_schema_invariants.py` (26) — the ten divergences and
  eleven unpinned defaults a 6,900-test per-field suite missed.
* `agent/…/TestProductionDefaults` (5) — 3/5/3 attempt budgets,
  `formal_eval_portion=1.0`, `health_gate_enabled=True`,
  `ExperimentPlan.is_trial=True`. Each is one character from a different
  science run.

**Rule: a test that caught a real regression is preserved without argument.**

### Things that LOOK duplicated and are not

| Looks like | Actually |
|---|---|
| five `*ordering*` files in `tests/unit/agent` (79 + 35) | four are **data ordering** (file permutation, shuffle provenance, PR2); the fifth is **metric ordering** (`MetricOrder`, 07b). A name-based merge would destroy both. If anything: *rename* to `test_file_order_*` / `test_metric_order_*` |
| `test_formal_stability.py` (41) vs `test_formal_stability_controller.py` (34) | the **rule** vs **the loop that closes around it** — the controller file exists because the rule landed with the loop unwired |
| `test_scoring_utils.py` vs `TestNUM6MechanismReplay` | closed form vs mechanism replay, documented as complements |
| the 44 `stepNN` capture-first baselines | written before the migration by design (§5) |

---

## 12. Missing or weak coverage — four verified gaps

Pruning is not success if the suite only gets smaller.

### 12.1 `FocalLoss1D` has no numeric parity oracle — highest value, lowest cost

CLAUDE.md asserts `ml_models/loss_models_sandbox.py:135-168` is *"line-for-line
identical to TIDMAD's `network.py:FocalLoss1D`"*. **No test asserts it.**
`tests/unit/ml_models/test_loss_functions.py::TestFocalLoss1D` is four weak
property tests (verified by reading all four):

```python
assert loss.shape == torch.Size([])     # torch guarantees this for reduction='mean'
assert loss.item() >= 0.0               # mathematically guaranteed
assert loss_perfect < loss_random       # genuine, very coarse
assert loss_sum(...) > loss_mean(...)   # genuine, very coarse
```

Change `alpha` from 0.5 to 0.25 — **the exact drift CLAUDE.md records as a past
defect** ("Was `0.25` before the fix") — and all four stay green. Add ~3
closed-form cases with hardcoded expectations for known
`(logit, target, alpha, gamma)` triples, in the `test_step00_numeric_baselines.py`
style. This is the frozen loss's missing oracle.

### 12.2 The producer/consumer artifact contract has a serialization hole

`execute_tools/test_per_file_best.py:145-198` builds the workspace by hand:

```python
f.write(output.model_dump_json())
```

Production, `nodes/ml_hyperparameter_tune_agent/records.py:936-953`, writes
something different:

```python
safe_output = coerce_nonfinite_to_none(agent_output.model_dump())
json.dump(safe_output, f, indent=4)
```

Different bytes and different **semantics**: production coerces `-inf`
no-signal sentinels to JSON `null` at the storage boundary (the comment says
`model_dump_json` would otherwise emit non-standard `-Infinity` and break the
dashboard). The fixture emits `-Infinity`. So the `-inf` path through
`build_table` and the `run_output_sha256` byte-check is exercised only against
a shape production never produces. *Field* drift is caught (the fixture routes
through `HyperparamTuningOutput`, and `test_producer_to_artifact_transport.py`
covers field reachability); the **serialization form** is not. One test that has
`records.py` write the artifact and `per_file_best.build_table` read it, with a
`-inf` best score in play, closes it.

### 12.3 The two halves of 07c never meet

`test_pr07c_validation_pricing.py` runs a real trainer and asserts the *sidecar
contents* (`:551-643`), and separately drives `_watchdog_deadline_provider` over
*hand-written* sidecars (`:157-380`). **No test feeds a real subprocess's
sidecar into the real provider.** That join is the exact hop 07a lost, it is ~4
lines inside the existing `_run` fixture, and it converts the module from
"arithmetic + reachability, separately" into an end-to-end claim.

Related, unowned at any layer: the same write-timing class can exist for the
**inference and scoring** sidecars. Currently untested, and structurally
invisible to fakes.

### 12.4 `manifest.json` has two independent hand-written definitions

Producer: `sdsc_submission_scripts/run_one_iteration.py:495-590`
(`status` / `iteration_dir` / `output_path` / `model_name` /
`run_output_sha256`). Consumers: `execute_tools/per_file_best.py:182`,
`core/resume.py:246`, `dashboard/api/router.py:531` — each tested against its
own hand-built dict. No schema, and no test comparing the two key sets.

### 12.5 Portability defects — three, all fixable in place

| Site | Defect |
|---|---|
| `ml_models/test_step03_m6_cardinality_derivation.py:184` | `pathlib.Path("ml_models/models_sandbox.py")` — CWD-relative. Direct CLAUDE.md violation |
| `workflows/test_step04b_task_description_single_source.py:277` | `Path("configs/task_config.yaml").resolve()` — same class |
| `scripts/test_c12b_legacy_fidelity.py:25` | `LEGACY_ROOT = Path("/home/tidmad/TIDMAD")`. It *does* declare and skip, satisfying the letter of the rule, but the path is hardcoded rather than env-configurable. **Keep the test** — it is the only legacy-source oracle, pinning the FCNet ladder to `network.py:291` and `lr=0.0005` to `train.py:113` — and move the root behind an env var with the current value as documented default |

Also: `scripts/test_bg_validation_harness.py:273,414` hardcode
`/home/klz/Data/SIDEREIS_DATA/bg0_evidence_20260802/bg0_fixture.json` (retiring
with the file).

### 12.6 Two unguarded hazards

* **The self-referential-default anti-pattern is unguarded.** 26
  `model_fields[…]` reads exist; all but one are currently benign, and nothing
  prevents the next one. A cheap guardrail could forbid comparing a value to a
  default fetched from the model under test.
* **Thin statistical margins are unguarded.** The 07a rung's
  `abs(r3 - train_ref) > 1e-4` was measured at 1.52e-4 on a clean baseline —
  1.5× its own threshold, verified by six pre-fix runs. Nothing detects a test
  whose margin is that thin.

---

## 13. Proposed waves — re-projected

### Wave 1 — mechanical, HIGH confidence

| | |
|---|---|
| Cases | 9,980 → ~9,644 (**−336**) |
| Contents | §6 Pydantic restatements (−132) · §7 cross-product collapses (−204) |
| Replacement authority | Pydantic/Pyright · one stronger scanning invariant per family |
| Classes retained | **all** — each collapsed family keeps its single failure class, with a better message (the banned-vocab scan reports *all* violations; today only the first cell trips) |
| Validation | per family, plant the violation the originals caught and confirm the survivor goes RED |

### Wave 2 — superseded authorities, MEDIUM-HIGH

| | |
|---|---|
| Cases | ~9,644 → ~9,395 (**−249**) |
| Contents | §10.1 verified supersessions (−29) · §10.2 closed-campaign harnesses (−220, **conditional**) |
| Blocked on | re-homing the reachability oracle in `test_environment_stability.py` and `test_formal_stability_controller.py` (§10.2) before the harness is deleted |
| Validation | the five-field record per retirement: `TEST / WHAT IT CLAIMED / INDEPENDENT FAILURE CLASS / EXISTING EVIDENCE / WHY REMOVAL DOESN'T REDUCE ACCEPTANCE` |

### Wave 3 — Gate-2 hygiene: **zero deletions**

| | |
|---|---|
| Cases | unchanged |
| Contents | fix the §9.1 modelled-timing half and the `:701` tautology · rename `TestWatchdogDeadlineUsesPhaseFactor` and two siblings · mark 111 real-subprocess cases `slow` · fixture-scope **~45 redundant subprocess launches** away |
| Value | the highest-value wave, and it removes nothing |
| Validation | before/after launch counts; unchanged assertion counts |

### Wave 4 — Gate-1 reassignment, small

| | |
|---|---|
| Cases | ~9,395 → ~9,385 (**−10**) |
| Contents | §8's four families |
| Precondition | for each removal, name the Gate that owns it **and confirm that Gate actually runs for the PR class in question** |

### Wave 5 — targeted additions

| | |
|---|---|
| Cases | ~9,385 → ~9,395 (**+10**) |
| Contents | §12.1 FocalLoss1D closed-form parity (~3) · §12.2 producer→consumer serialization (1) · §12.3 real-sidecar → real-provider join (1) · §12.4 manifest key-set contract (1) · §12.5 three portability fixes (0 net) · §12.6 two guardrails (~4) |

### Wave 6 — extrapolation, NOT yet evidence-backed

The same families exist in sub-modules that were counted but not read
body-by-body — `ml_model_implementor/test_config_adjustment_schema.py` (22),
`result_interpretation_agent/` (263), `ml_model_proposal_agent/` beyond the two
files read (602 total), `sdsc/test_run_one_iteration.py` (74). An AST pass
counts **1,078 of 4,210 (26 %)** functions in `tests/unit/agent` with exactly one
short assert — offered as a **size estimate, not a verdict**; the
no-heuristic-classification rule requires reading each body.

Plausible additional reduction: **−600 to −1,000**. It must not be spent before
it is earned.

---

## 14. Projected suite

```text
                                    cases
current                             9,980
  Wave 1  mechanical               −  336
  Wave 2  superseded (conditional) −  249
  Wave 3  Gate-2 hygiene           −    0   (~45 fewer subprocess launches)
  Wave 4  Gate-1 reassignment      −   10
  Wave 5  additions                +   10
                                   ------
evidence-backed floor              ~9,395   (−5.9 %)
  Wave 6  extrapolated             −600..−1,000
                                   ------
realistic landing                8,400–8,800  (−12 % to −16 %)
```

**This does not reach 5,500–6,500, and the audit found no honest path that
does.** Closing the remaining ~2,500-case gap means retiring a *category*, not
duplication:

* the 204-file / 937-function `stepNN` capture-first ladder (§18.3);
* the 169-case V19 launcher family (§18.6);
* the 111 real-subprocess cases, by moving them to Gate 2 (§9.2 argues against);
* `core/test_gpu_milestone_trace.py` (45), a diagnostic instrument built to
  locate a fixed 208 MiB under-read — inert-by-default production code with 8
  AST placement guards. Flagged as **operator territory**; the audit found no
  evidence either way that the investigation has concluded.

Each of those is a coverage decision with a named cost. None is a redundancy
finding, and this document will not present them as one.

---

## 15. Test ownership matrix

| Failure class | Canonical owner | Repository example |
|---|---|---|
| syntax, style, import order | **Ruff** | line length, unsorted imports |
| static typing | **Pyright** | strict mode across `core/runtime_control/` |
| ordinary field type / range / default | **Pydantic** | `validation_max_samples: int \| None = None, ge=1` |
| cross-field schema invariant | **Unit** | `validation_samples == validation_requested_samples`; `coerce_status` |
| numeric / scientific semantics | **Unit** | the frozen score formula; **`FocalLoss1D` parity (missing — §12.1)** |
| identity / hash / serialisation stability | **Unit** | `calibration_key`, batch sha256, `config_hash12` |
| contract resolution & protocol mapping | **Unit** | `resolve_input_dtype`; `{source}_to_{target}` |
| deterministic failure classification | **Unit** | `NotScoreableError` → `error_scoring` |
| architectural erosion | **Unit guardrail** | no model-name branches; no `TIDMAD_DATA_DIR` in core |
| worker-death matrix (signals × phases) | **Unit, real subprocess** | `test_probe_hard_timeout.py` — Gate 2 gives one lifecycle, not a matrix |
| rendered prompt bytes | **Unit** | PB-1 / PB-2 goldens |
| stub-response fidelity | **Unit** | `test_stub_llm_bridge.py` — Gate 1 cannot see stub drift |
| prompt → real LLM structured output | **Gate 1** | planner/reflector against a real model |
| real data loading, subprocess, GPU | **Gate 2** | HDF5 → tensor → device |
| **sidecar/persistence TIMING** | **Gate 2** | the 07c defect — a fake cannot own this |
| watchdog against real elapsed time | **Gate 2** (+ `test_watchdog.py::TestKillTree` for the process-group half) | deadline vs actual wall clock |
| real plugin registration lifecycle | **Gate 2** | MODEL_REGISTRY from a real subprocess |

---

## 16. New-test admission rule (permanent governance)

**Every new test must name its unique failure class.**

> If this test were deleted, what concrete bug would escape — and why would
> Ruff, Pyright, Pydantic, an existing unit test, Gate 1 and Gate 2 **all**
> miss it?

No answer ⇒ not added. **"Extra safety" is not an answer.** Nor is "this
function has no test".

**Every new test must state how it FAILS.** An author who cannot describe the
mutation that turns it RED has written decoration.

**Every feature design declares ownership up front:**

```text
UNIT OWNERSHIP    : ...
GATE-1 OWNERSHIP  : ...
GATE-2 OWNERSHIP  : ...
```

A design that leaves a row empty is making a claim and should say so.

**Anti-patterns, promoted to review triggers:**

* a fixture that manufactures the exact state whose *arrival or timing* is the
  property under test (§9.1 — this recurred **during** the PR that discovered it);
* an assertion that is arithmetic over constants the test itself chose;
* `x < x + positive` and other tautologies dressed as a reduction check;
* a cross-product parametrisation whose cells share one failure class;
* comparing a value to a default fetched from the model under test;
* `assert status == "success"` as the whole assertion;
* a class name that promises coverage the body cannot deliver (§9.1, third item);
* a new test family added while the layer it supersedes is left in place;
* an unfixtured real subprocess launched once per test method (§9.3).

---

## 17. Implementation / validation plan

**No implementation in this document.**

1. **Per-family record** for every retirement — `TEST / WHAT IT CLAIMED /
   INDEPENDENT FAILURE CLASS / EXISTING EVIDENCE / WHY REMOVAL DOESN'T REDUCE
   ACCEPTANCE`.
2. **Mutation evidence, selectively** — for every consolidated matrix and
   authority boundary, plant the defect the originals caught and confirm the
   survivor goes RED. Observe the mutation-proof hygiene rules: clear `.pyc`,
   assert the target site count is exactly 1, restore, re-run the baseline. Not
   repo-wide mutation testing.
3. **Wave-by-wave PRs**, each independently reviewable and revertible. Never one
   PR deleting thousands of cases.
4. **Gate-availability check before any Gate-ownership removal.** Deleting a
   test in favour of "Gate 2 owns it" is valid only if that Gate actually runs
   for the PR class in question. Otherwise the property becomes unowned.
5. **Wave 3 first.** It deletes nothing, fixes a live recurrence of the
   motivating defect, and buys the runtime. It is also the cheapest to review.
6. **Wave 2's harness block is blocked** on the §10.2 re-homing.
7. **Counts reported per wave** — collected cases and functions, before/after,
   plus subprocess-launch count for Wave 3.

**The failure mode to avoid:** a wave that is green because it deleted the tests
that could have failed.

---

## 18. Open questions requiring an operator ruling

1. **The target number.** ~8,400–8,800 is what redundancy-removal honestly
   yields. 5,500–6,500 requires deleting coverage. Which is the goal? If the
   latter, §14 lists the four categories that would have to go, each with its
   cost — the choice is which coverage to stop having.
2. **The closed-campaign harnesses (§10.2, 220 cases).** Retire
   `scripts/c2_prephase_validation.py` and `scripts/bg_admission_validation.py`
   with their tests, after re-homing the reachability oracle in
   `test_environment_stability.py` and `test_formal_stability_controller.py`?
   Or keep both script and tests?
3. **The `stepNN` capture-first ladder (204 files, 937 functions).** Retire once
   the step merges, or keep as historical regressions? The audit found **no**
   internal supersession, so this is purely a policy call.
4. **Guardrail policy.** Keep repo-wide scanning guardrails? They inflate the
   count, they do **not** scale with the repo (one case over all files), and 27
   of 31 cases in the largest one are detector self-tests that exist because a
   blind guardrail passed review on 2026-08-02.
5. **`core/test_gpu_milestone_trace.py` (45 cases, 740 lines).** Has the 208 MiB
   under-read investigation concluded? If yes, this is the largest single block
   whose *purpose* may have expired. No evidence either way was found in source.
6. **`v19_queue_runner.sh` — retired or not?** `sdsc_submission_scripts/README.md:77`
   labels it *"current production surface"*; `v20_queue_runner.py:37` sets
   `LAUNCHER = launch_v20_campaign.sh`. **These are not necessarily in
   conflict** — they may be two co-existing campaign surfaces. But 169 cases
   (`test_v19_campaign_pinning.py` 61 · `test_campaign_admission.py` 49 ·
   `test_v19_queue_runner.py` 32 · `test_c13_stop_semantics.py` 14 ·
   `test_v19_chain_role_resolution.py` 13) and the `c14` Gate-parity
   *reference* both hang on the answer. No deletion is proposed on evidence this
   ambiguous.
7. **Wave 5 scope.** All six additions, or only §12.1 (FocalLoss1D) and §12.3
   (the real-sidecar join) — the two whose absence has already produced, or
   nearly produced, a real escape?

---
---

# PHASE 2 — TEST OWNERSHIP / CATEGORY-RETIREMENT AUDIT

**STATUS — DESIGN / OBSERVATION ONLY. Still no test added, deleted,
consolidated or modified.** Audited read-only at `52bd98ba` (master, PR #219
merged), 2026-08-17.

Everything above this line is **Phase 1** and stands as written: a redundancy
audit, and a useful one. It is preserved unedited, including the places where
it was wrong.

**Phase 1 asked:** *which existing tests are redundant?* Answer: far fewer than
expected — ~630 evidence-backed, extrapolating to maybe 1,600.

**Phase 2 asks a different question:** *which entire CATEGORIES of testing
should still exist as Unit-test ownership in the current architecture?*

A test can be non-duplicate, internally correct, and historically justified,
and still no longer deserve to exist. The Phase-1 answer "not redundancy,
therefore retain" — which appears in several of its own §11 entries — is not a
valid disposition for a whole family. The governing question here is:

> **Would we deliberately create this test today, given the CURRENT
> architecture and current Gate ownership?**

---

## P2-1. Maintenance-shape metrics

Collected at `52bd98ba` by `pytest tests/unit --collect-only -q` plus an AST
pass over 535 files. Case counts are node IDs; function counts are node IDs
with the `[param]` suffix stripped, cross-checked against an independent AST
count of `def test*` (both give **8,284** — the two methods agree exactly).

### Whole suite

| Metric | Value |
|---|---:|
| collected cases | **9,980** |
| distinct test functions | **8,284** |
| distinct test files | **534** |
| **cases ÷ functions** | **1.20** |
| median asserts / function | **2.0** |
| mean asserts / function | 1.97 |

### The single most important number in this document

**Cases ÷ functions is 1.20.**

Parametrisation contributes only **1,696 cases** across the entire suite. The
suite is not 9,980 cases because of parametrised matrices — it is **8,284
distinct maintained claims**, each a separate function a future maintainer must
read, understand and preserve.

This reframes the whole exercise, and it retires a hope Phase 1 implicitly
carried:

```text
Phase 1 Wave 1 collapsed ~204 cross-product cells.
Absolute ceiling on parametrisation compression = 1,696 cases, ~0 functions.

    cases     9,980 -> 8,284   is the ENTIRE parametrisation budget
    functions 8,284 -> 8,284   unchanged

Compressing every matrix in the repository to one case each would remove
17% of cases and NOT ONE maintained claim.
```

Which is exactly the failure mode the operator named: *"cases 10,000 → 6,000
with functions unchanged may mostly be parametrization compression and not
solve maintainability."* The suite cannot be fixed by compressing cells,
because the cells are not the problem. **The target must be functions.**

### Assertion-density distribution

| asserts in function | functions | share |
|---:|---:|---:|
| 0 | 734 | 8.9 % |
| **1** | **3,236** | **39.1 %** |
| 2 | 2,149 | 25.9 % |
| 3 | 1,138 | 13.7 % |
| 4 | 500 | 6.0 % |
| 5 | 249 | 3.0 % |
| 6+ | 278 | 3.4 % |

**39 % of all maintained claims are single-assertion functions.** The 734
zero-assert functions are not necessarily empty — most use
`pytest.raises` as the assertion, which the AST pass does not count as
`ast.Assert`; they need per-body reading before any conclusion.

Single-assert functions are not automatically wrong: one assert per function
gives the best failure localisation, which is precisely what a unit tier is
for. But 3,236 of them is the population where "would we create this today"
has the highest yield, and it is the population Phase 1 did *not* classify
(the no-heuristic-classification rule forbids doing it by AST shape).

### By directory

| Directory | cases | functions | files | cases/fn |
|---|---:|---:|---:|---:|
| `agent` | 4,210 | 3,534 | 233 | 1.19 |
| `core` | 2,507 | 2,100 | 108 | 1.19 |
| `execute_tools` | 1,160 | 971 | 81 | 1.19 |
| `sdsc_submission_scripts` | 563 | 397 | 25 | 1.42 |
| `scripts` | 542 | 450 | 25 | 1.20 |
| `ml_models` | 272 | 202 | 14 | 1.35 |
| `workflows` | 255 | 253 | 16 | 1.01 |
| `tools` | 140 | 124 | 7 | 1.13 |
| `guardrails` | 100 | 54 | 8 | 1.85 |
| `examples` | 80 | 60 | 6 | 1.33 |
| `agent_generated` | 56 | 54 | 3 | 1.04 |
| `dashboard` | 44 | 44 | 2 | 1.00 |
| `nodes` | 30 | 20 | 3 | 1.50 |
| root files | 21 | 21 | 3 | 1.00 |

The ratio is remarkably flat — 1.19 in the three largest directories. There is
no directory where parametrisation explains the size. `guardrails` at 1.85 is
the most parametrised and is also the smallest meaningful directory (100
cases), which is the opposite of a problem.

### Top files by FUNCTIONS (not cases) — the maintenance view

| fn | asserts | lines | File |
|---:|---:|---:|---|
| 105 | 298 | 1,631 | `agent/prompt_templates/test_literature_review_prompts.py` |
| 89 | 141 | 2,175 | `workflows/test_model_exploration.py` |
| 88 | 158 | 1,178 | `scripts/test_c2_prephase_validation.py` |
| 75 | 116 | 843 | `scripts/test_bg_validation_harness.py` |
| 71 | 148 | 1,140 | `agent/ml_code_validator_agent/test_validator_agent.py` |
| 71 | 210 | 2,059 | `agent/tune_ml_hyperparam_agent/test_tuning_agent.py` |
| 70 | 118 | 1,541 | `core/test_resume.py` |
| 66 | 150 | 1,696 | `sdsc/test_run_one_iteration.py` |
| 63 | 129 | 1,493 | `agent/ml_model_proposal_agent/test_pipeline_runner.py` |
| 63 | 103 | 979 | `agent/test_llm_bridge.py` |
| 61 | 143 | 1,343 | `agent/result_interpretation_agent/test_interpretation_agent.py` |
| 60 | 119 | 1,083 | `agent/result_interpretation_agent/test_vocab_feedback.py` |
| 59 | 128 | 909 | `agent/evaluate_vram_skill/test_isolated_preflight.py` |
| 58 | 65 | 749 | `agent/ml_model_proposal_agent/test_phase_b_schemas.py` |
| 57 | 184 | 2,194 | `agent/ml_literature_review/test_node.py` |

Note `test_phase_b_schemas.py`: 58 functions carrying **65 assertions total**
— 1.1 per function. That shape (many functions, one short assert each,
schema-adjacent) is the Phase-1 §6 Pydantic finding seen from the maintenance
side.

### The four retirement categories, sized

| Category | cases | functions | files |
|---|---:|---:|---:|
| StepNN / pr0N ladder (`test_(step\|pr)0\d`) | 1,283 | 935 | 102 |
| Files launching real subprocesses | 1,262 | 1,000 | 59 |
| V19 launcher / campaign family | 246 | 159 | 7 |
| Guardrails + milestone tracer | 145 | 98 | 9 |
| **union (overlaps removed)** | **2,455** | **1,872** | **158** |

Overlaps: 10 StepNN files also spawn subprocesses; 7 V19 files do.

**The union is 24.6 % of cases and 22.6 % of functions** — almost exactly the
~2,500-case gap between the redundancy-only projection and the working target.
That is not a coincidence: these four categories *are* the gap. Whether they
should shrink is the Phase-2 question, and it is answered per category in
P2-4…P2-7, not by arithmetic.

### Wall time

Existing evidence only. The full unit suite ran **951 s** (9,967 passed / 3
skipped) at `3cb6eef1` from a clean tree, and exact-head CI's
`Lint + Type + Unit Tests` job took **17 m 12 s** including lint and pyright.
**Per-directory wall time was NOT measured** — obtaining it requires a full
timed run per directory, which the operator's standing rule reserves for
terminal gates. It is recorded here as a gap rather than estimated.

What can be said without a run: the ~45 redundant subprocess launches
identified in Phase 1 §9.3 are the only quantified wall-time item, and they are
recoverable without deleting anything.

---

## P2-8. Redesigning the two weak "load-bearing" tests

Both already have an operator ruling: **redesign, do not delete.** They exposed
the stronger problem — *the intended load-bearing semantic property is not
actually being tested*. Below, for each: the intended property, why the current
assertion does not prove it, the minimal stronger replacement, and the mutation
that must turn the replacement RED.

### P2-8.1 `test_pr07c_validation_pricing.py:309` — the modelled-timing half

**Intended semantic property.** The refreshed deadline (training + validation)
reaches the sidecar at an elapsed time *below* the stale training-only
deadline — i.e. the fix arrives before the kill it prevents.

**Why the current assertion does not prove it.** Lines 324-330:

```python
first_batch_seconds = VALIDATION_ACTUAL_S * (500 / 15_000)
elapsed_when_prediction_lands = TRAIN_ACTUAL_S + first_batch_seconds
assert elapsed_when_prediction_lands < old_deadline
```

`VALIDATION_ACTUAL_S`, `TRAIN_ACTUAL_S` and the `500/15_000` batch fraction are
all constants the test itself chose, and the "elapsed" value is a **model** of
production, not an observation of it. Production could defer the write
arbitrarily and this assertion would not move. It is the original defect one
level up.

**Minimal stronger replacement — and it already exists.**
`tests/unit/execute_tools/test_pr07c_validation_persistence_timing.py::TestValidationPredictionArrivesDuringThePass::test_the_sidecar_holds_a_measurement_backed_prediction_mid_pass`
runs a **real in-process streaming run whose model reads the live sidecar from
disk during validation** (`:66-73`, `:98`, `:117`) and asserts
`first_seen < total` (`:198`) with `source == "real_validation_verification"`
and `source in MEASUREMENT_BACKED_SOURCES` (`:203-204`). That is the property,
observed at the production boundary, over the run's own batch sequence rather
than a chosen index.

So the disposition is: **delete lines 324-330 with a pointer to the owning
test**, keep the refresh-observation half of `:309` (rewrite the sidecar,
re-read, assert `refreshed == (T+V) × factor`), and record
deadline-vs-real-elapsed as Gate-2 territory. Net **0 cases**; one modelled
assertion replaced by a pointer to an executable one.

**Mutation that must turn the survivor RED:** restore the pre-fix deferral in
`execute_tools/train_engine_sandbox.py` — move the `on_verified()` callback out
of `_validation_pass`'s terminal branch so completion runs only after the
function returns. `test_the_sidecar_holds_a_measurement_backed_prediction_mid_pass`
must fail on `assert appeared` / `first_seen < total`. This mutation was the
Gate-2 attempt-1 production defect, so the proof is historical as well as
mechanical.

### P2-8.2 `test_pr07c_validation_pricing.py:701` — the tautology

**Intended semantic property.** The training ACTUAL was reduced by the
validation seconds, so the two accountings **partition** the training window:
neither absorbs the other, and no double count exists.

**Why the current assertion does not prove it.**

```python
assert components["training"]["actual_seconds"] < (
    components["training"]["actual_seconds"] + validation_total
)
```

`x < x + c` with `c > 0` already established at `:695`. Necessarily true. The
comment above it asserts the semantics; the code asserts nothing. This is the
sharpest instance in the repository of the rule the operator stated:
**load-bearing prose does not make a weak assertion load-bearing.** The real
property has never been tested at all — only a necessarily-true proxy stood in
for it, which is why the file reads as if it were covered.

**The production site it should be bound to** —
`execute_tools/train_engine_sandbox.py:1726-1728`:

```python
runtime_session.record_phase_actual(
    "training", (time.perf_counter() - t_train_start) - validation_seconds_total
)
```

and `:1743` records `validation_seconds_total` as the validation ACTUAL.

**Minimal stronger replacement.** Bracket the partition against the wall time
of the training window as measured by the test around the run:

```text
W = wall measured by the test across the training window (an upper bound)
assert training_actual + validation_total <= W
assert training_actual + validation_total >= W - overhead_budget
```

i.e. the two accountings sum to the window, within a stated overhead budget —
the same bracketing method the Gate verdict used, for the same reason: an exact
equality is not observable, a bracket is.

**Mutation that must turn it RED:** change `:1727` from
`- validation_seconds_total` to `- 0.0`. Under the current assertion the test
stays GREEN (the tautology cannot see it). Under the replacement,
`training_actual` now contains the validation seconds, so
`training_actual + validation_total ≈ W + validation_total > W` and the upper
bound fails. This is the check that makes the per-optimizer-step cost model's
purity actually guarded — the thing Phase 1 called "load-bearing" while it was
guarding nothing.

**Governance rule these two produce**, proposed for §16:

> An assertion whose truth follows from the test's own constants, or from
> arithmetic that cannot reference production state, does not become
> load-bearing because a docstring says the property matters. Every assertion
> claimed as load-bearing must name the production mutation that turns it RED.

---

## P2-9. The two verified coverage gaps — designed oracles

Both accepted by operator ruling. The instruction was explicit: **one strong
oracle each, not a new test family.**

### P2-9.1 `FocalLoss1D` numerical correctness — 3 cases

**The hole, verified.** `ml_models/loss_models_sandbox.py:135-168` is asserted
by CLAUDE.md to be line-for-line identical to TIDMAD's `network.py:FocalLoss1D`
and is a frozen scientific quantity. The only coverage,
`tests/unit/ml_models/test_loss_functions.py::TestFocalLoss1D`, is four
property tests: `loss.shape == torch.Size([])` (guaranteed by
`reduction='mean'`), `loss.item() >= 0.0` (mathematically guaranteed),
`loss_perfect < loss_random`, and `loss_sum > loss_mean`. Setting
`alpha = 0.25` — **the exact drift CLAUDE.md records as a past defect** — leaves
all four green.

**The closed form.** Line 161 masks to the target class, so for target class
`c`:

```text
loss = mean over (batch, length) of   -alpha * (1 - p_c)^gamma * log(p_c)
```

**Verified expectations** (computed by hand, then checked against the real
implementation — three match to 1e-9, the fourth to 6e-9, i.e. float32
rounding):

| alpha | gamma | logits (2 classes) | expected | pins |
|---:|---:|---|---:|---|
| 0.5 | 2.0 | `[0, 0]` → p=0.5 | **0.0866433978** | alpha at its paper value |
| 0.5 | 0.0 | `[0, 0]` | **0.3465735912** | the focal exponent |
| 0.5 | 2.0 | `[ln 3, 0]` → p=0.75 | **0.0089900587** | softmax + target masking |

The historical drift is unmissable: `alpha = 0.25` on row 1 gives
**0.0433216989**, exactly half. Three cases, hand-computable, no fixture, no
GPU.

**Placement:** beside the other frozen scientific oracles, in the
`test_step00_numeric_baselines.py` style (expectations hardcoded, never derived
from the implementation under test).

**Mutation set:** `alpha 0.5 → 0.25` (row 1 RED); `gamma 2.0 → 1.0` (rows 1
and 3 RED); removing the `targets_one_hot *` mask at `:161` (row 3 RED, row 1
survives — which is why row 3 exists).

### P2-9.2 The producer → consumer non-finite serialization boundary — 1 case

**The hole, verified.** Two different serializations of the same object:

| | code | emits for `-inf` |
|---|---|---|
| **production** `nodes/ml_hyperparameter_tune_agent/records.py:952-954` | `coerce_nonfinite_to_none(agent_output.model_dump())` then `json.dump(..., indent=4)` | `null` |
| **test fixture** `tests/unit/execute_tools/test_per_file_best.py:145-198` | `f.write(output.model_dump_json())` | `-Infinity` |

The production comment (`:948-951`) states the constraint: `model_dump_json`
emits non-standard `-Infinity` tokens that break the dashboard's `JSON.parse`.
So the `-inf` path through `build_table` and the `run_output_sha256` byte-check
is exercised **only against a shape production never produces**. Field drift is
already caught (the fixture routes through `HyperparamTuningOutput`, and
`test_producer_to_artifact_transport.py` covers field reachability); the
serialization *form* is not.

**The oracle — one test, real producer to real consumer:**

```text
build a HyperparamTuningOutput with a -inf best score (the no-signal sentinel)
  -> let records.py write run_output_{run}.json  (the REAL producer, not a fixture)
  -> assert the on-disk text contains no "-Infinity" / "Infinity" / "NaN" token
  -> assert a strict RFC-8259 parse succeeds
  -> feed it to per_file_best.build_table  (the REAL consumer)
  -> assert the row renders the no-signal case, not a numeric -inf
```

**Mutation that must turn it RED:** drop `coerce_nonfinite_to_none` at `:952`
so the producer writes `model_dump()` raw — the on-disk token check fails
immediately. Second mutation: have the consumer treat `None` as `0.0`; the
final row assertion fails.

**Why unit and not Gate 2:** the boundary is a pure serialization contract with
no LLM, no GPU and no lifecycle. A Gate would exercise it incidentally and
localise it terribly.


---

## P2-3. Backbone-first analysis

The forcing question, per operator instruction: **if the repository could
retain only ~1,500–2,500 deterministic tests, which would be chosen FIRST?**
Not a target — a way to force semantic priority to be stated before anything is
deleted.

The backbone below is assembled from families whose independent failure class
was **verified against source** in Phase 1 §11, plus the four families Phase 1
did not enumerate (protocol mapping, contract resolution, genericity rungs,
node-schema completeness). Counts are at whole-file granularity and are
therefore an **upper bound** — several of these files also contain material
that is not backbone (most visibly `/schemas/`, where Phase 1 found ~49
Pydantic restatements).

### Tranche 1 — verified indispensable

| Family | cases | fn | files | Unique failure class | Why no Gate / static tool replaces it |
|---|---:|---:|---:|---|---|
| Frozen numeric / scientific oracles | 183 | 157 | 9 | a wrong number that still runs — anchor sha256, `s_max`, `LOG_BASE`, grand-mean vs mean-of-means, the `1e-10` NaN boundary, the 15-cell loss matrix | Gates adjudicate *execution*, never whether the metric is arithmetically right. A frozen formula has no behavioural symptom |
| Identity / hash / serialisation stability | 119 | 97 | 6 | values silently change under an unchanged key; two measurement buckets merge; writer and reader of `candidate_config_hash` drift by one key — indistinguishable from "no calibration exists" | invisible to every behavioural test by construction |
| The three refusal lanes | 128 | 83 | 4 | lane 2 read as lane 3 — a neighbour's GPU occupancy becomes "reduce model size" and a campaign shrinks to toy models (the V19 incident) | a Gate sees one lane per run; the distinctness is cross-lane |
| Admission / attribution distinct semantics (8 modules) | 318 | 242 | 9 | pre-flight vs runtime vs post-hoc vs quota vs realized-memory collapsing into one "resource failure" notion | same — the property is that they stay separate |
| VRAM authority partition | 140 | 101 | 3 | a host-memory kill phrased as a VRAM verdict; an inconclusive result carrying authority it must not have | Gate 2 is too expensive a place to prove a SIGTERM-ignoring descendant is reaped |
| Architectural guardrails | 100 | 54 | 8 | architectural erosion nothing else notices; 27 of the 31 launcher-guard cases are detector self-tests that exist because a blind guardrail once passed review | no runtime symptom at all |
| Cross-schema concepts + production defaults | 94 | 56 | 2 | the ten cross-schema divergences and eleven unpinned defaults a 6,900-test per-field suite missed | per-field shape cannot express a cross-model concept |
| Metric-order authority (07b) | 63 | 40 | 2 | flip `MetricSpec.direction` and a consumer left on a bare `max()` still answers correctly under TIDMAD and never calls the authority | only a recording double catches a bypassed authority |
| Validation-pass isolation + envelope (07a/07c) | 66 | 56 | 3 | a validation pass that perturbs RNG/optimizer state; mean-of-batch-means weighting; a clamp that overshoots or reaches the planner. Ships its own negative control | the RNG-fork property has no observable output difference at Gate scale |
| Estimator declaration-vs-substitution | 67 | 56 | 3 | an estimator substituting its own literal (`seg=1000`, `epochs=10`) prices a run the system never executes. Carries mutation provenance (M8) | the two errors cancel in the static path; only step-count assertions see it |
| Tuner control boundary + node public boundary | 59 | 38 | 2 | a cleanup-owned transient captured by a helper; a private module imported across the node boundary | pyright cannot see either |
| Examples maturity pins | 80 | 60 | 6 | `examples/` silently becoming a second authority; snapshots regenerated from the owning production accessor and deep-compared | nothing else compares the projection to its source |
| LLM salvage + stub fidelity | 91 | 91 | 3 | the parsing layer that must hold when a real LLM misbehaves; stub drift crashing a zero-cost smoke mid-chain | Gate 1 cannot see stub drift; it *is* the real model |
| Watchdog kill-tree + probe timeout matrix | 55 | 48 | 2 | a deadline enforced against real elapsed time with a real process group; 4 death-signals × 3 phases | Gate 2 gives one lifecycle, not a matrix |
| **tranche 1** | **1,563** | **1,179** | **62** | | |

### Tranche 2 — contract surfaces Phase 1 did not enumerate

| Family | cases | fn | files | Unique failure class |
|---|---:|---:|---:|---|
| Protocol mapping (every directed edge) | 110 | 78 | 8 | a field silently dropped between two nodes — the exact hazard the schema/storage/protocol triad exists to prevent |
| Contract resolution / the one probe builder | 89 | 59 | 5 | a second dataset convention reappearing; a capability claiming unavailability without a reason |
| Genericity contrasts / axis rungs | 27 | 25 | 3 | a "generic" path that silently answers TIDMAD for every task |
| Node schema completeness | 388 | 325 | 18 | an input schema that no longer validates that all required fields arrived — **discount ~49 Pydantic restatements found in Phase 1 §6** |
| **tranche 2** | **614** | **487** | **34** | |

### Backbone total

```text
tranche 1                1,563 cases   1,179 functions
tranche 2                  614 cases     487 functions
less Pydantic restatement  -49 cases     -40 functions (approx)
                         -----------   ---------------
BACKBONE                ~2,130 cases  ~1,630 functions   ~96 files
```

**This lands inside the 1,500–2,500 band without being aimed at it.** The
number was derived by summing families whose failure class was verified one at
a time, then reading the total — not by trimming toward a target. That is the
strongest evidence in this document that the band was a reasonable intuition.

### What the backbone implies

```text
whole suite      9,980 cases   8,284 functions
backbone        ~2,130 cases  ~1,630 functions      21 % / 20 %
remainder       ~7,850 cases  ~6,650 functions      79 % / 80 %
```

The remainder is **not** thereby condemned. Reasoning outward, the intended
suite is:

```text
   backbone
 + necessary compatibility layer     (back-compat oracles that are still true)
 + necessary negative / error matrix (fail-closed refusals per boundary)
 + necessary genericity coverage     (three-track contrasts)
 + selected regressions              (mechanism still reachable)
 = intended Unit suite
```

Each of those four additive layers must be sized from source, not assumed. The
category audits in P2-4…P2-7 size the largest contested parts of the
remainder; whatever is neither backbone nor a justified layer is the honest
retirement candidate.

**The methodological point:** starting from 2,130 and adding back is a
different exercise from starting at 9,980 and being afraid to delete. The first
forces every layer to state what it buys. Phase 1 did the second, which is why
it could only find ~630 cases.


---

## P2-0. TWO FINDINGS THAT OUTRANK THIS AUDIT

Found while auditing. Neither is a pruning matter; both are recorded here
because this is where they surfaced, and both need an operator decision.

### P2-0.1 The launcher guardrail is blind to the exact call shape of the
### incident it was written to prevent — and reports the repo CLEAN

`tests/unit/guardrails/test_no_test_executes_a_launcher.py` exists because on
2026-07-31 a test executed `v19_gate0_pair_runner.sh`, two chains launched, and
real API calls were billed (`:3-6`).

**Two test files execute a production launcher today:**

```python
# tests/unit/sdsc_submission_scripts/test_campaign_admission.py:31,84
RUNNER = REPO_ROOT / "sdsc_submission_scripts" / "v19_queue_runner.sh"
subprocess.run(["bash", str(RUNNER), *args], ...)

# tests/unit/sdsc_submission_scripts/test_v19_gate0_pair_runner.py:35,211
RUNNER = REPO_ROOT / "sdsc_submission_scripts" / "v19_gate0_pair_runner.sh"
subprocess.run(["bash", str(RUNNER)], ...)
```

The second is **the same script and the same call shape as the incident**.

**Verified by running the guardrail's own detector**, not by inspection:

```text
_executed_strings(test_campaign_admission.py)      -> 13 strings, launcher hits: []
_executed_strings(test_v19_gate0_pair_runner.py)   -> 33 strings, launcher hits: []
_scan_every_test_file()                            -> offenders {}, 591 scanned, 64 with spawns
```

**The guardrail reports the repository clean.** Cause: `_executed_strings`
(`:90-132`) collects only `ast.Constant` nodes. In `["bash", str(RUNNER), *args]`
the launcher path is an `ast.Call`, so the argv-list branch (`:111-119`) sees
`parts == ["bash"]`, finds `len(parts) < 2`, and appends nothing.

This is a **second instance of the same defect class the file already fixed
once**: `:107-110` and `:338` record that the argv-list form — how this repo
calls `subprocess` almost everywhere — was invisible until a mutation proof
found it. The fix closed the literal-list case and left the computed-path case
open.

**What currently prevents a real launch** — and it is not the guardrail:

| barrier | evidence |
|---|---|
| PATH `screen` shim | `test_campaign_admission.py:37-51`, `test_v19_gate0_pair_runner.py:171-188` |
| temporary `GATE_ROOT` / `WS_ROOT` | fixtures in both files |
| source-safe entry guard | **does not apply** — `v19_gate0_pair_runner.sh:448` guards *sourcing*; direct execution runs `main` by design |

So the protection is one PATH shim. If a shim were non-executable, mis-pathed,
or bypassed by a launcher that learned to use `nohup`/`setsid` instead of
`screen`, a real chain would start under pytest and bill real API calls.

**Recommendation (not applied — this is a production-safety defect, outside
the autonomous tier):**

1. Extend `_executed_strings` to resolve module-level `Path` constants of the
   form `RUNNER = REPO_ROOT / … / "<launcher>.sh"`.
2. Turn the two known cases into an **explicit named allowlist** stating the
   shim requirement, so the exemption is a recorded decision rather than a gap.
3. Add the positive/negative detector pair for the computed-path form.

Expect the file to **grow by 2–4 cases**. It is the one file in this document
that should get bigger.

### P2-0.2 Two opposite Gate LLM-config policies are encoded simultaneously

`docs/gates/gate_testing_standard.md:13-28` records the 2026-08-13 operator
decision moving real-LLM Gates to `openai_tiered_pro.json`; `:436` names
`openai_tiered_v1.json` as superseded; `test_gate_standard_contract.py:244`
enforces it. Meanwhile four tests pin `openai_tiered_v1.json` as **required**
(`test_c14_gate_v19_parity.py:123`, `test_v19_gate0_pair_runner.py:77`,
`test_v19_campaign_pinning.py:65`, `test_v19_queue_runner.py:334`) because the
two V19 launchers still emit it. `launch_v20_campaign.sh:115` uses pro.

Nothing fails, because each guard scopes to a different surface. The suite
currently encodes both policies at once and cannot tell you which is intended.

---

## P2-6. The real-subprocess family — audited by effect, not by token

**Scope as briefed:** 59 files / 1,262 cases / 1,000 functions selected by
`allow_real_subprocess|subprocess\.(run|Popen|check_output)`, minus the 17
files owned by other audits = 42 files / **825 cases / 701 functions**.

### The scoping itself is wrong, and that is the structural finding

`allow_real_subprocess` gates exactly four script names
(`tests/unit/conftest.py:44-49`). The grep selects files that *mention*
`subprocess`, which is neither necessary nor sufficient:

* **222 of the 825 in-scope cases launch nothing at all** —
  `test_sandbox_executor.py` (53), `test_sandbox_rlimit.py` (37),
  `test_validator_agent.py` (71) and six others patch
  `_run_observed_subprocess` and spawn zero children.
* **The two heaviest launch files in `tests/unit/core/` are excluded** because
  they spawn through production helpers: `test_gpu_measurement_runner.py`
  (**41** real children) and `test_probe_hard_timeout.py` (**22**).

Any future scoping must select on **effect**, not on the token `subprocess` —
which is the same lesson `tests/unit/conftest.py:11-15` already records for the
guard itself.

### Semantic classification — the (c)/(d) categories are nearly empty

Thirteen subfamilies were classified. The suspicion categories yielded **two**
instances, not a wave:

**(c) lifecycle timing simulation — one case.**
`test_watchdog.py::TestExecutorKillHandling::test_training_kill_cleans_partials_and_reports`
(`:163-209`) hand-creates the three partial artifacts a killed run leaves
(`:166-173`) and hand-writes `kill_info` (`:175-181`), then asserts the executor
deletes them. *What the partial set actually is* after a real kill is Gate-2
knowledge; if the trainer starts writing a fourth artifact this stays green and
the cleanup silently leaks it. The PR-07c shape at small scale.

*Decomposition:* extract the cleanup list into a named production function; the
unit test asserts it is called once and everything it returns is unlinked, plus
status/deadline propagation. Gate 2 then owns *"after a real watchdog kill no
file matching the trainer's output set survives"* — added as an explicit
assertion line, since Gate 2 is already REQUIRED with the watchdog ON.

**(d) fake Gate-2 replacement — one family, 90 cases.**
`test_bg_validation_harness.py` (78) + `test_bg_gpu_sampler.py` (12). Phase 1
proposed retiring these as *closed-campaign* work; the ownership view reaches
the same place by a different road and refines it. The file's own
`test_neither_script_is_reachable_from_the_launcher` (`:85-93`) asserts the
scripts are not referenced from `run_chain.sh`. But the *shape* is the finding:
~75 deterministic cases reconstruct in-process what a GPU validation campaign
would have concluded, and six of them are **static analysis wearing a pytest
costume** (`"pgrep" not in src` at `:638`, `:644`, `:553`, `:560`, `:651`, `:65`).

*Decomposition:* keep ~15–20 as real seam tests (the `/proc` decoy at `:609`,
`TestConfigPrecondition`'s real hashing/diff logic at `:303-464`,
`TestFixtureApplicability`, the one reachability assertion into production at
`:759-768`, `TestHolderBounds` arithmetic); convert the six source-text
assertions to a single repo lint; retire ~30 shape-pinning cases with the
campaign. `test_bg_gpu_sampler.py` **survives** — its script is still on disk
and driven directly, which corrects Phase 1 §0's open item.

### Correction to Phase 1's launch-count claim

| Phase 1 claim | Verdict | Detail |
|---|---|---|
| `test_gpu_measurement_runner.py` launches `_GOOD_WORKER` 20× uncached | **verified and understated** | **41** launches, zero fixtures. `test_each_required_field_is_present` is 8 identical launches to assert 8 fields of one record (`:561`) |
| `test_admission_join_contract.py` runs the join 14× where 2 would do | **PARTLY FALSE** | the 14 is right, but the file launches **zero** real processes — `_real_refusal` patches both `Popen` and `run` (`:84-85`). In-process CPU redundancy, not launch cost. Phase 1 attributing ~14 launches to it was an error |
| `test_pr07c_validation_pricing.py` runs 5 real trainings for 2 configs | **verified exactly** | class-scoped fixture keyed on `runtime_policy` gives 2. Largest wall-time win in the neighbourhood |

**Revised removable launches: 46** — 25 in-scope + 21 in the two excluded
neighbours. Same magnitude as Phase 1's "~45", differently distributed. The
largest single item Phase 1 missed: `test_campaign_path_resolution.py`, 24 → 9
(eleven launches share one env; `_resolve` is already variadic at `:31`).

```text
in-scope now                    825 cases  701 fn   ~192 launches (180-205)
after fixture scoping only      823 cases  699 fn   ~167 launches   (no coverage change)
after the (d) retirement        ~765       ~645     ~166            (operator decision)
excluded neighbours              +139               68 -> ~45
```

### Three process-group kill suites that must NOT be merged

The most important "looks duplicated, is not" in the repository:

| production implementation | own group | sole unit guard |
|---|---|---|
| `core/sandbox_executor.py:955,978-1003` | `start_new_session=True` | `test_watchdog.py::TestKillTree` |
| `core/runtime_control/probe_subprocess.py:340,353-358` | `start_new_session=True` | `test_probe_hard_timeout.py::TestHardTermination` |
| `core/runtime_control/gpu_measurement_runner.py:283,342-349` | `start_new_session=True` | `test_gpu_measurement_runner.py:277` |

**The duplication is in PRODUCTION, not in the tests.** Merging any two test
suites leaves a production kill path unguarded. Consolidate the three
implementations first, or leave all three suites alone.

This also **corrects a Phase 1 claim**: `TestKillTree` is *not* the only
unit-level real-elapsed-time process-group deadline test. What survives is
narrower and still valuable — it is the only one whose child spawns its own
children, so the only proof `killpg` reaches a **grandchild**.

### A new circular assertion, same class as `:701`

`test_watchdog.py:53` asserts `kill_info["survivors_detected"] is False` — a
value produced by the code under test (`core/sandbox_executor.py:995-1003`).
Delete the probe loop, hardcode `survivors = False`, and the test still passes.
`test_probe_hard_timeout.py:126-130` does it correctly:

```python
pgid = outcome.termination.worker_pgid
with pytest.raises(ProcessLookupError):
    os.killpg(pgid, 0)
```

**Harden, do not delete** — `kill_info` does not expose the pgid, so this needs
one field or a `Popen` spy.

### What the ownership view protects that the redundancy view would have missed

`test_generated_model_transport_chain.py` (6 cases, 6 torch-importing children)
deliberately **contaminates the parent registry** and proves the child still
cannot see it (`:342-369`). `test_registry_population_is_self_healing.py:24-27`
states why it must spawn: *"by the time pytest has collected this file,
something in the session has already imported `models_sandbox`, so every
assertion would pass vacuously."* The defect class — `CONFIG_REJECTED`, V20
attempts 2 and 3, **15 lost formal promotions** — is invisible in-process by
construction. This is the counter-example to the "spawn = Gate impersonation"
reflex.

---

## P2-7. The launcher family — the question is RESOLVED from source

**Scope:** 7 files / 246 cases / 159 functions.

### §18.6 is answered: a stale document, not a contradiction

| fact | evidence |
|---|---|
| `sdsc_submission_scripts/README.md` last touched **2026-08-04** | `git log -1 -- sdsc_submission_scripts/README.md` → `b0f83568` |
| `launch_v20_campaign.sh` **added 2026-08-06**, two days later | `git log --diff-filter=A` → `af9a7193` |
| the README's campaign table therefore cannot mention it | `README.md:75-79` lists only the V19/V18 scripts |

`README.md:77` "current production surface" was **true when written** and was
never updated. Three independent sources name the current surface, none of them
the README: `launch_v20_campaign.sh:3-5` ("OFFICIAL PRODUCTION CAMPAIGN
LAUNCHER … the one repository-controlled entry point"); the V21 design set
treating it as the live producer of production flags
(`pr_d_scientific_authority_reachable.md:94,307,1129`); and
`v20_queue_runner.py:11-13` ("**This is not V19's scheduler.**").

**Verdict.** One chain entry point (`run_chain.sh` + `_chain_common.sh`), five
operator-typed campaign surfaces on top of it, four generations:

```text
V18 / V18r    launch_v18_wave1.sh, v18r_queue_runner.sh   historical (README:79)
V19 campaign  v19_queue_runner.sh          4 waves x 2, band barrier   superseded
C14 Gate      v19_gate0_pair_runner.sh     pair + 90s stagger          superseded
V20 campaign  launch_v20_campaign.sh + v20_queue_runner.py   global FIFO   CURRENT
```

No script invokes any campaign surface; all five are operator-typed.

**And `v19_gate0_pair_runner.sh` is no longer the Gate entry point.**
`docs/gates/gate_testing_standard.md:176-194` gives the canonical Gate-2
command as `bash sdsc_submission_scripts/run_chain.sh` **directly**, with
validation-envelope flags the Gate runner emits none of
(`v19_gate0_pair_runner.sh:92-180`).

### Classification rollup — each case counted once

| class | cases | share |
|---|---:|---:|
| HIST — superseded policy generation | 118 | 48 % |
| SAFE — refusal / must-not-launch, mechanism still current | 62 | 25 % |
| SHAPE — asserts script text, not behaviour | 22 | 9 % |
| COMPAT — deliberate back-compat | 19 | 8 % |
| WIRE — forwarding mechanics | 10 | 4 % |
| CUR — current canonical contract | **9** | **4 %** |
| STALE — pins a superseded value | 6 | 2 % |
| GATE — only a real launch establishes it | 0 | 0 % |

**Only 9 of 246 cases test the current canonical chain contract**, all in
`test_c13_stop_semantics.py`. **Zero cases in this family test
`launch_v20_campaign.sh`** — it is covered, by `test_launch_v20_campaign.py`
(65 cases), which the scope filter excluded.

This is the clearest category-retirement result in the audit: **48 % of the
family tests a policy generation that has been superseded twice.**

### The largest single duplication found anywhere

`test_c14_gate_v19_parity.py` — 40 cases, of which **~34 re-assert
`test_v19_gate0_pair_runner.py` against the same `gate_chain_args` output**:
`test_the_production_settings_are_pinned` (18 params) and
`test_the_bounded_settings` (14 params) are all present in that file's
`FROZEN_VALUES` / `FROZEN_SWITCHES` (`:43-86`); `test_the_gate_is_cold_start`
and `test_the_two_chains_differ_only_in_identity_and_advice` are each dominated
by a strictly stronger sibling. Six cases are unique — the parity *mechanism*,
the DS8 scope pairing, and advice-file content integrity.

### Proposed matrix: one file per PROPERTY, not per launcher generation

| # | file | property | est. cases |
|---|---|---|---:|
| 1 | `test_chain_loop_stop_semantics.py` | the `_chain_common.sh` loop stops on STOP / on a signalled child, never respawns, records why | 9–12 |
| 2 | `test_campaign_admission.py` (trimmed) | a run is bound to its own state dir; unsafe/empty id refused before any `mkdir`; foreign stamp refuses; STOP campaign-scoped | 30–38 |
| 3 | `test_launcher_refusal_contract.py` **(new, parametrized over shipped launchers)** | every launcher refuses an unsafe path component before creating anything; excludes only itself from the live-process scan; is source-safe; every flag it emits is accepted by both `_chain_common.sh` **and** `run_one_iteration.py`'s argparse | 18–26 |
| 4 | `test_gate_command_parity.py` (rebuilt) | the Gate command differs from the **current** launcher only inside a frozen allowlist | 8–12 |
| 5 | `test_v19_campaign_surface_frozen.py` (only if the scripts stay) | one rendered-argv snapshot per historical launcher + the behavioural residue | 18–28 |

```text
now                              7 files   246 cases   159 fn
after, V19 + C14 scripts kept    5 files   83-116      62-85
after, V19 + C14 scripts retired 4 files   56-78       44-63
```

File #3 needs an explicit anti-vacuity case — *"the launcher list is non-empty
and contains every `*.sh` that reaches `run_chain.sh`"* — or a deleted script
silently shrinks the matrix.

### Non-negotiable floor

`test_c13_stop_semantics.py`'s first three classes (9 cases) must not shrink:
the only executable proof an operator stop actually stops the chain, driving
the real loop, naming a production defect (kill the iteration, the loop
respawns iteration 2). Also protected: the live-process self-exclusion guards
(`test_v19_queue_runner.py:404-632` — reproduces a load-dependent SIGPIPE
fail-open deterministically with a 200,000-line stream and asserts **both**
halves), the path-component refusals with their positive controls, the
library-default immunity test (`test_v19_campaign_pinning.py:112-130`, the only
test that sabotages `_chain_common.sh` in a copied tree and proves the rendered
command does not move), and advice-file content integrity.

### Do not merge

The Gate and queue live-process guards are **two separate implementations**:
`v19_queue_runner.sh:507` uses a variable capture because it inherits
`pipefail` from `_chain_common.sh:41`; `v19_gate0_pair_runner.sh:568-570` uses
`grep -qF` in an `if`, which is **correct there** because that script never
sources the library. Merging the tests is fine; assuming the scripts can share
one implementation is not.

---

## P2-5. Governance / milestone — mostly passes, one file does not

**Scope:** 9 files / 145 cases / 98 functions.

### The one-sentence-invariant test

Each family's current invariant, stated without naming a PR, milestone or date:

| family | cases | current invariant | verdict |
|---|---:|---|---|
| `test_no_test_executes_a_launcher.py` | 31 | no file under `tests/` may hand a production launcher path to a process spawner | **passes** |
| `test_gate_standard_contract.py` | 14 | the canonical Gate-2 command stays bounded, real, flag-valid against the live argparse, pinned to the production LLM tier | **passes** — and unusually, it is an executable test over a *document an operator copy-pastes* |
| `test_validation_posture_transport.py` | 16 | every validation-bounding flag is accepted at every hop and none is accepted then dropped | **passes** |
| `test_preflight_production_reachability.py` | 13 | the production pre-flight reaches the isolated worker and never the in-process skill | **passes** |
| `test_runtime_authority_audit.py` | 9 | no runtime consumer turns a projection into a blocking verdict without the shared policy | **passes** |
| `test_no_model_name_dtype_routing.py` | 9 | no model-name literal governs a dtype operation on the migrated surfaces | **passes** |
| `test_no_hardcoded_device_literals.py` | 3 | no device literal in live code; device facts come from `HardwareContext` | **passes** |
| `test_no_model_name_branches.py` | 5 | no architecture-name token in live code on the estimation surface | **passes**, mechanism caveat below |
| `test_gpu_milestone_trace.py` | 45 | an opt-in tracer wired into two production entry points stays inert and never perturbs what it measures | **partially** — ~30 cases test the tracer's own record schema instead |

**Seven of nine pass cleanly.** 145 cases guarding nine distinct repo-wide
properties is ~16 cases per property, and most of that cost is
detector-correctness rather than repetition. **Scope B is not bloated.**

### The 27 detector self-tests — confirmed, and load-bearing

Counted from node IDs: 14 positive + 13 negative = **27 exactly**, plus the
guarantee case and three anti-vacuity cases = 31.

They are load-bearing, and the argument is not "the detector was once wrong".
`_executes_a_launcher` and `_executes_a_dynamic_path` are two hand-written
regex heuristics whose **only** quality signal is these 27 cases. The guarantee
test is green-on-empty: it passes when the corpus is clean *and* when the
detector is broken, and its output cannot distinguish those states — which
P2-0.1 just demonstrated live. The 13 negatives stop the detector being widened
until it never fires; the 14 positives stop it being narrowed until it fires on
nothing.

One exception: `test_it_scanned_a_meaningful_number_of_files` (`:368-369`)
asserts `len(_test_files()) > 100`, strictly weaker than `:252-256` which
asserts the same threshold on files the scan actually **visited** — and does
not call the scan at all. One case of decoration out of 31.

Cost note: the scans do **not** scale in case count (one case over all files,
reasoning at `:205`), but `_scan_every_test_file()` is called three times
uncached, ~0.72 s per pass over 591 files — ~2.2 s per run, and that part *does*
grow linearly. An `lru_cache` removes two thirds.

### §18.5 is answered: the 208 MiB investigation CONCLUDED

`docs/design/v20_priorities/pr_c_measured_evidence_admission.md:3948` —
**"Lifecycle audit of the 208 MiB gap — RESOLVED, cause verified"**; `:4010`
— "the cause is verified". Cause: `load_state_dict(torch.load(...))`
materialises a second parameter set on device; `allocated` returns to 218 MiB
but the caching allocator retains the freed segments as *reserved*, and
driver-visible memory counts reserved. The arithmetic closes with no residual
(`:4030-4037`), across three reproductions.

**But the disposition is conditional, not automatic**, because the tracer is
still wired into production as an opt-in instrument:
`execute_tools/inference_single.py:14,402`,
`core/runtime_control/gpu_measurement_worker_main.py:63,483,573`,
`gpu_measurement_phases.py:263`, switched by
`SIDERIUS_C2_INFERENCE_MILESTONE_TRACE`.

While those hooks ship, *"an opt-in tracer stays inert and never perturbs what
it measures"* is a current, load-bearing invariant. *"The tracer's record schema
enforces ordering and uniqueness"* is Pydantic-declared, and is what most of the
45 cases assert.

```text
keep  inertness + no production module sets the variable (:108-199)      6
keep  no perturbation of the measured path (:600-740)                    6
keep  milestone-7 placement inside the PRODUCTION files (:510-599)       8
keep  one definition of driver-visible memory (:397-460)               2-3
trim  the tracer's own record schema / ordering / uniqueness           ~20 -> 3-4
                                                                      -------
                                                                      45 -> 16-22
```

The file goes to zero the day the hooks come out — but not before. Also worth
noting: `gpu_milestone_trace.py:6-14` still presents the question as open, which
the design doc's own conclusion contradicts.

### `_PENDING_CLEANUP` — sound, with two residual holes

`test_no_model_name_branches.py:85` is `{}`, deliberately emptied, with the
reasoning at `:66-84` and a mutation proof at `:76-77` ("3 passed, 1 xfailed"
with the entry present, hard failure without). The intent is right and the
guardrail-on-the-guardrail (`:83-84`, name the CURRENT owning PR) is right.

Two holes:
1. **A re-added entry can never announce it is stale.** `:241-244` uses
   imperative `pytest.xfail`, non-strict. If a label sits in the dict and the
   file comes clean, the branch is not taken and nothing reports it — exactly
   how the previous three entries rotted.
2. **A vanished target passes vacuously.** `_iter_target_files` (`:211-216`)
   yields nothing when the path is missing, so renaming
   `core/inference_defaults.py` turns its case green rather than red. All five
   targets exist today, so the hole is latent — and
   `test_no_model_name_dtype_routing.py:240,247` already solves it. Borrow both.

### Scope B rollup

```text
now       9 files  145 cases   98 fn
proposed  9 files  114-128     84-101      (-12% to -21%)
```

Essentially all movement is `test_gpu_milestone_trace.py` (−23 to −29), partly
offset by `test_no_test_executes_a_launcher.py` **growing** by 2–4 (P2-0.1) and
the two guardrails gaining anti-vacuity cases.


---

## P2-4. The StepNN ladder — the answer is the opposite of the hypothesis

**Scope re-derived at `52bd98ba`: 103 files / 1,285 cases / ~937 functions**
(the 102/1,283/935 figures predate the 07c merge).

### The ladder is not archaeology. It is actively pruned, and it leaves receipts.

The hypothesis was that each Step kept its own regression ladder after the
final public contract superseded the intermediate representations. **Five
independent mechanisms in the files themselves disprove it**, each verified
directly:

1. **Two inertness assertions were deleted and INVERTED, with tombstones.**
   `test_step05c_c1_deliverable_spec.py:294-306` (verified verbatim):

   > *"C1's inertness assertion — 'zero production importers' — lived here and
   > did its job: it went red the moment C2 wired the first production
   > consumer, which is exactly when it should. It was not deleted but
   > INVERTED, into …`test_only_the_censused_sites_consume_the_deliverable_spec`"*

   Both replacements exist and run — `test_step05c_c2_reader_migration.py:320`
   and `test_step06_c2_live_route.py:196`, confirmed present. This is precisely
   the class-4 pattern (a shape that existed only between two steps) being
   **retired on purpose**.
2. **A rung was deleted when a guardrail subsumed it** —
   `test_step03_m5_input_dtype_resolution.py:209-215`: *"…was REMOVED, not lost
   … now subsumed by `tests/unit/guardrails/test_no_model_name_dtype_routing.py`
   … One claim, one owner."*
3. **A Checkpoint-0 capture was REWRITTEN when its migration completed** —
   `test_step00_task_config_baselines.py:82-106`: *"CFG-3a, REWRITTEN at Step
   04b — the duplicate is gone … the old assertion would have *required* the
   duplicate to exist."*
4. **Step-00 goldens carry Step-06/07a/07b edits inline** — living contracts,
   not snapshots (`test_step00_prompt_goldens.py:115-156`, `:160-180`,
   `:265-297`, `:343-361`; `test_step06_planner_boundary.py:26-30` is labelled
   "UPGRADED at Step 07a C3", again at 07b).
5. **A step's scope list was edited when the next step took the surface** —
   `test_step05c_c7_stage_b_rung.py:62-71`.

### Verified retirements: 13 cases, in four narrow patterns

Each proven against production, not assumed:

| pattern | cases | proof the mechanism is gone |
|---|---:|---|
| step00 CFG-3a duplicate-declaration guard | 2 | `test_step04b_task_description_single_source.py:185-194` parses **every** `configs/**/*.yaml` and asserts the declaring set is exactly `{task_config.yaml}` — strictly implies both step00 assertions **and** covers a third file appearing, which step00's lit-review-only check cannot see |
| two whole-index-space filename loops | 2 | The divergent inline constructions (`f"{i:04d}"` vs `str(i).zfill(4)`) are **gone**: `grep -rn zfill execute_tools/ core/ nodes/` returns exactly three hits — `deliverable_spec.py:149` (the *declared* `index_width` authority), and two comments (`dataset_config.py:135`, `inference_single.py:908`, the tombstone). Verified directly |
| selection-determinism sentinel | 1 | The re-export collapse is complete; `test_step02b_b2_explicit_profile_selection.py:133-147` reads the builder source and forbids the three topology constants — strictly stronger |
| step03 A8 `test_the_workspace_boundary_is_declared_not_assumed` | 1 | Body is `assert isinstance(_on_disk_plugin_files(), list)` against a test-local helper returning a list literal (verified) — passes for any content of `agent_generated/models/` |
| step07a+07b STATUS/README prose pins **consolidated** to one | −6 | Seven cases across two files pin prose naming their own PR id; all seven must be rewritten together at D14. Collapse into one maturity-claim test that cross-checks the row against the executable capability |
| **verified total** | **−12** | |

Plus, from Phase 1's different axis: step03 A6 `:314-325` (6 self-referential
cases — the tables are test-local, confirmed) and one strictly-weaker
diagnostic. **−19 in total.**

### The ladder under the stated policy

```text
                    before        after (point)       range
cases                1,285            1,265        1,245 - 1,272
functions             ~937             ~918          ~902 -   925
files                  103              103                  103
```

**−1.6 % (range −1.0 % to −3.1 %). No whole file in this ladder is
retirable.** I am not going to manufacture a larger number; the ladder does not
contain one.

### The ladder's real cost is not case count

Three maintained step-relative artefacts, each needing an edit per future step:

1. **The two authority censuses** (`test_step05c_c2_reader_migration.py:300-353`,
   `test_step06_c2_live_route.py:172-214`). Each holds hardcoded
   `MIGRATED_CONSUMERS` / `FORBIDDEN_CONSUMERS`. The Step-06 forbidden list
   (`:186-193`) enumerates four files that are *scheduled to acquire* the
   interface when the D1 debt closes — at which point the test becomes **a
   blocker on the migration it was written to protect**. Not a defect today;
   a liability with a named expiry. Re-express as a derived claim: permanent
   ("the frozen arithmetic never imports the handle") vs not-permanent ("the
   dashboard does not yet").
2. **The out-of-rung literal list** (`test_step05c_c7_stage_b_rung.py:146-156`).
   Actively maintained, live in function — an operator call, not a proven
   cleanup.
3. **The per-PR STATUS.md prose pins** — 07a's and 07b's coexist; each new PR
   adds another naming its own id.

Plus a navigation defect: **the 07b C7 decomposition cut the tuner from 7,430
to 1,490 lines, and five scope files still cite tuner line numbers that no
longer exist** (`test_step00_record_baselines.py:4440,4448`,
`test_step00_dataset_baselines.py:4362`,
`test_step02b_checkpoint_c_live_integration.py:3806`,
`test_step05c_c0_launch_cleanup_baseline.py:5548`,
`test_step06_c0_two_route_oracle.py:5321`). Two docstrings now contradict their
own bodies (`test_step05c_c1_deliverable_spec.py:1-8` and
`test_step06_c1_evaluation_metric.py:9-12` both still say "inert", after C2
removed the assertion). The docstrings are this ladder's navigation system;
these are misdirections.

**Consolidating those three artefacts is worth more than deleting twenty
cases.**

### Specifically checked because the operator asked

| candidate | verdict |
|---|---|
| **Checkpoint-0 numeric baselines** | **Not dominated.** NUM-2/3/4/5/8 route through *production* helpers, so rewriting production aggregation reddens them. NUM-6 is labelled a mechanism replay, *explicitly not numeric parity* (`:13-20`), and `test_step06_c0_two_route_oracle.py:26-31` documents that NUM-6's monkeypatch **cannot reach the subprocess route** — which is why C0 exists beside it. Complementary, not stacked |
| **step03 A2 loss matrix** | **Keep.** Authority live (`models_format_sandbox.py:556` → `:516`, consumed at `core/sandbox_executor.py:1188`); still the only complete 3×5 oracle; `hybrid` remains an unconditional early return |
| **step03 A6 dtype baseline** | **Keep in full.** The F-1 divergence is encoded in production *today* as `model_input_dtype.py:69` (`TRAINING_SITE_DTYPE = "int32"`) and `:74` (`INFERENCE_SITE_DTYPE = "int64"`), and production names A6 as its evidence (`:53-59`, `models_format_sandbox.py:394-397`). M5 is **not** a superset — it pins *how* the dtype is chosen; only A6 observes what a real model's `forward` receives. The operator decision it informs is still open |
| **step07a / 07b / 07c rungs** | **Retire nothing.** 07c's persistence-timing test is a dated regression for the escape 9,967 green cases missed. `test_pr07c_b1_measurement_axis.py:111-196` carries axis *and* stability in one test with both a reproducibility and a negative control. **07b C2 and C3 must stay separate** — C3's docstring states a scale error passes every ordering assertion; merging recreates the blind spot. The step07 identity correction is class-7 with a **live** mechanism (`memory.time_mode`'s population deliberately unchanged) |

### Honest coverage bound

Bodies read in full for 55 of 103 files, in part for 11, **docstring only for
39**. Per the no-heuristic-classification rule, the 39 are reported as
*unverified at body level*, not classified — which is why the range above
widens to −3.1 % rather than being stated as a point.

---

## P2-10. Projection A vs Projection B

### Projection A — redundancy only (Phase 1)

What the redundancy audit alone supports.

```text
                          cases      functions      files
current                   9,980          8,284        534
Wave 1  mechanical         -336           ~-250       ~-2
Wave 2  superseded         -249            -190       -3
Wave 3  Gate-2 hygiene        0               0        0     (~45 fewer launches)
Wave 4  Gate-1 reassign      -10             -10        0
Wave 5  additions            +10             +10        0
                          -------      ---------    -----
PROJECTION A             ~9,395         ~7,844       ~529
                          (-5.9%)        (-5.3%)
  + unread-family extrapolation   -600..-1,000
realistic A            8,400-8,800    7,000-7,400
```

### Projection B — architecture retirement

Adds the category retirements, each sized from source in P2-4…P2-7.

| Source | cases | functions | files | confidence |
|---|---:|---:|---:|---|
| Projection A, evidence-backed core | −585 | −440 | −5 | HIGH |
| **Launcher family** (246 → 56–116) | −130 … −190 | −74 … −115 | −2 … −3 | **HIGH** — the generation question is resolved from source |
| **Governance** (145 → 114–128) | −17 … −31 | −0 … −14 | 0 | HIGH |
| **Real-subprocess** (825 → ~765) | −50 … −70 | −45 … −60 | 0 | MEDIUM — needs the operator call on the B-G family |
| **StepNN ladder** (1,285 → 1,245–1,272) | −13 … −40 | −12 … −35 | 0 | HIGH, and small |
| Unread-family extrapolation | −600 … −1,000 | −500 … −850 | −5 … −15 | LOW — not yet earned |
| **PROJECTION B total** | **−1,395 … −1,916** | **−1,071 … −1,514** | **−12 … −23** | |

```text
                          cases        functions        files
current                   9,980            8,284          534
PROJECTION B           8,064-8,585      6,770-7,213    511-522
                        (-14% .. -19%)   (-13% .. -18%)
```

### The honest conclusion

**Projection B is not much below Projection A, and neither reaches 5,500–6,500.**

The reason is now established rather than assumed: **the four categories that
looked like the gap are, on inspection, mostly current architecture.**

| category | expected | found |
|---|---|---|
| StepNN ladder (1,285) | archaeology preserved forever | **actively pruned, with tombstones** — −1.6 % |
| Governance (145) | milestone archaeology | 7 of 9 families pass the one-sentence-invariant test; the largest file should **grow** |
| Real-subprocess (1,262) | elaborate fake Gates | 2 instances found, not a wave; 222 in-scope cases launch nothing; the heaviest launchers were excluded by the scoping |
| Launcher family (246) | historical generations | **confirmed — 48 % is superseded policy.** The one category where the hypothesis held |

**Only one of four hypotheses survived contact with the source.** That is the
Phase-2 result, and it is worth more than a bigger number would have been.

Reaching ~6,000 would require deleting from the backbone or from the four
additive layers — i.e. **choosing which coverage to stop having**. This document
will not present that as a redundancy finding, and P2-11 asks it directly.

### What the suite would look like if the answer is "8,000 is right"

```text
backbone                            ~2,130 cases  ~1,630 functions   ~96 files
+ compatibility oracles                ~450          ~360
+ negative / fail-closed matrix        ~1,900        ~1,600
+ genericity contrasts / rungs         ~700          ~560
+ selected regressions (live mech.)    ~1,400        ~1,150
+ operator-surface & argv contracts    ~900          ~700
+ everything not yet classified        ~600          ~470
                                    ------------  ---------------
                                     ~8,080 cases  ~6,470 functions
```

The layer sizes are apportioned from the audited families and carry the same
uncertainty as Projection B. The point is not the arithmetic — it is that a
suite of ~8,000 **can** be described as six named layers rather than as
accumulated sediment, which is what "healthy architecture" would mean here.


---

## P2-11. The seven operator questions — reproduced VERBATIM, with rulings requested

Format per operator instruction: source evidence · options · recommendation ·
consequence on case/function/file count · semantic risk.

Two are now **answered from source** and need only confirmation. Five remain
genuine policy choices.

---

### Q1 — verbatim

> **1. The target number.** ~8,400–8,800 is what redundancy-removal honestly
> yields. 5,500–6,500 requires deleting coverage. Which is the goal? If the
> latter, §14 lists the four categories that would have to go, each with its
> cost — the choice is which coverage to stop having.

**Source evidence.** Cases ÷ functions = **1.20** (P2-1): parametrisation
contributes 1,696 cases suite-wide, so cell compression cannot remove a single
maintained claim. Backbone derives at **~2,130 cases / ~1,630 functions**
(P2-3), inside the 1,500–2,500 band without being aimed at it. Projection B
reaches **8,064–8,585 cases / 6,770–7,213 functions** (P2-10).

**Options.** (a) Adopt Projection B and declare ~8,000 the intended
architecture, described as six named layers. (b) Set the target on **functions
and files**, let cases fall out, and accept whatever case number results.
(c) Force ~6,000 by deleting from the additive layers, naming which coverage
stops existing.

**Recommendation: (b).** The maintenance unit is the claim, not the cell. A
target of "functions 8,284 → ~6,500 and files 534 → ~500" is measurable,
matches the stated cost model, and is achievable by Projection B without
touching the backbone. Quoting a case target invites exactly the parametrisation
compression that would change nothing.

**Consequence.** (a)/(b) → cases 8,064–8,585, functions 6,770–7,213, files
511–522. (c) → roughly 2,000 further cases from named layers.

**Semantic risk.** (b) is low. (c) is high and unquantified — the layers are
fail-closed matrices, genericity contrasts and live-mechanism regressions.

---

### Q2 — verbatim

> **2. The closed-campaign harnesses (§10.2, 220 cases).** Retire
> `scripts/c2_prephase_validation.py` and `scripts/bg_admission_validation.py`
> with their tests, after re-homing the reachability oracle in
> `test_environment_stability.py` and `test_formal_stability_controller.py`?
> Or keep both script and tests?

**Source evidence.** PR B merged 2026-08-02, PR C2 merged 2026-08-04;
`core/inference_defaults.py:26` calls both "legacy validation scripts"
(verified verbatim). `test_bg_validation_harness.py:85-93` itself asserts the
scripts are unreachable from `run_chain.sh`. **The coupling is real**:
`test_environment_stability.py:33` and `test_formal_stability_controller.py:32`
both `ast.parse()` `c2_prephase_validation.py` as their reachability oracle,
five sites — deleting the script breaks 77 must-keep cases. Phase 2 refines the
scope: `scripts/bg_gpu_sampler.sh` is a **documented operator contract**
(PR-E D-E-8) and its 12-case test survives; ~6 of the harness cases are static
analysis in a pytest costume and belong in lint.

**Options.** (a) Retire both scripts + tests after re-homing, keeping ~31 cases
and `test_bg_gpu_sampler.py`. (b) Keep everything. (c) Retire
`bg_admission_validation.py` only (no coupling), defer C2.

**Recommendation: (a).** This is the one category where "the campaign is
closed" is *documented in production*, not inferred. Do the re-homing in the
same commit; a 1,647-line untested script left in `scripts/` is worse than
either endpoint.

**Consequence.** −190 to −220 cases, −150 to −180 functions, −3 files. (c) is
−78 cases and leaves the larger half.

**Semantic risk.** Medium, concentrated entirely in the re-homing. If the
reachability oracle is not correctly re-pointed at a live caller, two
high-value files lose their reachability half silently.

---

### Q3 — verbatim

> **3. The `stepNN` capture-first ladder (204 files, 937 functions).** Retire
> aggressively once a later authority exists, or keep as historical
> regressions? The audit found **no** internal supersession, so this is purely
> a policy call.

**Source evidence — this question is now answered differently than it was
asked.** P2-4 audited the ladder for *ownership*, not duplication, and found
**five documented mechanisms of active retirement**, including two tombstones
where inertness assertions were deleted and inverted into named replacements
that exist and run. Verified archaeology: **13 cases (~1 %)**. The four
retirement patterns are each proven against production (the `zfill` divergence
is gone — three grep hits, all authority or comment).

**Options.** (a) Accept the ladder as current architecture; retire the 13
verified cases; consolidate the three maintained step-relative artefacts.
(b) Retire aggressively anyway on the "one step, one authority" principle.
(c) Keep everything unchanged.

**Recommendation: (a).** "Retire aggressively" would delete tests whose
production authorities are live and whose open decisions (F-1 dtype, the A2
`hybrid` early return) are unresolved. The ladder is not the problem it was
suspected of being.

**Consequence.** (a) −13 to −40 cases, **0 files**. (b) would reach ~−900
cases and is not supported by any evidence found.

**Semantic risk.** (a) low. (b) very high: A6 is the standing oracle for a
live open decision, and production *names it* as its evidence base
(`model_input_dtype.py:53-59`).

**Attached sub-ruling requested** — the three maintained artefacts (the two
authority censuses, the out-of-rung list, the per-PR STATUS prose pins) each
need an edit per future step, and the Step-06 census will become **a blocker on
the D1 migration it was written to protect**. Authorise re-expressing them as
derived claims?

---

### Q4 — verbatim

> **4. Guardrail policy.** Keep repo-wide scanning guardrails (they are cheap
> and catch architectural erosion nothing else does) even though they inflate
> the count?

**Source evidence.** They do not inflate the count: 100 cases over 8 files,
one case over all files by design (`:205`), 145 including the tracer — 1.5 % of
the suite for nine distinct repo-wide properties. Seven of nine pass the
one-sentence-invariant test cleanly. **And P2-0.1 demonstrated live why the 27
detector self-tests are load-bearing**: the guarantee test is green-on-empty
and cannot distinguish "corpus clean" from "detector broken" — which is exactly
the state the repository is in right now.

**Options.** (a) Keep, and **grow** the launcher guard by 2–4 cases to close
the computed-path blind spot. (b) Keep as-is. (c) Trim the detector self-tests.

**Recommendation: (a).** (c) would recreate the 2026-08-02 finding verbatim.

**Consequence.** +2 to +4 cases. Runtime: `lru_cache` on
`_scan_every_test_file` removes two of three full-corpus AST passes (~1.4 s).

**Semantic risk.** (c) is high and specifically demonstrated. (a) is the only
option that closes a live gap.

---

### Q5 — verbatim

> **5. `core/test_gpu_milestone_trace.py` (45 cases, 740 lines).** Has the
> 208 MiB under-read investigation concluded? If yes, this is the largest
> single block whose *purpose* may have expired. No evidence either way was
> found in source.

**ANSWERED — it concluded.** `docs/design/v20_priorities/pr_c_measured_evidence_admission.md:3948`
is headed **"Lifecycle audit of the 208 MiB gap — RESOLVED, cause verified"**;
`:4010` states "the cause is verified" (both verified verbatim). Cause:
`load_state_dict(torch.load(...))` materialises a second parameter set on
device; `allocated` returns to 218 MiB but the caching allocator keeps the freed
segments *reserved*, and driver-visible memory counts reserved. Arithmetic
closes with no residual (`:4030-4037`) across three reproductions.

**But the block's purpose has NOT expired**, because the tracer is still wired
into production as an opt-in instrument: `execute_tools/inference_single.py:14,402`,
`core/runtime_control/gpu_measurement_worker_main.py:63,483,573`,
`gpu_measurement_phases.py:263`.

**Options.** (a) Keep the hooks; retain 16–22 cases (inertness, non-perturbation,
milestone-7 placement, one-memory-policy), retire the ~20 record-schema
restatements Pydantic already declares, and fix the stale module docstring.
(b) Remove the hooks from production; all 45 cases go with them.
(c) Keep all 45.

**Recommendation: (a)**, unless you want the hooks out — which is a production
question, not a test question. While they ship, "an opt-in tracer stays inert
and never perturbs what it measures" is current and load-bearing.

**Consequence.** (a) −23 to −29 cases. (b) −45 cases plus a production change.

**Semantic risk.** (a) low. Note `gpu_milestone_trace.py:6-14` still presents
the question as open, contradicting the design doc's own conclusion — worth
fixing either way.

---

### Q6 — verbatim

> **6. `v19_queue_runner.sh` — retired or not?** `sdsc_submission_scripts/README.md:77`
> labels it *"current production surface"*; `v20_queue_runner.py:37` sets
> `LAUNCHER = launch_v20_campaign.sh`. **These are not necessarily in
> conflict** — they may be two co-existing campaign surfaces. But 169 cases
> … and the `c14` Gate-parity *reference* both hang on the answer. No deletion
> is proposed on evidence this ambiguous.

**ANSWERED — a stale document, not a conflict.** Verified by git:
`sdsc_submission_scripts/README.md` last touched **2026-08-04** (`b0f83568`);
`launch_v20_campaign.sh` **added 2026-08-06** (`af9a7193`), two days later. The
README's table cannot mention a file that did not exist. Three independent
sources name the current surface, none of them the README:
`launch_v20_campaign.sh:3-5` ("OFFICIAL PRODUCTION CAMPAIGN LAUNCHER … the one
repository-controlled entry point"), the V21 design set treating it as the live
producer of production flags, and `v20_queue_runner.py:11-13` ("**This is not
V19's scheduler.**").

**Also settled:** `v19_gate0_pair_runner.sh` is **not** the current Gate entry
point — `docs/gates/gate_testing_standard.md:176-194` runs `run_chain.sh`
directly with validation-envelope flags the Gate runner emits none of.

**The remaining question is genuinely yours**: the two V19 scripts are shipped
operator surfaces. Only the operator retires an operator surface.

**Options.** (a) Retire both scripts; ~120 cases follow and the family is
rebuilt around the current contract (246 → 56–78). (b) Keep them, mark them
"historical" in the README the way `v18r_queue_runner.sh` already is; the same
~120 cases collapse into one frozen-snapshot file (246 → 83–116). (c) Keep
everything and fix only the README.

**Recommendation: (b).** It preserves the operator's ability to re-run a V19
campaign while making the generation explicit, and it is reversible. Note the
family currently has **only 9 of 246 cases testing the current canonical chain
contract**, and **zero** testing `launch_v20_campaign.sh`.

**Consequence.** (a) −168 to −190 cases, −96 to −115 functions, −3 files.
(b) −130 to −163 cases, −74 to −97 functions, −2 files.

**Semantic risk.** Medium, and specific: the merge must not lose a refusal
case. The three process-group kill suites and the two live-process guards are
**separate production implementations** — merging the tests is fine, assuming
the scripts can share one implementation is not.

**Two sub-rulings attached.** (i) `openai_tiered_v1.json` is superseded for
real-LLM Gates yet pinned as required by four tests because the V19 launchers
emit it — **the suite encodes two opposite Gate-config policies at once**
(P2-0.2). (ii) `v20_queue_runner.py:220` sets a **shared collection-root
STOP** — the exact shape of the 08:17 incident that PR E removed from the V19
runner. Intentional (one orchestrator per root) or a reintroduction? No test
covers it either way.

---

### Q7 — verbatim

> **7. Wave 5 scope.** All six additions, or only §12.1 (FocalLoss1D) and
> §12.3 (the real-sidecar join) — the two whose absence has already produced,
> or nearly produced, a real escape?

**Source evidence.** You have already ruled §12.1 and §12.2 in, one strong
oracle each; both are designed and numerically verified in P2-9 (FocalLoss:
three hand-computed expectations matching the implementation to 1e-9;
`alpha=0.25` shows as an exact 2× difference). Remaining: §12.3 the
real-sidecar → real-provider join (~4 lines inside an existing fixture),
§12.4 the manifest key-set contract, §12.6's two guardrails.

**Options.** (a) Add all remaining. (b) Add §12.3 only. (c) Add §12.3 and the
self-referential-default guardrail — P2-6 found a **third** instance of that
pattern (`test_watchdog.py:53` asserts `survivors_detected`, a value produced
by the code under test), after Phase 1 found the first two.

**Recommendation: (c).** Three independent instances of one anti-pattern in one
audit is the case for a cheap mechanical guard. §12.4 is real but unowned by
any current incident; defer it.

**Consequence.** (c) +6 to +8 cases. (a) +10 to +12.

**Semantic risk.** Additions only; the risk is opportunity cost.

---

### Two items requiring a ruling that were NOT among the seven

**R1 — the launcher guardrail blind spot (P2-0.1).** Two test files execute a
production launcher via `["bash", str(RUNNER), *args]`, and the guardrail
written to prevent exactly that reports the repository **clean** — verified by
running its own detector. The only barrier is a PATH `screen` shim. This is a
production-safety defect, outside the autonomous tier, and it is the one place
in this document where the recommendation is to make a file **bigger**.

**R2 — `test_watchdog.py:53` circular assertion.** Asserts a value produced by
the code under test. `test_probe_hard_timeout.py:126-130` shows the correct
form (`os.killpg(pgid, 0)` → `ProcessLookupError`). Harden, do not delete —
`kill_info` does not expose the pgid, so it needs one field or a `Popen` spy.

---

## P2-12. Stop condition

**No pruning implemented. No test added, deleted, consolidated or modified.**

Report format per operator instruction:

| | cases | functions | files |
|---|---:|---:|---:|
| **1. current** | **9,980** | **8,284** | **534** |
| **2. redundancy-only projection** | 8,400–8,800 | 7,000–7,400 | ~529 |
| **3. architecture-retirement projection** | **8,064–8,585** | **6,770–7,213** | **511–522** |
| **4. proposed backbone** | **~2,130** | **~1,630** | **~96** |

**5. Largest category retirements.** Launcher family 246 → 56–116 (48 % is
superseded policy, the only hypothesis that held); closed-campaign harnesses
−190 to −220; milestone tracer 45 → 16–22; real-subprocess family ~825 → ~765.

**6. Highest-risk boundaries.** Retained: the three refusal lanes; the three
*separate* process-group kill implementations; A6 as the standing oracle for an
open decision; the 27 detector self-tests. Deleted: the C2 harness re-homing
(Q2), and any launcher merge that drops a refusal case (Q6).

**7. Redesign, do not delete.** `test_pr07c_validation_pricing.py:309` and
`:701`; `test_watchdog.py:53`. All three assert something necessarily true or
self-produced in place of the property their prose claims.

**8. Add.** FocalLoss1D numeric oracle (3 cases, expectations verified);
producer→consumer non-finite serialization (1); real-sidecar → real-provider
join (1); a self-referential-default guardrail (3 instances now found).

**9. The seven questions** are reproduced verbatim in P2-11 with the five-field
format. Q5 and Q6 are answered from source and need confirmation only; Q1, Q2,
Q3, Q4, Q7 are live policy choices; R1 and R2 are new and outside the seven.

**No test will be modified until those rulings are complete.**

---
---

# OPERATOR RULINGS — FROZEN FOR IMPLEMENTATION

**Issued 2026-08-17 in one batch, after the Phase-1 redundancy audit and the
Phase-2 ownership audit. These rulings are BINDING on the pruning
implementation and are not to be reinterpreted mid-wave.**

Implementation branch: `test-architecture-suite-pruning`, off `master` at
`9f289d54` (the guardrail safety fix, PR #220, merged first as a prerequisite).

## The governing reframe

> The success criterion for this cleanup is **not** "10k → 6k". It is:
> **remove invalid ownership, reduce maintained claims, and establish an
> architecture that will not inflate back.**

The question "did we cut hard enough" has been converted from a number into a
test-ownership question. That conversion is the long-term rule this work should
leave behind.

## Acceptance metrics — reordered

```text
PRIMARY
    distinct maintained test functions
    distinct test files
    semantic ownership

SECONDARY
    collected cases
    wall time
```

Rationale, from P2-1: cases ÷ functions = 1.20, so parametrisation contributes
only 1,696 cases suite-wide and compressing cells cannot reduce maintained
claims. The backbone independently derives to ~2,130 cases / ~1,630 functions.

### Accepted target band (evidence-supported, Projection B)

```text
cases        ~8,064 - 8,585
functions    ~6,770 - 7,213
files          ~511 -   522
```

### Stretch

```text
functions   aim <= ~7,000; stretch toward ~6,500 ONLY if NEW source-grounded
            retirement appears
files       aim ~510; stretch toward ~500, but never delete a meaningful file
            to move a count
```

### Hard prohibition

**It is forbidden to reach a case target by deleting fail-closed matrices,
genericity contrasts, or live-mechanism regressions.**

Two failure modes are equally prohibited, and the implementation is expected to
avoid both:

* stopping early because ~8k is permitted — every approved retirement must be
  taken to its reasonable limit;
* mining a further ~2,000 tests out of the backbone or out of independent
  failure classes to make a number look better.

---

## Q1 — Target number → **(b)**

Set the target on **functions, files and ownership**; let cases fall out. No
hard 6,000-case goal. Band and stretch as above.

## Q2 — Closed-campaign harnesses → **(a)**

Retire `scripts/c2_prephase_validation.py` and `scripts/bg_admission_validation.py`
**and their own tests** — but the reachability-oracle re-homing must complete
**in the same commit**, in this order:

```text
1. establish the new authoritative reachability oracle
2. prove the 77 retained tests exercise THAT oracle
3. mutation / negative evidence: breaking reachability makes them RED
4. only then delete the legacy harness + obsolete tests
```

**Explicitly prohibited:**

```text
delete old oracle
  -> rewrite retained tests into something conveniently green
```

Expected −190 to −220 cases. `test_bg_gpu_sampler.py` survives (its script is a
documented operator contract, PR-E D-E-8).

## Q3 — StepNN ladder → **(a)**

Retain current-contract and live-mechanism StepNN tests. Retire **only** the
source-proven superseded tombstones. Expected −13 to −40 cases, 0 files. Do not
force a larger number: Phase 2 found the ladder is ~98 % current architecture,
and several live production authorities name these tests as their evidence base.

### Q3 sub-ruling — the three maintained artefacts

Convert to **derived claims where valid**, subject to a hard constraint:

```text
the authority being checked   !=   the source used to generate the expectation
```

A derived claim must never degrade into self-reference:

```python
expected = current_registry()
assert current_registry() == expected      # PROHIBITED
```

Specifically for the **Step-06 census**: a historical hand-written census must
not become a blocker when D1 correctly *adds* capability. If it can be derived
from an independent authoritative manifest or public contract, make it a derived
invariant. **If no independent authority exists, keep a small explicit
hand-written oracle rather than manufacture a tautology.**

## Q4 — Guardrail policy → **(a)**

Keep the repo-wide guardrails **and** the detector self-tests; strengthen them.
R1 demonstrated live that "corpus clean" and "detector blind" both turn the
aggregate guarantee green, which is exactly what makes the detector self-tests
load-bearing. PR #220 addressed the defect.

Also approved: `lru_cache` on `_scan_every_test_file`, **provided** it only
avoids repeated scanning within one pytest process and does not change detection
semantics.

## Q5 — GPU milestone tracer → **(a)**

The 208 MiB investigation is RESOLVED, but the tracer still has production
consumers, so the hooks stay. 45 → **~16–22** cases.

```text
KEEP     hook correctness
         lifecycle / placement
         the one memory-policy semantic
         important producer/consumer behaviour
DELETE   ~20 schema restatements
         investigation-era redundancy
```

Also fix the stale module docstring (`gpu_milestone_trace.py:6-14`), which still
presents the investigation as open.

## Q6 — V19 launcher family → **(b)**

Do **not** delete the V19 operator surfaces. But they may no longer be described
as the current production surface:

```text
V19 launchers = historical / legacy operator surfaces
              = retained for reversibility and forensic compatibility
             != the current canonical launcher
```

Consolidate the family **246 → ~83–116**, into an explicit frozen historical
snapshot family. The current canonical contract gets its own small matrix. This
follows the source finding: only 9 of 246 cases test the current canonical
contract, and **zero** test `launch_v20_campaign.sh`.

### Q6(i) — `openai_tiered_v1.json`

Its status as a repo-wide / current Gate requirement is **revoked**.

```text
historical V19 snapshot   MAY pin openai_tiered_v1 — that is what V19 emitted
current Gate / launcher   MUST derive its configuration from the CURRENT
                          canonical authority
```

Four V19 tests must stop passing a historical model-routing policy off as
today's Gate policy. **Do not hardcode a new value by judgement** — take the
current expected config from the current Gate standard / current canonical
launcher authority.

### Q6(ii) — `v20_queue_runner.py:220` shared collection root

**Not to be assumed right or wrong inside the pruning PR.** Run a narrow
production-safety audit and source-prove whether the V20 shared collection root
is intentional.

```text
If it is the same unsafe shared-root mechanism as the PR-E incident:
    -> a SEPARATE narrow safety-fix PR
    -> merged BEFORE the Q6 consolidation completes

If V20 shares it intentionally under a distinct isolation contract:
    -> document that authority
    -> add ONE focused current-contract regression
```

This question **blocks only the final Q6 consolidation**. It does not block any
other wave, and it is not a reason to retain the whole 246-case family.

## Q7 — Wave 5 additions → **(c)**

Approved, minimal:

1. `FocalLoss1D` hand-computed numerical oracle
2. producer → serialization → consumer non-finite boundary oracle
3. real-sidecar → real-provider join
4. one general **self-referential-expectation guardrail**

Item 4 is justified by three instances of one failure class already found:
`test_pr07c_validation_pricing.py:309`, `:701`, and `test_watchdog.py:53`.

**§12.4 (manifest key-set contract) is NOT approved** — no current incident, no
clear owner. Do not build speculative coverage in the same PR that deletes
tests.

Net addition must stay small: **~+6 to +8 cases.**

---

## Ruling summary

| Question | Ruling |
|---|---|
| Q1 target | **(b)** functions / files / ownership first; no forced 6k cases |
| Q2 closed harnesses | **(a)** retire after same-commit oracle re-homing |
| Q3 StepNN | **(a)** retain live authorities; retire proven tombstones only |
| Q3 sub | manual future-step artefacts → independent derived claims where valid, never tautologies |
| Q4 guardrails | **(a)** keep and strengthen |
| Q5 tracer | **(a)** keep hooks; 45 → ~16–22 |
| Q6 V19 | **(b)** retain surfaces as historical; consolidate tests aggressively |
| Q6(i) config | historical v1 only; current policy from the current authority |
| Q6(ii) V20 root | narrow safety audit; separate fix PR if the same incident class |
| Q7 additions | **(c)** minimal high-value additions |

## Implementation protocol (frozen)

```text
 1. commit this document with the rulings                     [this commit]
 2. open a DRAFT PR; all pruning lives in it
 3. record the baseline: cases / functions / files / wall time
 4. one wave = one commit
 5. re-record the four numbers after every commit
 6. do NOT stop at each wave for approval
 7. if Q6(ii) exposes a real V20 defect -> fork a separate safety PR
 8. rebase this branch after any such safety PR merges
 9. full suite + ruff + pyright ONCE, at the final executable head
10. Draft -> Ready for Operator Review
11. NEVER auto-merge this PR
```

A wave stops for the operator **only** if it exposes a new semantic decision or
would violate the frozen reduction/ownership rules above.

---
---

# EXECUTION LEDGER

This section is the live record of the pruning PR (#221, branch
`test-architecture-suite-pruning`). One entry per wave, appended as the wave
lands. Everything above is the frozen audit and the frozen rulings; nothing
above is edited by an entry here.

## Baseline

Measured at `9f289d54` (master with PR #220 merged), the branch point.

| | value |
|---|---|
| collected cases | **9,987** |
| distinct test functions | **8,291** |
| test files | **534** |
| wall time | full unit suite, `-m "not real_run"` — recorded with Wave 1 |

**Correction to the audit's figures.** Phase 1 and Phase 2 measured
9,980 / 8,284 / 534 on master *before* PR #220. That safety fix added 7 cases
and 7 functions to `test_no_test_executes_a_launcher.py`, so the branch
baseline is 7 higher on both axes. All ledger deltas below are against
**9,987 / 8,291 / 534**. The audit numbers are left unedited above; this is the
reconciliation.

---

## Wave 1 — GPU milestone tracer (Q5)

### Before
9,987 cases · 8,291 functions · 534 files

### Change
| | |
|---|---|
| families touched | `tests/unit/core/test_gpu_milestone_trace.py`; docstring of `core/runtime_control/gpu_milestone_trace.py` |
| removed | 17 test functions / 17 cases |
| consolidated | none |
| redesigned | none |
| added | none |

Removed, with the reason each is no longer owned here:

| block | cases | replacement authority |
|---|---:|---|
| `test_unparsable_json_raises...`, `test_a_channel_missing_its_device_raises` | 2 | **Pydantic** — plain model validation |
| `test_identity_uuid_and_batch_travel_with_the_figure` | 1 | **Pydantic** — field declaration |
| `test_a_populated_unavailable_record_is_rejected` | 1 | **stronger unit invariant** — the "a gap cannot carry figures" concept is asserted across three separate snapshot models (`test_gpu_accounting.py:248,394`, `test_gpu_measurement_sampler.py:191`) |
| `TestBothSidesEmitOneSchema` (whole) | 2 | **Pydantic** — model round-trip with no custom serializer |
| `TestOrderAndUniquenessAreEnforced` minus the per-batch bound | 6 | **declaration + `MilestoneTraceMisuse`** — the ordering/uniqueness rules are raised by the type, not branched in code |
| `TestAMissingMilestoneIsVisible` (whole) | 2 | **obsolete** — asserts the diagnostic's own artifact shape, which was investigation-era output |
| `test_it_roots_ownership_at_its_own_process`, `test_the_tree_total_comes_from_the_driver_sampler_alone` | 2 | **the sampler's own tests** — `gpu_accounting` / `gpu_measurement_sampler` own ownership-rooting |
| `test_an_unreadable_allocator_is_none_and_never_zero` | 1 | **in-file duplicate** — same concept as `test_a_failed_query_stays_none_and_never_becomes_zero`, which is retained |

### Ownership rationale

The 208 MiB investigation is **RESOLVED, cause verified**
(`pr_c_measured_evidence_admission.md:3948`, `:4010`), so the file's
investigation-era content no longer owns anything. But the tracer is still
wired into production at four opt-in sites, so the *instrument* invariants
remain current and were kept in full.

### Independent failure classes

**Retained (28 cases):**

* the tracer stays **inert** without its environment variable, and no
  production module sets it (7) — keeps an opt-in diagnostic from becoming an
  always-on cost in the inference path;
* **milestone-7 placement inside the production files** (8) — asserts the shape
  of `inference_single.py` and the measurement worker, not of the tracer;
* the trace **does not perturb what it measures** (4) and the production path
  is byte-identical without it (2);
* **one definition of driver-visible memory** (2) — the default sampler *is* the
  production primitive, and no rival telemetry backend is introduced;
* three genuine runtime branches: a failed query stays `None` and never becomes
  `0`; a raising sampler becomes a value, not an exception; the per-batch bound
  skips rather than records (3);
* an unwritable path fails **before** any measurement, and an infrastructure
  error is not a measurement outcome (2).

**Intentionally retired:** the tracer's own record schema, ordering and
uniqueness rules, and the investigation-era artifact-shape checks.

### Validation
`tests/unit/core/test_gpu_milestone_trace.py` **28 passed**;
with `test_gpu_measurement_phases.py` **74 passed**; the two other files that
reference the module (`test_inference_checkpoint_loading.py`,
`test_step05c_c5_persisted_encoding.py`) **31 passed**. `ruff check` clean,
`ruff format --check` clean on both touched files. No mutation evidence
required: nothing was consolidated and no assertion was rewritten — every
retained case is byte-identical to its pre-wave form.

### After
9,970 cases · 8,274 functions · 534 files
**(−17 / −17 / 0)**

### Unexpected findings

1. **The wave lands at 28 cases, not the ~16–22 the ruling estimated.** The
   estimate assumed ~20 pure schema restatements; the actual count is 17.
   Reaching 22 would have required cutting into the explicitly-KEEP categories
   (inertness, placement, non-perturbation). The frozen rulings prohibit
   deleting real coverage to reach a number, so the number moved instead.
2. The production module docstring
   (`core/runtime_control/gpu_milestone_trace.py:6-14`) still presented the
   investigation as **open**, contradicting the design doc's own RESOLVED
   conclusion. Rewritten to state the verified cause, and to say explicitly what
   the surviving tests do and do not guard. No test asserted that prose, so
   nothing depended on it.
3. Every deleted block was an unparametrized single function, so cases and
   functions moved together 1:1 — this wave is neutral on the ratio and does not
   flatter the primary metric.

### Disposition
Inside the frozen rulings. **Continue autonomously.**

---

## Wave 2 — Closed-campaign harnesses (Q2) — **PARTIALLY IMPLEMENTED / PARTIALLY DEFERRED**

**No test was changed. No file was deleted.** The wave stopped at step 1 of the
frozen Q2 protocol, which is where it was designed to stop if the premise
failed.

### What the ruling required

```text
1. establish the new authoritative reachability oracle
2. prove the 77 retained tests exercise THAT oracle
3. mutation / negative evidence
4. only then delete the legacy harness + obsolete tests
```

**Step 1 is not satisfiable.** There is no other authoritative caller to
re-home onto.

### What the source says

`scripts/c2_prephase_validation.py` is the **sole non-test consumer of three
production modules**:

| production module | only importer |
|---|---|
| `core/runtime_control/environment_stability.py` | `scripts/c2_prephase_validation.py:121` |
| `core/runtime_control/formal_stability.py` | `scripts/c2_prephase_validation.py:124` |
| `core/runtime_control/formal_stability_controller.py` | `scripts/c2_prephase_validation.py:131` |

Verified by grepping every `*.py` outside `tests/` and `.gate_artifacts/`:
nothing else imports `environment_stability`, `formal_stability`,
`formal_stability_controller`, `FormalStabilityChannel`, `StepEventLog`,
`FormalStabilityWatcher`, `FormalStabilityController`,
`assess_pair_comparability` or `summarize_formal_arm`.

The reachability oracle in `test_environment_stability.py:336-351` and
`test_formal_stability_controller.py:456-547` is therefore not pointing at a
convenient caller that happens to be a legacy script. **It is pointing at the
only caller that exists.**

### Why this is a stop, not a judgement call

Deleting `scripts/c2_prephase_validation.py` does not retire a test harness.
It leaves three production modules with **zero callers** — and the 77 retained
cases, which Phase 2 classified as must-keep, would then be guarding code that
nothing reaches. That is the "component built, tested, never called" class the
repository already has a dedicated guardrail against
(`test_preflight_production_reachability.py`, V20 PR A).

This is frozen STOP condition **2** — *a supposedly historical test protects a
newly discovered current production invariant* — and it touches **3**, because
every resolution below changes production, not test architecture.

### The three resolutions, none authorised by the current rulings

| # | resolution | consequence |
|---|---|---|
| A | Keep the harness as the declared production entry point for the formal-stability subsystem, and re-label it (it is currently called a "legacy validation script" at `core/inference_defaults.py:26`) | Q2 becomes: retire `bg_admission_validation.py` only (−78 cases, no coupling). The C2 harness and its 104 cases stay, or shrink on their own merits |
| B | Retire the harness **and** the three production modules together | Largest reduction — but deletes a formal-stability subsystem, which is a scientific-behaviour decision, not a test decision |
| C | Wire the subsystem into a live path, then re-home the oracle onto that path | The largest amount of new production work, and it presumes the subsystem should be live — which nothing currently asserts |

### What is NOT blocked

Q2's other half has no such coupling. `scripts/bg_admission_validation.py` and
`scripts/bg_gpu_holder.py` import nothing that lacks another consumer, and
`test_bg_validation_harness.py:85-93` asserts they are unreachable from
`run_chain.sh`. That retirement (−78 cases) can proceed independently and is
not held by this question.

### Disposition
**DEFERRED under the conservative-retention policy above.** The operator ruled:
take the CONSERVATIVE HOLD — keep `c2_prephase_validation.py`, keep the
formal-stability production subsystem, keep the tests whose independent failure
classes depend on it. Do NOT choose B or C. Retiring it is no longer a
test-architecture decision; it is a production-ownership decision and is
outside this PR. **This is not a pruning failure — it is evidence that the
original Q2 assumption was incomplete.**

---

## POLICY AMENDMENT — conservative retention replaces stopping (operator, 2026-08-17)

Issued after Wave 2 stopped. The stop was consistent with the frozen stop
conditions, but the execution policy is changed so that a **local** ambiguity
can no longer become a **global** blocker.

**New default.** When pruning finds that a supposedly historical test or
harness is tied to a current production subsystem, and retiring it would need a
production decision:

```text
DO NOT modify production semantics
DO NOT guess whether the subsystem should be retired or made live
DO NOT stop the pruning PR

RETAIN the family conservatively
MARK the proposed retirement DEFERRED, with source evidence
CONTINUE every independent wave
```

The asymmetry that justifies it: **keeping 77 tests too long is reversible;
deleting a subsystem that may still matter is not.**

Decision rule per wave: (1) inside frozen authority → implement · (2) hidden
coupling but conservative retention preserves semantics → retain, defer,
continue · (3) separate production defect → record, fork a narrow safety PR if
obvious, continue · (4) would require choosing between meaningful production
behaviours → retain, defer, continue · (5) **no** meaningful pruning can
continue without new policy → only then stop.

Explicitly NOT reasons to stop: a family turns out unprunable; an estimate
shrinks; a hidden production caller exists; a design assumption is disproven; a
wave completes only partially.


---

## Wave 2a — Retire the unreachable B-G admission harness (Q2, independent half)

### Before
9,970 cases · 8,274 functions · 534 files

### Change
| | |
|---|---|
| removed | `scripts/bg_admission_validation.py`, `scripts/bg_gpu_holder.py`, `tests/unit/scripts/test_bg_validation_harness.py` (78 cases / 75 functions), and 3 cross-script cases in `test_bg_gpu_sampler.py` |
| consolidated / redesigned / added | none |

### Ownership rationale

PR B **merged 2026-08-02** (`pr_b_gpu_aggregation_attribution.md:3`, PR #153,
`4472f15`); the scripts have not been touched since. Production calls them
"legacy validation scripts" (`core/inference_defaults.py:26`), and the test file
itself asserts they are unreachable from `run_chain.sh`
(`test_bg_validation_harness.py:85-93`). Replacement authority: **obsolete**.

**The coupling that blocked the C2 half does not exist here — verified, not
assumed.** `bg_admission_validation.py` and `bg_gpu_holder.py` import only
`agent.schemas.hyperparam_tuning` (134 other non-test importers),
`agent.schemas.storage` (101), `core.sandbox_executor` (70) and
`execute_tools.dataset_config` (147). Deleting them orphans nothing.

The one claim worth keeping — `test_the_witness_calls_the_real_gate_not_a_copy`
(`:759-768`), that the witness reaches production `_admission_refusal` rather
than reimplementing it — **needed no re-homing**: the production-side
reachability is independently owned by `test_admission.py:348`
(`gates == ["_admission_refusal"]`), `test_admission_join_contract.py:29` and
`test_m5_resource_admission_enforcement.py:115`.

Three cases in `test_bg_gpu_sampler.py` read the deleted scripts' source
(`:126`, `:141`, `:151`) and were removed with them — their referent is gone, so
this is not weakening an assertion. `test_the_validation_launcher_is_a_known_role_not_foreign`
is **kept**: it reads only the sampler, which is unmodified.

### Independent failure classes

**Retired:** the internal shape of two scripts no production path reaches, from
a campaign that concluded 2026-08-02 — scenario wiring, one-admission-attempt
pinning, no-retry pinning, and six source-text assertions that were static
analysis in a pytest costume.

**Retained:** `scripts/bg_gpu_sampler.sh` and its 9 remaining cases. Its `STOP`
file is a **documented operator contract** that V20 PR E deliberately chose not
to change (`pr_e_campaign_scoped_control_state.md` D-E-8), which corrects the
Phase-1 claim that it was uncalled dead code. The script is left byte-unchanged;
its classification patterns for the two removed processes are now vestigial but
harmless, and modifying it is out of scope by D-E-8.

### Validation
`tests/unit/scripts/` + `test_gpu_admission_wiring.py` +
`health_checks/test_formal_launch_policy.py`: **556 passed**, rc=0. The last two
mention the removed script in prose only, and were run precisely to prove that.
`ruff check` and `ruff format --check` clean. No mutation evidence required:
deletions only, no assertion rewritten, no test consolidated.

### After
9,889 cases · 8,196 functions · 533 files
**(−81 / −78 / −1)**

### Unexpected findings
`test_bg_gpu_sampler.py` reads the deleted scripts' source — a coupling neither
audit phase found, because both classified the two files as independent. Caught
by grepping surviving references before committing, not by a failing test.

### Disposition
Inside the frozen rulings. **Continue autonomously.**

---

## Wave 2b — StepNN proven tombstones (Q3)

### Before
9,889 cases · 8,196 functions · 533 files

### Change
8 functions / 12 cases removed. Nothing consolidated, redesigned or added.

| removed | cases | proof the mechanism is gone |
|---|---:|---|
| `test_step00_task_config_baselines.py::test_cfg3a_lit_review_declares_no_task_description`, `::test_cfg3a_task_config_remains_the_one_declaration` | 2 | **`test_step04b_task_description_single_source.py:185-194`** parses *every* `configs/**/*.yaml` and asserts the declaring set is exactly `{task_config.yaml}`; `:224-228` carries the "not zero sources" half. Strictly implies both, and additionally sees a declaration appearing in a third file — which the lit-review-only check cannot |
| `test_step02a_c1_baselines.py::test_the_pattern_renders_identically_across_the_whole_index_space` | 1 | the divergent inline filename constructions are **gone**: `grep -rn zfill execute_tools/ core/ nodes/` yields exactly three hits — `deliverable_spec.py:149` (the declared `index_width` authority) and two comments. Re-inlining is guarded by `test_step02a_c4_inference_scoring.py:216-241`, which is retained |
| `test_step02a_c4_inference_scoring.py::test_every_index_in_the_declared_space_round_trips` | 1 | same mechanism, same retained guard |
| `test_step02a_c2_profile_injection.py::test_selection_determinism_is_unchanged_by_the_migration` | 1 | its own docstring names `test_sample_set_builder.py`'s five sha16 digests as the authority; the re-export collapse is complete, and `test_step02b_b2_explicit_profile_selection.py:133-147` forbids the three topology constants in the builder source — strictly stronger |
| `test_step03_a3_a8_plugin_compatibility.py::test_the_workspace_boundary_is_declared_not_assumed` | 1 | body is `assert isinstance(_on_disk_plugin_files(), list)` against a test-local helper returning a list literal. Passes for any content of `agent_generated/models/`. The declared boundary survives in the sibling's `pytest.skip` reason |
| `test_step03_a6_model_boundary_dtype.py::test_training_is_int32_and_inference_is_int64` (5 params), `::test_fcnet_is_float32_at_every_boundary` | 6 | the dtype tables are defined **in the test file** at `:108-130` — verified, no production definition exists — so these compare literals to literals. The tables stay: `:228` uses them as the expectation for an **observed** dtype |

### Ownership rationale

Phase 2 established the ladder is ~98 % current architecture and leaves receipts
for its own retirements (two tombstones where inertness assertions were deleted
and *inverted* into named replacements that exist and run). Only tombstones with
a proven-gone mechanism are retired here. **A6 and A2 are retained in full** —
the F-1 divergence A6 pins is encoded in production today
(`model_input_dtype.py:69,74`) and production names A6 as its evidence base
(`:53-59`); only the 6 self-referential cases go.

### Independent failure classes
**Retired:** none. Every removed claim has a named surviving owner, or was
structurally incapable of failing.
**Retained:** the entire capture-first ladder, including all Checkpoint-0
numeric baselines (protected), A2's 15-cell matrix, A6's three observed
boundaries, and every Stage-B genericity rung.

### Validation
`tests/unit/workflows/` + `tests/unit/ml_models/` + the four touched
`execute_tools` files: **588 passed**, rc=0. Ruff check and format clean on all
six files. No mutation evidence required — deletions only, no assertion
rewritten. The predicted delta (12 cases / 8 functions) matched the measured
delta exactly, which is the arithmetic check that nothing extra was removed.

### After
9,877 cases · 8,188 functions · 533 files
**(−12 / −8 / 0)**

### Unexpected findings
None. This is the one wave whose source-audit prediction held to the case.

### Disposition
Inside the frozen rulings. The STATUS/README prose-pin consolidation (7 → 1,
the remaining Q3 item) is deferred to Wave 5a, where the other test-redesign
work lives. **Continue autonomously.**

---

## FORECAST SUPERSEDED BY IMPLEMENTATION EVIDENCE (operator, 2026-08-17)

```text
Projection B (audit-time)          8,064 - 8,585 cases
                                   6,770 - 7,213 functions

Implementation-grounded forecast   ~9,350 - 9,500 cases
                                   ~7,650 - 7,850 functions
                                   ~530 files
```

**Reason:** several categories the audits assumed retirable were proven, at
source, to own current production semantics, and were conservatively retained —
principally the formal-stability subsystem behind `c2_prephase_validation.py`
(Wave 2, DEFERRED), and three of the four large categories that turned out to be
current architecture rather than archaeology.

**This is not a pruning failure.** Projection B was a forecast built on audit
assumptions; implementation tested those assumptions and several were wrong. The
operative rule is that a prediction may be wrong but semantic evidence may not
give way to a number.

The final figure is left to the implementation. The revised review standard is
correspondingly not "how far did the count fall" but:

1. do the removed maintained functions genuinely lack independent ownership?
2. can the surviving functions be explained as current architecture?
3. were weak green tests replaced by load-bearing ones?
4. does the admission rule prevent regrowth?


---

## Wave 3a — Pydantic restatements and one superseded truth table (`tests/unit/core`)

### Before
9,877 cases · 8,188 functions · 533 files

### Change
26 functions / 51 cases removed; 2 families consolidated in place.

**Superseded authority (−16 cases).** `test_scientific_authority.py`'s
`test_each_row` (10), `test_exactly_one_combination_is_authoritative` (1) and
`test_a_caller_supplying_a_conclusion_is_refused` (5). Replacement:
`test_authority_matrix_frozen.py`, verified — `len(MATRIX) == 27` at `:112` is
the **complete** 3×3×3 space against the truth table's 10 hand-picked rows, it
asserts the whole `model_dump()` per row (including
`enters_incumbent_selection` / `enters_scientific_aggregation`, which the 10-row
form never checked), it carries the same
`test_exactly_one_combination_is_authoritative` claim at `:156` derived over 27
rows, and `test_a_caller_cannot_supply_a_conclusion` at `:209`. The rest of
`test_scientific_authority.py` is untouched: `TestRecordAuthorityIsFailClosed`,
`TestRecordAuthorityLegacyLadder` and `TestLaunchHistoryCannotReachTheVerdict`
are unique.

**Pydantic/stdlib-owned declarations (−27 cases).** `Literal` rejection,
`extra="forbid"`, `frozen`, `gt=0` / `ge=1` / `min_length`, a required field
being required, and `SIGTERM == 15 / SIGKILL == 9` — across
`test_failure_attribution`, `test_runtime_session`, `test_probe_hard_timeout`,
`test_server_configs`, `test_gpu_admission_wiring`, `test_pair_admission`,
`test_v20_slot_scheduler`, `test_hardware_context`, `test_gpu_accounting`,
`test_calibration_quarantine`, `test_runtime_decision_policy`,
`test_measurement_identity_and_envelope`, `test_measurement_capability`.

**Consolidated, concept preserved (−14 cases, −0 functions).**
`test_no_identity_field_may_be_blank` (8 → 1) and `test_no_dimension_may_be_blank`
(8 → 1) now assert the concept across the whole field set in one pass and
**report every offending field**, where the parametrized form reported only the
first. The second also drops two cases that existed only to `pytest.skip` two
closed vocabularies; the exclusion is now a set difference with the reason in a
comment.

### What was deliberately NOT removed

Every genuine cross-field `model_validator`: `ResolvedMeasurementCapability`'s
"unavailable must explain itself" (three directions), `admitted=True` may not
carry a `reason_code`, `may_recommend_resource_reduction` refusable **and** not
disclaimable, source ↔ `formal_execution_eligible`, `telemetry_available=False`
may not carry figures, `headroom_gib` must follow from its inputs, soft budget <
hard deadline, and the inverted-span refusal. These encode multi-field semantics
no declaration expresses.

### Independent failure classes
**Retired:** none. Each removal is owned by Pydantic, by the stdlib, or by a
named stronger test.
**Retained:** the complete authority matrix; every cross-field validator; both
blank-field concepts, now with better failure messages.

### Validation
`tests/unit/core/` **2,439 passed**, rc=0 — the whole directory, because the
edits span 14 of its files. Ruff check and format clean across `tests/unit/core/`.
One structural fix: removing all four cases from `TestServerConfigSchema` left an
empty class body (a syntax error, caught by ruff before commit, not by pytest);
the class shell and its section header were removed with it.

### After
9,826 cases · 8,162 functions · 533 files
**(−51 / −26 / 0)**

### Unexpected findings
The case:function ratio of this wave is 1.96 — nearly double the suite's 1.20 —
because parametrised declaration restatements are exactly where cells outrun
claims. It is the one wave where case count overstates the ownership change, and
it is reported that way rather than quoted as progress against the primary metric.

### Disposition
Inside the frozen rulings. **Continue autonomously.**

---

## Wave 3b — Cross-product decision tables (prompt guards)

### Before
9,826 cases · 8,162 functions · 533 files

### Change
Three stacked cross-products collapsed. **0 functions removed** — every one of
the four test functions still exists and still owns its property; only the cells
are gone.

| family | cases | → | retained property |
|---|---:|---:|---|
| `test_prompt_banned_vocabulary.py::test_banned_vocabulary_absent` | 55 | 1 | no V9-banned token appears in any production prompt |
| `test_proposal_prompts.py::TestNoHardcodedAgentNames…::test_forbidden_phrase_absent` | 27 | 1 | no prompt file names an agent to set trust; calibration flows via `AgentCard.trust_level` |
| `…::TestModeFilesRedirectSynthesis` (2 functions) | 12 | 2 | every mode file redirects to the base prompt and never mentions the dead "Advice JSON" |

### Ownership rationale — why the collapsed form is *stronger*

Each was `len(tokens) × len(files)` cells sharing **one** failure class, and the
matrix form was worse in three concrete ways:

1. **pytest stops at the first failing cell**, so a token reintroduced across
   several prompts surfaced as a single failure;
2. cell count grew **multiplicatively** as either list grew;
3. `test_banned_vocabulary_absent`'s parametrize ids embedded the **entire
   multi-kilobyte prompt text**, making `--collect-only` and `-k` output
   unusable.

The replacements scan the whole matrix and report **every** violation.

### Validation
`tests/unit/agent/` **4,120 passed**, rc=0.
`tests/unit/agent/prompt_templates/test_proposal_prompts.py` 21 passed. Ruff
clean.

**Mutation evidence** (required — this wave consolidates rather than deletes).
Planted `"frequency_band low-frequency "` into `PLANNER_PROMPT` at
`agent/prompts.py`; asserted exactly one target site before mutating; the
survivor went RED and reported **both** violations:

```text
E   PLANNER_PROMPT: 'frequency_band'
E   PLANNER_PROMPT: 'low-frequency'
```

The parametrized form would have shown one. Production restored via
`git checkout` and the baseline re-run green (5 passed). That is the
consolidation's justification made executable: strictly more information from
one twelfth of the cells.

### Independent failure classes
**Retired:** none. Three properties in, three properties out.
**Retained:** all three, with strictly better failure messages.

### After
9,736 cases · 8,162 functions · 533 files
**(−90 / 0 / 0)**

### Unexpected findings
This wave is the clean illustration of the P2-1 finding: **−90 cases, −0
maintained claims.** It improves failure reporting and collection legibility and
does nothing at all for the primary metric. Recorded explicitly so the waterfall
is not misread as ownership progress.

### Disposition
Inside the frozen rulings. **Continue autonomously.**

---

## Wave 4a — V19 launcher family: retire the duplicated Gate-parity pins (Q6)

### Before
9,736 cases · 8,162 functions · 533 files

### Change
4 functions / 34 cases removed from `test_c14_gate_v19_parity.py` (40 → 6).

| removed | cases | replacement authority, verified |
|---|---:|---|
| `test_the_production_settings_are_pinned` | 18 | `test_v19_gate0_pair_runner.py::test_frozen_values_exact` |
| `test_the_bounded_settings` | 14 | same |
| `test_the_gate_is_cold_start` | 1 | `::test_no_forbidden_flags` — 3 flags vs this one's 1 |
| `test_the_two_chains_differ_only_in_identity_and_advice` | 1 | `::test_arch_loss_differ_only_in_intended_fields` — also asserts switch sets equal |

**Domination verified, not assumed.** Every flag/value pair in the two
parametrize lists appears in `FROZEN_VALUES` (`:43-77`) or `FROZEN_SWITCHES`
(`:78-84`), and `test_frozen_values_exact` (`:141-151`) iterates **all** of
`FROZEN_VALUES` against the same `gate_chain_args` output — for **both**
flavors, not one — and additionally asserts `switches == FROZEN_SWITCHES`
exactly. The replacement is strictly stronger on both axes.

### Ownership rationale — Q6(b) applied

The six survivors are what only a **cross-surface comparison** can establish,
and none is duplicated: the differential parity mechanism itself
(`test_nothing_outside_the_frozen_set_differs`, with its frozen 17-flag
`GATE_SCOPED_FLAGS` allowlist, which caught the real 2026-07-31 VRAM
divergence), the DS8 scope/monitored-file pairing, and advice-file content
integrity — the only place in the repository asserting an advice file is
schema-valid and speaks about its own role.

The module docstring now states the Q6(b) relabelling explicitly: both compared
surfaces are **retained legacy operator surfaces**, the current campaign surface
is `launch_v20_campaign.sh` (`v20_queue_runner.py:37`), the current Gate entry
point is `run_chain.sh` directly (`gate_testing_standard.md:176-194`), and
`README.md:77` says otherwise only because it was written 2026-08-04, two days
before the V20 launcher existed.

### Q6(i) — discharged for this file, by scoping not by editing

The removed `test_the_production_settings_are_pinned` carried one of the four
`openai_tiered_v1.json` pins. The remaining pins live in the V19 snapshot files
and are **permitted by the ruling** — a historical snapshot may pin what V19
emitted. What the ruling forbids is a historical pin passing as current policy,
so the docstring now states that current Gate policy is owned by
`test_gate_standard_contract.py:244` and requires `openai_tiered_pro.json`
(operator decision 2026-08-13). No V19 script was edited and no new value was
hardcoded by judgement.

### Independent failure classes
**Retired:** none — all four removals are dominated by a stronger sibling
asserting the same output.
**Retained:** everything the operator protected — `test_c13_stop_semantics.py`
untouched (9 current-contract cases), both live-process self-exclusion guards
untouched, all path-component refusals with their positive controls untouched,
library-default immunity untouched, and the three process-group kill suites
untouched and unmerged.

### Validation
`tests/unit/sdsc_submission_scripts/` **529 passed**, rc=0. Ruff clean. No
mutation evidence required: deletions dominated by an existing test, no
consolidation, no assertion rewritten.

### After
9,702 cases · 8,158 functions · 533 files
**(−34 / −4 / 0)**

### Unexpected findings

The ruling's target for this family was 246 → ~83–116, i.e. roughly −140. This
wave delivers −34. The remainder is the **restructure** — collapsing the V19
policy-generation tests into one frozen-snapshot family and building a current
launcher matrix — which is a rewrite, not a deletion, and which Q6(ii) blocks at
its final step. Per the conservative-retention policy that is recorded here
rather than forced: see the deferral below.

### Disposition
Inside the frozen rulings. **Continue autonomously.**

---

## Wave 4b — V19 family restructure — **DEFERRED**

The remaining ~106 cases of the Q6 target require rewriting the V19 policy tests
into a single frozen historical snapshot plus a new current-launcher matrix.
Deferred, for two reasons recorded rather than worked around:

1. **Q6(ii) blocks its final step.** `v20_queue_runner.py:220` sets
   `stop_file = ws_root / "STOP"` — a shared collection-root STOP, the shape of
   the 08:17 incident that V20 PR E removed from the V19 runner. The operator
   ruled this needs a narrow production-safety audit and, if it is the same
   incident class, a separate safety PR merged first. Building the current-
   launcher matrix now would bake in whichever answer I assumed.
2. The restructure's own risk is losing a refusal case in the merge, and the
   protected list is long and specific. It is the wave that most deserves to be
   done against a settled current-launcher contract rather than beside an open
   question about it.

Nothing is deleted for this item. The 246-case family stands minus the 34
verified duplicates.

---

## Wave 5a — Redesign the weak "load-bearing" regressions (Q7 / P2-8)

### Before / After
9,702 cases · 8,158 functions · 533 files → **unchanged (0 / 0 / 0)**.

This wave deletes nothing. Its success criterion is the one the operator set:
*before, the test is green but does not prove its claim; after, mutating the
intended semantic property turns it RED.*

### 1. `test_pr07c_validation_pricing.py:701` — tautology → differential oracle

**Was** `actual < actual + validation_total`, with `validation_total > 0`
established two lines above: necessarily true, and blind to the mutation its own
comment named.

**Why it could not simply be bracketed.** The training window is not recorded
anywhere in the sidecar (verified: the observation's `total` is `null`), and the
actual legitimately exceeds the verification's measured per-step rate — 21.4
against 5.87 ms/step on this fixture — because epoch ≥ 1 dataset reconstructions
**are** training cost (`train_engine_sandbox.py:1716-1718`). A tolerance
comparison against the measured rate would have been either vacuous or flaky. An
outer wall-clock bracket fails too: the training window is ~0.96 s inside a ~4 s
`_run`, so absorbing 0.44 s of validation stays well under any honest bound.

**Now a differential.** `_run` takes an `eval_sample_set` (sentinel-defaulted so
`None` still means *no validation*), and the test runs the identical workload
with the pass removed. Identical training work, so a pure per-step actual must
not move; an actual that absorbed validation rises by `validation_total`.
Carries an anti-vacuity assertion that validation is a large enough share of
training for the bound to be breachable — without it, a fast validation would
quietly restore the tautology.

**Mutation proof.** `- validation_seconds_total` → `- 0.0` at
`train_engine_sandbox.py:1727` (target site asserted `== 1`, caches cleared,
production restored, baseline re-run green):

```text
training actual 0.868s against 0.476s for the same work without validation,
while the pass cost 0.413s — the actual is absorbing the validation seconds
```

0.476 + 0.413 = 0.889 ≈ 0.868. The old assertion stayed green under this exact
mutation.

**Cost:** one extra ~4 s CPU subprocess in this test.

### 2. `test_pr07c_validation_pricing.py:309` — modelled timing → pointer

Removed the three lines that computed `TRAIN_ACTUAL_S + VALIDATION_ACTUAL_S *
(500/15_000)` and compared it to the stale deadline: arithmetic over three
constants the test chose, which production could not move. The refresh-observation
half is kept. The docstring now names the owner of arrival time —
`test_pr07c_validation_persistence_timing.py::TestValidationPredictionArrivesDuringThePass`,
a real streaming run whose model reads the live sidecar **during** validation —
and records that deadline-vs-real-elapsed is Gate 2's.

### 3. `test_watchdog.py:53` — self-produced value → kernel probe

**Was** `assert kill_info["survivors_detected"] is False`, a value produced by
the code under test (`core/sandbox_executor.py:995-1003`). Deleting the orphan
probe and hardcoding `False` left it green — confirmed by mutation.

**Now** the child reports its own process-group id and the test asks the kernel
directly, matching `test_probe_hard_timeout.py:126-130`:

```python
with pytest.raises(ProcessLookupError):
    os.killpg(pgid, 0)
```

Production's self-report is still asserted, but now *beside* an independent
oracle rather than as the only one.

**Honest limit, recorded rather than glossed.** I could not construct a cheap
mutation that isolates the new oracle. The paired mutation (kill the leader only,
leaving grandchildren, **and** disable the probe) does not fail — it *hangs* for
61 s, because the parent blocks on a pipe the orphans hold open, and by the time
the probe runs they have exited on their own. So the improvement here rests on
the CLAUDE.md rule (never assert a value read back from the thing under test)
and on parity with an existing correct pattern — not on a mutation proof. Stated
plainly because claiming one would repeat the defect being fixed.

### Independent failure classes
**Retired:** none. **Retained:** all three, and two of them are now actually
provable.

### Validation
`test_pr07c_validation_pricing.py` 26 passed; `test_watchdog.py` 13 passed. Ruff
check and format clean. Production verified byte-restored after both mutation
runs (`git diff --stat core/sandbox_executor.py` empty, `killpg` count 7).

### Unexpected findings
Adding the no-validation control tripped `FileExistsError` on
`(tmp_path / "data").mkdir()` — the helper assumed one call per test. Fixed with
`exist_ok=True`. A second `_run` in one test had never been done before.

### Disposition
Inside the frozen rulings. The STATUS/README prose-pin consolidation (Q3 sub,
7 → 1) is **not** done: it is a `tests/unit/examples/` maturity-governance edit
whose D14 owner is a different milestone, and it is recorded as remaining debt
rather than bundled into a redesign wave. **Continue autonomously.**

---

## Wave 5b-1 — Approved additions: FocalLoss1D oracle and the self-referential guardrail (Q7)

### Before → After
9,702 → **9,714** cases · 8,158 → **8,170** functions · 533 → **534** files
**(+12 / +12 / +1)**

### 1. `FocalLoss1D` numeric oracle — 5 cases

The frozen loss had no arithmetic test. `TestFocalLoss1D`'s four cases assert a
scalar shape (guaranteed by `reduction="mean"`), non-negativity
(mathematically guaranteed) and two coarse orderings — all of which survive an
`alpha` change.

Closed form (line 161 masks the sum to the target class):
`loss = mean(-alpha * (1 - p_c)**gamma * log(p_c))`. Every expectation is
hand-computed from it and hardcoded.

| alpha | gamma | logits | expected | pins |
|---:|---:|---|---:|---|
| 0.5 | 2.0 | `(0, 0)` | 0.0866433978 | the paper alpha |
| 0.25 | 2.0 | `(0, 0)` | 0.0433216989 | the historical drift, as an exact ×½ |
| 0.5 | 0.0 | `(0, 0)` | 0.3465735912 | the focal exponent |
| 0.5 | 2.0 | `(ln 3, 0)` | 0.0089900587 | softmax + target mask |
| *defaults* | 2.0 | `(0, 0)` | 0.0866433978 | **both** default sites |

**A defect in my own first draft, recorded because it is the point.** The first
four cases all pass `alpha` explicitly, so flipping the default proved
*nothing* — mutation showed the new oracle staying green exactly like the four
legacy tests. The drift that actually happened was a **default**. Adding the
fifth case exposed a second trap: there are **two** defaults on this path and
they are easy to confuse — `LossConfig.alpha` is declared `default=0.5`
(`models_format_sandbox.py:640`), which is what an unset config really gets,
while the class-level `else 0.5` (`loss_models_sandbox.py:143`) is reached only
when alpha is explicitly `None`. The case now pins both.

**Mutation proof**, each applied at an asserted-unique site, caches cleared,
production restored via `git checkout`, baseline re-run:

| mutation | legacy `TestFocalLoss1D` | new oracle |
|---|---|---|
| schema default `0.5 → 0.25` (`models_format_sandbox.py:640`) | **4 passed** | **1 failed** |
| class fallback `0.5 → 0.25` (`loss_models_sandbox.py:143`) | **4 passed** | **1 failed** |

Two earlier mutation attempts aborted on `count != 1` and are reported rather
than hidden: their "passed" results were meaningless because production was
never modified. The site-count assertion is what caught it.

### 2. `tests/unit/guardrails/test_no_self_referential_expectations.py` — 7 cases

Justified by three instances of one failure class in a single audit
(`:701`, `test_observed_subprocess_seam.py:422`, `test_watchdog.py:53`).
CLAUDE.md already forbids it in prose; prose did not stop three of them.

**Scope is deliberately narrow, and the docstring says so.** It detects exactly
one syntactic shape — a value compared against a `model_fields[...]` lookup. It
does **not** attempt the tautology form (`x < x + c`) or the
self-reported-value form, because neither is decidable from syntax; those stay
review-time rules. A guard that guessed would fire on correct tests and be
switched off, which is how the launcher guard nearly died.

Three exemptions, each with its own detector case: cross-model agreement
(`A.model_fields[k].default == B.model_fields[k].default` — a real invariant,
and what `test_cross_schema_invariants.py` exists for), existence checks, and
**comparison against a literal**, which is the correct hardcoded-pin form every
offender should become. That last exemption was added after the first draft
flagged `TrainConfig.model_fields["epochs"].default == 10` — a *good* test.

4 of the 7 cases are detector self-tests, plus one anti-vacuity case. The
corpus currently scans clean.

### Independent failure classes
**Added:** the frozen loss's arithmetic (incl. both default sites); the
self-referential-expectation shape, repo-wide and flat in cost.

### Validation
`tests/unit/guardrails/` + `tests/unit/ml_models/` **390 passed**. Ruff check
and format clean. `git diff --stat ml_models/` empty after all four mutation
runs.

### Disposition
Inside the frozen rulings; net addition so far +12 against the ~+6–8 budget,
which the remaining two additions will not exceed by much. **Continue.**

---
---

# OPERATOR PIVOT — THE PRIMARY PROBLEM IS TEST-LAYER OWNERSHIP

**Issued 2026-08-17, after Phase A landed. This supersedes the framing of
everything above, and re-scopes the PR.**

Phase A is accepted and stays. But it did not attack the main architectural
problem, and the case/function counts it moved are not the objective:

> **The primary problem is that Unit, Gate 1 and Gate 2 overlap too much.**

For a system this size it is neither necessary nor desirable for the Unit tier
to attempt to prove every behaviour. The philosophy *"every meaningful behaviour
should have a Unit test"* is **explicitly rejected**. What is required instead:

> **every IMPORTANT failure class has a canonical verification layer.**

Some important failure classes are only honestly testable in Gate 1 or Gate 2.
That is acceptable and intentional.

## The PR's three phases

| phase | question | status |
|---|---|---|
| **A** | mechanical redundancy and weak-test cleanup | **LANDED** — 10 commits, −273 cases / −121 functions |
| **B** | Unit vs Gate 1 vs Gate 2 **ownership** pruning | **IN PROGRESS** |
| **C** | selective CI architecture | **IN PROGRESS** |

## Canonical ownership (frozen)

A behaviour has **ONE** canonical owner. Overlap requires an explicit
independent reason, and **"extra safety" is not a reason.**

**UNIT owns** — deterministic local semantics · scientific/numerical oracles ·
nontrivial cross-field invariants · contract resolution · protocol mapping ·
serialization / identity / hashing · deterministic failure classification ·
pure policy and state-machine arithmetic · fail-closed local boundaries ·
genericity contrasts · narrowly localized regressions.

**GATE 1 owns** — the real LLM boundary · real prompt → model response ·
structured generation · schema-valid real agent output · proposer / implementor
/ validator behavioural reachability with a real model · failures that
fundamentally depend on **model** behaviour rather than deterministic
repository logic.

**GATE 2 owns** — real data · real subprocess lifecycle · real GPU · training ·
validation · inference · scoring · watchdog against **real elapsed time** ·
persistence timing · **sidecar visibility timing** · process cleanup · complete
production workflow reachability.

## PR-07c is the reference example, and the test to apply everywhere

~9,967 Unit cases were green. Real Gate 2 found the validation prediction was
not persisted during the live pass. The Unit suite proved arithmetic against a
sidecar **that was already populated**; Gate 2 proved whether production caused
that state to exist at the correct time.

```text
Unit    provider arithmetic
        the RuntimeSession persistence METHOD
        a narrow regression that precisely localizes the discovered bug

Gate 2  whether the real training -> validation lifecycle writes the
        prediction before the stale watchdog fires
```

**The decisive question for every family in Phase B:** *could a fixture have
manufactured the state whose arrival, timing or existence is the property under
test?* If yes, Unit cannot own it.

And the standing prohibition, restated: **do not replace a deleted fake Gate
with a more elaborate fake Gate.**

## Phase-B classification vocabulary

Every substantial family is classified as exactly one of:

```text
UNIT-OWNED          deterministic; the fake is irrelevant to what it proves
GATE1-OWNED         what it really proves needs a real model
GATE2-OWNED         what it really proves needs a real lifecycle
JUSTIFIED OVERLAP   both layers need it — the independent reason is stated
OBSOLETE            owns nothing
```

Phase B reports, separately: Unit-owned functions retained · Gate1-owned Unit
functions retired · Gate2-owned Unit functions retired · justified-overlap
functions retained · obsolete functions retired.

## Phase C — selective CI

`every PR → full unit suite` does not scale (~16 min today). Target:

```text
changed production modules
    -> affected semantic owners / consumers
    -> corresponding deterministic test suites
    +  required Gate classification
```

Filename heuristics alone are **not** acceptable; an explicit
ownership/dependency model is required, it must **fail safe** (an unmapped path
runs everything), and it must carry a test proving the map is not stale.

The full suite is **not** deleted — its role changes:

```text
PR CI                     selective affected deterministic tests
merge queue / post-merge  full unit suite
nightly                   full unit suite + broader integration
milestone / semantic      Gate 1 / Gate 2 per ownership
```

## New feature-PR requirement (permanent governance)

Every future design document declares:

```text
UNIT OWNERSHIP    exact deterministic failure classes
GATE 1 OWNERSHIP  exact real-LLM failure classes
GATE 2 OWNERSHIP  exact real-lifecycle failure classes
CI IMPACT         affected test domains / modules
```

And every new test answers **both**: what unique failure class does this own,
and why is that class not already adequately owned by another layer?

## Success metric, restated

No longer function count alone. The primary result is:

```text
clean ownership boundaries
+ a materially smaller Unit suite
+ PR-scoped CI
+ a full-suite safety net on main and nightly
```


---

## Wave 5b-2 — Producer → serialization → consumer boundary oracle (Q7)

### Before → After
9,714 → **9,717** cases · 8,170 → **8,173** functions · 534 files **(+3 / +3 / 0)**

### The hole
Two different serializations of the same object:

| | code | emits for `-inf` |
|---|---|---|
| production `records.py:952-954` | `json.dump(coerce_nonfinite_to_none(output.model_dump()), …)` | `null` |
| the test fixture `test_per_file_best.py:171` | `f.write(output.model_dump_json())` | `-Infinity` |

Production's own comment states the constraint: `model_dump_json` emits
non-standard `-Infinity`, which breaks the dashboard's `JSON.parse`. So the
whole `-inf` no-signal path through `build_table` and the `run_output_sha256`
byte check was exercised only against a shape production never produces.

### Three cases

1. **`test_production_writes_through_the_coercion`** — the reachability half.
   Asserts `records.py` still coerces *before* serialising, and that the
   `model_dump_json` form has not returned.
2. **`test_a_no_signal_score_survives_as_null_not_as_a_nonstandard_token`** —
   no `-Infinity` / `Infinity` / `NaN` reaches disk, and the document parses
   under a **strict** RFC reader. `json.loads` accepts `-Infinity` by default,
   which would have hidden the entire defect, so the test installs a
   `parse_constant` that refuses.
3. **`test_the_consumer_reads_the_producers_bytes`** — the join: `build_table`
   treats the coerced `null` as no signal.

### Scope, stated because it bounds the claim
Driving `finalize_run_output` end to end needs a full `RunBindings` and
`RunExitSnapshot` — out of proportion for a serialization contract. The
behavioural cases therefore call the **real** `coerce_nonfinite_to_none` with
the same `json.dump` call production uses, and case 1 binds that to production
so the two cannot drift apart silently. **Without case 1 this file would be
asserting its own conventions again — which is the defect it exists to fix.**

### Mutation proof
Reverting `records.py` to `f.write(agent_output.model_dump_json())` (target site
asserted `== 1`, production restored, baseline re-run): case 1 goes RED,
`1 failed, 18 passed`.

### Validation
`test_per_file_best.py` 19 passed. Ruff check and format clean.

### Not done, and why
The **real-sidecar → real-provider join** (the fourth approved addition) is
folded into Phase B instead. Under the frozen ownership model, *sidecar
visibility timing* is explicitly Gate-2-owned; what remains for Unit is the
narrower contract question — does the provider parse what the producer wrote —
and that is better placed once Phase B has settled which sidecar tests survive
in Unit at all. Recorded so it is not silently dropped.

### Disposition
Phase A additions complete: **+15 cases / +15 functions** against the ~+6–8
budget, the overshoot being the two extra FocalLoss default cases and the
guardrail's detector self-tests. **Continue into Phase B.**

---

## CONTEXT-SAFE AUTONOMY AMENDMENT (operator, 2026-08-17)

Running low on context is **not** an operator stop condition. The distinction:

```text
semantic STOP              a new operator decision is genuinely required
execution / context        checkpoint + fresh-session continuation,
boundary                   NO re-approval needed
```

When a session lacks the headroom to independently verify Phase-B / Phase-C
findings with the required rigor, it must **not** rush verification, relay
sub-agent conclusions as truth, implement deletions on unverified
classifications, or ask for re-authorization of already-frozen work. It
performs an **EXECUTION CHECKPOINT** instead.

### Verification labels — never collapse a claim into a finding

Every Phase-B / Phase-C item is recorded with exactly one status:

| label | meaning |
|---|---|
| **CLAIM** | a sub-agent said it; the main session has not checked it |
| **VERIFIED** | the main session read the source and confirmed it |
| **PARTIALLY VERIFIED** | some load-bearing parts confirmed; the rest named |
| **REFUTED** | checked and found wrong; the correction is recorded |
| **UNVERIFIED** | not yet checked, with the exact next inspection named |

**No deletion may be implemented from a `CLAIM` or `UNVERIFIED` item.** This is
not caution for its own sake: in the Phase-1/2 rounds four sub-agent claims
failed verification, and two of this session's own additions were defective on
first draft and caught only by mutation.

### Required per audit item

raw finding · source files/symbols inspected · proposed classification ·
verification status · any claim that FAILED verification · exact implementation
consequence if verified · exact next source inspection if not.

### Continuation is pre-authorized

A fresh session may re-read the ledger and source, verify remaining claims,
reject or refine bad ones, implement verified ownership pruning, implement
selective CI, update the ledger, and continue to READY FOR OPERATOR REVIEW —
**without asking** "may I continue Phase B?", "may I implement this frozen
rule?", or "may I continue after the context reset?". Those are already
authorized.

> Prefer verified partial work + a durable ledger + fresh continuation over
> rushed completion in one context window.

---

## PHASE B — REQUIRED REPORTING SHAPE

The audit must land on numbers, not impressions:

```text
Gate-1-owned Unit functions
    inspected:
    retire:
    retain as deterministic seams:
    justified overlap:

Gate-2-owned Unit functions
    inspected:
    retire:
    retain as deterministic seams:
    justified overlap:

Pure Unit
    retained:
```

If the totals come out small, that is itself the finding — it would mean the
repository is cleaner than the pivot assumed, and it must be reported that way
rather than padded.

### The `real-sidecar → real-provider join`, re-split under the frozen model

Recorded as the worked example of the ownership question, because the operator
accepted the re-classification:

```text
Unit    given a valid production-SHAPED sidecar, the provider parses and
        uses it correctly                                    <- a contract

Gate 2  the real runtime actually produces that sidecar at the required
        lifecycle moment                                     <- timing
```

The second must not be pushed back into Unit.

---

## PHASE C — THE NON-NEGOTIABLE PRINCIPLE

Selective CI must **fail closed**:

```text
changed file -> selector KNOWS the ownership      -> run the relevant suites
changed file -> selector does NOT know            -> run the FULL suite
```

Never `unmapped file -> no tests`.

These always trigger broad or full, by construction rather than by mapping:

* `conftest.py` and anything under `tests/helpers/`
* shared schemas / protocols with broad fan-out
* the CI selector itself, and the dependency manifest it reads
* repo-wide guardrails (their input is the entire tree)
* central registry / plugin infrastructure

A selective model that creates a blind spot to save 15 minutes is a net loss.


---
---

# PHASE B — AUDIT FINDINGS AND VERIFICATION

Each item carries an explicit status. **Nothing labelled CLAIM or UNVERIFIED
may be implemented.**

## B-I. Gate-1 ownership — audit complete, main-session verification done

### The headline, and it inverts the pivot's expectation for this half

> **VERIFIED: there is no GATE1-OWNED family in `tests/unit/agent/`.
> Zero functions move to Gate 1.**

Not "few". None that survived inspection. The audit's own framing — that
"drives an LLM-powered node with a stub" predicts Gate-1 overlap — measured a
hit rate of approximately zero against the bodies. In every family read, the
stub is a **fixture that makes deterministic repository logic reachable**, not
a stand-in for model behaviour.

### The three structural facts, each verified against source

| # | claim | status | evidence |
|---|---|---|---|
| 1 | CI runs the unit suite and nothing else | **VERIFIED** | `.github/workflows/ci.yml:61` — `uv run pytest tests/unit/ -m "not real_run" -q`. The job is ruff → ruff format → pyright → pytest, and no gate step exists |
| 2 | Gate 1 is operator-approved and per-spend | **VERIFIED** | `docs/gates/gate_testing_standard.md:148` — "**Needs user approval**: yes (real LLM cost)." CLAUDE.md records Gate 1 NOT REQUIRED for PR #217 and for the frozen 07c disposition |
| 3 | Gate 1 constructs the REAL bridge, so it cannot observe the stub | **VERIFIED** | `scripts/checkpoint_l_gate1.py:239` — `bridge_factory=LLMBridge` |

**The consequence is decisive.** Moving a behaviour Unit → Gate 1 moves it from
*every push* to *sometimes, if the operator approves the spend*. That is not a
lateral transfer of ownership; it is a reduction in verification frequency from
"always" to "occasionally". The bar for any such reassignment is therefore far
higher than "there is conceptual overlap", and nothing in this scope cleared it.

### Three findings that make the negative result *structural*, not incidental

1. **Gate 1 cannot reach the retry and self-correction branches — VERIFIED by
   construction.** `TestSelfCorrection` and the proposer/segmentation retries
   drive `bridge.generate.side_effect = [bad, good]`. Those paths are reachable
   *only when generation fails*. A real model on Gate 1 usually succeeds on the
   first attempt, so Gate 1 exercises the happy path and **silently skips the
   branch**. The stub is the only instrument that reaches this code.
2. **Gate 1 would actively MISATTRIBUTE a retry regression — VERIFIED.**
   `docs/gates/gate_testing_standard.md:434` instructs the operator: "If all
   proposals fail validation → **LLM quality issue, not a feature bug**." So a
   genuine regression in the retry logic surfaces on Gate 1 as advice to check
   the LLM config. This is the single strongest argument in the audit against
   moving retry behaviour, and it is written into the Gate standard itself.
3. **The response-salvage layer exists *because* real models are
   non-deterministic.** A Gate run either misses the shape (green, proves
   nothing) or hits it and dies three nodes downstream. Two of its cases carry
   named production incidents (`explore_novel_v4_0425`'s "Extra data: line 2
   column 1"; `deepseek-v4-pro`'s HTTP-200-with-empty-body).

### `test_stub_llm_bridge.py` — the earlier judgement CONFIRMED, and strengthened

**VERIFIED.** `StubLLMBridge` is **production code**, not test scaffolding:
`agent/llm_bridge.py:1868`, selected by the shipped CLI flag `--is_pseudo_llm`
(`sdsc_submission_scripts/run_one_iteration.py:1373`). Gate 1 cannot see stub
drift because it builds the real bridge (fact 3 above). The tests assert the
stub's canned responses **round-trip through the production schema the real
response would feed** — and one runs the stub's code through the real
`MLModelImplementor._validate_code`. A drifted stub bricks every zero-cost
smoke run.

New qualification the earlier audit did not state: **~13 of the 26 cases guard
the harness contract** (no API client constructed, no `token_usage.jsonl` rows,
markers still flow), not schema round-trip. Same verdict, different reason —
recorded so a future pass does not split the file assuming it is homogeneous.

**Four more infrastructure-guardian families found**, all of which a name-based
or grep-based pass would misread as Gate-1 overlap:
`test_stub_plugin_template_loads.py` (5) · `test_stub_constructor_compat.py` (5,
docstring names a live `TypeError`) · `test_synth_stub_model_name.py` (6) ·
`test_run_one_iteration.py::TestPseudoModeFactoryWiring` (4). Plus
`test_stub_sandbox.py` (9) for the training stub. **55 cases total, all
invisible the moment a real model is used.**

### The one genuine retirement

**VERIFIED — 1 case.**
`test_tuning_agent.py:284` `test_output_validates_against_schema` re-validates a
`HyperparamTuningOutput` against its own schema with **no assertion at all**;
`output` was built by Pydantic, so it cannot fail. The CLAUDE.md rule names it.

**REFUTED — the audit claimed this is "the only instance repo-wide".** It is
not: `grep -rn "model_validate(.*\.model_dump())" tests/unit` returns at least
five further sites (`test_planner_prompt_task_config.py:159`,
`test_health_feedback.py:310`, `test_training_diagnosis.py:186`,
`test_step07a_c3_tuner_boundary.py:221,223`). Those are **not** automatically
the same defect — several feed a dump into a *different* schema, which is a
real transport check. **UNVERIFIED: whether any of the five is decorative.**
Next inspection: read each body and check whether an assertion follows the
validate call, and whether the source and target schemas differ.

### Phase-B Gate-1 counts

```text
Gate-1-owned Unit functions
    inspected:                  ~180 cases read in full or in body (~4.5% of 4,120)
                                + structural survey of ~20 files
    retire:                     0
    retain as deterministic seams: all of them
    justified overlap:          0 (nothing overlaps)

obsolete, retired:              1  (test_output_validates_against_schema)
Unit→Unit consolidation available: 16 firm (validator + implementor flat clusters)
```

**Coverage limit, stated honestly:** `tune_ml_hyperparam_agent/` is 1,225 cases
(30 % of the scope) and was surveyed structurally, not read. Its classification
is **UNVERIFIED extrapolation**, not a finding. Next inspection if it matters:
read the ~1,000 bodies, or accept the extrapolation explicitly.

### What this means for the pivot

The pivot's premise — that Unit/Gate overlap is the main source of bloat — is
**not supported on the Gate-1 side**. The honest report is that this half of
the repository is already correctly layered, and the reason is structural: with
CI running unit-only and Gate 1 waived by default, there is nowhere for a
behaviour to move *to*.

**Open operator question raised by the audit and worth answering:** *is Gate 1
permitted to become a standing obligation?* Every reassignment argument in this
space collapses on Gate 1 being waived by default. If Gate 1 were required at
each PR's final head, a small number of reassignments would become arguable.
Under current policy, none are.


## B-II. Gate-2 ownership — audit complete, main-session verification partial

Scope collected: `tests/unit/core` + `execute_tools` + `workflows` = 3,843 cases,
plus the `evaluate_vram_skill` and tuner families reached by the grep.

### The boundary is already small and deliberate — VERIFIED

`tests/unit/conftest.py:44-89` refuses `train_engine_sandbox.py`,
`inference_single.py`, `denoising_score_single.py` and `preflight_worker_main`
from any unit test unless it carries `@pytest.mark.allow_real_subprocess`.
**Exactly 8 marked sites exist in the whole unit suite.** That guard is why this
audit is tractable at all, and it is the correct list to start from.

### The retirements — 13 cases, but the real prize is the launches

| family | cases | → | classification | status |
|---|---:|---:|---|---|
| `pr07c_validation_pricing::TestTheRealTrainerEmitsAValidationComponent` | 5 | 1 | **GATE2-OWNED** | VERIFIED |
| `pr07c_validation_envelope::TestTheClampInARealRun` | 5 | 1 | **GATE2-OWNED** | VERIFIED |
| `pr07c_validation_envelope::TestTheSchemaRefusesNonsense` | 5 | 1 | declaration-owned (`ge=1` at two sites) | VERIFIED |
| `step05c_c0_launch_cleanup_baseline` cleanup half | 2 | 0 | **OBSOLETE** | VERIFIED |
| `step07a_c2_transport::TestRungB07a2ValidationScopeAxis` | 1 | 0 | GATE2-OWNED | **BLOCKED — Q1** |
| **subtotal** | **18** | **≤5** | | |

**The headline is not 13 cases — it is that 12–13 of the 13 real training
subprocess launches leave the unit suite.** Those launches each build a
two-family HDF5 fixture and run 1–2 CPU epochs. Wall-clock saving is
**UNVERIFIED** (the audit was forbidden from running pytest); a plausible
8–25 s each puts it at 2–5 minutes, and it must be measured at the terminal
head rather than quoted.

**Why rows 1–2 are Gate-2-owned, in the pivot's own terms.**
`test_the_validation_evidence_reaches_the_runtime_session` asserts that after a
real training subprocess a `validation` component **exists** in the sidecar.
That is "did production cause this state to exist" — the Gate-2 half of the
reference split — run against a 3-file synthetic fixture on CPU with
`--data_dir` monkeypatched in. **A real subprocess, but no real data, no GPU,
and a watchdog whose deadline never fires: the lifecycle is a costume.**

Two of the removals are *strictly dominated* rather than merely relocated, and
that matters because it means no coverage moves anywhere:
`test_a_stabilised_pass_lands_a_measurement_backed_prediction` is dominated by
`test_pr07c_validation_persistence_timing.py:203-205` (same source assertions
**plus** the timing), and `test_the_training_actual_still_excludes_validation` —
the differential I built in Wave 5a, at two real children — is dominated by
`test_step07a_c1_validation_pass.py:410-462`, which injects a `_validation_pass`
reporting 100 s and asserts `-300.0 <= by_phase["training"] < -290.0`. Deeply
negative is **impossible** unless the subtraction happens: an unfalsifiable
proof, in-process, with no anti-vacuity ratio needed. **My Wave-5a redesign was
correct but sited in the more expensive of two places.** Recorded as a finding
against my own work.

**`step05c_c0` cleanup half — VERIFIED obsolete on two independent grounds.**
Its docstring cites the tuner at `:5540-5542`; that file is **1,490 lines**
after the 07b C7 decomposition. And the test defines the glob as a test
constant and runs `glob.glob` on it — **no production code is called**, so it
tests CPython's `fnmatch`. Superseded by
`test_step05c_c1_deliverable_spec.py:84-127`, which asserts the identical match
and survivor sets **through the production accessors**. The same file's three
argv goldens are sound and stay (→ Q4).

### Counter-weights — all five CONFIRMED, none refuted

`probe_hard_timeout` (40, and `:124-130` asks the **kernel** via `killpg`) ·
`TestKillTree` (5) · the VRAM preflight workers (100, `SIG_IGN` on SIGTERM,
64 MiB allocations) · `generated_model_transport_chain` (6, separate
interpreter with a scrubbed env, contamination control shipped) · the
process-group kill suites.

**One refinement worth more than the counter-weight it corrects.** There are
**four** launch sites, not three (`isolated_probe.py:486` is the fourth), and
`gpu_measurement_runner` + `isolated_probe` **share** primitives via
`core/runtime_control/process_group.py` — so three primitive copies. But the
conclusion holds for a *better* reason: the four **supervision loops** are
genuinely different code with different bound sources and different evidence
records (`kill_info` dict · `ProbeTerminationRecord` · `ProcessEvidence` ·
`HostMemoryEvidence`). Merging the suites would leave three supervision loops
unguarded.

### A FOURTH instance of the self-reported-value anti-pattern — VERIFIED

Found the day after the guardrail for it was built.

```python
# tests/unit/core/test_gpu_measurement_runner.py:301
assert run.process.orphans_remaining is False
```

`core/runtime_control/gpu_measurement_runner.py:423` sets
`orphans_remaining=process_group_alive(pgid)` — **the value is produced by the
code under test.** Delete the call, hardcode `False`, and the assertion stays
green. Character-for-character the defect corrected at `test_watchdog.py:53`.

Compounding it: the fake worker at `:280` is `journal(...); time.sleep(60)` and
spawns **no children**, so the group is trivially dead and the assertion is
doubly empty.

**It is not caught by the new guardrail** — `test_no_self_referential_expectations.py:27-31`
states it detects only the `model_fields[...]` shape and that the
self-reported-value form remains a review-time rule. Three instances justified
building the guard; this is a fourth, one day later. → **Q3**.

**Fix (not applied — pending the Q3 ruling):** read the pgid from the worker and
call `os.killpg(pgid, 0)` from the test as `test_probe_hard_timeout.py:126-130`
does, **and** give the worker a grandchild, or the assertion means nothing
either way.

### Gate-2 assertion lines the retirements REQUIRE

Coverage evaporates unless these land first. Hook:
`gate_testing_standard.md:294` PASS criterion 9. Eleven lines are specified in
the audit; the load-bearing ones:

* the sidecar carries a `validation` component with `unit_count` = rows × epochs
  **computed from the launch config, not read back**;
* `components.training.actual_seconds` did not absorb validation **on a real
  run**;
* with the watchdog ON and real validation cost exceeding the pre-07c
  training-only deadline, **the attempt completes** — the counterfactual-
  discriminative line, and the only place the whole 07c fix is actually proved;
* after a real kill, no file matching the trainer's output set survives, **the
  set enumerated by observing the trainer, not read from
  `sandbox_executor.py:1499-1509`** — taking it from the cleanup loop
  reproduces the closed loop the line exists to open;
* `os.killpg(<attempt pgid>, 0)` raises `ProcessLookupError`, asked of the
  kernel rather than read from `kill_info`.

### Phase-B Gate-2 counts

```text
Gate-2-owned Unit functions
    inspected:                     ~15 families body-read; ~25 docstring-only
    retire:                        13 cases / 12 functions   (VERIFIED)
    retain as deterministic seams: 2 rewritten in-process
    justified overlap:             4 cases (step06_c0 two-route equality)

obsolete, retired:                 2  (the cleanup-glob pair)
real training children removed:    12 of 13   (13th blocked on Q1)
```

**PROVISIONAL, not acted on:** `rt2b/c/d` (26 cases) assert *ordering of
persistence* in-process, which is adjacent to "sidecar visibility timing" on the
Gate-2 list. Docstrings argue they are legitimate Unit; bodies not read. If they
and the six header-only stability/measurement families (~220 cases) contain the
same pattern, the retirement could grow to **13–60 cases**. **UNVERIFIED — next
inspection: read `test_rt2b_streaming_preamble.py` bodies and decide whether
in-process persistence ordering is Unit's or Gate 2's** (→ Q2).

### New operator questions from B-II

* **Q1** — `TestRungB07a2ValidationScopeAxis` is registered contrast rung
  **B-07a-2** in the frozen 07a ledger. Retiring a rung is a design-ledger
  amendment. Does the obligation survive as a Gate-2 assertion line, or does it
  need an executable unit rung?
* **Q2** — is in-process persistence *ordering* Unit's, or does "sidecar
  visibility timing" cover it? The 07c defect was timing against a real wall
  clock, which `rt2b/c/d` do not simulate.
* **Q3** — a fourth self-reported-value instance appeared one day after the
  guardrail. Does that change the ruling that the tautology and
  self-reported-value forms stay review-time rules?
* **Q4** — delete the two obsolete cleanup cases in place, or is a C0 baseline
  capture a frozen artifact that must be retired as a unit?

## B-III. Selective CI (Phase C) — audit STILL RUNNING at checkpoint time

No findings recorded. Status: **UNVERIFIED / not received.**


## B-III / PHASE C — Selective CI, audit complete, verification partial

### Current CI reality — VERIFIED

One workflow, `.github/workflows/ci.yml`, 62 lines, single job. Triggers: push
to `master`, PR targeting `master`. **No `merge_group`, no `schedule`, no
`workflow_dispatch`.** Steps: checkout → uv → sync → `ruff check .` →
`ruff format --check .` → `pyright` → `pytest tests/unit/ -m "not real_run" -q`.
Recorded timings (`ci.yml:19-32`, master run 31857482569):
`install 47s · ruff 1s · pyright 2m17s · pytest 10m28s → 13m38s`.

**Nothing scopes anything today**, and `tests/integration/` (328 cases) is run
by nobody automatically.

### A finding that reaches beyond CI — VERIFIED, and it touches a binding rule

`ci.yml:57` labels the step **"pyright (strict, blocking)"**.
`pyrightconfig.json:28` is `"typeCheckingMode": "basic"`, and the string
`strict` appears **nowhere** in `pyrightconfig.json` or `pyproject.toml`
(verified: grep returns nothing).

This matters past the label. CLAUDE.md justifies the binding
responsibility-decomposition rule with pyright's **strict** complexity
ceiling — *"258 branch nodes passed, 259 failed… past that limit strict mode
does not degrade, it abandons the whole function"*. Under `basic` that
justification does not hold as written. **Flagged, not fixed — this is an
operator-level question about a frozen architectural rule, not a test-pruning
decision.**

Also verified: pyright **excludes `tests/`** and covers ten production roots
whole-repo, so cross-module inference makes it not safely file-scopable. Its
137 s is a **fixed floor**.

### The map — derived from imports, not names

2,211 test→repo import edges from AST over 1,064 files, 0 parse failures, plus
a second edge type for literal path references.

**The headline: directory names lie.** The strongest single case —
**the tuner node has no `tests/unit/nodes/ml_hyperparameter_tune_agent/`
directory at all.** Its 1,225-case suite lives at
`tests/unit/agent/tune_ml_hyperparam_agent/`, an old name for a renamed node;
`tests/unit/nodes/` holds 30 cases and is *not* its owner. Likewise 53 modules
under `unit/agent` import `execute_tools/*`, and 10 import
`core/runtime_control`. A filename heuristic would be wrong in exactly the
places that matter most.

Only **5 unit modules (20 cases)** have no edge of either kind, and all five are
whole-tree scanners — a clean always-run set, not a coverage hole.

### What the mechanism cannot see — six categories, stated

Directory-scoped text reads through a **non-constant** root
(`tests/helpers/tuner_source.py:32` — 31 modules / 838 cases with no derivable
edge) · runtime registry/plugin dispatch · subprocess paths built from
non-constants · conftest-level imports · `importlib` with computed names ·
deliberate package-prefix over-approximation.

### Cost/benefit — the honest part

Modelled against the **seven most recent real merged PRs**, calibrated to
reproduce the 951 s reference within 2 s:

| PR | selected | saving |
|---|---:|---:|
| #220 guardrail fix | 1.4 % | **76 %** |
| #214 PR0 examples | 3.3 % | 75 % |
| #217 correction | 18.7 % | 63 % |
| #218 llm timeout | 35.1 % | 48 % |
| #216 07b | 53.4 % | 33 % |
| #215 07a | 62.3 % | 27 % |
| #219 07c | 80.0 % | **15 %** |

**Median ≈ 48 %, bimodal — and smallest exactly where it is most wanted.** The
fixed floor is 185 s (23 % of 818 s) and selection cannot touch it. Hub fan-out
is real: `execute_tools/dataset_config.py` alone reaches 59 % of the suite at
depth 1. Depth-2 buys almost nothing over depth-1; depth-0 halves selection but
is unsound.

### The audit's own recommendation, which I am recording rather than overriding

> Leverage order: **(1)** `pytest -n auto` on the full suite — 9,717
> mostly-mocked cases across 534 files is a near-ideal parallel workload, cuts
> the *full* suite, benefits every tier, and carries none of the selection risk;
> **(2)** split the one `quality` job into parallel `lint` / `type` / `test`,
> removing 138 s from the critical path immediately; **(3)** selection.
> **(1) and (2) may make (3) unnecessary** — worth measuring before building a
> manifest the repo must then keep honest forever.

That is a material argument against the Phase-C brief as written, and it is the
kind of thing this ledger exists to surface rather than smooth over. It does not
contradict the operator's requirement — a fail-closed selective model remains
designable, and the design is recorded below — but the ordering question is
genuinely open. → **Q5**.

### The design, if selection proceeds

**Both** a derived model and a checked-in manifest; the manifest holds only what
the AST cannot derive (hubs → full suite · the always-on block ·
directory-scan declarations · helper→production declarations · Gate ownership ·
extension routing). Location `tools/ci_selection/`, never imported by
production, matching the `tools/example_packs/` precedent.

**Fail-safe rules, executable:** no inbound edge and no manifest rule → full
suite · resolver raises, times out, or selects 0 for a non-empty diff → full
suite · a diff touching the selector, either root `conftest.py`,
`pyproject.toml`, `pyrightconfig.json`, `uv.lock` or `.github/workflows/**` →
full suite · a declared hub → full suite · ruff and pyright stay whole-repo,
always.

**Three honesty tests, each naming a defect only it catches**, all inside the
always-on block so they cannot be selected away: every unit module is reachable
by some changed-path input · every manifest path resolves in the checkout · a
**mutation oracle** over (changed file → known-failing test) pairs harvested
from merged fix commits — the only one of the three that catches a
wrong-but-consistent model.

**Rollout:** observe-only report → land the honesty tests → shadow ~15 PRs →
flip PR CI selective **and add `merge_group:` so the full suite is MOVED, not
weakened** → add `schedule:` for full unit + integration → Gate classification
as advisory output (CI must never trigger a Gate; they cost money and need
approval).

### `paths-ignore: '**.md'` would be WRONG — VERIFIED

Docs are literal test inputs. `tests/unit/guardrails/test_gate_standard_contract.py:31`
reads `docs/gates/gate_testing_standard.md` directly; ten-plus further `.md`
files under `docs/`, `examples/`, `reference_data/` and `reports/` are read by
tests. The obvious first optimisation someone will reach for would skip CI on a
change that breaks the Gate-standard contract test.

Coupling debt noted in passing: `reports/gate2_evidence_pr07c/**` — the evidence
this session preserved — is read by up to 13 tests, and `reports/` is ruff- and
pyright-excluded. Committed run evidence is now a CI input.

### Phase-C status

**Design VERIFIED in its load-bearing claims** (CI shape, pyright mode, the
tuner directory mismatch, docs-as-inputs). **Timings UNVERIFIED** — modelled,
not measured; the audit was forbidden from running pytest. **Nothing
implemented.** → Q5 decides whether it should be.

* **Q5** — implement selection now, or first measure `pytest -n auto` and the
  lint/type/test job split, which may deliver more for one line of YAML and no
  permanent manifest obligation?
* **Q6** — `ci.yml:57` claims pyright strict; the config is basic, and CLAUDE.md
  cites the strict complexity ceiling as the justification for a binding
  architectural rule. Fix the label, raise the mode, or amend the rule's stated
  rationale?


---

## Wave B-1 — Verified Gate-2 ownership retirements + the fourth anti-pattern

Only VERIFIED items. Q1–Q4 resolved by **conservative retention** rather than
escalation — none of them blocked progress.

### Before → After
9,717 → **9,708** cases · 8,173 → **8,167** functions · 534 files
**(−9 / −6 / 0)**, and **4 of the 6 real training subprocess launches** removed
from `test_pr07c_validation_pricing.py` (6 → 2).

### Removed — strictly DOMINATED, so no coverage moves anywhere

| removed | dominator, verified by reading both |
|---|---|
| `pricing::test_the_training_actual_still_excludes_validation` (2 launches) | `test_step07a_c1_validation_pass.py:410-462` injects a `_validation_pass` reporting 100 s × 3 while real work is milliseconds, then asserts `-300.0 <= by_phase["training"] < -290.0` — **deeply negative is impossible unless the subtraction happens**. In-process, no second subprocess, no anti-vacuity ratio, and it pins `by_phase["validation"] == approx(300.0)` beside it |
| `pricing::test_a_stabilised_pass_lands_a_measurement_backed_prediction` (1) | `persistence_timing.py:203-204` asserts the same `source == "real_validation_verification"` **and** `in MEASUREMENT_BACKED_SOURCES`, plus the timing |
| `pricing::test_the_first_measured_batch_is_counted_exactly_once` (1) | `persistence_timing.py:224-231` asserts the identical `unit_count × ms_per_unit × safety_factor` exactness at `rel=1e-9` |

**The first row retires my own Wave-5a work, and that is the correct outcome.**
The redesign fixed the right property — the tautology was real — but sited it in
the more expensive of two places, needing two real subprocesses and a
`validation_total > 0.4 * without` guard whose own comment admitted it could
become unfalsifiable. The in-process version is strictly stronger and already
existed. Recorded as a finding against this session's work, not smoothed over.

### Removed — OBSOLETE (Q4: deleted in place, argv goldens kept)

`step05c_c0::test_c0_tuner_cleanup_glob_match_and_survivor_sets` and
`::test_c0_sandbox_watchdog_cleanup_glob_match_and_survivor_sets`. **Verified**
self-contained: both define the glob as a **test constant** and run
`glob.glob` — no production code is called, so they test CPython's `fnmatch`.
Their docstrings cite the tuner at `:5540-5542`; that file is **1,490 lines**
after the 07b C7 decomposition. Superseded by
`test_step05c_c1_deliverable_spec.py:84-127`, which asserts the identical match
and survivor sets **through the production accessors**. The same file's three
argv goldens are sound and stay — Q4 answered by taking the smaller, reversible
action.

### Consolidated — `TestTheSchemaRefusesNonsense` 5 → 1

Five parametrized `ValidationError` cases across two schemas, both declaring
`ge=1` (`session.py:238`, `hyperparam_tuning.py:1944`). Replaced by the
invariant a declaration **cannot** enforce: that two independently-edited
schemas keep the **same** bound. If one drifted to `ge=0` the other would still
refuse, and the disagreement would surface as a confusing startup error rather
than a caught one.

### Repaired — the FOURTH self-reported-value instance (Q3)

`test_gpu_measurement_runner.py:301` asserted `orphans_remaining`, produced by
`gpu_measurement_runner.py:423`. Now the worker writes its own pgid and the test
asks the **kernel** (`os.killpg(pgid, 0)` → `ProcessLookupError`), with the
runner's own report kept beside it rather than as the only oracle.

**Compounding defect also fixed:** the worker was `journal(...); sleep(60)` and
spawned **nothing**, so the process group was trivially dead and the assertion
was doubly empty. It now spawns a real grandchild.

**Honest limit, same as `test_watchdog.py:53`.** The "delete the probe" mutation
still passes — correctly, because the kill genuinely leaves no survivors. The
isolating mutation is "leave a real orphan", which **hangs rather than fails**
(the parent blocks on a pipe the orphan holds open). The improvement rests on
the CLAUDE.md rule and parity with `test_probe_hard_timeout.py:126-130`, not on
a mutation proof. Stated, not claimed.

### Q1–Q4 dispositions — resolved without escalation

* **Q1** — `TestRungB07a2ValidationScopeAxis` is frozen contrast rung B-07a-2.
  Retiring it amends a frozen design ledger → **RETAINED**, deferred.
* **Q2** — `rt2b/c/d` need a body read, not a decision → **RETAINED**, deferred,
  next inspection named.
* **Q3** — repaired above; the guardrail's scope is unchanged, and whether the
  self-reported-value form should become mechanically detectable stays an
  operator question with a **fourth** data point now attached.
* **Q4** — answered by the smaller action.

### NOT removed, and why

`pricing::test_the_validation_evidence_reaches_the_runtime_session` and all of
`envelope::TestTheClampInARealRun` are **GATE2-OWNED relocations**, not
dominated. Their coverage does not exist anywhere else, so removing them before
the eleven Gate-2 assertion lines land would delete coverage rather than move
it. **Conservative retention applies.**

### Validation
141 passed across the seven affected files, rc=0. Ruff clean over
`tests/unit/core/` and `tests/unit/execute_tools/`. Production byte-restored
after the mutation run (`git diff --stat core/` empty).

### Disposition
Inside the frozen rulings. **Continue.**

---

## Wave B-2 — The Unit half of the producer → provider join

### Before → After
9,708 → **9,709** cases · 8,167 → **8,168** functions · 534 files **(+1 / +1 / 0)**

### The split, applied

```text
Unit    given a valid production-SHAPED sidecar, the provider parses and
        uses it correctly                                        <- ADDED here
Gate 2  the real runtime actually produces that sidecar at the required
        lifecycle moment                                         <- stays there
```

### The gap it closes — and it is not the one originally written down

The Phase-1 finding was "no test feeds a real subprocess's sidecar into the real
provider". Under the ownership model that framing is wrong: the *real
subprocess* half is Gate 2's by definition. What remains for Unit is narrower
and had a genuine hole.

**Every other test in the file builds its sidecar with `_write_sidecar`, whose
payload carries two top-level keys. A real subprocess writes sixteen** —
`admission`, `calibration_context`, `hardware`, `historical_prior`,
`prior_agreement`, `runtime_policy`, `software`, `storage`, `total`,
`watchdog_status` and the rest. So the provider had only ever been proven
against a strict **subset** of the document it reads in production, and a reader
that tripped over a populated sibling key would have passed every existing case.

The new case populates every field the fixture can, and carries an anti-vacuity
assertion naming the exact set it does **not** exercise — so a schema that grows
a top-level field fails here rather than silently leaving the provider unproven
against it.

### It found something immediately
`RuntimeObservation.schema_version` is an **int**, not a version string. The
first draft used `"1.0.0"` and `model_validate` refused. Minor, but it is the
kind of thing a two-key fixture never surfaces.

### Validation
`test_pr07c_validation_pricing.py` **24 passed**. Ruff clean.

### Disposition
Q7 additions now complete. **Continue to Phase C.**

---

## PHASE C — DISPOSITION: designed, verified, deliberately NOT implemented

### The audit's central recommendation rests on a premise that is false as stated

It argued: *"`pytest -n auto` … plausibly delivers more for one line of YAML"*,
and put selection third behind it.

**VERIFIED — `pytest-xdist` is NOT installed.** `import xdist` raises
`ModuleNotFoundError`; no `-n` or xdist reference exists in `pyproject.toml`.
So `-n auto` is not one line of YAML. It is: a dev-dependency addition, a
`uv.lock` change, and — the part nobody has costed — **proving that 9,709 tests
are parallel-safe** in a suite that mutates global registries
(`MODEL_REGISTRY`, `PLUGIN_CONFIG_REGISTRY`), binds dataset profiles through
**ContextVars**, spawns real subprocesses, and carries autouse fixtures. The
machine has 24 cores, so the upside is real; the safety work is unquantified and
nobody has done it.

This does not refute the recommendation — parallelism may still beat selection.
It refutes the *cost* half of the comparison, which is what made it look
obviously prior. **Q5's premise is corrected, and the question stands.**

### Why the selector is not being built in this PR

Not context exhaustion, and not deference — a judgement about risk placement:

1. **The audit that designed it argues it may be unnecessary.** Building a
   mechanism whose own designer ranks it third, before the two cheaper options
   have been *measured*, inverts the ordering the evidence supports.
2. **A wrong selector fails OPEN into green.** This is the one artifact in the
   PR whose failure mode is a confident false pass — the exact class this whole
   exercise exists to eliminate. It earns its keep only with the shadow period
   (~15 PRs) and the mutation oracle, neither of which fits inside this PR.
3. **The measured payoff is worst where it is most wanted** — 15 % on the
   feature PRs that touch `runtime_control` + `execute_tools` + the tuner
   together, against a 185 s floor selection cannot touch.
4. **The design is complete and recorded** (B-III): fail-closed rules, the
   always-on block, three honesty tests including the mutation oracle, and a
   six-step rollout. Implementation is a separable follow-up, which is exactly
   what "where safely separable" permits.

### What Phase C delivers in this PR

An **ownership model in prose that is already source-verified** — the
import-derived map, the six categories the AST cannot see, per-area Gate
requirements, and the hard cases. That is the durable part; a resolver built on
top of it is mechanical by comparison.

The two findings from this phase that outlive whatever Q5 decides:

* **`paths-ignore: '**.md'` would be wrong** (VERIFIED) —
  `test_gate_standard_contract.py:31` reads the Gate standard as a test input.
  This is the first optimisation anyone reaches for.
* **`ci.yml:57` claims pyright *strict*; the config is *basic*** (VERIFIED),
  and CLAUDE.md cites the strict complexity ceiling to justify a binding
  architectural rule → **Q6**, out of scope here and not to be lost.

### Recommended next step on Q5, in order

1. Add `pytest-xdist`, run the full suite `-n auto`, and **measure**. If tests
   are not parallel-safe, that surfaces immediately and cheaply.
2. Split the single `quality` job into parallel `lint` / `type` / `test` —
   removes 138 s from the critical path with no test-selection risk at all.
3. Only then decide whether the residual justifies a manifest the repo must
   keep honest forever.


---

## Wave B-3 (B1) — Same-authority micro-test consolidation

### Before → After
9,709 → **9,697** cases · 8,168 → **8,156** functions · 534 files
**(−12 / −12 / 0)** — and, unlike Wave 3b, **cases and functions move together
1:1**, because these are separate functions, not parametrized cells. This is the
shape the primary metric is measured in.

### The clusters, each verified by reading the bodies

| cluster | fn | → | why the old boundary had no independent value |
|---|---:|---:|---|
| `test_validator_agent.py::TestMLCodeValidatorAgentRun` all-pass | 4 | 1 | four functions executing the **identical** `agent.run(make_input(tmp_path))` under the same fixture, each reading a different attribute off the same output. One claim, four full agent runs |
| `test_validator_agent.py::TestFilePersistence` | 5 | 2 | four re-ran the agent to read a different key out of the same JSON. `test_workspace_created_if_missing` is **kept separate** — it exercises `mkdir(parents=True)`, a different failure |
| `test_implementor_agent.py::TestLLMCallStructure` | 4 | 2 | three asserted one fact each about the same two bridge calls. The **ordering** case stays separate: different fixture wiring (`side_effect` recorders) and a different break |
| `test_implementor_agent.py::TestFilePersistence` | 3 | 1 | existence, parseability and one key of the same file |
| `test_stub_llm_bridge.py::test_is_subclass_of_llm_bridge` | 1 | 0 | `isinstance(stub, LLMBridge)` is enforced by `class StubLLMBridge(LLMBridge)` |
| `test_tuning_agent.py::test_output_validates_against_schema` | 1 | 0 | re-validates a Pydantic-built object against its own schema, **no assertion at all** |

### How the consolidations avoid the failure mode the operator named

Not merged into one blob: **each retained assertion keeps its own message**, so
a failure still names which half of the contract broke. Where a group is
homogeneous the test reports **every** offender rather than the first —
`failed = sorted(name for name, ok in per_check.items() if ok is not True)` and
`missing = [f for f in required if f not in data]`. That is strictly better
localisation than the four-function form gave, not worse.

One assertion was **dropped rather than carried**: `isinstance(data, dict)`
after `json.loads`. A parse failure raises, which is the same signal, and the
type of a JSON object is not a claim about the implementor.

### Independent failure classes
**Retired:** none — every retained group asserts everything its predecessors
did, minus one tautology. **Two boundaries deliberately preserved** where the
audit's arithmetic would have merged them (the `mkdir` case, the call-ordering
case).

### Validation
`ml_code_validator_agent/` 130 passed · `ml_model_implementor/` 237 passed ·
`llm_bridge/` 176 passed · `test_tuning_agent.py` 70 passed. Ruff check and
format clean on all four files. No mutation evidence required: no assertion was
weakened, and the two deletions are declaration-owned.

One lint finding fixed in passing: the first draft put the shared agent kwargs
on a class attribute, which is RUF012 (mutable class default). Moved to a module
constant.

### Disposition
Inside the frozen rulings. **Continue.**

---
---

# PHASE B — REPORT IN THE REQUIRED COUNTS SHAPE

```text
Gate-1-owned Unit functions
    inspected:                     ~180 cases read in full or body
                                   + structural survey of ~20 files
                                   (tune_ml_hyperparam_agent, 1,225 cases /
                                    30% of scope, surveyed NOT read)
    retire:                        0
    retain as deterministic seams: all of them
    justified overlap:             0        (nothing overlaps to justify)

Gate-2-owned Unit functions
    inspected:                     ~15 families body-read
                                   + ~25 docstring-only (PROVISIONAL)
    retire:                        3 functions   (all strictly DOMINATED)
    retain as deterministic seams: 2            (relocations held pending
                                                  the 11 Gate-2 lines)
    justified overlap:             4 cases      (step06_c0 two-route exact
                                                  float equality — Gate 2 has
                                                  no route (i) to compare to)

Obsolete, retired
    Gate-1 side:                   1   (schema re-validated against itself)
    Gate-2 side:                   2   (cleanup-glob pair: test constant +
                                        glob.glob, no production called)

Same-authority consolidation (B1)
    functions retired:            12   (6 clusters, bodies read)

Pure Unit
    retained:                  8,156 functions / 9,697 cases / 534 files
```

## Phase B's actual result, stated plainly

**The pivot's premise is not supported by the source.**

| hypothesis | result |
|---|---|
| Unit ↔ Gate 1 overlap is a major source of bloat | **refuted** — zero functions move, for structural reasons |
| Unit ↔ Gate 2 overlap is a major source of bloat | **largely refuted** — 3 dominated functions; the win is wall-clock, not count |
| micro-consolidation can reach ~7,000 functions | **not from verified evidence** — 12 functions from the firm list |

**What Phase B did produce, which is worth more than a count:**

* **The reason Gate-1 reassignment is impossible here, in three verified
  facts** — CI is unit-only, Gate 1 is paid and waived by default, and Gate 1
  builds the real bridge. Any future proposal to "move this to Gate 1" now has a
  documented answer.
* **Gate 1 would MISATTRIBUTE a retry regression** (`gate_testing_standard.md:434`)
  and **cannot reach** the retry branches at all. That is a permanent argument,
  not a finding about today's suite.
* **4 of 6 real training subprocess launches** removed from the unit suite's
  most expensive file, by domination rather than deletion.
* **A fourth self-reported-value instance** found and repaired, one day after
  the guardrail for that class was built — and outside what it detects by
  design.
* **A Unit-side hole nobody had named**: the watchdog deadline provider had only
  ever been proven against a 2-key sidecar where production writes 16.

## Whole-PR waterfall

```text
                         cases    functions   files
baseline  9f289d54       9,987      8,291      534
Phase A (12 commits)     9,717      8,173      534    -270 / -118 /  0
Phase B (4 waves)        9,697      8,156      534     -20 /  -17 /  0
                        ------     ------     ----
total                    9,697      8,156      534    -290 / -135 /  0
                                                     -2.9% / -1.6% /  0%
```

**This does not reach the ~7,000-function target, and no source-grounded path to
it was found.** The operator's own rule governs the outcome: *never delete
fail-closed matrices, genericity contrasts or live-mechanism regressions to
reach a number.* Every remaining candidate class was inspected and found to own
something.

**The defensible claim this PR can make is not "the suite got smaller". It is
that the suite's size is now explained**: ~2,130 cases of derived backbone, four
named additive layers, and — newly — a documented reason why Unit/Gate
reassignment yields nothing here.


---

## Q2 — ANSWERED from source, no escalation needed. `rt2b/c/d` are UNIT-OWNED.

The 26 cases left PROVISIONAL in B-II are now **VERIFIED as Unit-owned and
retained.** The deciding line is `test_rt2b_streaming_preamble.py:108`:

```python
session = RuntimeVerificationSession(str(sidecar), attempt_id="exp_adm")
# Event log exists BEFORE any verification/training happened.
assert json.load(open(sidecar))["final_status"] == "setup_started"
```

**Production's own constructor writes that file; the test only reads it.** No
fixture manufactures the state, which is the decisive Phase-B question, and the
answer is no.

### The distinction that resolves the ambiguity, stated so it generalises

"Sidecar visibility timing" is on the Gate-2 list, and `rt2b` asserts an
ordering of persistence — so the two look adjacent. They are not:

```text
Gate 2   visibility to an EXTERNAL observer running against real elapsed
         time -- the watchdog reading a file written by another process
         while a deadline counts down. A race. Unfalsifiable in-process.

Unit     the ORDER in which production's own persistence calls happen
         inside one process. Deterministic control flow: production either
         stages before verifying or it does not, and there is no clock.
```

The operator's reference split names this lane explicitly: *"Unit: provider
arithmetic; **the RuntimeSession persistence METHOD**; a narrow regression that
precisely localizes the discovered bug."* `rt2b` is that method, called
directly. `rt2c/d` share the fixture and the same shape.

**Retained: 26 cases.** The B-II uncertainty range of "13–60 cases" therefore
resolves to **13** — the upper half of that band was this family, and it stays.


---

## Wave B-4 — Portability fixes and the Q3 sub-ruling

### Before → After
9,697 cases · 8,156 functions · 534 files → **unchanged** (+1 non-test module).

Neither item is a reduction. Both are the "improve what survives" half of the
brief.

### Portability — 2 fixed, 1 REFUTED

| site | disposition |
|---|---|
| `test_step03_m6_cardinality_derivation.py:184` | **FIXED.** `pathlib.Path("ml_models/models_sandbox.py")` was cwd-relative; now derived from `__file__` |
| `test_c12b_legacy_fidelity.py:25` | **FIXED.** `LEGACY_ROOT` now reads `SIDERIUS_LEGACY_TIDMAD_ROOT`, defaulting to the documented lilab path, and the skip reason names the variable |
| `test_step04b_task_description_single_source.py:277` | **REFUTED — not a defect.** The audit flagged `Path("configs/task_config.yaml").resolve()` as cwd-relative. It sits **inside a `monkeypatch.chdir(tmp_path)` block** and the line above says why: `load_task_config()` resolves cwd-relative, so the test is deliberately asserting that resolution lands on the temp config. Fixing it would have deleted the property |

**Portability proof, executed rather than argued.** Running
`test_step03_m6_cardinality_derivation.py` from `/tmp`:

```text
before the fix   FileNotFoundError: 'ml_models/models_sandbox.py'   1 failed, 30 passed
after  the fix                                                           31 passed
```

That is the check CLAUDE.md's portability section asks for — a different
absolute path, proving the test reads the checkout it claims to.

### Q3 sub-ruling — the maturity vocabulary now lives in ONE place

New non-test module `tests/unit/examples/maturity_vocabulary.py`. Each Step-07
PR had added its own prose pins naming its own PR id against the same two
`STATUS.md` files; 07a's and 07b's coexisted, and **at D14 every one of those
strings changes together.**

**Deliberately NOT a derived claim.** The operator's constraint was
`the authority being checked != the source generating the expectation`. A
version that read the maturity row and asserted it matched itself would be the
self-referential shape this PR has now found **four** times. So the
expectations stay hardcoded; what is shared is only *where they are written*.
The authority remains the pack's own `STATUS.md` / `README.md` on disk.

**Proven, not asserted:** changing `DEFERRAL_TOKEN` from `"D14"` to `"D15"` in
that one module turns **3 cases across both test modules** red. One edit
reaches every pin, which is exactly what the sub-ruling asked for.

### Validation
`tests/unit/examples/` 80 passed · `test_step03_m6` 31 passed (and 31 from
`/tmp`) · `test_c12b_legacy_fidelity` skips cleanly. Ruff check and format clean
across `tests/unit/examples/`, `tests/unit/ml_models/`, `tests/unit/scripts/`.

### Disposition
Q3 sub-ruling closed. **Continue.**

---

## Wave C-1 — The selection model, BUILT (not wired)

### Before → After
9,697 → **9,711** cases · 8,156 → **8,166** functions · 534 → **535** files
**(+14 / +10 / +1)**

### I over-refused earlier, and this corrects it

The Phase-C disposition above argued against building the selector because *"a
wrong selector fails OPEN into green"*. That objection is real — **but it only
bites when CI actually selects.** Building the model and its honesty tests while
CI continues to run the entire suite has **zero** fail-open risk: nothing can be
skipped, because nothing consumes the model yet. That is precisely the "where
safely separable" the ruling authorised, and refusing it was the wrong call.

What is built: `tools/ci_selection/{resolver,manifest}.py` (never imported by
production, matching `tools/example_packs/`) and
`tests/unit/tools/ci_selection/`. What is **not** built: any change to
`.github/workflows/`. Flipping PR CI to consume this stays a separate decision
(Q5), now with the model checked in and proven first — the only safe order.

### Fail-closed, demonstrated

```text
[]                                        -> 0 modules      (empty diff only)
agent/schemas/hyperparam_tuning.py        -> FULL SUITE     (declared hub)
tools/ci_selection/resolver.py            -> FULL SUITE     (the selector itself)
tests/unit/conftest.py                    -> FULL SUITE     (autouse, whole suite)
core/does_not_exist.py                    -> FULL SUITE     (unmapped: fail closed)
docs/gates/gate_testing_standard.md       -> 14 modules     (docs are INPUTS)
nodes/ml_hyperparameter_tune_agent/policy.py -> 57 modules + "gate2" advisory
```

There is no code path returning an empty selection for a non-empty diff.

### The honesty tests found two real blind spots — in my own resolver

This is the part worth reading. Both were found by the tests, not by review.

1. **The mutation oracle caught an AST-invisible dependency.**
   `test_step07b_c2_order_consumers.py` reaches the tuner through `importlib`
   with a computed name (`:36`). So a change to
   `nodes/ml_hyperparameter_tune_agent/policy.py` would **not** have selected
   the suite guarding its MetricOrder consumers. Reachability and freshness both
   passed while this was true — which is exactly why the oracle exists and why
   the other two are insufficient.
2. **Reachability caught helper indirection.**
   `test_step00_choreography_baselines.py` reaches production only through
   `tests/helpers/step00_pseudo_iteration.py`, and `tests` was not a recorded
   package, so the module had **no edges at all** and would never have been
   selected. The resolver now records `tests.helpers.*` edges — a helper is the
   indirection that *hides* a production dependency — and each helper declares
   its production reach in the manifest.

Both are now declared, and the tests that found them would fail again if either
regressed.

### Cost, because a tool that shrinks the suite must not grow it

First run: **100 s** — `build_edges` parses ~600 files and 14 tests each
recomputed it. `lru_cache` on the pure derivation: **7.6 s**. Caught by
measuring rather than by assuming, since adding 100 s to every CI run while
claiming to shorten it would have been self-defeating.

### Validation
`tests/unit/tools/ci_selection/` **14 passed**. Ruff check and format clean.

### Still deliberately absent
No `.github/workflows/` change, no `paths-ignore`, no Gate is ever triggered by
CI (`gates_required` returns strings for a human; a test asserts the manifest
cannot call a spawner).


---

## Wave C-2 — Selective CI WIRED (Q5 = implement), Q6 deferred

### Before → After
9,711 → **9,716** cases · 8,166 → **8,171** functions · 535 files **(+5 / +5 / 0)**

### Q5 — implemented, not left as a design

```text
pull_request   changed paths -> selector -> affected suites -> targeted pytest
master         FULL UNIT SUITE
schedule       FULL UNIT SUITE  (nightly, 03:00 UTC — added; nothing ran
                                 automatically on a schedule before)
```

`.github/workflows/ci.yml` now invokes `python -m tools.ci_selection` and the
pytest step consumes its output. `workflow_dispatch` added so the full suite can
be demanded on request.

### Fail-closed at three levels, because one is not enough

| level | mechanism |
|---|---|
| **policy** | non-PR events never select. Hubs, the selector itself, both root conftests, `tests/helpers/`, `pyproject.toml`, `pyrightconfig.json`, `uv.lock` and `.github/workflows/**` all resolve to the full suite |
| **resolver** | an unmapped production path, a file with no known owner, or any exception → full suite. `__main__` catches `BaseException` deliberately: **a crash must make CI run MORE** |
| **shell** | `set -e` is deliberately **ABSENT** from the selection step. A failed base-ref fetch, a failed diff, a non-zero selector, or missing `pytest_args` each call `full` and continue. **A selector that can break the build is a selector people switch off** |

`fetch-depth: 0` added to checkout — a shallow clone makes the base diff fail,
which would fall back safely but silently disable selection on every PR.

### The safety net is MOVED, not weakened

Selection is a speed optimisation on the PR path only. master and the nightly
schedule always run everything, so a selector mistake costs at most one night
rather than becoming a permanent silent gap. `tests/integration/` (328 cases,
previously run by nobody automatically) can now be attached to the nightly tier.

### PR #221 validates itself the hard way — proven, not assumed

```text
$ git diff --name-only master...HEAD | python -m tools.ci_selection
FULL SUITE
  - tests/unit/tools/ci_selection/__init__.py: infrastructure/selector trigger
```

This PR changes the selection machinery, so it lands in its own full-suite
fallback class. That is the operator's explicit requirement, and it is enforced
by the mechanism rather than by remembering.

### Five new cases guard the wiring itself

A silent unwiring — someone "simplifying" the pytest step back to a hardcoded
`tests/unit/` — would leave CI green while the selector sat there doing
nothing. So `TestTheWorkflowActuallyConsumesTheSelector` reads `ci.yml` as an
input (the same way `test_gate_standard_contract.py` reads the Gate standard)
and asserts: the pytest step consumes `steps.selection.outputs.pytest_args` ·
non-PR events run everything · **all four shell fallbacks exist and `set -e`
does not** · `fetch-depth: 0` is present.

**Mutation proof:** replacing the pytest step with a hardcoded `tests/unit/`
turns `test_the_pytest_step_uses_the_selector_output` RED.

### Q6 — DEFERRED, and preserved rather than resolved

`ci.yml` labels the step "strict"; `pyrightconfig.json` sets `basic`; CLAUDE.md
leans on the *strict* complexity ceiling to justify a binding architectural
rule. `basic → strict` could produce a wave of real type failures; rewriting the
prose `strict → basic` could invalidate an architectural rationale. **Both are
type-safety policy, not test-pruning**, so this PR changes neither — including
leaving the misleading label alone, since correcting it would quietly pick a
side. `test_pyright_mode_is_not_touched_by_this_pr` pins `basic` so a later
change is a deliberate act.

Also closed here: the two dead lines in `manifest.py` (`REPO_ROOT` and its
`Path` import), removed in this commit rather than costing a separate CI run —
the wiring had to touch the file anyway.


---
---

# DEFERRED ISSUES FILED (operator directive, scope freeze)

Material out-of-scope findings are now GitHub issues, each self-contained enough
to act on without this conversation. Banked-debt prose is no longer sufficient.

| # | title | why deferred | #221 | D14 | Step 08 |
|---|---|---|---|---|---|
| [#222](https://github.com/Galileo-Sandbox/SIDERIUS/issues/222) | test/typing: Pyright policy is documented as strict but configured as basic | choosing the type-safety policy is a production decision, not test ownership | no | no | no |
| [#223](https://github.com/Galileo-Sandbox/SIDERIUS/issues/223) | runtime: formal-stability subsystem has only a legacy harness caller | every resolution changes production ownership | no | no | no |
| [#224](https://github.com/Galileo-Sandbox/SIDERIUS/issues/224) | launcher: V20 campaign STOP isolation is convention, not construction | making the scoping structural is launcher redesign | no | no | no |

## Q6(ii) — CLASSIFIED FROM SOURCE: (B) intentional, with a caveat

Directed to classify before filing, and the classification changed the outcome.

**Not the same mechanism as the 08:17 incident.** V19's defect was a STOP at the
**collection** root, above the per-campaign directories. In V20, `ws_root` *is*
the campaign directory — `--ws_root` defaults to
`/home/klz/Data/SIDEREIS_DATA/v20` (`v20_queue_runner.py:196`) and workspaces
are `ws_root / job.run_name` (`:51`). There is no `ws_root/<campaign_id>/`
nesting for a sibling campaign's STOP to sit above.

**The caveat, which is why it is still an issue.** `--ws_root` (`:196`) and
`--campaign_id` (`:200`) are **independent arguments with independent
defaults**, and nothing enforces that distinct campaigns get distinct roots. PR
E made V19's scoping **structural**; V20's rests on an **unenforced
convention**. Two campaigns sharing a `ws_root` would share one STOP —
the incident's consequence by a different route.

So: no safety PR forked, no behaviour changed, documented here and in #224.
This is also what keeps **Wave 4b deferred** — building the current-launcher
matrix now would bake in an assumed answer.


---
---

# PHASE B — FINAL OWNERSHIP ACCOUNTING

## Gate 1

```text
functions inspected                ~180 cases read in full or at body level,
                                   plus a structural survey of ~20 files
functions retired from Unit           0
deterministic seams retained        all inspected
justified overlaps retained           0   (nothing overlaps to justify)
obsolete functions retired            1
```

**Representative — retired (1).** `test_tuning_agent.py::test_output_validates_against_schema`: re-validated a Pydantic-built `HyperparamTuningOutput` against its own schema, **with no assertion at all**. Could not fail.

**Representative — retained as a deterministic seam.** `test_llm_bridge.py::TestGenerate` (11): markdown-fenced JSON, trailing prose, a second object after the first, non-dict first token, empty-then-retry. Two carry named production incidents (`explore_novel_v4_0425`'s `Extra data: line 2 column 1`; `deepseek-v4-pro`'s HTTP-200-with-empty-body). **The salvage layer exists *because* real models are non-deterministic**: a Gate run either misses the shape or dies three nodes downstream.

**Representative — the class that looks Gate-1-owned and is not.** `test_stub_llm_bridge.py` (26) + four sibling families (55 cases total) guard the **test infrastructure**: `StubLLMBridge` is production code (`agent/llm_bridge.py:1868`) shipped behind `--is_pseudo_llm`, and Gate 1 builds the *real* bridge (`checkpoint_l_gate1.py:239`), so it cannot see stub drift at all.

**Why zero, structurally.** CI runs unit-only (`ci.yml:61`); Gate 1 needs paid operator approval (`gate_testing_standard.md:148`) and was NOT REQUIRED for both PR #217 and 07c. Unit → Gate 1 moves a behaviour **from every push to sometimes-if-approved**. Worse, Gate 1 *cannot reach* the retry branches (only reachable when generation fails; a real model usually succeeds first attempt), and `gate_testing_standard.md:434` tells the operator to read a validation failure as *"LLM quality issue, not a feature bug"* — so Gate 1 would **misattribute** a genuine retry regression.

## Gate 2

```text
functions inspected                ~15 families body-read (main session verified
                                   5 families / 267 cases personally)
                                   + ~19 docstring-only, conservatively retained
functions retired from Unit           3   (all strictly DOMINATED, not relocated)
deterministic seams retained          2   (relocations HELD — see below)
justified overlaps retained           4 cases
obsolete functions retired            2
real training subprocesses removed  4 of 6 in the suite's most expensive file
```

**Representative — retired (3).** All dominated, so no coverage moved anywhere. The sharpest: `test_the_training_actual_still_excludes_validation` — **this session's own Wave-5a redesign**, superseded by `test_step07a_c1_validation_pass.py:410-462`, which injects a `_validation_pass` reporting 100 s × 3 and asserts `-300.0 <= training < -290.0`. Deeply negative is *impossible* unless the subtraction happens: in-process, no second subprocess, no anti-vacuity ratio. My version was correct but sited in the more expensive of two places.

**Representative — justified overlap (4).** `test_step06_c0_two_route_oracle.py`: route (i) in-process vs route (ii) through the real scoring child, asserted to **exact float equality**. Gate 2 runs route (ii) only and has no route (i) to compare against, so the cross-route equality is not expressible as a Gate assertion. The independent reason is stated in the module itself.

**Representative — deterministic replay against sealed real evidence.** `test_environment_stability.py` (43) replays `tests/fixtures/c2_lite_a20_case12_environment.json`, a **committed 166 KB artifact with a `provenance` block** captured from a real Gate. This is the honest form of the split — Gate 2 *produces* the evidence, Unit *deterministically replays* it — and is categorically unlike a unit test fabricating a sidecar and declaring the lifecycle correct.

**Representative — HELD, not retired (2).** `test_the_validation_evidence_reaches_the_runtime_session` and `TestTheClampInARealRun` are **GATE2-OWNED relocations**, not dominated. Their coverage exists nowhere else, so removing them before the eleven Gate-2 assertion lines exist would delete coverage rather than move it.

## Pure Unit

```text
functions retained                 8,171   (9,716 cases, 535 files)
```

**Representative.** Frozen numeric oracles (`s_max = 295715680.14248306`, sha256-pinned anchor maps, `LOG_BASE == 5.27` agreeing bit-for-bit across three modules) · the three refusal lanes, whose conflation cost the V19 campaign · identity/hash stability, invisible to every behavioural test by construction · the estimator declaration-vs-substitution family, carrying mutation provenance · repo-wide guardrails, whose cost is flat rather than per-file.

## The answer to the central question

> *Which existing Unit functions are actually attempting to simulate behaviour canonically owned by Gate 1 or Gate 2?*

**Measured: three, plus two held pending their Gate lines.** Not hundreds.

That is a genuine finding, not a failure to look. The suite was audited with the sharper test — *a deterministic fake of a real lifecycle can still be Gate-2-owned* — and the fakes largely are not there. Where they were, they were removed or held. Where a test is deterministic **and** owns local arithmetic, parsing, policy, contract transformation, classification, or replay against sealed real evidence, it was retained on that basis rather than on being cheap to run.

**The honest conclusion:** the earlier judgement that "Unit is testing everything and the Gates repeat it" is **not supported by this repository's source**. The layers were already close to complementary. What #221 changes is that the ownership is now written down, executable, and enforced by the CI selector rather than assumed.


---

## Phase-B verification, extended — 510 cases now personally verified

Continued while the terminal suite ran. All read-only; no classification below
rests on a sub-agent's word.

| family | cases | verdict | evidence |
|---|---:|---|---|
| `test_measurement_validity` | 48 | UNIT | zero spawn/sleep; builds `GpuAccountingSnapshot` directly. No arrival or timing property exists to own |
| `test_environment_stability` | 43 | UNIT | replays a **committed** 166 KB sealed Gate artifact with `provenance` |
| `test_formal_stability` | 41 | UNIT | zero spawn/sleep |
| `test_formal_stability_controller` | 34 | UNIT | 3 apparent hits: two are **prose in comments**, one a 10 ms sleep in a watcher loop |
| `test_gpu_measurement_{worker,phases,sampler}` | 101 | UNIT | **zero** spawn hits across all three; 29 injection points |
| `test_prephase_admission` · `test_admission` | 102 | UNIT | zero spawn, zero long sleeps |
| `test_observation_store` · `test_gpu_accounting` | 67 | UNIT | zero spawn, zero injection — pure in-process |
| `test_admission_wiring` | 22 | UNIT | zero spawn; AST placement assertions |
| `test_runtime_probe` | 30 | UNIT | one `Popen(["sleep","5"])` — **cannot be faked**: it proves `descendant_pids` finds a *real* descendant via `/proc` |
| `test_watchdog_admission_split` | 22 | UNIT | two `bash -c` runs sourcing `_chain_common.sh` and reading resolved argv. **The system under test IS a bash program**, so no in-process seam exists |

**510 cases moved from "the audit says so" to "I read it."** Roughly 12
docstring-only families remain PROVISIONAL and are conservatively retained.

The two spawn sites deserve their own note, because a spawn count alone would
have misclassified both. Neither is a lifecycle simulation: one reads `/proc`
for a genuinely-real descendant, the other exercises a shell contract that has
no non-shell form. **"Spawns a process" remains a poor predictor of Gate
ownership** — the question is always what failure class the test proves.


### Verification complete — 707 cases personally read, PROVISIONAL list closed

Final screening pass over the remaining families:

| family | cases | verdict |
|---|---:|---|
| `test_calibration_policy` · `test_calibration_read_authority` · `test_realized_vs_admitted_memory` · `test_pair_admission` · `test_b3_graded_admission` · `test_m5_resource_admission_enforcement` | 171 | UNIT — zero spawn, zero long sleeps |
| `test_gate2_policy_wiring` · `test_sandbox_executor_rt2b` · `test_sandbox_executor_rt2d` · `test_rt2b_streaming_preamble` | 26 | UNIT — the single `subprocess.run` hit is a **docstring** describing a mock (`test_sandbox_executor_rt2b.py:67`), not a spawn |

**707 of the ~1,500 Gate-2-adjacent cases are now personally read**, and the
B-II PROVISIONAL list is closed: **no family in it turned out to be a fake
Gate.** The B-II uncertainty band of "13–60 cases" resolves firmly to **13**.

Worth stating because it is the whole Phase-B result: three separate screening
heuristics — "uses a stub LLM", "spawns a subprocess", "mentions `subprocess`" —
each predicted Gate overlap and each was **wrong**. The prose hits were
comments; the spawns were `/proc` reads and shell contracts; the stubs were
making deterministic branches reachable. Ownership had to be decided by reading
what failure class each test proves, one family at a time, and doing that
produced a far smaller answer than any heuristic promised.


### The last unverified block closed — `tune_ml_hyperparam_agent/` (1,225 cases)

The Gate-1 audit surveyed this directory structurally and explicitly refused to
certify it: *"this is the largest directory (30 % of scope) and I surveyed
structure, not 1,225 bodies. I am not certifying it."* That was the single
largest UNVERIFIED extrapolation in the whole audit, so it was screened directly:

* **Zero real spawns across all 75 files.** No Gate-2 lifecycle simulation
  exists here at all.
* The `status == "completed"` assertions that would mark a bare Gate-1 arrival
  check are **not** bare — each is a guard clause immediately preceding the real
  property, e.g. `test_per_round_attempt_budget.py:340` is followed by
  `completed_rounds == 2` and `total_attempts == 4`. The subject is
  attempt-budget arithmetic; the status check is its precondition.

**Result: no Gate-owned behaviour found in the largest directory in scope.**
This is the strongest single piece of evidence for the Phase-B conclusion,
because it is the block most likely on priors to have contained fake Gates —
1,225 cases driving an LLM-powered orchestrator with a mocked bridge — and it
contains none.


---

## Wave B-5 — A flaky bound in the test this PR made load-bearing

### Found by the terminal suite, not by any targeted run

```text
FAILED test_step07a_c1_validation_pass.py::TestRuntimeAccounting::
       test_training_actual_excludes_the_recorded_validation_seconds
AssertionError: [('training', -287.34168810676783), ('validation', 300.0)]
assert -287.34168810676783 < -290.0
```

**Pre-existing, not caused by this PR** — and it matters twice over, because
this is the exact test cited in **Wave B-1** as the dominator justifying the
retirement of my own Wave-5a differential. Retiring a robust-but-expensive test
in favour of a flaky one would have been a bad trade made on my own reasoning.

### The defect

The test injects a `_validation_pass` reporting 100 s × 3, so
`training_actual = real_elapsed − 300`. The bound was:

```python
assert -300.0 <= by_phase["training"] < -290.0
```

The `< -290.0` half silently asserts **the real CPU training finishes in under
10 seconds**. It does on an idle machine. Under full-suite load it took 12.66 s
and the test failed — a **machine-speed assumption masquerading as a correctness
bound**, and precisely the "thin statistical margin" class flagged as unguarded
in Phase 1 §12.6.

### The fix, and why it loses nothing

```python
assert -300.0 < by_phase["training"] < 0.0
```

The property the test exists for is *"negative is impossible unless the 300 s
was subtracted out"* — real elapsed time is strictly positive, so a negative
actual has exactly one cause. `< 0` expresses that completely. The lower bound
stays because elapsed cannot exceed the injected total. **No host speed is
pinned.**

### Mutation proof — the corrected bound is exactly as strong

Dropping the subtraction at `train_engine_sandbox.py:1727` (target site asserted
`== 1`, caches cleared, production restored, baseline re-run):

```text
E   assert 1.9473966471850872 < 0.0
1 failed
```

The mutant produces a **positive** actual, so the new bound kills it just as
dead as the old one — while the old one additionally failed on a slow machine
and the new one cannot.

### Validation
`TestRuntimeAccounting` 2 passed; mutation RED; production byte-restored
(`git diff --stat execute_tools/` empty).

### The wider point
The full suite earned its keep here in the one way targeted runs cannot: **this
test passed in every per-wave run and in Wave B-1's own 141-case validation.**
It only failed under load, which is the condition CI and a busy developer
machine both create.


---

## Wave C-3 — Two operator corrections: docs and area-owned modules must not run everything

### The rulings

> *"the doc-only change should never trigger full suite CI, this is stupid"*
> *"dashboard is not related to any production code, there should no be full suite test"*

Both correct, and both expose the same conceptual error in my resolver:
**fail-closed applies where reachability cannot be determined — not where it
can.** For a `.md`, the literal-path map is *complete*: a doc cannot be
imported, so a path read is the only way a test reaches one, and the AST pass
finds every such read. "No edge" for a doc is therefore **knowledge, not
ignorance**. And a production module nothing imports still has an *area* whose
owning suite is known. Running 9,716 cases in either situation is noise — and
noise is what gets a selector switched off.

### The fix

Two manifest structures + one resolver branch:

* **`NON_IMPORTABLE_SUFFIXES`** (`.md`, `.txt`, `.rst`, `.csv`) — no derived
  edge means *nothing can be affected*; only the always-on guard block runs.
* **`AREA_OWNERS`** — longest-prefix map from every production area to its
  owning suites. A `.py` with no derived edge runs its area's suites. Only a
  path matching *neither* an edge, nor a non-importable suffix, nor an area is
  genuinely unmapped and runs everything.

### Behaviour, before → after

```text
docs/architecture.md      FULL SUITE  ->  13 modules (always-on guards only)
docs/gates/gate_testing_standard.md      15 modules  (unchanged — tests READ it)
dashboard/main.py         FULL SUITE  ->  15 modules (its own suite + guards)
core/<nonexistent>.py     FULL SUITE      (unchanged — genuinely unknown)
agent/schemas/… (hub)     FULL SUITE      (unchanged)
```

### The edge system caught its own tests, twice

The first drafts of the two new honesty tests **failed**: writing
`"docs/architecture.md"` as a literal inside the test made *the test file
itself* a reader of that path, so the resolver — correctly — selected it as an
owner and the "nothing reads this doc" premise became false. The paths are now
built by concatenation, with the reason documented in place. A selector whose
own tests cannot silently exempt themselves is working as designed.

### Validation
`tests/unit/tools/ci_selection/` **21 passed** (19 → 21). Freshness now also
verifies every `AREA_OWNERS` prefix and suite path resolves. Ruff clean.

## §10 REPRESENTATIVE SELECTION TABLE (required deliverable)

| area | changed path | selected | gate advisory |
|---|---|---|---|
| LLM-facing prompt | `agent/prompts.py` | 32 modules | gate1 |
| prompt template | `agent/prompt_templates/proposal/proposing_stage.md` | 29 modules | gate1 |
| schema (hub) | `agent/schemas/hyperparam_tuning.py` | **FULL SUITE** | — |
| protocol | `agent/schemas/protocols/ml_model_valid_to_ml_model_tune.py` | **FULL SUITE** | — |
| tuner node internals | `nodes/ml_hyperparameter_tune_agent/policy.py` | 60 modules | gate2 |
| runtime control | `core/runtime_control/watchdog.py` | **FULL SUITE** | gate2 |
| training engine | `execute_tools/train_engine_sandbox.py` | 43 modules | gate2 |
| scoring / numerical | `execute_tools/scoring_utils.py` | **FULL SUITE** (hub) | gate2 |
| loss math | `ml_models/loss_models_sandbox.py` | 29 modules | gate2 |
| shell launcher | `sdsc_submission_scripts/run_chain.sh` | 19 modules | gate2 |
| guardrail test | `tests/unit/guardrails/test_no_model_name_branches.py` | 13 modules | — |
| docs, read by tests | `docs/gates/gate_testing_standard.md` | 15 modules | — |
| docs, read by nothing | `docs/architecture.md` | **13 modules** | — |
| dashboard | `dashboard/main.py` | **15 modules** | — |

