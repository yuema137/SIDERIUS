# PR 08c — contrast families + generic collapse checks + three-task evidence (child design)

## 0. Status and provenance

**DRAFT — REVISION 1. NOT FROZEN. IMPLEMENTATION NOT STARTED.**

Drafted 2026-08-18 at the operator's direction, after 08b merged. Child of
the FROZEN Step-08 parent (rev 3,
`docs/design/generic_framework_upgrade/step_08_health_check_task_profile.md`).
Authority order: frozen parent > current source (§2) > merged 08a/08b
implementations and ledgers > roadmap §8/§22.24 >
`pluggable_health_checks.md`.

**Audit anchor.** Every statement below is verified against **master
`d7b2c8c9`**, which contains the merged 08b (squash **`13e28796`**, PR #236)
plus its doc sync. Real-artifact claims are verified against the preserved
D14 gate evidence on this machine (§2.4), including one correction to the
parent's own prose (§2.7).

**Open questions:** four (§8). Every implementation checkbox in §4 is `[ ]`.
Freeze requires the operator to resolve §8 and ratify §3.

### 0.1 What this PR is, in one paragraph

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
extends to health core and the Step-08 completion criteria (§14 A–H) close.

### 0.2 The boundary this PR must not cross

Per Q-08b-4 (resolved at the 08b freeze) and the parent §11: 08c owns the
standard capabilities, the reusable generic checks and the Pets/DAVIS
bindings. It does NOT own: prompt/planner exposure of health (any PB delta
re-dispositions Gate 1 — none is elected), tuner integration of Pets/DAVIS
(parent §3.3.3: *"claiming tuner-integrated Pets health would be maturity
inflation"* — that is Steps 10/12), TIDMAD re-parameterization (§3.6 below),
Step-09 interpretation, or the Step-10/12 composition root.

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
* **Gates** (parent §12 08c + §10 table): Gate 2 = **bounded real Pets +
  DAVIS artifact evaluations (≤10 min each, D14 runner pattern; PASS/FAIL
  from semantic evidence)**. Gate 1: none unless a prompt delta is elected
  (none is).
* **Completion**: parent §14 items B, C, D and the 08c halves of F/H close
  here; A (TIDMAD goldens) must remain true at every commit.

## 2. Source audit (at master `d7b2c8c9`, merged 08b `13e28796`)

### 2.1 The landed 08b seam this PR builds on (file:line)

| element | location | behaviour 08c consumes |
|---|---|---|
| view transport | `_view_provider.py:48` `HealthView`, `:73` `HealthViewProvider` | opaque envelope; `materialize(capability_key, ctx, config)`; I/O only after applicability |
| provider registration | `registry.py:74` `register_view_provider` (public, `__init__`-exported) | pack plugins register providers exactly as the 08b acme fixture did |
| plugin loading | `_plugin_binding.py:354` `load_task_health_plugins` | config-named `.py`, run-scoped ledger, content digests → pinned identity |
| Phase-B resolution | `_plugin_binding.py:466` `resolve_task_health_bindings` | unresolved check/provider/capability → `HealthBindingError`; also sets `bound_task_facts` (`:544`) |
| materialization step | `_plugin_binding.py:554` `materialize_view`; wired in `runner.evaluate_gate` inside the Bug-B guard | a check with `requires_view=True` receives `view=`; provider failure → `CheckVerdict.ERROR` |
| composition | `config.py:533` `load_composed_health_config`, `:580` `materialize_effective_config(..., task_health_binding=)` | state C (explicit path) is the route Pets/DAVIS take; state A composes TIDMAD (`_composition.py:89`) |
| disposition→policy | `_composition.py:105` `DispositionPolicy`, `:186` `compose_gate` | task selects `blocking`/`recording`; framework derives role/cadence/actions/`aggregation` |
| fact-parameter injection precedent | `_composition.py:243` `value_scale_parameters_for` (+ keys `:170`, `:179`) | declaration-driven: checks declaring the `value_scale_unit` axis receive the injected factor — **the mechanism Q-08c-1 proposes to mirror for cardinality** |
| declarations | `schemas.py:880` `CheckInputDeclaration` (`requires_view` `:899`), `:741` `FACT_AXES`, `:1000` `applicability` | one applicability authority; biconditional discipline (declare only what you consume) |
| D18 | `schemas.py:113` `PerSampleEvidence` | already landed; 08c adds nothing to it |
| bootstrap | `__init__.py:95` `_bootstrap_registry` (invoked `:120`) | the built-ins' convenience bootstrap — the generic checks join it; it is NOT the extension path (census-pinned) |

### 2.2 `FACT_AXES` already covers both new tasks — no axis growth

`FACT_AXES = {encoding_family, symbol_cardinality, value_scale_unit,
file_group_size, sampling_frequency_hz}` (`schemas.py:741`). Pets declares
`encoding_family` (a NEW opaque VALUE — values are open) plus
`symbol_cardinality=37` (the axis exists; `TaskHealthFacts` `:798` already
validates cardinality>1 and requires the family to accompany it). DAVIS
declares `encoding_family="continuous_float"` — the exact value the 8.4
rung corpus has used since 08a. **The parent's growth discipline holds with
zero new axes**: adding these tasks required no vocabulary growth, which is
itself evidence for §13.

### 2.3 The 8.4-C seed check and its own recorded 08c disposition

`sample_dispersion_floor.py` is the 08a negative control. Its docstring is
explicit about this PR: *"The full generic continuous family — a real view
provider, real artifact reads, task-owned thresholds — is 08c. Here the
samples arrive through the check's own config, because 08a has no
view-provider mechanism yet."* Its capability key is deliberately
fixture-spelled (`step08.fixture_continuous_samples`), its facts requirement
is `encoding_family == continuous_float`, threshold `min_dispersion`, and it
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
| preserved real artifact | Gate-2 corpora (08a/08b) | `predictions_pets_reference_cnn_d14p_pets_gate2_001.csv`, **6 812 bytes**, sha256 `cc8470267fbf5331827c7b641ac2ce8efb834b07441a31836084d4d417ff752c` — byte-identical in BOTH `/home/klz/Data/SIDEREIS_DATA/d14_pets_gate2_20260818{,b}/`; recorded in D14 `gate_evidence.json` | `predictions_davis_reference_predictor_d14d_davis_gate2_001.npz`, **17 874 045 bytes**, in `/home/klz/Data/SIDEREIS_DATA/d14_davis_gate2_20260818c/` (`gate_evidence.json`: mse `0.017289766656259548` — the D14 record value) |
| committability | n/a | **YES — this is the parent §9 "committed fixture-of-record (small, deterministic)"** | NO (17.9 MB) — real-npz evidence is Gate-2/runner + a skip-guarded machine-local test; in-repo unit fixtures are small synthetic arrays |

### 2.5 The REAL collapse, measured from the artifact (not from prose)

Computed directly from the preserved CSV at the anchor:

```text
rows = 370        distinct predicted classes = 2 (of 37)
dominant class   = 5, count 369  →  dominant fraction = 369/370 = 0.9972973
metric (D14 gate_evidence.json): accuracy = 0.02702702702702703 = exactly chance (10/370)
```

These are the hand-computable anchors the generic checks' tests pin (§4.2).

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
   369/370 = 0.9973 with 2 distinct classes (§2.5). The parent's scientific
   point survives intact — and is in fact sharpened: a dominance threshold
   must catch a NEAR-constant deliverable, not only an exactly-constant
   one, which is precisely why the check thresholds on a fraction rather
   than testing `distinct == 1`. Acceptance below uses the real numbers.
2. **Evidence-directory citations.** Parent §3.4 cites
   `d14_pets_gate2_20260818b/`; the D14 ledger cites `…20260818/`. The CSVs
   in both are byte-identical (one sha), so the fixture-of-record identity
   is unambiguous. The DAVIS npz lives in `…20260818c/` while the D14
   ledger cites `…818b/` (which preserves the evidence JSON, not the npz);
   the fresh C5/Gate-2 run supplies the live npz regardless.

### 2.8 What already auto-extends (verified, so 08c does not duplicate it)

* `test_check_declarations.py:173` (value-scale biconditional) and
  `test_per_sample_evidence.py` (no shipped check declares
  `per_sample_evidence`) iterate ALL registered checks — new checks are
  covered the moment they register, provided they declare correctly.
* `test_plugin_binding.py::BUILTIN_CHECK_NAMES` is a hardcoded 7-tuple —
  it does NOT auto-extend and is a planned test disposition (§5).
* The 08b out-of-tree proof (`test_out_of_tree_extension.py`) keeps passing
  untouched — the parent forbids re-proving it by walkthrough.
* The census precedent to extend is
  `tests/unit/guardrails/test_task_data_path_census.py` (AST-based,
  production roots, token discipline, anti-vacuity — its header states the
  pattern).

## 3. Design (proposed for freeze)

### 3.1 The two standard capabilities (framework-shipped payload contracts)

New public module `execute_tools/health_checks/standard_views.py`
(un-prefixed deliberately: like `schemas.py`, it is vocabulary that PACK
authors import — the 08b acme fixture already established that plugins
import the package's public surface):

```text
CATEGORICAL_PREDICTIONS = "categorical_predictions"     (parent §6.3 verbatim)
CONTINUOUS_SAMPLES      = "continuous_samples"

CategoricalPredictionsPayload   symbols: tuple[int, ...]     (the predicted
                                symbol/class multiset, order-irrelevant)
ContinuousSamplesPayload        samples: tuple[float, ...]
```

**Opacity is preserved.** The ENGINE still never inspects a payload —
`evaluate_gate`/`materialize_view` transport `HealthView` unchanged. A
standard capability differs from a plugin-local one in exactly one way: the
framework SHIPS the payload model and the consuming checks, so a task
binding a provider for the key gets the checks for free. The key strings are
declared ONCE here; growth of the STANDARD set requires a forcing task
(parent §13); plugin-local keys remain free.

Payload models validate SHAPE only (types, tuple-ness). Whether values are
*healthy* (finite, in-range) is check arithmetic, not transport validation —
see Q-08c-2 for where the integrity verdict lives and why `failed` (a
pathology statement) rather than `error` (could-not-compute) is proposed.

### 3.2 The generic collapse family — three checks, mechanisms from parent §3.2

Extracted mechanisms, NOT TIDMAD rewrites (§3.6):

| check (registered name) | consumes | threshold (task-owned) | arithmetic | verdict on the real Pets collapse |
|---|---|---|---|---|
| `categorical_distinct_symbols` | `categorical_predictions`, `requires_view=True` | `min_distinct_symbols` | count distinct symbols; occupancy = distinct/cardinality recorded as metric | distinct=2 → FAILED under any floor ≥3 |
| `categorical_dominant_fraction` | `categorical_predictions`, `requires_view=True` | `max_dominant_fraction` | max symbol count / n | 0.9973 → FAILED under a 0.95 ceiling |
| `sample_dispersion_floor` (UPGRADED in place) | `continuous_samples`, `requires_view=True` | `min_dispersion` (unchanged name) | population-std floor (existing hand-computed arithmetic kept) | n/a (continuous) |

Shared properties, each an acceptance criterion in §4.2:

* **Fail closed on emptiness** — an empty symbol/sample stream is
  `CheckVerdict.ERROR` (the existing `sample_dispersion_floor` discipline:
  absence of evidence is not evidence of health).
* **Integrity guards** (Q-08c-2 recommended shape): a non-finite continuous
  sample, or a categorical symbol outside `[0, cardinality)`, is a FAILED
  verdict with the offense named — the parent §3.2 "values finite/valid"
  generic baseline, block-capable, folded into the family checks.
* **No metric consumption** — no check reads `denoising_score`,
  `file_vector` or `.scalar` (the existing census iterates all registered
  checks and extends automatically).
* **No value-scale axis** — thresholds are in the view's native units (a
  task that declares no physical unit, like DAVIS, must not render the
  check inapplicable). The value-scale biconditional set stays exactly the
  four TIDMAD checks.

### 3.3 Cardinality reaches the categorical checks by declaration (Q-08c-1)

The categorical checks need `symbol_cardinality` (range validation +
occupancy). Recommended transport — mirror the landed value-scale
mechanism 1:1: the checks declare
`FactRequirement(axis="symbol_cardinality")`; composition injects the
declared value as check parameter `symbol_cardinality`
(generalizing `_composition.py:243`'s declaration-driven injection from its
value-scale-specific form). Single source (the task's facts), applicability
gates honestly (a task declaring no cardinality → categorical checks
inapplicable, axis named), and the biconditional discipline extends: a check
receives the parameter iff it declares the axis. The alternative
(cardinality inside the payload, provider-populated) is Q-08c-1's option B.

### 3.4 The Pets and DAVIS families (reference packs, the EXTERNAL interface)

Both bind through **state C** — an explicit task-health-config path — and
config-named pack plugins, i.e. exactly the route an external user takes
(parent: *"reference packs, never a privileged path"*). Proposed layout
(Q-08c-3):

```text
examples/oxford_iiit_pet/
  declared/task_health.yaml        facts: encoding_family=categorical_labels,
                                          symbol_cardinality=37
                                   plugins: [./../plugins/pets_health_views.py]  (ref
                                     relative to the config's own directory)
                                   providers: [pets.prediction_views]
                                   roster:
                                     pets_distinct_symbols_blocking   (min_distinct_symbols, blocking)
                                     pets_dominant_fraction_blocking  (max_dominant_fraction, blocking)
  plugins/pets_health_views.py     registers a provider exposing
                                   categorical_predictions by reading the
                                   pack's CSV deliverable at the ctx-supplied
                                   path (§3.5)
  expected/d14_gate2_collapse_predictions.csv
                                   the fixture-of-record — the REAL preserved
                                   CSV, committed byte-identical (sha
                                   cc8470… pinned by test)

examples/davis_future_prediction/
  declared/task_health.yaml        facts: encoding_family=continuous_float
                                   providers: [davis.sample_views]
                                   roster:
                                     davis_dispersion_blocking (min_dispersion, blocking)
  plugins/davis_health_views.py    provider exposing continuous_samples from
                                   the npz (deterministic flatten; provider
                                   config may cap the sample count
                                   deterministically)
```

Threshold VALUES are task-owned initial choices with provenance comments —
grounded against the real artifacts (Pets: dominance 0.9973 / distinct 2
must FAIL, a healthy 37-class spread must PASS; DAVIS: the floor is chosen
below the preserved healthy artifact's measured dispersion with the margin
recorded at implementation). **They are safety floors, not tuned science —
no threshold-tuning campaign is designed or run in this PR** (operator
rule).

The D14 invariant is untouched: production imports nothing from
`examples/`; the runners pass pack paths as DATA (established D14
practice), and the pack-governance guards continue to pass (`.py` only
under `plugins/`; the health YAML's top-level keys are not the forbidden
`task_description`/`forward_contract`).

### 3.5 The bounded real-artifact evaluation path (runner-pattern, the live half)

The provider learns WHERE the deliverable is from the context: the
harness/test builds `HealthCheckContext(denoised_paths={0: <deliverable>})`
and the pack provider reads `ctx.get_denoised_path(0)`. This reuses the
existing generic "produced artifact" slot — no schema change; its docstring
gains a sentence saying so. The Pets provider parses its own pack's CSV
format (header-checked, mirroring `pets_data_path.py:232`); drift between
the two readers is structurally caught because the committed
fixture-of-record WAS written by the production codec, so the provider is
permanently tested against the real writer's bytes.

Runner stage (Q-08c-4 recommended shape — extend the two D14 runners in
place, sharing one helper so the two cannot drift):

```text
after the metric stage:
  materialize_effective_config(source=None,            # policy-only framework file
                               files=None, workspace,
                               task_health_binding=<pack task_health.yaml>)   # EXPLICIT, state C
  → get_gates_for_position(1, config_path=<effective>)
  → evaluate_gate(gate_id, ctx(denoised_paths={0: deliverable}), config_path=<effective>)
  → persist {gate ids, check verdicts, actions, decisive metrics} into gate_evidence.json
```

The binding is NEVER omitted — an omitted binding now composes TIDMAD
(state A), which is exactly the cross-task hazard the 08b audit pinned. The
inverted guardrail (§4.5) makes that executable.

### 3.6 What TIDMAD does NOT do in 08c (parity, not unification)

TIDMAD's six checks, roster, thresholds, ids, actions, firing point and
verdicts are untouched; the 27-case verdict manifest and the composed
executed-semantics goldens must be byte-identical at every commit. The
parent's *optional* "TIDMAD MAY additionally expose its int8 stream as a
categorical view (≡ int8 parity)" is **deliberately not elected** —
"parity, not unification, is the Step-08 obligation" (§6.3), and touching
the golden instances to re-bind them through new checks is re-parameterization
risk with zero mandated payoff. If the operator elects it later, it is its
own evidence unit.

**The ordering-behaviour rule, adapted (08b precedent):** 08c's analogue of
a visited-sequence claim is the composed roster, the executed check
sequence, the verdicts and the persisted values — every parity criterion
below is written against those, never against composed config objects; and
the default (state-A TIDMAD) path's roster selection, executed sequence,
verdicts and persisted values must be proven unchanged at every commit.

## 4. Commit decomposition

### 4.0 Standing rules (operator standard, this PR)

* Each commit's first item is a bounded read of the exact functions it
  edits, at the implementation head. Ambiguity or larger scope than the
  design assumes → **STOP and ask before changing the plan**.
* `[ ]` = not done; `[x]` only with recorded evidence. **Every box below is
  `[ ]`.** Pytest verdicts from complete log files, never a wrapper's exit
  status.
* **Before each commit: STOP and show the exact diff summary, staged file
  list, tests run, and any deviations from the approved design.**
* **Real-training / real-artifact Gate runs are listed separately (§7) and
  are NOT launched without operator approval.**
* Planner/prompt exposure and production-default changes are OUTSIDE these
  commits; any such delta is a material deviation requiring separate
  evidence and operator approval.
* Threshold values are recorded safety floors with provenance — **no
  empirical threshold-comparison campaign is designed or run here**.
* TIDMAD parity (27-case manifest + composed goldens byte-identical) is
  re-verified at every commit; a moved byte is a STOP.
* Out of scope for all commits: Pets/DAVIS tuner integration, TIDMAD
  categorical-view re-binding, new `FACT_AXES`, Step 09, Step 10/12.

---

### 4.1 C1 — the standard view capabilities (vocabulary only)

**Goal.** `categorical_predictions` and `continuous_samples` exist as
framework-shipped, typed payload vocabulary — the parent §6.3 "standard
capabilities" — so that "what a standard view IS" is reviewable separately
from check arithmetic, and so pack/provider authors have one import for the
contract. This commit and no other defines the two key strings.

**Scope.** NEW `execute_tools/health_checks/standard_views.py` (two key
constants + two payload models, shape-validation only); `__init__.py`
exports. Deliberately UNREACHABLE from production (inert; grep-guard with
the 08a/08b anti-vacuity defences, INVERTED in C2). Must not change: any
check, `runner.py`, `_view_provider.py`, `_plugin_binding.py`,
`_composition.py`, any YAML, the engine's opacity (no engine code learns
the keys). Depends on: nothing.

**Implementation plan.**
- [ ] Re-read `_view_provider.py` and the 08b acme fixture's import surface
      at the head; confirm the public-import route pack plugins use.
- [ ] Define the two key constants with the parent §6.3 spellings, declared
      exactly once.
- [ ] Define `CategoricalPredictionsPayload` / `ContinuousSamplesPayload`
      (frozen models; shape validation only — integrity is check
      arithmetic per §3.2/Q-08c-2).
- [ ] Export via `__init__.py`; add the inertness grep-guard (root
      assertion, exit-code assertion, positive probe, `--untracked`).

**Validation plan.**
- [ ] Unit: construction with valid shapes; rejection of wrong types
      (non-int symbol, non-float sample, non-sequence payloads).
- [ ] Unit: the key strings equal the parent §6.3 spellings, hardcoded.
- [ ] Census: no engine module (`runner.py`, `_view_provider.py`,
      `_plugin_binding.py`) references the new keys — opacity preserved.
- [ ] Backward-compat: health package green; 27-case manifest
      byte-identical; inertness guard green and mutation-proven (a real
      production import turns it RED).

**Acceptance criteria.**
- [ ] The two capability-key strings exist in exactly ONE production
      module (grep census counts definitions).
- [ ] A payload model rejects each wrong-shape class at construction with
      the offender named.
- [ ] Engine opacity census green: zero references to either key outside
      `standard_views.py` (+ its tests).
- [ ] Inertness guard green and mutation-proven; manifest byte-identical.

**Failure and edge cases.** Empty `symbols`/`samples` tuples are ACCEPTED
by the payload (emptiness is a check-level ERROR, not a transport
rejection — a provider must be able to say honestly "I read the artifact
and it was empty"). Non-finite floats are ACCEPTED by the payload and
condemned by the check (Q-08c-2).

**Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/execute_tools/health_checks/ -q > /tmp/08c_c1.log 2>&1`
      Evidence: _(pending)_
- [ ] `ruff check` + `ruff format --check`. Evidence: _(pending)_
- [ ] `pyright` — CI-owned; recorded, never claimed locally.

**Commit boundary.** Vocabulary + tests only; no consumer; no check
changes; independently reviewable as "is this the right standard-view
contract?".

---

### 4.2 C2 — the generic collapse checks (hand-computed) + cardinality injection

**Goal.** The three generic checks exist with hand-computed arithmetic and
consume the standard views through the real 08b transport
(`requires_view=True`), and the categorical checks receive
`symbol_cardinality` by declaration. This is the "generic
categorical/continuous checks on views | UNIT (hand-computed)" row of the
parent §10 table.

**Scope.** NEW `categorical_distinct_symbols.py`,
`categorical_dominant_fraction.py`; UPGRADE `sample_dispersion_floor.py` in
place (consume `continuous_samples` via `view=`, `requires_view=True`,
retire the config-borne `samples` path its docstring called scaffolding);
`_composition.py` (generalize the declaration-driven fact-parameter
injection to `symbol_cardinality`, per Q-08c-1's resolution);
`__init__._bootstrap_registry` (+2). Must not change: the six TIDMAD
checks, `runner.py` semantics, any threshold value, any YAML. Depends on
C1. C1's inertness guard is INVERTED here (the checks are the first
consumers).

**Implementation plan.**
- [ ] Re-read `sample_dispersion_floor.py`, `test_step08_44_rungs.py` and
      `_composition.py:186-292` at the head; record the exact rung-test
      surfaces the upgrade touches and the injection insertion point.
- [ ] Implement the two categorical checks per §3.2 (declarations exact:
      `consumes_view=CATEGORICAL_PREDICTIONS`, `requires_view=True`,
      cardinality axis per Q-08c-1, `threshold_parameter_names` =
      exactly the one boundary key each).
- [ ] Upgrade `sample_dispersion_floor` to view consumption; keep name,
      threshold name, ERROR-on-empty and the hand-computed arithmetic.
- [ ] Implement the integrity guards (Q-08c-2 resolution): out-of-range
      symbol / non-finite sample → FAILED with the offense named.
- [ ] Generalize the fact-parameter injection; the value-scale behaviour
      must be provably unchanged (its tests + manifest).
- [ ] Register the two new checks in the bootstrap; update the
      `BUILTIN_CHECK_NAMES` 7-tuple (§5).

**Validation plan.**
- [ ] Unit, hand-computed anchors (expectations hardcoded, never derived
      from the implementation): dominant fraction of the REAL collapse
      distribution `{5: 369, other: 1}` = 369/370 = 0.9972973 → FAILED at
      ceiling 0.95; distinct=2 → FAILED at floor 5; a healthy spread
      PASSES both; dispersion √5 series kept from the existing suite.
- [ ] Negative: empty view → ERROR (never pass); out-of-range symbol →
      FAILED naming the symbol; NaN sample → FAILED naming it.
- [ ] Ordering/transport: an inapplicable categorical check (task declares
      no cardinality, under Q-08c-1-A) causes ZERO materialize calls (the
      08b spy shape); a view-consuming check receives the keyword-only
      `view`.
- [ ] Mutation: injection removed → the cardinality-consuming tests RED;
      integrity guard removed → the out-of-range test RED.
- [ ] Backward-compat/default-parity: 27-case manifest byte-identical;
      composed state-A goldens byte-identical; `test_check_declarations`
      biconditionals green over the grown registry (the new checks declare
      NO value-scale axis, NO `per_sample_evidence`);
      the new checks are registered but configured in NO shipped config
      (extend the `:150` pattern).

**Acceptance criteria.**
- [ ] Each check's declaration lists exactly its one threshold key; the
      value-scale biconditional set is still exactly the four TIDMAD
      checks.
- [ ] The real-collapse arithmetic anchors pass with hardcoded
      expectations (0.9972973; 2).
- [ ] `sample_dispersion_floor`'s config-borne `samples` path is GONE
      (grep census) and the 8.4-C property survives through the view path
      (§5 disposition executed, mutation-proven: reverting the upgrade
      fails the upgraded rung).
- [ ] Value-scale injection behaviour unchanged (its tests + manifest).
- [ ] Registry census: bootstrap registers exactly 9; no shipped config
      references any new check.

**Failure and edge cases.** A roster entry naming a categorical check while
the task declares no cardinality: Q-08c-1-A → `INAPPLICABLE` (axis named);
this must NOT be an error (a validly bound check whose facts are silent).
A blocking gate's injected `aggregation: any_pass` (DispositionPolicy) is
ignored by single-artifact checks — harmless, asserted so the assumption is
recorded. Provider raising mid-materialize stays `ERROR` (08b guard,
untouched).

**Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/execute_tools/health_checks/ -q > /tmp/08c_c2.log 2>&1`
      Evidence: _(pending)_
- [ ] Manifest `--check` byte-identical. Evidence: _(pending)_
- [ ] `ruff` clean; `pyright` CI-owned. Evidence: _(pending)_

**Commit boundary.** Generic family + injection only; no pack content; no
runner change; TIDMAD untouched.

---

### 4.3 C3 — the Pets family + the committed collapse fixture-of-record

**Goal.** Pets binds a real health family through the external interface,
and the framework detects the REAL D14 collapse: parent §14.B — *"the
framework can now SAY what D14 could only observe."*

**Scope.** NEW `examples/oxford_iiit_pet/declared/task_health.yaml`; NEW
`examples/oxford_iiit_pet/plugins/pets_health_views.py`; NEW committed
fixture `examples/oxford_iiit_pet/expected/d14_gate2_collapse_predictions.csv`
(byte-identical copy, sha pinned); pack `STATUS.md`/`PROVENANCE.md` rows;
NEW test module. Must not change: any framework module, any shipped config,
`pets_data_path.py`, the runners (C5's job). Depends on C1–C2.

**Implementation plan.**
- [ ] Re-read the pack governance guards and `_task_health_config.py`
      constraints at the head (plugin refs relative to the config's own
      directory — confirm `../plugins/…` resolves, or place the config
      accordingly); STOP if the layout fights a governance guard.
- [ ] Author the family per §3.4 with provenance comments on both
      thresholds (grounded on §2.5's real numbers; floors, not tuning).
- [ ] Implement the provider plugin: registers `pets.prediction_views`
      exposing `CATEGORICAL_PREDICTIONS` from the CSV at
      `ctx.get_denoised_path(0)` (header-checked parse mirroring
      `pets_data_path.py:232`).
- [ ] Commit the fixture-of-record byte-identical; pin sha
      `cc8470267fbf…f752c` and size 6 812 in the test.
- [ ] Evidence tests: full state-C chain on the fixture (compose → load →
      resolve → materialize → evaluate) → `categorical_dominant_fraction`
      FAILED with `dominant_fraction == 369/370` persisted,
      `categorical_distinct_symbols` FAILED with `distinct == 2`, gate
      action `invalidate_round`; counterfactual healthy CSV → both PASS.
- [ ] TIDMAD's int8 checks under Pets' DECLARED facts → `inapplicable`
      (the 8.4-B rung, now with a real task's declaration).

**Validation plan.**
- [ ] Unit as above, plus: provider round-trip against the fixture proves
      reader compatibility with the production writer's bytes; broken CSV
      header → provider raises → `CheckVerdict.ERROR` (never a pass);
      missing deliverable path → ERROR.
- [ ] Negative (fail-closed pair, 08b idiom): pack config with the plugin
      file removed → `HealthPluginError`; plugin present but the roster
      naming an unregistered check → `HealthBindingError`.
- [ ] Census: `37` and every pack identifier appear in the PACK + its
      tests only, never in generic health core.
- [ ] Backward-compat: EXPLICIT_NONE and state-A regressions untouched;
      manifest byte-identical; pack-governance suite green.

**Acceptance criteria.**
- [ ] The committed fixture's sha256 equals `cc8470267fbf5331827c7b641ac2ce8efb834b07441a31836084d4d417ff752c`
      (asserted by test, so the fixture-of-record cannot silently drift).
- [ ] On that fixture, the blocking gates FAIL with the dominant-fraction
      evidence (0.9972973) and distinct-count (2) PERSISTED in the results
      — the parent §12 acceptance verbatim, with the corrected number.
- [ ] The healthy counterfactual passes — without it, an always-failing
      family satisfies the collapse test.
- [ ] Every Pets identifier is absent from production source (id census,
      C7-08b pattern).

**Failure and edge cases.** CSV with unknown image ids: irrelevant to
health (the checks see symbols only) — recorded, not guarded. Symbols
outside `[0, 37)`: integrity FAILED (C2 guard). An operator hand-editing
the pack thresholds: caught by nothing here by design — thresholds are
task-owned; only the fixture EVIDENCE values are pinned.

**Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/execute_tools/health_checks/ tests/unit/examples/ -q > /tmp/08c_c3.log 2>&1`
      Evidence: _(pending)_

**Commit boundary.** Pets content only; DAVIS is C4; runners untouched.

---

### 4.4 C4 — the DAVIS family

**Goal.** A dense-continuous task binds the same machinery with no TIDMAD
or classification assumption (parent §14.C), through the identical external
interface.

**Scope.** NEW `examples/davis_future_prediction/declared/task_health.yaml`;
NEW `examples/davis_future_prediction/plugins/davis_health_views.py`; pack
docs rows; NEW test module (synthetic in-repo fixtures; one skip-guarded
machine-local test over the preserved npz, declared per the CLAUDE.md
portability rules). Must not change: framework modules, shipped configs,
`davis_data_path.py`, runners. Depends on C1–C2 (not C3).

**Implementation plan.**
- [ ] Re-read `davis_data_path.py:310-340` at the head; record the npz
      payload shape the provider decodes.
- [ ] Implement the provider: `davis.sample_views` exposing
      `CONTINUOUS_SAMPLES` from the npz at `ctx.get_denoised_path(0)` —
      deterministic flatten across sorted clip keys; provider config may
      cap the count DETERMINISTICALLY (a prefix, never a random sample).
- [ ] Author the family: facts `continuous_float`;
      `davis_dispersion_blocking` with `min_dispersion` chosen BELOW the
      preserved artifact's measured dispersion with the margin computed
      and recorded in the provenance comment (one bounded measurement of
      the existing artifact — not a campaign).
- [ ] Evidence tests: synthetic near-constant npz → FAILED; synthetic
      varied npz (hand-computed dispersion) → PASSED; skip-guarded test
      over `/home/klz/.../d14_davis_gate2_20260818c/…npz` → PASSED with
      the measured dispersion recorded (skips with the declared reason
      when the machine-local artifact is absent).
- [ ] TIDMAD's int8 checks inapplicable under DAVIS' declared facts.

**Validation plan.**
- [ ] Unit as above; negative: corrupt/missing npz → ERROR; NaN frames →
      FAILED (integrity guard); fail-closed plugin/binding pair as C3.
- [ ] Census: DAVIS identifiers absent from production source; no new
      `FACT_AXES`.
- [ ] Backward-compat: manifest byte-identical; C3's Pets evidence
      untouched-green (families are independent).

**Acceptance criteria.**
- [ ] Verdicts flow through the SAME engine path as Pets with zero
      task-name knowledge (id census + the shared-machinery imports being
      the only framework surface touched — i.e., none).
- [ ] The synthetic pair is decisive (one FAILED, one PASSED, hand-computed
      expectations hardcoded).
- [ ] The skip-guarded real-npz test passes on this machine and skips
      honestly elsewhere (never claimed as run when skipped).

**Failure and edge cases.** Clip tensors of unequal shape: provider raises
→ ERROR (a malformed deliverable is not health evidence). Empty npz
(`{}` from the reader's missing-file contract) → empty samples → ERROR.

**Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/execute_tools/health_checks/ tests/unit/examples/ -q > /tmp/08c_c4.log 2>&1`
      Evidence: _(pending)_

**Commit boundary.** DAVIS content only.

---

### 4.5 C5 — the runner-pattern evaluation stage + guardrail inversion

**Goal.** The bounded real-artifact evaluation path exists (parent "Allowed
changes" verbatim): both D14 runners evaluate their pack's health family on
the fresh real deliverable with an EXPLICIT state-C binding, persisting
verdicts into `gate_evidence.json`. **This is the final
production-surface commit — the Gate-2 head.**

**Scope.** `scripts/run_pets_gate2.py`, `scripts/run_davis_gate2.py`
(+ one shared stage helper so the two runners cannot drift — location
resolved per Q-08c-4, e.g. `scripts/_gate2_health_stage.py`); UPGRADE of
`tests/unit/guardrails/test_step08b_cross_task_compatibility.py::`
`TestNeitherExistingTaskCanReachTheTidmadFallback` (§2.6). Must not change:
the runners' training/inference/metric stages, any framework module, any
pack family content. Depends on C3–C4.

**Implementation plan.**
- [ ] Re-read both runners end-to-end at the head; record the exact
      insertion point after the metric stage and the evidence-JSON shape.
- [ ] Implement the shared stage per §3.5: materialize with
      `task_health_binding=<pack config>` (EXPLICIT — never omitted),
      evaluate round-1 gates, persist gate ids / check verdicts / actions
      / decisive metrics.
- [ ] Define each runner's PASS semantics for the health block and print
      it: the stage ran, the family's gates evaluated, verdicts persisted
      (a collapse-detecting FAILED verdict on a collapsed deliverable is
      the stage WORKING).
- [ ] INVERT the guardrail: from "never enters Health composition" to
      "enters composition ONLY through the shared stage with an explicit
      pack binding; an OMITTED binding (which would compose TIDMAD) is
      census-refused" — keep the anti-vacuity probe; KEEP the sibling
      classes unchanged.

**Validation plan.**
- [ ] Unit on the shared stage with a tmp deliverable + tmp pack config:
      explicit binding threaded; verdicts persisted; an omitted-binding
      call shape does not exist (AST/text census).
- [ ] Mutation: omitting the binding in the stage → the inverted guardrail
      RED (this is the cross-task hazard made executable).
- [ ] NO real run in this commit's validation — the live half is Gate 2
      (§7), operator-approved.

**Acceptance criteria.**
- [ ] Both runners share ONE stage implementation (census: no second
      composition/evaluation code path in `scripts/`).
- [ ] The inverted guardrail is RED under the omitted-binding mutation and
      green at the commit head.
- [ ] `gate_evidence.json` schema addition documented in the runner
      docstrings (doc-sync rule).

**Failure and edge cases.** Pack config path missing → the stage fails
LOUDLY before evaluation (never silently skips health — a runner that
quietly dropped its health stage would report D14-era evidence as if it
were 08c evidence). Deliverable absent → provider ERROR path (asserted in
C3/C4).

**Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/guardrails/ tests/unit/execute_tools/health_checks/ -q > /tmp/08c_c5.log 2>&1`
      Evidence: _(pending)_

**Commit boundary.** Runner stage + guardrail inversion only. Gate 2 (§7)
runs at THIS head after operator approval.

---

### 4.6 C6 — milestone census + three-task evidence + docs (test/docs ONLY)

**Goal.** Parent §13's health-core census (including the strengthened
structural items) becomes executable; the three-task milestone claim is one
test; documentation synchronized. **No production behaviour change** — the
Gate-2 evidence at the C5 head must still cover the final state.

**Scope.** NEW health-core census module under `tests/unit/guardrails/`
(extending the `test_task_data_path_census.py` AST pattern); a three-task
composition rung; docs: `docs/design/pluggable_health_checks.md` (standard
capabilities + generic family section), both pack `STATUS.md` 08c rows,
this document's ledger. Roadmap/parent/CLAUDE.md status = post-merge
bookkeeping, not PR content. Depends on C1–C5.

**Implementation plan.**
- [ ] Census over the enumerated GENERIC health modules (list them; the
      TIDMAD-family check modules are excluded BY NAME as task-owned):
      zero `tidmad|pet|davis` comparisons; zero `examples` imports; no
      `37`; no int8/channel/mV literals; no closed view-kind
      enum/dispatch; no metric-scalar reads; no central task
      roster/mapping; registration requires no central import edit
      (08b's proof re-asserted structurally, not re-proven).
- [ ] Three-task rung: compose TIDMAD (state A), Pets (state C), DAVIS
      (state C) in one test module — `reset_run_scope` between, per the
      08b run-scope semantics — asserting the three rosters are disjoint,
      generic checks fire for B/C, int8 checks inapplicable under B/C
      facts, and state A byte-stable.
- [ ] Map parent §14 A–H to evidence in this document's ledger.
- [ ] Docs sync last, quoting each documented behaviour against merged
      source (node/skill doc-sync rule).

**Validation plan.**
- [ ] The census is anti-vacuous (planted-offender probes, the C7-08b
      pattern).
- [ ] Full health package + guardrails + examples targeted suites.
- [ ] `git diff` of this commit shows tests/docs only (asserted in the
      ledger, so Gate-2 coverage of the final executable state is a
      recorded fact, not an assumption).

**Acceptance criteria.**
- [ ] Every §13 strengthened item is one executable assertion with a
      planted-offender probe.
- [ ] The three-task rung passes; the §14 A–H table in the ledger cites
      per-item evidence.
- [ ] Zero production-source bytes changed by this commit.

**Failure and edge cases.** A census pattern that would fire on the
TIDMAD-owned check modules: they are excluded by an explicit LISTED set
with a comment, so the census cannot silently widen or narrow.

**Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/execute_tools/health_checks/ tests/unit/guardrails/ tests/unit/examples/ -q > /tmp/08c_c6.log 2>&1`
      Evidence: _(pending)_

**Commit boundary.** Census + rung + docs; no Gate; no production change.

## 5. Test disposition (named in advance, executed at the owning commit)

| existing surface | disposition | commit |
|---|---|---|
| `test_step08_44_rungs.py` dispersion arithmetic + rungs B/C | **UPGRADE** — samples arrive through a real provider/view instead of check config; every hand-computed expectation and the 8.4-C claim (a generic check FIRES and FAILS where int8 is inapplicable) preserved, now via the real transport; mutation: reverting the check upgrade fails the upgraded rung | C2 |
| `test_plugin_binding.py::BUILTIN_CHECK_NAMES` (hardcoded 7-tuple) | **UPGRADE** to 9 — the tuple is deliberately hardcoded (its docstring: read-back would compare the registry to itself) | C2 |
| `test_check_declarations.py` biconditionals; `test_per_sample_evidence.py` census; metric-scalar census | **KEEP** — iterate all registered checks; new checks covered automatically | C2 |
| rung `:150` "registered but configured nowhere in production" | **EXTEND** to the two new checks | C2 |
| `test_step08b_cross_task_compatibility.py::TestNeitherExistingTaskCanReachTheTidmadFallback` | **INVERT** (never delete): runners enter composition ONLY with an explicit pack binding; omitted-binding shape census-refused; anti-vacuity probe kept | C5 |
| its sibling classes (EXPLICIT_NONE, D18 real metrics, no-task-name-branch) | **KEEP** unchanged | — |
| 08b out-of-tree proof; 27-case manifest; composed goldens; pack-governance guards | **KEEP** — byte-identical / green at every commit | all |

## 6. Evidence economy

Targeted per-commit suites (health package; + `tests/unit/examples/` at
C3/C4/C6; + `tests/unit/guardrails/` at C5/C6). No local full suite; no
manual CI dispatch; ONE canonical exact-head CI on the formal PR. Gate 2 is
not duplicate CI — it owns the real-artifact lifecycle no fixture can.

## 7. Gates

**Gate 1 — NOT REQUIRED.** No prompt/PB delta is elected; health stays
counts + named absence + stable ids in every LLM-facing surface. Any
accidental delta is a MATERIAL deviation → stop for operator
re-disposition.

**Gate 2 — TWO bounded real-artifact evaluations at the C5 head
(parent-mandated), and per the operator's rule for this PR they are NOT
launched without explicit operator approval.** Specification is written
into §10 before the approval request; classification is
PASS/FAIL/INCONCLUSIVE from persisted semantic evidence, never exit code.

* **Pets run** (`run_pets_gate2.py`, D14 bounds: 370/74/370 images,
  2 epochs, ≤10 min): must show startup composition from the PACK config
  (state C, `task_health_binding` explicit in the evidence), plugin
  load/resolve of the pack provider, the family's gates evaluated on the
  FRESH deliverable, verdicts + dominant-fraction/distinct metrics
  persisted. The reference CNN's 2-epoch collapse behaviour is expected to
  recur — a FAILED dominance verdict on a genuinely collapsed fresh
  deliverable is the framework working (the D14-observed pathology now
  NAMED); if the fresh deliverable happens to be healthy, PASSED verdicts
  with persisted evidence are equally a Gate PASS. INCONCLUSIVE = the
  stage never ran / training or inference failed before it.
* **DAVIS run** (`run_davis_gate2.py`, D14 bounds: 60/15/15 clips, ≤10
  min): same lifecycle claims over the continuous family; expected PASSED
  dispersion verdict with the measured value persisted.
* Combined expected wall time ≤ ~20 min + the existing D14 training costs;
  evidence preserved under `/home/klz/Data/SIDEREIS_DATA/` alongside the
  D14 corpora.

**TIDMAD**: no new Gate — §12 08c assigns TIDMAD's 08c evidence to the
goldens ("TIDMAD untouched"), re-verified at every commit; the parent §10
row's "unchanged behaviour re-shown" is satisfied by the byte-identical
manifest + composed goldens unless the operator elects a live re-run at
freeze.

## 8. Open questions (operator input required at freeze)

| id | question | options | recommendation |
|---|---|---|---|
| **Q-08c-1** | How does `symbol_cardinality` reach the categorical checks? | **A**: facts axis + declaration-driven injection (mirror the landed value-scale mechanism `_composition.py:243`; single source; honest inapplicability when undeclared). **B**: provider-populated payload field (matches §6.3's "stream + declared cardinality" phrasing literally; no composition change; but a second home for the number beside the facts). | **A** — reuses landed machinery, keeps one source of truth, extends the biconditional discipline; §6.3's phrasing is read as the capability's *description*, not its struct. |
| **Q-08c-2** | Where does the §3.2 "values finite/valid" universal baseline live? | **A**: integrity guards inside the family checks (out-of-range symbol / non-finite sample → FAILED with the offense named). **B**: separate per-capability baseline checks (literal reading of parent §4's "tiny universal baseline" as checks; more persisted names, more roster entries per task). | **A** — same block-capable verdicts, no check proliferation, and `failed` (pathology statement) is the honest verdict where `error` (could-not-compute) would be wrong. |
| **Q-08c-3** | Where do the Pets/DAVIS health configs + the collapse fixture-of-record live? | **A**: in the packs (`declared/task_health.yaml`, `expected/…csv`) — "packs declare config" verbatim; state-C explicit path = the true external interface; D14 zero-production-dependency preserved. **B**: `configs/task_health/{pets,davis}.yaml` + `tests/.../goldens/` — beside TIDMAD's; but TIDMAD's location is load-bearing ONLY because state A defaults to it, which is false for B/C, and it would blur "reference pack" into "shipped default". | **A**. |
| **Q-08c-4** | Runner integration shape? | **A**: extend `run_{pets,davis}_gate2.py` in place with ONE shared stage helper ("runner-pattern" per the parent; the evidence JSON stays one file per run). **B**: a separate evaluation-only runner over preserved artifacts (cheaper re-runs, but splits the evidence trail and does not exercise the fresh-artifact live half §9 L2 requires). | **A**, with the shared helper so two runners cannot drift. |

## 9. Risks

* **R-08c-1 — threshold values become accidental science.** The pack
  thresholds are floors with recorded provenance, not tuned results; the
  no-campaign rule is in §4.0, and the healthy/collapsed counterfactual
  pairs are what keep a wrong floor from passing silently.
* **R-08c-2 — the guardrail inversion weakens the cross-task protection.**
  Mitigated by the mutation requirement (omitted binding → RED) and by
  keeping EXPLICIT_NONE's own regression untouched.
* **R-08c-3 — census scope creep or blindness.** The generic-module list is
  explicit and the TIDMAD-owned exclusions are LISTED; every pattern
  carries a planted-offender probe.
* **R-08c-4 — the upgraded `sample_dispersion_floor` breaks the 8.4-C
  historical claim.** The rung is upgraded WITH the check in one commit and
  the claim re-proven through the real transport; the pre-upgrade
  arithmetic anchors are kept verbatim.
* **R-08c-5 — run-scope ledger friction in multi-family tests.** Three
  families in one process is a test-only situation; `reset_run_scope`
  between compositions is the established 08b idiom and is noted in C6.

## 10. Ledger

*(filled per commit during implementation; the §14 A–H completion table
lands here at C6)*
