# PR 08c — contrast families + generic collapse checks + three-task evidence (child design)

## 0. Status and provenance

**REVISION 2 — FROZEN. Operator ruling 2026-08-18. IMPLEMENTATION NOT
STARTED.**

Rev 1 (`3e94133f`) was reviewed by the operator with the verdict **APPROVED
IN DIRECTION / REQUIRED FINAL FREEZE AMENDMENTS**: the six-commit
architecture is approved, C1–C6 are not redesigned, no new milestone is
added, and all four open questions are resolved (§0.1). Rev 2 applies the
sixteen freeze amendments (§0.2) and freezes per the ruling's own §16
procedure — the operator authorized freeze WITHOUT a further design-review
round unless the one-time DAVIS measurement exposed a scientific ambiguity.
**It did not** (§2.9: one clean measurement, all values finite, an honest
safety floor exists), so this revision is frozen.

Child of the FROZEN Step-08 parent (rev 3). Authority order: frozen parent >
current source (§2) > merged 08a/08b implementations and ledgers > roadmap
§8/§22.24 > `pluggable_health_checks.md`.

**Audit anchor.** Master **`d7b2c8c9`** (merged 08b squash `13e28796` + doc
sync), with three amendment-mandated audits added at rev 2 (§2.8–§2.11) and
real-artifact claims verified against the preserved D14 evidence on this
machine. **Zero `SOURCE-INSPECTION REQUIRED` markers. Every implementation
checkbox in §4 is `[ ]`.**

### 0.1 Operator rulings incorporated (all four questions closed)

| id | ruling |
|---|---|
| **Q-08c-1** | **A — with frozen details (§3.3).** `TaskHealthFacts.symbol_cardinality` is the ONE authority; declaration-driven composition injection; **not a threshold**; an authored roster parameter colliding with an injected key **fails closed**; NO blanket "all FACT_AXES become parameters" — only the explicitly frozen injectable axes participate. |
| **Q-08c-2** | **A — with the verdict boundary frozen (§3.2a).** Readable-but-invalid values are Health **FAILED**; unreadable/unmaterializable structure is **ERROR**; empty evidence is **ERROR**. Integrity validation lives in the consuming checks (one shared pure helper), never in the opaque engine. |
| **Q-08c-3** | **A.** Pets/DAVIS task-health config and reference evidence live in their reference packs and bind through explicit state C. TIDMAD's `configs/task_health/` location is the state-A legacy-default responsibility, not a precedent for a central catalog. |
| **Q-08c-4** | **A.** Extend the two existing D14 runners with ONE shared Health evaluation-stage implementation, so the Gate-2 artifact is the fresh one this run's training/inference produced. |

### 0.2 The sixteen freeze amendments, and where each landed

| # | amendment | landed at |
|---|---|---|
| 1 | restore implementation autonomy (commits + the two specified Gates autonomous; the rev-1 stop-and-show / pre-Gate-approval rules were an accidental procedural regression) | §4.0, §7 |
| 2 | freeze an efficient NumPy-backed standard payload ABI — never dense Python-object materialization | §2.10, §3.1 |
| 3 | biconditional discipline for the upgraded dispersion check — drop the `encoding_family` seed-scaffold requirement its arithmetic never consumes | §2.11, §3.4, C2 |
| 4 | cardinality is injected, never a second task parameter; authored collision fails closed; no blanket axis generalization | §3.3, C2 |
| 5 | integrity verdict boundary frozen (ERROR vs FAILED); shared validity helper | §3.2a, C2 |
| 6 | thresholds frozen at design time — Pets `5` / `0.95` with the four-value evidence pin (incl. occupancy 2/37); DAVIS measured ONCE, `min_dispersion = 0.04` with recorded margin | §2.9, §3.4 |
| 7 | DAVIS evaluates the FULL decoded view; no prefix cap; any future sampling is a frozen-semantics change → STOP | §3.5, C4 |
| 8 | artifact-decoding ownership audited; independent provider projection is the narrow source-grounded choice; codec-parity regressions REQUIRED for BOTH tasks | §2.12, C3, C4 |
| 9 | runner evidence is additive (`health:` nested block; existing D14 fields untouched); the stage evaluates EVERY selected gate — it is evidence collection, not tuner round control | §3.5, C5 |
| 10 | census registration claim corrected: EXTERNAL registration needs no central edit; the bootstrap legitimately enumerates framework-shipped built-ins | §4.6 |
| 11 | runner-owning test surface audited (none exists — recorded); the NEW shared-stage tests own the runner evidence contract directly | §2.8, C5, C6 |
| 12 | TIDMAD validation economical: no new TIDMAD Gate; every-commit deterministic parity instead; parity movement → STOP and re-disposition | §3.6, §6 |
| 13 | two real 08c Gates, AUTONOMOUS after their specs are written into the ledger | §7 |
| 14 | explicit runtime projection replacing the ambiguous wording | §7 |
| 15 | the final Step-08 validation stack made explicit | §3.7 |
| 16 | freeze/bootstrap procedure (adversarial pass → freeze → master → fresh implementation branch → do NOT implement) | executed at this commit |

### 0.2a Final operator approval (2026-08-18) — three minor corrections

The operator's final review returned **APPROVED WITH THREE MINOR
CORRECTIONS — NO FURTHER DESIGN REVIEW REQUIRED**, applied in this
revision:

1. **Parent factual erratum** — the parent's "dominant fraction = 1.0"
   prose (§3.1 table, §3.1 narrative, §9 L2) corrected to the measured
   369/370 = 0.9972972972972973 with 2 distinct classes, and the
   Pets/DAVIS evidence-directory citations annotated; marked in the parent
   as factual evidence/provenance correction only, frozen architecture and
   acceptance unchanged. The child's authority chain is now free of the
   §2.7 inconsistency (that section stands as the audit record of what was
   corrected).
2. **NumPy no-copy contract precision** — the ABI asserts
   `np.shares_memory` + read-only view + provider writeability/contents
   preserved (both directions), never exact `.base` identity (§3.1, C1).
3. **DAVIS float precision ownership** — the provider hands over the
   NATIVE float32 stream; the CHECK owns float64 accumulation
   (`np.std(..., dtype=np.float64, ddof=0)`); no contract claims
   concatenation upcasts (§2.9, §3.5/§3.5a, C2, C4). Verified at freeze to
   reproduce the frozen dispersion bit-equal.

### 0.3 What this PR is, in one paragraph

08b built the extension architecture and proved it with a synthetic fourth
task. 08c puts the first REAL contrast content through it: the two
framework-standard view capabilities (`categorical_predictions`,
`continuous_samples`) with their first consumers — three generic collapse
checks with hand-computed arithmetic — and the Pets and DAVIS health
families, bound as reference packs **through the SAME public interface an
external user would use, never a privileged path**. The framework then does
what D14 could only observe: it detects the REAL preserved Pets
constant-prediction collapse as a blocking failure, and evaluates a REAL
DAVIS dense artifact, with zero task-name knowledge. The milestone census
extends to health core and the Step-08 completion criteria (parent §14 A–H)
close.

### 0.4 The boundary this PR must not cross

Per Q-08b-4 and the parent §11: 08c owns the standard capabilities, the
reusable generic checks and the Pets/DAVIS bindings. It does NOT own:
prompt/planner exposure of health (any PB delta re-dispositions Gate 1 —
none is elected), tuner integration of Pets/DAVIS (parent §3.3.3: *"claiming
tuner-integrated Pets health would be maturity inflation"* — Steps 10/12),
TIDMAD re-parameterization (§3.6), Step-09 interpretation, or the Step-10/12
composition root.

## 1. Mandate (frozen parent, §12 08c — quoted obligations)

* **Goal**: Pets and DAVIS bind real health families; the generic
  categorical/continuous collapse checks exist with hand-computed
  arithmetic; the framework detects the REAL D14 Pets collapse and
  evaluates a REAL DAVIS artifact with zero task-name knowledge; the
  guardrail census extends to health.
* **Allowed changes**: new task health bindings (packs declare config), the
  generic check family, the bounded real-artifact evaluation path
  (runner-pattern), census extension.
* **Acceptance**: collapse fixture-of-record → blocking-fail with the
  dominant-fraction evidence persisted; DAVIS npz → verdicts through the
  continuous family; TIDMAD untouched (goldens); Pets/DAVIS bindings
  register through the SAME public interface external plugins use; census
  per parent §13 including the strengthened structural items. The
  fourth-task extensibility claim is NOT re-proven by walkthrough — 08b's
  proof test keeps passing.
* **Gates** (parent §12 08c + §10 table): Gate 2 = bounded real Pets +
  DAVIS artifact evaluations (≤10 min each, D14 runner pattern; PASS/FAIL
  from semantic evidence). Gate 1: none unless a prompt delta is elected
  (none is).
* **Completion**: parent §14 items B, C, D and the 08c halves of F/H close
  here; A (TIDMAD goldens) must remain true at every commit.

## 2. Source audit (at master `d7b2c8c9`, merged 08b `13e28796`)

### 2.1 The landed 08b seam this PR builds on (file:line)

| element | location | behaviour 08c consumes |
|---|---|---|
| view transport | `_view_provider.py:48` `HealthView` (**`arbitrary_types_allowed=True` at `:56`** — a NumPy payload flows through TODAY with zero transport change), `:73` `HealthViewProvider` | opaque envelope; `materialize(capability_key, ctx, config)`; I/O only after applicability |
| provider registration | `registry.py:74` `register_view_provider` (public, `__init__`-exported) | pack plugins register providers exactly as the 08b acme fixture did |
| plugin loading | `_plugin_binding.py:354` `load_task_health_plugins` | config-named `.py`, run-scoped ledger, content digests → pinned identity |
| Phase-B resolution | `_plugin_binding.py:466` `resolve_task_health_bindings` | unresolved check/provider/capability → `HealthBindingError`; also sets `bound_task_facts` (`:544`) |
| materialization step | `_plugin_binding.py:554` `materialize_view`; wired in `runner.evaluate_gate` inside the Bug-B guard | a check with `requires_view=True` receives `view=`; provider failure → `CheckVerdict.ERROR` |
| composition | `config.py:533` `load_composed_health_config`, `:580` `materialize_effective_config(..., task_health_binding=)` | state C (explicit path) is the route Pets/DAVIS take; state A composes TIDMAD (`_composition.py:89`) |
| disposition→policy | `_composition.py:105` `DispositionPolicy`, `:186` `compose_gate` (parameter/policy/peek/scale update order at `:226-230`) | task selects `blocking`/`recording`; framework derives role/cadence/actions/`aggregation` |
| fact-parameter injection precedent | `_composition.py:243` `value_scale_parameters_for` (+ keys `:170`, `:179`) | declaration-driven; **the mechanism §3.3 extends for cardinality, with the new collision refusal** |
| declarations | `schemas.py:880` `CheckInputDeclaration` (`requires_view` `:899`), `:741` `FACT_AXES`, `:1000` `applicability` | one applicability authority; biconditional discipline (declare only what you consume) |
| D18 | `schemas.py:113` `PerSampleEvidence` | already landed; 08c adds nothing to it |
| bootstrap | `__init__.py:95` `_bootstrap_registry` (invoked `:120`) | the built-ins' convenience bootstrap — the generic checks join it; EXTERNAL registration never needs it (§4.6's corrected census claim) |

### 2.2 `FACT_AXES` already covers both new tasks — no axis growth

`FACT_AXES = {encoding_family, symbol_cardinality, value_scale_unit,
file_group_size, sampling_frequency_hz}` (`schemas.py:741`). Pets declares
`encoding_family` (a NEW opaque VALUE — values are open) plus
`symbol_cardinality=37` (the axis exists; `TaskHealthFacts` `:798` already
validates cardinality>1 with an accompanying family). DAVIS declares
`encoding_family="continuous_float"` — the exact value the 8.4 rung corpus
has used since 08a. **The parent's growth discipline holds with zero new
axes**, which is itself §13 evidence.

### 2.3 The 8.4-C seed check and its own recorded 08c disposition

`sample_dispersion_floor.py` is the 08a negative control. Its docstring is
explicit about this PR: *"The full generic continuous family — a real view
provider, real artifact reads, task-owned thresholds — is 08c."* Its
capability key is deliberately fixture-spelled
(`step08.fixture_continuous_samples`), threshold `min_dispersion`, and it
already fails CLOSED (`CheckVerdict.ERROR`) on empty samples. Consumers at
the anchor: `__init__` bootstrap; `tests/.../test_step08_44_rungs.py`
(arithmetic + rungs B/C + "registered but configured nowhere in production"
`:150`); `test_plugin_binding.py::BUILTIN_CHECK_NAMES` (hardcoded 7-name
tuple); the shipped-config baseline census. **No production YAML references
it** — the upgrade surface is fully enumerated.

### 2.4 The three real deliverables and the preserved artifacts

| | TIDMAD | Pets | DAVIS |
|---|---|---|---|
| deliverable | per-file HDF5 int8 | ONE CSV, header `image_id,predicted_class_index` (`pets_data_path.py:255` naming; `:232` header-checked reader → `{image_id: int}`) | ONE compressed npz `{clip_key: float32 [3,4,128,224]}` (`davis_data_path.py:310` writer, `:332` reader) |
| preserved real artifact | Gate-2 corpora (08a/08b) | `predictions_pets_reference_cnn_d14p_pets_gate2_001.csv`, **6 812 bytes**, sha256 `cc8470267fbf5331827c7b641ac2ce8efb834b07441a31836084d4d417ff752c` — byte-identical in BOTH `/home/klz/Data/SIDEREIS_DATA/d14_pets_gate2_20260818{,b}/`; recorded in D14 `gate_evidence.json` | `predictions_davis_reference_predictor_d14d_davis_gate2_001.npz`, **17 874 045 bytes**, sha256 `ee52a7109798a1c4c608e7824e623604e2986dab8d499b75a4794d443e0fa010`, in `/home/klz/Data/SIDEREIS_DATA/d14_davis_gate2_20260818c/` (`gate_evidence.json`: mse `0.017289766656259548` — the D14 record value) |
| committability | n/a | **YES — the parent §9 "committed fixture-of-record (small, deterministic)"** | NO (17.9 MB) — real-npz evidence is the Gate-2 runner + a skip-guarded machine-local test; in-repo unit fixtures are small synthetic arrays |

### 2.5 The REAL collapse, measured from the artifact (not from prose)

Computed directly from the preserved CSV at the anchor — these are the four
hand-computable evidence values the tests pin (§3.4, C3):

```text
n                 = 370
distinct          = 2   (of 37)
occupancy         = 2/37   = 0.05405405405405406
dominant fraction = 369/370 = 0.9972972972972973   (dominant class = 5)
metric (D14 gate_evidence.json): accuracy = 0.02702702702702703 = exactly chance
```

### 2.6 The runner harnesses and the 08b guardrail that must move

`scripts/run_pets_gate2.py` / `run_davis_gate2.py` are the D14
direct-execution harnesses (train → infer → write deliverable → metric →
`gate_evidence.json`; pack roots at `run_pets_gate2.py:36-38`). At the
anchor they never enter Health composition, and
`tests/unit/guardrails/test_step08b_cross_task_compatibility.py::`
`TestNeitherExistingTaskCanReachTheTidmadFallback` (`:84`) PINS that: no
call to a composition entry point (`:99`), no health import (`:110`), with
an anti-vacuity probe (`:122`). **C5 deliberately changes the pinned
property** — the runners gain a health-evaluation stage with an EXPLICIT
pack binding — so that guard is INVERTED (08a/08b precedent: upgraded,
never deleted) into "enters composition ONLY with an explicit pack binding,
never omitted" (§4.5). Its sibling classes
(`TestTheExplicitNoBindingStateProtectsThem` `:133`,
`TestD18AgainstTheRealNonTidmadMetrics` `:173`,
`TestNoTaskNameBranchWasNeeded` `:255`) are unaffected and KEEP.

### 2.7 Corrections to parent prose, recorded (evidence preserved, prose corrected)

1. **Dominant fraction is 0.9973, not 1.0.** Parent §3.1 and §9 say the
   Pets collapse has "dominant class fraction = 1.0". The artifact says
   369/370 = 0.9972973 with 2 distinct classes (§2.5). The parent's point
   survives sharpened: a dominance check must catch a NEAR-constant
   deliverable, not only an exactly-constant one — which is why the check
   thresholds on a fraction rather than testing `distinct == 1`.
2. **Evidence-directory citations.** Parent §3.4 cites
   `d14_pets_gate2_20260818b/`; the D14 ledger cites `…20260818/`. The CSVs
   in both are byte-identical (one sha). The DAVIS npz lives in
   `…20260818c/` while the D14 ledger cites `…818b/` (which preserves the
   evidence JSON, not the npz); the fresh C5/Gate-2 run supplies the live
   npz regardless.

### 2.8 Runner-owning test surface — audited: NONE exists (amendment 11)

The only test in the repository referencing either runner is the 08b
cross-task guardrail (§2.6); `tests/unit/scripts/` owns chain/campaign
tooling, not these two harnesses. **Amendment 11's fallback therefore
applies and is recorded as the design's position**: the NEW shared-stage
tests introduced at C5 OWN the runner-facing evidence contract directly
(explicit binding threaded; additive evidence block shape; every selected
gate evaluated), and C6's terminal deterministic validation includes them
alongside health + guardrails + examples. No unrelated giant suite is run
in their name.

### 2.9 The one-time DAVIS measurement (amendment 6 — executed at rev 2)

Measured ONCE, before freeze, with the final standard-view semantics:
sorted clip keys → per-clip `ravel()` → one concatenated 1-D array in the
artifact's NATIVE float32 (concatenation does not change dtype), with the
population statistic (ddof 0) computed under FLOAT64 ACCUMULATION — the
estimator the check owns (§3.5a). Verified at freeze:
`np.std(native_float32_stream, dtype=np.float64, ddof=0)` reproduces the
value below EXACTLY equal:

```text
artifact   /home/klz/Data/SIDEREIS_DATA/d14_davis_gate2_20260818c/
             predictions_davis_reference_predictor_d14d_davis_gate2_001.npz
sha256     ee52a7109798a1c4c608e7824e623604e2986dab8d499b75a4794d443e0fa010
clips      15 × float32 [3,4,128,224]        n_samples = 5 160 960
all finite yes        range [-0.016510800, 1.024050832]      mean 0.483544476
population dispersion = 0.2156402715035823
```

**Frozen threshold: `min_dispersion = 0.04`.** Rationale, stated before any
implementation exists: the one measured healthy artifact sits **≈5.4×**
above the floor (0.2156/0.04), the near-collapse synthetic control
(constant plus a tiny perturbation, dispersion ≈ 0–10⁻³) fails it by
orders of magnitude, and the value is a round safety floor in the
deliverable's native units — the same provenance style as TIDMAD's
`min_std_mv = 1.0` (≈7× below healthy ≈7.35, ≈5× above worst collapse).
Honest caveat, carried into the provenance comment: exactly ONE healthy
real artifact exists, so this is a floor against near-constancy, not a
calibrated healthy-population statistic. **No further measurement, sweep or
tuning is performed** — the two acceptance controls are the synthetic
near-collapse FAIL and the preserved-artifact PASS at the recorded margin.

### 2.10 Numerical-carrier convention audit (amendment 2)

NumPy is the repository's established dense carrier: the DAVIS codec
returns `{clip_key: np.ndarray}` (`davis_data_path.py:332-339`, and
`truth_windows` `:342`), and the scoring subsystem's array surfaces are
`np.ndarray` throughout (`scoring_utils.py:109,188,195-196`). The 08b
transport already admits it: `HealthView.model_config` sets
`arbitrary_types_allowed=True` (`_view_provider.py:56`) with an `Any`
payload the engine never inspects. **No competing convention exists**, so
§3.1 freezes a NumPy-backed carrier; `tuple[float, ...]` (rev 1's sketch)
is rejected as public-ABI debt — a dense DAVIS view must never require
5.16 M Python float objects.

### 2.11 The upgraded dispersion check's facts requirement (amendment 3)

`SampleDispersionFloorCheck.run()` (`sample_dispersion_floor.py:63-114`)
reads `min_dispersion` and the samples — **it never reads
`encoding_family`**; the `FactRequirement(axis="encoding_family",
equals="continuous_float")` in its declaration (`:57`) exists only because
the 08a fixture needed an applicability axis before views existed
(the file's own docstring says so). Under the biconditional discipline
(declare only what you consume), the upgraded check **drops that
requirement**: binding the `continuous_samples` capability IS the semantic
statement that a continuous view exists. DAVIS still declares
`encoding_family=continuous_float` in its facts — that declaration's job is
to make the TIDMAD-specific checks honestly INAPPLICABLE, not to gate the
generic check.

### 2.12 Artifact-decoding ownership (amendment 8 — audited disposition)

Reuse of the existing `TaskDataPath` readers was audited and is **not
architecturally available to the providers**: `read_evaluation_payload` is
request-shaped (`EvaluationReadRequest(deliverable_dir, exp_id, run_name,
model_type)`), the provider holds only a PATH (via ctx, §3.5), and the
deliverable filename grammar
`predictions_{model_type}_{run_name}_{exp_id}` is not invertible (both
`model_type` and `run_name` contain underscores — e.g.
`pets_reference_cnn`, `d14p`). Refactoring the D14 seam modules to expose
path-based decoders would put D14-owned production surface inside a health
PR — exactly the cross-PR blast radius the split exists to avoid.
**Disposition: each pack's Health provider carries its own narrow
projection of the pack's OWN format, and BOTH tasks get a mandatory
codec-parity regression** (production writer bytes → `TaskDataPath` reader
AND → provider projection must agree: Pets on header + `{id: class}`
content; DAVIS on clip-key set, shapes, dtype and values). A format change
cannot leave one reader silently accepting a different artifact than the
other.

## 3. Design (frozen)

### 3.1 The two standard capabilities — the exact payload ABI

New public module `execute_tools/health_checks/standard_views.py`
(un-prefixed deliberately: like `schemas.py`, it is vocabulary that PACK
authors import — the 08b acme fixture already established that plugins
import the package's public surface):

```text
CATEGORICAL_PREDICTIONS = "categorical_predictions"     (parent §6.3 verbatim)
CONTINUOUS_SAMPLES      = "continuous_samples"

CategoricalPredictionsPayload.symbols   1-D np.ndarray, integer dtype
                                        (dtype.kind in {"i","u"})
ContinuousSamplesPayload.samples        1-D np.ndarray, floating dtype
                                        (dtype.kind == "f")
```

Frozen ABI properties (amendment 2, each an executable C1 criterion):

* **NumPy-backed, never dense Python objects.** A 5.16 M-sample DAVIS view
  is one array, not five million floats. Both payload models are frozen
  pydantic models with `arbitrary_types_allowed` (the `HealthView`
  precedent, `_view_provider.py:56`).
* **1-D at the standard-view boundary.** The provider owns the projection
  from its artifact's geometry to the stream; a non-1-D array is rejected
  at construction.
* **Strictly typed, no coercion.** dtype kinds are checked, not converted:
  bool (`"b"`), strings (`"U"/"S"`), objects (`"O"`) and — for the
  continuous payload — integers are REJECTED with the offending dtype
  named. A Python list/tuple is rejected (it is not an `np.ndarray`);
  providers construct arrays explicitly.
* **Consumer must not mutate.** The payload stores a READ-ONLY VIEW
  (`writeable=False`); a check attempting in-place mutation raises. No-copy
  is the SEMANTIC contract, asserted as
  `np.shares_memory(stored_view, provider_array) is True` — never as exact
  `.base` identity, which NumPy does not guarantee for an input that is
  itself already a view. Construction must not change the provider array's
  own writeability state or contents (a writable input stays writable; a
  read-only input stays read-only — both cases tested). Checks may compute
  through NumPy freely (reductions allocate their own results).
* **Runtime-only.** The payload is not required to be JSON/persistence
  serializable; nothing persists it (verdicts and metrics persist, views do
  not).
* **Engine-opaque.** No engine module (`runner.py`, `_view_provider.py`,
  `_plugin_binding.py`) references the keys or the payload types — the
  contract binds provider↔check only; standard vs plugin-local differs
  ONLY in who ships the payload model and the consuming checks. Growth of
  the STANDARD set still requires a forcing task (parent §13); plugin-local
  keys remain free.

Payload models validate SHAPE/TYPE only. Whether values are *healthy*
(finite, in-range) is check arithmetic — §3.2a fixes which verdict each
failure class carries.

### 3.2 The generic collapse family — three checks, mechanisms from parent §3.2

Extracted mechanisms, NOT TIDMAD rewrites (§3.6):

| check (registered name) | consumes | threshold (task-owned) | arithmetic | on the real artifacts |
|---|---|---|---|---|
| `categorical_distinct_symbols` | `categorical_predictions`, `requires_view=True` | `min_distinct_symbols` | distinct symbol count; `occupancy = distinct / symbol_cardinality` recorded as a metric (the injected cardinality provably enters the arithmetic) | Pets collapse: distinct = 2 → FAILED at floor 5; occupancy = 2/37 |
| `categorical_dominant_fraction` | `categorical_predictions`, `requires_view=True` | `max_dominant_fraction` | max symbol count / n | Pets collapse: 369/370 = 0.9972973 → FAILED at ceiling 0.95 |
| `sample_dispersion_floor` (UPGRADED in place) | `continuous_samples`, `requires_view=True` | `min_dispersion` (name unchanged) | population-std floor (existing hand-computed arithmetic kept verbatim) | DAVIS preserved artifact: 0.2156402715… → PASSED at floor 0.04 |

Shared properties, each a §4.2 acceptance criterion: fail closed on empty
evidence (ERROR); integrity guards per §3.2a; no metric consumption
(`denoising_score` / `file_vector` / `.scalar` — the existing census
iterates all registered checks); **no value-scale axis** (thresholds are in
the view's native units; the value-scale biconditional set stays exactly
the four TIDMAD checks); and the categorical validity arithmetic lives in
ONE shared pure helper consumed by both categorical checks, so the two
cannot drift (mutation-proven).

### 3.2a The integrity verdict boundary (frozen — amendment 5)

```text
provider cannot read/decode the artifact
    (missing file, bad header, corrupt npz, materialize raises)   -> ERROR
payload structurally absent / EMPTY stream                        -> ERROR
payload decoded, but a continuous value is non-finite             -> FAILED
payload decoded, but a categorical symbol lies outside
    [0, symbol_cardinality)                                       -> FAILED
```

The first two are inability to compute — the absence of evidence, never a
pass (and on a blocking gate they fail closed, the frozen §7 semantics).
The last two are OBSERVABLE deliverable pathologies: the artifact was read
and it is wrong, which is exactly the statement Health exists to make.
This is the parent §3.2/§4 "values finite/valid — block-capable generic
baseline", folded into the consuming checks; the opaque engine gains no
integrity validation of any kind.

### 3.3 Cardinality reaches the categorical checks by declaration (Q-08c-1 = A, frozen details)

* `TaskHealthFacts.symbol_cardinality` is the ONE authority. A categorical
  check that needs it declares `FactRequirement(axis="symbol_cardinality")`;
  composition injects check parameter `symbol_cardinality` into exactly the
  checks declaring that axis. A task declaring no cardinality →
  those checks are honestly `INAPPLICABLE` (axis named).
* **It is NOT a threshold** — it never appears in
  `threshold_parameter_names` (the 08a `peek_samples` lesson).
* **Authored collision fails closed.** A roster entry hand-authoring ANY
  injected key (`symbol_cardinality`, and equally the value-scale keys
  `value_scale_units_per_sample` / `value_scale_unit`) in its `parameters`
  is a deterministic `HealthCompositionError` naming the key — never a
  silent overwrite in either direction. (Today `compose_gate`'s update
  order `_composition.py:226-230` would silently overwrite an authored
  value; the refusal replaces that hazard. TIDMAD's shipped task config
  authors none of these keys — asserted, so its behaviour cannot move.)
* **No blanket generalization.** `_composition` gains an explicit frozen
  table of injectable axes — `value_scale_unit → (unit, factor)` (landed,
  08b) and `symbol_cardinality → symbol_cardinality` (this PR). An axis
  without a frozen injection rule injects nothing; "all FACT_AXES become
  parameters" is census-refused.

### 3.4 The Pets and DAVIS families (reference packs, the EXTERNAL interface — thresholds FROZEN)

Both bind through **state C** — an explicit task-health-config path — and
config-named pack plugins: exactly the route an external user takes
("reference packs, never a privileged path"). Layout (Q-08c-3 = A):

```text
examples/oxford_iiit_pet/
  declared/task_health.yaml     facts: encoding_family=categorical_labels,
                                       symbol_cardinality=37
                                plugins: [../plugins/pets_health_views.py]
                                providers: [pets.prediction_views]
                                roster (both blocking):
                                  pets_distinct_symbols_blocking
                                      min_distinct_symbols = 5       (FROZEN)
                                  pets_dominant_fraction_blocking
                                      max_dominant_fraction = 0.95   (FROZEN)
  plugins/pets_health_views.py  provider exposing categorical_predictions
                                from the pack's CSV at the ctx-supplied path
  expected/d14_gate2_collapse_predictions.csv
                                the fixture-of-record — the REAL preserved
                                CSV, committed byte-identical
                                (sha cc8470267fbf…f752c, 6 812 bytes)

examples/davis_future_prediction/
  declared/task_health.yaml     facts: encoding_family=continuous_float
                                plugins: [../plugins/davis_health_views.py]
                                providers: [davis.sample_views]
                                roster (blocking):
                                  davis_dispersion_blocking
                                      min_dispersion = 0.04           (FROZEN, §2.9)
  plugins/davis_health_views.py provider exposing continuous_samples from
                                the npz — the FULL decoded view (§3.5)
```

Threshold provenance (comments carried in the configs, verbatim intent):
Pets floors must FAIL the real collapse (distinct 2 < 5; dominance
0.9972973 > 0.95) and PASS any healthy 37-class spread — they are safety
floors chosen against the §2.5 evidence, not tuned results. DAVIS's floor
carries the §2.9 measurement, margin and single-artifact caveat. The four
Pets evidence values (n=370, distinct=2, occupancy=2/37,
dominant=369/370) and the DAVIS dispersion are HARDCODED in the evidence
tests. **No threshold campaign, sweep, or "try until green" exists in this
PR; if implementation shows a frozen floor cannot honestly hold, STOP and
return the evidence rather than adjusting the number.**

The upgraded `sample_dispersion_floor` declares NO facts (§2.11); the
D14 zero-production-dependency invariant is untouched (runners pass pack
paths as DATA — established D14 practice); the pack-governance guards
continue to pass (`.py` only under `plugins/`; the health YAML's top-level
keys are not the forbidden ones).

### 3.5 The bounded real-artifact evaluation path (runner-pattern, the live half)

The provider learns WHERE the deliverable is from the context: the
harness/test builds `HealthCheckContext(denoised_paths={0: <deliverable>})`
and the pack provider reads `ctx.get_denoised_path(0)` — the existing
generic "produced artifact" slot; no schema change; its docstring gains a
sentence saying so.

**DAVIS evaluates the FULL decoded view** (amendment 7): sorted clip keys →
`ravel()` → one concatenated 1-D array, **preserving the artifact's native
floating dtype** (float32 for the real npz) — the §2.9 semantics exactly.
No prefix cap, no sampling: 17.9 MB is not too large for a bounded
evaluation, and a prefix would make dispersion depend on flatten ordering.

**Precision ownership (§3.5a, final-approval correction 3).** The PROVIDER
owns the artifact projection and hands over the native-dtype sample stream;
the CHECK owns the numerical estimator and computes the population
dispersion with float64 accumulation (`np.std(samples, dtype=np.float64,
ddof=0)` — the NumPy equivalent of the estimator the current check already
owns, whose `math.fsum` accumulation is float64). Ordinary NumPy
concatenation of float32 arrays does NOT upcast, and no contract relies on
it doing so. This division reproduces the frozen §2.9 value exactly
(verified at freeze, bit-equal). If
implementation evidence ever suggests a cap is needed, that is a
frozen-semantics change → STOP; any future sampling policy would have to be
explicit task-owned config, deterministic and coverage-preserving — it is
NOT designed here.

Runner stage (Q-08c-4 = A): both D14 runners gain the SAME stage through one
shared helper (`scripts/_gate2_health_stage.py`), inserted after the metric
stage:

```text
materialize_effective_config(source=None,            # policy-only framework file
                             files=None, workspace,
                             task_health_binding=<pack task_health.yaml>)   # EXPLICIT, state C
→ get_gates_for_position(1, config_path=<effective>)
→ for EVERY selected gate:  evaluate_gate(gate_id, ctx, config_path=<effective>)
→ append to gate_evidence.json, ADDITIVE nested block:
     health:
       task_health_binding        (the explicit pack config path)
       effective_config_sha256    (the pinned body sha)
       resolved_plugins           (configured_ref + member + content_sha256)
       gates                      (ordered: gate id, check ids, check_verdicts,
                                   resolved action, threshold/config values
                                   needed to interpret the result,
                                   decisive metrics)
```

Frozen semantics of the stage (amendment 9):

* **Additive evidence.** The existing D14 `gate_evidence.json` fields
  (`training` / `inference` / `metric` / …) are not renamed, removed or
  reinterpreted; `health:` is a new nested block following the file's
  existing block convention.
* **Every selected gate is evaluated and persisted**, even when an earlier
  blocking gate returns `invalidate_round`. The stage collects Health
  EVIDENCE; it is not the tuner's round-control state machine — on a
  collapsed Pets deliverable, BOTH the dominant-fraction and the
  distinct-symbol evidence must be present.
* **The binding is NEVER omitted** — an omitted binding now composes TIDMAD
  (state A), the exact cross-task hazard the 08b audit pinned; the inverted
  guardrail (§4.5) makes that executable.
* **A FAILED verdict can be a Gate-2 PASS**: the Gate asks whether Health
  classified the real artifact CORRECTLY, not whether the artifact was
  healthy.

### 3.6 What TIDMAD does NOT do in 08c (parity, not unification — amendment 12)

TIDMAD's six checks, roster, thresholds, ids, actions, firing point and
verdicts are untouched. **No new TIDMAD Gate is run**: its real-lifecycle
evidence is 08b's Gate-2 PASS at `bf6e9e19`, and 08c's only TIDMAD-adjacent
runtime surface is the C2 injection refactor. The deterministic owners
re-proven at EVERY semantic commit instead: the 27-case verdict manifest
byte-identical; the composed state-A executed-semantics golden
byte-identical; value-scale injection behaviour unchanged; state-A roster /
order / verdicts / persisted values unchanged. **If any of these parity
proofs moves, or TIDMAD executable semantics change outside the frozen C2
refactor: STOP and re-disposition a real TIDMAD Gate** — otherwise no
duplicate expensive run. The parent's *optional* TIDMAD categorical view is
deliberately not elected.

**The ordering-behaviour rule, adapted (08b precedent):** 08c's analogue of
a visited-sequence claim is the composed roster, the executed check
sequence, the verdicts and the persisted values — every parity criterion is
written against those, never against composed config objects.

### 3.7 The final Step-08 validation stack (amendment 15 — the completion plan)

```text
TIDMAD       08b real Gate-2 PASS (bf6e9e19)
             + 08c deterministic parity at every commit (§3.6)

Pets         committed REAL D14 collapse fixture-of-record
             + healthy counterfactual
             + full state-C unit chain (compose → load → resolve → evaluate)
             + fresh real train → infer → metric → Health   (Gate 2)

DAVIS        hand-computed synthetic FAILED/PASSED pair
             + preserved real-npz deterministic evidence (skip-guarded,
               reproducing the §2.9 dispersion exactly)
             + fresh real train → infer → metric → Health   (Gate 2)

Cross-task   three-task composition rung
             + health-core structural census (parent §13, strengthened)
             + 08b external fourth-task proof remains green
             + zero task-name branches / no central external registration

Repository   ONE canonical formal PR CI on the exact final PR HEAD
             (no local full suite; no manual duplicate CI)
```

## 4. Commit decomposition

### 4.0 Standing rules (amendment 1 — autonomy restored)

* Each commit's first item is a bounded read of the exact functions it
  edits, at the implementation head. Ambiguity or larger scope than the
  design assumes → **STOP and ask before changing the plan**.
* `[ ]` = not done; `[x]` only with recorded evidence. **Every box below is
  `[ ]`.** Pytest verdicts from complete log files, never a wrapper's exit
  status.
* **Commits are AUTONOMOUS** — no per-commit operator checkpoint. The
  permanent Implementation Working Rules govern: inspect → implement →
  targeted validation → ledger → semantic commit → continue.
* **The two bounded Gate-2 runs are AUTONOMOUS** once their exact
  specifications are written into §10 (§7). Push / PR / routine CI repair
  are autonomous. Stop only for a genuine material semantic / architecture
  / budget contradiction, or at READY FOR OPERATOR REVIEW.
* Planner/prompt exposure and production-default changes are OUTSIDE these
  commits; any such delta is a material deviation requiring operator
  review.
* Threshold values are FROZEN in §3.4/§2.9 — no campaign, no sweep; a floor
  that cannot honestly hold is a STOP, not an adjustment.
* TIDMAD parity (§3.6's four deterministic owners) is re-verified at every
  commit; a moved byte is a STOP.
* Out of scope for all commits: Pets/DAVIS tuner integration, TIDMAD
  categorical-view re-binding, new `FACT_AXES`, new injectable axes beyond
  §3.3's table, Step 09, Step 10/12.

---

### 4.1 C1 — the standard view capabilities (the exact NumPy payload ABI)

**Goal.** `categorical_predictions` and `continuous_samples` exist as
framework-shipped, typed payload vocabulary with the §3.1 ABI — reviewable
separately from check arithmetic; pack/provider authors get one import for
the contract. This commit and no other defines the two key strings.

**Scope.** NEW `execute_tools/health_checks/standard_views.py` (two key
constants + two payload models); `__init__.py` exports. Deliberately
UNREACHABLE from production (inert; grep-guard with the 08a/08b
anti-vacuity defences, INVERTED in C2). Must not change: any check,
`runner.py`, `_view_provider.py`, `_plugin_binding.py`, `_composition.py`,
any YAML, the engine's opacity. Depends on: nothing.

**Implementation plan.**
- [ ] Re-read `_view_provider.py` (`arbitrary_types_allowed` at `:56`) and
      the 08b acme fixture's import surface at the head.
- [ ] Define the two key constants with the parent §6.3 spellings, declared
      exactly once.
- [ ] Define the payload models per §3.1: 1-D `np.ndarray`; dtype-kind
      checks (categorical `{"i","u"}`, continuous `"f"`); reject bool /
      string / object dtypes and non-array inputs with the offender named;
      store a read-only no-copy VIEW (`writeable=False`).
- [ ] Export via `__init__.py`; add the inertness grep-guard (root
      assertion, exit-code assertion, positive probe, `--untracked`).

**Validation plan.**
- [ ] Unit: valid construction (int8/int64 symbols; float32/float64
      samples); rejection of each wrong class — bool array, string array,
      object array, int array as continuous, 2-D array, Python list/tuple.
- [ ] Unit: read-only + no-copy semantics — in-place mutation through the
      stored view raises; `np.shares_memory(stored_view, provider_array)`
      is True (no copy — deliberately NOT `.base` identity); construction
      leaves the provider array's writeability state and contents unchanged,
      tested for BOTH a writable input (stays writable) and a read-only
      input (stays read-only).
- [ ] Unit: the key strings equal the parent §6.3 spellings, hardcoded.
- [ ] Census: no engine module references the keys or payload types.
- [ ] Backward-compat: health package green; 27-case manifest
      byte-identical; inertness guard green and mutation-proven.

**Acceptance criteria.**
- [ ] The two capability-key strings exist in exactly ONE production module
      (grep census counts definitions).
- [ ] Every §3.1 ABI bullet has a failing test: wrong dtype-kind rejected
      with the dtype named; non-1-D rejected; mutation raises; no copy via
      `shares_memory`; provider writeability preserved in both directions.
- [ ] Engine opacity census green; inertness guard green and
      mutation-proven; manifest byte-identical.

**Failure and edge cases.** Empty arrays are ACCEPTED by the payload
(emptiness is check-level ERROR per §3.2a — a provider must be able to say
honestly "I read the artifact and it was empty"). Non-finite floats are
ACCEPTED by the payload and condemned by the check (§3.2a). NaN cannot hide
in an integer categorical payload by construction.

**Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/execute_tools/health_checks/ -q > /tmp/08c_c1.log 2>&1`
      Evidence: _(pending)_
- [ ] `ruff check` + `ruff format --check`. Evidence: _(pending)_
- [ ] `pyright` — CI-owned; recorded, never claimed locally.

**Commit boundary.** Vocabulary + tests only; no consumer; no check
changes; independently reviewable as "is this the right standard-view ABI?".

---

### 4.2 C2 — the generic collapse checks (hand-computed) + cardinality injection

**Goal.** The three generic checks exist with hand-computed arithmetic and
consume the standard views through the real 08b transport
(`requires_view=True`); the categorical checks receive `symbol_cardinality`
by declaration with the §3.3 collision refusal; the §3.2a verdict boundary
is executable. The parent §10 "generic categorical/continuous checks on
views | UNIT (hand-computed)" row.

**Scope.** NEW `categorical_distinct_symbols.py`,
`categorical_dominant_fraction.py` (+ ONE shared pure validity helper for
the categorical family); UPGRADE `sample_dispersion_floor.py` in place
(consume `continuous_samples` via `view=`, `requires_view=True`, retire the
config-borne `samples` scaffolding, **drop the `encoding_family` fact
requirement per §2.11**); `_composition.py` (the frozen injectable-axes
table + the authored-collision refusal covering `symbol_cardinality` AND
the value-scale keys); `__init__._bootstrap_registry` (+2). Must not
change: the six TIDMAD checks, `runner.py` semantics, any threshold value,
any YAML. Depends on C1 (inertness guard INVERTED here).

**Implementation plan.**
- [ ] Re-read `sample_dispersion_floor.py`, `test_step08_44_rungs.py` and
      `_composition.py:186-292` at the head; record the exact rung-test
      surfaces the upgrade touches and the injection/refusal insertion
      points.
- [ ] Implement the two categorical checks per §3.2 (declarations exact:
      `consumes_view=CATEGORICAL_PREDICTIONS`, `requires_view=True`,
      `FactRequirement(axis="symbol_cardinality")`,
      `threshold_parameter_names` = exactly the one boundary key each);
      NumPy arithmetic over the read-only view (`np.unique` /
      `np.bincount`-class reductions — no mutation).
- [ ] Implement the shared categorical validity helper (§3.2a: out-of-range
      symbol → FAILED naming the symbol and the range) consumed by BOTH
      categorical checks.
- [ ] Upgrade `sample_dispersion_floor`: view consumption; keep name,
      threshold name, ERROR-on-empty and the hand-computed arithmetic; the
      estimator becomes `np.std(samples, dtype=np.float64, ddof=0)` (§3.5a
      — float64 accumulation, the NumPy equivalent of the existing
      `math.fsum` form); drop the facts requirement; add the non-finite →
      FAILED guard.
- [ ] Implement the frozen injectable-axes table + authored-collision
      refusal in `_composition`; value-scale behaviour otherwise provably
      unchanged.
- [ ] Register the two new checks in the bootstrap; update
      `BUILTIN_CHECK_NAMES` to 9 (§5).

**Validation plan.**
- [ ] Unit, hand-computed anchors (expectations hardcoded): the four §2.5
      values — distinct=2 → FAILED at floor 5; occupancy = 2/37 =
      0.05405405405405406 recorded as a metric; dominant 369/370 =
      0.9972973 → FAILED at ceiling 0.95; a healthy spread PASSES both;
      dispersion √5 series kept verbatim from the existing suite.
- [ ] §3.2a boundary: empty view → ERROR; out-of-range symbol → FAILED
      (via the shared helper — mutation-prove the helper is load-bearing
      for BOTH checks); NaN sample → FAILED naming it; provider raise →
      ERROR (existing 08b guard, re-asserted).
- [ ] Injection (amendment 4's four required tests): positive injection;
      no-declaration ⇒ no injection; authored-collision ⇒ deterministic
      refusal naming the key (for `symbol_cardinality` AND a value-scale
      key); value-scale behaviour unchanged (its tests + manifest).
- [ ] Ordering/transport: a task declaring no cardinality → categorical
      checks INAPPLICABLE (axis named) with ZERO materialize calls (the
      08b spy shape); a view-consuming check receives the keyword-only
      `view`.
- [ ] Backward-compat/default-parity: §3.6's four deterministic owners
      byte-identical; `test_check_declarations` biconditionals green over
      the grown registry (new checks declare NO value-scale axis, NO
      `per_sample_evidence`; the upgraded dispersion check declares NO
      facts); new checks configured in NO shipped config (extend the
      `:150` pattern); TIDMAD's shipped task config authors NO injected
      key (the §3.3 census).

**Acceptance criteria.**
- [ ] Each check's declaration lists exactly its one threshold key;
      `symbol_cardinality` appears in NO `threshold_parameter_names`.
- [ ] The real-collapse anchors pass with all four §2.5 values hardcoded —
      occupancy included, proving the injected cardinality enters the
      arithmetic.
- [ ] `sample_dispersion_floor`'s config-borne `samples` path and its
      `encoding_family` requirement are GONE (grep + declaration census);
      the 8.4-C property survives through the view path (§5 disposition,
      mutation-proven: reverting the upgrade fails the upgraded rung).
- [ ] The authored-collision refusal is deterministic and named; the
      silent-overwrite hazard at `_composition.py:226-230` is gone
      (mutation: restoring silent overwrite turns the collision tests RED).
- [ ] Registry census: bootstrap registers exactly 9; value-scale
      biconditional set still exactly the four TIDMAD checks.

**Failure and edge cases.** A roster naming a categorical check while the
task declares no cardinality: INAPPLICABLE, not an error (validly bound,
facts silent). A blocking gate's injected `aggregation: any_pass` is
ignored by single-artifact checks — harmless, asserted so the assumption is
recorded. An int8 symbols array with cardinality 256: distinct counting
must not overflow or coerce (NumPy handles it; asserted with an int8
fixture).

**Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/execute_tools/health_checks/ -q > /tmp/08c_c2.log 2>&1`
      Evidence: _(pending)_
- [ ] Manifest `--check` byte-identical; composed state-A golden
      byte-identical. Evidence: _(pending)_
- [ ] `ruff` clean; `pyright` CI-owned. Evidence: _(pending)_

**Commit boundary.** Generic family + injection only; no pack content; no
runner change; TIDMAD untouched.

---

### 4.3 C3 — the Pets family + the committed collapse fixture-of-record

**Goal.** Pets binds a real health family through the external interface,
and the framework detects the REAL D14 collapse: parent §14.B — *"the
framework can now SAY what D14 could only observe."*

**Scope.** NEW `examples/oxford_iiit_pet/declared/task_health.yaml`
(thresholds per §3.4, FROZEN); NEW
`examples/oxford_iiit_pet/plugins/pets_health_views.py`; NEW committed
fixture `examples/oxford_iiit_pet/expected/d14_gate2_collapse_predictions.csv`
(byte-identical copy, sha pinned); pack `STATUS.md`/`PROVENANCE.md` rows;
NEW test module incl. the Pets codec-parity regression (§2.12). Must not
change: any framework module, any shipped config, `pets_data_path.py`, the
runners (C5's job). Depends on C1–C2.

**Implementation plan.**
- [ ] Re-read the pack-governance guards and `_task_health_config.py`
      constraints at the head (confirm the `../plugins/…` relative ref
      resolves from `declared/`, or place the config at the pack root —
      a bounded layout decision); STOP only if the layout fights a
      governance guard.
- [ ] Author the family per §3.4 with the frozen thresholds and provenance
      comments quoting §2.5.
- [ ] Implement the provider: registers `pets.prediction_views` exposing
      `CATEGORICAL_PREDICTIONS` from the CSV at `ctx.get_denoised_path(0)`
      (header-checked projection; unreadable/bad header → raise → ERROR).
- [ ] Commit the fixture-of-record byte-identical; pin sha
      `cc8470267fbf…f752c` and size 6 812 in the test.
- [ ] Codec-parity regression (§2.12): production-writer bytes (the
      fixture) → `pets_data_path.read_evaluation_payload` AND → the
      provider projection agree on the `{image_id: class}` content.
- [ ] Evidence tests: full state-C chain on the fixture → BOTH gates
      evaluated: `categorical_dominant_fraction` FAILED with
      `dominant_fraction == 369/370`, `categorical_distinct_symbols`
      FAILED with `distinct == 2` and `occupancy == 2/37`, actions
      `invalidate_round`; counterfactual healthy CSV → both PASS.
- [ ] TIDMAD's int8 checks under Pets' DECLARED facts → `inapplicable`
      (the 8.4-B rung with a real task's declaration).

**Validation plan.**
- [ ] Unit as above; negative: broken CSV header → ERROR; missing
      deliverable path → ERROR; fail-closed pair (plugin file removed →
      `HealthPluginError`; roster naming an unregistered check →
      `HealthBindingError`).
- [ ] Census: `37` and every pack identifier appear in the PACK + its
      tests only, never in generic health core.
- [ ] Backward-compat: EXPLICIT_NONE and state-A regressions untouched;
      §3.6 parity owners byte-identical; pack-governance suite green.

**Acceptance criteria.**
- [ ] The committed fixture's sha256 equals
      `cc8470267fbf5331827c7b641ac2ce8efb834b07441a31836084d4d417ff752c`
      (asserted, so the fixture-of-record cannot silently drift).
- [ ] On that fixture, BOTH blocking gates FAIL with all four §2.5 evidence
      values persisted — the parent §12 acceptance with the corrected
      numbers.
- [ ] The healthy counterfactual passes (without it, an always-failing
      family satisfies the collapse test).
- [ ] Codec parity holds for Pets (both readers agree on the fixture).
- [ ] Every Pets identifier is absent from production source (id census,
      C7-08b pattern).

**Failure and edge cases.** CSV with unknown image ids: irrelevant to
health (the checks see symbols only) — recorded, not guarded. Symbols
outside `[0, 37)`: FAILED via the shared validity helper. A hand-edited
pack threshold: caught by nothing here BY DESIGN (thresholds are
task-owned); only the fixture EVIDENCE values are pinned.

**Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/execute_tools/health_checks/ tests/unit/examples/ -q > /tmp/08c_c3.log 2>&1`
      Evidence: _(pending)_

**Commit boundary.** Pets content only; DAVIS is C4; runners untouched.

---

### 4.4 C4 — the DAVIS family

**Goal.** A dense-continuous task binds the same machinery with no TIDMAD
or classification assumption (parent §14.C), through the identical external
interface, evaluating the FULL decoded view.

**Scope.** NEW `examples/davis_future_prediction/declared/task_health.yaml`
(`min_dispersion = 0.04`, FROZEN, §2.9 provenance); NEW
`examples/davis_future_prediction/plugins/davis_health_views.py`; pack docs
rows; NEW test module incl. the DAVIS codec-parity regression and the
skip-guarded machine-local real-npz test. Must not change: framework
modules, shipped configs, `davis_data_path.py`, runners. Depends on C1–C2
(not C3).

**Implementation plan.**
- [ ] Re-read `davis_data_path.py:310-340` at the head; record the npz
      payload shape the provider projects.
- [ ] Implement the provider: `davis.sample_views` exposing
      `CONTINUOUS_SAMPLES` as the FULL decoded view — sorted clip keys →
      `ravel()` → one concatenated 1-D array (the §2.9 semantics; **no
      cap, no sampling** — amendment 7).
- [ ] Author the family per §3.4 with the §2.9 provenance comment
      (measurement, margin, single-artifact caveat).
- [ ] Codec-parity regression (§2.12): a production-writer-produced npz
      (synthetic, written through `davis_data_path.write_deliverable`) →
      `read_evaluation_payload` AND → the provider projection agree on
      clip-key set, shapes, dtype and values.
- [ ] Evidence tests: synthetic near-constant npz → FAILED; synthetic
      varied npz (hand-computed dispersion) → PASSED; skip-guarded test
      over the preserved npz (sha `ee52a710…0a010`) → PASSED reproducing
      dispersion `0.2156402715035823` exactly (skips with the declared
      reason when the machine-local artifact is absent — never claimed as
      run when skipped).
- [ ] TIDMAD's int8 checks inapplicable under DAVIS' declared facts.

**Validation plan.**
- [ ] Unit as above; negative: corrupt/missing npz → ERROR; NaN frames →
      FAILED; unequal clip shapes → provider raises → ERROR; empty npz
      (`{}` from the reader's missing-file contract) → ERROR; fail-closed
      plugin/binding pair as C3.
- [ ] Census: DAVIS identifiers absent from production source; no new
      `FACT_AXES`; the generic dispersion check declares NO facts (§2.11).
- [ ] Backward-compat: §3.6 parity owners byte-identical; C3's Pets
      evidence untouched-green (families independent).

**Acceptance criteria.**
- [ ] Verdicts flow through the SAME engine path as Pets with zero
      task-name knowledge (id census; no framework surface touched).
- [ ] The synthetic pair is decisive (one FAILED, one PASSED, hand-computed
      expectations hardcoded).
- [ ] The skip-guarded real-npz test reproduces the §2.9 dispersion to the
      recorded value on this machine and skips honestly elsewhere.
- [ ] Codec parity holds for DAVIS (both readers agree on a
      production-written npz).

**Failure and edge cases.** The payload carries the artifact's NATIVE
float32; float64 enters only inside the check's estimator (§3.5a precision
ownership) — no contract claims concatenation upcasts. A future clip-count
change alters n but not the semantics — nothing pins 15.

**Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/execute_tools/health_checks/ tests/unit/examples/ -q > /tmp/08c_c4.log 2>&1`
      Evidence: _(pending)_

**Commit boundary.** DAVIS content only.

---

### 4.5 C5 — the runner-pattern evaluation stage + guardrail inversion

**Goal.** The bounded real-artifact evaluation path exists (parent "Allowed
changes" verbatim): both D14 runners evaluate their pack's health family on
the fresh real deliverable with an EXPLICIT state-C binding, persisting the
§3.5 additive `health:` evidence block. **The final production-surface
commit — the Gate-2 head.**

**Scope.** `scripts/run_pets_gate2.py`, `scripts/run_davis_gate2.py`, NEW
shared helper `scripts/_gate2_health_stage.py`; UPGRADE of
`tests/unit/guardrails/test_step08b_cross_task_compatibility.py::`
`TestNeitherExistingTaskCanReachTheTidmadFallback` (§2.6); NEW shared-stage
test module — which, per the §2.8 audit, is the FIRST owner of the runner
evidence contract. Must not change: the runners' training/inference/metric
stages or their existing evidence fields, any framework module, any pack
family content. Depends on C3–C4.

**Implementation plan.**
- [ ] Re-read both runners end-to-end at the head; record the exact
      insertion point after the metric stage and the existing evidence-JSON
      block convention.
- [ ] Implement the shared stage per §3.5: explicit binding; EVERY selected
      gate evaluated (no short-circuit across gates — this is evidence
      collection); the additive `health:` block with binding path,
      effective sha, resolved plugin identities, ordered gate entries.
- [ ] Wire both runners through the ONE helper; define and print each
      runner's health-stage PASS semantics (stage ran; family evaluated;
      verdicts persisted; a FAILED verdict on a genuinely collapsed
      deliverable is the stage WORKING).
- [ ] INVERT the guardrail: from "never enters Health composition" to
      "enters composition ONLY through the shared stage with an explicit
      pack binding; an OMITTED binding is census-refused" — keep the
      anti-vacuity probe; KEEP the sibling classes unchanged.
- [ ] Update both runners' docstrings (CLI/docs sync rule) with the new
      stage and evidence block.

**Validation plan.**
- [ ] Shared-stage owner tests (tmp deliverable + tmp pack config):
      explicit binding threaded; effective sha in the block equals the
      artifact's pin; EVERY selected gate persisted even when the first
      blocking gate fails (a two-gate fixture where gate 1 fails — gate 2's
      evidence MUST be present); existing D14 evidence keys untouched
      (additivity asserted against a golden of the pre-C5 key set).
- [ ] Mutation: omitting the binding in the stage → the inverted guardrail
      RED; short-circuiting after the first failed gate → the
      every-gate-persisted test RED.
- [ ] NO real run in this commit's validation — the live half is Gate 2
      (§7), autonomous at this head once the specs are written.

**Acceptance criteria.**
- [ ] Both runners share ONE stage implementation (census: no second
      composition/evaluation code path in `scripts/`).
- [ ] The inverted guardrail is RED under the omitted-binding mutation and
      green at the commit head.
- [ ] The `health:` block is ADDITIVE (pre-C5 key set unchanged) and
      carries every §3.5 field.
- [ ] On a collapsed fixture deliverable, BOTH Pets gates' evidence is
      present in one evidence file.

**Failure and edge cases.** Pack config path missing → the stage fails
LOUDLY before evaluation (a runner that silently dropped its health stage
would pass off D14-era evidence as 08c evidence). Deliverable absent →
provider ERROR path (asserted in C3/C4). Evidence file pre-existing from a
prior run in the same workspace: the stage writes into THIS run's evidence
dict before the single JSON dump — no partial-file merge logic.

**Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/guardrails/ tests/unit/execute_tools/health_checks/ <new shared-stage module> -q > /tmp/08c_c5.log 2>&1`
      Evidence: _(pending)_

**Commit boundary.** Runner stage + guardrail inversion + stage owner
tests. **Gate 2 (§7) runs at THIS head, autonomously, after its §10 specs
are written.**

---

### 4.6 C6 — milestone census + three-task evidence + docs (test/docs ONLY)

**Goal.** Parent §13's health-core census (including the strengthened
structural items) becomes executable with the CORRECTED registration claim;
the three-task milestone claim is one test; documentation synchronized.
**No production behaviour change** — the Gate-2 evidence at the C5 head
must still cover the final state.

**Scope.** NEW health-core census module under `tests/unit/guardrails/`
(extending the `test_task_data_path_census.py` AST pattern); a three-task
composition rung; docs: `docs/design/pluggable_health_checks.md` (standard
capabilities + generic family section), both pack `STATUS.md` 08c rows,
this document's ledger incl. the §14 A–H table. Roadmap/parent/CLAUDE.md
status = post-merge bookkeeping, not PR content. Depends on C1–C5.

**Implementation plan.**
- [ ] Census over the enumerated GENERIC health modules (the TIDMAD-family
      check modules excluded BY LISTED NAME as task-owned): zero
      `tidmad|pet|davis` comparisons; zero `examples` imports; no `37`; no
      int8/channel/mV literals; no closed view-kind enum/dispatch; no
      metric-scalar reads; no central task roster/mapping; **the corrected
      registration claim (amendment 10)**: adding an EXTERNAL
      task/package/provider/custom check requires no central
      registry/import/config edit — asserted structurally as: the central
      bootstrap enumerates ONLY framework-shipped built-ins, and no Pets
      id, DAVIS id or synthetic external-task id appears in the bootstrap,
      any central mapping, or the framework policy files.
- [ ] Three-task rung: compose TIDMAD (state A), Pets (state C), DAVIS
      (state C) in one module — `reset_run_scope` between, per the 08b
      run-scope semantics — asserting disjoint rosters, generic checks
      firing for B/C, int8 checks inapplicable under B/C facts, state A
      byte-stable.
- [ ] Map parent §14 A–H to evidence in this document's ledger.
- [ ] Docs sync last, quoting each documented behaviour against merged
      source (node/skill doc-sync rule).

**Validation plan.**
- [ ] The census is anti-vacuous (planted-offender probes, the C7-08b
      pattern) — including a probe that a fixture id planted in the
      bootstrap IS detected.
- [ ] Terminal deterministic validation (amendment 11): health package +
      `tests/unit/guardrails/` + `tests/unit/examples/` + the C5
      shared-stage owner module.
- [ ] `git diff` of this commit shows tests/docs only (recorded in the
      ledger, so Gate-2 coverage of the final executable state is a fact,
      not an assumption).

**Acceptance criteria.**
- [ ] Every §13 strengthened item is one executable assertion with a
      planted-offender probe; the registration claim reads exactly as
      amendment 10 froze it.
- [ ] The three-task rung passes; the §14 A–H table in the ledger cites
      per-item evidence.
- [ ] Zero production-source bytes changed by this commit.

**Failure and edge cases.** A census pattern that would fire on the
TIDMAD-owned check modules: excluded by an explicit LISTED set with a
comment, so the census cannot silently widen or narrow.

**Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/execute_tools/health_checks/ tests/unit/guardrails/ tests/unit/examples/ <shared-stage module> -q > /tmp/08c_c6.log 2>&1`
      Evidence: _(pending)_

**Commit boundary.** Census + rung + docs; no Gate; no production change.

## 5. Test disposition (named in advance, executed at the owning commit)

| existing surface | disposition | commit |
|---|---|---|
| `test_step08_44_rungs.py` dispersion arithmetic + rungs B/C | **UPGRADE** — samples arrive through a real provider/view instead of check config; every hand-computed expectation and the 8.4-C claim preserved via the real transport; the rung-B "int8 inapplicable" half keeps its fixture facts; mutation: reverting the check upgrade fails the upgraded rung | C2 |
| `sample_dispersion_floor` `encoding_family` requirement | **REMOVE** (biconditional, §2.11) — the applicability-contrast property the 08a fixture used it for is owned by the rung-B fixtures and the real B/C families, not by the generic check's declaration | C2 |
| `test_plugin_binding.py::BUILTIN_CHECK_NAMES` (hardcoded 7-tuple) | **UPGRADE** to 9 — deliberately hardcoded (read-back would compare the registry to itself) | C2 |
| `test_check_declarations.py` biconditionals; `test_per_sample_evidence.py` census; metric-scalar census | **KEEP** — iterate all registered checks; new checks covered automatically | C2 |
| rung `:150` "registered but configured nowhere in production" | **EXTEND** to the two new checks | C2 |
| `test_step08b_cross_task_compatibility.py::TestNeitherExistingTaskCanReachTheTidmadFallback` | **INVERT** (never delete): runners enter composition ONLY with an explicit pack binding; omitted-binding shape census-refused; anti-vacuity probe kept | C5 |
| its sibling classes (EXPLICIT_NONE, D18 real metrics, no-task-name-branch) | **KEEP** unchanged | — |
| runner-owning tests | **NONE EXIST (§2.8)** — the C5 shared-stage module becomes the first owner of the runner evidence contract | C5 |
| 08b out-of-tree proof; 27-case manifest; composed goldens; pack-governance guards | **KEEP** — byte-identical / green at every commit | all |

## 6. Evidence economy

Targeted per-commit suites (health package; + `tests/unit/examples/` at
C3/C4; + `tests/unit/guardrails/` and the shared-stage owner at C5/C6). No
local full suite; no manual CI dispatch; ONE canonical exact-head CI on the
formal PR. Gate 2 is not duplicate CI — it owns the real-artifact lifecycle
no fixture can. TIDMAD gets NO new Gate (§3.6): its four deterministic
parity owners run at every commit, and a moved byte is a STOP that
re-dispositions a real TIDMAD Gate rather than being absorbed.

## 7. Gates

**Gate 1 — NOT REQUIRED.** No prompt/PB delta is elected; health stays
counts + named absence + stable ids in every LLM-facing surface. Any
accidental delta is a MATERIAL deviation → stop for operator
re-disposition.

**Gate 2 — TWO bounded real-artifact evaluations at the C5 final executable
head, AUTONOMOUS once each spec is written into §10** (amendment 13; no
pre-Gate operator checkpoint). Classification is PASS/FAIL/INCONCLUSIVE
from persisted semantic evidence, never exit code. Each spec must record:
exact executable HEAD; exact command; the pack binding path; dataset/
training bounds; expected wall time; evidence destination; and the
PASS/FAIL/INCONCLUSIVE semantics below.

* **Pets** (`run_pets_gate2.py`, D14 bounds: 370/74/370 images, 2 epochs).
  PASS evidence: fresh train/infer/write/metric completed; explicit
  state-C binding recorded in the `health:` block; pack provider plugin
  loaded/resolved with its content digest present; the effective artifact
  generated and its sha recorded; BOTH gates evaluated with decisive
  metrics persisted; no TIDMAD fallback; no unintended
  INAPPLICABLE/ERROR. **Healthy or collapsed fresh predictions can both
  yield Gate PASS, provided the Health verdict is numerically consistent
  with the artifact** (the reference CNN's 2-epoch collapse is expected to
  recur; a FAILED dominance verdict on a collapsed fresh deliverable is
  the framework working). FAIL: a verdict numerically inconsistent with
  the fresh artifact; a TIDMAD roster in the effective artifact; an
  unintended INAPPLICABLE/ERROR. INCONCLUSIVE: the stage never ran /
  training or inference failed before it.
* **DAVIS** (`run_davis_gate2.py`, D14 bounds: 60/15/15 clips): same
  lifecycle claims; the FULL continuous view evaluated; the dispersion
  metric persisted and the verdict consistent with the frozen 0.04 floor.
* **Runtime projection (amendment 14).** The Gate includes its bounded
  training/inference: D14 measured pets train 3.52 s + infer 0.74 s and
  davis train 7.28 s + infer 0.58 s, so each run is startup-dominated —
  projected ≤ ~2 min each, bounded at ≤ 10 min each, combined expected
  ≤ ~20 min, inside the permanent ≤ ~1 h PR validation envelope. A
  materially larger projection is a STOP before launch.
* Evidence preserved under `/home/klz/Data/SIDEREIS_DATA/` beside the D14
  corpora.

**TIDMAD**: no new Gate (§3.6/amendment 12) — the §3.6 STOP rule is the
re-disposition trigger.

## 8. Open questions

**None.** All four Q-08c questions are RESOLVED by the operator ruling
(§0.1); the sixteen amendments (§0.2) are applied in this revision.

## 9. Risks

* **R-08c-1 — a frozen floor meets an artifact it cannot honestly
  classify.** The floors are frozen (§3.4/§2.9); the counterfactual pairs
  and the recorded margins are the guard. If implementation shows a floor
  cannot hold, the rule is STOP-and-return-evidence, never adjust-and-pass.
* **R-08c-2 — the guardrail inversion weakens the cross-task protection.**
  Mitigated by the omitted-binding mutation (RED required) and by keeping
  EXPLICIT_NONE's own regression untouched.
* **R-08c-3 — census scope creep or blindness.** The generic-module list is
  explicit, the TIDMAD-owned exclusions are LISTED, and every pattern
  carries a planted-offender probe — including one planted in the
  bootstrap, so the corrected registration claim cannot pass vacuously.
* **R-08c-4 — the upgraded `sample_dispersion_floor` breaks the 8.4-C
  historical claim.** The rung is upgraded WITH the check in one commit and
  the claim re-proven through the real transport; the pre-upgrade
  arithmetic anchors are kept verbatim.
* **R-08c-5 — run-scope ledger friction in multi-family tests.** Three
  families in one process is test-only; `reset_run_scope` between
  compositions is the established 08b idiom (noted in C6).
* **R-08c-6 — reader drift between a pack provider and the TaskDataPath
  codec.** Owned by the mandatory two-task codec-parity regressions
  (§2.12) — a format change cannot leave one reader silently accepting a
  different artifact than the other.

## 10. Ledger

*(filled per commit during implementation; the Gate-2 specs land here
before launch; the parent §14 A–H completion table lands here at C6)*
