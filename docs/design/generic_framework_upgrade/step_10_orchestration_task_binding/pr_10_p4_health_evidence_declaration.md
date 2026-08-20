# Step 10 / P4 — Health Evidence Declaration Migration

## 0. Status

**DRAFT rev 1 — FOR OPERATOR REVIEW. NOT FROZEN. IMPLEMENTATION NOT
STARTED.** Semantic design complete; the least upstream-sensitive Step-10
child — **likely candidate for early freeze after source reconciliation**
(no dependency on P2a/P2b/P3/P5; P1 is already merged). Not frozen in this
session by mandate.

| field | value |
|---|---|
| parent | Step-10 parent REVISION 2 (frozen), §3.5 / §13; owns scope item **S6** |
| source anchor | merged `master` = **`d7d94740`** (production tree == P1 squash `bcb17e45`). All §2 sites re-verified at this anchor |
| depends on | nothing unmerged. P1 (merged) supplies the composed Health binding used to DEMONSTRATE on a second task; Step 08's declaration/plugin architecture is the substrate |
| downstream | **P6** (contrast-task loop runs produce COMPLETE persisted Health evidence only after this lands) |
| Gate disposition | proposed: **NO Gate** — declaration-ownership migration with deterministic evidence-parity and evidence-completeness owners (§8). Quoted against the gate standard at freeze |
| open operator questions | **1** (§12) |

---

## 1. Parent contract (recovered, binding)

* **§3.5**: Step 08 finished Health OWNERSHIP migration except
  `execute_tools/health_checks/evaluation.py`, which still holds **three
  tables keyed on TIDMAD's check NAMES** plus a duplicated default constant
  and a sampling-method literal. The failure mode is **silence**: a
  task-owned check absent from the tables persists evidence with no
  threshold, no metric name, no unit — "the gate still fires and still
  blocks correctly; its evidence is quietly poorer than TIDMAD's".
* **§13 constraints (frozen)**: NO Health scientific semantics change —
  verdicts, actions, severity resolution and thresholds bit-identical for
  TIDMAD; a task-specific check requires NO central-table edit; extending
  `CheckInputDeclaration` ONCE is allowed (a new *capability*, not a new
  *task*); the `:89` / `tidmad.yaml` disagreement is repaired **by removing
  the duplicate**, never by editing one side to match.
* **§20.3**: P4 is independent — "needs P1 only to *demonstrate* on a
  second task" (P1 has merged, so nothing blocks P4).
* Known live latent defect (parent §3.8 tail): Pets declares
  `categorical_distinct_symbols`/`categorical_dominant_fraction` and DAVIS
  declares `sample_dispersion_floor`, and NONE is in any table — unbitten
  only because the D14 Gate runners bypass `evaluation.py`. The moment a
  contrast task routes through the tuner (P6), its persisted health evidence
  goes blank. P4 exists so P6 does not inherit that.

---

## 2. Current source audit (measured at `d7d94740`)

### 2.1 The residual central tables — re-verified line-exact

| # | site | shape | task-specific content |
|---|---|---|---|
| T1 | `evaluation.py:84-107` `_threshold(check_name, config)` | `if check_name == "output_diversity": … elif "output_std" … elif "amplitude_collapse" …` | per-check: evidence metric name, comparison OPERATOR (`>`/`>=`/`<=`), config KEY, UNIT, and a hardcoded DEFAULT (`5`, `1.0`, `0.95`) |
| T2 | `evaluation.py:117-124` | dict of SIX check names → per-file metric names | names |
| T3 | `evaluation.py:124-131` | dict of six check names → units (`count`/`mV`/`fraction`/`correlation`/`ratio`) | units |
| L1 | `evaluation.py:158` | `"sampling_method": "channel0001_prefix_peek"` — one literal for EVERY check's per-file rows | a TIDMAD-shaped sampling label applied universally |
| D1 | `evaluation.py:89` | `config.get("min_unique_int8_values", 5)` | a SECOND declaration of a threshold whose task value is `25` (`configs/task_health/tidmad.yaml`) — the duplicate-authority shape, currently masked because the composed effective config always carries the key |

### 2.2 Consumers — evidence only, never verdicts

`_per_file_metrics` is called at `:216` and `_threshold` at `:263`, both
inside the construction of `PersistedHealthGateResult` (`:210-270`). The
gate's PASS/FAIL comes from the TYPED check results; the tables feed only
the persisted EVIDENCE (threshold row, per-file metric naming, units,
sampling label). **This confirms the parent's scoping: P4 is an evidence
migration; actions/verdicts are structurally untouched.**

### 2.3 The declaration substrate that already exists (Step 08)

`CheckInputDeclaration` (`execute_tools/health_checks/schemas.py:880`):
frozen model with `consumes_view`, `requires_view`,
`required_context_inputs`, `required_facts`, and
`threshold_parameter_names` — the last one already populated by every
shipped check (`output_diversity.py:64` → `("min_unique_int8_values",)`,
etc.). Checks register through the public `register`; external task plugins
register the same way with content digests pinned (08b); the registry maps
check NAME → registered check, so `evaluation.py` can resolve a name to its
declaration with **no new lookup mechanism**.

### 2.4 Residual-debt table (audit → owner)

| central source | task-specific content | current consumer | proposed declaration owner | generic mechanism preserved | migration validation |
|---|---|---|---|---|---|
| T1 operator/unit/metric-name/key | per-check evidence identity | persisted threshold row | the CHECK's own declaration (extended `CheckInputDeclaration`, §4.1) | threshold VALUE still read from the run's effective CONFIG (task-owned, 08b) | TIDMAD threshold rows byte-identical on fixtures |
| T1 defaults `5`/`1.0`/`0.95` | duplicated threshold constants | same | **REMOVED** — the config is the only value source (§4.3) | fail-closed absence: no second default | absent-key fixture renders a named absent state, never `5` |
| T2 metric names | six names | per-file rows | check declaration | row construction unchanged | per-file rows byte-identical for TIDMAD |
| T3 units | six units | per-file rows | check declaration | same | same |
| L1 sampling label | TIDMAD peek label | per-file rows | check declaration (each check states how it sampled) | row shape unchanged | TIDMAD rows byte-identical; a view-based check states its own label |
| D1 | see T1 defaults | — | — | — | the 5-vs-25 disagreement dies WITH the duplicate |

---

## 3. Goal / semantic owner / boundary

**One semantic owner: Health evidence declaration.** After P4, everything
the three tables know is declared BY the check that knows it; `evaluation.py`
reads declarations through the existing registry; the tables are deleted; a
task-owned check's persisted evidence is as complete as TIDMAD's with zero
central edits.

Proposed boundary (names `PROVISIONAL`, shape not):

```text
CheckInputDeclaration — extended ONCE (the §13-sanctioned framework change):
    evidence_thresholds: tuple[ThresholdDeclaration, ...]   # config key, operator, unit, evidence metric name
    per_file_metric_name: str | None                        # None = check emits no per-file metric rows
    per_file_metric_unit: str | None
    sampling_method_label: str | None                       # what the check states about its own sampling
```

The exact field grouping (one nested block vs flat fields) is an
implementation choice; what is frozen by this draft is: **declarative data
on the check, resolved via the existing registry, zero name-keyed tables in
generic code, and no framework-owned default values for task thresholds.**

**Non-goals**: check arithmetic; verdict/aggregation/action machinery; the
plugin ABI and loaders (08b's, reused); `health_policy`; any threshold
VALUE; the `evaluation.py` gate-selection logic; Health's ContextVar/binding
lifecycle (P1's); dashboards.

---

## 4. Design decisions (load-bearing)

### 4.1 Declaration-driven, resolved through the registry

`evaluation.py` already has the check NAME (from the gate config) at both
consumer sites. It resolves the registered check's declaration
(name → registry → ClassVar) and renders the threshold row / per-file
naming / sampling label from THAT. Built-ins carry their migrated table
content on their own declarations; task-plugin checks carry theirs; an
UNREGISTERED name is already a fail-closed configuration state upstream.

### 4.2 Absence is a named state, not a blank

A check that declares no per-file metric (`per_file_metric_name=None`)
produces rows without a fabricated name — the CURRENT behaviour for unknown
checks, now an explicit declaration rather than a table miss. A check with
no `evidence_thresholds` persists no threshold row (recording-only checks
already declare `threshold_parameter_names=()` — the same honest shape).

### 4.3 The duplicate-default repair (parent-mandated shape)

The threshold VALUE is read from the run's effective config under the
declared key with **no fallback constant**. If the key is genuinely absent
(a hand-written pre-08b config), the persisted threshold row records a named
absent value rather than a silently invented `5`. This is the ONE deliberate
behaviour delta of P4, it is fail-closed-shaped, and it is unreachable for
every composed/shipped config (the effective config always carries the
keys). Stated rather than hidden.

### 4.4 What the three tables' CONTENT migration must preserve

For TIDMAD's six checks the migrated declarations carry byte-for-byte the
values the tables hold today (operator symbols, units, metric names, config
keys, the `channel0001_prefix_peek` label). The migration moves WORDS, not
meanings — pinned by fixture parity on persisted evidence.

## 5. Three-task control

| | TIDMAD | Pets | DAVIS | same path? |
|---|---|---|---|---|
| Health family | `configs/task_health/tidmad.yaml`, 6 checks | pack `declared/task_health.yaml`: `categorical_distinct_symbols`, `categorical_dominant_fraction` | pack `declared/task_health.yaml`: `sample_dispersion_floor` | YES — 08b binding states |
| evidence today | complete (tables know the names) | **blank** (absent from every table) | **blank** | — |
| evidence after P4 | byte-identical | complete, from the checks' own declarations | complete | YES — one registry-resolved declaration read |
| threshold values | task YAML (unchanged) | pack YAML (5 / 0.95, frozen by 08c) | pack YAML (0.04) | YES |

Fourth task: a new check INSTANCE = declaration/config only, zero framework
edits; a genuinely new BACKEND capability (a new view kind, a new evidence
shape the declaration cannot express) is legitimate framework work — the
§7.2 distinction, restated here because P4 is where it is most tempting to
blur.

## 6. Structure preflight

| file | now | P4 change | owners after |
|---|---|---|---|
| `execute_tools/health_checks/schemas.py` | large, coherent schema family | +the ONE declaration extension | unchanged |
| `execute_tools/health_checks/evaluation.py` | evidence persistence + gate evaluation | tables DELETED; two consumer sites read declarations; net NEGATIVE | unchanged set |
| the six built-in check modules | one check each | +declaration fields each | unchanged |
| Pets/DAVIS pack plugins | task-owned | +declaration fields on their checks (TASK-owned edits, not framework) | unchanged |

No new module is expected; if the declaration-rendering grows past a
coherent inline shape, the minimum extraction is a private
`_evidence_rendering.py` beside `evaluation.py` — decided at implementation
by ownership, not by LOC.

## 7. Proposed commit decomposition (PROVISIONAL until freeze reconciliation)

* **C0** — evidence goldens: persisted `PersistedHealthGateResult` fixtures
  for all six TIDMAD checks at base (threshold rows, per-file naming, units,
  sampling label), plus the CURRENT blank-evidence capture for one Pets and
  one DAVIS check (the defect, recorded before the fix); table census
  (the three name-keyed tables exist, byte-listed).
* **C1** — the declaration extension + built-in declarations populated with
  the tables' content; NO consumer change yet (inert data, schema tests).
* **C2** — `evaluation.py` consumers read declarations; tables DELETED;
  TIDMAD fixtures byte-identical to C0; Pets/DAVIS fixtures flip from blank
  to complete; the absent-key state test; plant-and-catch (a re-introduced
  name-keyed table / a check name branch turns a census RED).
* **C3** — task-pack declarations (Pets/DAVIS plugin checks) + the
  three-task evidence-completeness fixtures through `evaluation.py` (the
  §13 acceptance route) + fourth-task instance proof (a synthetic check via
  declaration/config only; zero framework edits, censused).
* **C4** — closure: censuses, docs sync (`health_checks` docs + the design
  doc ledger), ONE exact-head CI.

## 8. Validation strategy / Gate disposition

Deterministic owners: TIDMAD evidence byte-parity fixtures (C0 goldens);
Pets/DAVIS completeness fixtures routed through `evaluation.py` (NOT through
the Gate runners — that bypass is the defect's hiding place); the absent-key
named state; AST census (zero check-name-keyed tables/branches in generic
health code, planted offender RED); schema tests for the declaration
extension; the existing 08a/08b verdict manifests stay untouched and green.

**Gate 1: NOT REQUIRED** (no LLM surface). **Gate 2: NOT REQUIRED** — this
is declaration transport/ownership; the real-lifecycle Health evidence
under a live run belongs to P6's closure. A deterministic migration failure
must never be compensated by a Gate.

## 9. Preservation invariants

Verdicts, actions, severity resolution, thresholds: bit-identical for
TIDMAD. The pinned effective-config sha MECHANISM untouched. `health_policy`
untouched. The 08b plugin/binding lifecycle untouched. Persisted evidence
for TIDMAD: byte-identical (C0 goldens). The ONLY deltas: task-owned checks
gain complete evidence; the absent-config-key state becomes named.

## 10. Failure / edge cases

| case | behaviour |
|---|---|
| check name not in the registry at evidence time | already fail-closed upstream (selection); evidence code never invents a declaration |
| a check declares thresholds but the config lacks the key | named absent value (§4.3) — the honest repair of D1 |
| recording-only checks | declare no thresholds; no threshold row — today's shape, now explicit |
| legacy persisted artifacts | untouched — P4 changes production of NEW evidence only; readers of old records see what was recorded |
| a plugin declares a unit/name the renderer never saw | rendered verbatim — declarations are data, the framework does not enumerate them |

## 11. Risk register

| risk | mitigation |
|---|---|
| the tables reappear as one "generic" catalog module | census forbids name-keyed tables anywhere in generic health code; the plant proves it fires |
| a threshold VALUE silently moves during migration | values never migrate — only the config KEY name is declared; TIDMAD byte parity is the proof |
| scientific-metadata vs framework-mechanics blur | §2.4's explicit split column; the declaration carries WORDS about evidence, never behaviour |
| P6 lands first and inherits blank evidence | sequencing note: P4 has no unmerged dependency and should land well before P6 |

## 12. Open operator questions

| id | question | proposal |
|---|---|---|
| **Q-P4-1** | The absent-config-key threshold state (§4.3): named-absent evidence (proposed) or hard fail-closed at evidence time? | named-absent — evidence rendering must not turn a running gate into a crash; the gate's own config validation upstream remains the fail-closed edge. Dispositioned at freeze |

## 13. Cross-child ownership

* P4 touches NO carrier (`ChainState`/`WorkflowRunBindings`/composition) —
  its surface is check declarations + `evaluation.py`.
* No dependency on P2a/P2b/P3/P5; implementable in parallel with P3 (and
  with P5, absent shared files — re-checked at freeze).
* P1's composed `task_health_binding` is how a second task's family reaches
  `evaluation.py` in tests; P4 adds no binding mechanics.
* Hand-off to P6: complete evidence for contrast tasks through the GENERIC
  route; the Gate runners' direct-`runner.evaluate_gate` bypass is retired
  by P6 per Q-10-5 = B.

## 14. Post-upstream reconciliation obligations (before freeze)

1. Re-verify §2.1's five sites at the freeze-time master (P2a/P2b do not
   touch health, but verify).
2. Confirm no OTHER name-keyed residue appeared (census re-run).
3. Quote the gate standard for the NO-Gate disposition; disposition Q-P4-1.

## 15. Adversarial self-review (draft-stage)

| attack | answer |
|---|---|
| Central table merely renamed? | the census bans name-keyed tables in generic health code wherever they live; declarations are per-check ClassVars, not a catalog |
| Task metadata remains in generic code? | the three tables + literal + default are enumerated for deletion; census guards regression |
| Scientific threshold accidentally moved/changed? | values never migrate; TIDMAD byte parity + the D1 repair removes a default rather than choosing one |
| New task check requires framework edit? | C3's fourth-task instance proof; §7.2 distinction stated |
| Health ACTION semantics drift? | consumers are evidence-only (`:216`/`:263` audited); verdict machinery untouched; 08a/08b manifests stay green |
| Task-name branch? | none exists, none is added; the Step-10 class-(b) census inherits |
