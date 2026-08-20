# Step 10 / P4 — Health Evidence Declaration Migration

## 0. Status

**REVISION 3 — FROZEN. IMPLEMENTED. MERGED 2026-08-20.
CONTEXT CLOSED.**

| field | value |
|---|---|
| PR | **#243** (squash) |
| final executable head | `d57d2482` |
| final PR head | `d73e39e3` |
| exact-head CI | **32426702255 — SUCCESS** (lint · ruff-format · pyright · 11,072 passed / 32 skipped / 0 failed, read from the log) |
| squash SHA | **`79833db8`** |
| resulting `origin/master` | `79833db8` — verified **byte-identical** to the validated head |
| independent final review | **PASS**, no corrections required (operator-authorized, 2026-08-20) |

Implemented on `step10-p4-health-evidence-declaration-migration-impl`, cut
from this document's freeze commit `d44f6f6a`. The frozen semantics were NOT
re-litigated during implementation; §19 records what was built against them.

**Carried forward, unimplemented by design (Q-P4-3):** **HD-T5** (Health
representative-evidence declaration capability) and **HD-T6** (Health
LLM-advice declaration capability) — named post-Step-10 Health-capability
debt, explicitly NOT P6's and NOT assumed to be Step 12's.

Rev 1 (DRAFT, architecture review PASSED 2026-08-20) was written against the
parent's §3.5 table and reproduced its boundary: *three name-keyed tables in
`execute_tools/health_checks/evaluation.py`*. Rev 2 executed the post-P1
reconciliation required by rev 1 §14 against merged `master` `64446b2b`
(production tree unchanged since the P1 squash `bcb17e45`) and found four
things that boundary did not cover:

* the five §2.1 sites, confirmed, with two line anchors off by one (§2.1);
* **three further name-keyed surfaces of the identical failure class**,
  downstream of `evaluation.py` and outside S6's *enumerated* boundary
  (§2.2 — T4, T5, T6, plus the L2 unit literal), on the live production
  path, re-imposing the same silence on Pets and DAVIS *after* the
  `evaluation.py` migration has done its work;
* a **duplicate unit authority** rev 1 would have relocated rather than
  removed: the `mV` in T1/T3 is a third copy of the task-owned
  `value_scale.unit` (§2.3, U1);
* a **false premise in Q-P4-1**: the "absent config key" state rev 1
  proposed to name does not mean the check thresholded on nothing — it
  means the check thresholded on its own private `_DEFAULT_*` ClassVar,
  so "named absent" evidence would *misreport* what the gate actually did
  (§2.4, D1).

**Rev 3 applies the operator rulings of 2026-08-20 (§12).** Q-P4-1 = **(a)
with fallback-only labelling**; Q-P4-2 = **YES, absorb T4/L2 as a
derivation**; Q-P4-3 = **DEFER BOTH, NAMED**; C-P4-1 = **resolved by a
minimum parent scope-completeness correction** that leaves the semantic
owner, the seven-child decomposition, the scientific Health semantics, the
public result schema and P4/P2a parallelism unchanged. **Open operator
questions = 0. Material contradictions = 0.** P4 is frozen.

| field | value |
|---|---|
| parent | Step-10 parent REVISION 2 (frozen), §3.5 / §4.1 / §13; owns scope item **S6**, whose enumeration receives the §12 completeness correction |
| source anchor | merged `master` = **`64446b2b`**; production tree identical to the P1 squash `bcb17e45`. Every site in §2 re-verified at this anchor. **Anchors are evidence, not authority** — re-verify at the implementation branch head |
| depends on | nothing unmerged. P1 (merged) supplies the composed Health binding used to DEMONSTRATE on a second task; Step 08's declaration/plugin architecture is the substrate |
| downstream | **P6** — contrast-task loop runs produce COMPLETE persisted AND LLM-facing Health evidence once this lands |
| Gate disposition | **Gate 1 NOT REQUIRED · Gate 2 NOT REQUIRED** (§8) — P4 remains a deterministic declaration-ownership migration, which the Q-P4-3 deferral preserves |
| open operator questions | **0** (§12) |
| material contradictions | **0** (§12) |
| P2a parallel-overlap verdict | **SAFE TO IMPLEMENT IN PARALLEL WITH P2a, WITH NORMAL POST-MERGE SOURCE RECONCILIATION** (§16); competing semantic owners = **0** |

**Operator architecture-review verdict (2026-08-20), recorded verbatim and
still standing**: architecture coherent; **likely independent Health lane**
confirmed (P1 → P4 → P6, parallel to the main semantic lane); **no fake
central registry** — the per-check-declaration + registry-resolution shape
passed the review's anti-pattern check. The reconciliation does not disturb
that verdict: the declaration-driven mechanism is confirmed correct by
source. What it disturbs is the *extent* of the surface that mechanism must
cover.

---

## 1. Parent contract (recovered, binding)

* **§3.5**: Step 08 finished Health OWNERSHIP migration except
  `execute_tools/health_checks/evaluation.py`, which still holds **three
  tables keyed on TIDMAD's check NAMES** plus a duplicated default constant
  and a sampling-method literal. The failure mode is **silence**: a
  task-owned check absent from the tables persists evidence with no
  threshold, no metric name, no unit — "the gate still fires and still
  blocks correctly; its evidence is quietly poorer than TIDMAD's".
* **§4.1 (FROZEN)**: every scope item has exactly one owning child, "no
  orphan scope item", and — quoted — *"if the post-merge reconciliation
  changes it, it is revised **before** any child freezes."* **§2.2 was
  exactly that case, and the operator applied the correction before this
  freeze (§12, C-P4-1).** Note the precision: §4.1's own map row already
  reads "Health evidence declaration migration" and needed **no** edit; the
  narrow implementation enumeration lived in §4's S6 authority column and
  §13's scope line, and only those two were corrected. S6 keeps exactly one
  owning child.
* **§13 constraints (frozen)**: NO Health scientific semantics change —
  verdicts, actions, severity resolution and thresholds bit-identical for
  TIDMAD; a task-specific check requires NO central-table edit; extending
  `CheckInputDeclaration` ONCE is allowed (a new *capability*, not a new
  *task*); the `:89` / `tidmad.yaml` disagreement is repaired **by removing
  the duplicate**, never by editing one side to match.
* **§7.2**: a new *task instance* must cost zero framework edits; a new
  *backend capability* may legitimately require framework work. P4 is where
  that line is most tempting to blur, and §11 restates it.
* **§20.3**: P4 is independent — "needs P1 only to *demonstrate* on a
  second task" (P1 has merged, so nothing blocks P4).
* Known live latent defect (parent §3.8 tail): Pets declares
  `categorical_distinct_symbols`/`categorical_dominant_fraction` and DAVIS
  declares `sample_dispersion_floor`, and NONE is in any table — unbitten
  only because the D14 Gate runners bypass `evaluation.py`. The moment a
  contrast task routes through the tuner (P6), its persisted health evidence
  goes blank. P4 exists so P6 does not inherit that.

---

## 2. Current source audit (measured at `64446b2b`)

### 2.1 The residual central tables in `evaluation.py` — re-verified line-exact

Two anchors moved by one line versus rev 1; the content is unchanged.

| # | site (rev 1 → **verified**) | shape | task-specific content |
|---|---|---|---|
| T1 | `evaluation.py:84-107` → **`:84-106`** `_threshold(check_name, config)` | `if check_name == "output_diversity": … elif "output_std" … elif "amplitude_collapse" …` | per-check: evidence metric name, comparison OPERATOR (`>`/`>=`/`<=`), config KEY, UNIT, and a hardcoded DEFAULT (`5`, `1.0`, `0.95`) |
| T2 | `evaluation.py:117-124` → **`:116-123`** | dict of SIX check names → per-file metric names | names |
| T3 | `evaluation.py:124-131` — **confirmed exact** | dict of six check names → units (`count`/`mV`/`fraction`/`correlation`/`ratio`) | units |
| L1 | `evaluation.py:158` — **confirmed exact** | `"sampling_method": "channel0001_prefix_peek"` — one literal for EVERY check's per-file rows | a TIDMAD channel label applied universally |
| D1 | `evaluation.py:89` — **confirmed exact** | `config.get("min_unique_int8_values", 5)` | a duplicated default — see §2.4, where its true provenance is corrected |

**Consumers — evidence only, never verdicts (confirmed).**
`_per_file_metrics` is called at `:216` and `_threshold` at `:263`, both
inside the construction of `PersistedHealthGateResult` (`:203-267`). The
gate's PASS/FAIL comes from the TYPED check results; the tables feed only
the persisted EVIDENCE. Rev 1's scoping claim holds: **P4 is an evidence
migration; actions/verdicts are structurally untouched.**

**A structural invariant P4 inherits and must not silently widen**: both
consumers read `result.check_results[0]` and `gate_config.checks[0].config`
— one check per gate. That is guaranteed by composition
(`_composition.py:280` emits `"checks": [{…}]`, exactly one entry per roster
row). P4 renders per-check declarations for that one check; it does not
introduce multi-check evidence.

**The declaration substrate already exists (Step 08), confirmed at anchor.**
`CheckInputDeclaration` (`execute_tools/health_checks/schemas.py:880`):
frozen model with `consumes_view`, `requires_view`,
`required_context_inputs`, `required_facts`, and
`threshold_parameter_names` (`:927`) — the last one populated by every
shipped check (`output_diversity.py:64`, `output_std.py:91`,
`amplitude_collapse.py:80`, `sample_dispersion_floor.py:65`,
`categorical_distinct_symbols.py:51`, `categorical_dominant_fraction.py:52`,
and `()` at `pearson_dispersion.py:95`, `spectral_peak_ratio.py:102`,
`per_file_output_std.py:95`). `declaration` is a `ClassVar` on the Protocol
(`protocol.py:50`); `registry.get(name)` maps check NAME → registered check,
so `evaluation.py` can resolve a name to its declaration with **no new
lookup mechanism**.

**A load-bearing alignment, verified rather than assumed**: the three checks
with non-empty `threshold_parameter_names` are exactly the three T1 branches
and exactly TIDMAD's three `blocking` roster entries; the three with `()`
are exactly the three `recording` entries and exactly the three that persist
`threshold: None` today. So declaration-driven rendering — *emit a threshold
row iff the declaration carries one* — reproduces today's TIDMAD threshold
rows **including their three absences**, with no special case.

### 2.2 THE RECONCILIATION FINDING — three more name-keyed surfaces, downstream, on the live path

Rev 1 §14.2 obligated a census for "OTHER name-keyed residue". Executed at
this anchor over all production (non-test, non-`scripts/`) modules, it
returns three surfaces the parent's §3.5 table does not name.

| # | site | shape | what goes silent without it |
|---|---|---|---|
| **T4** | `agent/schemas/health_feedback.py:110-117` `_WORST_STAT_BY_METRIC` | `{"n_unique_int8_values": "minimum", "output_std_mv": "minimum", "dominant_mode_fraction": "maximum"}` — persisted `threshold.metric` NAME → which `aggregate_statistics` entry is the worst case | the round's `CollapseFingerprint`. `_extract_discriminating_metrics` (`:397-418`) returns `({}, {})` for any metric not in the map, and `build_collapse_fingerprint` (`:436-437`) then returns `None` |
| **T5** | `agent/schemas/health_feedback.py:124-133` `_RECORDING_KEY_METRICS` | frozenset of six TIDMAD recording scalars (`pearson_dispersion`, `pearson_mean`, `ratio_mean`, `std_mv_mean`, `std_mv_min`, `std_mv_max`) | `GateOutcome.key_metrics` (`:462`) — a task-owned recording check's scalars are dropped |
| **T6** | `agent/prompts.py:24-32` `_COLLAPSE_ADVICE_BY_CHECK` + the two literal call sites `agent/llm_bridge.py:1005` / `:1009` | per-check-NAME table of TIDMAD collapse prose, injected into the PLANNER prompt | the planner's collapse-advice sentences. `render_collapse_advice` already asks `task_render.has_check(name)`, so a Pets/DAVIS run renders `""` — correct, but there is no way for a task to supply its own |
| **L2** | `agent/schemas/health_feedback.py:417` | `exact = threshold.get("unit") == "count"` — a unit VALUE literal deciding integer-vs-float signature rendering (`bucket_value`, `:143-153`) | nothing today; it is coupled to T3's vocabulary across a module boundary |

**These are on the production path, not a legacy branch.**
`nodes/result_interpretation_agent/evidence.py:267-268` calls
`build_gate_outcomes` and `build_collapse_fingerprint` on the persisted
`gate_results`, producing `RoundHealth`, which is what reaches the
interpreter and (via the proposer's health-evidence block) the LLM. The
chain is:

```text
check.run()  →  evaluation.py::_persist   [T1 T2 T3 L1 D1]
             →  PersistedHealthGateResult.threshold{metric,unit} + metrics
             →  record.health_gate_results
             →  evidence.py:267-268
             →  health_feedback.py       [T4 T5 L2]
             →  RoundHealth  →  interpreter / proposer prompts
             ⇢  planner prompt            [T6]  (parallel, from the roster)
```

**P4 as scoped by S6 fixes the first hop only.** After the `evaluation.py`
migration, a Pets `categorical_distinct_symbols` failure persists a complete
threshold row (`metric: "distinct_symbols"`, `operator: ">="`, unit,
value) — and then T4 still has no entry for that metric name, so
`build_collapse_fingerprint` still returns `None` and the LLM-facing health
evidence is still blank. The defect does not regress; it simply relocates
one hop downstream, from "no threshold row" to "metric not in the worst-stat
table". **The parent's own §3.5 failure-mode sentence applies verbatim to
T4.**

**This contradicted P4's rev-1 §13 hand-off promise to P6** ("complete
evidence for contrast tasks through the GENERIC route"), which P6 depends
on. Recorded as **C-P4-1** and posed as **Q-P4-2**; both are **RESOLVED** at
rev 3 (§12) — T4 and L2 are IN SCOPE, absorbed as derivations.

**T4 is not new declaration content — it is DERIVABLE from what P4 already
migrates.** The worst-case direction follows from the declared comparison
operator: a FLOOR (`>`, `>=`) makes the minimum the worst case; a CEILING
(`<=`, `<`) makes the maximum. Verified 3/3 against the current map
(`n_unique_int8_values` `>` → minimum; `output_std_mv` `>=` → minimum;
`dominant_mode_fraction` `<=` → maximum). So absorbing T4 **deletes** a
table without adding a field — it strengthens P4's single semantic owner
rather than widening it. L2 is the same shape one level down (exactness is
a property of the declared unit/metric, not a string compared in another
module).

**T5 and T6 are NOT of that kind — DEFERRED, NAMED (Q-P4-3 = defer both).**
T5 is a whitelist over free-form check `metrics` keys, which no check
declares today. T6 needs a *per-check LLM-facing advice* channel; the
roster's `reason` prose exists in the composed config
(`_composition.py:283`) but has **zero production consumers** — it is
documentation in the effective YAML. Giving either a declaration is a **new
framework capability** (§11), not a task instance, and both carry LLM-facing
byte-parity obligations (07b PB-1/PB-2 guard the planner prompt; 09b froze
the interpretation surface). The frozen distinction:

```text
T4  already-declared semantics, hard-coded a second time
        -> delete the duplicate, derive from the declaration     IN SCOPE

T5  nothing today declares which recorded scalars are representative
T6  nothing today declares a check's task-specific LLM advice
        -> a NEW declaration capability must exist first          OUT OF SCOPE
```

**Named residual debts, with owners frozen by the operator ruling (§12):**

| id | debt | owner |
|---|---|---|
| **HD-T5** | Health **representative-evidence declaration capability** — which recorded observation/scalar keys a check exposes as representative `key_metrics` | named post-Step-10 Health-capability debt / a future dedicated Health-extensibility PR |
| **HD-T6** | Health **LLM-advice declaration capability** — task/check-specific collapse advice reaching the planner, with its own Gate-1 and prompt-parity disposition | same |

Two owners are explicitly **excluded** by the ruling. **P6 must not
implement them**: its contract is final executable closure and it *adds no
new scientific semantics*; it may verify the generic path and report HD-T5 /
HD-T6 as a remaining optional Health-capability limitation, nothing more.
**Step 12 must not be assumed to own them** merely because task packages
become external: Step 12 externalizes a task package's SOURCE, and it may
only externalize a source once an interface exists.

### 2.3 U1 — the unit duplicate rev 1 would have relocated instead of removed

T1 renders `"unit": "mV"` for `output_std`; T3 renders `"mV"` for
`output_std` and `per_file_output_std`. Since 08b, the millivolt scale is
**task-owned**: `configs/task_health/tidmad.yaml` declares
`value_scale: {unit: mV, units_per_sample: 0.3125}`, and
`_composition.py:287-309` injects `value_scale_unit` into the config of
exactly those checks whose declaration requires the `value_scale_unit` axis
— declaration-driven, never keyed on a check or task name.

Executable confirmation at this anchor (composed TIDMAD effective config,
loaded from this worktree):

```text
output_std_blocking          value_scale_unit='mV'  units_per_sample=0.3125
per_file_output_std_recording value_scale_unit='mV'  units_per_sample=0.3125
pearson_dispersion_recording  value_scale_unit='mV'  units_per_sample=0.3125
spectral_peak_ratio_recording value_scale_unit='mV'  units_per_sample=0.3125
```

So a literal `"mV"` copied onto `output_std.py`'s declaration would be a
**third** declaration of one number's unit, and would render `mV` for a task
whose scale is µV. It would also survive the health-core census undetected,
because that census excludes the six TIDMAD check modules by listed name —
passing the guard while re-committing the defect 08b was written to remove.

Note the discriminating counter-example that forbids the lazy rule "use
`value_scale_unit` when present": `pearson_dispersion` and
`spectral_peak_ratio` both RECEIVE `value_scale_unit='mV'` and both have
dimensionless evidence units (`correlation`, `ratio`). The unit source is
genuinely per-check. Ruled in §4.2 (R-2).

### 2.4 D1 corrected — what the duplicated default actually duplicates

The parent describes `evaluation.py:89`'s `5` as "a SECOND declaration of a
threshold whose task value is `25`". Source says something sharper: `5` is a
byte-identical copy of the CHECK's own authoring default,
`OutputDiversityCheck._DEFAULT_MIN_UNIQUE = 5`
(`output_diversity.py:67-69`). Same for the other two:
`_DEFAULT_MIN_STD_MV = 1.0` (`output_std.py:94`) and
`_DEFAULT_COLLAPSE_THRESHOLD = 0.95` (`amplitude_collapse.py:83`). TIDMAD's
`25` is the task config's OVERRIDE, which wins over both and is why the
disagreement is currently masked.

**This falsifies rev 1 §4.3's premise.** If the config key is absent, the
check does **not** threshold on nothing — `run` falls back to its private
`_DEFAULT_*` and thresholds on `5`. Rendering "named absent" evidence would
therefore *misreport a gate that ran and thresholded*, which is a worse
failure than the duplicate it repairs. The honest states are:

| config key | what the check used | honest evidence |
|---|---|---|
| present (every composed/shipped config) | the config value | that value — today's behaviour, byte-identical |
| absent | the check's own `_DEFAULT_*` | the check's default, labelled as the check's default — **never** "absent", and never a second copy of the number |

Q-P4-1 is re-posed on this corrected basis (§12).

### 2.5 Residual-debt table (audit → owner)

| central source | task-specific content | current consumer | proposed declaration owner | generic mechanism preserved | migration validation |
|---|---|---|---|---|---|
| T1 operator / metric-name / config key | per-check evidence identity | persisted threshold row | the CHECK's own declaration (§4.1) | threshold VALUE still read from the run's effective CONFIG (task-owned, 08b) | TIDMAD threshold rows byte-identical on fixtures |
| T1 unit (`mV` rows) | the TASK's value scale | same | the declaration names the *source* (`value_scale_unit` config key), not the string (R-2) | injection unchanged (`_composition.py:287`) | TIDMAD renders `mV`; a µV task renders µV |
| T1 unit (`count`/`fraction`) | check-owned, dimensionless | same | literal on the declaration — it follows from the arithmetic (R-2) | — | byte-identical |
| T1 defaults `5`/`1.0`/`0.95` | duplicates of the checks' `_DEFAULT_*` | same | **REMOVED**; the check's default becomes the single authoring authority (R-3) | fail-closed: no second number anywhere | absent-key fixture renders the check's default with `source: "check_default"`; present-key rows carry NO source label and stay byte-identical |
| T2 metric names | six names | per-file rows | check declaration | row construction unchanged | per-file rows byte-identical for TIDMAD |
| T3 units | six units | per-file rows | same split as T1's unit rows (R-2) | same | same |
| L1 sampling label | TIDMAD channel label | per-file rows | check declaration (each check states how it sampled) | row shape unchanged | TIDMAD rows byte-identical; a view-based check states its own label |
| D1 | see T1 defaults | — | — | — | the disagreement dies WITH the duplicate |
| **T4** — IN SCOPE | worst-stat direction per metric name | `CollapseFingerprint` | **DERIVED from the declared operator** (§2.2, R-7) — table deleted, no field added | fingerprint construction unchanged | 3/3 TIDMAD parity; Pets/DAVIS gain a fingerprint |
| **L2** — IN SCOPE | `unit == "count"` exactness literal | signature rendering | **DERIVED from the declared unit**, with T4 | `bucket_value` unchanged | byte-identical signatures |
| **T5** — DEFERRED (**HD-T5**) | six TIDMAD recording-scalar names | `GateOutcome.key_metrics` | needs a NEW declaration channel — capability, not instance (§11) | — | out of P4; named debt, §2.2 |
| **T6** — DEFERRED (**HD-T6**) | per-check LLM collapse prose | planner prompt | needs a NEW declaration channel + LLM byte-parity handling | — | out of P4; named debt, §2.2 |

---

## 3. Goal / semantic owner / boundary

**One semantic owner: Health evidence declaration.** After P4, everything
the migrated tables know is declared BY the check that knows it (or derived
from that declaration); the generic evidence path resolves declarations
through the existing registry; the tables are deleted; a task-owned check's
evidence is as complete as TIDMAD's with zero central edits.

Proposed boundary (names `PROVISIONAL`, shape not):

```text
CheckInputDeclaration — extended ONCE (the §13-sanctioned framework change):
    evidence_thresholds: tuple[ThresholdDeclaration, ...]
        # config key, comparison operator, unit SOURCE, evidence metric
        # name, and the authoring default (R-3)
    per_file_metric_name: str | None      # None = check emits no per-file rows
    per_file_metric_unit: <unit source>   # same two-kind rule as above (R-2)
    sampling_method_label: str | None     # what the check states about its own sampling
```

Nothing is added for T4/L2 — they are **derivations** over the fields above:

```text
declaration.evidence_thresholds[].operator
        -> generic worst-statistic derivation
               >  / >=   (a FLOOR)   -> minimum is worst
               <  / <=   (a CEILING) -> maximum is worst

declaration's unit
        -> generic exactness derivation  (integral vs bucketed rendering)
```

What this revision freezes as *shape* (not names): **declarative data on the
check, resolved via the existing registry, zero name-keyed tables anywhere in
the generic evidence path — persistence AND fingerprint alike — no
framework-owned copy of a task threshold, and no framework-owned copy of a
task unit.**

**The executable form of the genericity claim.** The
health-core census
(`tests/unit/guardrails/test_health_core_census.py:52-65`) excludes
`evaluation.py` from the GENERIC partition by listed name, with a comment
that names this debt and its owner: *"`evaluation.py` is the pre-08a
campaign-persistence adapter whose per-check-name threshold tables predate
declarations — recorded 08c out-of-scope finding, owner Step 9/10, NOT
silently generic."* After the T1/T2/T3/L1/D1 migration, `evaluation.py`
carries no check-name branch, no `channel0001` label, no `mV` and no
`n_unique_int8_values`. **P4's acceptance is therefore that `evaluation.py`
MOVES from `TIDMAD_FAMILY_MODULES` into `GENERIC_MODULES` and passes the
existing census unchanged.** That is a single-line diff in a guard that
already exists, already has planted-offender probes, and was written by the
prior step to be redeemed by this one. No new census is invented.

**The second acceptance, for the absorbed surfaces**: after the T4/L2
derivation, `agent/schemas/health_feedback.py` contains no per-check and no
per-metric NAME table. Its two deleted constants are pinned by a census with
a planted offender (a re-introduced name→statistic map, or a
`unit == "count"` style literal comparison, turns it RED), so the ruling
cannot silently regress. **R-7 is the standing rule**: a relocated map is a
failure, not a completion.

**Non-goals**: check arithmetic; verdict/aggregation/action machinery; the
plugin ABI and loaders (08b's, reused); `health_policy`; any threshold
VALUE; the `evaluation.py` gate-selection logic; Health's binding lifecycle
(P1's); multi-check gates; dashboards; the D14 Gate runners' direct
`runner.evaluate_gate` bypass (P6's, per Q-10-5 = B).

---

## 4. Design decisions (load-bearing)

### 4.1 R-1 — declaration-driven, resolved through the existing registry

`evaluation.py` already has the check NAME at both consumer sites. It
resolves the registered check's declaration (name → `registry.get` →
`ClassVar`) and renders the threshold row / per-file naming / sampling label
from THAT. Built-ins carry their migrated table content on their own
declarations; task-plugin checks carry theirs. An UNREGISTERED name is
already fail-closed upstream: `runner.evaluate_gate` resolves the check
through `registry.get`, which raises `KeyError`, so evidence construction is
never reached with an unknown name. The evidence path never invents a
declaration.

### 4.2 R-2 — units have two kinds, and only one of them is a literal

* **Check-owned (dimensionless / structural)** — `count`, `fraction`,
  `correlation`, `ratio`. These follow from the check's arithmetic and are
  the same for every task. A literal on the declaration is correct.
* **Task-owned (physical scale)** — the `mV` rows. The declaration names
  the config KEY the unit arrives under (`value_scale_unit`, injected by
  `_composition.py:287-309` into exactly the checks that declare the axis);
  the renderer reads the value. TIDMAD renders `mV` byte-identically; a task
  with another scale renders its own; and there is **no third copy** of the
  unit anywhere (§2.3).

A check whose declared unit source is absent for this run (no `value_scale`
declared, e.g. DAVIS) renders no unit rather than a defaulted one.

### 4.3 R-3 — the duplicate-default repair (parent-mandated shape, corrected premise)

The threshold VALUE is read from the run's effective config under the
declared key. `evaluation.py`'s three constants are **deleted** — the
duplicate is removed, neither side is edited to match (§13 satisfied). The
remaining single authoring authority is the check's own default, which is
what `run` uses; P4 moves it from a private `_DEFAULT_*` ClassVar onto the
declaration beside its key, so `run` and the evidence renderer read **one**
number. This is unreachable for every composed/shipped config (the effective
config always carries the key) and it removes the misreporting hazard rev 1
would have introduced (§2.4).

**Q-P4-1 RESOLVED = (a), fallback-only labelling (operator, 2026-08-20).**
Frozen:

```text
config value present   (every composed / shipped config today)
    -> persist exactly the configured value, as today
    -> add NO source label
    -> shipped TIDMAD evidence rows stay BYTE-IDENTICAL

config key absent      (the check legally ran on its own default)
    -> persist the actual default the check used
    -> label that threshold's source:  "check_default"
```

The label is **FALLBACK-ONLY**. Stamping `source` on every row would create
a persisted-output delta on every TIDMAD row for no disambiguation gain and
would break the C0 goldens; only the fallback branch is ambiguous, and only
it is labelled. The rejected options and why: **(b) unlabelled** leaves "the
task configured 5" indistinguishable from "the check defaulted to 5" — a
weaker form of the very duplicate-authority ambiguity this child removes;
**(c) fail closed at evidence time** would raise inside `_persist` for a
check that executed legally and produced a verdict, contradicting §9 and the
§2.1 boundary that evidence is never a verdict. `threshold` is
`dict[str, Any]`, so the label is **not** a public-schema change, and the
downstream readers consume only `threshold.metric` / `threshold.unit`.

### 4.4 R-4 — absence is a named state, not a blank

A check that declares no per-file metric (`per_file_metric_name=None`)
produces rows without a fabricated name — the CURRENT behaviour for unknown
checks, now an explicit declaration rather than a table miss. A check with
no `evidence_thresholds` persists no threshold row; recording-only checks
already declare `threshold_parameter_names=()`, and §2.1 verified that this
reproduces TIDMAD's three existing threshold absences exactly.

### 4.5 R-5 — the two `threshold_parameter_names` must not become two authorities

`evidence_thresholds` and the existing `threshold_parameter_names` would
both answer "which config keys are this check's thresholds".
`threshold_parameter_names` has **no production consumer** today (verified:
only its own declaration sites, two docstrings, and tests). P4 must
therefore make one of them derived from the other — the config keys named by
`evidence_thresholds` ARE `threshold_parameter_names` — and pin the
biconditional with the existing declaration tests
(`tests/unit/execute_tools/health_checks/test_check_declarations.py:394-472`
already owns the "declares THRESHOLDS, not parameters read" concept and is
the natural home). Two independently-authored tuples that must agree is the
duplicate-authority shape this child exists to remove.

### 4.6 R-6 — what the migration must preserve, byte for byte

For TIDMAD's six checks the migrated declarations carry exactly the values
the tables hold today (operator symbols, metric names, config keys, the
`channel0001_prefix_peek` label) and resolve the two `mV` rows to the same
string through the task's declared scale. The migration moves WORDS, not
meanings — pinned by fixture parity on persisted evidence.

### 4.7 R-7 — T4/L2 are absorbed as a DERIVATION (Q-P4-2 = YES, operator, 2026-08-20)

T4 and L2 are IN SCOPE and enter as a **deletion**: the worst-case statistic
is computed from the declared comparison operator (floor `>`/`>=` → minimum;
ceiling `<`/`<=` → maximum), and exactness from the declared unit — no new
declaration field, no relocated table, and 3/3 byte parity against today's
TIDMAD map.

The ruling's reasoning, recorded: `_WORST_STAT_BY_METRIC` is not a new
scientific semantic — it is the **already-declared per-check operator,
hard-coded a second time**, and while it stands, a correctly persisted
Pets/DAVIS threshold row still becomes blank evidence one hop downstream.

**Standing prohibition.** If T4 is reproduced as a per-metric-name or
per-check-name map in ANY module — including a "generic" one — that is the
fake-central-registry anti-pattern and P4 must refuse it (§11). The census in
§3 is what makes the prohibition executable rather than advisory.

---

## 5. Three-task control

| | TIDMAD | Pets | DAVIS | same path? |
|---|---|---|---|---|
| Health family | `configs/task_health/tidmad.yaml`, 6 gates / 6 checks | pack `declared/task_health.yaml`: `categorical_distinct_symbols` (5), `categorical_dominant_fraction` (0.95) | pack `declared/task_health.yaml`: `sample_dispersion_floor` (0.04) | YES — 08b binding states, verified by the existing three-task rung |
| binding state | `LEGACY_OMITTED` → the TIDMAD config (bounded legacy path) | EXTERNAL state C (explicit path + `kind: file` pack plugin, `pets.prediction_views`) | EXTERNAL state C (`davis.sample_views`) | YES |
| per-file evidence today | populated (T2/T3 know the names) | none — and correctly so: these checks emit scalar metrics, no `per_file` | none, same reason | — |
| **threshold row today** | 3 of 6 (blocking only; the 3 recording checks correctly have none) | **blank** — absent from T1 | **blank** | — |
| threshold row after P4 | byte-identical, including the three absences | complete, from the check's own declaration | complete | YES — one registry-resolved read |
| **LLM-facing fingerprint today** | populated (T4 knows the metrics) | **blank** (T4 miss) | **blank** (T4 miss) | — |
| LLM-facing fingerprint after P4 | byte-identical (3/3 derivation parity) | **complete** — derived from the declared operator | **complete** | YES — one generic derivation, no name table |
| representative `key_metrics` / planner collapse advice | populated | still absent — **HD-T5 / HD-T6**, named debt outside P4 (§2.2) | same | — (a NEW capability, not this migration) |
| threshold values | task YAML (unchanged) | pack YAML, frozen by 08c | pack YAML, frozen by 08c | YES |

Correction to rev 1's table: it claimed TIDMAD "evidence today: complete".
That is true of per-file naming and units, and **false of the threshold
row** for `pearson_dispersion`, `spectral_peak_ratio` and
`per_file_output_std` — which is correct behaviour (they are recording-only
and declare no threshold), and which P4 must preserve rather than
"complete".

The genericity requirement is the same declaration/binding/protocol path,
**not** the same checks. No generic path may dispatch on task identity; none
does today, and P4 adds none.

## 6. Structure preflight

| file | now | P4 change | owners after |
|---|---|---|---|
| `execute_tools/health_checks/schemas.py` | 1,049 lines, coherent schema family | +the ONE declaration extension | unchanged |
| `execute_tools/health_checks/evaluation.py` | 309 lines; evidence persistence + gate iteration | tables DELETED; two consumer sites read declarations; net NEGATIVE; **leaves the census's TIDMAD-family exclusion list** | unchanged set |
| the nine built-in check modules | one check each | +declaration fields each | unchanged |
| Pets/DAVIS pack plugins | task-owned | no change required (they use built-in generic checks; their thresholds are already declared in pack YAML) | unchanged |
| `agent/schemas/health_feedback.py` | 671 lines; provenance + fingerprint + outcomes + retention | `_WORST_STAT_BY_METRIC` and the `unit == "count"` literal DELETED, one derivation added; net NEGATIVE | unchanged set |
| `agent/prompts.py` / `agent/llm_bridge.py` | prompt assembly | **UNTOUCHED** — Q-P4-3 defers T6 (HD-T6) | — |

No new module is expected. `_per_file_metrics` will need the gate config
(for R-2's unit source) that `_persist` already holds — a parameter, not a
new responsibility. If declaration-rendering outgrows a coherent inline
shape, the minimum extraction is a private `_evidence_rendering.py` beside
`evaluation.py`, decided at implementation by ownership, not by LOC. Neither
file is a god-file today and neither becomes one; `evaluation.py` shrinks.

## 7. Commit decomposition (FROZEN — C3′ is unconditional under Q-P4-2 = YES)

* **C0** — evidence goldens: persisted `PersistedHealthGateResult` fixtures
  for all six TIDMAD gates at base (threshold rows *including the three
  absences*, per-file naming, units, sampling label) **plus the current
  `CollapseFingerprint` / `GateOutcome` goldens**; the CURRENT
  blank-evidence capture for one Pets and one DAVIS check at BOTH hops (the
  defect, recorded before the fix); table census — T1/T2/T3/L1/D1 and
  T4/T5/L2/T6 byte-listed with their anchors.
* **C1** — the declaration extension + built-in declarations populated with
  the tables' content, R-2's unit sources and R-3's defaults; R-5's
  biconditional pinned; NO consumer change yet (inert data, schema tests).
* **C2** — `evaluation.py` consumers read declarations; T1/T2/T3/L1/D1
  DELETED; TIDMAD fixtures byte-identical to C0; Pets/DAVIS threshold rows
  flip from blank to complete; the config-key-absent test asserting the
  check's default AND `source: "check_default"`, plus its twin asserting the
  present-key row carries NO source label (Q-P4-1); `evaluation.py` moves
  into the census's GENERIC partition and passes it; plant-and-catch (a
  re-introduced name-keyed table or a check-name branch turns the census RED).
* **C3** — task-pack three-task evidence-completeness fixtures routed
  through `evaluation.py` (NOT through the D14 Gate runners — that bypass is
  the defect's hiding place) + the fourth-task instance proof (§13).
* **C3′** — T4/L2 derived from the declared operator and unit; the two
  constants deleted; TIDMAD fingerprint / `key_metrics` goldens
  byte-identical to C0; Pets and DAVIS gain a fingerprint, asserted on the
  real 08c collapse fixture; the §3 second-acceptance census with its
  planted offender (R-7). `agent/prompts.py`, `agent/llm_bridge.py` and
  `_RECORDING_KEY_METRICS` are **not** touched — HD-T5 / HD-T6 are out of
  scope by ruling.
* **C4** — closure: censuses, docs sync (`docs/design/pluggable_health_checks.md`,
  the health-checks operator docs, this design's ledger), ONE exact-head CI.

## 8. Validation strategy / Gate disposition

Deterministic owners: TIDMAD evidence byte-parity fixtures (C0 goldens, both
hops); Pets/DAVIS completeness fixtures routed through `evaluation.py`; the
config-key-absent state; the health-core census with `evaluation.py`
promoted to GENERIC and its existing planted-offender probes; schema tests
for the declaration extension and R-5's biconditional; the fourth-task
out-of-tree instance proof; the existing 08a 27-case verdict manifest and
08b/08c three-task rung stay untouched and green.

**Gate 1: NOT REQUIRED.** P4 changes no prompt template bytes and no
prompt-assembly code: `agent/prompts.py` and `agent/llm_bridge.py` are
untouched because Q-P4-3 defers T6. The T4/L2 derivation changes *which
statistic is quoted as evidence* for contrast tasks only — TIDMAD
fingerprints are byte-identical, and the property is deterministic and
golden-owned. The exclusion of HD-T5/HD-T6 is what preserves this
disposition, which is precisely why the operator ruled them separately.
**Gate 2: NOT REQUIRED.** The changed property is deterministic declaration
transport; no real data, GPU, training, inference or scoring behaviour is
touched. Real-lifecycle Health evidence under a live run is P6's closure
evidence. A deterministic migration failure must never be compensated by a
Gate. Both dispositions are to be quoted against
`docs/gates/gate_testing_standard.md` at freeze, per roadmap §17.0.

## 9. Preservation invariants

Verdicts, actions, severity resolution, thresholds: bit-identical for
TIDMAD. The pinned effective-config sha MECHANISM untouched. `health_policy`
untouched. The 08b plugin/binding lifecycle and the three binding states
untouched. One-check-per-gate untouched. Persisted evidence for TIDMAD:
byte-identical (C0 goldens), including its three legitimate threshold
absences. The ONLY deltas: task-owned checks gain complete evidence, and the
config-key-absent state stops being a second copy of a number.

## 10. Failure / edge cases

| case | behaviour |
|---|---|
| check name not in the registry at evidence time | unreachable — `runner.evaluate_gate` already raises `KeyError` from `registry.get`; the evidence path never invents a declaration |
| a check declares thresholds but the config lacks the key | the check ran on its own declared default; the evidence says so (§2.4, Q-P4-1) — never "absent", never a second copy |
| recording-only checks | declare no thresholds; no threshold row — today's shape, now explicit |
| duplicate check ids | already fail-closed: `registry.register` raises on a duplicate name; roster gate ids are composed per task |
| a roster hand-authoring an injected key | already `HealthCompositionError` (`_composition.py:261-268`) — P4 adds no new injected keys |
| a task declares no `value_scale` but a check declares a scale-sourced unit | the check is already INAPPLICABLE by 08a applicability (it requires the axis); no evidence row is produced |
| legacy persisted artifacts | untouched — P4 changes production of NEW evidence only |
| a plugin declares a unit/name the renderer never saw | rendered verbatim — declarations are data, the framework does not enumerate them |
| an explicitly-composed task with no Health family | `EXPLICIT_NONE` is a NAMED absence; it must never fall back to TIDMAD's family, and P4 adds no fallback |

## 11. Instance extensibility vs backend capability (frozen distinction, restated)

* **A new task-specific check INSTANCE using existing capabilities** —
  declaration + task/pack config only. Framework semantic edits **0**,
  central catalog edits **0**, task-name branches **0**.
* **A genuinely new backend capability** — a new view kind, or an evidence
  shape the declaration cannot express — may legitimately require framework
  work. T5 (a declared recording-scalar channel) and T6 (a per-check
  LLM-advice channel) are of this kind, which is precisely why they are
  posed as Q-P4-3 rather than absorbed.

P4's genericity claim is about task-specific semantic **instances**. It does
not promise zero framework edits for future capability classes.

## 12. Operator rulings — RESOLVED (2026-08-20)

All four freeze blockers are ruled. **Open operator questions = 0. Material
contradictions = 0.**

| id | question | **RULING** |
|---|---|---|
| **Q-P4-1** | Given §2.4 (an absent config key means the check thresholded on its OWN default, not on nothing): does the evidence row (a) render that default with a `source: "check_default"` label, (b) render it unlabelled, or (c) fail closed at evidence time? | **RESOLVED = (a), FALLBACK-ONLY.** Configured value present ⇒ persist exactly as today, no source label, TIDMAD rows byte-identical. Key absent ⇒ persist the actual default the check used and label it `"check_default"`. Not unlabelled (would hide the difference); not fail-closed (the check executed legally). Frozen in §4.3 |
| **Q-P4-2** | **Scope boundary.** S6 is enumerated as `evaluation.py`'s tables, but T4/L2 (`agent/schemas/health_feedback.py`) re-impose the identical silence one hop downstream and defeat P4's hand-off to P6 (§2.2). Does P4 absorb T4/L2, or does the parent assign them elsewhere? | **RESOLVED = YES, absorb.** `_WORST_STAT_BY_METRIC` is the already-declared per-check operator hard-coded a second time, not a new scientific semantic; the `unit == "count"` exactness literal derives from the migrated unit declaration. Both enter as deletions via derivation (R-7), never as a relocated map. Frozen in §4.7 |
| **Q-P4-3** | T5 (`_RECORDING_KEY_METRICS`) and T6 (`_COLLAPSE_ADVICE_BY_CHECK` + its two literal call sites) are the same failure class but need NEW declaration channels and carry LLM-facing byte-parity obligations. Deferred, or in scope? | **RESOLVED = DEFER BOTH, NAMED.** Neither migrates an existing authority; each would create a framework capability that does not exist. Recorded as **HD-T5** (representative-evidence declaration capability) and **HD-T6** (LLM-advice declaration capability), owned by named post-Step-10 Health-capability debt / a future dedicated Health-extensibility PR. **Explicitly NOT P6** (it adds no new semantics) and **explicitly NOT assumed to be Step 12** (a source may be externalized only once an interface exists). Frozen in §2.2 |

| id | contradiction | **RESOLUTION** |
|---|---|---|
| **C-P4-1** | Parent §3.5 defines the failure class ("silence — evidence quietly poorer than TIDMAD's") while §4's S6 row and §13's scope line enumerate `evaluation.py` members only. Source shows the class is not contained by that file, so P4-as-enumerated could not deliver its own §13 hand-off to P6 | **RESOLVED by a minimum parent scope-completeness correction.** The implementation enumeration is replaced by the semantic boundary: *residual framework-owned per-check Health evidence metadata that is derivable from the task/check declaration becomes declaration-derived* — explicitly including `evaluation.py`'s name/operator/unit/default surfaces, `_WORST_STAT_BY_METRIC` and the unit-exactness literal, and explicitly NOT including surfaces that require new declaration capabilities. **§4.1's map row needed no edit** (it already reads "Health evidence declaration migration"); only §4's S6 authority column and §13's scope line changed. Changed: P4 semantic owner **NO** · seven-child decomposition **NO** · scientific Health semantics **NO** · public result schema **NO** · P4/P2a parallelism **NO** · parent Step-10 semantics **NO** (completeness correction, not a Revision-3 redesign of the parent) |

## 13. Fourth-task genericity proof (design requirement)

A synthetic, out-of-tree-shaped fourth task declares a Health family using
only existing capabilities: a temporary external directory (pytest
`tmp_path`, never mutable working-tree state as the oracle) holding a task
health config and an underscore-prefixed plugin referenced by `kind: file`,
registering one check through the public `register` with a declaration
carrying its own evidence metadata. It resolves through the standard
binding, composes, executes, and persists **complete** evidence through the
generic path. Asserted: framework task-specific production edits **0**,
central Health task-table edits **0**, task-name branches **0**. The 08b
out-of-tree extension proof
(`tests/unit/execute_tools/health_checks/test_out_of_tree_extension.py`)
is the existing shape to extend, not duplicate.

## 14. Cross-child ownership

* P4 touches NO run-state carrier (`ChainState` / `WorkflowRunBindings` /
  composition) and creates none — its surface is check declarations plus the
  evidence renderers.
* No dependency on P2a / P2b / P3 / P5. **Verified, not assumed**: P5's
  draft records "P4 touches health schemas/evaluation; P5 touches
  [elsewhere]"; P3's surface is the proposer's interpretation-evidence
  reader and prediction-authoring grammar, neither of which is the Health
  fingerprint builder. Under Q-P4-2 = YES, P4 edits
  `agent/schemas/health_feedback.py` — a file no other Step-10 child claims.
* P1's composed `task_health_binding` is how a second task's family reaches
  `evaluation.py` in tests; P4 adds no binding mechanics.
* Hand-off to P6: complete evidence for contrast tasks through the GENERIC
  route, **at both hops** — persisted threshold rows and the LLM-facing
  fingerprint alike, closed by the Q-P4-2 = YES ruling. P6 inherits two
  named, non-blocking limitations (HD-T5 / HD-T6) which it must REPORT and
  must not implement, since P6 adds no new scientific semantics. The Gate
  runners' direct `runner.evaluate_gate` bypass is retired by P6 per
  Q-10-5 = B.

## 15. Adversarial review (25 attacks, executed at `64446b2b`)

| # | attack | verdict |
|---|---|---|
| 1 | Generic source still contains task-specific Health check NAMES? | **CORRECTED** — T1/T2/T3 confirmed; census found T5 (`pearson_dispersion`) and T6 (`output_diversity`, `amplitude_collapse`) beyond the parent's list. Rev 2 §2.2 |
| 2 | Generic source still contains task-specific Health UNITS? | **CORRECTED** — yes, and rev 1 would have relocated `mV` rather than removed it. R-2 (§2.3) |
| 3 | A TIDMAD-only operator/display map survives? | **CLOSED** — T1's operators migrate to declarations; T4's direction map becomes derived, not relocated (R-7) |
| 4 | Was a central task Health catalog merely renamed? | **CLOSED** — declarations are per-check `ClassVar`s resolved by the existing registry; the census bans name-keyed tables in the generic partition wherever they live, with a planted offender proving it fires |
| 5 | Does a fourth ordinary task-specific check INSTANCE require a framework edit? | **CLOSED** — §13 proof; framework edits 0 |
| 6 | Does any generic Health path dispatch on task identity? | **CLOSED** — none today (census `TASK_TOKENS`, one quarantined `LEGACY_DEFAULT_TASK_HEALTH_CONFIG` allowance); P4 adds none |
| 7 | Does an unknown plugin/check declaration fail closed? | **CLOSED** — `registry.get` raises `KeyError` in `evaluate_gate`, before evidence; `register` raises on duplicates; a hand-authored injected key is `HealthCompositionError` |
| 8 | Can an explicit task silently fall back to TIDMAD Health semantics? | **CLOSED** — `EXPLICIT_NONE` is a named absence (08b); P4 introduces no fallback and deletes one (D1) |
| 9 | Did any scientific threshold change? | **CLOSED** — values never migrate; only the KEY, the operator and the unit SOURCE are declared. TIDMAD byte parity is the proof |
| 10 | Did any Health action / pass-fail rule change? | **CLOSED** — consumers audited at `:216`/`:263` are evidence-only; verdict machinery untouched; 08a/08b/08c manifests stay green |
| 11 | Did P4 move generic framework mechanics into task code? | **CLOSED** — packs need no edit at all; only framework-shipped check declarations gain fields |
| 12 | Did P4 create another plugin loader / registry authority? | **CLOSED** — it reuses `registry.get`; no new lookup |
| 13 | Does it use the existing binding rather than a parallel carrier? | **CLOSED** — P1's `task_health_binding`; no new carrier |
| 14 | Does P4 add a run-state carrier? | **CLOSED** — none |
| 15 | Does P4 alter `ChainState`? | **CLOSED** — no |
| 16 | Does P4 collide semantically with P2a's active changes? | **CLOSED** — §16: zero shared files, zero shared functions |
| 17 | Can P4 merge BEFORE P2a and leave master coherent? | **CLOSED** — yes; disjoint surfaces, and P4 depends only on merged P1 |
| 18 | Can P4 merge AFTER P2a by normal reconciliation? | **CLOSED** — yes; no semantic redesign, at most line-anchor refresh |
| 19 | Are TIDMAD / Pets / DAVIS on ONE generic declaration path? | **CLOSED** — §5; the 08c three-task rung already proves the binding/composition half |
| 20 | Can a synthetic fourth task prove zero central semantic edits? | **CLOSED** — §13 |
| 21 | Exactly ONE obvious semantic owner for per-check declaration metadata? | **CLOSED** — Q-P4-2 = YES brings the derivable surface (T4/L2) under the same owner; Q-P4-3 places the two capability-class surfaces outside P4 under named owners (HD-T5 / HD-T6). One owner for what P4 migrates, named owners for what it does not |
| 22 | Are backend capabilities clearly distinguished from task check instances? | **CLOSED** — §11; T5/T6 explicitly classified as capabilities and NOT absorbed silently |
| 23 | Is P6 the only downstream child depending on both P4 and the main lane? | **CLOSED** — yes (parent §20.2 / §20.3) |
| 24 | Any hidden P3 / P5 dependency? | **CLOSED** — §14, verified against both drafts and the source surfaces |
| 25 | Is every proposed validation tied to an actual P4 failure class? | **CLOSED** — §8; each owner names the silence it catches, and the census promotion is a pre-existing guard redeemed rather than a new one invented |

**Totals at rev 3**: 25 attacks — **23 CLOSED**, **2 CORRECTED** (attacks 1
and 2, corrected in rev 2 and carried), **0 OPEN**, **0 material
contradictions**. Attack 21 closed on the Q-P4-2 / Q-P4-3 rulings; C-P4-1
closed on the parent scope-completeness correction.

## 16. P2a parallel-overlap audit (P2a implementation ACTIVE in a separate worktree)

Performed from P2a's FROZEN design (§2.1's twelve sites) and from source —
**the live P2a worktree was not inspected or modified**.

| | P2a (frozen surface) | P4 (this design) | overlap |
|---|---|---|---|
| files | `execute_tools/evaluation_metric.py` (reconciliation promotion) · `workflows/model_exploration.py` · `core/resume.py` · `execute_tools/per_file_best.py` · `dashboard/data_sources/*` · `dashboard/api/router.py` · `scripts/build_diagnostic_summary.py` · `scripts/finalize_recovered_diagnostic_round.py` · `nodes/proposal_helpers.py` | `execute_tools/health_checks/{evaluation,schemas}.py` · the nine check modules · `agent/schemas/health_feedback.py` (Q-P4-2 = YES) | **NONE** |
| functions | `_pick_best`, `_row_beats`, `top_n`, the three workflow comparisons | `_threshold`, `_per_file_metrics`, `_persist`, `_extract_discriminating_metrics` | **NONE** |
| shared authority | `MetricOrder` / `MetricSpec` | none — Health evidence never reads the golden metric (census `TestNoMetricScalarConsumption` forbids it) | **NONE** |
| shared guards | the direction AST scanner | the health-core census | **NONE** |
| shared schemas | `MetricSpec` | `CheckInputDeclaration` | **NONE** |

**One live observation, recorded honestly.** At the end of this session the
main checkout (P2a's) had advanced past `64446b2b` and its `git status`
showed `nodes/result_interpretation_agent/evidence.py` among its modified
files — a module P2a's frozen §2.1 table does not list. Its *contents were
not inspected*: in-flight work is not authority, and the kickoff forbids
reading that tree for this audit. What matters for P4 is that `evidence.py`
is a **caller**, not a surface P4 touches: P4's conditional edit is to
`health_feedback.py`, the callee. The relationship is adjacency, not
competing ownership. A P4 implementation landing after P2a should expect at
most a line-anchor refresh at `evidence.py:267-268`, never a semantic
reconciliation — and must re-verify it rather than trusting this note.

**FROZEN VERDICT: SAFE TO IMPLEMENT IN PARALLEL WITH P2a, WITH NORMAL
POST-MERGE SOURCE RECONCILIATION.** Competing semantic owners = **0**. No
shared file, no shared function, no shared guard, no shared schema. Merge
order is free in both directions (attacks 17 and 18). The only coupling is
textual — line anchors in *this document* are evidence, not authority, and
must be re-verified at whatever head P4 implementation branches from. **The
P2a worktree must not be touched by P4 work at any point.**

## 17. Freeze verdict

| criterion | status |
|---|---|
| source reconciliation complete | **YES** — §2, at `64446b2b` |
| no P1 contradiction | **YES** — P1's composition is consumed, not modified |
| open operator questions = 0 | **YES — 0** (§12, all four ruled 2026-08-20) |
| material contradictions = 0 | **YES — 0** (C-P4-1 resolved by the scope-completeness correction) |
| semantic owner = one | **YES** — one owner for what P4 migrates (§3); named external owners for HD-T5 / HD-T6 |
| no fake central task Health catalog | **YES** — R-1, R-7, and the two censuses in §3 with planted offenders |
| fourth-task instance costs zero central edits | **YES** — §13 |
| no task-name dispatch | **YES** |
| TIDMAD scientific Health semantics preserved | **YES** — §9; verdicts, actions, severity, thresholds bit-identical |
| public result schema unchanged | **YES** — `threshold` is `dict[str, Any]`; `CollapseFingerprint` / `GateOutcome` shapes untouched; the only model change is the ONE §13-sanctioned `CheckInputDeclaration` extension |
| P2a overlap shows no competing ownership | **YES** — §16, competing semantic owners = 0 |
| implementation sequence coherent | **YES** — §7, C0 → C4 with C3′ unconditional |
| deterministic validation owns the failure class | **YES** — §8 |
| Gate disposition explicit | **YES** — Gate 1 NOT REQUIRED, Gate 2 NOT REQUIRED |

**P4 IS FROZEN at REVISION 3 — OPERATOR APPROVED, IMPLEMENTATION NOT
STARTED.** Every criterion is met. The rulings of §12 are binding on the
implementation session and are not to be re-litigated there.

**Next action: a fresh P4 implementation session**, cutting its own branch
from the then-current `origin/master`, executing §7 C0 → C4. It must not
touch the P2a worktree, and it must re-verify every §2 anchor at its own
branch head before editing.

## 18. Obligations for the implementation session

1. Re-verify §2.1's five anchors and §2.2's four at the branch head. They
   are evidence, not authority; P2a/P2b do not touch Health (§16), but
   verify rather than assume.
2. Re-run the name-keyed residue census over production; confirm no surface
   beyond T1–T6 / L1 / L2 / D1 / U1 appeared. A new one is a finding to
   record, not a scope expansion to absorb (§11, and the Q-P4-3 precedent).
3. Quote `docs/gates/gate_testing_standard.md` for the NO-Gate disposition
   in the PR body, per roadmap §17.0.
4. Hold the §12 rulings exactly: fallback-only `check_default`; T4/L2 as
   derivations never as a relocated map; HD-T5 / HD-T6 untouched.
5. Node/skill doc sync as the last pre-merge step: the Health-checks
   operator docs and `docs/design/pluggable_health_checks.md`, with each
   changed behaviour quoted against the merged source.

---

## 19. Implementation ledger (LIVE)

Implementation branch `step10-p4-health-evidence-declaration-migration-impl`,
cut from the frozen design commit `d44f6f6a`. `origin/master` was `64446b2b`
at kickoff — **unchanged since the §2 source audit, so no drift reconciliation
was required at start**. P2a was concurrently active in the main checkout
(`ff333468`) and was never touched.

### 19.1 C0 — evidence baseline + residual census — **[x] COMPLETE**

Two test-only modules; **zero production files touched** (verified by the
commit's own file list).

**`tests/unit/execute_tools/health_checks/test_step10_p4_c0_evidence_baseline.py`**
— drives the PRODUCTION evidence builder `evaluation._persist` once per
composed gate for all three tracks, then the real hop-2 call
(`build_collapse_fingerprint` / `build_gate_outcomes`, the same pair
`nodes/result_interpretation_agent/evidence.py:267-268` makes). Every
expectation is a HARDCODED literal captured from the base tree; nothing is
read back from the code under test.

Observed at base and frozen as goldens:

| gate | threshold row | per-file (name, unit) | fingerprint |
|---|---|---|---|
| `output_diversity_blocking` | `{metric: n_unique_int8_values, operator: ">", value: 25, unit: count}` | `n_unique_int8_values`, `count` | `…:n_unique_int8_values=1` |
| `output_std_blocking` | `{…, operator: ">=", value: 1.0, unit: mV}` | `output_std_mv`, `mV` | `…:output_std_mv=1` |
| `amplitude_collapse_blocking` | `{…, operator: "<=", value: 0.95, unit: fraction}` | `dominant_mode_fraction`, `fraction` | `…:dominant_mode_fraction=30` |
| `pearson_dispersion_recording` | **None** | `pearson_correlation`, `correlation` | None |
| `spectral_peak_ratio_recording` | **None** | `spectral_peak_ratio`, `ratio` | None |
| `per_file_output_std_recording` | **None** | `output_std_mv`, `mV` | None |

All six per-file rows carry `sampling_method = "channel0001_prefix_peek"` (L1).
The three `None` threshold rows are the **legitimate absences** §2.1 predicted
— the recording-only checks declare `threshold_parameter_names=()` — and a
dedicated test names them so a migration that "completes" them is RED.

**The defect, measured at both hops.** All three contrast gates
(`pets_distinct_symbols_blocking`, `pets_dominant_fraction_blocking`,
`davis_dispersion_blocking`) persist `threshold = None` **and** therefore
produce `fingerprint = None`, on the real 08c collapse values (370 predictions,
2 of 37 classes, dominant 369/370; DAVIS dispersion 0.0005 vs floor 0.04).
`per_file` is `{}` and `aggregate_statistics` is `{"count": 0}` for all three —
**correctly**, since these checks emit scalars and have no per-file dimension;
a test pins that so C2 does not invent per-file rows for them. This is the
§2.2 finding reproduced executably: the row is blank at hop 1, and the
fingerprint is blank at hop 2 *as a consequence*.

**`tests/unit/execute_tools/health_checks/test_step10_p4_c0_residual_census.py`**
— the migration tracker. All nine surfaces are located by CONTENT (AST), not
line number, so the census does not rot as lines move. `EXPECTED_PRESENT` is
the stage marker C2/C3′ edit:

| id | surface | owner | removed by |
|---|---|---|---|
| T1 | `_threshold` check-name branches | P4 | C2 |
| T2 | per-file metric-name dict | P4 | C2 |
| T3 | per-file unit dict | P4 | C2 |
| L1 | `channel0001_prefix_peek` literal | P4 | C2 |
| D1 | duplicated numeric defaults | P4 | C2 |
| T4 | `_WORST_STAT_BY_METRIC` | P4 | C3′ |
| L2 | `unit == "count"` literal | P4 | C3′ |
| **T5** | `_RECORDING_KEY_METRICS` | **HD-T5** | **NEVER — deferred** |
| **T6** | `_COLLAPSE_ADVICE_BY_CHECK` | **HD-T6** | **NEVER — deferred** |

The T5/T6 rows assert those surfaces **survive**: a dedicated test fails if a
later session absorbs them, which is the executable form of Q-P4-3.

Check-name literal census, hardcoded at base: `evaluation.py` = the six TIDMAD
check names (C2 drives this to `set()`); `health_feedback.py` =
`{"pearson_dispersion"}` — **T5's, not T4's**, so C3′ drives it to exactly that
one-element set and *not* to empty.

**IR-P4-1 — the census must collect `AnnAssign`, not only `Assign`.**
Both tracked constants are annotated (`_WORST_STAT_BY_METRIC: dict[str, str] =
…`), so a collector seeing only `ast.Assign` reports them ABSENT and the whole
census passes vacuously at every stage. Found while writing the detector;
pinned by `test_annotated_constant_is_collected`.

**Validation.**

* `pytest <both C0 modules>` → **21 passed, exit 0** (verdict read from the log).
* Targeted subsystem: `tests/unit/execute_tools/health_checks` +
  `tests/unit/guardrails/test_health_core_census.py` +
  `tests/unit/agent/schemas/test_health_feedback.py` → **856 passed, exit 0**.
* **Plant-and-catch on the real target**: renaming `_WORST_STAT_BY_METRIC`
  (3 occurrences) in the production module made the census **RED**
  (`test_every_tracked_surface_matches_the_stage_marker`, exit 1); reverting
  restored **10 passed, exit 0**, with `git status agent/` clean — the detector
  binds to the real file, not to a synthetic fixture. Caches were cleared
  around both directions.
* `ruff check` + `ruff format` clean. **RUF012** (mutable class attribute) was
  fixed with `ClassVar`, never a suppression.

**Environment limitation, recorded rather than glossed:** local `pyright`
could not execute in this worktree — the bundled pyright exits with a Node/JS
`require` error, not a type finding. This is the known unsupported-Node
condition; the exact-head CI owns that check. No local pyright claim is made
for C0.

**Deviation from the frozen plan: none.** C0's content matches §7 exactly.

**A note for C2/C3′, learned here:** Health check registration is
process-global and 08b's run-scope guard refuses a second, different plugin
set in one process. Composing two packs in one test REQUIRES
`_plugin_binding.reset_run_scope()` between them (the 08c three-task rung does
the same). The first draft of the coverage test omitted it and correctly
failed — that was a test defect, and the guard behaving exactly as designed.

### 19.2 C1 — declaration extension, populated but INERT — **[x] COMPLETE**

The ONE §13-sanctioned extension to `CheckInputDeclaration`, plus two new
frozen models in `schemas.py`, and all nine built-in declarations populated
with the tables' content. **No consumer reads any of it yet** — that is C2/C3′
— so C1's acceptance is that the C0 goldens are unchanged.

**`EvidenceUnit`** encodes R-2 as a type: exactly one of `literal`
(check-owned, dimensionless) or `config_key` (task-owned scale, resolved at
render time), enforced by a model validator. Declaring both is two
authorities for one unit; declaring neither is an unnamed unit; both fail
closed at authoring time.

**`ThresholdDeclaration`** carries `metric`, `operator`
(`Literal[">", ">=", "<", "<="]`), `config_key`, `default`, `unit`. The
closed operator vocabulary is load-bearing beyond rendering — it is the single
declaration C3′ derives the worst-case statistic from, which is what lets T4
be *deleted* rather than relocated.

**`CheckInputDeclaration`** gains `evidence_thresholds`,
`per_file_metric_name`, `per_file_metric_unit`, `sampling_method_label`. A
check declaring none of them persists exactly the absences it does today.

**IR-P4-2 — `threshold_parameter_names` is DERIVED, not co-authored, and the
field stays settable.** R-5 requires one authority. Removing the 08a field
outright would have been cleanest — but it would break the plugin ABI: an
out-of-tree check declares it directly (`test_out_of_tree_extension.py:114`),
and the frozen invariants forbid breaking external plugins. Resolution: a
`mode="before"` validator derives it from `evidence_thresholds` when omitted,
a `mode="after"` validator fails closed if both were authored and disagree,
and a check that declares only the 08a field keeps working untouched. One
authority for new authors, zero ABI breakage, disagreement impossible.
Pinned by `test_names_are_derived_when_not_authored`,
`test_disagreement_fails_closed` and
`test_plugin_abi_is_unchanged_for_a_declaration_without_evidence`.

**IR-P4-3 — `default` is `int | float`, not `float`.** Authoring it as
`float` silently coerced `5` → `5.0`, which would have rendered `5.0` where
the evidence has always said `5` — and the fingerprint's integer rendering
keys off exactly that type. Caught by inspecting the populated declarations
rather than by a test failure, because at C1 nothing consumes them yet.
Pinned by `test_count_defaults_stay_integers` and by
`test_declared_defaults_are_the_checks_own_defaults`, which compares against
the check's own `_DEFAULT_*` ClassVar (a transcribed literal would have been
a third copy, defeating R-3).

**A required reordering.** The declaration now references the check's own
`_DEFAULT_*` ClassVar (R-3: ONE number), and a class body executes top-down,
so every check's defaults had to move ABOVE its `declaration`. Done with an
AST-driven pass over exact statement spans rather than a regex, and verified
by import.

**IR-P4-4 — the 08a channel-literal guard was NARROWED, not widened.**
Moving the `channel0001_prefix_peek` label from `evaluation.py` onto each
check's `sampling_method_label` put it inside the six modules
`test_peek.py::TestNoChannelLiteralsSurviveInHealthCode` scans, and the guard
correctly went RED. That guard's own text distinguishes a **lookup** (the
hazard: a literal that agrees with the contract until a task binds different
channel groups, at which point the peek reads the wrong signal) from a
**persisted record label** (already whitelisted, "a recorded VALUE in
historical artifacts, not a lookup"). The label is exactly the whitelisted
category, moved to its owner. Rather than exempt six more FILES, the
exemption became SYNTACTIC: the literal is legal only on a
`sampling_method_label=` declaration line, anywhere else in the same file it
is still an offender. That is strictly stricter than the file-level whitelist
it replaces. **Mutation-proven**: a planted `_lookup = "channel0001"` inside
`output_diversity.run` turned the guard RED (exit 1) — the exemption bought
no amnesty for a lookup — and reverting restored green.

**Values migrated (verified against the C0 goldens, not transcribed):**
six per-file declarations and six threshold declarations. `output_std` and
`per_file_output_std` name `config_key="value_scale_unit"` for their unit
rather than the string `"mV"` (U1/R-2); `pearson_dispersion` and
`spectral_peak_ratio` keep dimensionless literals (`correlation`, `ratio`)
even though both RECEIVE `value_scale_unit` — the discriminating
counter-example §2.3 recorded. `sample_dispersion_floor` names the same
config key, so DAVIS (which declares no `value_scale`) renders no unit while
a task that declares one renders its own.

The three contrast checks gain the `evidence_thresholds` they never had
(`distinct_symbols` `>=`, `dominant_fraction` `<=`, `dispersion` `>=`) and
declare NO per-file name, unit or sampling label — they emit scalars and have
no per-file dimension.

**Validation.**

* C1 declaration tests: **19 passed, exit 0**.
* **Inertness — the real C1 acceptance**: the full Health subsystem plus the
  health-core census, `health_feedback`, the Gate-2 health stage and the
  examples suites → **1088 passed, exit 0**. The C0 goldens are untouched,
  which is the executable statement that C1 changed no behaviour.
* Mutation proof on the narrowed guard (above): RED planted / green reverted,
  caches cleared, production file restored.
* `ruff check` + `ruff format` clean (I001 import ordering fixed with ruff's
  own fix, never a suppression). Local pyright still cannot execute here
  (Node/JS runtime error) — CI owns it.

**Deviation from the frozen plan: none.** IR-P4-2/3/4 are mechanical rulings
inside the frozen semantics; none changes a threshold, verdict, action or the
public result schema.

### 19.3 C2 — `evaluation.py` reads declarations; T1/T2/T3/L1/D1 DELETED — **[x] COMPLETE**

`_threshold` and `_per_file_metrics` now take the check's `CheckInputDeclaration`
instead of its NAME. `_persist` resolves it once via `_declaration_for`, a
LOOKUP through the same registry the runner already used — nothing in the
evidence path interprets a check name any more.

**Deleted from generic code**: the three-branch `_threshold` name comparison
(T1), both per-check-name dicts (T2/T3), the universal
`channel0001_prefix_peek` literal (L1), the three duplicated numeric defaults
(D1) — and, found during C2, the `or` cascade over three TIDMAD metrics keys
(below).

**Q-P4-1 delivered exactly as ruled.** Configured value ⇒ persisted as today
with NO `source` key; absent key ⇒ the check's OWN declared default persisted
and labelled `source: "check_default"`. Never rendered as absent, never
raising. The value is cast to the type of the declared default, which
reproduces the removed table's per-branch `int()` / `float()` casts from the
declaration rather than per check name — so a hypothetical `min_std_mv: 1`
still persists `1.0`, exactly as before.

**IR-P4-5 — the `or` cascade was a fourth `evaluation.py` surface, not
enumerated at C0.** Promoting `evaluation.py` into the census GENERIC
partition failed on a surviving `mV`: `metrics.get("pearson_per_file") or
metrics.get("ratio_per_file") or metrics.get("std_mv_per_file")`. Same class as
T2/T3 — the generic builder knowing three TIDMAD checks' metrics keys — and
derivable, but NOT from an existing field: the key is not the evidence metric
name (`pearson_dispersion` publishes `pearson_per_file` and reports
`pearson_correlation`), so the two cannot be collapsed. Resolved inside the
same single extension with `per_file_metrics_key: str = "per_file"` — the
default is what the three list-shaped checks already use, and the three
named-dict checks declare their own. The cascade is deleted; a check with no
per-file values under its declared key yields no rows rather than falling
through to another check's key. This is a scope *completeness* finding of
exactly the kind §2.2 was about, resolved by derivation, not by a new table.

**Structural acceptance met**: `evaluation.py` was removed from
`TIDMAD_FAMILY_MODULES` in `tests/unit/guardrails/test_health_core_census.py`
and passes the generic census unchanged — zero task tokens, zero `int8` /
`channel0001` / `mV` literals, zero check-name literals. The exclusion comment
naming this debt and its Step-9/10 owner was replaced by the record of its
redemption.

**IR-P4-4 follow-through.** C2 removed the label from `evaluation.py`, so the
08a anchor test that asserted it was still there became stale. Both of its
purposes were preserved rather than dropped: the exemption must describe
something real (now asserted across the SIX declaring modules, and required to
appear in `sampling_method_label=` position), and the scanner must provably
find literals. A new test asserts the central literal is *gone* from the
persistence adapter, which is what the census promotion depends on.

**The contrast tasks' hop-1 defect is FIXED** — the C0 witness was flipped
deliberately, with the produced rows hardcoded:

| gate | threshold row after C2 |
|---|---|
| `pets_distinct_symbols_blocking` | `{metric: distinct_symbols, operator: ">=", value: 5, unit: count}` |
| `pets_dominant_fraction_blocking` | `{metric: dominant_fraction, operator: "<=", value: 0.95, unit: fraction}` |
| `davis_dispersion_blocking` | `{metric: dispersion, operator: ">=", value: 0.04, unit: **None**}` |

DAVIS renders NO unit because it declares no `value_scale` — R-2's rule that
an unresolvable task-owned unit renders nothing rather than a default. None of
the three carries a `source` label: all three values come from their pack
YAML. Their `per_file` stays `{}` — C2 invents no per-file rows for a scalar
check.

**TIDMAD parity: byte-identical.** All C0 goldens pass unchanged at both hops,
including the three legitimate threshold absences.

**Validation.**

* Targeted: health_checks + health-core census + health_feedback +
  gate2_health_stage + examples → **1115 passed, exit 0**.
* Q-P4-1 provenance module: **18 passed** — both branches asserted as a pair,
  plus the labelled default proven equal to the check's own `_DEFAULT_*` (not
  a transcribed literal), plus "never absent" and "never raises" as explicit
  tests of the two options the ruling rejected.
* R-2: a µV fixture proves the same framework check renders another task's
  unit — the property the literal `"mV"` could never have.
* **Plant-and-catch**: reintroducing a `check_name == "output_diversity"`
  branch returning a `"mV"` unit into `_threshold` turned **three independent
  guards RED** (health-core `mV` literal, residual-surface T1, check-name
  literal census); reverting restored 139 passed with zero check-name literals
  in `evaluation.py`. Caches cleared both directions.
* `ruff check` + `ruff format` clean across `execute_tools/` and `tests/unit/`.

**Deviation from the frozen plan: none.** IR-P4-5 extends the same single
declaration extension rather than adding a second authority; no threshold,
verdict, action or public schema changed.

### 19.4 C3 — three-task completeness + the fourth-task evidence proof — **[x] COMPLETE**

08b already proved a synthetic external task can REGISTER and RUN with zero
additional infrastructure edits. C3 proves the narrower P4 claim: that task's
check gets **evidence as complete as TIDMAD's**, with zero central metadata
edits and zero task-name branches.

The `zenith` fixture is deliberately unlike TIDMAD in every dimension the old
tables encoded: its own capability, its own metric name (`observed_drift`), a
`<` operator **no shipped check uses**, a task-owned unit (`kPa`) resolved
from a config key the check names itself (`pressure_unit`, not
`value_scale_unit`), its own per-file metrics key (`drift_per_window`) and its
own sampling label (`rolling_window_median`). Every one of those would have
been unrenderable before P4. Routed through `evaluation._persist` — the
production builder — and deliberately NOT through the D14 Gate runners, whose
`runner.evaluate_gate` bypass is where this defect hid.

Rendered: `{metric: observed_drift, operator: "<", value: 5.0, unit: kPa}`,
per-file rows named and united by the check, `sampling_method:
rolling_window_median`. Q-P4-1's fallback is generic too: unconfigured, the
row carries the check's own `9.0` labelled `source: "check_default"`.

Zero-central-edit proof: eight fixture identifiers asserted absent from
`execute_tools`, `nodes`, `agent`, `core`, `scripts`, `workflows` and
`configs` — by absence from source, never by inspecting a git diff, which
would describe this commit rather than the property.

Three-task completeness: all six declaring gates across TIDMAD, Pets and
DAVIS render a complete row through one path, with the three TIDMAD
recording-only gates correctly still absent.

**Two test-side defects, diagnosed before fixing:**

* the registry lookup ran BEFORE the out-of-tree plugin was loaded — ordering
  bug in the test, not a production fault;
* the identifier scan used a raw substring `in` and reported `kPa` inside
  `HealthChec`**`kPa`**`nelOutput`. A false positive. Fixed by matching on
  identifier boundaries, which is what the proof meant all along — recorded
  because the same trap will catch the next fixture that picks a short unit.

**Validation**: C3 module 5 passed; health_checks + health-core census green.

### 19.5 C3′ — T4/L2 DERIVED; both constants deleted — **[x] COMPLETE**

`_WORST_STAT_BY_METRIC` and the `unit == "count"` literal are gone.
`_worst_statistic(operator)` derives the direction from the declared
comparison operator — FLOOR (`>` / `>=`) is breached downward so the worst
observation is the `minimum`; CEILING (`<` / `<=`) is breached upward so it is
the `maximum` — and exactness comes from the declared unit via
`_INTEGRAL_UNITS`. An unrecognised or absent operator yields `None` rather
than a guess: an evidence reader must not invent a direction it was not told.

3/3 parity with the deleted map is asserted against its contents transcribed
as DATA, not imported — the constant no longer exists, and importing the new
code to generate the expectation would compare it against itself.

**IR-P4-6 — the value source follows the check's SHAPE, and the derivation is
incomplete without it.** C0 measured that the contrast checks' 
`aggregate_statistics` is `{"count": 0}`, because they have no per-file
dimension. A derivation that only read `aggregate_statistics` would therefore
still have produced NO fingerprint for exactly the tasks P4 exists to fix —
the defect would have MOVED one level deeper rather than gone. The rule is
generic and needs no table: *the worst observed value of the declared evidence
metric* — from `aggregate_statistics[worst_stat]` when the check is per-file,
and from the single value published under the DECLARED metric name when it is
scalar. This is why C1 chose the contrast checks' metric names to match the
keys they already publish (`distinct_symbols`, `dominant_fraction`,
`dispersion`); the alignment was deliberate, not luck. Non-numeric values and
booleans are rejected — `isinstance(True, int)` is True in Python, and a flag
is not a measurement.

**A pre-existing FIXTURE defect surfaced, and it was a real one.**
`tests/unit/agent/schemas/test_health_feedback.py::_gate` hardcoded
`"operator": ">"` for EVERY gate it built, including `_amplitude_gate` — which
models a CEILING check whose real persisted row says `<=` (C0's golden proves
it). The fixture claims to reproduce "real V17 persisted shapes" and did not.
It was harmless only because nothing read the operator: the direction came
from the redundant name map. Making the operator load-bearing exposed it
immediately. Fixed by giving the fixture the operator the check actually
declares, which makes it MORE faithful to the shape it claims. This is the
clearest evidence that the duplicate authority was masking drift rather than
providing safety.

**The defect is now closed at BOTH hops.** The C0 witness was flipped a second
time, with the new signatures hardcoded:

| gate | fingerprint after C3′ |
|---|---|
| `pets_distinct_symbols_blocking` | `…:distinct_symbols=2` |
| `pets_dominant_fraction_blocking` | `…:dominant_fraction=1` |
| `davis_dispersion_blocking` | `…:dispersion=0.0005` |

None of these existed before P4 — the contrast tasks had no fingerprint at
all. TIDMAD's three fingerprints and all six `key_metrics` entries are
byte-identical to the C0 goldens.

**R-7 made executable (the §3 second acceptance).** A census over
`health_feedback.py` fails on ANY module-level dict whose values are statistic
names, plus a direct assertion that the deleted constant is gone.
**Mutation-proven**: re-planting `_WORST_STAT_BY_METRIC` turned **three**
guards RED (the deleted-constant check, the relocation census, and the
residual-surface stage marker); reverting restored 32 passed. The surviving
`_RECORDING_KEY_METRICS` is HD-T5's, deferred by Q-P4-3, and is a SET of
recording scalars rather than a direction map — the census distinguishes them.

**Validation**: derivation module 22 passed; broad targeted sweep
(health_checks + census + agent/schemas + gate2 stage + examples +
interpretation + proposer) **2631 passed, exit 0**.

### 19.6 C4 — closure — **[x] COMPLETE**

**Final closure census (executable, loaded from this worktree):**

| module | check-name literals | `mV` | channel literals |
|---|---|---|---|
| `execute_tools/health_checks/evaluation.py` | **none** | no | **none** |
| `agent/schemas/health_feedback.py` | `pearson_dispersion` only | no | none |

The one surviving literal is **HD-T5's**, inside `_RECORDING_KEY_METRICS` —
deferred by Q-P4-3 and asserted to SURVIVE, which is why the census expects
exactly that one-element set rather than an empty one.

**Deferred debt verified intact**: `_RECORDING_KEY_METRICS` present,
`_COLLAPSE_ADVICE_BY_CHECK` present, and `git diff d44f6f6a..HEAD` touches
**neither `agent/prompts.py` nor `agent/llm_bridge.py`** — HD-T6 untouched, so
the Gate-1 NOT REQUIRED disposition holds on the evidence, not the intention.
`_WORST_STAT_BY_METRIC` is gone.

**Docs sync**: `docs/design/pluggable_health_checks.md` §6.1 (new) documents
the evidence half of the declaration — the two unit kinds, the load-bearing
operator and its worst-statistic derivation, fallback-only threshold
provenance, and declared absence — plus the statement that an ordinary
task-specific check now costs no framework edit while a new *capability*
(HD-T5 / HD-T6) still does.

**Validation.** Broad targeted sweep across every area this PR can reach —
`tests/unit/{execute_tools,guardrails,agent/schemas,agent/result_interpretation_agent,agent/ml_model_proposal_agent,examples,scripts,core}`
→ **6,660 passed, 1 skipped, 1 failed**.

The single failure is
`test_sdsc_argument_forwarding.py::TestPythonIsTheSingleValidator::test_an_unknown_flag_fails_the_runner_loudly`,
and it is **PRE-EXISTING and environmental, proven rather than assumed**: it
shells out to `REPO_ROOT/.venv/bin/python`, which does not exist in a git
worktree (the venv lives in the main checkout). Reproduced at the frozen base
`d44f6f6a` in a throwaway detached worktree — **1 failed, 2 passed** there
too, with none of P4's code present. It touches no Health surface and CI runs
in a checkout that has a `.venv`.

`ruff check` and `ruff format --check` clean across `execute_tools/`,
`agent/` and `tests/unit/`. Local `pyright` cannot execute in this
environment (the bundled binary exits on a Node/JS `require` error, not a type
finding) — recorded as a limitation at every commit; the exact-head CI owns
that check.

### 19.7 CI fix — the one error local pyright could not have caught

Exact-head CI on `ae5b4698` reported **one error** amid pre-existing warnings:

```
execute_tools/health_checks/evaluation.py:119:23 - error: Argument of type
"str | None" cannot be assigned to parameter "key" of type "str"
```

`_resolve_unit` passed `unit.config_key` straight to `config.get`.
`EvidenceUnit`'s validator guarantees exactly one of `literal` / `config_key`
is set, but that is a RUNTIME invariant enforced in another layer — pyright
cannot see it, and neither can a reader of this function. Fixed by narrowing
explicitly and saying why, rather than by an assert or a suppression.

This is exactly the class of defect the recorded environment limitation
predicted: local pyright could not execute in this worktree, every commit said
so, and CI owned the check. The process worked as designed — the gap was
declared rather than discovered.

Fix commit: **`d57d2482`** — the final executable head.

### 19.8 Post-merge closure and the P2a interaction

**Merged**: PR #243, squash `79833db8`, `origin/master` verified
byte-identical to the validated head `d73e39e3`. Independent final review
before merge: **PASS**, no corrections required — every review point checked
against source and executable probes rather than the implementation session's
self-report, including a fresh anti-vacuity mutation (a *differently named*
central direction map and a task-name branch in generic evidence code; both
caught, by different guards).

**P2a interaction, measured — not assumed.** P2a
(`step10-p2a-golden-metric-order-closure`, PR #242, head `0ea3d238`) was
reconciled against P4 in a THROWAWAY worktree; its live branch and worktree
were not touched, and PR #242 was not updated.

| | result |
|---|---|
| shared changed files (production AND test) | **0** |
| merge of P4 into P2a | **clean, no conflicts** |
| combined-tree targeted tests | 1,441 passed + 3,114 passed |
| semantic classification | **A — no overlap** |

The one adjacency the frozen §16 predicted holds and composes: P2a edits
`nodes/result_interpretation_agent/evidence.py`, the CALLER of
`agent/schemas/health_feedback.py` which P4 edits. Adjacent, not competing.
**P2a owns its own terminal reconciliation against the now-P4-bearing master**;
it should be mechanical.
