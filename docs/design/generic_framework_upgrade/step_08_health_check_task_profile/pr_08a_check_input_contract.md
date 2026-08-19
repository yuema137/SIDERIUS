# PR 08a — check input contract + applicability (child design)

## 0. Status and provenance

**FROZEN — rev 2, operator authorization 2026-08-18.** Rev 1 (draft,
commit `90868774`) was reviewed by the operator ("very good") with one
required revision: per-commit detailed implementation checklists in the
operator's eight-section template, checkbox-tracked (`[ ]` → `[x]` only
with recorded evidence), followed by freeze. Rev 2 adds §4 in that form
and freezes. The open questions are ADOPTED AS PROPOSED at freeze:
**Q-08a-1** — per-check verdicts persist as a typed additive
`check_verdicts: dict[str, str] | None` field on
`PersistedHealthGateResult` (not inside the `metrics` dict);
**Q-08a-2** — a gate whose checks are ALL inapplicable takes `on_pass`
(never blocks) while persisting `execution_status="not_run"` + verdicts,
with counting surfaces reading verdicts. Any objection reopens these
BEFORE implementation, which starts only from this frozen revision.

Child of the FROZEN Step-08 parent (`step_08_health_check_task_profile.md`,
rev 3, operator ruling 2026-08-18). Source audit at master `38c8fd0c`.
This child changes NO ownership, NO YAML layout, NO prompts, NO registry
mechanics — those are 08b/08c.

Authority order: the frozen parent (esp. §4, §6.1–.2, §7, §8, §10, §12
08a) > current source (audited below) > roadmap §8.4/§8.4a >
`docs/design/pluggable_health_checks.md` (rev 6 — the docstring
contracts this PR supersedes are amended citing the parent, per parent
§4 row E).

## 1. Mandate (quoted from the frozen parent, §12 08a)

* **Goal**: "inapplicability becomes a typed verdict decided before I/O;
  checks declare their inputs as data; TIDMAD reads route through the
  Deliverable Contract byte-identically."
* **Allowed changes**: "`protocol.py`, `schemas.py` (additive verdict +
  declaration), `runner.py`/`evaluation.py` (verdict transport), the six
  checks' declarations, `_peek`/`_multi_file_peek` re-plumbing. NO YAML
  layout change, no registry/ownership change, no new checks beyond the
  minimal 8.4-C dispersion fixture-check, no prompt change."
* **Acceptance**: "six-check verdict parity on goldens; 8.4-B with the
  no-file-opened spy; 8.4-C negative control; applicability reachability
  from `evaluate_and_persist_health_gates`; Gate 2 = one bounded TIDMAD
  round (gates fire + persist through the new path). Gate 1: none."

## 2. Source audit (at `38c8fd0c`)

### 2.1 The NA=pass convention — complete production inventory

| site | form |
|---|---|
| `protocol.py:22-31` | THE contract: "a skill that finds its inputs missing should return `HealthCheckResult(passed=True, reason="<check_name>: not applicable — …")`" |
| `schemas.py:196` (`target_path_fn` doc) · `:242` (`get_target_path` doc) | "checks that need it fall back to `passed=True` with a 'not applicable' reason" (M8 §3.4) |
| `_multi_file_peek.py:252-261` | the fallback condition is precise: `not peek_file_indices and no_path_count == n_attempted and n_attempted > 0` → `passed=True, reason="not applicable — no path configured in context"` (`:28`, `:107` document it) |
| `spectral_peak_ratio.py:62` · `per_file_output_std.py:53` | `reason=f"{self.name}: not applicable — no files in context"` |
| `output_diversity.py:22,80` | routes the multi-peek NA pass through (`elif outcome.reason:` — an NA pass carries a reason) |
| `evaluation.py:173` | **the string sniff**: `… or "not applicable" in reasons → "not_run"` — persistence already reverse-engineers the honest verdict from prose |

The dishonesty is precisely located: the RUNTIME verdict says
`passed=True` (indistinguishable from health in `evaluate_gate`'s
`gate_passed = all(r.passed …)`, in eligibility inputs and in any
counting), while the PERSISTED `execution_status` already wants —
and string-matches its way to — `"not_run"`.

Important asymmetry (verdict-mapping input): with EXPLICIT
`peek_file_indices` (the production shape — the 02c group) and every
path missing/unreadable, the NA fallback does NOT trigger; aggregation
runs and `any_pass` over only-io-failed entries returns `False`
(`_apply_aggregation`, `_multi_file_peek.py:146-152`) with reason
"all N peeked file(s) failed I/O" — i.e. today that case is a FAIL that
drives `on_fail`, and under the new vocabulary it is `ERROR`
(same action, now typed).

### 2.2 The error path (already fails closed at the action level)

`runner.py:123-139` (the PR #101 Bug-B guard): an exception inside a
check → caught → `HealthCheckResult(passed=False, reason="… raised …",
metrics={"exception_type": …})` → the gate takes `on_fail`.
`evaluation.py:168-169` maps `exception_type` → `execution_status =
"error"`. So "error on a blocking check fails closed" (parent §7) is
ALREADY the action-level behavior; 08a formalizes it as a typed verdict
without changing the action.

### 2.3 The persisted vocabulary already matches the parent's shape

`evaluation.py:167`: `Literal["passed", "failed", "not_run", "error"]`.
Mapping to the parent §7 runtime vocabulary is 1:1
(`inapplicable ↔ not_run`), so the frozen record layout (parent §8)
needs NO existing-field change — the runtime verdict becomes the
DERIVATION SOURCE of a status that today is string-sniffed.
`PersistedHealthGateResult` (`schemas.py:294-369`) already carries
`check_passed: bool | None`, `gate_role`, `configured_action`,
`healthgate_mode`, `result_authority` — the additive `check_verdicts`
lands beside them (Q-08a-1).

### 2.4 The peek plumbing and its literals

`_peek.py`: hardcoded walk `timeseries/<channel>/timeseries` (`:86`),
channel names `"channel0001"`/`"channel0002"` (`:92-100`, callers).
`_multi_file_peek.py`: `peek_and_aggregate(ctx, peek_file_indices,
metric_fn, predicate, aggregation, peek_samples, channel="channel0001")`
(`:170-178` — the literal is a parameter DEFAULT), aggregation modes
`any_pass|all_pass|max|min|mean|median` (`:134-167`),
`PerFilePeekResult`/`MultiFilePeekOutcome` (`:46`, `:79`), index
resolution with order-preserving dedupe + single-file fallback
(`_resolve_indices`, `:113-131`). The Deliverable Contract already owns
exactly these facts: `DeliverableStorage.input_channel_group` /
`target_channel_group` / `storage_dtype` / `value_offset`
(`deliverable_spec.py:226-235`, defaults documented as TIDMAD's) and
`DeliverableNaming` (`:85`); regime-A derivation
`derive_tidmad_deliverable_spec(profile)` exists and is already used by
`inference_single.py:365` and `denoising_score_single.py:179`.

### 2.5 Gate/config/eligibility shapes (unchanged surfaces this PR must respect)

* `CheckRef{name, config}` · `GateConfig{id, gate_role, after_round,
  short_circuit, checks, on_pass, on_fail, reason}`
  (`config.py:47-256`). Declarations therefore live on CHECK CLASSES
  (ClassVar data), never in YAML — no layout change.
* `evaluate_gate` (`runner.py:74-154`): config-listed order,
  `short_circuit` stops at first FAILURE, `gate_passed = all(passed)`,
  action = `on_pass`/`on_fail`. Aggregation frozen by parent §7.
* Eligibility: `classify_candidate_health(…, required_gate_ids)`
  (`candidate_eligibility.py:148`), `required_blocking_gate_ids`
  (`:134`), UNKNOWN discipline (`:46`); feedback consumes
  `classify_candidate_health(record)` per record and renders
  counts + named-absence lines + failed gate names from the persisted
  dicts (`feedback.py:138-178`) — the byte-pin targets.
* `evaluation.py` also carries TIDMAD vocabulary in `_threshold`
  (`:83-105`), `_per_file_metrics` metric/unit tables (`:114-130`) and
  the persisted label `"channel0001_prefix_peek"` (`:157`). **These are
  persisted-record VALUES and family vocabulary — explicitly OUT of 08a
  scope** (ownership moves in 08b/08c; record bytes stay identical).

### 2.6 Existing test surface (parity baseline)

24 test modules under `tests/unit/execute_tools/health_checks/`
(per-check behaviour tests for all six; `test_runner.py`,
`test_campaign_evaluation.py`, `test_candidate_eligibility.py`,
`test_honest_gate_labels.py`, `test_multi_file_peek.py`, `test_peek.py`,
`test_schemas.py`, `test_context_target_path.py`,
`test_step00_health_config_baseline.py` config-baseline pin, scope +
role-consistency guards). `goldens/` holds the resolved-config golden
(`hc1_health_checks_resolved.json`); per-check VERDICT parity today
lives as fixture-expectation assertions inside the per-check tests.
Parent §8's capture-first rule therefore lands as a NEW committed
capture manifest (C1) rather than pre-existing verdict goldens.

## 3. Design

### 3.1 The verdict vocabulary (typed, additive)

`schemas.py` gains:

```python
class CheckVerdict(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    INAPPLICABLE = "inapplicable"
    ERROR = "error"
```

`HealthCheckResult` gains `verdict: CheckVerdict` with a
back-compatibility model validator so every EXISTING constructor call
keeps working and every existing outcome maps deterministically:

| today's result | derived verdict |
|---|---|
| `passed=True`, reason empty or non-NA | `PASSED` |
| `passed=True`, reason carries the production NA marker | `INAPPLICABLE` |
| `passed=False`, error-classed: `metrics.exception_type` present OR (`n_files_attempted` > 0 AND `n_files_io_failed == n_files_attempted`) | `ERROR` |
| `passed=False` otherwise (incl. partial-io with a computed failing metric) | `FAILED` |

The derivation exists ONLY as the compatibility bridge; by C4 every
production constructor passes `verdict=` explicitly and the
string-derivation branch is reachable only from legacy-shaped test
fixtures (asserted by a targeted test). `passed` KEEPS its exact
semantics ("did not fail" — it is what drives `on_pass`/`on_fail` and
`short_circuit`), so gate ACTIONS are bit-for-bit unchanged everywhere:
`INAPPLICABLE.passed is True` at the action layer (never blocks),
while honesty moves to the layers that were lying — counting,
persistence, eligibility (per parent §7: never *counts* as pass).

### 3.2 The check input declaration (data on every check)

`schemas.py` gains a frozen `CheckInputDeclaration` carrying only what
§2's audit shows the six checks actually consume (parent §6.1; no
mega-schema):

* `consumes_view: str` — the view CAPABILITY KEY (parent §6.3, opaque).
  In 08a the six declare TIDMAD-family keys (e.g.
  `tidmad.int8_prefix_peek`, `tidmad.target_comparison_peek`,
  `tidmad.file_vector`); the STANDARD capabilities ship in 08c. The
  engine never interprets the string (census).
* `required_context_inputs: tuple[str, ...]` — which
  `HealthCheckContext` fields must be present/non-empty
  (`denoised_source`, `target_source`, `file_vector`, …).
* `required_facts: tuple[FactRequirement, ...]` — declaration-vs-facts
  axes: encoding family (`int8_symbol_stream` vs `continuous_float`),
  value-scale presence, file-group structure. Each requirement names its
  axis so the inapplicable reason can name the mismatch (parent §6.2).
* `threshold_parameter_names: tuple[str, ...]` — which config keys are
  task thresholds (pure metadata in 08a; 08b consumes it for
  ownership migration).

Each of the six checks declares one as a `ClassVar` (protocol.py's
`HealthCheckSkill` gains the attribute); the protocol docstring's NA
contract (§2.1 row 1) is REPLACED, citing parent §7.

### 3.3 The applicability engine (pure, pre-I/O)

New pure function in `schemas.py` (side-effect-free canonical home, the
CB1 precedent):

```text
applicability(declaration, task_facts, ctx) ->
    Applicable | Inapplicable(reason names the mismatched axis)
```

Two pre-I/O input classes, both typed:

1. **Declaration vs task facts** — regime-A facts are derived
   presence-discriminated from `resolve_dataset_profile()` + the
   Deliverable Contract (parent §6.2; the D14 truth-table pattern):
   TIDMAD's facts say `int8_symbol_stream`, so all six are applicable
   and TIDMAD behaviour is unchanged by construction. The 8.4-B fixture
   supplies contrast facts (`continuous_float`) WITHOUT any task
   binding machinery (that is 08b) — facts arrive as an explicit
   argument with the regime-A derivation as the production default.
2. **Declared context inputs vs actual context** — e.g.
   `target_path_fn is None` at a pre-scoring gate → `inapplicable`
   naming the absent input (this replaces the M8 §3.4 in-check
   fallbacks; same outcome, decided before the check runs).

Wiring (`runner.py::evaluate_gate`): BEFORE `skill.run`, evaluate
applicability; on `Inapplicable`, append a typed
`HealthCheckResult(verdict=INAPPLICABLE, passed=True, reason=<axis>)`
WITHOUT invoking the skill (the 8.4-B spy asserts no file I/O and no
`run()` call). `short_circuit` ignores inapplicable results (it stops
only on FAILED — unchanged, since inapplicable has `passed=True`).
I/O failures DURING an applicable run stay what they are today:
classified `ERROR` (blocking → `on_fail`, the Bug-B action, unchanged)
— never retro-declared inapplicable.

### 3.4 Verdict transport (evaluation.py, eligibility, feedback)

* `_execution_status` consumes typed verdicts: `ERROR → "error"`,
  all-inapplicable (or the existing all-io-failed rule) → `"not_run"`,
  else passed/failed. **The `"not applicable" in reasons` string sniff
  is deleted.** Output values byte-identical for every existing input
  (proven by a differential test over the captured outcomes).
* `PersistedHealthGateResult` gains ONE additive optional field,
  `check_verdicts: dict[str, str] | None` (check_name → verdict) —
  Q-08a-1, adopted at freeze. Existing fields byte-identical (parent §8).
* `candidate_eligibility`: the required-set computation excludes checks
  whose round result is INAPPLICABLE; ERROR is never excluded
  (parent §7). For TIDMAD (all applicable) the required set is
  unchanged — asserted.
* `feedback.py:145-175` rendering: BYTE-STABLE for TIDMAD inputs
  (test pins the rendered lines; parent §2.4/§10 — no prompt change).

### 3.5 TIDMAD peek routed through the Deliverable Contract (C5)

`_peek.py`/`_multi_file_peek.py` stop hardcoding
`"channel0001"`/`"channel0002"`/walk literals: the channel names, the
filename construction and the storage dtype come from
`derive_tidmad_deliverable_spec(resolve_dataset_profile())`
(`DeliverableStorage.input_channel_group`/`target_channel_group`,
`DeliverableNaming`) — the SAME values, now from the owning authority.
Byte-identical reads proven two ways: (i) fixture-level — identical
arrays returned pre/post on the committed HDF5 fixtures; (ii) the
six-check parity manifest (C1) re-verified after C5. Persisted STRINGS
(e.g. `sampling_method: "channel0001_prefix_peek"`,
`evaluation.py:157`) are record values and DO NOT change in 08a.

### 3.6 The minimal 8.4-C dispersion fixture-check

One tiny generic check (`sample_dispersion_floor`, registered normally,
NOT referenced by any production YAML) whose declaration requires
`continuous_float` facts: on the SAME declared-float fixture where
8.4-B proved the int8 family inapplicable, this check FIRES, computes a
dispersion floor over the fixture samples, and CAN FAIL (the fixture
includes a constant-output case). This is the negative control that
inapplicability is a statement about ONE family, never an exemption
from health (roadmap §8.4-C verbatim). Its full-family successor is 08c
scope; if 08c's continuous family subsumes it, retirement is 08c's
disposition to argue.

## 4. Commit decomposition — detailed implementation checklists

### 4.0 Standing rules for every commit (binding during implementation)

* **Inspect before finalizing.** Each commit's first checklist item is a
  bounded read of the exact functions it edits, re-verified at the
  implementation head (this design was audited at `38c8fd0c`; the tree
  may have moved). If inspection reveals an ambiguity or a larger scope
  than this design assumes, STOP and ask the operator before changing
  the plan — never silently pick one.
* **Checkbox discipline.** `[ ]` = not done; `[x]` only after the change
  is implemented AND its evidence line below it is filled in (test
  counts + wall time, or the recorded reason a check could not run —
  never claim what was not run). **All boxes in this frozen revision are
  `[ ]` — nothing has been implemented.** This document is updated at
  every implementation/test checkpoint, not batched at the end.
* **Pytest verdicts come from the full log file** (CLAUDE.md):
  `… > /tmp/08a_<cN>.log 2>&1; rc=$?` — never a piped tail's exit code.
* **Commit boundary protocol (every commit).** Before committing: show
  the exact `git diff --stat`, the staged file list, the test evidence,
  and any deviation from this frozen design; wait for operator
  permission. No unrelated cleanup rides along; genericization-in-
  passing, if any, is its own commit.
* **Out of scope for ALL commits** (require separate evidence + operator
  approval, and are NOT in 08a): planner/prompt exposure of health
  (byte-pinned instead), production YAML/default changes, registry or
  ownership mechanics (08b), the full generic check families (08c).
* **Gate 2 is listed separately (§7) and is never launched without
  operator approval of the exact command.**
* Any commit may split into `-code`/`-docs` git commits at clean
  boundaries preserving the final split's acceptance.

---

### 4.1 C1 — verdict vocabulary + capture-first parity manifest

**Goal.** Make the four-way verdict (`passed|failed|inapplicable|error`)
a typed fact on `HealthCheckResult`, and freeze TODAY's behaviour as
committed evidence BEFORE any behavioural change exists. It is first
because every later commit's parity claim compares against this
manifest; putting capture after any behaviour change would let the new
code author its own expectations (the D14-1 lesson).

**Scope.**
* Changes: `execute_tools/health_checks/schemas.py` (add `CheckVerdict`
  StrEnum; add `verdict: CheckVerdict` to `HealthCheckResult` with the
  §3.1 back-compat derivation validator); NEW committed manifest
  `tests/unit/execute_tools/health_checks/goldens/verdict_parity_manifest_pre08a.json`
  + its generator script beside it (test-owned, stdlib-deterministic);
  NEW `tests/unit/execute_tools/health_checks/test_check_verdict.py`.
* Must NOT change: any check module, `runner.py`, `evaluation.py`,
  `protocol.py`, any YAML, any existing test file.
* Depends on: nothing.

**Implementation plan.**
- [ ] Enumerate every `HealthCheckResult(` constructor site (grep) and
      confirm all pass keyword arguments only (expected from §2.1:
      the six checks + the `runner.py:134` exception guard + the
      multi-peek NA path; verify the exact list and record it here).
      Evidence: _(pending)_
- [ ] Write the capture generator: runs the six registered checks over
      the EXISTING unit-test fixture inputs (reuse the per-check test
      fixtures; do not invent new inputs) and records
      `(check_name, passed, reason, metrics-keyset, expected-verdict)`
      per case, deterministic ordering, into the manifest.
      Evidence: _(pending — case count recorded here)_
- [ ] Generate + commit the manifest at the PRE-change tree (verify the
      working tree is clean of schema edits when generating; record the
      generation tree SHA in the manifest header).
      Evidence: _(pending)_
- [ ] Add `CheckVerdict` + additive `verdict` field + the §3.1
      derivation as a Pydantic model validator, with the io-classed rule
      exactly as §3.1 row 3; explicit `verdict=` kwarg wins over
      derivation; contradictory explicit input rejected.
      Evidence: _(pending)_

**Validation plan.**
* Unit: one test per §3.1 mapping row (passed-clean, NA-pass-with-
  reason, exception-classed, all-io-failed, partial-io-failed,
  plain-fail); explicit-`verdict=` wins over derivation; JSON
  round-trip of the new field.
* Parity: replay every manifest case through the NEW
  `HealthCheckResult`; assert `passed/reason/metrics` byte-equal to the
  manifest and `verdict` equals the manifest's expected class.
* Negative: unknown verdict string rejected (enum); `verdict=PASSED`
  with `passed=False` rejected (consistency validator).
* Backward-compat: the ENTIRE existing health-check test package green
  with ZERO edits to pre-existing test files.
* Gate: none in this commit.

**Acceptance criteria.**
- [ ] `pytest tests/unit/execute_tools/health_checks/` green; `git diff`
      shows no pre-existing test file modified.
- [ ] Manifest committed; generator re-run at the C1 head reproduces it
      byte-identically (diff empty).
- [ ] Mutation check: invert one branch of the derivation (count==1
      mutation site, caches cleared per the mutation-hygiene rules) →
      the named mapping test fails; restore → green.
- [ ] Legacy shape `HealthCheckResult(check_name=…, passed=True)`
      constructs with `verdict == PASSED`.

**Failure and edge cases.**
* Legacy-shaped construction (no `verdict=`): derived, never rejected —
  the bridge is load-bearing until C4.
* Contradictory explicit input (`verdict=PASSED, passed=False`): raise
  at construction (stop — a lying result must never persist).
* Reason-prose drift ("Not Applicable" capitalization etc.): derivation
  matches the exact production marker only (lowercase
  `"not applicable"`, as emitted at `_multi_file_peek.py:260`,
  `spectral_peak_ratio.py:62`, `per_file_output_std.py:53`); any other
  prose derives from `passed` alone — asserted, so prose drift surfaces
  as a test failure, not a silent verdict change.
* numpy scalars in `metrics`: unchanged pass-through (existing
  behaviour, no new handling).

**Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/execute_tools/health_checks/ -q > /tmp/08a_c1.log 2>&1; rc=$?; tail -20 /tmp/08a_c1.log`
      Evidence: _(pending — counts + wall time)_
- [ ] Manifest regeneration diff (must be empty).
      Evidence: _(pending)_
- [ ] Mutation check transcript (site, red test name, restoration).
      Evidence: _(pending)_

**Commit boundary.**
- [ ] Independently reviewable (one schema + tests + frozen evidence;
      zero consumer changes); no unrelated cleanup.
- [ ] Diff summary + staged file list + test evidence + deviations
      (expected: none) shown to operator; permission received before
      `git commit`.

---

### 4.2 C2 — `CheckInputDeclaration` + the pure applicability engine

**Goal.** The comparison logic — declaration × facts × context-presence
→ `Applicable | Inapplicable(axis-named reason)` — exists and is fully
tested in ISOLATION before any production path can reach it. Separate
from C3 so the wiring diff (behavioural) is reviewable apart from the
logic diff (pure).

**Scope.**
* Changes: `schemas.py` (frozen `CheckInputDeclaration`,
  `FactRequirement`, `TaskHealthFacts` carrier, `ApplicabilityVerdict`,
  pure `applicability(...)` — schemas.py is the CB1 side-effect-free
  canonical home); NEW `execute_tools/health_checks/_regime_a_facts.py`
  (derive `TaskHealthFacts` from `resolve_dataset_profile()` + the
  Deliverable Contract, presence-discriminated) — a separate private
  module rather than more mass in `schemas.py` (§2.5 god-file watch);
  NEW `tests/unit/execute_tools/health_checks/test_applicability.py`.
* Must NOT change: `runner.py`, `evaluation.py`, any check, protocol.
  The engine is deliberately UNREACHABLE from production in this
  commit — stated here, and asserted by a grep-test (removed in C3).
* Depends on: C1 (verdict vocabulary exists for the Inapplicable
  result's typed reason class).

**Implementation plan.**
- [ ] Inspect `DatasetProfile`/`ValueEncoding` (`dataset_config.py:381,
      :439`) and `derive_tidmad_deliverable_spec` +
      `DeliverableStorage` (`deliverable_spec.py:209-`,
      `evaluation_metric.py:677-`) and FIX the exact field list the
      regime-A fact derivation reads (expected axes: encoding family
      from storage dtype, symbol cardinality, mV scale presence,
      file-group structure from num_files; expected channel-group
      defaults "channel0001"/"channel0002" — VERIFY, do not assume).
      Record the verified list here before coding.
      Evidence: _(pending)_
- [ ] Define `CheckInputDeclaration` per §3.2 (four fields, frozen) and
      `TaskHealthFacts` with presence-discriminated optional axes
      (absent axis ≠ mismatched axis — the D14 truth-table pattern);
      contradictory axis pairs rejected at construction.
      Evidence: _(pending)_
- [ ] Implement `applicability()`: context-input presence first
      (cheapest, no derivation), then fact axes; FIRST mismatch wins;
      reason names the axis and both sides (declared vs actual);
      deterministic reason strings.
      Evidence: _(pending)_
- [ ] Implement `_regime_a_facts.derive_tidmad_health_facts()`; module
      docstring states it is regime-A ONLY and that 08b's binding
      replaces the CALL SITE, not this function's contract.
      Evidence: _(pending)_

**Validation plan.**
* Unit (pure): TIDMAD facts → hand-built six-equivalent declarations
  all applicable; contrast facts (`continuous_float`) → int8-family
  declarations inapplicable naming the encoding axis; absent
  `target_source` context input → inapplicable naming the input; absent
  fact AXIS → inapplicable naming the axis as ABSENT, never as
  mismatched.
* Negative/invalid: empty declaration → always applicable (explicitly
  legal, asserted); unknown context-input name in a declaration →
  `ValueError` at construction (fail closed at authoring time);
  contradictory facts carrier → construction error.
* Determinism: same inputs → byte-identical reason strings (reasons are
  persisted evidence).
* Backward-compat: production behaviour unchanged BY CONSTRUCTION;
  grep-test asserts no production module imports `applicability`.
* Regime-A pin: the derived TIDMAD facts equal HARDCODED expected
  values in the test (never read back from the deriver).
* Gate: none.

**Acceptance criteria.**
- [ ] Every mismatch class has a test whose assertion names the expected
      axis; the ordering rule (context before facts) has a test that
      fails if the order flips.
- [ ] Regime-A fact values pinned as hardcoded expectations, green.
- [ ] Unreachability grep-test green.

**Failure and edge cases.**
* Profile resolution unavailable: impossible today
  (`resolve_dataset_profile()` falls back to `TIDMAD_PROFILE` — audited
  `dataset_config.py:613`); the deriver therefore never raises on the
  regime-A path — recorded; 08b owns fail-closed for DECLARED bindings.
* Malformed facts (contradictory axes): stop at construction, never a
  plausible verdict.
* Declaration naming a threshold param the check does not read: legal
  in C2 (pure metadata); consistency asserted in C4 where declarations
  meet the real checks.

**Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/execute_tools/health_checks/ -q > /tmp/08a_c2.log 2>&1; rc=$?; tail -20 /tmp/08a_c2.log`
      Evidence: _(pending — counts + wall time)_
- [ ] Unreachability grep-test result recorded.
      Evidence: _(pending)_

**Commit boundary.**
- [ ] Pure additions + one private module; zero behavioural diff
      (untouched pre-existing suite + unreachability test prove it).
- [ ] Diff summary + staged list + evidence + deviations shown;
      permission received before commit.

---

### 4.3 C3 — engine wiring + verdict transport (the behavioural commit)

**Goal.** The applicability decision runs BEFORE every skill invocation;
the string sniff dies; verdicts reach persistence, eligibility and
(unchanged bytes) feedback. This is THE behavioural commit — everything
around it is deliberately non-behavioural so this diff stays small and
fully reviewable.

**Scope.**
* Changes: `runner.py::evaluate_gate` (pre-run applicability for
  declaration-carrying checks; `Inapplicable` → typed result WITHOUT
  calling `skill.run`); `evaluation.py::_execution_status` (typed
  derivation; DELETE the `"not applicable" in reasons` branch at
  `:173`); `evaluation.py::_persist` (populate additive
  `check_verdicts`); `schemas.py` (`check_verdicts: dict[str, str] |
  None = None` on `PersistedHealthGateResult` — Q-08a-1; amend
  `GateResult.passed` + `get_target_path` docstrings to the typed
  contract); `candidate_eligibility.py` (required-set exclusion of
  INAPPLICABLE; ERROR never excluded).
* Must NOT change: gate ACTION selection (`passed` drives
  `on_pass`/`on_fail` exactly as before), `short_circuit` semantics,
  `get_gates_for_position`, any existing `PersistedHealthGateResult`
  field's VALUE for TIDMAD-shaped inputs, any YAML, `feedback.py`
  (bytes pinned, file untouched).
* Depends on: C1, C2. In C3 the six checks still carry NO declarations —
  `evaluate_gate` treats a declaration-less check as unconditionally
  applicable (exactly pre-08a behaviour), so C3 is a production no-op
  for TIDMAD by construction; the real declarations arrive in C4.

**Implementation plan.**
- [ ] Inspect the firing site (`execution.py:955` region) and every
      `evaluate_and_persist_health_gates` / `evaluate_gate` caller to
      confirm no caller iterates check-level `passed` in a way the
      additive verdict changes (expected consumers: `resolved_action`,
      gate-level `passed`, persisted dicts; verify and record).
      Evidence: _(pending)_
- [ ] `evaluate_gate`: applicability step; inapplicable branch
      constructs the typed result and does NOT invoke the skill; check
      ORDER and short-circuit behaviour otherwise untouched.
      Evidence: _(pending)_
- [ ] `_execution_status`: typed rule (ERROR if any verdict ERROR;
      `not_run` if all verdicts INAPPLICABLE or the existing
      all-io-failed rule; else passed/failed from `result.passed`);
      string branch deleted.
      Evidence: _(pending)_
- [ ] `_persist`: `check_verdicts` populated from `check_results`.
      Evidence: _(pending)_
- [ ] Eligibility exclusion rule + TIDMAD-invariance assertion.
      Evidence: _(pending)_

**Validation plan.**
* Unit: inapplicable short-path with a HAND-BUILT declaration (8.4-B
  lands here in its C3 form; upgraded to the real `output_diversity`
  declaration in C4) — spy asserts BOTH zero `run()` calls AND zero
  `h5py.File` opens, while a sibling applicable check in the SAME gate
  still executes in config-listed order (validate the actual executed
  check SEQUENCE, not the configuration).
* Differential (`_execution_status`): the C1 manifest corpus replayed —
  old-rule expectation table (frozen in the test as DATA, not live
  code) vs new typed rule → identical status string for every case.
* Default-parity (TIDMAD path): same gates selected for the round; same
  executed check sequence; same actions; field-by-field equality of
  every pre-existing `PersistedHealthGateResult` field against a
  pre-C3 captured dump; `check_verdicts` the only addition.
* Eligibility: INAPPLICABLE-excluded / ERROR-retained cases; TIDMAD
  required set unchanged.
* Feedback byte-pin: `_build_trial_validity_feedback` rendered over
  fixture records pre/post → byte-identical.
* Reachability: a test that FAILS if the production path
  (`evaluate_and_persist_health_gates` → `evaluate_gate`) reaches
  `skill.run` without the applicability step for a declaration-carrying
  check (bypass detection, the CLAUDE.md boundary rule).
* Negative: declaration-less check → pre-08a behaviour bit-for-bit
  (differential through `evaluate_gate` on manifest cases).
* Gate: none in-commit (§7 runs at the final head).

**Acceptance criteria.**
- [ ] 8.4-B spy green (both assertions), sibling-execution assertion
      green.
- [ ] `_execution_status` differential: 100% identical over the corpus;
      grep pin: `"not applicable"` absent from `evaluation.py`.
- [ ] Persisted parity: pre-existing fields byte-equal on TIDMAD-shaped
      fixtures; `check_verdicts` populated.
- [ ] Feedback bytes identical; TIDMAD required set identical.
- [ ] Old NA docstring sentences absent from `GateResult.passed` /
      `get_target_path` (grep pin).

**Failure and edge cases.**
* ALL checks inapplicable → gate takes `on_pass` (Q-08a-2), persists
  `execution_status="not_run"` + verdicts; eligibility excludes them
  from the required set. Asserted.
* Mixed inapplicable + failed → gate fails with the FAILED check's
  reason (first-failure rule unchanged); an inapplicable result is
  never selected as `failure_reason`.
* Check raises DURING an applicable run → unchanged Bug-B guard →
  `verdict=ERROR`, `on_fail` (blocking fails closed — today's action,
  now typed).
* Legacy persisted records (no `check_verdicts`) read by
  eligibility/feedback: `None`-defaulted; classification falls back to
  today's inputs — resume-over-pre-08a-records asserted unchanged
  against a real pre-08a record fixture.
* An 08a-written record read by `.get`-style legacy readers: additive
  field ignored — asserted on the feedback reader.

**Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/execute_tools/health_checks/ -q > /tmp/08a_c3a.log 2>&1; rc=$?; tail -20 /tmp/08a_c3a.log`
      Evidence: _(pending)_
- [ ] `.venv/bin/python -m pytest tests/unit/nodes/ -q -k "feedback or eligibility" > /tmp/08a_c3b.log 2>&1; rc=$?; tail -20 /tmp/08a_c3b.log`
      Evidence: _(pending)_
- [ ] Grep pins recorded (as tests, not one-off greps).
      Evidence: _(pending)_

**Commit boundary.**
- [ ] One behavioural diff + its differential proofs; six checks and
      peek untouched.
- [ ] Diff summary + staged list + evidence + deviations shown;
      permission received before commit.

---

### 4.4 C4 — the six checks declare their inputs

**Goal.** The real declarations land (ClassVar data per §3.2), every
production constructor passes `verdict=` explicitly, and the in-check NA
fallbacks become defensive typed returns. Separate from C3 so
declaration CONTENT review (scientific: what each check truly requires)
is not entangled with engine-wiring review.

**Scope.**
* Changes: the six check modules (declaration ClassVar + explicit
  `verdict=` at each constructor + NA returns typed + defensive-only
  comments), `protocol.py` (Protocol gains the declaration attribute;
  §2.1 NA docstring REPLACED citing parent §7), `_multi_file_peek.py`
  docstrings only.
* Must NOT change: check arithmetic, thresholds, config keys,
  aggregation modes, peek plumbing (C5), YAML.
* Depends on: C1–C3.

**Implementation plan.**
- [ ] Read `pearson_dispersion.py` and `spectral_peak_ratio.py`
      END-TO-END (the two checks not yet fully read; §2 covers their NA
      sites only) and record here what each actually consumes before
      writing its declaration (expected from the parent §2.2 census:
      pearson = denoised+target peeks; spectral = target peek +
      `sampling_frequency` from the PROFILE — verify, incl. which
      channels and which config keys).
      Evidence: _(pending)_
- [ ] Write the six declarations FROM verified consumption (expected
      shape: diversity/std/amplitude → `tidmad.int8_prefix_peek` +
      `int8_symbol_stream` facts (+ scale for std); pearson/spectral →
      `tidmad.target_comparison_peek` + target-source context input
      (+ spectral's frequency fact); per_file_output_std →
      `tidmad.int8_prefix_peek` + file-group fact) — adjust to what the
      reads prove, and STOP AND ASK if a check's true consumption does
      not fit the §3.2 declaration shape.
      Evidence: _(pending)_
- [ ] Explicit `verdict=` at every production constructor; the C1
      derivation bridge instrumented-asserted reachable ONLY from
      legacy-shaped fixtures.
      Evidence: _(pending)_
- [ ] Declaration↔config-key consistency assertion:
      `threshold_parameter_names` ⊆ the keys `run()` actually reads
      (checked programmatically against the real `cfg.get` keys).
      Evidence: _(pending)_

**Validation plan.**
* Parity: C1 manifest replayed through the six updated checks —
  `passed/reason/metrics` byte-identical; `verdict` explicit and equal
  to the C1-derived class for every case (script-compared).
* Unit per check: declaration content pins (hardcoded expected view
  key, context inputs, fact axes); 8.4-B upgraded to the REAL
  `output_diversity` declaration.
* Negative: a six-check gate under contrast facts → the int8 blocking
  checks inapplicable, gate `on_pass`, `not_run` persisted — and the
  SAME fixture under TIDMAD facts → all applicable (the pair proves the
  axis, not the fixture).
* Backward-compat: full health package green; §5 dispositions applied
  (ONLY the named NA-prose pins upgraded).
* Gate: none.

**Acceptance criteria.**
- [ ] Manifest parity script: zero diffs on pre-existing fields across
      all cases.
- [ ] Derivation-bridge instrumentation: zero hits from the six checks'
      suites; >0 from the legacy-shape test (proves the instrument
      works).
- [ ] Old protocol NA sentence absent (grep pin); new text cites
      parent §7.
- [ ] Declaration↔config-key assertion green for all six.

**Failure and edge cases.**
* A check invoked DIRECTLY (legacy tests, not via `evaluate_gate`) with
  absent inputs: defensive typed NA return preserves today's outcome
  (`passed=True` + reason) with `verdict=INAPPLICABLE` — same
  behaviour, now honest, marked defensive-only.
* Explicit `peek_file_indices` + every path missing (production shape):
  stays the aggregation path → `passed=False`, io-classed →
  `verdict=ERROR` (blocking fails closed exactly as today — asserted
  against the C1 manifest's io cases; §2.1 asymmetry note).
* Duplicate `peek_file_indices`: `_resolve_indices` dedupe unchanged
  (existing test kept green; no new test invented for it).

**Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/execute_tools/health_checks/ -q > /tmp/08a_c4.log 2>&1; rc=$?; tail -20 /tmp/08a_c4.log`
      Evidence: _(pending)_
- [ ] Manifest parity script output recorded (case count, zero diffs).
      Evidence: _(pending)_

**Commit boundary.**
- [ ] Declaration content + constructor explicitness only; no engine,
      no peek, no arithmetic changes.
- [ ] Diff summary + staged list + evidence + deviations shown;
      permission received before commit.

---

### 4.5 C5 — TIDMAD peek routed through the Deliverable Contract

**Goal.** The peek stops carrying its own copy of TIDMAD's storage facts
(`"channel0001"`/`"channel0002"`/walk literals) and reads them from the
owning authority — byte-identically. Its own commit because its risk
class (I/O parity) is disjoint from verdict semantics.

**Scope.**
* Changes: `_peek.py` (walk parameterized by spec channel-group
  values), `_multi_file_peek.py` (the `channel="channel0001"` parameter
  DEFAULT at `:177` removed/required — supplied at call sites from
  `derive_tidmad_deliverable_spec(resolve_dataset_profile()).storage`),
  the peek-calling checks' call sites, parity additions in
  `test_peek.py`/`test_multi_file_peek.py`.
* Must NOT change: bytes read (proven), persisted record STRINGS
  (`"channel0001_prefix_peek"` at `evaluation.py:157` exempted BY
  NAME), YAML, aggregation, `peek_int8_at_path` legacy wrapper's
  external behaviour.
* Depends on: C4 (call sites already touched once — avoids re-reviewing
  half-migrated constructors).

**Implementation plan.**
- [ ] VERIFY the `DeliverableStorage` TIDMAD default values equal the
      literals before any swap (expect
      `input_channel_group="channel0001"`,
      `target_channel_group="channel0002"`, `storage_dtype="int8"` —
      read `deliverable_spec.py:209-260` + the derive path and record
      the actual values here; if they differ, STOP AND ASK).
      Evidence: _(pending)_
- [ ] Plumb: one spec resolution per check `run()` (regime-A derive);
      channel values flow to `peek_and_aggregate(channel=…)` and the
      target-peek sites; legacy wrapper kept with a deprecation note.
      Evidence: _(pending)_
- [ ] Literal-grep pin as a TEST: zero `"channel0001"`/`"channel0002"`
      literals in `_peek.py`/`_multi_file_peek.py`/the six checks;
      `evaluation.py:157`'s persisted label whitelisted by exact
      file+string.
      Evidence: _(pending)_

**Validation plan.**
* Identical-bytes: on the committed HDF5 fixtures, pre-C5 vs post-C5
  peeks — `np.array_equal` AND raw `tobytes()` sha256 (both channels;
  single- and multi-file paths). The PRE-side hashes are captured and
  pinned as constants BEFORE the plumbing change.
* Parity: C1 manifest re-verified at the C5 head.
* Negative: a spec whose channel group is absent from the fixture file
  → `KeyError` surfaces exactly as today (io-classed ERROR path
  unchanged).
* Backward-compat: full health package green; existing `test_peek.py`
  cases untouched.
* Gate: none in-commit.

**Acceptance criteria.**
- [ ] Byte-sha equality on every fixture read (table recorded).
- [ ] Manifest parity re-run: zero diffs.
- [ ] Literal-grep pin test green.
- [ ] No pre-existing test file edited beyond the named additions.

**Failure and edge cases.** Missing file → unchanged `OSError` → ERROR;
malformed spec cannot occur on the regime-A path (derive is total over
the shipped profile — recorded); non-TIDMAD specs are 08b/08c's concern
(no speculative handling).

**Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/execute_tools/health_checks/ -q > /tmp/08a_c5.log 2>&1; rc=$?; tail -20 /tmp/08a_c5.log`
      Evidence: _(pending)_
- [ ] Byte-sha parity table recorded (fixtures × channels).
      Evidence: _(pending)_

**Commit boundary.**
- [ ] Plumbing-only; verdicts untouched (manifest re-run proves it).
- [ ] Diff summary + staged list + evidence + deviations shown;
      permission received before commit.

---

### 4.6 C6 — 8.4-C minimal check + rung fixtures + docs sync

**Goal.** The negative control exists (a generic dispersion check FIRES
and can FAIL on the same declared-float fixture 8.4-B used —
inapplicability is never an exemption), and every touched surface's
documentation matches the final code (CLAUDE.md doc-sync rule — hence
last).

**Scope.**
* Changes: NEW `execute_tools/health_checks/sample_dispersion_floor.py`
  (§3.6 — registered normally, referenced by NO production YAML;
  declaration requires `continuous_float`; view key deliberately
  plugin-local-style, e.g. `step08.fixture_continuous_samples`, proving
  the opaque-key claim in miniature), its registration in
  `__init__.py` (the built-ins' bootstrap — allowed here because 08a
  predates 08b's external channel; recorded as such), 8.4-B/8.4-C rung
  fixtures as named tests, docs
  (`docs/design/pluggable_health_checks.md` §6/§8 amendments citing the
  parent; this design's §10 ledger; parent §12 08a checkbox).
* Must NOT change: production YAML (the new check is NOT configured
  anywhere), any TIDMAD behaviour.
* Depends on: C1–C5.

**Implementation plan.**
- [ ] `sample_dispersion_floor`: hand-computed arithmetic test vectors
      FIRST (constant series → std 0.0 → FAIL at the fixture floor;
      varied series → PASS), then the check; blocking-capable in the
      fixture gate config.
      Evidence: _(pending)_
- [ ] 8.4-B/8.4-C rung pair as named tests quoting roadmap §8.4 wording
      in their docstrings; both run against the SAME declared-float
      fixture within ONE gate evaluation (int8 checks inapplicable,
      dispersion check fires).
      Evidence: _(pending)_
- [ ] Docs amended (quote each documented behaviour against merged
      source); §10 ledger filled; parent §12 08a checkbox ticked.
      Evidence: _(pending)_

**Validation plan.** Unit: arithmetic vectors; fires-on-contrast-facts
+ fails-on-constant; the new check under TIDMAD facts → INAPPLICABLE
(both directions of the axis proven); registry duplicate-registration
guard green; empty sample set → ERROR (a floor over nothing is not
evidence — fail closed). Docs: quoted-against-source check. Gate: §7's
Gate 2 runs AFTER this commit at the final executable head, on
operator-approved command only.

**Acceptance criteria.**
- [ ] 8.4-C fires AND fails on the constant fixture in one gate
      evaluation alongside inapplicable int8 checks.
- [ ] Full health package green; config-baseline test untouched-green.
- [ ] Docs quote-verified; ledger complete.

**Failure and edge cases.** Empty/degenerate sample input → ERROR
(asserted); the check never appears in production YAML (baseline pin
proves it); TIDMAD facts → INAPPLICABLE (proves the axis cuts both
ways).

**Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/execute_tools/health_checks/ -q > /tmp/08a_c6.log 2>&1; rc=$?; tail -20 /tmp/08a_c6.log`
      Evidence: _(pending)_
- [ ] Full targeted set for the PR (health package + tuner
      feedback/eligibility consumers), log + counts recorded.
      Evidence: _(pending)_

**Commit boundary.**
- [ ] New fixture-check + fixtures + docs; no production config.
- [ ] Diff summary + staged list + evidence + deviations shown;
      permission received before commit.

## 5. Test disposition (existing families; KEEP unless named)

| family | disposition | reason |
|---|---|---|
| six per-check behaviour tests | **KEEP**; C4 **UPGRADE** only the specific assertions that pin `passed=True` + NA prose as the honest outcome (they now also assert `verdict is INAPPLICABLE`) | they are the parity baseline; deleting or loosening any would orphan the §3.1 mapping |
| `test_runner.py` | KEEP + extend (applicability wiring, short-circuit×inapplicable) | owns `evaluate_gate` semantics |
| `test_campaign_evaluation.py` | KEEP + extend (`check_verdicts` additive field, `_execution_status` differential) | owns persistence |
| `test_candidate_eligibility.py` | KEEP + extend (exclusion rule; TIDMAD required-set unchanged) | owns eligibility |
| `test_peek.py` / `test_multi_file_peek.py` | KEEP + C5 parity additions | own the byte-identical-read proof |
| `test_step00_health_config_baseline.py`, config/scope/role guards | KEEP untouched | 08a makes no YAML/role change — these must stay green as-is |
| `test_schemas.py`, `test_context_target_path.py` | KEEP; UPGRADE the `get_target_path` NA-contract docstring pin to the typed contract | docstring superseded by design |

New tests each name their defect class: §3.1 mapping rows (a silently
mis-derived verdict); applicability axes (a mismatch that stops naming
its axis); the 8.4-B spy (I/O or `run()` behind an inapplicable
verdict); the 8.4-C negative control (inapplicability read as
exemption); reachability (production path bypassing the boundary);
feedback byte-pin (prompt drift); `_execution_status` differential
(string-sniff semantics silently changed).

## 6. Evidence economy

Targeted per-commit tests + the health-package suite per commit; NO
local full suite; NO manual dispatch; ONE canonical CI on the final
integrated Step-08 head (parent §11, #233 caveat); Gate 2 once at this
child's final executable head. The capture manifest is committed
evidence, not a recomputed claim.

## 7. Gates

* **Gate 1: NOT REQUIRED** — parent §10/§15 Q3 (operator, 2026-08-18):
  "Gate 1 = NOT REQUIRED by default in 08a/08b/08c"; 08a makes no
  prompt/PB delta (C3's byte-stability pin is the executable proof).
  Any accidental delta re-dispositions per the 07b PB rules.
* **Gate 2: REQUIRED, bounded, once** — parent §10 row "production
  firing + persistence through the new path | GATE 2 (bounded TIDMAD
  round) | required | 08a". Spec: ONE cold-start bounded TIDMAD tuner
  round (no `--seed_paths`, CLAUDE.md rule), `openai_tiered_pro.json`,
  time-budgeted ≤10 min, at the final 08a executable head. PASS
  criteria (semantic, decided before launch): gates fire at the round
  boundary; `PersistedHealthGateResult`s carry `check_verdicts`; all six
  TIDMAD checks report `verdict=passed|failed` (never inapplicable);
  actions/severity identical to the pre-08a baseline for the same
  outcomes; run completes with the standard record set. **The exact
  command is shown for operator approval before launch — never launched
  autonomously.**

## 8. Risks / decisions

* **Q-08a-1 — ADOPTED AT FREEZE (operator authorization 2026-08-18)**:
  typed additive `check_verdicts: dict[str, str] | None` on
  `PersistedHealthGateResult` (records are read by resume/
  interpretation tooling; a dict key inside `metrics` would be a silent
  contract). Additive-optional keeps parent §8 ("record fields
  unchanged" = existing fields).
* **Q-08a-2 — ADOPTED AT FREEZE**: an all-inapplicable gate takes
  `on_pass` (never blocks — parent §7) while persisting
  `execution_status="not_run"` + verdicts; eligibility sees the
  blocking check excluded from the required set. "Takes on_pass" is not
  "counts as pass": counting surfaces read verdicts.
* **R-08a-1**: the §3.1 back-compat derivation could linger as a second
  truth source — bounded by the C4 explicit-verdict DoD + the
  reachable-only-defensively instrumentation.
* **R-08a-2**: C5 could drift a read byte — bounded by capture-first
  parity re-verified at C5 and the pinned pre-change byte hashes.
* **R-08a-3**: scope growth discovered at implementation (a check
  consuming something §3.2 cannot declare) — the standing rule is STOP
  AND ASK, never widen silently (§4.0).

## 9. Adversarial self-review

1. *Does 08a smuggle in task binding?* No — facts arrive as an explicit
   argument; the production default is the regime-A derivation; binding
   machinery is 08b (§3.3).
2. *Does any TIDMAD verdict change?* No path: all six applicable under
   regime-A facts; actions driven by `passed`, untouched; capture-first
   manifest pins it.
3. *Is `inapplicable` reachable in production after 08a?* Only via
   absent context inputs (today's NA cases, same outcomes, now typed);
   declaration-mismatch inapplicability becomes production-reachable
   when 08b binds a family — stated, not over-claimed.
4. *Could the spy pass vacuously?* It asserts BOTH no-I/O and
   no-`run()`; and 8.4-C on the same fixture proves the engine still
   executes applicable checks.
5. *Prompt surface?* Byte-pinned (C3).
6. *Registry/YAML creep?* Declarations are ClassVars; the frozen config
   baseline test stays untouched-green; the one `__init__.py`
   registration line (C6) is the built-ins' bootstrap, recorded as
   predating 08b's external channel.
7. *Is the string-sniff deletion safe?* Differential test over the C1
   captured corpus — same outputs, new derivation.
8. *New check discipline?* Exactly one, fixture-scoped, named by the
   roadmap ladder (8.4-C), full family deferred to 08c.
9. *Checkbox honesty?* Every box in this frozen revision is `[ ]`;
   evidence lines are pending; §4.0 forbids `[x]` without recorded
   evidence — the first drafting of rev 2 violated exactly this and was
   corrected before commit; the rule is now load-bearing text.

## 10. Ledger

*(filled per commit during implementation)*
