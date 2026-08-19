# PR 08a — check input contract + applicability (child design)

## 0. Status and provenance

**DRAFT rev 1 — READY FOR OPERATOR REVIEW (2026-08-18).** Child of the
FROZEN Step-08 parent (`step_08_health_check_task_profile.md`, rev 3,
operator ruling 2026-08-18). Source audit at master `38c8fd0c`. This
child changes NO ownership, NO YAML layout, NO prompts, NO registry
mechanics — those are 08b/08c. Implementation begins only after this
design is frozen.

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
| `_multi_file_peek.py:260` | `passed=True, reason="not applicable — no path configured in context"` (`:28`, `:107` document the same) |
| `spectral_peak_ratio.py:62` · `per_file_output_std.py:53` | `reason=f"{self.name}: not applicable — no files in context"` |
| `output_diversity.py:22,80` | routes the multi-peek NA pass through |
| `evaluation.py:173` | **the string sniff**: `… or "not applicable" in reasons → "not_run"` — persistence already reverse-engineers the honest verdict from prose |

The dishonesty is precisely located: the RUNTIME verdict says
`passed=True` (indistinguishable from health in `evaluate_gate`'s
`gate_passed = all(r.passed …)`, in eligibility inputs and in any
counting), while the PERSISTED `execution_status` already wants —
and string-matches its way to — `"not_run"`.

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

### 2.4 The peek plumbing and its literals

`_peek.py`: hardcoded walk `timeseries/<channel>/timeseries`
(`:86`), channel names `"channel0001"`/`"channel0002"` (`:92-100`,
callers). `_multi_file_peek.py`: `peek_and_aggregate(…)` (`:170`),
`PerFilePeekResult`/`MultiFilePeekOutcome` (`:46`, `:79`), index
resolution `_resolve_indices` (`:113`). The Deliverable Contract already
owns exactly these facts: `DeliverableStorage.input_channel_group` /
`target_channel_group` / `storage_dtype` / `value_offset`
(`deliverable_spec.py:226-235`) and `DeliverableNaming`
(`:85`, prefix/extension/index_width); regime-A derivation
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
  (`:134`), UNKNOWN discipline (`:46`, `feedback.py:145-175` named
  absence). Parent §7: an inapplicable check is EXCLUDED from the
  required set; an errored one is NOT.
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
| `passed=True`, reason contains the NA marker (constructor-supplied during migration only) | `INAPPLICABLE` |
| `passed=False`, `metrics.exception_type` or `io_error`-classed | `ERROR` |
| `passed=False` otherwise | `FAILED` |

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
  `check_verdicts: dict[str, str] | None` (check_name → verdict).
  Existing fields byte-identical (parent §8). [Q-08a-1 below.]
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

## 4. Commit decomposition

**C1 — verdict vocabulary + capture-first parity manifest.**
`CheckVerdict`; additive `verdict` on `HealthCheckResult` with the
back-compat derivation (§3.1); the committed capture manifest: the six
checks run over the EXISTING test fixtures, `HealthCheckResult` fields
captured BEFORE any behavioural commit (the D14-1 discipline — expected
values never recomputed by new code). DoD: all existing health tests
green untouched; manifest committed; derivation-mapping tests (one per
row of the §3.1 table) red-green proven.

**C2 — `CheckInputDeclaration` + the applicability engine (pure).**
Schema + `applicability(...)` + regime-A fact derivation
(profile + Deliverable Contract, presence-discriminated). Pure-function
unit tests: TIDMAD facts → six× applicable; contrast facts → int8
family inapplicable naming the encoding axis; absent context input →
inapplicable naming the input. DoD: no production wiring yet (engine
unreachable = stated), tests prove the comparison logic in isolation.

**C3 — engine wiring + verdict transport.** `evaluate_gate` pre-run
applicability (§3.3); `_execution_status` typed (string sniff deleted);
additive `check_verdicts` persistence; eligibility exclusion rule;
feedback byte-stability pin. DoD: 8.4-B with the no-file-opened +
no-`run()`-called spy; differential `_execution_status` test over
captured outcomes; TIDMAD required-set unchanged; reachability —
a test that FAILS if `evaluate_and_persist_health_gates` reaches a
skill without the applicability step (bypass-detection per the
CLAUDE.md boundary rule).

**C4 — the six checks declare inputs.** ClassVar declarations; every
production constructor passes `verdict=` explicitly; in-check NA
returns become defensive typed returns (reachable-only-defensively,
asserted); protocol.py + schemas.py docstrings superseded citing the
parent. DoD: C1 manifest byte-identical modulo the additive field
(script-compared); per-check tests updated ONLY where they pinned the
NA-as-pass prose (disposition table §5).

**C5 — peek re-plumb through the Deliverable Contract** (§3.5).
DoD: pre/post identical-bytes fixture proof; C1 manifest re-verified;
zero `"channel0001"`/`"channel0002"` literals left in
`_peek.py`/`_multi_file_peek.py` (grep pin; `evaluation.py`'s persisted
label exempted by name).

**C6 — 8.4-C minimal check + rungs + docs.** `sample_dispersion_floor`
(§3.6) with hand-computed arithmetic tests; the 8.4-B/8.4-C rung pair
as named fixtures; docs sync (`pluggable_health_checks.md` §6/§8
amendment notes, this design's §10 ledger, parent §12 08a checkbox) as
the last pre-review step. DoD: 8.4-C fires AND fails on the constant
fixture; all targeted suites green; ledger complete.

Per the split-commit rule, any C may split into `-code`/`-docs` at
clean boundaries preserving the last split's DoD.

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
  outcomes; run completes with the standard record set. Command shown
  for operator approval before launch.

## 8. Risks / open questions

* **Q-08a-1 (operator, at review)**: the additive persisted field —
  proposed as a typed optional `check_verdicts: dict[str, str] | None`
  on `PersistedHealthGateResult` (this design), the alternative being
  verdicts inside the existing `metrics` dict. Typed field preferred:
  records are read by resume/interpretation tooling and a dict key is
  a silent contract. Additive-optional keeps parent §8 ("record fields
  unchanged" = existing fields).
* **Q-08a-2 (confirm)**: a gate whose checks are ALL inapplicable takes
  `on_pass` (never blocks — parent §7) while persisting
  `execution_status="not_run"` + verdicts; eligibility sees the
  blocking check excluded from the required set. This is exactly
  today's TIDMAD-invisible path made honest; flagged because "takes
  on_pass" could be misread as "counts as pass" — it does not: counting
  surfaces read verdicts.
* **R-08a-1**: the §3.1 back-compat derivation could linger as a second
  truth source — bounded by the C4 explicit-verdict DoD + the
  reachable-only-defensively assertion.
* **R-08a-2**: C5 could drift a read byte — bounded by capture-first
  parity re-verified at C5 and the fixture identical-bytes proof.

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
   baseline test stays untouched-green.
7. *Is the string-sniff deletion safe?* Differential test over the C1
   captured corpus — same outputs, new derivation.
8. *New check discipline?* Exactly one, fixture-scoped, named by the
   roadmap ladder (8.4-C), full family deferred to 08c.

## 10. Ledger

*(filled per commit during implementation)*
