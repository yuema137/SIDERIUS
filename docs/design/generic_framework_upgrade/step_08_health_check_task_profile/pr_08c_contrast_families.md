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
- [x] Re-read `_view_provider.py` (`arbitrary_types_allowed` at `:56`
      confirmed) and the 08b acme fixture's import surface
      (`test_out_of_tree_extension.py:361-378`: plugins import ONLY
      `execute_tools.health_checks` / `.schemas` — so C1 exports through the
      package root).
- [x] Two key constants in `standard_views.py`, parent §6.3 spellings,
      declared exactly once (census-enforced).
- [x] Payload models per §3.1: `_validated_readonly_stream` does
      isinstance/ndim/dtype-kind checks naming the offender, returns
      `value.view()` with `writeable=False`; frozen pydantic models with
      `arbitrary_types_allowed` (the `HealthView` precedent); before-mode
      validators.
- [x] Exported via `__init__.py` (4 names); guard module
      `tests/unit/execute_tools/health_checks/test_standard_views.py` —
      root assertion, rc∈{0,1} assertion, positive probes, `--untracked`.

**Validation plan.**
- [x] Unit: valid construction (int8/int64/uint8/uint32 symbols;
      float32/float64 samples, native dtype preserved); rejection of every
      wrong class — bool, string, object, float-as-categorical,
      int-as-continuous, 2-D, list, tuple — each naming the offender;
      empty arrays and non-finite floats ACCEPTED (check-level per §3.2a).
- [x] Unit: read-only + no-copy — mutation through the stored view raises
      `ValueError: read-only`; `np.shares_memory` True (NOT `.base`);
      writable input stays writable; read-only input stays read-only and is
      accepted; contents unchanged.
- [x] Unit: key strings hardcoded; package-root export identity asserted.
- [x] Census: engine modules (`runner.py`, `_view_provider.py`,
      `_plugin_binding.py`, `_composition.py`) have zero CODE references.
- [x] Backward-compat: health package 626 passed (`/tmp/08c_c1.log`,
      rc=0); goldens 0 bytes changed (`git status` clean on `goldens/`);
      inertness guard mutation-proven (below).

**Acceptance criteria.**
- [x] The two capability-key strings exist in exactly ONE production module
      (`test_key_string_is_defined_in_exactly_one_production_module`).
- [x] Every §3.1 ABI bullet has a failing test: wrong dtype-kind rejected
      with the dtype named; non-1-D rejected; mutation raises; no copy via
      `shares_memory`; provider writeability preserved in both directions.
- [x] Engine opacity census green; inertness guard green and
      mutation-proven; manifest byte-identical.

**C1 deviation (bounded, recorded).** The §3.1/§4.1 census is implemented
CODE-level (AST: identifiers, imports, class/function definitions,
non-docstring string literals; git-grep `--untracked` as substring
prefilter) rather than raw-text grep. Reason, from source at the head:
`_view_provider.py:33` (08b, must-not-change in C1) names both standard
keys in PROSE while remaining perfectly opaque to them, and
`sample_dispersion_floor.py`'s plugin-local key
`step08.fixture_continuous_samples` contains `continuous_samples` as a
substring. A raw-text census would cry wolf on both; the code-level census
tests the actual §3.1 claim (no import/branch/literal). Keys are matched
EXACTLY (keys are exact strings); the module name `standard_views` as a
substring (dotted import paths). Non-`.py` production files (YAML etc.)
count on the raw hit. Mutation evidence: an untracked
`execute_tools/_c1_mutation_probe.py` (import + key literal) turned 3
census tests RED, and an untracked `configs/_c1_mutation_probe.yaml`
(`capability: continuous_samples`) turned the non-Python census RED;
removed → 46/46 green.

**Failure and edge cases.** Empty arrays are ACCEPTED by the payload
(emptiness is check-level ERROR per §3.2a — a provider must be able to say
honestly "I read the artifact and it was empty"). Non-finite floats are
ACCEPTED by the payload and condemned by the check (§3.2a). NaN cannot hide
in an integer categorical payload by construction.

**Verification commands and evidence.**
- [x] `.venv/bin/python -m pytest tests/unit/execute_tools/health_checks/ -q > /tmp/08c_c1.log 2>&1`
      Evidence: **626 passed in 2.55s, rc=0** (46 new + 580 existing; the
      27-case verdict manifest, composed state-A goldens and value-scale
      owners all inside this run; goldens byte-identical on disk).
- [x] `ruff check` + `ruff format --check`. Evidence: **All checks passed /
      3 files already formatted** (after fixing 2 RUF043 in the new test
      module — escaped regex dots in `pytest.raises(match=)`).
- [x] `pyright` — CI-owned; recorded, never claimed locally.

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
- [x] Re-read at the head: `sample_dispersion_floor.py` (full),
      `test_step08_44_rungs.py` (full), `_composition.py` (full),
      `schemas.py:720-1049`, `runner.py:130-240`,
      `_plugin_binding.py:466-602`, `_task_health_config.py:95-169`,
      `test_view_provider.py` idiom, `test_check_declarations.py`
      biconditionals, `test_per_sample_evidence.py` censuses. Insertion
      point confirmed: `compose_gate`'s update order (silent-overwrite
      hazard) + `value_scale_parameters_for` (the declaration-driven
      precedent).
- [x] Two categorical checks (`categorical_distinct_symbols.py`,
      `categorical_dominant_fraction.py`): declarations exactly as frozen;
      `np.unique`(+`return_counts`) over the read-only view; occupancy =
      distinct/cardinality recorded (the injected fact provably in the
      arithmetic); dominant records the dominant symbol and fraction.
- [x] Shared family module `_categorical_validity.py`: `validate_symbols`
      (out-of-range → FAILED half, deterministic report naming first
      offender + range) AND `resolve_categorical_inputs` (the ERROR half:
      absent view / foreign payload / missing injected cardinality / empty
      stream) — one §3.2a mechanism, both checks consume it.
- [x] `sample_dispersion_floor` upgraded in place: `CONTINUOUS_SAMPLES`
      view, `requires_view=True`, `required_facts=()` (§2.11), config-borne
      `samples` RETIRED, `np.std(samples, dtype=np.float64, ddof=0)` +
      float64 mean, non-finite → FAILED naming index/value, metric keys
      unchanged (dispersion/mean/min_dispersion/n_samples), default floor
      0.5 kept.
- [x] `_composition.py`: `SYMBOL_CARDINALITY_PARAMETER`, frozen
      `INJECTABLE_AXIS_PARAMETERS` table (+ derived
      `INJECTED_PARAMETER_KEYS`), `symbol_cardinality_parameters_for` +
      `injected_parameters_for` (union of table injectors),
      authored-collision refusal in `compose_gate` (deterministic
      `HealthCompositionError` naming the keys, before config assembly);
      `value_scale_parameters_for` semantics byte-preserved (shared
      `_declared_axes` extracted); `compose_gate` 4th param renamed
      `injected_parameters` (all callers positional — verified).
- [x] Bootstrap 7→9 (`__init__.py` registers both, with the §4.6
      built-in-vs-external comment); `BUILTIN_CHECK_NAMES` hardcoded to 9.

**Validation plan.**
- [x] Unit, hand-computed anchors (hardcoded in
      `test_generic_collapse_checks.py`): all four §2.5 values (n=370,
      distinct=2 FAILED at 5, occupancy 0.05405405405405406, dominant
      0.9972972972972973 FAILED at 0.95, dominant symbol 5); healthy
      37-cycle spread PASSES both (dominant exactly 10/370); inclusive
      boundaries load-bearing both directions; dispersion √5 series kept
      verbatim (upgraded rung module, via views).
- [x] §3.2a boundary: empty → ERROR (both categorical + dispersion);
      out-of-range → FAILED naming offender+range, mutation-proven
      load-bearing for BOTH checks (helper silenced per-module → ruling
      disappears); NaN → FAILED naming index; absent view → ERROR;
      foreign payload → ERROR naming type; missing injected cardinality →
      ERROR; provider raise → ERROR through `evaluate_gate` (08b guard
      re-asserted with a categorical provider).
- [x] Injection: positive (composed config carries 37 for both gates);
      no-declaration ⇒ nothing (dispersion check); no-cardinality task ⇒
      nothing; authored-collision refusal for ALL THREE injected keys +
      the agreeing-value case; frozen table hardcoded
      (`INJECTABLE_AXIS_PARAMETERS` / `INJECTED_PARAMETER_KEYS`);
      value-scale behaviour owned by the untouched existing tests + the
      byte-identical composed goldens.
- [x] Ordering/transport: no-cardinality task → INAPPLICABLE with
      `inapplicable_axis == symbol_cardinality` and `provider.calls == []`
      (spy); the composed→bound→evaluated chain delivers the keyword-only
      view (occupancy in persisted metrics proves injection reached
      `run`).
- [x] Backward-compat/default-parity: health package 672 passed + goldens
      0 changes on disk (`/tmp/08c_c2.log` final: 808 passed with
      `tests/unit/guardrails/`, rc=0); declaration censuses green over the
      grown registry (new checks: no value-scale axis, no
      `per_sample_evidence`, `symbol_cardinality` in NO
      `threshold_parameter_names`); `:150` pattern extended to all three
      generic checks; TIDMAD task config authors NO injected key
      (`test_tidmads_shipped_task_config_authors_no_injected_key`).

**Acceptance criteria.**
- [x] Each check's declaration lists exactly its one threshold key;
      `symbol_cardinality` appears in NO `threshold_parameter_names`
      (asserted over the whole registry).
- [x] The real-collapse anchors pass with all four §2.5 values hardcoded —
      occupancy included, proving the injected cardinality enters the
      arithmetic (also end-to-end through the composed chain).
- [x] Config-borne `samples` + `encoding_family` requirement GONE (grep:
      only prose comments remain; declaration census `required_facts ==
      ()`); 8.4-C survives through the view path — **mutation: reverting
      `sample_dispersion_floor.py` to the pre-C2 committed form → 10 rung
      tests RED including both decisive rungs; restored → green.**
- [x] Collision refusal deterministic and named; silent overwrite gone —
      **mutation: neutralizing the refusal intersection → all 4 collision
      tests RED (3 keys + agreeing-value); restored → 9/9 green.**
- [x] Registry census: bootstrap registers exactly 9 (hardcoded
      `BUILTIN_CHECK_NAMES`); value-scale biconditional set still exactly
      the four TIDMAD checks (existing biconditional + new-check
      assertions).

**C2 deviations (bounded, recorded).**
1. The §3.2a ERROR half is shared family code too:
   `resolve_categorical_inputs` lives beside `validate_symbols` in
   `_categorical_validity.py` (the design named one shared helper for the
   validity arithmetic; the ERROR guards are the other half of the same
   boundary and putting them in one check would have forced a check→check
   import).
2. `test_view_provider.py::test_all_seven_builtins_declare_a_capability_
   but_require_no_view` asserted `requires_view is False` for ALL
   registered checks — an 08b-era premise C2 deliberately changes.
   UPGRADED (not deleted) to a hardcoded partition: six TIDMAD checks
   legacy-path, three generic checks view-requiring.
3. `compose_gate`'s 4th parameter renamed `value_scale_parameters` →
   `injected_parameters` (it now carries the table's union); all callers
   audited positional-only, `value_scale_parameters_for` behaviour
   preserved byte-for-byte.

**Failure and edge cases.** A roster naming a categorical check while the
task declares no cardinality: INAPPLICABLE, not an error (validly bound,
facts silent). A blocking gate's injected `aggregation: any_pass` is
ignored by single-artifact checks — harmless, asserted so the assumption is
recorded. An int8 symbols array with cardinality 256: distinct counting
must not overflow or coerce (NumPy handles it; asserted with an int8
fixture).

**Verification commands and evidence.**
- [x] `.venv/bin/python -m pytest tests/unit/execute_tools/health_checks/ tests/unit/guardrails/ -q > /tmp/08c_c2.log 2>&1`
      Evidence: **808 passed, rc=0** (health package 672 incl. the 104
      new/upgraded C2 tests + guardrails 136).
- [x] Manifest + composed state-A goldens byte-identical: their owner
      tests green inside the run AND `git status goldens/` = 0 changes.
- [x] `ruff check` clean; `ruff format` applied (2 new test files
      reformatted, then re-run green); `pyright` CI-owned.

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
- [x] Re-read governance guards + `_task_health_config.py` + the plugin
      loaders at the head. Layout: relative ref `../plugins/…` from
      `declared/` is legal (refs are config-relative, `HealthPluginRef`).
      **Bounded deviation (loader-convention collision):** the plugin file
      is `plugins/_pets_health_views.py` (underscore-prefixed), not
      `pets_health_views.py` — BOTH generic directory scanners exec/skip
      by the `_` convention (`ml_models/plugin_loader.py:136` EXECUTES
      every non-underscore `.py` it scans, and
      `tests/unit/examples/test_pets_reference_plugin.py` +
      `SIDERIUS_PLUGIN_DIRS` scan the pack's whole `plugins/` dir, which
      would exec the health plugin and leak its provider registration
      into unrelated processes/tests; `_plugin_binding.py:261` skips `_`
      members in directory-kind scans identically). The explicit
      `kind: file` ref is underscore-exempt and is the plugin's ONLY
      loading path.
- [x] `declared/task_health.yaml`: facts `categorical_labels` +
      `symbol_cardinality: 37`; both blocking gates with the FROZEN
      thresholds; §2.5 provenance comments carried verbatim.
- [x] Provider `pets.prediction_views` (in `_pets_health_views.py`):
      header-checked pack-local projection `project_predictions` →
      image-id-sorted int64 stream → `CategoricalPredictionsPayload`;
      missing file / bad header raise → ERROR; imports ONLY the package
      public surface (the acme shape).
- [x] Fixture-of-record committed byte-identical from
      `/home/klz/Data/SIDEREIS_DATA/d14_pets_gate2_20260818/`; sha256
      `cc847026…f752c` + size 6 812 verified at copy time and pinned in
      `TestFixtureOfRecord`. Real distribution confirmed from the bytes:
      369× class 5, 1× class 33.
- [x] Codec parity (§2.12): same bytes through
      `PetsTaskDataPath.read_evaluation_payload` (production grammar name
      in tmp) AND `project_predictions` → identical `{image_id: class}`
      (370 entries); BOTH readers refuse the same bad header.
- [x] Evidence tests: full state-C chain (shipped policy-only framework
      config + pack binding) → both gates FAILED with all four §2.5
      values + `invalidate_round`; healthy 37-class counterfactual →
      both PASS.
- [x] TIDMAD's six int8 checks inapplicable under the pack's RESOLVED
      facts, each on `axis == encoding_family` (full context supplied so
      the fact axis, not a context input, decides).

**Validation plan.**
- [x] Unit as above (15 tests, `test_pets_health_family.py`); negative:
      bad header → ERROR through the gate (`view provider failed`);
      missing deliverable → ERROR; fail-closed pair (plugin file absent →
      `HealthPluginError`; roster naming `pets_nonexistent_check` →
      `HealthBindingError`); relocated-pack composition still resolves
      (path-independence).
- [x] Census: AST id census over `execute_tools/health_checks/*.py` —
      no `pets`/`oxford`/`categorical_labels`/gate-id identifier and NO
      integer literal 37 in generic health core (anti-vacuity probe on a
      known identifier).
- [x] Backward-compat: examples 152 + health 672 = 824 passed rc=0
      (`/tmp/08c_c3.log`); goldens 0 changes; pack-governance suite green
      inside the run (the new YAML + underscore plugin pass the guards).

**Acceptance criteria.**
- [x] Committed fixture sha256 == `cc847026…f752c` and size 6 812,
      asserted (`TestFixtureOfRecord`).
- [x] BOTH blocking gates FAIL on the fixture with all four §2.5 values
      persisted in check metrics; actions `invalidate_round`.
- [x] Healthy counterfactual passes both gates.
- [x] Codec parity holds (content equality + shared header refusal).
- [x] Pets identifier census green over generic health core.

**Failure and edge cases.** CSV with unknown image ids: irrelevant to
health (the checks see symbols only) — recorded, not guarded. Symbols
outside `[0, 37)`: FAILED via the shared validity helper. A hand-edited
pack threshold: caught by nothing here BY DESIGN (thresholds are
task-owned); only the fixture EVIDENCE values are pinned.

**Verification commands and evidence.**
- [x] `.venv/bin/python -m pytest tests/unit/examples/ tests/unit/execute_tools/health_checks/ -q > /tmp/08c_c3.log 2>&1`
      Evidence: **824 passed, rc=0**; goldens 0 changes on disk; ruff
      check clean + format applied; pyright CI-owned.

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
- [x] Re-read `davis_data_path.py` writer/reader (`:310-339`), `clip_key`
      (`{sequence}:{start}`), `deliverable_name` (`.npz` grammar) and the
      request models at the head.
- [x] Provider `davis.sample_views`
      (`plugins/_davis_health_views.py`, underscore-prefixed — the C3
      loader-convention deviation applies identically):
      `project_full_sample_stream` = missing file → raise; sorted clip
      keys → per-clip C-order `ravel()` → ONE `np.concatenate`, native
      dtype preserved; unequal clip shapes → raise (structurally
      inconsistent artifact); zero clips → EMPTY float32 stream (the
      artifact WAS read; the CHECK rules emptiness). No cap, no
      sampling.
- [x] `declared/task_health.yaml`: facts `continuous_float`;
      `davis_dispersion_blocking` with FROZEN `min_dispersion: 0.04`;
      §2.9 provenance comment (measurement, ≈5.4× margin,
      single-artifact caveat) verbatim.
- [x] Codec parity (§2.12): three clips written through the PRODUCTION
      `write_deliverable` → `read_evaluation_payload` (key set, shapes,
      float32 dtype, values vs originals) AND → provider stream ==
      concat(sorted ravel of the reader payload), dtype-equal.
- [x] Evidence tests: constant npz → FAILED dispersion 0.0 exact; §2.9
      near-collapse perturbation control → FAILED at ≈√7e-6; varied npz →
      PASSED at hand-computed √5; skip-guarded real-npz tests (sha
      verified; n = 5,160,960; dispersion == 0.2156402715035823 EXACT;
      gate PASSED at 0.04 with the frozen value persisted) — **RAN on
      this machine** (artifact present), skip path declared.
- [x] TIDMAD's six int8 checks inapplicable under DAVIS' resolved facts,
      each on `axis == encoding_family`.

**Validation plan.**
- [x] Negative paths all through `evaluate_gate`: missing npz → ERROR
      (`view provider failed`); corrupt bytes → ERROR; unequal shapes →
      ERROR naming them; empty npz → ERROR at the check with
      `n_samples == 0`; NaN frame → FAILED with
      `non_finite_samples == 1`; fail-closed pair (missing plugin →
      `HealthPluginError`; unregistered check → `HealthBindingError`).
- [x] Census: DAVIS identifiers (`davis`, gate id, `sample_views`)
      absent from generic health core (AST census); no new `FACT_AXES`
      (nothing added); the dispersion check's empty facts declaration
      owned by the C2 rung module.
- [x] Backward-compat: examples 173 + health 672 = 845 passed rc=0
      (`/tmp/08c_c4.log`); goldens 0 changes; C3 Pets evidence green in
      the same run (families independent).

**Acceptance criteria.**
- [x] Verdicts flow through the SAME engine path as Pets with zero
      task-name knowledge (id census; no framework surface touched — the
      C4 diff contains no `execute_tools/health_checks/` change).
- [x] The synthetic pair is decisive (FAILED 0.0 / PASSED √5, hardcoded).
- [x] The skip-guarded real-npz test reproduces the §2.9 dispersion
      EXACTLY on this machine (ran, not skipped) and skips honestly
      elsewhere with the declared reason.
- [x] Codec parity holds for DAVIS.

**Failure and edge cases.** The payload carries the artifact's NATIVE
float32; float64 enters only inside the check's estimator (§3.5a precision
ownership) — no contract claims concatenation upcasts. A future clip-count
change alters n but not the semantics — nothing pins 15.

**Verification commands and evidence.**
- [x] `.venv/bin/python -m pytest tests/unit/examples/ tests/unit/execute_tools/health_checks/ -q > /tmp/08c_c4.log 2>&1`
      Evidence: **845 passed, rc=0** (incl. the 21 new DAVIS tests with
      the 3 real-npz tests EXECUTED — the preserved artifact is present
      on this machine); goldens 0 changes; ruff clean + format applied;
      pyright CI-owned.

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
- [x] Re-read both runners end-to-end at the head. Insertion point: after
      `evidence["metric"]`, before `evidence["verdict"]` and the single
      JSON dump (both runners follow one convention — an `evidence` dict
      written once). Both runners set `SIDERIUS_PLUGIN_DIRS` to the
      pack's whole `plugins/` dir, retroactively confirming the C3/C4
      underscore-prefix decision (the ML scan at Gate-2 runtime would
      have EXEC'd a non-underscore health plugin).
- [x] Shared stage `scripts/_gate2_health_stage.py::run_health_stage`
      (keyword-only, binding REQUIRED with no default): loud
      `FileNotFoundError` on a missing binding BEFORE evaluation;
      `materialize_effective_config(None, None, workspace,
      task_health_binding=…)` (state C); `get_gates_for_position(1)` →
      `evaluate_gate` for EVERY selected gate (no cross-gate
      short-circuit); returns the additive block (binding path, pinned
      sha, `loaded_plugin_set()` canonical identities, ordered gate
      entries with check ids / composed check configs / verdicts /
      resolved action / failure reason / metrics).
- [x] Both runners wired through the ONE helper
      (`from scripts._gate2_health_stage import run_health_stage`; the
      namespace-package import the scripts tests already use);
      per-gate verdict/action printed; PASS framing documented in both
      docstrings ("a FAILED verdict on a genuinely collapsed deliverable
      is the stage WORKING").
- [x] Guardrail INVERTED in place
      (`TestExistingTasksEnterHealthOnlyThroughTheExplicitBinding`):
      runners reach Health ONLY through the shared stage (no raw
      entry-point call, no direct health import, stage import REQUIRED);
      every `run_health_stage` call carries `task_health_binding=` and
      names the pack's own `task_health.yaml`; the stage parameter is
      keyword-only with NO default; every composition call in the stage
      passes the keyword; the stage is the ONLY
      `materialize_effective_config` caller under `scripts/`;
      anti-vacuity probes kept (omitted-shape detection + health-import
      detection). Sibling classes untouched.
- [x] Both runners' docstrings updated (stage, binding, additive
      evidence block, PASS semantics).

**Validation plan.**
- [x] Shared-stage owner tests (`tests/unit/scripts/test_gate2_health_stage.py`,
      12 tests — the FIRST owner of the runner evidence contract, per the
      §2.8 audit): binding threaded (block path == pack path; block sha ==
      `read_effective_config_body_sha` of the materialized artifact;
      plugin canonical identity present); BOTH Pets gates persisted on
      the collapsed fixture although the FIRST resolves
      `invalidate_round` — with thresholds (5 / 0.95 / injected 37) and
      the §2.5 decisive metrics in the block; JSON-serializable; DAVIS
      pack flows through the SAME helper (√5 synthetic PASS at the 0.04
      floor); missing binding refuses loudly with NO effective config
      written; runner evidence keys == golden pre-C5 set ∪ {health}
      (AST census over both runners, extractor anti-vacuity).
- [x] Mutations (all RED then restored green): stage binding acquires a
      default → kwonly-no-default guard RED; stage drops the binding
      keyword at the composition call → keyword census RED; pets runner
      drops the explicit kwarg → runner census RED; stage short-circuits
      after the first failed gate → every-gate-persisted owner RED.
- [x] NO real run in this commit — Gate 2 (§7) at this head after the
      §10 specs are written.

**Acceptance criteria.**
- [x] ONE stage implementation (census: the stage is the only
      `materialize_effective_config` caller under `scripts/`).
- [x] Inverted guardrail RED under the omitted-binding mutations, green
      at the head.
- [x] `health:` block ADDITIVE (pre-C5 key set unchanged, structural)
      and carries every §3.5 field.
- [x] On the collapsed fixture, BOTH Pets gates' evidence present in one
      block.

**Failure and edge cases.** Pack config path missing → the stage fails
LOUDLY before evaluation (a runner that silently dropped its health stage
would pass off D14-era evidence as 08c evidence). Deliverable absent →
provider ERROR path (asserted in C3/C4). Evidence file pre-existing from a
prior run in the same workspace: the stage writes into THIS run's evidence
dict before the single JSON dump — no partial-file merge logic.

**Verification commands and evidence.**
- [x] `.venv/bin/python -m pytest tests/unit/guardrails/ tests/unit/execute_tools/health_checks/ tests/unit/scripts/test_gate2_health_stage.py -q > /tmp/08c_c5.log 2>&1`
      Evidence: **820 passed, rc=0**; goldens 0 changes; ruff clean +
      format applied; pyright CI-owned.

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
- [x] Census (`tests/unit/guardrails/test_health_core_census.py`, 124
      tests) over the ENUMERATED generic partition (TIDMAD-family
      surfaces excluded BY LISTED NAME, exhaustiveness-guarded so a new
      module lands censused by default): zero task tokens
      (`tidmad|pets|davis|oxford|acme`) in generic CODE with exactly ONE
      quarantined allowance (`LEGACY_DEFAULT_TASK_HEALTH_CONFIG`'s
      `tidmad.yaml` string, named + still-real-asserted); zero `examples`
      imports package-wide; no literal 37; no `int8`/`channel000x`/`mV`
      code literals (Field `description=` strings and bare-string
      attribute docstrings excluded as documentation — the collector fix
      below); the standard vocabulary confined to
      `standard_views/__init__` + the three consumers; no metric-scalar
      consumption outside the two NAMED non-check allowances
      (`schemas.py` carrier/predicates; `candidate_eligibility.py`
      record-eligibility read) + the invariant-16 check-source census
      re-run over the grown registry; **amendment 10 exactly**: the
      bootstrap enumerates ONLY the nine hardcoded framework built-ins,
      and no pack/external id appears in the bootstrap, any package
      module, or the framework policy YAMLs.
- [x] Three-task rung (same module): state A composes the six known
      TIDMAD gate ids; Pets state C the two categorical gates; DAVIS
      state C the dispersion gate; rosters pairwise disjoint; the six
      int8 declarations inapplicable (axis `encoding_family`) under BOTH
      contrast tasks' resolved facts; state A re-materialized AFTER the
      interleaving is byte-identical (sha + full text) —
      `reset_run_scope` between compositions (the 08b idiom).
- [x] Parent §14 A–H mapped to evidence (§10.8 below).
- [x] Docs sync: `docs/design/pluggable_health_checks.md` — NEW §9a
      (standard capabilities + generic family + reference bindings,
      quoted against merged source), §10 registration story corrected to
      the current two-path reality (built-in bootstrap vs external
      zero-edit; task rosters in TASK configs — the framework YAML is
      policy-only), changelog entry; both pack STATUS health rows →
      C5-landed with Gate-2 results.

**Validation plan.**
- [x] Census anti-vacuity: collector self-probe (code string seen,
      docstring/description prose skipped); planted task-comparison
      probe; planted examples-import probe; planted science-literal
      probe; **a fixture id planted in a synthetic bootstrap IS detected
      and breaks the hardcoded-nine equality**.
- [x] Terminal deterministic validation (amendment 11) — see the
      verification command below.
- [x] `git diff` of this commit: tests/docs only (verified before
      committing — zero production-source bytes).

**Acceptance criteria.**
- [x] Every §13 strengthened item is one executable assertion with a
      planted-offender probe; the registration claim reads exactly as
      amendment 10 froze it.
- [x] The three-task rung passes; the §14 A–H table cites per-item
      evidence.
- [x] Zero production-source bytes changed by this commit.

**C6 finding (bounded, recorded — out of scope).**
`execute_tools/health_checks/evaluation.py` (the pre-08a campaign
persistence adapter) hardcodes per-check-name threshold/metric tables for
the six TIDMAD checks (`_threshold`, `_per_file_metrics`) — TIDMAD-family
knowledge in a generically-named module, predating declarations. It is
EXCLUDED from the generic census by listed name with a comment, exactly
like the six check modules. Making it declaration-driven is future debt
(Step 9/10 territory), deliberately NOT absorbed into 08c.

**C6 census-collector correction (bounded).** The first census run flagged
`_composition.py`/`_plugin_binding.py` on bare-string ATTRIBUTE docstrings
(the `CONSTANT = …` + `"""prose"""` idiom) — prose, not code. The
collector now treats EVERY bare string expression statement as
documentation (a bare string has no runtime effect), alongside pydantic
`description=` strings; the self-probe pins both exclusions.

**Failure and edge cases.** A census pattern that would fire on the
TIDMAD-owned check modules: excluded by an explicit LISTED set with a
comment, so the census cannot silently widen or narrow.

**Verification commands and evidence.**
- [x] `.venv/bin/python -m pytest tests/unit/execute_tools/health_checks/ tests/unit/guardrails/ tests/unit/examples/ tests/unit/scripts/test_gate2_health_stage.py -q > /tmp/08c_c6.log 2>&1`
      Evidence: **1117 passed, rc=0** (health 672 · guardrails incl. the
      124 new census/rung tests · examples 173 · stage 12); goldens 0
      changes; working tree carries ZERO production-source changes
      (verified by `git status` category filter before commit); ruff
      clean; pyright CI-owned.

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

### 10.1 C1 — standard view capabilities (2026-08-18)

* Base `70eb21b9` (== master == origin/master, verified; clean tree at
  start). Files: NEW `execute_tools/health_checks/standard_views.py`
  (2 key constants, `_validated_readonly_stream`, 2 frozen payload
  models); `__init__.py` +2 import blocks / +4 `__all__`; NEW
  `tests/unit/execute_tools/health_checks/test_standard_views.py`
  (46 tests: ABI, read-only/no-copy, key spellings, engine-opacity census,
  C1 inertness census).
* TIDMAD parity at this commit: health package 626 passed rc=0
  (`/tmp/08c_c1.log`); `goldens/` 0 changes on disk — 27-case manifest,
  composed state-A executed-semantics golden, value-scale owners all
  green and byte-identical.
* Mutation evidence: planted untracked `.py` (import + key literal) → 3
  RED; planted untracked YAML key use → 1 RED; removed → 46/46 green.
* Bounded deviation: census is AST/code-level, not raw-text (prose
  collisions in `_view_provider.py:33` and the fixture-spelled key —
  recorded under §4.1 acceptance).
* Ruff clean; pyright CI-owned.

### 10.2 C2 — generic collapse checks + cardinality injection (2026-08-18)

* Files: NEW `_categorical_validity.py` (shared §3.2a mechanism:
  `validate_symbols` FAILED half + `resolve_categorical_inputs` ERROR
  half), NEW `categorical_distinct_symbols.py`, NEW
  `categorical_dominant_fraction.py`; UPGRADED
  `sample_dispersion_floor.py` (view-consuming, no facts, float64
  estimator, non-finite guard, config-samples retired); `_composition.py`
  (frozen `INJECTABLE_AXIS_PARAMETERS` table, `INJECTED_PARAMETER_KEYS`,
  cardinality injector, union injector, collision refusal in
  `compose_gate`); `__init__.py` bootstrap 7→9. Tests: NEW
  `test_generic_collapse_checks.py` (37 tests); `test_step08_44_rungs.py`
  REWRITTEN for the real transport (real provider + real binding path, no
  runner monkeypatch; anchors verbatim); `test_standard_views.py`
  inertness census INVERTED to the enumerated 4-module consumer set;
  `BUILTIN_CHECK_NAMES` → 9; `test_view_provider.py` partition upgrade
  (deviation 2).
* TIDMAD parity at this commit: 808 passed rc=0 (health 672 + guardrails
  136); goldens 0 changes on disk (27-case manifest, composed state-A
  executed-semantics, value-scale owners all inside the run).
* Mutations: (A) revert `sample_dispersion_floor.py` to pre-C2 → 10 rung
  tests RED, restored green; (B) neutralize the collision-refusal
  intersection → 4 collision tests RED, restored green; (C1 carryover)
  helper-silencing per check module → range ruling disappears (in-suite
  permanent mutation tests).
* Ruff clean; pyright CI-owned.

### 10.3 C3 — Pets family + committed collapse fixture-of-record (2026-08-18)

* Files: NEW `examples/oxford_iiit_pet/declared/task_health.yaml` (frozen
  floors 5 / 0.95, §2.5 provenance comments); NEW
  `examples/oxford_iiit_pet/plugins/_pets_health_views.py` (provider
  `pets.prediction_views`, pack-local `project_predictions`,
  underscore-prefixed — bounded deviation recorded in §4.3, the explicit
  `kind: file` ref is the only loading path); NEW committed fixture
  `examples/oxford_iiit_pet/expected/d14_gate2_collapse_predictions.csv`
  (sha `cc847026…f752c`, 6 812 B, verified at copy: 369× class 5 + 1×
  class 33); STATUS.md health row → 08c C3; PROVENANCE.md fixture
  section; NEW `tests/unit/examples/test_pets_health_family.py`
  (15 tests, local registry-isolation fixture since the health conftest
  is out of scope there).
* Framework config for the state-C chain is the SHIPPED policy-only
  `configs/health_checks.yaml` (source_path=None) — more
  production-faithful than the acme fixture's synthesized policy file.
* One test-bug diagnosis during bring-up: the int8-inapplicability
  assertion first used a ctx without a target source, so
  `pearson_dispersion` was inapplicable on `target_source` (context
  inputs precede fact axes — the 08a order working as designed); fixed by
  satisfying all context inputs so the FACT axis decides.
* TIDMAD parity at this commit: examples 152 + health 672 = 824 passed
  rc=0; goldens 0 changes.
* Ruff clean; pyright CI-owned.

### 10.4 C4 — DAVIS family (2026-08-18)

* Files: NEW `examples/davis_future_prediction/declared/task_health.yaml`
  (frozen floor 0.04, §2.9 provenance + single-artifact caveat); NEW
  `examples/davis_future_prediction/plugins/_davis_health_views.py`
  (provider `davis.sample_views`, FULL decoded view — sorted keys →
  C-order ravel → concat, native float32, no cap; unequal shapes refuse);
  STATUS.md health row → 08c C4; PROVENANCE.md threshold-provenance
  section; NEW `tests/unit/examples/test_davis_health_family.py`
  (21 tests).
* The frozen §2.9 dispersion REPRODUCED on this machine from the
  preserved npz (sha `ee52a710…0a010` verified): full 5,160,960-sample
  view, `np.std(dtype=float64, ddof=0)` == `0.2156402715035823`
  bit-equal, and the composed gate PASSES it at the 0.04 floor with the
  value persisted. Skip guard covers machines without the corpus.
* Codec parity proven on production-written bytes (three clips, both
  readers agree on keys/shapes/dtype/values; provider stream equals the
  reader-derived expectation exactly).
* No framework module touched in this commit (engine untouched by
  construction — the diff is pack + tests only).
* TIDMAD parity at this commit: examples 173 + health 672 = 845 passed
  rc=0; goldens 0 changes.
* Ruff clean; pyright CI-owned.

### 10.5 C5 — shared runner Health stage + guardrail inversion (2026-08-18)

* Files: NEW `scripts/_gate2_health_stage.py` (`run_health_stage`,
  keyword-only explicit binding, every-gate evidence collection, additive
  block); `scripts/run_pets_gate2.py` + `scripts/run_davis_gate2.py`
  (docstring + `TASK_HEALTH_BINDING` + one `evidence["health"]`
  assignment + per-gate print — training/inference/metric stages and all
  existing evidence fields untouched);
  `tests/unit/guardrails/test_step08b_cross_task_compatibility.py`
  guard class INVERTED in place (module docstring records the inversion;
  siblings untouched); NEW `tests/unit/scripts/test_gate2_health_stage.py`
  (12 tests — first owner of the runner evidence contract).
* Mutations (4/4 decisive, restored green): stage default / stage
  keyword drop / runner kwarg drop / cross-gate short-circuit.
* TIDMAD parity at this commit: guardrails + health + stage = 820 passed
  rc=0; goldens 0 changes.
* Ruff clean; pyright CI-owned.
* **This commit is the FINAL EXECUTABLE-PRODUCTION HEAD — the Gate-2
  head.** C6 is tests/docs only.

### 10.6 Gate-2 specifications (written BEFORE launch — §7 / amendment 13)

Preconditions verified before writing these specs: both data roots exist
(`/home/klz/Data/OXFORD_IIIT_PET/images`, `/home/klz/Data/DAVIS_2017`),
CUDA available (RTX 5090), and the D14 evidence corpora confirm the
runner shape (D14 pets train 3.42 s at these exact bounds).

#### 10.6.1 Pets Gate 2 — specification

* **Exact executable HEAD**: `ede11fd518b4f7037ec23bed2009f60db0792e81`
  (C5).
* **Claim**: the REAL Pets lifecycle — fresh train → infer → deliverable
  → metric — now ends in the pack's Health family evaluating that fresh
  deliverable through the explicit state-C binding, with both categorical
  gates' verdicts numerically consistent with the artifact and the full
  §3.5 evidence block persisted.
* **Command**:
  `SIDERIUS_ALLOW_LAUNCH=1 .venv/bin/python scripts/run_pets_gate2.py
  --data_dir /home/klz/Data/OXFORD_IIIT_PET/images
  --workspace /home/klz/Data/SIDEREIS_DATA/step08c_pets_gate2_20260818`
* **Bounds**: the committed D14 gate manifests — 370 train / 74
  validation / 370 final images, 2 epochs, batch 32 (runner defaults).
* **Binding**: `examples/oxford_iiit_pet/declared/task_health.yaml`
  (hardwired in the runner as `TASK_HEALTH_BINDING`; state C).
* **Expected lifecycle**: plugin scan → training (R2+R3, comparability
  established) → inference (370 predictions) → deliverable written →
  accuracy through the Step-06 handle → health stage (effective config
  materialized into the workspace; BOTH gates evaluated) → evidence JSON.
* **Expected wall time**: ≤ ~2 min (startup-dominated; D14 measured
  train 3.52 s + infer 0.74 s); hard bound 10 min.
* **PASS evidence** (from `gate_evidence.json`, never exit code): all
  pre-C5 stages complete (finite R2/R3, comparability `established`,
  370 predictions, finite accuracy in [0,1]); `health.task_health_binding`
  = the pack path; `health.effective_config_sha256` present and matches
  the workspace artifact; `health.resolved_plugins[0].configured_ref` =
  `../plugins/_pets_health_views.py` with a 64-hex content sha; BOTH
  gates present in order with verdicts ∈ {passed, failed} that are
  NUMERICALLY consistent with the fresh deliverable (recomputable from
  the deliverable bytes: distinct count vs floor 5, dominant fraction vs
  ceiling 0.95); no TIDMAD gate id in the block; no INAPPLICABLE, no
  ERROR. **Healthy or collapsed fresh predictions BOTH yield Gate PASS
  when the verdicts are numerically correct** — the reference CNN's
  2-epoch collapse is EXPECTED to recur, and FAILED verdicts on it are
  the framework working.
* **FAIL**: a verdict inconsistent with the fresh artifact's recomputed
  statistics; a TIDMAD roster in the health block; an unintended
  INAPPLICABLE/ERROR; a missing gate entry; a pre-C5 evidence key
  renamed/removed.
* **INCONCLUSIVE**: training/inference/metric fails before the health
  stage runs; no fresh deliverable; the stage never reached for a reason
  unrelated to the health claim.
* **Evidence destination**:
  `/home/klz/Data/SIDEREIS_DATA/step08c_pets_gate2_20260818/`
  (fresh workspace beside the D14 corpora; nothing preserved is
  overwritten).

#### 10.6.2 DAVIS Gate 2 — specification

* **Exact executable HEAD**: `ede11fd518b4f7037ec23bed2009f60db0792e81`
  (C5).
* **Claim**: the REAL DAVIS lifecycle ends in the pack's Health family
  evaluating the FULL decoded view of the fresh npz through the explicit
  state-C binding, with the dispersion metric persisted and the verdict
  consistent with the frozen 0.04 floor.
* **Command**:
  `SIDERIUS_ALLOW_LAUNCH=1 .venv/bin/python scripts/run_davis_gate2.py
  --data_dir /home/klz/Data/DAVIS_2017
  --workspace /home/klz/Data/SIDEREIS_DATA/step08c_davis_gate2_20260818`
* **Bounds**: the committed D14 gate manifests — 60 train / 15
  validation / 15 final clips, 2 epochs, batch 4 (runner defaults).
* **Binding**: `examples/davis_future_prediction/declared/task_health.yaml`.
* **Expected lifecycle**: plugin scan → training → inference (15/15
  clips) → npz written → global MSE through the Step-06 handle → health
  stage (FULL 15 × [3,4,128,224] = 5,160,960-sample view) → evidence
  JSON.
* **Expected wall time**: ≤ ~2 min (D14 measured train 7.28 s + infer
  0.58 s); hard bound 10 min.
* **PASS evidence**: all pre-C5 stages complete (finite MSE ≥ 0, 15
  predictions); explicit binding + sha + plugin identity as for Pets
  (`../plugins/_davis_health_views.py`); exactly ONE gate
  (`davis_dispersion_blocking`) with `sample_dispersion_floor` verdict ∈
  {passed, failed}, `n_samples == 5,160,960` (the FULL view), and the
  persisted dispersion NUMERICALLY consistent with the fresh npz
  (recomputable: `np.std(full stream, dtype=float64, ddof=0)` vs the
  0.04 floor); no TIDMAD fallback; no INAPPLICABLE; no ERROR.
* **FAIL**: dispersion/verdict inconsistent with the fresh artifact; a
  partial view (`n_samples` ≠ full element count of the fresh npz); a
  TIDMAD roster; unintended INAPPLICABLE/ERROR; a pre-C5 key changed.
* **INCONCLUSIVE**: the real workflow fails before the health claim is
  exercised.
* **Evidence destination**:
  `/home/klz/Data/SIDEREIS_DATA/step08c_davis_gate2_20260818/`.

### 10.7 Gate-2 results (2026-08-19, both at HEAD `ede11fd5`)

#### Pets Gate 2 — **PASS**

* Command exactly as specified; wall time ≈ 20 s end-to-end (training
  3.8 s, inference 0.7 s), inside every bound; exit 0 (not used as the
  verdict). Log `/tmp/08c_pets_gate2.log`; evidence
  `/home/klz/Data/SIDEREIS_DATA/step08c_pets_gate2_20260818/gate_evidence.json`.
* Lifecycle: plugin scan → 2-epoch training (R2 [3.6223, 3.6118], R3
  [3.6109, 3.6107], comparability established) → 370 predictions →
  deliverable → accuracy `0.02702702702702703` (exactly chance — the
  reference CNN's collapse RECURRED as projected) → health stage →
  evidence.
* **The fresh deliverable is BYTE-IDENTICAL to the committed
  fixture-of-record** (`cc8470267bf…f752c`) — the seed-11 bounded run is
  deterministic, so the Gate's live artifact and the C3 fixture are one
  measurement.
* Health block: binding = the pack's `task_health.yaml` (state C);
  `effective_config_sha256 = 22804f138b17…c2602b` — matches the
  workspace artifact's own header; plugin
  `../plugins/_pets_health_views.py` with content sha `9203c038…70d7d4`;
  BOTH gates present in order, both FAILED with `invalidate_round`.
* Independent recomputation from the fresh bytes: n=370, distinct=2,
  dominant symbol 5 at 369/370 = 0.9972972972972973 — the persisted
  metrics equal these exactly; verdict arithmetic consistent both
  directions (2 < 5 ⇒ failed; 0.99729… > 0.95 ⇒ failed). Verdict union
  == {failed}: no INAPPLICABLE, no ERROR. Effective config carries ZERO
  `tidmad` mentions; gate ids are the pack's two. Pre-C5 evidence keys
  intact + exactly one new `health` key.
* Classification: **PASS** — a collapsed fresh deliverable with
  numerically CORRECT blocking failures is the framework working (§7).

#### DAVIS Gate 2 — **PASS**

* Command exactly as specified; wall time ≈ 25 s end-to-end (training
  7.3 s, inference 0.6 s); exit 0 (not the verdict). Log
  `/tmp/08c_davis_gate2.log`; evidence
  `/home/klz/Data/SIDEREIS_DATA/step08c_davis_gate2_20260818/gate_evidence.json`.
* Lifecycle: plugin scan → 2-epoch training (R2 [0.04954, 0.04769], R3
  [0.04443, 0.04430], comparability established) → 15/15 predictions →
  npz → global MSE `0.017289766656259548` (better than last-frame-copy
  `0.017392…` — the D14 record values reproduced) → health stage →
  evidence.
* **The fresh npz is BYTE-IDENTICAL to the preserved §2.9 artifact**
  (`ee52a710…0a010`) — the bounded run is deterministic end-to-end.
* Health block: binding = the pack's `task_health.yaml` (state C); sha
  pin matches the workspace artifact; plugin
  `../plugins/_davis_health_views.py` with content sha `138ed7c5…e0b28`;
  ONE gate (`davis_dispersion_blocking`), `sample_dispersion_floor`
  PASSED with `continue`.
* Independent recomputation from the fresh npz: 15 clips, n = 5,160,960
  float32 samples (the FULL view — 15 × 3 × 4 × 128 × 224 exactly),
  `np.std(dtype=float64, ddof=0)` = `0.2156402715035823` — equal to the
  persisted dispersion AND to the frozen §2.9 value bit-for-bit;
  0.2156… ≥ 0.04 ⇔ passed ✓. `min_dispersion` 0.04 in the block; NO
  `symbol_cardinality` injected (no declaration). Zero `tidmad` mentions
  in the effective config; no INAPPLICABLE, no ERROR; pre-C5 keys
  intact + `health`.
* Classification: **PASS**.

Combined real runtime ≈ 45 s — far inside the ≤ ~20 min projection and
the ≤ ~1 h envelope. No retry was needed for either Gate. No preserved
evidence was overwritten (fresh `step08c_*` workspaces).

### 10.8 C6 — census + three-task rung + docs; parent §14 A–H closure (2026-08-19)

* Files (tests/docs ONLY — zero production-source bytes): NEW
  `tests/unit/guardrails/test_health_core_census.py` (124 tests: census +
  anti-vacuity probes + the three-task rung);
  `docs/design/pluggable_health_checks.md` §9a/§10/changelog; both pack
  STATUS health rows → C5-landed + Gate-2 results; this ledger.
* Terminal deterministic validation: **1117 passed rc=0**
  (`/tmp/08c_c6.log`) — health package, guardrails (inverted cross-task
  guard + census + rung), examples (both families + governance +
  **the 08b out-of-tree fourth-task proof**, green inside the health
  package run), shared-stage owner. Goldens byte-identical at every one
  of the six semantic commits.

**Parent §14 A–H completion mapping (the 08c halves + A re-verified):**

| item | evidence at this head |
|---|---|
| **A** TIDMAD untouched | §3.6's four deterministic owners green at every commit C1–C6 (27-case verdict manifest, composed state-A executed-semantics golden, value-scale owners, state-A roster/order — all inside the health-package runs; goldens 0 bytes moved); real-lifecycle authority remains 08b Gate-2 PASS at `bf6e9e19`; no 08c commit touched a TIDMAD check/roster/threshold |
| **B** Pets | committed real collapse fixture FAILS both blocking gates with the four §2.5 values persisted (C3 unit chain) AND the live half: 08c Pets Gate-2 PASS at `ede11fd5` — the fresh deliverable reproduced the collapse byte-identically and the family caught it (§10.7) |
| **C** DAVIS | real dense npz through the SAME engine with zero TIDMAD/classification assumption: frozen dispersion reproduced bit-equal on the preserved artifact (C4, skip-guarded, RAN) and on the fresh Gate-2 artifact (§10.7); no framework module changed in C4 |
| **D** generic core census | `test_health_core_census.py` — strengthened items executable + planted-offender probes (incl. the bootstrap probe) |
| **E** semantics | verdict vocabulary distinct/deterministic/persisted (08a authority, re-proven: verdict manifests byte-identical; §3.2a ERROR/FAILED boundaries owned by C2 tests; required-blocking-uncomputable fails closed — ERROR takes `on_fail`, asserted through gates in C2/C3/C4) |
| **F** testing ownership | per-commit ownership declared and executed (§4.1–§4.6 validation plans); no fake lifecycle Units — the live halves are the two real Gates; evidence cumulative (08a/08b corpora untouched) |
| **G** extensibility EXECUTABLE | the 08b out-of-tree proof (`test_out_of_tree_extension.py`) green at every commit — NOT re-proven by walkthrough, per the parent |
| **H** strong criterion | (i) zero task-name branches in generic core — census item 1 with the ONE quarantined constant; (ii) Pets (existing primitives + external provider plugin) and DAVIS (same) integrate via external task config + pack plugin with ZERO SIDERIUS infrastructure-source edits — C3/C4 diffs contain no `execute_tools/health_checks/` change, and the packs' ids appear nowhere in the package (census); the novel-semantics half is owned by the 08b acme proof (custom check + plugin-local capability), kept green |
