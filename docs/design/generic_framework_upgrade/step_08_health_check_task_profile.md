# Step 08 — Health genericity: task-declared health families on a task-identity-free engine (parent design)

## 0. Status and provenance

**DRAFT rev 2 — READY FOR OPERATOR REVIEW (2026-08-18).** Supersedes the
PREMATURE rev-1 draft (`0b2a7884`, reverted by `7f650971` — scratch only,
never reviewed, never frozen). Every rev-1 assumption was re-checked against
the MERGED D14 state; §3.4 lists the ones D14 refuted. Authority order:
current source (audited at `baa77ad1`) > merged D14 implementation/evidence
> roadmap (`siderius_generic_framework_upgrade.md` §8, §8.4/§8.4a, §15.1 §8
row, §22.11a, §22.12) > merged Step-06/07 contracts > the scratch draft.

This is a PARENT design: scope, ownership, acceptance, validation and PR
decomposition. Per-commit implementation plans belong to the child designs
(§11 concludes MULTI-PR, so this document deliberately stops above that
level).

## 1. The core problem

The HealthGate machinery is generic; its HEALTH SEMANTICS are TIDMAD
end-to-end, and its "not applicable" vocabulary is dishonest:

* All six shipped checks assume the TIDMAD deliverable: the peek walk
  hardcodes `timeseries/channel0001/timeseries` + int8
  (`_peek.py`), thresholds are millivolts and int8-vocabulary counts
  inside the FRAMEWORK config (`configs/health_checks.yaml`), and
  `spectral_peak_ratio` is injected-frequency physics.
* The protocol's own docstring defines inapplicability as
  `passed=True, reason="not applicable — …"` (`protocol.py:22-31`) —
  **not-applicable IS pass** today, indistinguishable from a genuine pass
  in every aggregate, record and prompt-rendered count.
* A second task cannot bind health behaviour without editing TIDMAD's
  framework YAML, and the checks could not read its deliverable anyway
  (Pets ships a CSV, DAVIS an npz — no channel0001 exists).

D14 makes this concrete: three materially different tasks now execute for
real, and one of them produced a REAL health event — the Pets bounded run
collapsed to a constant prediction (accuracy 0.027 = 1/37 exactly) while
every execution stage PASSED. Execution correctness ≠ model health, from a
real run. Step 08 must make the framework able to SAY that, for any bound
task, without knowing the task's name.

## 2. Current source census (audited at `baa77ad1`, post-D14)

### 2.1 The machinery (generic — keep)

`execute_tools/health_checks/`: `registry.py` (flat name→skill, duplicate
refusal) · `runner.py` (gate selection by position) · `evaluation.py`
(`evaluate_and_persist_health_gates`: per-gate execution status, threshold
provenance, `would_invalidate_under_production_policy`, persistence) ·
`candidate_eligibility.py` (`classify_candidate_health` →
`VALID / INVALID / UNKNOWN`; UNKNOWN is already disciplined as
"evidence incomplete", NOT a soft invalid — `feedback.py:155-165` names
absent evidence instead of counting it as pass) · `launch_policy.py` ·
gate actions + severity `SKIP_ITER > SKIP_TO_FORMAL > INVALIDATE_ROUND >
CONTINUE` (CLAUDE.md-frozen) · `--healthgate_mode` enforce/observe (V20
PR D) · firing point `execution.py:955` at tuner round boundaries, ctx
carries `file_vector`, `denoised_filename_fn`, `target_path_fn`,
`denoising_score`.

### 2.2 The checks (TIDMAD — classify, §4)

Three BLOCKING (`output_diversity` ≥25 unique int8 · `output_std` ≥1.0 mV ·
`amplitude_collapse` dominant fraction <0.95), three RECORDING
(`pearson_dispersion` · `spectral_peak_ratio` · `per_file_output_std`).
All six peek the TIDMAD deliverable directly (a second reader beside the
D14 codec). Group indirection ALREADY landed (02c):
`peek_file_indices: task_health_peek` resolves from
`DatasetProfile.health_peek_files` ([3,10,17]), separate from
`anchor_selection_files`; `spectral_peak_ratio` already reads the profile
for `sampling_frequency` — the partial migration to complete.

### 2.3 Hard boundaries (unchanged by Step 08)

* `core/run_invariants.py:475-488` REFUSES a changed effective-config sha
  against an existing workspace → any content change lands at a
  fresh-workspace boundary between campaigns. Both the sha-pin MECHANISM
  and this refusal are untouched.
* `score_vector` never returns health data (frozen since commit-5a).
* Gate IDs and check IDs are referenced by records and by the
  interpreter's fingerprint prose
  (`result_interpretation_agent.py:171` — `output_diversity_blocking:…`);
  IDs stay stable.

### 2.4 LLM-facing surfaces today (Gate-1 relevance)

Health reaches prompts only as (a) validity COUNTS + named-absence lines in
trial-validity feedback (`feedback.py:145-175`) and (b) interpreter
fingerprints naming check IDs. No raw check metrics are prompt-rendered.
Step 08's default keeps it that way (§10).

### 2.5 God-file check (§17 of the kickoff)

No health god-file today: largest are `config.py` (514) and `schemas.py`
(434), each single-responsibility. `evaluation.py` (279) mixes evaluation
with persistence — acceptable now, RECORDED as the watch item: 08b touches
config composition and must not push `config.py` past one responsibility;
if it would, the child extracts `composition.py` first (the CLAUDE.md
decomposition rule), never as a side effect.

## 3. The D14 evidence that constrains this design

### 3.1 Three real tasks, three real output semantics

| | TIDMAD | Pets | DAVIS |
|---|---|---|---|
| deliverable | per-file HDF5, int8 stream | ONE CSV `{image_id: class}` | ONE npz `{clip: float32 [3,4,128,224]}` |
| output semantics | **per-sample 256-way categorical** (argmax of `[B,256,T]` logits → int8 symbols) | per-image 37-way categorical | dense continuous tensor |
| real health event | mode collapse observed for years (the gates' raison d'être); D14 gate pair reproduced `failed_mode_collapse` | **constant-prediction collapse observed at D14** (dominant class fraction = 1.0; 10/370 correct = exactly chance) | healthy-ish: beat the last-frame-copy baseline (0.017290 < 0.017392) |

The middle row is the load-bearing discovery: **TIDMAD's blocking checks
are already categorical-collapse checks** — unique-symbol count, dominant-
symbol fraction, dispersion floor — expressed in int8/mV vocabulary. The
same three mechanisms, parameterized differently, describe the OBSERVED
Pets collapse (37 symbols, dominant fraction 1.0, occupancy 1) and the
DAVIS analogue (per-tensor dispersion). The generic family is not invented;
it is extracted.

### 3.2 The three-column reasoning table (kickoff §3), per concept

| concept | TIDMAD | Pets | DAVIS | verdict |
|---|---|---|---|---|
| view materializes + values finite | meaningful (h5 readable, int8) | meaningful (CSV parses, classes in range) | meaningful (npz loads, floats finite) | **GENERIC BASELINE** (block-capable) |
| distinct-symbol count / occupancy | unique int8 ≥25 | distinct predicted classes (collapse ⇒ 1 of 37) | n/a (continuous) | **generic mechanism over a declared CATEGORICAL view**; thresholds task-owned |
| dominant-symbol fraction | ≥0.95 blocking | THE observed collapse (1.0) | n/a | same |
| dispersion floor | std ≥1.0 mV | n/a (no continuous output) | per-tensor / cross-clip std (all-identical predictions ⇒ 0) | **generic mechanism over a declared CONTINUOUS view**; scale+threshold task-owned |
| output↔target correlation dispersion | physics-adjacent, file-structured, recording | not meaningful as-is | conceivable but different structure | **TIDMAD-owned family** (recording) |
| injected-frequency PSD ratio | pure TIDMAD physics | no | no | **TIDMAD-owned family** (recording) |
| per-file std breakdown | TIDMAD file vocabulary | no files | clips, not files | **TIDMAD-owned family** (recording) |

Blocking-vs-recording and every numeric threshold: task-declared, always.

### 3.3 What Pets/DAVIS force (they are inputs, not decorations)

1. **Applicability cannot compare against `DatasetProfile` /
   `DeliverableSpec` for B/C** — D14 pinned both as "NOT representable"
   for those tasks. So the comparison is *check-declared requirements vs
   task-declared health facts*: regime-A (TIDMAD, no declaration) derives
   its facts from profile + deliverable contract; a bound task declares
   its own. Presence-discriminated, never name-discriminated — the exact
   D14 truth-table pattern.
2. **Health must read deliverables through task-owned readers.** The
   generic engine cannot open a CSV, an npz and an h5 with one walk. The
   task's health binding supplies typed VIEWS of its artifacts (a
   categorical-prediction view; a continuous-samples view); TIDMAD's view
   provider is its existing peek plumbing routed through the Deliverable
   Contract (byte-identical reads).
3. **B/C health evidence is engine-level, not tuner-level, in Step 08.**
   Gates fire at tuner round boundaries, and Pets/DAVIS do not run through
   the tuner until Steps 10/12. Step 08's real B/C evidence therefore uses
   the D14 bounded-runner pattern over REAL artifacts; TIDMAD keeps the
   production firing-point evidence. Claiming tuner-integrated Pets health
   would be maturity inflation.

### 3.4 Rev-1 scratch assumptions refuted or superseded by D14

* "No real deliverable exists before D14 / L2 is a deferred obligation" →
  real artifacts exist; real-artifact evidence is now REQUIRED milestone
  scope (§14), including the preserved Pets collapse artifact
  (`/home/klz/Data/SIDEREIS_DATA/d14_pets_gate2_20260818b/`).
* "Deliverable facts come from the Deliverable Contract" (as the universal
  comparison surface) → true only for regime-A/TIDMAD; B/C facts come from
  the task's health declaration (§3.3.1).
* The 2-PR split → re-decided as 3 PRs (§11): the contrast-track surface
  became live implementable scope with its own blast radius.

## 4. Classification of the current checks (kickoff §2, derived not assumed)

| check | class | disposition |
|---|---|---|
| `output_diversity` | **B** — generic distinct-symbol mechanism; int8 vocabulary + threshold 25 + peek scale are TIDMAD parameterization | mechanism extracted to the generic categorical family; TIDMAD binds it with current values; verdict parity pinned |
| `output_std` | **B** — generic dispersion-floor mechanism; mV scale + 1.0 threshold TIDMAD | same, continuous family |
| `amplitude_collapse` | **B** — generic dominant-fraction mechanism; 0.95 TIDMAD-declared | same, categorical family; the mechanism that names the Pets collapse |
| `pearson_dispersion` | **C + D** — TIDMAD-owned recording (output↔target correlation dispersion over TIDMAD's file structure) | stays in the TIDMAD family, recording-only, relocated ownership not rewritten |
| `spectral_peak_ratio` | **C + D** — TIDMAD physics | same |
| `per_file_output_std` | **C + D** — TIDMAD file-structure diagnostics | same |
| `passed=True` "not applicable" convention | **E** — superseded | replaced by the `inapplicable` verdict (§7); the rev-6 docstring is amended citing this design |
| `_peek` hardcoded h5 walk | **E** as a generic mechanism | becomes TIDMAD-family plumbing routed through the Deliverable Contract; byte-identical reads |

Nothing current lands in pure class A; the only NEW class-A (generic-by-
semantics) checks Step 08 introduces are the tiny universal baseline —
*declared view materializes* and *values finite* — which every task gets
and which may block.

## 5. Semantic ownership — what Health owns and does not own

```text
Health OWNS      validity/pathology evidence computed FROM produced outputs
                 (deliverable-side), plus its blocking/recording policy and
                 persisted gate evidence.

Health does NOT own
  shape/dtype legality of model I/O ......... ModelIOContract (Step 03)
  whether a deliverable is scoreable ........ ScoreabilityContract (Step 06)
  the golden/secondary metric value ......... EvaluationMetric (Step 06)
  training/validation curves + diagnosis .... TrainingHistory/-Diagnosis (Step 07)
  how bytes become samples/deliverables ..... TaskDataPath (D14)
```

The independent failure class that justifies Health beside the metric,
demonstrated by D14: Pets' metric said "0.027, finite, scoreable" — a
number, not a verdict; Health's job is the *pattern statement* "the
deliverable is a constant prediction", which exists even when no metric is
computable and is NOT derivable from the scalar (a bad-but-varied model
scores low without collapsing). Conversely DAVIS shows a modest metric with
no pathology. Health never reads a metric verdict; a metric never reads a
gate's. `HealthCheckContext`'s existing `denoising_score`/`file_vector`
fields are compatibility inputs for TIDMAD's current checks, not a licence
— **no NEW check may consume the golden metric scalar** (guardrail §13).

## 6. The minimal generic abstraction (proposed)

One sentence: **a task binds a HEALTH FAMILY — a declared roster of checks
with task-owned parameters and dispositions, plus a task-owned VIEW
PROVIDER that turns its real artifacts into a tiny typed view vocabulary —
and the generic engine evaluates, aggregates and persists verdicts without
knowing the task.**

Components, smallest that the three real tasks force:

1. **Check input declaration** (data, on every check): which view kind it
   consumes (`categorical_predictions` | `continuous_samples` | a
   TIDMAD-family task view), which declared facts it requires (e.g.
   symbol cardinality, value scale, file group), and which parameter names
   are task thresholds.
2. **Applicability verdict**: requirements compared against the bound
   task's declared health facts BEFORE any I/O →
   `applicable | inapplicable(reason names the mismatched axis)`.
   Regime-A derives TIDMAD's facts from profile + Deliverable Contract
   (presence-discriminated, D14 pattern).
3. **View vocabulary** (deliberately two kinds + task-opaque views):
   `categorical_predictions` (finite symbol stream + declared cardinality)
   and `continuous_samples` (float stream + declared scale). TIDMAD's six
   consume TIDMAD-family views (its peeks); TIDMAD MAY additionally expose
   its int8 stream as a categorical view (it is one), but parity, not
   unification, is the Step-08 obligation. A third view kind requires a
   fourth task to force it — not invented now.
4. **Task health binding**: family roster + parameters + dispositions
   (blocking/recording) as task-owned CONFIG DATA; the view provider as
   task-owned CODE, registry-bound like `TaskDataPath` (capability-keyed,
   fail-closed on absent/unknown binding for an explicitly-bound task;
   regime-A resolves TIDMAD). Composed with framework gate POLICY into the
   same single pinned `health_checks_effective.yaml` — mechanism untouched.
5. **Generic engine** (existing, kept): runner, gate actions, severity,
   enforce/observe mode, persistence, eligibility classification.

What the framework config keeps: gate ROLES, actions, severity, cadence.
What moves to the task: which checks, their thresholds, their views, their
dispositions. No mega-schema: the declaration carries only what §3.2's
table forced, and a task omitting health entirely is regime-legal
(UNKNOWN-style evidence-absence, §7 — never a synthesized pass).

## 7. Blocking / recording / inapplicable / error semantics (frozen here)

* Verdict vocabulary per check execution:
  `passed | failed | inapplicable | error`. `inapplicable` is decided by
  declaration comparison BEFORE I/O and never blocks, never counts as
  pass, and is persisted + aggregable as itself. `error` (a check that
  should run but cannot compute) on a BLOCKING check fails closed — it is
  never converted to pass or silently skipped; on a recording check it is
  persisted as error.
* Disposition (blocking vs recording) and thresholds: task-declared;
  ACTIONS and severity resolution stay the frozen framework set.
* Aggregation: unchanged (per-gate `on_fail` action; severity max across
  fired gates; `short_circuit` honoured). One blocking failure fails
  health for the round, as today.
* Candidate eligibility keeps `VALID / INVALID / UNKNOWN`; a round whose
  REQUIRED blocking set was not fully evaluated stays UNKNOWN with the
  absent evidence NAMED (the existing `feedback.py` discipline extends to
  inapplicability: an inapplicable check is excluded from the required
  set, an errored one is not).
* Health outcome is independent of metric direction and of the metric
  entirely.

## 8. TIDMAD preservation strategy

* **Verdict parity, capture-first**: the six checks' `HealthCheckResult`s
  byte-identical on the committed fixtures at every migration commit
  (goldens exist under `tests/unit/execute_tools/health_checks/goldens/`);
  where any composed-config byte could shift, a pre-change capture
  manifest pins expected values (the D14-1 discipline — expected values
  never recomputed by the new code).
* Gate IDs, check IDs, record fields (`health_gate_results`,
  `PersistedHealthGateResult`), severity, firing point, enforce/observe
  mode: unchanged.
* Thresholds move ownership with VALUES unchanged and empirical provenance
  comments carried along.
* Effective-config sha: mechanism untouched; the content change lands at a
  fresh-workspace boundary (run-invariants refusal is the safety net and
  is itself asserted, not weakened).
* Anything that would change a TIDMAD verdict is a semantic change
  requiring operator review — none is proposed.

## 9. Pets / DAVIS extension strategy (cumulative corpus)

* **L1 (declarations + atomic fixtures)**: each pack declares its health
  family + facts; the roadmap ladder runs as frozen — 8.4-A (two file-set
  declarations observably independent), 8.4-B (declared-float ⇒ int8
  family `inapplicable`, no file opened — spy-proven), 8.4-C (a generic
  check FIRES and can FAIL on that same declared-float output: the
  negative control that inapplicability is not an exemption).
* **L2 (real artifacts)**: the D14 gate artifacts are the first real
  corpus — the preserved Pets collapse CSV becomes a committed-fixture-of-
  record (small, deterministic) whose evaluation by the generic engine
  yields `dominant-fraction = 1.0 → blocking-fail` under Pets' declared
  family; a DAVIS npz evaluates through the continuous family with no
  TIDMAD/classification assumption. Fresh bounded runs (D14 runner
  pattern) provide the live half.
* Later Step-08 PRs INHERIT earlier evidence: TIDMAD parity goldens stay;
  B/C fixtures add beside them; the rung/census style follows D14
  (extend, never replace).
* Unit tests do NOT all run three tasks: each runs the smallest
  discriminating fixtures for the changed boundary; the THREE-task
  demonstration is milestone-level (§14).

## 10. Unit / Gate 1 / Gate 2 ownership

| property | canonical owner | TIDMAD evidence | Pets evidence | DAVIS evidence | when |
|---|---|---|---|---|---|
| declaration schema + applicability comparison (pure) | UNIT | regime-A derivation | declared facts | declared facts | 08a |
| inapplicable ≠ pass ≠ error transport (records/aggregation) | UNIT | goldens unchanged | 8.4-B fixture | continuous fixture | 08a |
| contract-routed TIDMAD peek parity | UNIT (goldens) | byte-identical results | — | — | 08a |
| production firing + persistence through the new path | **GATE 2** (bounded TIDMAD round) | required | — | — | 08a |
| task-owned family/threshold composition + pinning | UNIT + **GATE 2** (bounded TIDMAD, startup composition is lifecycle) | composed artifact semantically identical; verdicts identical | L1 declaration composes | L1 declaration composes | 08b |
| D18 typed no-per-sample statement | UNIT | negative control (per-file metric unchanged) | scalar-only metric real instance | scalar-only metric real instance | 08b |
| generic categorical/continuous checks on views | UNIT (hand-computed) | optional categorical view ≡ int8 parity | collapse arithmetic | dispersion arithmetic | 08c |
| REAL collapse detected / real dense output evaluated | **GATE 2** (bounded real artifact evaluations) | unchanged behaviour re-shown | **D14 collapse artifact → blocking-fail** | real npz → verdicts, no task assumptions | 08c |
| LLM-visible health feedback | — unchanged by default; any prompt delta ⇒ **GATE 1** at that child | counts/absence lines byte-stable | — | — | any child that renders |
| no-name-branch / no-examples-import invariants | UNIT guardrail census (extends the D14 census) | — | — | — | 08c |

Gate 1 is NOT required by default anywhere in Step 08: no LLM-facing
semantics change (prompt-visible health stays counts + named absence +
stable IDs). If a child elects to render inapplicability or family identity
into prompts, that child's freeze re-dispositions Gate 1 under the 07b
PB-delta rules.

## 11. PR decomposition — THREE PRs (derived, not copied)

Three capabilities, three blast radii, three failure classes:

```text
08a  CHECK INPUT CONTRACT + APPLICABILITY
     what a check declares, what it receives, how it honestly says
     "not for this task"; contract-routed TIDMAD peek; every check touched
08b  TASK-OWNED HEALTH CONFIG + THE TIDMAD FAMILY + D18
     who owns thresholds/roster/disposition; composition into the pinned
     effective artifact; the six become the first task family
08c  CONTRAST FAMILIES + GENERIC COLLAPSE CHECKS + THREE-TASK EVIDENCE
     the view vocabulary with its first consumers; Pets/DAVIS bindings;
     real-artifact evaluations incl. the D14 collapse; milestone census
```

Why not 2 (the scratch's split): pre-D14, 08c's content was L1-only and
could ride along; post-D14 it is live production surface (two new task
bindings, new generic checks, real-artifact evaluation paths) whose review
concerns — new science-adjacent arithmetic and real evidence — differ from
both the contract PR and the ownership PR. Why not 1: contract-vocabulary
changes to every existing check + config-ownership migration + new task
families in one diff would mix exactly the concerns the kickoff §15 names.
Why not 4: "generic checks fire cross-task" is not a fourth capability —
8.4-C's minimal case lands with 08a's fixtures, the full family with its
real consumers in 08c.

Dependencies: 08b consumes 08a's declaration contract; 08c consumes both.
Stacked like D14; per the validation-economy rule the children get targeted
tests + their own bounded Gates, and ONE canonical full CI runs on the
final integrated master-targeting head (#233 caveat: stacked PRs get no
automatic CI — evidence via the formal-PR run at the end, exactly the D14
closeout pattern).

## 12. Per-PR scope / goal / validation (parent level — no commit plans)

### 08a — check input contract + applicability
* **Goal**: inapplicability becomes a typed verdict decided before I/O;
  checks declare their inputs as data; TIDMAD reads route through the
  Deliverable Contract byte-identically.
* **Allowed changes**: `protocol.py`, `schemas.py` (additive verdict +
  declaration), `runner.py`/`evaluation.py` (verdict transport), the six
  checks' declarations, `_peek`/`_multi_file_peek` re-plumbing. NO YAML
  layout change, no registry/ownership change, no new checks beyond the
  minimal 8.4-C dispersion fixture-check, no prompt change.
* **Acceptance**: six-check verdict parity on goldens; 8.4-B with the
  no-file-opened spy; 8.4-C negative control; applicability reachability
  from `evaluate_and_persist_health_gates`; Gate 2 = one bounded TIDMAD
  round (gates fire + persist through the new path). Gate 1: none.

### 08b — task-owned health config + first family + D18
* **Goal**: the task owns roster/thresholds/dispositions; framework owns
  policy; composition lands in the SAME pinned artifact; scalar-only
  metrics reach the context as a typed statement (D18), consumed as
  `inapplicable` by per-file checks — never a hollow pass.
* **Allowed changes**: `config.py` (watch the god-file line, §2.5),
  effective-config composition, registry family identity (flat lookup
  preserved), `HealthCheckContext` additive statement, TIDMAD family
  relocation with values unchanged.
* **Acceptance**: composed TIDMAD artifact semantically identical (byte
  delta, if any, called out + fresh-workspace note); verdict parity;
  run-invariants refusal asserted; 8.4-A; D18 positive (real scalar-only
  `MetricSpec` instances now exist: accuracy, mse) + negative control;
  Gate 2 = one bounded TIDMAD round (startup composition is lifecycle).
  Gate 1: none.

### 08c — contrast families + generic checks + three-task evidence
* **Goal**: Pets and DAVIS bind real health families; the generic
  categorical/continuous collapse checks exist with hand-computed
  arithmetic; the framework detects the REAL D14 Pets collapse and
  evaluates a REAL DAVIS artifact with zero task-name knowledge; the
  guardrail census extends to health.
* **Allowed changes**: new task health bindings (production task modules,
  packs declare config), the generic check family, the bounded real-
  artifact evaluation path (runner-pattern), census extension.
* **Acceptance**: collapse fixture-of-record → blocking-fail with the
  dominant-fraction evidence persisted; DAVIS npz → verdicts through the
  continuous family; TIDMAD untouched (goldens); census: zero task-name
  branches in health core, zero `examples/` imports, no 37/int8/temporal
  literals in generic code; a documented fourth-task walkthrough requiring
  zero generic-core edits. Gate 2 = bounded real Pets + DAVIS artifact
  evaluations (≤10 min each, D14 runner pattern; PASS/FAIL from semantic
  evidence). Gate 1: none unless a prompt delta is elected.

## 13. Genericity / task-identity guardrails (structural acceptance)

Extending the D14 census (`test_task_data_path_census.py` precedent) to
health core: zero `tidmad|pet|davis` comparisons; zero `examples/` imports
in production; no `37`, no int8 vocabulary, no channel/file literals, no
temporal geometry in generic health code; no golden-metric arithmetic and
no `TrainingDiagnosis` logic in any check; new-check-consumes-metric-scalar
is census-refused; view vocabulary growth requires a task that forces it.
A fourth task binds by declaration + registered provider only.

## 14. Step-08 completion criteria

A. TIDMAD: six verdicts byte-identical on goldens; gate IDs/records/firing
   point/severity/mode unchanged; production Gate-2 evidence at 08a and
   08b heads. B. Pets: the real D14 collapse artifact evaluates to a
   blocking categorical-collapse failure under Pets' declared family — the
   framework can now SAY what D14 could only observe. C. DAVIS: a real
   dense artifact evaluates through the same engine with no TIDMAD or
   classification assumption. D. Generic core: census green (§13).
   E. Semantics: `inapplicable`/`error`/`unknown` distinct, deterministic,
   persisted; required-blocking-uncomputable fails closed. F. Testing:
   ownership per §10, no fake lifecycle Units, evidence cumulative.
   G. Extensibility: the documented fourth-task walkthrough shows zero
   generic-core edits.

## 15. Residual risks / open questions

* **R1 — composed-config sha churn (08b)**: byte-identity of the effective
  artifact may be impossible under composition; fallback is "semantically
  identical + called-out delta + fresh-workspace boundary". Operator
  ratification requested (carried over from scratch Q4).
* **R2 — TIDMAD categorical-view unification temptation**: expressing the
  int8 checks THROUGH the new generic family would be elegant and is
  deliberately NOT required — parity first; unification only if verdicts
  stay byte-identical, else it is deferred debt, not scope.
* **R3 — firing-point honesty**: B/C health runs engine-level until
  Steps 10/12 bind their workflows; the design says so everywhere a claim
  could be over-read (§3.3.3).
* **R4 — #233**: stacked children get no automatic CI; the D14 closeout
  pattern (one canonical formal-PR run at the integrated head) is the
  plan of record unless #233 is fixed first.
* **Open for operator**: (Q1) 3-PR split accepted? (Q2) R1 fallback
  accepted? (Q3) confirm health stays prompt-invisible beyond today's
  counts/absence lines (Gate 1 stays off by default)?

## 16. Explicitly deferred (none block Step 08)

`collapse_detection_framework_generic.md` machinery stays dead (§8.5
roadmap); #225 scope-opacity, #226 auto-resume, #227 integration rot,
#228 two-route non-finite divergence, #229 pseudo-probe escape — separate
issues; prompt-side health rendering (Step 09's consumption of evidence);
tuner-integrated B/C health (Steps 10/12); any new view kind (needs a
forcing task).

## 17. Adversarial self-review (kickoff §23, applied)

1. *TIDMAD HealthGate with optional fields?* No — the task binding is
   roster+params+provider, not a widened TIDMAD schema; B/C declare
   different families, not TIDMAD's with switches. 2. *Does core now
   "understand classification"?* It understands `categorical_predictions`
   — a view kind TWO real tasks instantiate (Pets, and TIDMAD's own
   argmax-symbol output), with cardinality DECLARED, never inferred; the
   37 lives in Pets' declaration. 3. *Temporal understanding?* None —
   DAVIS reduces to `continuous_samples` through ITS provider; no
   temporal axis exists in core. 4. *Ownership theft?* §5 table;
   scoreability/metric/diagnosis untouched; the D18 statement REPLACES a
   silent bridge rather than adding metric knowledge. 5. *NA→pass?* The
   verdict is the PR-08a headline; 8.4-B asserts the verdict AND the
   absence of I/O. 6. *Silent skips?* `error` fails closed on blocking;
   UNKNOWN names absences (existing discipline, extended). 7.
   *Mega-schema?* Two view kinds, forced by three real tasks; growth
   gated on a forcing task. 8. *Units faking lifecycle?* Firing,
   composition/pinning and real-artifact evaluation are Gate-2-owned
   (§10). 9. *Gate 1 by habit?* Off everywhere by default, with the
   re-disposition rule stated. 10. *B/C decorative?* They reshaped the
   abstraction (§3.3: declaration-based applicability, view providers,
   engine-level evidence) — the design is different BECAUSE of them.
   11. *God file?* §2.5 watch item with a pre-committed extraction rule.
   12. *Fourth task?* §14.G makes the walkthrough an acceptance item.
