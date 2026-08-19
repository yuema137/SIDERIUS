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
* **Commit boundary protocol (every commit) — AMENDED, see §4.0a.**
  Before committing, establish the exact `git diff --stat`, the staged
  file list, the test evidence, and any deviation from this frozen
  design, and record them in this ledger. Commits are AUTONOMOUS: this
  is a self-verification checklist, not a blocking operator checkpoint.
  No unrelated cleanup rides along; genericization-in-passing, if any,
  is its own commit.
* **Out of scope for ALL commits** (require separate evidence + operator
  approval, and are NOT in 08a): planner/prompt exposure of health
  (byte-pinned instead), production YAML/default changes, registry or
  ownership mechanics (08b), the full generic check families (08c).
* **Gate 2 is listed separately (§7) and is specified in this ledger
  BEFORE launch** (§4.0a — the pre-launch approval requirement was
  removed by operator amendment; the pre-launch SPECIFICATION requirement
  was not).
* Any commit may split into `-code`/`-docs` git commits at clean
  boundaries preserving the final split's acceptance.

### 4.0a Operator procedural amendment (2026-08-18)

**The semantic design is UNCHANGED and remains FROZEN.** Scope, contract,
acceptance criteria, the C1→C6 ordering, Health ownership, the TIDMAD
parity requirement and validation ownership are untouched by this entry.
What changed is the implementation-control PROCEDURE.

The frozen 08a implementation contract had introduced two manual approval
checkpoints that contradicted the repository's generic Implementation
Working Rules. The operator **removed both**:

| requirement | status |
|---|---|
| operator approval before every semantic commit | **REMOVED** — commits are autonomous |
| operator approval before the bounded Gate-2 launch | **REMOVED** — bounded Gate 2 launches autonomously |

Restored working loop per milestone: inspect exact source → implement →
targeted validation → inspect the diff → update this ledger → semantic
commit → refresh `before_end_memory.md` → next milestone. The
pre-commit information set (milestone, source findings, diff summary,
staged files, validation evidence, deviations, risks, message) is still
established and recorded here — it is simply no longer a blocking gate.

Bounded Gate 2 may launch autonomously provided it is the already-approved
Step-08a Gate, non-destructive, overwrites no preserved evidence, runs
in ≲10 min within the ~1 h total real-runtime budget, costs modestly and
disrupts no shared infrastructure — with its specification (HEAD, command,
claim, expected evidence, bounded scope, expected wall time, evidence
destination) written here BEFORE launch, and PASS/FAIL/INCONCLUSIVE decided
from semantic evidence rather than exit code.

Gate 1 is unchanged: NOT REQUIRED unless an actual prompt/PB semantic delta
appears — which remains a MATERIAL deviation requiring operator review.

Genuine stop conditions remain: source falsifying a frozen invariant · a
materially different architecture · scope expansion into 08b/08c · TIDMAD
behaviour unpreservable · a public contract change beyond the approved 08a
schema additions · ownership change · a prompt/PB delta · a material
production-default change · validation exceeding the approved envelope ·
destructive action · genuinely blocked resources · READY FOR OPERATOR
REVIEW. Ordinary source findings, bounded implementation decisions, routine
test failures, mutations, commits, pushes, PR updates, bounded Gate 2 and
ordinary CI failures are **not** stop conditions.

**Autonomy here means resolving bounded implementation details from source
and evidence inside the frozen design. It is not permission to change
frozen semantics.**

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
- [x] Enumerate every `HealthCheckResult(` constructor site (grep) and
      confirm all pass keyword arguments only (expected from §2.1:
      the six checks + the `runner.py:134` exception guard + the
      multi-peek NA path; verify the exact list and record it here).
      Evidence: **14 production sites, all keyword-only** (each read, not
      just grepped): `output_std.py:80` · `output_diversity.py:83` ·
      `amplitude_collapse.py:103` · `per_file_output_std.py:50,94,103` ·
      `pearson_dispersion.py:53,62,136,144` ·
      `spectral_peak_ratio.py:59,128,137` · `runner.py:134`.
      **Correction to §2.1's phrasing** (mechanical, no semantic
      consequence): `_multi_file_peek.py` does NOT construct a
      `HealthCheckResult` — it returns a `MultiFilePeekOutcome` whose NA
      reason the three peek-based checks fold into their own constructor.
      The census is "six checks + the runner guard".
- [x] Write the capture generator: runs the six registered checks over
      the EXISTING unit-test fixture inputs (reuse the per-check test
      fixtures; do not invent new inputs) and records
      `(check_name, passed, reason, metrics-keyset, expected-verdict)`
      per case, deterministic ordering, into the manifest.
      Evidence: **27 cases** across the six checks —
      `tests/unit/execute_tools/health_checks/_verdict_corpus.py` (the
      reproducible invocations + the INDEPENDENT §3.1 classifier) and
      `goldens/generate_verdict_parity_manifest.py` (writer/`--check`
      verifier, refuses to capture from a tree with modified production
      source). Distribution: 7 passed / 6 failed / 7 inapplicable /
      7 error. Input shapes are the ones the per-check tests already use
      (constant-int8 collapse, varied int8, missing file, missing
      dataset, sinusoid, empty context) — no new scientific case.
- [x] Generate + commit the manifest at the PRE-change tree (verify the
      working tree is clean of schema edits when generating; record the
      generation tree SHA in the manifest header).
      Evidence: **generated at the PRE-change tree** — `source_tree_sha`
      recorded in the manifest header is `a37fd15d`, and the generator's
      `_assert_capture_tree_clean()` guard proved no production file
      differed from HEAD at capture time (only the three capture-owned
      test files may differ). Regeneration reproduces it byte-identically.
      Committed in `ac580514`.
- [x] Add `CheckVerdict` + additive `verdict` field + the §3.1
      derivation as a Pydantic model validator, with the io-classed rule
      exactly as §3.1 row 3; explicit `verdict=` kwarg wins over
      derivation; contradictory explicit input rejected.
      Evidence: `schemas.py` — `CheckVerdict` StrEnum,
      `_NON_FAILING_VERDICTS`, `NA_REASON_MARKER`, the additive
      `verdict: CheckVerdict` field, `_derive_verdict` (`mode="before"`,
      skipped entirely when `verdict` is supplied) and
      `_verdict_agrees_with_passed` (`mode="after"`, rejects the four
      contradictory pairs). The io-classed rule additionally guards
      `attempted > 0` and excludes `bool` from the `int` check so
      `n_files_attempted=0` and a stray `True` cannot be read as
      "every file failed".

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
- [x] `pytest tests/unit/execute_tools/health_checks/` green; `git diff`
      shows no pre-existing test file modified.
      Evidence: 324 passed, rc=0. `git diff HEAD --name-only` =
      `execute_tools/health_checks/schemas.py` ONLY; the other four paths
      are new untracked files (`_verdict_corpus.py`,
      `goldens/generate_verdict_parity_manifest.py`,
      `goldens/verdict_parity_manifest_pre08a.json`,
      `test_check_verdict.py`). Zero pre-existing test files touched.
- [x] Manifest committed; generator re-run at the C1 head reproduces it
      byte-identically (diff empty).
      Evidence: `--check` at the post-schema-change head reports
      "OK — 27 cases reproduce the committed manifest byte-identically",
      i.e. the additive field perturbed no captured value. Committed in
      `ac580514`; re-verified again at the C2 head.
- [x] Mutation check: invert one branch of the derivation (count==1
      mutation site, caches cleared per the mutation-hygiene rules) →
      the named mapping test fails; restore → green.
      Evidence: **two** mutations, each verified `count == 1` before
      applying and every `__pycache__` cleared around each run.
      (1) `NA_REASON_MARKER in reason.lower()` → `not in`: 2 failed
      (`test_pass_with_na_marker_derives_inapplicable` + the parity
      replay); restored → 2 passed. (2) `attempted > 0` → `>= 0`:
      1 failed (`test_zero_files_attempted_is_not_error`), 1 passed;
      restored → 2 passed. `schemas.py` verified byte-identical to its
      pre-mutation backup afterwards. **Honest note**: mutation (2) was
      caught ONLY by the dedicated boundary test — the 27-case corpus has
      no zero-attempted failing case, so the parity manifest alone would
      not have caught it. That is why both tests exist.
- [x] Legacy shape `HealthCheckResult(check_name=…, passed=True)`
      constructs with `verdict == PASSED`.
      Evidence: `test_clean_pass_derives_passed`; and the entire
      pre-existing suite constructs legacy-shaped results with zero edits.

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
- [x] `.venv/bin/python -m pytest tests/unit/execute_tools/health_checks/ -q > /tmp/08a_c1.log 2>&1; rc=$?; tail -20 /tmp/08a_c1.log`
      Evidence: **324 passed, 1.75 s, PYTEST_RC=0** (verdict read from the
      complete log file, not from a piped tail's status).
      Consumers additionally checked (cheap insurance for the additive
      field flowing through `GateResult`):
      `tests/unit/agent/tune_ml_hyperparam_agent/test_gate_integration.py`
      + `tests/unit/agent/schemas/test_health_feedback.py` → **74 passed,
      2.44 s, rc=0**. A production-consumer grep confirms nothing outside
      `health_checks/` reads `check_results`; `policy.py:983` consumes
      `list[GateResult]` and `PersistedHealthGateResult` is untouched in
      C1, so no persisted record byte changes here.
- [x] Manifest regeneration diff (must be empty).
      Evidence: `generate_verdict_parity_manifest.py --check` →
      "OK — 27 cases reproduce the committed manifest byte-identically"
      (run both before and after `ruff format` touched the corpus module).
- [x] Mutation check transcript (site, red test name, restoration).
      Evidence: recorded under Acceptance criteria above.
- **Static checks.** `ruff check` and `ruff format --check` green over
  `execute_tools/health_checks/` and the health test package (three new
  test files were reformatted by `ruff format`, then re-verified).
  **`pyright` could NOT be run locally**: the vendored pyright requires a
  newer Node than this host provides (`node --version` = `v10.19.0`, the
  bundle fails with `SyntaxError: Unexpected token =`). Type checking for
  this change is therefore CI-owned — claimed as CI-only, not as a local
  green.

**Commit boundary.**
- [x] Independently reviewable (one schema + tests + frozen evidence;
      zero consumer changes); no unrelated cleanup.
      Evidence: the only production diff is `schemas.py`; no check, no
      runner, no evaluation, no YAML, no pre-existing test.
- [x] Diff summary + staged file list + test evidence + deviations
      (expected: none) established and recorded in the ledger (§4.0a).
      Evidence: recorded in §10's C1 entry; 6 files, +2013/−18, of which
      `schemas.py` (+146/−18) is the only production change. Presented to
      the operator at the C1 checkpoint and **APPROVED** in the same
      procedural amendment that removed the checkpoint requirement.

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
- [x] Inspect `DatasetProfile`/`ValueEncoding` (`dataset_config.py:381,
      :439`) and `derive_tidmad_deliverable_spec` +
      `DeliverableStorage` (`deliverable_spec.py:209-`,
      `evaluation_metric.py:677-`) and FIX the exact field list the
      regime-A fact derivation reads (expected axes: encoding family
      from storage dtype, symbol cardinality, mV scale presence,
      file-group structure from num_files; expected channel-group
      defaults "channel0001"/"channel0002" — VERIFY, do not assume).
      Record the verified list here before coding.
      Evidence: **verified by executing the real resolution**, not by
      reading literals — `resolve_dataset_profile()` →
      `channels={'input_channel': 'channel0001', 'target_channel':
      'channel0002'}`, `encoding={'storage_dtype': 'int8',
      'compute_dtype': 'int16', 'value_offset': 128, 'num_classes': 256}`,
      `dataset.num_files=20`, `dataset.sampling_frequency=1.0e7`; and
      `derive_tidmad_deliverable_spec(...).storage` →
      `{'input_channel_group': 'channel0001', 'target_channel_group':
      'channel0002', 'storage_dtype': 'int8', 'value_offset': 128}`. The
      channel-group expectation is CONFIRMED. `resolve_dataset_profile()`
      at `dataset_config.py:613` is `_ACTIVE_PROFILE.get() or
      TIDMAD_PROFILE` — total on the regime-A path, as the design's edge
      case recorded.
      **One expected axis is NOT derivable — see the mV finding in §10.**
- [x] Define `CheckInputDeclaration` per §3.2 (four fields, frozen) and
      `TaskHealthFacts` with presence-discriminated optional axes
      (absent axis ≠ mismatched axis — the D14 truth-table pattern);
      contradictory axis pairs rejected at construction.
      Evidence: `schemas.py` — `FACT_AXES` (5 axes),
      `CONTEXT_INPUT_PREDICATES` (4 logical inputs), `FactRequirement`
      (axis + optional `equals`; unknown axis rejected at construction),
      `TaskHealthFacts` (all axes optional, `gt` bounds on the numeric
      ones, and a `symbol_cardinality`-without-`encoding_family`
      contradiction rejected **structurally** — deciding whether an
      opaque family string "is symbolic" would require interpreting a
      value this module must never interpret),
      `CheckInputDeclaration` (four frozen fields; unknown context input
      rejected at construction).
- [x] Implement `applicability()`: context-input presence first
      (cheapest, no derivation), then fact axes; FIRST mismatch wins;
      reason names the axis and both sides (declared vs actual);
      deterministic reason strings.
      Evidence: `schemas.py::applicability` — pure, total, no I/O, no
      profile resolution. `ApplicabilityVerdict` carries the deciding
      `axis` as a TYPED FIELD (not only in prose), and its own validator
      forbids an inapplicable verdict that names no axis. Reasons omit
      the check-name prefix so the runner can produce today's exact
      `"{check_name}: not applicable — …"` shape in C3.
- [x] Implement `_regime_a_facts.derive_tidmad_health_facts()`; module
      docstring states it is regime-A ONLY and that 08b's binding
      replaces the CALL SITE, not this function's contract.
      Evidence: NEW `execute_tools/health_checks/_regime_a_facts.py` with
      `derive_health_facts(profile)` + `resolve_health_facts()`. Named
      without a task prefix deliberately — it contains no task name and
      no place for one; everything is read from the resolved profile.
      Module docstring states the regime-A-only scope and the
      call-site-replacement rule verbatim.

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
- [x] Every mismatch class has a test whose assertion names the expected
      axis; the ordering rule (context before facts) has a test that
      fails if the order flips.
      Evidence: `test_applicability.py` — absent-axis, mismatched-axis,
      absent-context-input and presence-only classes each assert
      `verdict.axis`; `test_context_inputs_are_decided_before_fact_axes`
      constructs a declaration with BOTH a missing context input and a
      mismatched fact axis and pins that the context input wins;
      `test_first_declared_requirement_wins_within_a_kind` pins
      declaration order. The absent-axis test additionally asserts
      `"requires" not in reason`, so an absent axis can never be
      re-described as a mismatch.
- [x] Regime-A fact values pinned as hardcoded expectations, green.
      Evidence: `TestRegimeADerivation` asserts the literals
      `"int8_symbol_stream"` / `256` / `20` / `1.0e7` — never read back
      from the deriver — plus `value_scale_unit is None`.
- [x] Unreachability grep-test green.
      Evidence: `TestEngineIsUnreachableFromProduction`, 4 tests. **It was
      initially VACUOUS and was repaired** — see §10's C2 entry: the
      repo-root hop was off by one, so `git grep` ran outside the
      checkout and found nothing. It now (i) asserts the resolved root
      contains `.git` and the module under test, (ii) asserts `git grep`
      exited 0/1 rather than treating a failed search as "no callers",
      (iii) runs a positive probe that must find the definition, and
      (iv) uses `--untracked` so a brand-new production module counts.
      Mutation-proven: adding a real `applicability(...)` call + import to
      `runner.py` turns 2 of the 4 red; restored → 25 passed and
      `runner.py` byte-identical.

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
- [x] `.venv/bin/python -m pytest tests/unit/execute_tools/health_checks/ -q > /tmp/08a_c2.log 2>&1; rc=$?; tail -20 /tmp/08a_c2.log`
      Evidence: **349 passed, rc=0, 3.03 s** (324 at C1 + 25 new
      applicability tests). C1's manifest `--check` re-run at the C2 head:
      byte-identical — C2 changed no check behaviour, as intended.
      `ruff check` + `ruff format --check` green over
      `execute_tools/health_checks/` and the health test package.
      `pyright` still not runnable locally (Node `v10.19.0`) — CI-owned.
- [x] Unreachability grep-test result recorded.
      Evidence: recorded under Acceptance criteria above, including the
      vacuous-guard repair and its mutation proof.

**Commit boundary.**
- [x] Pure additions + one private module; zero behavioural diff
      (untouched pre-existing suite + unreachability test prove it).
      Evidence: `2d1c7b61` — no pre-existing test edited; the C1 manifest
      re-verified byte-identical; the unreachability guard green and
      mutation-proven.
- [x] Diff summary + staged list + evidence + deviations established and
      recorded in the ledger (§4.0a — self-verification, not a blocking
      operator checkpoint).

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
- [x] Inspect the firing site (`execution.py:955` region) and every
      `evaluate_and_persist_health_gates` / `evaluate_gate` caller to
      confirm no caller iterates check-level `passed` in a way the
      additive verdict changes (expected consumers: `resolved_action`,
      gate-level `passed`, persisted dicts; verify and record).
      Evidence: **production callers are exactly three** —
      `nodes/ml_hyperparameter_tune_agent/execution.py:955`
      (`evaluate_and_persist_health_gates`, the tuner firing point),
      `scripts/run_comparison.py:471` (same), and
      `scripts/finalize_recovered_diagnostic_round.py:136`
      (`evaluate_gate`). **No production code outside `health_checks/`
      reads `check_results` at all**; `policy.py:983` consumes
      `list[GateResult]` (gate-level only) and `agent/schemas/
      hyperparam_tuning.py:465` carries `PersistedHealthGateResult`.
      So the additive per-check field reaches consumers only through the
      persisted dict, exactly as designed.
- [x] `evaluate_gate`: applicability step; inapplicable branch
      constructs the typed result and does NOT invoke the skill; check
      ORDER and short-circuit behaviour otherwise untouched.
      Evidence: `runner.py::evaluate_gate` — `getattr(skill,
      "declaration", None)`, so a declaration-less check keeps the exact
      pre-08a path; facts resolved LAZILY and once per gate (a gate of
      declaration-less checks resolves no profile at all — asserted);
      the inapplicable branch appends a typed result and `continue`s
      before `skill.run`. `_resolve_task_facts()` is a one-line indirection
      so 08b has a single call site to redirect.
- [x] `_execution_status`: typed rule (ERROR if any verdict ERROR;
      `not_run` if all verdicts INAPPLICABLE or the existing
      all-io-failed rule; else passed/failed from `result.passed`);
      string branch deleted.
      Evidence: implemented, string sniff deleted, **but the rule ORDER
      differs from the bullet's phrasing — see §10's C3 finding 2.** The
      binding requirement is the design's own "byte-identical for every
      existing input", and the all-io-failed class derives
      `CheckVerdict.ERROR`, so an "ERROR first" ordering would have moved
      that class from `"not_run"` to `"error"`. Today's ordering is
      preserved exactly; the four-way truth lives in `check_verdicts`.
- [x] `_persist`: `check_verdicts` populated from `check_results`.
      Evidence: `evaluation.py::_persist` builds
      `{check.check_name: check.verdict.value for check in
      result.check_results}` — the checks that produced a result, so a
      short-circuited gate reports what ran rather than inventing entries.
- [x] Eligibility exclusion rule + TIDMAD-invariance assertion.
      Evidence: `candidate_eligibility._all_checks_inapplicable` +
      the `continue` inside the required-gate loop. ERROR is never
      excluded; a legacy record (no `check_verdicts`) and an empty verdict
      map both return False and take the pre-08a path — asserted by two
      dedicated tests, because reading absence as inapplicability would
      silently promote historical UNKNOWN rounds to VALID.

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
- [x] 8.4-B spy green (both assertions), sibling-execution assertion
      green.
      Evidence: `test_runner.py::TestApplicabilityWiring` — the
      `no_file_may_be_opened` fixture monkeypatches `h5py.File` to RAISE,
      so an implementation that peeked before giving up fails even though
      `run_calls == 0` would still hold. The sibling test asserts the
      executed SEQUENCE (`[r.check_name for r in gr.check_results] ==
      ["int8_only", "universal"]` with `run_calls` 0 and 1), not the
      configuration. `test_applicable_declaring_check_runs_normally`
      proves the other direction of the axis, so a wiring bug that made
      EVERY declaring check inapplicable cannot pass.
- [x] `_execution_status` differential: 100% identical over the corpus;
      grep pin: `"not applicable"` absent from `evaluation.py`.
      Evidence:
      `test_campaign_evaluation.py::test_execution_status_is_byte_identical_to_the_pre_08a_rule`
      replays all 27 captured cases against the pre-08a rule transcribed
      as test-owned data (quoted from `a37fd15d`) — zero divergences.
      `test_the_differential_corpus_covers_every_status` guards the guard.
      The prose pin uses **AST** rather than a substring search, because
      the new docstring legitimately quotes the removed branch: it
      unparses `_execution_status`'s executable body (docstring dropped)
      and asserts neither `not applicable` nor `.reason` appears.
      **Coverage limit, recorded honestly:** the corpus contains no
      `exception_type` case (the C1 corpus calls checks directly, and that
      metric is produced by the runner's Bug-B guard), so the differential
      does not exercise the `"error"` status. That class is owned by the
      C1 mapping test and by `test_runner.py`'s existing Bug-B test.
- [x] Persisted parity: pre-existing fields byte-equal on TIDMAD-shaped
      fixtures; `check_verdicts` populated.
      Evidence: the pre-existing `test_failed_gate_persists_full_typed_observation`
      passes untouched, and
      `test_check_verdicts_are_persisted_for_every_check_that_ran` pins the
      new field alongside an unchanged `execution_status`.
      `test_legacy_persisted_record_without_verdicts_still_validates`
      pins `None` for records that predate the field.
- [x] Feedback bytes identical; TIDMAD required set identical.
      Evidence: **captured from a git worktree at `a37fd15d`**, not from
      current code — `git worktree add /tmp/pre08a_worktree a37fd15d`, the
      same renderer script run against both checkouts, outputs
      byte-identical (sha256 `32405904042f715df72ff28f2c9b30dc…`, 174
      lines, 8 record-set × skipped-flag combinations covering
      all-invalid, a not-run gate, no gates and an execution failure).
      Frozen as `tests/unit/agent/tune_ml_hyperparam_agent/goldens/
      step08a_trial_validity_feedback_pre08a.json` and asserted by
      `test_trial_validity_feedback_is_byte_identical_to_pre_step08a`,
      with a companion test proving the golden is not all-`None`.
      TIDMAD required set: `test_tidmad_shaped_record_is_unaffected`.
- [x] Old NA docstring sentences absent from `GateResult.passed` /
      `get_target_path` (grep pin).
      Evidence: both docstrings rewritten to the typed contract citing
      parent §7. **§5 expected an existing docstring pin in
      `test_context_target_path.py` to "upgrade"; source shows NO test
      pinned that prose** (the `M8 §3.4` matches are test module
      docstrings, not assertions). Rather than record an upgrade that did
      not happen, the pin was CREATED:
      `TestTheSupersededNotApplicableContractIsGone` asserts the
      superseded instruction is absent from
      `HealthCheckContext.get_target_path.__doc__` and that the typed
      contract is stated instead. It immediately earned its place — it
      caught the first draft of the replacement docstring, which quoted
      the retired phrase while explaining it; the docstring was reworded
      rather than the pin weakened.

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
- [x] `.venv/bin/python -m pytest tests/unit/execute_tools/health_checks/ -q > /tmp/08a_c3a.log 2>&1; rc=$?; tail -20 /tmp/08a_c3a.log`
      Evidence: **371 passed, rc=0, 2.52 s** (349 at C2 + 22 new C3
      tests). C1 manifest `--check` byte-identical at the C3 head.
- [x] `.venv/bin/python -m pytest tests/unit/nodes/ -q -k "feedback or eligibility" …`
      Evidence: the feedback consumers live under
      `tests/unit/agent/tune_ml_hyperparam_agent/` (not `tests/unit/nodes/`
      — a mechanical path correction), so the run was
      `pytest tests/unit/execute_tools/health_checks/
      tests/unit/agent/tune_ml_hyperparam_agent/ tests/unit/agent/schemas/`.
      Result recorded in §10's C3 entry.
- [x] Grep pins recorded (as tests, not one-off greps).
      Evidence: three, all executable — the AST-based prose pin on
      `_execution_status`; the one-call-site pin on `applicability`
      (`TestEngineIsWiredExactlyOnce`, the C2 unreachability guard
      INVERTED rather than deleted); and the `get_target_path` docstring
      pin. None is a one-off shell grep.

**Commit boundary.**
- [x] One behavioural diff + its differential proofs; six checks and
      peek untouched.
      Evidence: `aac9b3ba` — the diff touches `runner.py`,
      `evaluation.py`, `schemas.py` and `candidate_eligibility.py` only;
      no check module and no peek module changed, so the manifest stayed
      byte-identical.
- [x] Diff summary + staged list + evidence + deviations established and
      recorded in the ledger (§4.0a — self-verification, not a blocking
      operator checkpoint).

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
- [x] Read `pearson_dispersion.py` and `spectral_peak_ratio.py`
      END-TO-END (the two checks not yet fully read; §2 covers their NA
      sites only) and record here what each actually consumes before
      writing its declaration (expected from the parent §2.2 census:
      pearson = denoised+target peeks; spectral = target peek +
      `sampling_frequency` from the PROFILE — verify, incl. which
      channels and which config keys).
      Evidence: **the pearson expectation is CONFIRMED; the spectral one
      is REFUTED.** `pearson_dispersion` reads
      `peek_int8_at_channel(denoised_path, "channel0001", …)` AND
      `peek_int8_at_channel(target_path, "channel0002", …)` (`:79-80`),
      guards `target_path_fn is None` (`:52`), and reads config keys
      `peek_samples` + `peek_file_indices` (no threshold — it is
      recording-only). **`spectral_peak_ratio` never touches the target
      channel**: it peeks `channel0001` of the DENOISED path only
      (`:74`) and computes a PSD, reading
      `resolve_dataset_profile().dataset.sampling_frequency` (`:55`) for
      the frequency axis; config keys `peek_samples` +
      `peek_file_indices`, again no threshold. The design's "spectral =
      target peek" expectation was exactly the kind of assumption its own
      "verify, do not assume" instruction exists to catch.
- [x] Write the six declarations FROM verified consumption (expected
      shape: diversity/std/amplitude → `tidmad.int8_prefix_peek` +
      `int8_symbol_stream` facts (+ scale for std); pearson/spectral →
      `tidmad.target_comparison_peek` + target-source context input
      (+ spectral's frequency fact); per_file_output_std →
      `tidmad.int8_prefix_peek` + file-group fact) — adjust to what the
      reads prove, and STOP AND ASK if a check's true consumption does
      not fit the §3.2 declaration shape.
      Evidence: written from the reads, with **three adjustments** to the
      expected shape, none of which needed a new declaration field (the
      §3.2 shape held — no STOP condition):
      (a) **no `scale for std`** — the mV constant is check-local
      (C2 finding 2); requiring it would break TIDMAD parity;
      (b) **spectral consumes `tidmad.int8_prefix_peek`, not
      `tidmad.target_comparison_peek`, and does NOT require
      `target_source`** — it reads only the denoised stream. Only
      `pearson_dispersion` declares `target_source`, pinned by a census
      test so a future copy-paste cannot quietly widen it;
      (c) `per_file_output_std` and `pearson_dispersion` additionally
      require `file_group_size` (both describe per-FILE structure);
      spectral requires `sampling_frequency_hz`.
- [x] Explicit `verdict=` at every production constructor; the C1
      derivation bridge instrumented-asserted reachable ONLY from
      legacy-shaped fixtures.
      Evidence: all 15 production constructors now pass `verdict=`
      (14 audited at C1 + the C3 inapplicable branch).
      **Instrumentation replaced by a static census** —
      `TestProductionNeverReliesOnTheCompatibilityBridge` walks the AST of
      the six checks plus `runner.py` and asserts every
      `HealthCheckResult(...)` call carries a `verdict` keyword. Stronger
      than a runtime counter, which would only cover the constructors a
      test happens to execute, and it needs no instrumentation inside
      production code. To avoid six transcriptions of the §3.1 rule, the
      mapping was extracted as `schemas.classify_verdict(...)`: the C1
      compatibility validator now DELEGATES to it, so there is one
      classifier reached two ways rather than a bridge and a production
      copy that can drift (this closes R-08a-1 more tightly than the
      design's own plan).
- [x] Declaration↔config-key consistency assertion:
      `threshold_parameter_names` ⊆ the keys `run()` actually reads
      (checked programmatically against the real `cfg.get` keys).
      Evidence: `TestDeclarationsMatchWhatTheCheckReads` parses each
      check's `run` (dedented — `inspect.getsource` of a method keeps its
      class indentation, which caught itself on the first run) and
      extracts every `cfg.get("literal")`. Subset assertion green for all
      six, with a companion test asserting the extractor finds keys at all
      so ⊆ cannot pass vacuously, and a test pinning that
      `peek_file_indices` (run-level DataScope policy) and `aggregation`
      (gate policy) are deliberately NOT declared as task thresholds — so
      08b does not migrate framework policy to task ownership.

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
- [x] Manifest parity script: zero diffs on pre-existing fields across
      all cases.
      Evidence: `--check` at the C4 head → "OK — 27 cases reproduce the
      committed manifest byte-identically". Declarations and explicit
      verdicts changed no `passed`, `reason` or `metrics` value, and every
      explicit verdict equals the independently-classified expectation.
- [x] Derivation-bridge instrumentation: zero hits from the six checks'
      suites; >0 from the legacy-shape test (proves the instrument
      works).
      Evidence: satisfied by the STATIC census instead (see the
      implementation item above) — every production constructor states its
      verdict, asserted across all 15 call sites rather than only the ones
      a test path reaches. The legacy-shape direction remains covered by
      C1's `TestVerdictDerivation`.
- [x] Old protocol NA sentence absent (grep pin); new text cites
      parent §7.
      Evidence: `protocol.py` rewritten — the "return
      `HealthCheckResult(passed=True, reason="… not applicable …")`"
      instruction is gone, replaced by the declaration contract citing the
      Step-08 parent §7, and the Protocol now carries
      `declaration: ClassVar[CheckInputDeclaration]`.
- [x] Declaration↔config-key assertion green for all six.
      Evidence: recorded in the implementation item above.

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
- [x] `.venv/bin/python -m pytest tests/unit/execute_tools/health_checks/ -q > /tmp/08a_c4.log 2>&1; rc=$?; tail -20 /tmp/08a_c4.log`
      Evidence: **371 passed, rc=0** for the health package before the new
      declaration tests landed (proving the declarations alone changed no
      existing behaviour), then **475 passed, rc=0** across the health
      package + `test_trial_validity_feedback.py` +
      `test_health_feedback.py` with the 35 new C4 tests included.
      `ruff check` + `ruff format --check` green.
- [x] Manifest parity script output recorded (case count, zero diffs).
      Evidence: 27 cases, zero diffs, byte-identical.

**Commit boundary.**
- [x] Declaration content + constructor explicitness only; no engine,
      no peek, no arithmetic changes.
      Evidence: `ab9b5909` — manifest byte-identical, so no check's
      arithmetic, reason or metrics moved. `classify_verdict` was
      extracted rather than transcribed six times (recorded deviation).
- [x] Diff summary + staged list + evidence + deviations established and
      recorded in the ledger (§4.0a — self-verification, not a blocking
      operator checkpoint).

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
- [x] VERIFY the `DeliverableStorage` TIDMAD default values equal the
      literals before any swap (expect
      `input_channel_group="channel0001"`,
      `target_channel_group="channel0002"`, `storage_dtype="int8"` —
      read `deliverable_spec.py:209-260` + the derive path and record
      the actual values here; if they differ, STOP AND ASK).
      Evidence: **CONFIRMED by execution** (C2, re-confirmed here):
      `default_deliverable_storage()` →
      `input_channel_group='channel0001'`,
      `target_channel_group='channel0002'`, `storage_dtype='int8'`,
      `value_offset=128`. Also pinned as a test
      (`test_deliverable_contract_channel_names_match_what_the_files_use`)
      so the equality the swap depends on is asserted, not assumed.
- [x] Plumb: one spec resolution per check `run()` (regime-A derive);
      channel values flow to `peek_and_aggregate(channel=…)` and the
      target-peek sites; legacy wrapper kept with a deprecation note.
      Evidence: all six checks resolve `default_deliverable_storage()`
      once per `run()` — **which already IS
      `derive_tidmad_deliverable_spec(resolve_dataset_profile()).storage`**
      (`deliverable_spec.py:314-329`), so no new resolution helper was
      invented. The three peek checks pass
      `channel=storage.input_channel_group`; `per_file_output_std` and
      `spectral_peak_ratio` pass it to `peek_int8_at_channel`;
      `pearson_dispersion` passes `input_channel_group` and
      `target_channel_group` to its two reads. `peek_int8_at_path` keeps
      its signature, now resolving the channel from the contract, with the
      deprecation note retained.
- [x] Literal-grep pin as a TEST: zero `"channel0001"`/`"channel0002"`
      literals in `_peek.py`/`_multi_file_peek.py`/the six checks;
      `evaluation.py:157`'s persisted label whitelisted by exact
      file+string.
      Evidence: `TestNoChannelLiteralsSurviveInHealthCode` scans all eight
      files line by line; zero occurrences remain (docstring examples were
      reworded too, so the pin needs no prose carve-out). The single
      whitelisted string `"channel0001_prefix_peek"` at
      `evaluation.py:158` is asserted still present by a companion test —
      which doubles as proof the scanner can find literals at all, so the
      main assertion cannot pass vacuously.

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
- [x] Byte-sha equality on every fixture read (table recorded).
      Evidence: the oracle is **independent, not captured** — the expected
      sha256s are computed from the seeded generator that WROTE the file,
      so they assert what the bytes should be rather than what the peek
      last returned. Validated at the PRE-C5 tree (18 passed) before any
      plumbing edit, then re-verified after.

      | read | expectation | result |
      |---|---|---|
      | `channel0001`, 4096 samples, seed 11 | sha256 of the generator's first 4096 bytes | equal (dtype int8, shape (4096,)) |
      | `channel0002`, 4096 samples, seed 22 | sha256 of the generator's first 4096 bytes | equal |
      | contract-resolved name vs the old literal | `np.array_equal` | equal |
      | the two channel hashes | must DIFFER | differ (a channel swap cannot hide) |
- [x] Manifest parity re-run: zero diffs.
      Evidence: `--check` at the C5 head → 27 cases byte-identical.
- [x] Literal-grep pin test green.
      Evidence: recorded above.
- [x] No pre-existing test file edited beyond the named additions.
      Evidence: `test_peek.py` gained two new classes and their helpers;
      no existing case was modified. `test_multi_file_peek.py` was NOT
      touched at all — see the deviation below.

**Failure and edge cases.** Missing file → unchanged `OSError` → ERROR;
malformed spec cannot occur on the regime-A path (derive is total over
the shipped profile — recorded); non-TIDMAD specs are 08b/08c's concern
(no speculative handling).

**Verification commands and evidence.**
- [x] `.venv/bin/python -m pytest tests/unit/execute_tools/health_checks/ -q > /tmp/08a_c5.log 2>&1; rc=$?; tail -20 /tmp/08a_c5.log`
      Evidence: **412 passed, rc=0**; with the step02c live-consumer suite
      (which exercises the shipped config against real peek paths)
      **428 passed, rc=0**. `ruff check` + `ruff format --check` green
      after fixing an import-order and a RUF012 finding in the new test.
- [x] Byte-sha parity table recorded (fixtures × channels).
      Evidence: table above.

**Commit boundary.**
- [x] Plumbing-only; verdicts untouched (manifest re-run proves it).
      Evidence: `7e25e541` — manifest byte-identical, and byte-sha parity
      against an independent oracle validated PRE- and post-change.
- [x] Diff summary + staged list + evidence + deviations established and
      recorded in the ledger (§4.0a — self-verification, not a blocking
      operator checkpoint).

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
- [x] `sample_dispersion_floor`: hand-computed arithmetic test vectors
      FIRST (constant series → std 0.0 → FAIL at the fixture floor;
      varied series → PASS), then the check; blocking-capable in the
      fixture gate config.
      Evidence: vectors written first and asserted directly —
      `[2,2,2,2]` → mean 2.0, every deviation 0 → dispersion exactly
      `0.0` → FAIL at floor 0.5; `[0,2,4,6]` → mean 3.0, deviations
      ∓3/∓1, squares 9+1+1+9=20, /4=5 → dispersion `sqrt(5)` → PASS. A
      third test runs the SAME data against two floors so the threshold
      is proven load-bearing, and the floor is pinned inclusive.
      Blocking-capable: the fixture gate's `on_fail` is
      `INVALIDATE_ROUND` and the gate is asserted to take it.
- [x] 8.4-B/8.4-C rung pair as named tests quoting roadmap §8.4 wording
      in their docstrings; both run against the SAME declared-float
      fixture within ONE gate evaluation (int8 checks inapplicable,
      dispersion check fires).
      Evidence: NEW `test_step08_44_rungs.py`, 12 tests. The decisive
      three share ONE `declared_float_gate` fixture — a single
      `evaluate_gate` over all seven checks under
      `encoding_family="continuous_float"`, with `h5py.File` patched to
      raise. Rung B: all six int8 checks `INAPPLICABLE`, no ERROR (an
      attempted read would have surfaced as one). Rung C: the dispersion
      check `FAILED` with `dispersion == 0.0`. Plus **the gate actually
      blocks** (`INVALIDATE_ROUND`, failure_reason names the check) and
      **no result carries `PASSED`** — the two assertions that stop the
      pair being satisfied by a framework that checks nothing.
- [x] Docs amended (quote each documented behaviour against merged
      source); §10 ledger filled; parent §12 08a checkbox ticked.
      Evidence: `docs/design/pluggable_health_checks.md` gains **§6a**
      (the declaration attribute; the rev-6 NA convention marked
      SUPERSEDED with the reason), a **§8 amendment box** (the
      applicability step in `evaluate_gate`, lazy once-per-gate fact
      resolution, inapplicable ≠ pass), **§9.3** (the fixture check, its
      non-production status and why it exists) and a **§10** step
      requiring new checks to declare and to state `verdict=`. Each
      statement was written from the merged source in this branch.
      §10 ledger: this entry. **Parent §12 checkbox: none exists** — the
      frozen parent contains zero `[ ]` markers (verified by grep), so
      there is nothing to tick; recorded rather than invented. Parent
      status synchronisation belongs to the merge lifecycle, not to a
      stacked child.

**Validation plan.** Unit: arithmetic vectors; fires-on-contrast-facts
+ fails-on-constant; the new check under TIDMAD facts → INAPPLICABLE
(both directions of the axis proven); registry duplicate-registration
guard green; empty sample set → ERROR (a floor over nothing is not
evidence — fail closed). Docs: quoted-against-source check. Gate: §7's
Gate 2 runs AFTER this commit at the final executable head, on
operator-approved command only.

**Acceptance criteria.**
- [x] 8.4-C fires AND fails on the constant fixture in one gate
      evaluation alongside inapplicable int8 checks.
      Evidence: `TestRungsBAndCInOneGateEvaluation`, 4 tests over one
      shared gate evaluation.
- [x] Full health package green; config-baseline test untouched-green.
      Evidence: **424 passed, rc=0** with the new check registered;
      `test_step00_health_config_baseline.py` unmodified and green — the
      new registration changed no shipped config. A dedicated test also
      asserts `sample_dispersion_floor` is absent from BOTH shipped
      configs while being resolvable via `registry.get`.
- [x] Docs quote-verified; ledger complete.
      Evidence: recorded above.

**Failure and edge cases.** Empty/degenerate sample input → ERROR
(asserted); the check never appears in production YAML (baseline pin
proves it); TIDMAD facts → INAPPLICABLE (proves the axis cuts both
ways).

**Verification commands and evidence.**
- [x] `.venv/bin/python -m pytest tests/unit/execute_tools/health_checks/ -q > /tmp/08a_c6.log 2>&1; rc=$?; tail -20 /tmp/08a_c6.log`
      Evidence: **424 passed, rc=0** (412 at C5 + 12 rung tests).
- [x] Full targeted set for the PR (health package + tuner
      feedback/eligibility consumers), log + counts recorded.
      Evidence: recorded in the closeout section below.

**Commit boundary.**
- [x] New fixture-check + fixtures + docs; no production config.
      Evidence: `7ae72ae5` — no YAML touched; a test asserts the new check
      is absent from both shipped configs while resolvable by name.
- [x] Diff summary + staged list + evidence + deviations established and
      recorded in the ledger (§4.0a — self-verification, not a blocking
      operator checkpoint).

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
* **Gate 2: PASS** at HEAD `7ae72ae5` — see §10's "Gate 2 — RESULT: PASS".
  Six gates fired, all six carried `check_verdicts`, the verdict union was
  exactly `{passed, failed}` with **no `inapplicable`**, and the round was
  correctly invalidated by a real mode collapse.
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
  command, HEAD, bounded scope, expected wall time, expected PASS evidence
  and evidence destination are written into §10 BEFORE launch; the run
  then proceeds autonomously** within the §4.0a envelope (operator
  procedural amendment, 2026-08-18 — the prior "never launched
  autonomously" requirement was removed; the pre-launch specification
  requirement was not).

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

### Implementation context

Branch `step08-pr08a-check-input-contract`, based on master
`a37fd15d1141d096e5310ae02ae392da67345c99` (the freeze head: parent rev 3
frozen, Steps 01–07 audit accepted, this child design frozen rev 2).
Source audit for this design was taken at `38c8fd0c`; every §2 statement
this implementation depends on has been re-verified at `a37fd15d` and any
difference is recorded below.

### C1 — verdict vocabulary + capture-first parity manifest

**Status: IMPLEMENTED, validated, awaiting the operator commit checkpoint.**

Files: `execute_tools/health_checks/schemas.py` (only production change) ·
NEW `tests/unit/execute_tools/health_checks/_verdict_corpus.py` · NEW
`tests/unit/execute_tools/health_checks/goldens/generate_verdict_parity_manifest.py`
· NEW `.../goldens/verdict_parity_manifest_pre08a.json` (27 cases) · NEW
`tests/unit/execute_tools/health_checks/test_check_verdict.py`.

**Source findings (all re-verified at `a37fd15d`).**

1. The constructor census is 14 keyword-only production sites — six checks
   plus the `runner.py:134` Bug-B guard. §2.1's phrase "the multi-peek NA
   path" overstates: `_multi_file_peek` returns a `MultiFilePeekOutcome`,
   never a `HealthCheckResult`. Mechanical only; the §3.1 derivation is
   unaffected.
2. **All six checks carry `n_files_attempted` and `n_files_io_failed`** in
   `metrics` on their computed results — the three peek-based checks via
   `MultiFilePeekOutcome`, the three loop-based checks built explicitly
   (`per_file_output_std.py:73-75`, `pearson_dispersion.py:108-110`,
   `spectral_peak_ratio.py:107-109`). §3.1's io-classed ERROR rule is
   therefore uniformly implementable. The NA early-returns carry only
   `{"peek_samples_requested": …}`, so they fall to rows 1/2 as designed.
3. `_execution_status` (`evaluation.py:164-174`) is exactly as §2.1
   describes. **Pre-existing asymmetry recorded for C3**: `_persist` reads
   `metrics` from `check_results[0]` only (`evaluation.py:187`) while the
   `exception_type` and reason scans iterate ALL results. C1 changes
   nothing here; C3's typed rule must reproduce today's output for every
   captured case regardless of this asymmetry, and the differential test
   is what will prove it.
4. `HealthCheckResult` had no validators before this commit, so the
   additive field + two validators are a clean addition.

**Bounded implementation decisions (none change the frozen contract).**

* *Manifest normalisation.* Reasons and metrics embed absolute fixture
  paths and non-finite floats, neither of which is byte-stable in JSON.
  The corpus rewrites the case's temp directory to `<WORKDIR>` and maps
  NaN/±Inf to explicit sentinels, then asserts the row survives
  `json.dumps(..., allow_nan=False)`. Without this the "manifest" would
  differ on every run and prove nothing.
* *Manifest records FULL normalised metrics, not only the keyset.* §4.1's
  implementation bullet says "metrics-keyset" while the validation plan
  says "metrics byte-equal"; recording both satisfies the stronger
  reading, and `metrics_keyset` is kept as an explicit field.
* *Corpus module placement.* The generator lives beside the manifest in
  `goldens/` as the design specifies; the reproducible invocations live in
  `tests/unit/execute_tools/health_checks/_verdict_corpus.py` so the
  generator AND the parity test share ONE definition of each case. Putting
  the cases in `goldens/` would have required making that directory a
  package.
* *Expected verdicts are transcribed independently.*
  `_verdict_corpus.classify_expected_verdict` implements §3.1 from the
  design text and never calls production code, so the parity test compares
  production against evidence production did not author.

**Honest corpus property.** The `FAILED` class is reachable only for the
three BLOCKING checks. The three recording-only checks
(`per_file_output_std`, `spectral_peak_ratio`, `pearson_dispersion`) pass
on numeric completion and fail only when every file failed I/O — which is
the ERROR class. So the corpus's 6 `failed` cases are all from the
blocking checks, by design and not by omission.

**Validation.** Health package 324 passed (rc=0, 1.75 s); consumer spot
check 74 passed (rc=0); manifest `--check` byte-identical; two `count==1`
mutations each proven load-bearing with caches cleared and `schemas.py`
restored byte-identically; `ruff check` + `ruff format --check` green;
`pyright` **not runnable locally** (Node `v10.19.0` too old for the
vendored bundle) — CI owns type checking for this change.

**Deviations from the frozen design: none semantic.** The one factual
correction is finding 1 above.

**Committed:** `ac580514` — *feat(step08a-c1): typed CheckVerdict +
capture-first verdict parity manifest*.

### C2 — `CheckInputDeclaration` + the pure applicability engine

**Status: IMPLEMENTED, validated, committed.**

Files: `execute_tools/health_checks/schemas.py` (declaration/facts/verdict
types + the pure `applicability()`), NEW
`execute_tools/health_checks/_regime_a_facts.py`, NEW
`tests/unit/execute_tools/health_checks/test_applicability.py`.

**Source findings.**

1. **The channel-group expectation is confirmed by execution, not by
   reading a literal.** `resolve_dataset_profile()` and
   `derive_tidmad_deliverable_spec(...).storage` were run and printed:
   `channel0001` / `channel0002`, `int8`, `value_offset=128`,
   `num_classes=256`, `num_files=20`, `sampling_frequency=1.0e7`.
2. **`value_scale_unit` is NOT derivable, and requiring it would break
   TIDMAD parity.** The design's §4.2/§4.4 expectation list includes an
   "mV scale presence" axis and expects `output_std` /
   `per_file_output_std` to declare "+ scale for std". Source says the
   millivolt scale is `_MV_PER_LSB = 40.0 / 128.0`, a module-level literal
   inside `output_std.py`, `per_file_output_std.py` and
   `pearson_dispersion.py` — **no `DatasetProfile` field declares it**.
   Consequences, both taken:
   * the regime-A deriver leaves the axis ABSENT rather than inventing a
     declaration the task never made (presence-discrimination doing its
     job);
   * therefore **no 08a check may declare a `value_scale_unit`
     requirement** — under regime-A facts that would make TIDMAD's two
     std checks `inapplicable`, i.e. silently stop running two production
     checks. That is a parity break, and parity is a frozen invariant.
   The axis still EXISTS on `TaskHealthFacts` so a task CAN declare it.
   Ownership of the scale moves with the thresholds in **08b**, where the
   checks' TIDMAD parameters become task-owned. Recorded here as the
   binding constraint on C4's declaration content.
3. Nothing else in the §4.2 expectation list required adjustment.

**Bounded implementation decisions.**

* *Logical context inputs, not raw field names.* `CONTEXT_INPUT_PREDICATES`
  exposes `denoised_source` / `target_source` / `file_vector` /
  `denoising_score`. `denoised_source` is satisfied by EITHER
  `denoised_paths` or `denoised_filename_fn`; declaring the raw fields
  would force every check to restate that disjunction. Matches the design's
  own §3.2 naming.
* *Opaque axis VALUES, framework-owned axis NAMES.* Family strings are
  compared for equality and never parsed, so a fourth task declares
  `"continuous_float"` (or anything else) with no framework edit — the
  same discipline parent §6.3 sets for view capability keys. There is no
  `EncodingFamily` enum, deliberately: a closed one would have to grow per
  task, which the forward invariant forbids.
* *Structural, not semantic, contradiction check.*
  `symbol_cardinality` without `encoding_family` is rejected; whether a
  given family "is symbolic" is deliberately NOT decided, because that
  would mean interpreting an opaque value.
* *`ApplicabilityVerdict` names the axis in a TYPED FIELD*, with a
  validator forbidding an inapplicable verdict that names none — so
  correctness never depends on reason prose (invariant 12), while the prose
  stays deterministic for the persisted record.
* *Reason strings carry no check-name prefix*; the runner adds it in C3 so
  the persisted prose keeps today's exact
  `"{check_name}: not applicable — …"` shape.
* *Module named `_regime_a_facts.derive_health_facts`*, not
  `derive_tidmad_health_facts`: the file contains no task name and needs
  none. The design's working title is honoured in substance (regime-A only,
  08b replaces the CALL SITE) and stated in the module docstring.

**A test defect found and repaired inside this commit.** The
unreachability guard initially passed **vacuously**: `REPO_ROOT` used
`parents[5]` (correct for the goldens generator, one level deeper) instead
of `parents[4]`, so `git grep` ran in `/home/yuema137`, failed, and
returned nothing — which the assertion read as "no callers". Repaired with
four independent defences (root assertion, exit-code assertion, a positive
probe that must find the definition, `--untracked`) and then
**mutation-proven** by adding a real call + import to `runner.py`: 2 of the
4 guard tests turn red, restored → 25 passed, `runner.py` byte-identical.
Recorded because it is precisely the "could the spy pass vacuously?"
failure class §9.4 warns about, and the same discipline applies to C3's
8.4-B spy.

**Validation.** Health package **349 passed, rc=0, 3.03 s**; C1 manifest
`--check` byte-identical at the C2 head (C2 changed no check behaviour);
`ruff check` + `ruff format --check` green; unreachability guard green and
mutation-proven. `pyright` not runnable locally (Node `v10.19.0`) —
CI-owned.

**Deviations from the frozen design:** one, recorded above and consequential
for C4 — the `value_scale_unit` axis is derivable by no task declaration
that exists today, so it is left absent and must not be required by any 08a
check. No semantic contract changes; parity is preserved, which is what the
frozen invariant protects.

**Committed:** `2d1c7b61` — *feat(step08a-c2): check input declarations +
pure applicability engine*.

### C3 — engine wiring + verdict transport (the behavioural commit)

**Status: IMPLEMENTED, validated, committed.**

Files: `runner.py` (pre-run applicability + `_resolve_task_facts`),
`evaluation.py` (typed `_execution_status`, `check_verdicts` persistence),
`schemas.py` (`PersistedHealthGateResult.check_verdicts`; `GateResult.passed`
and `get_target_path` docstring contracts), `candidate_eligibility.py`
(`_all_checks_inapplicable` + required-set exclusion), and test extensions in
`test_runner.py`, `test_campaign_evaluation.py`,
`test_candidate_eligibility.py`, `test_context_target_path.py`,
`test_applicability.py`, plus
`tests/unit/agent/tune_ml_hyperparam_agent/test_trial_validity_feedback.py`
and its new pre-08a golden.

**Source findings.**

1. **Consumer census (design item 1) — narrower than feared.** Three
   production callers: `execution.py:955`, `run_comparison.py:471`,
   `finalize_recovered_diagnostic_round.py:136`. **Nothing outside
   `health_checks/` reads `check_results`.** `policy.py:983` takes
   `list[GateResult]` (gate-level only). So the additive per-check field
   reaches consumers only via `PersistedHealthGateResult`.
2. **A contradiction INSIDE the frozen §4.3 bullet, resolved toward the
   frozen acceptance criterion.** The bullet specifies "ERROR if any verdict
   ERROR; `not_run` if all verdicts INAPPLICABLE **or the existing
   all-io-failed rule**". These cannot both hold: §3.1 row 3 derives
   `CheckVerdict.ERROR` for the all-io-failed class, so an "ERROR first"
   ordering moves that class from today's `"not_run"` to `"error"` — while
   the same section requires "output values byte-identical for every
   existing input", and §4.3's acceptance demands "100% identical over the
   corpus". Byte-identity is the stronger, twice-stated, and safer
   requirement (invariant 11: production defaults are out of scope), so the
   pre-08a rule ORDER is preserved exactly: exception → `"error"`;
   all-io-failed → `"not_run"`; all-inapplicable → `"not_run"`; else
   pass/fail. The consequence is explicit and documented in the function:
   an all-io-failed gate persists `execution_status="not_run"` while
   `check_verdicts` says `"error"`. That is what "additive" means here —
   the legacy field keeps its legacy meaning, and the honest four-way
   statement lives in the new one. **No frozen semantic was overridden; a
   local ambiguity was resolved toward the frozen acceptance criterion.**
3. **§5 expected a `get_target_path` docstring pin to upgrade; none
   existed.** Created instead (see the acceptance entry above).
4. **`tests/unit/nodes/` does not hold the feedback/eligibility consumers**
   — they are under `tests/unit/agent/tune_ml_hyperparam_agent/`. The §4.3
   verification command's path was corrected accordingly.

**Bounded implementation decisions.**

* *Declaration discovered by `getattr`, not by the Protocol.* `protocol.py`
  gains the attribute in C4; until then `getattr(skill, "declaration", None)`
  keeps C3 a strict no-op for the six shipped checks.
* *Facts resolved lazily, once per gate.* A gate of declaration-less checks
  resolves no profile at all (asserted), so C3 adds literally zero work to
  the TIDMAD path. `_resolve_task_facts()` exists so 08b has ONE call site to
  redirect.
* *`inapplicable_axis` in the result's metrics* so the deciding axis survives
  into the persisted record, not only into prose.
* *`check_verdicts` built from `check_results`*, i.e. the checks that
  produced a result — a short-circuited gate reports what ran rather than
  inventing entries for checks that never executed.
* *Eligibility exclusion is gate-level and evidence-gated.* Only a gate whose
  every verdict is `inapplicable` is excluded; a legacy record (field
  absent) and an empty verdict map both take the pre-08a path.

**The C2 unreachability guard was INVERTED, not deleted.** The design says
the grep-test is "removed in C3". Deleting it would have discarded a live
invariant, so it became `TestEngineIsWiredExactlyOnce`: production must call
`applicability` from exactly one place, and that place must be the runner. A
second call site would mean two policies deciding what "does not apply"
means — invisible to every behavioural test until they diverged. (It fired
correctly the moment C3 landed, which is how the inversion was prompted.)

**Validation.** Health package **371 passed, rc=0** (349 at C2 + 22 new).
Broader consumer sweep `tests/unit/execute_tools/health_checks/ +
tests/unit/agent/tune_ml_hyperparam_agent/ + tests/unit/agent/schemas/`:
**1 983 passed, rc=0, 444.7 s**. That sweep began before the final
docstring reword (a prose-only production change), so the targeted set was
re-run at the exact committed head: **475 passed, rc=0** across the health
package plus `test_trial_validity_feedback.py`, `test_gate_integration.py`
and `test_health_feedback.py`. Recorded this way rather than claiming the
1 983 figure for a head it did not run on.
`_execution_status` differential: 27/27 identical to the transcribed pre-08a
rule. 8.4-B spy: zero `run()` calls AND `h5py.File` monkeypatched to raise,
so a peek-then-skip implementation fails. Feedback byte-pin: captured from a
`git worktree` at `a37fd15d` and byte-identical (sha256
`32405904042f715df72ff28f2c9b30dc…`). C1 manifest `--check` byte-identical.
`ruff check` + `ruff format --check` green. `pyright` not runnable locally
(Node `v10.19.0`) — CI-owned.

**Prompt/PB delta: NONE** — the byte-pin is the executable proof, so the
frozen "Gate 1 NOT REQUIRED" disposition stands unchanged.

**Committed:** `aac9b3ba` — *feat(step08a-c3): wire applicability before I/O;
verdicts reach persistence*.

### C4 — the six checks declare their inputs

**Status: IMPLEMENTED, validated, committed.**

Files: the six check modules, `protocol.py`, `schemas.py`
(`classify_verdict` extraction), `runner.py` (explicit `verdict=` on the
Bug-B guard), NEW
`tests/unit/execute_tools/health_checks/test_check_declarations.py`.

**Source findings.**

1. **`spectral_peak_ratio` does NOT read the target channel.** It peeks
   `channel0001` of the DENOISED path only (`:74`) and computes a PSD;
   the only thing it takes from the profile is
   `dataset.sampling_frequency` (`:55`). The design's §4.4 expectation
   ("spectral = target peek") is refuted by the code. Its declaration is
   therefore `tidmad.int8_prefix_peek` + `sampling_frequency_hz`, with NO
   `target_source`. Had the expectation been coded as written, spectral
   would have gone inapplicable on any task lacking a target channel —
   for a signal it never reads.
2. **`pearson_dispersion` confirmed** as the only two-channel check
   (`channel0001` denoised vs `channel0002` target, `:79-80`).
3. **Neither recording check has a threshold.** `per_file_output_std`,
   `spectral_peak_ratio` and `pearson_dispersion` read only
   `peek_samples` and `peek_file_indices`; they pass on numeric
   completion. So `threshold_parameter_names` is `("peek_samples",)` for
   all three — declaring a threshold they do not read would have sent
   08b's migration after a parameter that does not exist.
4. **`target_path_fn` is supplied at EVERY production construction site**
   — `execution.py:949` (a `def`, never None), `run_comparison.py:465`,
   `official_paper_health_scan.py:141`, `fcnet_health_metrics_scan.py:73`.
   So pearson's new `target_source` requirement never fires in
   production, and the persisted record for that gate is unchanged.
   Without this check, C4 could have silently altered a persisted metrics
   dict on a path nobody exercised in unit tests.

**Bounded implementation decisions.**

* *`classify_verdict` extracted to `schemas.py`.* Three peek-based checks
  derive their verdict from an aggregation outcome; transcribing §3.1
  into each would have created the drift `_multi_file_peek` exists to
  prevent. The C1 compatibility validator now delegates to the same
  function, so bridge and production share ONE rule. (C4's scope list
  names the check modules and `protocol.py`; touching `schemas.py` for a
  shared classifier is the narrower change than six copies, and it
  strengthens R-08a-1 rather than widening scope.)
* *Unambiguous returns state a literal verdict* (`CheckVerdict.INAPPLICABLE`
  on the defensive NA paths, `PASSED` on numeric completion); only
  outcome-derived returns call the classifier.
* *The Protocol requires `declaration`; the runner stays tolerant.*
  `pyrightconfig.json` excludes `tests`, so a required Protocol member
  breaks no test typing, and the runner's `getattr` keeps pre-08a and
  externally supplied checks working as unconditionally applicable. The
  mismatch is deliberate and documented on the Protocol.
* *In-check NA returns kept and marked defensive-only* — they are now
  unreachable through `evaluate_gate` but remain correct for direct
  callers, which is what keeps the C1 manifest (a direct-call corpus)
  byte-identical.

**Validation.** Health package 371 passed before the new tests, 475 passed
with them (rc=0). C1 manifest `--check` byte-identical at the C4 head —
declarations and explicit verdicts perturbed no captured value. Both
directions of the axis proven per check: applicable under derived TIDMAD
facts, inapplicable under declared-float facts naming `encoding_family`.
A six-check gate under contrast facts returns all-inapplicable, takes
`on_pass`, and opens no HDF5 file (`h5py.File` patched to raise), with
**no result carrying `PASSED`** — the executable form of "inapplicable is
not pass". `ruff` clean; `pyright` CI-owned.

**Deviations:** finding 1 (a refuted design expectation, resolved toward
source) and the `classify_verdict` extraction. Neither changes a frozen
semantic; both are recorded above.

#### C4 CORRECTION — `threshold_parameter_names` semantics (operator review, 2026-08-19)

**Defect, found by the operator in code review, not by any test.** C4's own
source audit recorded that `per_file_output_std`, `spectral_peak_ratio` and
`pearson_dispersion` have **no threshold** — they pass on numeric completion
and fail only when every file failed I/O — and then declared
`threshold_parameter_names=("peek_samples",)` for all three anyway. The
three blocking checks likewise carried `peek_samples` beside their real
threshold.

That does not follow. `peek_samples` is a config parameter the check
**reads**; it is not a threshold. Nothing in any check's predicate compares
against it — verified: `output_diversity` decides on `m > min_unique`,
`output_std` on `m >= min_std_mv`, `amplitude_collapse` on
`m <= collapse_threshold`, and the three recording checks have no predicate
at all.

**Why it mattered, and why it had to be fixed in 08a rather than noticed in
08b.** The frozen field means "which config keys are TASK THRESHOLDS", and
**08b consumes exactly this metadata to migrate parameters into task-owned
config**. Shipping the wrong classification would have frozen a wrong
ownership decision into a task config, and would have silently widened the
frozen contract to `threshold_parameter_names ≈ task_parameter_names` for
every future task.

**Why the existing test could not catch it.**
`TestDeclarationsMatchWhatTheCheckReads` asserts only

```text
threshold_parameter_names  ⊆  the keys run() actually reads
```

which any read key satisfies. It proves the declared parameter is *read*;
it cannot distinguish a threshold from a sampling width. A green CI was
therefore never going to surface this.

**Fix.**

| check | before | after |
|---|---|---|
| `output_diversity` | `("min_unique_int8_values", "peek_samples")` | `("min_unique_int8_values",)` |
| `output_std` | `("min_std_mv", "peek_samples")` | `("min_std_mv",)` |
| `amplitude_collapse` | `("collapse_threshold", "peek_samples")` | `("collapse_threshold",)` |
| `per_file_output_std` | `("peek_samples",)` | `()` |
| `spectral_peak_ratio` | `("peek_samples",)` | `()` |
| `pearson_dispersion` | `("peek_samples",)` | `()` |
| `sample_dispersion_floor` | `("min_dispersion",)` | unchanged — a real threshold |

`peek_samples` is NOT promoted to some other declaration field. If 08b
decides task-owned health config should own non-threshold parameters, that
is 08b's problem to solve with the right ownership concept — not by
mislabelling them here.

**New test — `TestThresholdParameterNamesMeansThreshold`** (6 tests): the
exact threshold tuple per check, transcribed from each predicate by reading
source; a named assertion that no check declares `peek_samples` /
`peek_file_indices` / `aggregation` as a threshold; recording-only checks
declare `()`; blocking checks declare exactly one non-policy key; the
fixture check keeps its real threshold; and every declared threshold name
must actually appear in the check's `run` source.

**Mutation proof that the new test is load-bearing AND that the old one is
blind** — the original defect was reinstated in `per_file_output_std`:

```text
new semantic test  -> 3 failed, 13 passed   (catches it)
old subset test    -> 13 passed             (structurally blind, as argued)
restored           -> 51 passed, file byte-identical
```

**Gate 2 is NOT re-run, and this is why.** The change is metadata-only:
* the entire production diff is six `threshold_parameter_names=` lines plus
  comments (`git diff --stat`: 6 files, +16/−6, all within the declarations);
* `applicability()` reads only `required_context_inputs` and
  `required_facts` — **never** `threshold_parameter_names` (verified by
  reading the function);
* the field has **no production consumer at all** (verified by repository
  grep — only the declarations, the schema field, and tests).

So applicability facts, runtime execution and persisted behaviour are
untouched, and the Gate-2 evidence captured at `7ae72ae5` continues to
describe this code. The C1 manifest re-verified byte-identical after the
fix, which independently confirms no check's behaviour moved.

**Validation after the fix.** Health package + tuner feedback + health
feedback + step02c live consumers: **525 passed, rc=0**. C1 manifest
byte-identical. `ruff check` + `ruff format --check` green.

**Committed:** `ab9b5909` — *feat(step08a-c4): the six checks declare what
they consume*.

### C5 — TIDMAD peek routed through the Deliverable Contract

**Status: IMPLEMENTED, validated, committed.**

Files: `_peek.py`, `_multi_file_peek.py`, the six check modules,
`test_peek.py` (two new test classes; no existing case modified).

**Source findings.**

1. **The contract's TIDMAD values equal the literals** — confirmed by
   running the resolution, and now pinned as a test.
2. **`peek_int8_at_channel` already took `channel` as a parameter.** The
   only literals were `peek_int8_at_path`'s hardcoded argument, the
   `channel="channel0001"` DEFAULT at `_multi_file_peek.py:177`, and the
   six checks' call sites. The primitive itself needed no signature change.
3. **The `"timeseries"` group-walk literal has no owning authority and
   stays.** §3.5 says the peek should stop hardcoding "walk literals", but
   `DeliverableStorage` owns channel groups, dtype and offset, and
   `DeliverableNaming` owns filenames — **nothing owns the in-file group
   path**. Inventing a field for it would be a new contract surface, i.e.
   08b/D14-adjacent scope. Recorded as a bounded finding: 08a removes
   every literal that HAS an owner, and the walk literal is deferred with
   its reason, not silently ignored.
4. **`default_deliverable_storage()` already is the regime-A adapter**
   (`deliverable_spec.py:314`), so the "one spec resolution per `run()`"
   instruction needed no new helper.

**Bounded implementation decision — `channel` defaults to `None`, not
required.** §4.5 says the default should be "removed/required". Making it
required would force edits to **19 pre-existing call sites** in
`test_multi_file_peek.py`, which §5 disposes as KEEP. Instead the
parameter accepts `None` and resolves from the contract, which:
(a) removes the literal from the module, which is the actual goal;
(b) leaves all 19 kept tests untouched and passing;
(c) reproduces verbatim the precedent `deliverable_spec.py:314-329`
documents for `create_abra_file` — every production call site supplies the
channel explicitly, while a caller predating the parameter still reads
exactly what it read before. Production checks all pass it explicitly.

**Validation.** Health package **412 passed**, +step02c live consumers
**428 passed**, rc=0. Byte parity proven against an INDEPENDENT oracle
(hashes computed from the generator that wrote the fixture, not captured
from the peek), validated at the PRE-C5 tree first and re-verified after
the swap; the two channels' hashes are asserted to DIFFER so a channel
swap cannot pass. C1 manifest byte-identical. Literal pin green with its
own anti-vacuity companion. `ruff` clean; `pyright` CI-owned.

**Committed:** `7e25e541` — *feat(step08a-c5): TIDMAD peek reads channel
identity from the contract*.

### Gate 2 — specification, written BEFORE launch (§4.0a)

**Claim.** On the REAL TIDMAD production path, health gates still fire at
the round boundary; every `PersistedHealthGateResult` carries the new
`check_verdicts`; all six TIDMAD checks report `passed` or `failed` and
**never** `inapplicable`; actions/severity match pre-08a behaviour for the
same outcomes; the run completes with the standard record set.

**Why a Gate owns this.** Unit tests supply a `HealthCheckContext` by
hand. Gate 2 is the only layer where the context is BUILT by the tuner
from a real round — real `denoised_filename_fn`, real `target_path_fn`,
real profile resolution — and where the applicability step therefore
faces the inputs production actually produces. A fixture cannot establish
that the six checks are applicable *in production*; it can only establish
that they are applicable given a context a test wrote.

**Exact HEAD.** `7ae72ae5` (C6), clean tree.

**Command** — the gate standard's canonical cold-start shape, with two
deviations recorded below:

```bash
bash sdsc_submission_scripts/run_chain.sh \
    --mode lilab \
    --workspace /tmp/gate2_step08a_<ts> \
    --run_name gate2_step08a \
    --num_iterations 1 \
    --max_rounds 1 \
    --max_proposal_attempts 3 \
    --max_epochs 1 \
    --data_scope 4-9 \
    --health_gate_files 4,5,6,7,8,9 \
    --validation_max_portion 0.01 \
    --validation_max_train_samples 2000 \
    --no-force_formal_round \
    --trial_vram_budget_gb 16 \
    --formal_vram_budget_gb 16 \
    --llm_config llm_configs/openai_tiered_pro.json
```

No `--seed_paths` — cold-start, per the CLAUDE.md rule. The paired
`--data_scope` / `--health_gate_files` is the DS8 partial-scope
requirement, and it is also what puts the health gates on the scoped
files.

**Deviation 1 — `--runtime_watchdog` and `--validation_max_phase_seconds`
OMITTED (source-grounded).** The canonical command includes them, but the
07a Gate-2 record states the watchdog killed 3 of 4 attempts INSIDE the
un-priced validation pass, and that watchdog-enabled real campaigns are
not a reliable configuration until 07c lands. **07c is not implemented at
this head** — verified in source: `core/runtime_control/admission.py`
still documents "the prephase measurement covers `phase="training"`
only". Including a component known to be flaky, and unrelated to the
health-verdict claim, would manufacture INCONCLUSIVE runs. The gate
standard's own §85 rule requires dropping
`--validation_max_phase_seconds` alongside the watchdog, which is done.

**Deviation 2 — VRAM budgets 24 → 16 GB.** The RTX 5090 is shared and
another user's job holds ~5.8 GB at ~79% utilisation. 16 GB leaves clear
headroom so this run cannot OOM a colleague's work, and the bounded
workload (2 000 validation samples, 1 epoch, 1 round) needs far less.
"The Gate harness owns the amount of real work" — this only lowers that
ceiling.

**Bounded scope.** 1 iteration · 1 round · 1 epoch · 6 of 20 files ·
≤2 000 validation samples · ≤3 proposal attempts. Expected wall time
≤10 min; hard stop and classify at 20 min (GPU contention could stretch
it). Modest LLM spend on `openai_tiered_pro.json`.

**Expected PASS evidence** (read from artifacts, never from exit code):
per-round `health_gate_results` present; every entry carries a
`check_verdicts` dict; the union of verdict values ⊆ `{passed, failed}`;
`execution_status` ∈ `{passed, failed}`; `resolved_action` consistent with
each gate's configured action; a completed `run_output_*.json`.

**Expected FAIL modes.** Any check reporting `inapplicable` (would mean
the regime-A facts do not satisfy a shipped declaration on the real path —
a parity break); `check_verdicts` absent from a persisted result; a gate
that fails to fire.

**INCONCLUSIVE modes.** LLM provider outage; no candidate surviving 3
proposal attempts; a crash before the round boundary; GPU contention
preventing training. Any of these means the health path was not exercised
and the run proves nothing either way.

**Evidence destination.** Workspace records under the run workspace, with
the decisive fields extracted into this ledger.

### Gate 2 — RESULT: **PASS**

Executed at HEAD `7ae72ae5`, clean tree. Workspace
`/tmp/gate2_step08a_1787103998`; durable evidence copied to
`/home/klz/Data/SIDEREIS_DATA/step08a_gate2_evidence_20260819/`
(record JSON, `health_checks_effective.yaml`, full chain log).
`CHAIN_RC=0` — **and the verdict below comes from the persisted record,
not from that exit code.**

**The run was counterfactual-discriminative, which is what makes it
evidence.** The real LLM's first candidate failed validation on an
in-place-op backward error (the model's defect, not this PR's path); a
later candidate trained for real (Epoch 0, avg loss 3.551, validation loss
4.376 over 7 500 ML segments) and then **genuinely collapsed** — 10–11
unique int8 values against a `>25` threshold and 0.293–0.325 mV std against
a `>=1 mV` floor. So the gates had something real to object to.

Persisted `health_gate_results` at
`records/iter_001/midstack_fourier_gated_tcn_coldstart_iter_001_001.json`
(`exp_id=…_iter_001_001`, `status=failed_mode_collapse`, `is_trial=True`,
`denoising_score=-4.196141447518896`):

| gate | execution_status | check_passed | resolved_action | `check_verdicts` |
|---|---|---|---|---|
| `output_diversity_blocking` | failed | False | `invalidate_round` | `{"output_diversity": "failed"}` |
| `output_std_blocking` | failed | False | `invalidate_round` | `{"output_std": "failed"}` |
| `amplitude_collapse_blocking` | passed | True | `continue` | `{"amplitude_collapse": "passed"}` |
| `pearson_dispersion_recording` | passed | True | `continue` | `{"pearson_dispersion": "passed"}` |
| `spectral_peak_ratio_recording` | passed | True | `continue` | `{"spectral_peak_ratio": "passed"}` |
| `per_file_output_std_recording` | passed | True | `continue` | `{"per_file_output_std": "passed"}` |

**Every PASS criterion, checked against that table:**

- [x] gates fire at the round boundary — all **6/6** present.
- [x] every `PersistedHealthGateResult` carries `check_verdicts` — **6/6**.
- [x] all six TIDMAD checks report `passed`/`failed` and **never
      `inapplicable`** — the union of verdict values is exactly
      `{"failed", "passed"}`. This is the decisive one: it proves the
      declarations added in C4 are satisfied by the regime-A facts on the
      REAL path, with a context the tuner built rather than a test.
- [x] actions/severity consistent with configuration — blocking gates that
      failed resolved `invalidate_round`; everything that passed resolved
      `continue`; roles (`blocking` / `observational`) unchanged.
- [x] run completes with the standard record set — record, summary,
      `run_output_iter_001.json`, `health_checks_effective.yaml` and
      `run_invariants_lock.json` all materialized; DataScope confirmed
      `files=[4,5,6,7,8,9] health_gate_enabled=True monitored=[4..9]`.

**Not a vacuous all-pass.** Two checks failed and four passed *in the same
round*, so the per-check verdict transport is carrying genuinely different
outcomes rather than one repeated value — precisely what a uniform result
could not have established. `status=failed_mode_collapse` is a real health
outcome reached through the new path.

Wall time ~11 min for the whole chain including three proposal attempts and
two LLM implementor rounds; the bounded training itself was ~23 s. Within
the approved envelope. No shared-GPU disruption: the run held well under
the lowered 16 GB budget while another user's job continued.

### C6 — 8.4-C minimal check + rung fixtures + docs sync

**Status: IMPLEMENTED, validated, committed.**

Files: NEW `execute_tools/health_checks/sample_dispersion_floor.py`, its
registration in `__init__.py`, NEW
`tests/unit/execute_tools/health_checks/test_step08_44_rungs.py`,
`docs/design/pluggable_health_checks.md` (§6a, §8 box, §9.3, §10).

**Source findings.**

1. **The parent design contains no checkboxes.** §4.6 instructs "parent
   §12 08a checkbox ticked"; `grep` over the frozen parent returns zero
   `[ ]`/`[x]` markers. Nothing was invented; parent/roadmap status
   synchronisation is a merge-lifecycle action, not a stacked child's.
2. **`default_deliverable_storage` and the registry needed no changes** to
   accommodate a seventh check — the bootstrap is a plain tuple.

**Bounded implementation decision — the fixture check takes its samples
from its own config.** §3.6 says it "computes a dispersion floor over the
fixture samples" without saying how they arrive. The candidates were:
* `ctx.file_vector` — **rejected**. Parent §5 and guardrail §13 forbid a
  NEW check consuming golden-metric output, and `file_vector` is
  metric-derived per-file magnitude. Using it would have earned the
  census refusal the guardrail exists for.
* a float view provider — **rejected as 08b scope**; inventing half a
  provider mechanism to serve one fixture is precisely the creep §4.0
  forbids.
* config-supplied samples — **chosen**. The check is explicitly
  fixture-scoped and referenced by no production YAML, so its inputs
  arriving through its own config is honest rather than a shortcut. Its
  view key `step08.fixture_continuous_samples` is deliberately spelled
  plugin-local to demonstrate parent §6.3's opaque-key claim in
  miniature.

**Validation.** Health package **424 passed, rc=0** (412 at C5 + 12 rung
tests). The arithmetic has a hand-computed oracle (`0.0` and `sqrt(5)`),
the threshold is proven load-bearing by running one dataset against two
floors, and an empty/absent sample set is `ERROR` rather than a pass. Both
rungs share ONE gate evaluation, and the pair is strengthened by two
assertions the design did not require but the claim does: the gate
actually **takes `INVALIDATE_ROUND`**, and **no result in the gate carries
`PASSED`**. The axis is proven in both directions (the new check is
`INAPPLICABLE` under TIDMAD). `test_step00_health_config_baseline.py` is
untouched and green. `ruff` clean; `pyright` CI-owned.
