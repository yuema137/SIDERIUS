# SIDERIUS Generic Framework Upgrade — overall architecture & roadmap

**Status: DRAFT — operator review pending. Audit + architecture direction
only; this document authorizes NO implementation.** Each module named
here receives its own detailed design document before any code changes.
This document decides direction, module ownership, compatibility
surfaces, and migration order — never exact schemas or field names.

Created 2026-08-10 from an 11-area parallel source audit at master
`c636c624` (post-V21: all seven V21 PRs merged; V21 ledger CLOSED).
Audit areas: A graph/orchestration, B task/config/prompts, C
data/dataset, D proposer/implementor/validator, E1 tuner
planning/policy, E2 tuner execution/resource, F scoring/interpretation,
G plugins/models/losses, H runtime/execution infrastructure, I
tests/fixtures/compatibility, J documentation/history. Load-bearing
claims were re-verified in source by the main auditor; every important
current-state claim below carries `file:line` evidence from that audit.

**Revision 2 (2026-08-11, operator-directed reconciliation):** adds the
task-COMPOSITION principle (§0 rule 9); splits absent-config semantics
into a legacy adapter vs fail-closed generic binding (§2); separates the
DELIVERABLE contract from the input dataset contract with ownership
moved to the convergence ledger (§3.1, V9, §4/§7c/§9/§10/§14); makes
every contrast fixture ATOMIC (one axis per fixture, §0.7); splits
framework completion into CORE and FINAL milestones with D1 no longer
exempt from FINAL (§16); states the 7c/metric sequencing boundary
explicitly (§7c, §15 step 5); adds the long-lived status table (§15.1);
and corrects the Seam-2/Seam-3 inheritance mapping (§0.A). A second
adversarial pass reviewed this revision (record appended below).

**Revision 3 (2026-08-11, operator planner-contract review):** narrows
this document to its GOVERNANCE role — principles, per-module FINAL
EFFECTS, the compatibility iron law, uniform validation checkpoints
(0/A-E), dependency order, and completion milestones; implementation
detail stays in future per-module designs. Adds: the module
COMPLETION-CONTRACT MATRIX (§15.1, replacing the status-only table —
one table, still the single meter); the standardized checkpoint model
(§17); the PROPOSER-FIRST sequencing reconciliation (§15.0 — a
planner-level conflict with a prior operator decision, resolved from
the source dependency graph with options presented; the prior decision
was NOT recorded in-repo and is recorded now); and the D1
consumer classification from source (§16). A third adversarial
planning pass reviewed this revision (record below).

**Third adversarial review record (2026-08-11, planning pass on
Revision 3):** a fresh planning-only reviewer attacked the governance
revision; 14 findings CONFIRMED and corrected in place — decisively:
the O1 loss-legality claim was FALSE (the commit prompt is a plain
string with zero substitution; extraction is NEW placeholder work
extending the live mechanism, its sources of truth existing —
corrected with 6-P's scope honestly narrowed and its constraints-block
slice deferred to step 2); the 6-P/6-M split had not propagated into
§6/§13 (now it has, incl. the contract-reassertion pin re-targeting
moving to step 1's design); §10's live-integration consumer at step 6
is production scoring through the interface (incumbents remain §7a's
step-7 C); the Deliverable Contract row is STAGED 5→11 with an
ownership tie-break rule; the dashboard's peripheral classification is
now operative in the debt list; checkpoint-B's definition unified with
§16.5 (design-declared required rungs); the two previously
un-instantiated §2 surfaces (prior-plugin loadability; LLM-boundary
kwargs) now appear in the relevant A cells; step 0 exempted from
checkpoints A-C; §8's final effect made behavioral; §12's completion
claim scoped to its own surfaces; checkpoint-E given a blocking
deadline; one stale step number and one citation defect fixed.
Cleared: dependency graph acyclic (after the two named fixes), no
premature architecture decisions found (§8-of-brief clean), all
spot-checked citations verified.

**Second adversarial review record (2026-08-11, on Revision 2):** a
fresh reviewer attacked the revised document against the operator's
seven Rev-2 questions plus a consistency sweep; 8 finding groups were
CONFIRMED and are corrected in place: the regime-A/B split had not
propagated into module sections and its regime-B switch had no roadmap
step (now: propagation rule in §0 rule 9, step 12 scheduled, and
regime dispositions attached to the two named silent core defaults in
§5/§9); §4/§9/§8 residue still conflating input data with deliverables
(now fully re-pointed at the §3.1 contract); Rev 2's own composition
text violated its no-semantic-ownership rule via the task_config
"embryo" claim (corrected: content is §13-owned, the root only binds);
four fixture passages remained multi-axis and §7e had none (all now
atomic ladders, the unsatisfiable 7c fixture corrected, the cumulative-
rung rule added, the non-HDF5 deliverable rung given an owner);
Milestone 2's enumeration missed campaign_artifacts.py,
per_file_best.py and the interpretation sign-band (now named, with
status-table debt ties); 7c's step-5 consumption of a not-yet-owned
contract resolved via provisional extraction; three §14 rows sat below
the ledger's own ≥2-designs bar and §6.6 carried a stale entry (all
reconciled); six numbering/cross-reference defects fixed (§0.A rename,
step-12 addition, single-progress-meter rule, D8/§16 pointer,
step-0 status wording, dangling §E.3d.1 reference).

**Adversarial review record (2026-08-10):** a fresh reviewer agent
attacked the first draft against the §0 rules with source re-opened per
criticism; 19 findings were CONFIRMED and are corrected in place, each
marked "(finding N)" at the corrected spot. The most consequential:
portions misfiled as dataset config (1); budget prose misfiled as
config against the live [HARDWARE CONTEXT] precedent (2); premature
owner pre-assignment vs the §14 merge rules (3-4); a self-contradictory
roadmap order around the metric handle (5-6); a crash-resume guard
misread as scoreability validation (7); a missed in-tree metric-identity
precedent (8); an undercounted name-branch inventory + over-claimed
guardrail scope (9); a missed core/ task coupling
(campaign_artifacts.py) (10); hardcoded metric direction in dashboards/
resume (11); two hidden fresh-workspace migration boundaries (12); a
test-re-targeting rule that would have made absence-pins vacuous (13);
an invented three-layer prompt architecture replaced by extension of
the working placeholder mechanism (15); the draft's own citation of a
consumer-less remedy seam (16); a three-concepts-one-name conflation in
axis V2 (17); and six citation corrections (18).

---

## 0. Purpose and migration philosophy (operator-frozen, 2026-08-10)

Evolve the working TIDMAD-centered system into a framework that supports
materially different data formats, dataset organizations, task
semantics, model/input contracts, output forms, training/inference
workflows and evaluation contracts — WITHOUT a big-bang rewrite.

Binding method:

1. **Module by module, submodule by submodule.** Every completed module
   independently becomes more generic, clearer and more testable; the
   repository stays working at every step. Migration follows the REAL
   module boundaries where they are sound; no new top-down architecture
   is invented for cleanliness. Abstractions are extracted from the
   working system.
2. **Local config first, shared config later.** No universal mega
   TaskConfig up front. Each module extracts its own task-sensitive
   behavior into its own typed, module-local config. Cross-module
   unification happens only AFTER multiple completed module designs
   expose the same semantic concept with the same ownership — tracked in
   the Cross-Module Convergence Ledger (§14) until then. Duplication
   during migration is acceptable; premature abstraction is not. Two
   fields both named `data_shape` is not evidence of shared semantics.
3. **Not every helper earns a config.** Only behavior that varies with
   task/data/output contract is configurable. Pure deterministic helpers
   stay plain functions. Config explosion is a failure mode.
4. **Config is task semantics, never ephemeral runtime state.**
   Multi-file topology, systematic groups, split semantics, output
   structure → config. A probed `inference_batch=16`, measured VRAM,
   warm-up timings, the current incumbent, HealthGate evidence → runtime
   state/records, exactly as today. The inputs-vs-config-vs-runtime-state
   item of every module section separates the three explicitly.
5. **Two-stage pattern per module.** Stage A (extraction/parity):
   TIDMAD-specific behavior → explicit module-local config/contract →
   SAME behavior, proven. Stage B (generalization): the contract
   supports at least one materially different case, proven by the
   module's contrast fixture. Never combined when separable, so a
   regression is attributable to "extraction" or "new capability".
6. **TIDMAD is the golden compatibility profile** — an INSTANCE of the
   generic contract, never `if tidmad` branches in core code.
7. **Genericity is proven, not asserted — with ATOMIC fixtures (Rev 2).**
   Moving strings into YAML proves nothing. Every module ends with (a)
   TIDMAD parity evidence and (b) contrast fixtures from an ATOMIC
   LADDER: each fixture varies exactly ONE audited axis RELATIVE TO ITS
   LADDER'S ESTABLISHED BASELINE (later rungs may build on already-
   proven earlier rungs — e.g. a regressor custom loss builds on the
   proven regressor rung), so a failing fixture identifies WHICH
   abstraction failed. A module's detailed
   design picks the minimum ladder subset its landed abstraction
   requires — not every rung in one PR, and never a multi-axis fixture
   presented as proof of one abstraction.
8. **Minimum sufficient abstraction.** No abstract base classes with one
   implementation, no config fields with no caller, no registries
   without a second implementation, no universal schemas from
   hypotheticals. The repository's most-repeated defect shape — *a
   correct mechanism exists but no live caller supplies/uses it*
   (the V21 ledger's §E.3d.1 defect shape, docs/design/v21_priorities.md — found eight times across V21) — must not be reproduced by
   the genericization itself. The audit found existing instances to heed:
   `DatasetConfig.validation_file_pattern` has ZERO production consumers
   (dataset_config.py:46-49,298 — a seam built before its consumer);
   `protocols/ml_model_tune_to_ml_result_interp.local_all_records` is
   implemented but unused by `run_workflow` (which builds
   `InterpretationInput` inline, model_exploration.py:2083); the
   proposer's `template_vars["task_description"]` is supplied but no
   proposal template contains the placeholder (ml_model_proposal_agent
   .py:1597); `score_vector`'s `anchor_map` parameter is dead in its
   body (scoring_utils.py:473 vs :575-586, re-verified). Stage A work
   must land seams WITH their first consumer.
9. **Task composition is a thin binding layer, not an owner (Rev 2).**
   Independently-owned module configs still eventually need a
   composition/binding root so ONE task can select its dataset/input
   profile, model/output contract, metric instance, health profile,
   prompt/task blocks, deliverable contract, and future module-owned
   configs. Principle: *task composition is a thin binding/REFERENCE
   layer over module-owned configs — never an owner of their semantics
   and never a merged mega-config.* Its exact physical representation
   (file layout, schema) is DEFERRED until several module configs exist
   (D12; scheduled as §15 step 12). NO composition root exists in-tree
   today: `configs/task_config.yaml` is §13's module-owned config —
   its CONTENT (task_description, forward_contract) is semantic and
   §13-owned; only its snapshot/injection MECHANICS
   (workflows/task_config.py + _snapshot_task_config) hint at binding.
   genericity_contract.md Seam 3's "one pluggable unit" anticipated
   composition as a BINDING concept while the unit's contents remain
   module-owned. Rules a future composition design must satisfy: it
   references module configs by identity, adds no semantic fields of
   its own, and binding a task through it switches the framework from
   legacy-adapter defaulting to fail-closed resolution (§2, Rev 2).
   Regime PROPAGATION rule (second pass, F1): every module section's
   "TIDMAD default" wording is regime-A ADAPTER wording by definition;
   per-module fail-closed (regime-B) tests land WITH step 12's
   composition design, not with each module's Stage A — module designs
   only ensure their resolution path can DISTINGUISH "unbound legacy
   caller" from "bound task" when step 12 arrives.

### 0.A Relationship to prior genericization commitments

This roadmap SUPERSEDES-BY-ABSORPTION the two 2026-07-28 artifacts and
corrects the record:

```text
Previous assumption (CLAUDE.md:214-216, docs/architecture.md:717-718):
  seams are defined "in v19_priorities.md §1.3 until the dedicated
  contract doc exists".
Audit evidence: docs/design/genericity_contract.md has existed since
  2026-07-28 (commit 60bd881d) with four seams (indexed dataset;
  proposed/override/resolved config; task pack PLACEHOLDER; metric
  PLACEHOLDER); docs/design/tidmad_coupling_ledger.md was seeded the
  same day. NEITHER has been updated since (git: one commit each),
  despite the binding "decouple in the same commit" rule; V20 §1.4
  replaced the mechanism with per-PR "Genericization impact" sections
  without superseding the ledger. The ledger is stale in both
  directions: probe_wiring.py's TIDMAD_DATA_DIR coupling was FIXED in
  V20 PR C1 with no DECOUPLED entry; the "47 abra_* literals in 7
  scripts" count is now 53 in 13 files.
Corrected understanding: the seam definitions in genericity_contract.md
  remain sound and are inherited here. CORRECTED MAPPING (Rev 2 — the
  Rev-1 line "Seam 2 → §13 config rules; Seams 3/4 → §5 and §10" was
  wrong twice): Seam 1 (indexed dataset) → §4. Seam 2
  (proposed/override/resolved config governance + the
  agent-settable/operator-overridable/chain-locked/frozen taxonomy) →
  the §0 config rules and the §17 ladder — NOT §13, which is the
  prompt/task-profile module. Seam 3 (task pack: "task description,
  forward contract, and task-specific prompt fragments travelling as
  one pluggable unit", genericity_contract.md:134-145) → §13 PLUS the
  new composition principle (§0 rule 9) — its "one pluggable unit"
  anticipated composition as BINDING; it was never about the model/loss
  contract, and mapping it to §5 was a name-over-semantics error.
  Seam 4 (metric, frozen exception) → §10 (correct in Rev 1). Roadmap
  consequence: Seam 3's CONTENT (task description, forward contract,
  prompt fragments) is §13-owned; the composition root (D12, step 12)
  eventually BINDS/references that unit and never owns its semantics —
  the second adversarial pass caught Rev 2's own draft violating this
  (F3) by calling the root the unit's "home". The coupling ledger's
  per-entry statuses are absorbed into this document's module sections
  and the ledger is retired as a separate progress meter.
Generic-framework consequence: this document is the single seam
  authority going forward; CLAUDE.md's pointer must be updated when the
  first module PR lands (not in this docs-only change). CLAUDE.md:8's
  claim that "the framework is task-agnostic — porting starts with
  editing configs/task_config.yaml" is a TARGET, not current state:
  task_config parameterizes exactly two prompt surfaces
  (task_description + forward_contract; workflows/task_config.py:150,
  171) while 61 TIDMAD_DATA_DIR occurrences across 24 non-test modules (incl.
  scripts/ and the production chain entry) and the coupling inventory
  below remain.
```

Also corrected: `docs/design/collapse_detection_framework_generic.md`
cites trackers V17 dropped (M1/M4), declares an authoritative
`reference_data/collapse_phantoms.json` that never existed, marks the
pearson guard "not yet built" (it is built and registered), and its
acceptance criterion "zero task-specific values hardcoded in
health_checks/" is false today (`output_diversity.py:76-77` class-127
literal; `output_std.py:36` `_MV_PER_LSB=40/128`). Its health-check
genericization intent is absorbed into §8 (HealthGates submodule).

---

## 1. Current system map (source-grounded)

Two entry points exist; only one drives the agent graph:

- **Chain entry (production)**: `sdsc_submission_scripts/
  run_one_iteration.py` — one iteration per subprocess; resolves chain
  workspace + invariants (`DataScope.resolve(TIDMAD)` :1392), restores
  ALL cross-iteration state from disk via `core.resume.
  restore_prior_state()` (:1770), resolves the task-bound measurement
  capability at the CALLER (`resolve_tidmad_measurement_capability`
  :1858 — `run_workflow` deliberately refuses to name a task resolver,
  model_exploration.py:1578-1582), then calls `run_workflow(...,
  max_iterations=1)`.
- **`scripts/run_comparison.py` is NOT a graph entry**: it never calls
  `run_workflow`; it subprocess-launches the tuner node CLI directly
  and runs paper-spec baselines from `legacy_baseline_configs.json`.

In-workflow graph (`workflows/model_exploration.py:run_workflow`
:1334), per iteration:

```text
task/config init
  configs/task_config.yaml -> load_task_config (process-cached,
  workflows/task_config.py:44); snapshot to run_dir (:1692)
    |
interpret   ResultInterpretationAgent          [InterpretationInput
            built INLINE :2083-2106 — the tune->interp protocol
            exists but is production-unused]
    |
lit review  MLLiteratureReviewAgent (flag-gated :2133) ->
            merge_external_agent_outputs :2158
    |
propose     protocol local_full_context :2262 -> MLModelProposalAgent
            (+ post-hoc fields: task_description, forward_contract,
            hardware_context, previous_failures, mindset)
    |
implement   protocol local_full_spec :2375 -> MLModelImplementor
            (writes plugin .py + test + description)
    |
validate    protocol local_all_fields :2412 -> MLCodeValidatorAgent
            (9 checks + realized param counts)
    |         on pass: CapabilityRegistry.register; in-memory registry
    |         extension; plugin staged tuner-scoped + chain-canonical;
    |         loss/model promotion to the global library
    |
tune        protocol local_validated_model :2569 (~55 kwargs) ->
            HyperparamTuningAgent.run()  [see §7 submodules]
    |
records     iteration_results; knowledge cache; incumbents; vocab;
            workflow_{run}.json; per-node {node}_{run}.json files
```

Major side channels: resource preflight (isolated VRAM probe workers),
pre-phase GPU measurement (spec-file worker subprocess), runtime
verification RT2 (in-subprocess sidecars), watchdog (deadline from live
sidecar), dataset/sample selection (`build_sample_set`), plugin
registry + `$SIDERIUS_CHAIN_WORKSPACE` transport, prompts
(agent/prompts.py + prompt_templates/), HealthGates (post-inference),
scoring subprocess, evolution/token JSONL logs.

Execution boundaries (all four sandbox spawns use RELATIVE script paths
with `cwd=os.getcwd()` — repo root required; sandbox_executor.py:1251,
1564,1794): training (`train_engine_sandbox.py`, JSON config files +
sample-set JSON + RT2 sidecar; `_OK_{exp_id}` sentinel protocol),
inference (`inference_single.py --mode agent`, per-file HDF5 outputs +
timing sidecar), scoring (`denoising_score_single.py`, merge-into-JSON
IPC; the only spawn without the observed-subprocess seam), GPU
measurement worker (spec **file**, parent-side RSS/deadline
supervision). Cross-iteration state that ACTUALLY crosses subprocesses
is reconstructed from disk by `core/resume.py` (manifest→source_paths;
plugins; runtime vocab; key findings; knowledge cache; physical
rejections capped K=10; gate exhaustions; previous proposal; collapse
fingerprints; chain incumbent) — an inventory that any genericization
of records must preserve field-for-field.

What is ALREADY task-agnostic in orchestration (audit A): workflows/
task_config.py, llm_config.py, the six protocol modules (only DataScope
typing imported), core/run_invariants (scope passed as parameters),
core/resume state machine, DataScope/DatasetConfig as CLASSES, the
measurement-capability seam, iteration/round control. What binds it to
TIDMAD: the module-level `TIDMAD` import + full-scope checks
(model_exploration.py:104,1817,1856), `file_index=6` default (:1347),
construction-probe `loss_type="focal"`/`representative_T=16000`
(:672,737-750), every `*denoising_score*` field read, and the legacy
source-path template (:297-306).

---

## 2. Global backward-compatibility contract

TIDMAD is the golden profile. Compatibility is defined PER SURFACE with
the strongest feasible criterion — never "roughly the same":

| Surface | Criterion | Mechanism |
|---|---|---|
| Rendered prompts | **Exact string equality** for the TIDMAD profile, including whitespace/ordering/formatting: `render(current prompt) == render(framework prompt + TIDMAD config)` | Golden snapshot per prompt-producing call site, captured from CURRENT master BEFORE extraction (see baseline gap below) |
| Config/default resolution — TWO regimes (Rev 2) | **(A) Legacy/migration adapter**: an EXISTING TIDMAD caller may omit newly-extracted module config and resolve to exactly today's TIDMAD behavior, deep-equal — this is a backward-compatibility ADAPTER, kept for the migration and for un-migrated callers. **(B) Generic binding**: once a task is explicitly bound through the composition mechanism (§0 rule 9), required task semantics resolve EXPLICITLY; missing required semantics FAIL CLOSED — they never silently inherit TIDMAD assumptions. Principle: *TIDMAD defaults are a backward-compatibility adapter, not the universal framework default.* Exact API/config syntax deferred to the module designs | (A): parity tests on resolved objects; (B): fail-closed tests land WITH step 12 (§0 rule 9 propagation rule) |
| Scoring/evaluation | Frozen TIDMAD scorer byte-identical (standing operator rule; genericity_contract.md Seam 4 frozen exception: `log_{5.27}`, global `s_max` ruler, grand-mean aggregation). Generic metrics land BESIDE it | Existing pins + legacy-parity test (real_run) + the offline numeric baseline (`test_scoring_reference_default.py` scalar pins) |
| Records/schemas/trajectories | Operational criterion: field-set + semantics pins on every restored field; a resume replay over a recorded TIDMAD workspace reconstructs identical state; ON-DISK GENERATED PLUGINS are part of this surface (finding 12b — core/resume.py:1290-1303 re-loads prior iterations' plugin .py files, warns-not-fails on validation breaks; §5/§6 contract changes must keep prior plugins loadable or declare the workspace boundary). NO migration merely for genericization | Schema-shape pins + resume replay + prior-plugin load tests |
| Deterministic runtime behavior | Exact parity (same inputs → same artifacts); SampleSet determinism already hash-pinned (sha16 goldens @seed 42, test_sample_set_builder.py:244-264) | Targeted parity tests per module |
| Nondeterministic behavior | The ACTUAL invariant is named and tested (e.g. same kwargs reach `LLMBridge.plan`; same policy identity consulted; provenance recorded) | Boundary-capture tests (RecordingLLMBridge.calls is today's only prompt-capture surface) |

### 2.1 Golden-baseline gap (audit I) — the compatibility foundation is INCOMPLETE today

What already exists and anchors parity: 4 rendered-prompt goldens
(interpreter ×3, proposer reasoning ×1 — exact `==`); the offline
TIDMAD numeric baseline (5 hard scalars + length-20 pins over committed
reference_data); legacy scorer parity vs a verbatim legacy copy at 1e-10
(real_run-gated); SampleSet sha16 goldens; the C8 consumer-parity
literals; the frozen 3×3×3 authority matrix; 5 exact schema key-set
pins; two canonical dual-mode choreographies (k9, l_fail); the
name-branch guardrail with an EMPTY pending list.

What has NO pin today (must be captured BEFORE the first extraction):
rendered `PLANNER_PROMPT`/`REFLECTOR_PROMPT`, `PROPOSAL_COMMIT_PROMPT`,
implementor code/loss prompts, validator LLM prompt, all lit-review
rendered prompts; the shipped `configs/task_config.yaml` resolved
content; the `TIDMAD` DatasetConfig constants themselves; any
serialized-record golden; scorer replay runnable in CI (the parity test
needs real data); pseudo↔real schema fidelity (declared unenforced by
tests/pseudo_data/README.md). **Roadmap step 0 (§15) is therefore a
test-only golden-capture PR with zero production diff.**

---

## 3. Generic variation axes discovered in the codebase

Derived from the coupling inventory, not invented. "Candidate owner" = the module whose DETAILED DESIGN is expected to
claim the axis — a hypothesis to be confirmed by that design, never a
pre-merge assignment; §14 governs every actual unification, and its
default (DO NOT MERGE YET) outranks this column wherever they touch
the same concept.

| # | Variation axis | Current TIDMAD assumption (evidence) | Modules affected | Likely owner | Generic target |
|---|---|---|---|---|---|
| V1 | Dataset topology (file families, counts, index space) | 2 parallel families `abra_{training,validation}_{i:04d}.h5`, one 0..19 index space, num_files=20 (dataset_config.py:292-304); equal-cardinality unverified | dataset, tuner, scoring, health, scripts | Dataset (§4) | declared file families + index spaces; consumers receive resolved topology |
| V2 | Sample geometry — three DISTINCT concepts (finding 17), not one: (a) psd_segment_length = the METRIC's 1-second analysis window (shared §4/§10 ownership UNKNOWN); (b) segments_per_file = dataset addressing (§4); (c) segmentation_size = a proposer-owned MODEL HYPERPARAMETER (schema-bounded, models_format_sandbox:106) that is runtime plan state, NOT dataset config | dataset, proposer, tuner, estimators, workload resolvers, scoring | §4 owns (b) + the LEGALITY function; (a) shared pending §10; (c) stays plan state | per-task decomposition + legality; hyperparameter legality derived, value never configured |
| V3 | Value encoding (dtype, offsets, classes) | int8 +128→int64 in [0,256); 256 hardcoded in every builtin AND ≥9 independent literals in candidate creation AND estimator formulas (models_sandbox:226…; validator:333; training est:402) | models, candidate creation, execution, estimators, health checks | split: §4 DECLARES the data-side encoding, §5 OWNS the model-contract derivation (the single story; §5.3 and §14 use the same wording) | encoding declared once; probes/templates/formulas derive |
| V4 | Output contract (per-output_type shapes) | classifier [B,256,T] / regressor [B,T] / hybrid(loss-dependent, builtin-only) | models, candidate creation, inference decode, VRAM probes | Model/loss contract (§5) | output forms per declared type; alphabet extensible |
| V5 | Loss families | closed Literal{focal,focal_cw,ce,smooth_l1,custom}; families partitioned by output_type; custom probed classifier-only | models, candidate creation, tuner | Model/loss contract (§5) | per-output_type family map + custom probe recipe |
| V6 | Split/selection semantics | snapshot/anchors/target strategies; ANCHOR_FILES=[0,10,19]; portions; formal-eval locked to snapshot; trial packing asymmetry | dataset, tuner data selection, scoring | Dataset (§4) + tuner data-selection (§7b) | strategy definitions as data; group-aware anchors |
| V7 | Systematic structure (groups/bands) | informal in FOUR places: anchors triplet, health peek [3,10,17] "low/mid/high", scripts band tables, AND core/campaign_artifacts.py:57 (`if requested == [3, 10, 17]`) — which also requires a `denoising_score` field (:39) and imports TIDMAD for the full-scope default (:88-92); a task coupling inside core/ with no owner | dataset, health, interpretation, scripts | Dataset (§4) as named groups | groups as declared data consumed by all three |
| V8 | Metric identity (name, direction, aggregation, references) | `denoising_score` literal in schemas/prompts/~40 tuner sites; higher-is-better implicit everywhere; frozen formula; committed anchor/reference artifacts; scalar-per-record authority object | scoring, tuner, orchestration, interpretation, dashboard | Metric interface (§10) | named metric instance w/ direction + aggregation; TIDMAD frozen instance beside |
| V9 | Deliverable/artifact form — a DISTINCT contract from the input dataset (Rev 2, §3.1) | denoised int8 HDF5 `timeseries/channel000N`, template re-inlined ≥6 sites; attrs hardcoded; INDEXED by input file identity but its FORM is the task deliverable | producer: inference execution (writes, inference_single:561-563,:700-705; layout array2h5:26,44-72); readers: scorer (scoring_utils:148,:389), health peeks (_peek/_multi_file_peek channel0001), cleanup globs (sandbox:1652, tuner:5401), run_comparison | **UNKNOWN — convergence ledger** (§14); NOT the Dataset module: TIDMAD's input/output sharing HDF5 conventions is coincidence, not shared semantics | one Deliverable Contract (naming, layout, dtype, attrs) whose owner is decided by evidence (§14 row) |
| V10 | Prompt task content | 15 hardcoded prose families beyond the 2 injected placeholders (audit B §2: commit prompt, loss prompts, validator prompt, personas, SQUID worked examples, full-spectrum doctrine, data-volume anchors, CH1/CH2 semantics, collapse advice, budgets) | every LLM node | Task profile & prompts (§6) with per-node blocks | framework instruction + module instruction + task blocks; golden-equal for TIDMAD |
| V11 | Model catalogue & descriptions | 5-model roster in PLANNER_PROMPT:16-21; description.md files embed SQUID/axion prose; builtin config map duplicated | tuner prompts, model registry, interpretation | Model/loss contract (§5) + task profile (§6) | catalogue from registry; descriptions carry task-block seams |
| V12 | Resource/time calibration | ×2.7 ratio (N=2), 800k intensity cap, RSS caps 40/60/24 GiB (dataset-sized rationale), overhead 185/50 MB, batch table, store-reuse bounds, seg defaults 40000/1000 | estimators, gates, sandbox | Resource planning (§7d) — mostly RUNTIME/CALIBRATION state, not task config | calibration records keyed by (hardware, workload-class); task-shaped terms derived from profile |
| V13 | Health-check semantics | int8 diversity/amplitude/mV-scale checks; _MV_PER_LSB=40/128 ×4 copies; range(20) ×3; peek [3,10,17]; class-127 literals | health checks, prompts | HealthGates (§8) | checks declare task-profile inputs; thresholds per-task config |
| V14 | Hardware assumptions | device index 0; 0.80 cap; CUDA-sized RSS ceilings on CPU; nvidia-smi dependency | hardware context, sandbox, measurement | Execution infra (§9) — framework invariants + calibration | already mostly framework; keep out of task config |
| V15 | Workflow/iteration semantics | rounds/attempts/formal-promotion; incumbent gates; -inf bootstrap; skip/bypass deltas | tuner policy (§7a), orchestration (§11) | Tuner policy (§7a) | already largely task-free; metric-direction dependency via V8 |

### 3.1 Four contracts, not one (Rev 2 — operator-directed re-audit)

TIDMAD's inputs and outputs both being flat-int8 HDF5 seduced Rev 1
into assigning derived-artifact naming/layout to the Dataset module.
The audit evidence does not support that ownership:

```text
INPUT DATASET CONTRACT   what exists to READ: file families, index
                         spaces, decomposition, truth channels.
                         Owner: §4. Evidence: dataset_config,
                         sample_set_builder, training/inference reads.
MODEL I/O CONTRACT       what a model accepts/emits in memory.
                         Owner: §5 (declared encoding from §4).
DELIVERABLE CONTRACT     what an attempt PERSISTS as its product:
                         naming, layout, dtype, attrs, completeness.
                         Producer: inference execution; readers:
                         scorer, health peeks, cleanup, scripts.
                         TIDMAD instance: the denoised-HDF5 family.
                         A future task may emit a JSON report, a
                         trained-model package, a geometry+scalar —
                         forms with NO input-dataset kinship.
                         Owner: UNKNOWN → §14 ledger row.
METRIC SCOREABILITY      what makes a deliverable SCOREABLE by a
CONTRACT                 given metric. Owner: §10, defined AGAINST
                         the deliverable contract (today implicit —
                         no scoreability validation exists; §10.2).
```

What §4 keeps: derived-artifact INDEXING (deliverables are keyed by
input identity — file_index today) and nothing else about their form.
What moves to the ledger: the Deliverable Contract's owner, decided by
whichever detailed design first NEEDS it (§7c writes it, §10 reads it
— the first of those two designs proposes ownership; §14 row).

---

# Module sections

Template per module: current responsibility → current couplings →
target generic responsibility → module-local config (CONCEPTUAL groups,
no field freeze) → inputs vs config vs runtime state → target behavior
flow → TIDMAD compatibility contract → generic contrast fixture →
convergence candidates → dependencies → detailed-design follow-up.

## 4. Module: Dataset & Sample Topology

`execute_tools/dataset_config.py`, `sample_set_builder.py`,
`data_paths.py`, + the SampleSet type and derived-artifact INDEXING.
(`array2h5.py` is the DELIVERABLE writer — Deliverable Contract, §3.1 —
covered by audit C but not §4-owned.)

#### 4.1 Current responsibility
Declares THE dataset as module-level singleton `TIDMAD`
(dataset_config.py:292-304) with bare constants re-exported (:302-304;
ledger status PARTIAL — "hardcodes 'the one dataset' at every import
site"). Builds SampleSets `dict[int→list[int]]` (snapshot/anchors/
target). Resolves data dirs from `tidmad_data_config.yaml`
(import-time, silent example-fallback; data_paths.py:24-40). Writes
HDF5 via `create_abra_file` with hardcoded attrs
(voltage_range_mV=80, fs=1e7, N=2e9 split; array2h5.py:26,44-72).

#### 4.2 Current TIDMAD couplings (top evidence)
- Singleton + constants consumed by ≈10 modules (scoring_utils :315,
  :571; workload_resolvers; both engines; health checks re-hardcode
  `range(20)` ×3 despite `num_files` existing — pearson_dispersion
  .py:34, per_file_output_std.py:30, spectral_peak_ratio.py:39).
- Two file families, one index space; `validation_file_pattern` dead
  (zero consumers — the seam-without-consumer anti-pattern); raw
  validation name inlined in the SCORER worker (scoring_utils.py:389,
  444) and inference (:583,782).
- Divisibility rule enforced at 3 layers; seg defaults re-appear as
  bare `.get(...,40000)` in 4+ places after the B1 resolver existed.
- Files NOT exchangeable: anchors [0,10,19] "frequency extrema", health
  peek [3,10,17] "band triplet", scripts band tables — three informal
  encodings of V7 with no owner.
- Trial packing asymmetry (denoised local-index vs raw original-index;
  scoring_utils:387-399,446-457) — a load-bearing layout contract
  between inference and scoring with no named owner.
- Derived-artifact template re-inlined ≥6 sites (tuner :1083, :5401;
  inference_single :561-563,:827-834; sandbox cleanup :1652;
  denoising_score_single :139-146; run_comparison :445).
- SampleSet JSON round-trip: keys become strings; every consumer
  re-ints differently (train_engine :158-159,:300-331; inference :559,
  :609-613; scoring :577-587; resolvers; estimators; tuner :4426).
- `data_shape_class = "psd{}_seg{}_files{}"` is the measurement
  interchangeability key (data_paths.py:93-97) — framework mechanism
  keyed on dataset geometry.

#### 4.3 Target generic responsibility
One owner answering: what files exist (topology/identity/families);
how a file decomposes into addressable samples (geometry + legality);
which samples belong to which selection (split semantics/strategies +
packing rules); what systematic structure exists (named groups); how
derived artifacts are INDEXED by input identity — their form/naming
belongs to the Deliverable Contract (§3.1). Consumers receive a
RESOLVED profile object — never module-level constants.

#### 4.4 Module-local config (conceptual — CANDIDATE groups; the
systematic-structure and encoding groups below overlap
§14 rows whose merge evidence is still pending, so §4's detailed
design must re-confirm each against §14's rules before freezing it)
- Topology: file families + index spaces + counts + patterns (the
  validation pattern finally gains its first consumers: scorer +
  inference read paths); physical-vs-usable sizes.
- Sample geometry: the dataset's OWN decomposition (file → PSD
  segments) + the sample-shape LEGALITY function; NOT segmentation_size
  itself, which is a proposer-owned model hyperparameter (finding 17) —
  only its legality rule lives here. Plus the dtype+offset encoding
  DECLARATION (derived by §5/§7).
- Split semantics: strategy DEFINITIONS, per-family selection rules,
  packing rule (trial asymmetry made explicit), group-aware anchor
  selection replacing the [0,10,19] literal. NOT portions: portions are
  LLM-planned/operator-clamped runtime inputs (plan.trial_portion,
  tuner :2134, VRAM-ceiling clamp :4323) — adversarial-review finding 1
  corrected a draft that listed them as config, violating §0.4.
- Systematic structure: named groups as data (bands), consumed by
  anchors, health peeks, interpretation, scripts.
- Derived-artifact INDEXING only (Rev 2, §3.1): how deliverables are
  keyed by input identity. The Deliverable Contract itself (naming
  template, layout, dtype, attrs — the ≥6 inlined copies) is a
  DISTINCT contract whose owner is UNKNOWN → §14 ledger row; §4 does
  NOT own it merely because TIDMAD's inputs and outputs share HDF5
  conventions.
#### 4.5 Inputs vs config vs runtime state
Inputs: DataScope, seeds, portions chosen by plan. Config: the five
groups above. Runtime: resolved SampleSets, seed derivations, packing
maps, data_shape_class values, resolved dirs.
#### 4.6 Target behavior flow
`task dataset profile (config) + DataScope + seeds (inputs) →
resolution → {topology object, SampleSets, artifact namer, group map}
→ consumed by engines/scoring/health/estimators`.
#### 4.7 TIDMAD compatibility contract
Default profile deep-equals today's singleton (constants pinned — a
NEW pin, none exists); SampleSet sha16 goldens unchanged; filename
renders byte-identical; anchors artifact untouched; +128/int8 encoding
declaration produces byte-identical tensors; `data_shape_class` strings
unchanged (measurement-store keys must not be invalidated).
#### 4.8 Generic contrast fixtures (ATOMIC ladder, Rev 2)
One axis per fixture; the detailed design picks the minimum subset:
- 4.8-A topology only: 3 files, single family, TIDMAD geometry
  otherwise unchanged.
- 4.8-B sample geometry only: 20-file two-family shape, non-10M
  decomposition length.
- 4.8-C group semantics only: TIDMAD shape with a DIFFERENT declared
  group map (proves anchors/peeks read groups, not literals).
- 4.8-D truth availability only: TIDMAD shape, no truth channel.
Seeds already in-tree (corrected, finding 18d): the
non-TIDMAD `_cfg` helper in test_dataset_config.py:15-23 (used at
:74,:122), and — the actual seam-with-first-consumer precedent §0.8
asks for — test_dataset_contract.py:32-42's non-TIDMAD config probed
through the REAL training loader's resolved path (:63-75). Plus the
TIDMAD-layout-only `synthetic_h5` conftest generator to be
generalized.
#### 4.9 Convergence candidates
SampleSet type ownership (15 consumer families); sample-shape legality
(proposer duplicates); group semantics (health/anchors/scripts);
the DELIVERABLE CONTRACT (Rev 2 — moved OUT of §4 ownership, §3.1);
data_shape_class (runtime-control). DO NOT MERGE YET — record only.
(Second pass F7: every row here obeys the §14 ≥2-designs bar.)
#### 4.10 Dependencies / follow-up
First PROFILE module in the roadmap (§15 step 2; 6-P precedes it per
§15.0) — nearly everything reads it; Stage A is injection-with-TIDMAD-default, killing bare
constant imports module-by-module (the ledger's REMAINING entries).
Detailed design: `docs/design/generic_framework/pr_dataset_topology.md`.

## 5. Module: Model/Loss Contract & Plugin Registry

`ml_models/models_sandbox.py`, `models_format_sandbox.py`,
`loss_models_sandbox.py`, `plugin_loader.py`, `agent_generated/`
loaders, `core/inference_defaults.py`. (Audit G.)

#### 5.1 Current couplings (top evidence)
- 256 hardcoded inside every builtin (models_sandbox:226,288,355,379,
  402,478,493,525-556,631,677); no config exposes class count; the only
  declarative surface (task_config num_classes) reaches prompts only.
- Dtype at model boundary NAME-keyed: fcnet .float() vs .long().
  Corrected inventory (adversarial finding 9): production branch sites
  are train_engine_sandbox:572,618,770,981; inference_single:201,337,
  388; evaluate_time_skill wrapper:259,384,414; plus prose/name sites
  check_config_format_skill/wrapper.py:22, proposal_helpers.py:106,152,
  workflow_validation.py:22. Estimators already migrated to signature
  introspection (training_skill/estimator.py:305-319 — the Stage-A
  precedent).
- output_type alphabet {classifier,regressor,hybrid}: hybrid has ONE
  impl (builtin fcnet), CANNOT be generated (schema Literals + validator
  exclude it) — plugin_loader:82's hybrid acceptance is a dead branch
  for plugins. Disposition UNKNOWN (deliberate restriction vs drift) —
  decided in this module's detailed design.
- Two tolerance tiers: plugin_loader silently defaults missing
  PLUGIN_OUTPUT_TYPE→classifier (:81-87) vs fail-closed get_output_type
  (:192-214). Regime disposition (second pass, F1): the silent
  classifier default is a regime-A adapter for legacy on-disk plugins;
  §5's detailed design decides its regime-B fate (fail closed for
  task-bound loads) — it is NOT left undecided.
- Loss: closed Literal(5); families {ce,focal,focal_cw}/{smooth_l1};
  FocalLoss1D paper-frozen; loss math class-agnostic (shape[1]) but
  estimators hardcode ×256; custom-loss config instantiated with ZERO
  args (proposer hyperparams never reach it — acknowledged TODO,
  loss_models_sandbox:253-276); dtype-registry "float" arm has zero
  on-disk implementations.
- Second builtin name→config map duplicating MODEL_REGISTRY
  (models_format_sandbox:338-345); registry population is an import
  side effect with bare except (models_sandbox:749-755); class-weight
  histogram fixed 256 bins with no direct unit test
  (train_engine:80,126,196).

#### 5.2 Target generic responsibility
Contract authority: per-output_type I/O forms DERIVED from the task's
declared encoding/class-count; loss families per output_type +
custom-loss probe recipe + hyperparameter passing; dtype routing by
CONTRACT (killing fcnet name branches, following the introspection
precedent); single builtin catalogue; explicit registration (reducing
import side effects where cheap).
#### 5.3 Module-local config (conceptual)
Task model-I/O profile (class count, output forms; the input ENCODING
is declared in §4 and this module owns only its model-contract
DERIVATION — the one consistent ownership story, matching §3 V3 and
§14); loss-family map + probe recipes; builtin catalogue.
#### 5.4 TIDMAD compatibility
Builtin forwards byte-identical (frozen FocalLoss1D untouched);
registry contents identical under the TIDMAD profile; name-branch
removal behavior-proven per the estimator precedent. NOTE (finding 9):
test_no_model_name_branches scans only FOUR paths (:47-53 — the vram
skill, two estimators, inference_defaults), so its empty pending list
is evidence about THOSE paths only; extending its targets to each
newly-cleaned file is part of this module's Stage-A acceptance, not
pre-existing evidence.
#### 5.5 Contrast fixtures (ATOMIC ladder, Rev 2)
- 5.5-A class count only: num_classes≠256 classifier, int64 input.
- 5.5-B input contract only: contract-keyed float-input model at 256
  classes (kills the fcnet name branches attributably).
- 5.5-C output type only: regressor beside classifier (seed exists:
  `test_generated_model_transport_chain.py` pair).
- 5.5-D custom-loss capability separately: a regressor custom loss
  (impossible today — probe classifier-shaped).
#### 5.6 Convergence candidates
ForwardContract ownership (shared reads from §6 candidate creation);
estimator ×256 terms (§7d derives from this module's profile).
#### 5.7 Follow-up
`docs/design/generic_framework/pr_model_output_contract.md`.

## 6. Module: Candidate Creation (Proposer → Implementor → Validator)

(Audit D; see also §5 for the contract it consumes.)

#### 6.1 Current couplings (top evidence)
- The 256-class contract exists as ≥9 independent literals across
  validator probe (`_PROBE_NUM_CLASSES=256`, FU-A-1 documented deferral
  ":new transport required"), probe shapes (1,256,64)/T=64, implementor
  self-check + TEST_TEMPLATE + `_OUTPUT_CONTRACT_COMMENTS` (written
  into every generated plugin), PROPOSAL_COMMIT_PROMPT ("256 denoising
  bins is contract-fixed" — actively PINNED by
  test_contract_reassertion.py, meaning today's tests DEFEND the
  hardcode), validator LLM prompt, plugin_loader docstring, compat
  error strings.
- segmentation_size proposer-owned/implementor-forbidden with dataset
  legality reaching into DATASET_CONFIG (proposal.py:1113-1128).
- forbidden_pattern_skill assumes named time axes + "T ≥ 80,000".
- Personas/budgets hardcoded ("signal denoising"; "<10 GB VRAM, <100M
  params" — contradicting the runtime [HARDWARE CONTEXT] block that
  already exists).
- Custom-loss dummy probe classifier-shaped only (a declared-regressor
  custom loss cannot pass — genuine gap).
- Already generic (preserve as Stage-A precedents): declared
  output_type flows end-to-end and probes DERIVE shapes from it;
  name-blind compat; fail-closed get_output_type; {TASK_BACKGROUND}/
  {OUTPUT_SHAPE} injection on 2 of 3 prompt surfaces; PR E funnel
  name-blind on system-minted candidate_id.

#### 6.2 Target generic responsibility
Turn context into validated plugins against the DECLARED model I/O
contract (§5) — no shape/class literal in templates, probes, prompts,
or generated artifacts; candidate constraints (budgets, forbidden
patterns) as per-task config.
#### 6.3 Module-local config (conceptual)
Candidate-creation contract view (probe tensor recipes, expected
shapes per output_type — derived from §5); per-task forbidden-pattern
lists; prompt task blocks (commit-prompt facts) — rendered via §6's
own templates but sourced from the task profile (§13); NOTE (Rev 3):
the PROPOSER's prompt task blocks (commit-prompt facts) moved to 6-P,
step 1 — this section's remaining prompt scope is the implementor/
validator surfaces (6-M, step 4). Resource-budget
prose is NOT config (adversarial finding 2): the proposer already
defers to the live [HARDWARE CONTEXT] block
(ml_model_proposal_agent.py:282-284, rendered from runtime hardware
context + vram_budget_gb at :1049,:1512) — the correct precedent. The
one stale literal (implementor :363 "<10 GB VRAM, <100M parameters")
is fixed by DERIVING from the same runtime block, not by a new field.
#### 6.4 TIDMAD compatibility
Rendered proposer/implementor/validator prompts EXACT golden equality;
generated plugin file byte-identical for a fixed spec under the TIDMAD
profile; validator verdicts identical on existing fixture plugins.
Test-disposition nuance (finding 13; re-assigned by the 3rd review,
F4): contract-reassertion's pins are TEMPLATE-structure pins (regex
over PROPOSAL_COMMIT_PROMPT); they break at STEP 1, so the semantic
change to PROFILE-PARAMETERIZED pins is stated by 6-P's design
(`pr_proposer_hypothesis_space.md`), not deferred to §13's.
#### 6.5 Contrast fixtures (ATOMIC ladder, Rev 2)
- 6.5-A class count only: num_classes=16 classifier — probes/templates
  derive; the 256 literals are dead paths.
- 6.5-B shape/T only: T=128 at 256 classes (validator/implementor probe
  recipes derive T).
- 6.5-C output type only: declared-regressor generation end-to-end.
- 6.5-D custom-loss capability: the regressor custom loss (with 5.5-D).
#### 6.6 Convergence candidates
Model I/O contract (with §5); sample-shape legality (with §4).
(Resource-budget prose REMOVED — resolved by the first adversarial
review, finding 2: derive from the runtime [HARDWARE CONTEXT] block;
§14 row marks it resolved.)
#### 6.7 Follow-up
6-P (step 1): `docs/design/generic_framework/pr_proposer_hypothesis_space.md`.
6-M (step 4): `docs/design/generic_framework/pr_candidate_creation_contract.md`
(includes the FU-A-1 transport and the hybrid-alphabet decision with
§5).

## 7. Module: Hyperparameter Tuner — source-grounded submodule decomposition

The tuner is NOT one module. From audits E1/E2 (`run()` = :3597-6277
of 6868 lines; 19 planning responsibilities + 8 execution/resource
clusters), the real decomposition:

### 7a. Planning & round policy
P1-P8,P10-P12,P14-P19 of audit E1: startup/invariants; formal-reference
resolution; prompt-input assembly; plan parse + 6-stage override chain
(plan_overrides → mode chain → scope normalization → epoch clamp →
formal replacement → validation clamp); round/attempt/fail policy;
incumbent + skip/bypass gates; guardrails; degeneracy; records/memory;
reflection; iteration feedback; finalization (4-track best).
**Task couplings**: metric name `denoising_score` across ~40 sites;
-inf bootstrap (anti-phantom, parametrized-tested); 5% efficiency band
(:5486); "baseline" exp_id substring (:5424 + PLANNER_PROMPT rule);
planner/reflector prompt families (5-model roster, collapse advice
with focal α/γ + class-127 + gate-name substrings, 4000/200 segment
anchors, CH1/CH2 semantics — audit B); file_index=6 legacy on every
record; dead CLI --trial_strategy/--eval_strategy.
**Target**: policy engine parameterized by a METRIC HANDLE (§10) and
prompt task blocks (§6/§13); round/attempt mechanics are already
framework-invariant. **State hazard to fix in decomposition**:
`resolved_action` written 5 levels deep, never reset between attempts.
Finding 16: the documented remedy objects (AttemptTransition/
AttemptDecision, :295-345) have ZERO production consumers — only
test_control_boundary.py imports them — i.e. the hazard's fix is
itself a §0.8 consumer-less seam today; 7a's design must WIRE them or
REMOVE them, never leave the third state.
**Compatibility**: planner/reflector rendered prompts golden-equal;
override-chain resolution deep-equal; record fields unchanged.
**Fixture**: a lower-is-better scalar metric on the stub task — proves
direction/threshold logic flows from the metric handle.

### 7b. Data selection & sample-set construction
P5,P7-P9: strategy resolution, TrialConfig, seeds/ordering, SampleSet
build, segment accounting. Couplings: DATASET_CONFIG import (:76),
anchors-required-in-trial (:3800-3808), divisibility validation
(:1099-1128), legacy single-file fallback (:4428-4433).
**Target**: consume §4's resolved profile; zero direct singleton reads.
**Compatibility**: SampleSet hashes + trial_config JSON deep-equal.
**Fixture**: §4's 3-file dataset flows through TrialConfig→SampleSet.

### 7c. Execution contracts (training/inference/scoring launches)

**Sequencing boundary with the metric interface (Rev 2, operator
question resolved from source):** step-5 7c genericizes launch
MECHANICS (argv/file-IPC/sentinels), dataset/deliverable TRANSPORT, and
model-contract ENCODE/DECODE (the +128/argmax family — the decode rule
is already contract-keyed at inference_single:262-273). It does NOT
touch scorer selection or metric semantics: the scoring launch keeps
invoking `denoising_score_single.py` exactly as today, TIDMAD-bound,
until step 6 lands the metric interface. This separation is viable in
source because the scoring spawn is already an isolated argv contract
(sandbox_executor:1792-1817) whose internals 7c never needs to open.
Scoring is NOT generic after step 5 — only its launch plumbing is.
Audit E2-A/B/C + §9: skill wrappers splat active_params; sandbox argv/
file IPC; per-file inference loop; int8 HDF5 writes; sentinel protocol.
Couplings: filename templates at the engines; +128/argmax/int8 in
inference_single (:188-189,:264-284); fcnet branches; fix-mode
input_size=40000; class-weight 256 bins in train_engine.
**Target**: engines consume the Deliverable Contract — at step 5 as a
PROVISIONAL extraction of the TIDMAD instance (regime-A; §14 row,
second pass F6), with §7c's design proposing final ownership — + §5's
contract (decode
rule per output_type is ALREADY contract-keyed at :262-273 — extend the
precedent); launch mechanics stay framework.
**Compatibility**: argv/file-IPC byte-identical for TIDMAD; artifacts
byte-identical; sentinel semantics untouched.
**Fixture (atomic, second pass F4)**: single axis = deliverable
transport: under the TIDMAD profile with a renamed deliverable template
(from the provisional contract), the ENGINES write/clean exclusively
via the contract — no inlined template executed in engine/cleanup
code. Scorer-side `abra_*` literals (scoring_utils:389,:444)
legitimately REMAIN until step 6 per the boundary note; the Rev-2
fixture wording ("no abra_* literal executed") was unsatisfiable at
step 5 and is corrected. Dataset-axis coverage comes from 4.8-A via
7b, not from this fixture.

### 7d. Resource & time planning (VRAM/time gates, estimators)
Audit E2-D/E: analytic estimators (partly production-dead per
:123-128), live probe gate + batch resolver (name-blind), time
aggregator + warmup + store reuse + shared decision policy; workload
resolvers as the one source of workload truth.
Couplings: ×256 logits/one-hot terms (training est :402,:436; inference
est :161); PSD-unit `PSD_SEGMENT_LENGTH // seg_size` in 5+ places;
×2.7 ratio (N=2 archs); 800k intensity cap; seg defaults 40000/1000;
candidate batches (64..1); probe tensor recipes [B,T]long/[B,256,T].
**Classification discipline**: calibration constants (×2.7, caps,
overheads, batch table) are RUNTIME/CALIBRATION state frozen as
constants — they migrate to calibration records keyed by
hardware/workload-class, NOT to task config. Task-shaped TERMS
(×256, PSD unit, probe shapes) derive from §4/§5 profiles.
**Compatibility**: forecasts byte-identical under TIDMAD profile
(deep-equal breakdowns — the PR G parity-pin pattern generalizes);
policy identities unchanged.
**Fixture**: contrast profile changes the derived terms; calibration
values unchanged.

### 7e. Measurement, verification & watchdog (runtime control)
Audit E2-F/G: measurement identity/spec/worker; prephase admission;
RT2 session/steady-state; watchdog. Couplings: gpu_measurement_data
channel roles + CLASS_INDEX_OFFSET=128 + abra_training glob
(:61-66,:117,:156); planned-identity defaults seg=40000/batch=1;
worker seg default; data_shape_class keying.
**Target**: measurement DATA feeding (what tensors a probe batch is
built from) derives from §4; identity/comparison mechanics stay
framework. Two sibling couplings the probe_wiring fix did NOT cover
(finding 19): core/runtime_control/bootstrap.py:516-520 (+ operator
message :233 naming a "readable TIDMAD directory") and
probe_production.py:17,210-212 still fall back to TIDMAD_DATA_DIR —
owned here. Most of this subsystem is genuinely runtime state — the
smallest task surface of the tuner.
**Compatibility**: identity hashes/comparability unchanged (the PR G
0.R.12 pin pattern); measurement-store keys stable.
**Fixture (atomic, second pass F4)**: single axis = measurement data
feeding: probe/measurement batches built from a contrast dataset
profile (4.8-B geometry) while identity keys and comparability stay
byte-stable — proves the data-feeding derivation carries no TIDMAD
residue independent of any other axis.

### 7f. HealthGates → §8 (its own module; fires at tuner round
boundaries but owns independent semantics).

Sequencing inside the tuner: 7b (after §4) → 7d (after §4+§5) → 7c;
THEN §10 lands the metric handle; THEN 7a → 7e (smallest task
surface). The §15 steps encode this: tuner data/execution = step 5,
metric interface = step 6, tuner policy = step 7.
Each subphase is its own PR with its own detailed design under
`docs/design/generic_framework/pr_tuner_<submodule>.md`. The
responsibility-oriented decomposition rule (CLAUDE.md, binding) governs
every extraction: typed boundaries, reachability tests, no new
responsibilities into `run()`.

## 8. Module: HealthGates

`execute_tools/health_checks/` + `configs/health_checks.yaml`.
(Audits E2-H, B, J.)

#### 8.1 Current couplings
The runner/registry/evaluation/eligibility machinery is generic; the
CHECKS are int8-amplitude semantics end-to-end: `n_unique_int8_values`
(min 25), dominant int8 bin ≥0.95, `_MV_PER_LSB = 40.0/128.0`
duplicated ×4, `range(20)` defaults ×3 (despite DatasetConfig.num_files
existing), peek triplet [3,10,17] as an undeclared band sample, channel
literal `channel0001` in the peek walkers, class-127 reason text with
the phantom score literal (`output_diversity.py:76-77`), spectral check
importing the TIDMAD singleton for fs. Check IDs restated in planner
prose (prompts.py:72-75) and interpreter fingerprints (:171).
#### 8.2 Target generic responsibility
Runner/policy/aggregation stay framework. Each CHECK declares the
task-profile inputs it needs: file groups from §4 (NOTE: this design
IS the "first group-aware consumer" the §14 systematic-groups row
names as its required evidence — it supplies that evidence, never
presumes the merge); encoding + mV scale + channel layout of the
DELIVERABLE from the Deliverable Contract (§3.1 — the peeks read the
denoised artifact, _peek.py:93-100, not the input dataset) and per-task thresholds live in the task's health
config. Collapse-detection checks become the first family of TASK
health plugins, with TIDMAD's six as the golden instances.
#### 8.3 Compatibility
`health_checks_effective.yaml` sha-pinning MECHANISM untouched; TIDMAD
verdicts identical on fixture outputs; gate IDs stable (records +
prompts reference them). HARD BOUNDARY (finding 12a): the run-
invariants lock hard-refuses a changed health-config sha against an
existing workspace (core/run_invariants.py:475-488, remediation =
"start a new workspace") — so this step's content changes MUST land at
a fresh-workspace boundary between campaigns; the detailed design
states this migration note explicitly.
#### 8.4 Fixtures (ATOMIC ladder, second pass F4)
- 8.4-A group semantics only: TIDMAD-shaped outputs, peek files
  resolved from a DIFFERENT declared group map.
- 8.4-B encoding declaration only: float-valued output → int8-diversity
  checks inapplicable-by-declaration (no other axis varied).
- 8.4-C generic-check firing only: a dispersion check fires on the same
  declared-float output that 8.4-B established.
#### 8.5 Follow-up
`docs/design/generic_framework/pr_health_check_task_profile.md`
(absorbs the stale collapse_detection_framework_generic.md intent —
that doc's phantom-fingerprint/byte-identity machinery remains
NOT-built and is NOT resurrected without new evidence).

## 9. Module: Execution Infrastructure (sandbox, subprocesses, hardware)

`core/sandbox_executor.py`, engines' process contracts,
`core/subprocess_env.py`, `core/hardware_context.py`,
`core/run_invariants.py`, `core/resume.py`. (Audit H.)

#### 9.1 Current couplings
Mostly framework-invariant (sentinel protocol, RLIMIT_AS, watchdog,
session semantics, plugin transport, invariants lock, resume). Task
leaks: `dirs["data"]=TIDMAD_DATA_DIR` (:1055-1060); cleanup glob on the
denoised template (:1652); RSS ceilings justified by full-scope int8
arithmetic (:105-121) — calibration presented as framework constants;
relative-script-path + cwd assumption; `cached_models` name re-derived
independently in the child; import-time data-dir resolution with silent
example fallback (data_paths.py:24-40); device index-0 binding;
OOM regex string-sniffing.
#### 9.2 Target
Task-shaped elements: data dir wiring flows from §4; the cleanup
globs' TEMPLATE flows from the Deliverable Contract (§3.1/§14 — §9 is
a READER of that contract, sandbox_executor:1650-1652), §4 supplying
only input-identity indexing;
per-role resource ceilings become explicit calibration config with
recorded provenance (NOT task config); the rest stays framework.
UNKNOWN (needs its detailed design): whether the probe worker's
missing-`env` asymmetry (probe_subprocess.py:336-341 vs the measurement
runner) is deliberate. Regime disposition (second pass, F1): the
import-time silent example-fallback in data_paths.py:24-40 is regime-A
adapter behavior; §9's design classifies its regime-B fate (a bound
task with no data config fails closed, not silently on the example).
#### 9.3 Compatibility
argv/IPC/sentinels byte-identical; per-role rlimits resolve to the
SAME VALUES for the TIDMAD profile — and any calibration config must
define its precedence against the EXISTING override seam
(SIDERIUS_SUBPROCESS_RSS_GB wins over _ROLE_DEFAULT_RSS_GB,
sandbox_executor.py:134-143; finding 14: a third layer with unstated
ordering is not acceptable); kill/cleanup semantics untouched
(operator-stop-critical plain-vs-session launch split preserved).
#### 9.4 Follow-up
`docs/design/generic_framework/pr_execution_infrastructure.md`
(late in the roadmap; highest blast radius, smallest genericity gain).

## 10. Module: Scoring & Metric Interface

`execute_tools/scoring_utils.py`, `scoring_helpers.py`,
`denoising_score_single.py`, `per_file_best.py`, reference artifacts,
`nodes/scoring_reference.py`, + the authority layer. (Audit F.)

#### 10.1 Current couplings
The frozen formula (PSD→peak→SNR→per-segment anchor-normalized→linear
grand-mean→log_5.27) with its deliberate legacy literals (Nyquist 5e6;
volt/(2·128); attrs always read from channel0001; NaN guard); log base
duplicated ×3 (one flagged REMAINING); raw filename inlined in the
scorer worker; length-20 dense file_vector; metric NAME `denoising_
score` as schema fields across tuner/interpretation/orchestration/
dashboard; direction (higher-better) implicit in ~8 consumer families;
score-table machinery (Impact_Score/Linear_Weight — REQUIRED by prompt
tests); the committed anchor + 42 reference JSONs; scalar-per-record
authority coupling; metric DIRECTION is additionally hardcoded in
consumers the draft's first pass missed (finding 11):
dashboard/data_sources/local_json.py:245 sorts descending,
dashboard/data_sources/base.py:119 documents "higher is better",
dashboard/api/models.py:79,151,220 carry the field; plus
core/resume.py:438 and workflows/model_exploration.py:2740 use bare
`>` comparisons. The §10 design must state which of these the metric
handle REACHES and which remain TIDMAD-only until the D1 migration —
the §10.5 lower-is-better fixture cannot honestly claim coverage of
consumers it does not reach. The authority layer itself is PROVEN
metric-blind
(ScientificAuthority consumes 3 non-score facts; frozen 3×3×3 matrix
test) — a genuine framework invariant to preserve.
#### 10.2 Target generic responsibility
Define the metric interface FROM the TIDMAD instance (genericity
contract Seam 4, placeholder until now): a named metric with per-sample
vector, scalar aggregate, direction, comparability rules, reference
baselines, and a scoreability contract on the deliverable artifact.
CORRECTED by adversarial review (finding 7): today NO explicit
scoreability validation exists — the int8-channel check at
inference_single.py:57-86 is `_is_complete_trial_output`, a
crash-resume REUSE guard gated on `--reuse_complete_outputs` (:566),
never consulted by scoring; a wrong-shaped artifact simply errors
inside the scorer worker. The metric design defines scoreability
FRESH and must NOT relocate the reuse guard. Also (finding 8): a
metric-identity precedent already ships — per_file_best.py:358-362
emits `metric_id: "tidmad_denoising_score"`, `score_transform:
"log"`, `log_base` in a schema-versioned artifact with its key set
pinned (test_per_file_best.py:719). The interface EXTENDS that
precedent (extract-from-working-system), never a parallel invention.
The frozen TIDMAD scorer becomes instance #1, byte-identical.
Generic metrics plug in BESIDE it.
#### 10.3 Module-local config
Metric identity (name/direction/aggregation semantics); reference
artifact locations; scoreability contract. NOT config: s_max, log base,
formula internals — those are the frozen instance's OWN constants.
#### 10.4 Compatibility
Frozen-formula byte identity (existing pins + the offline scalar
baseline + real_run legacy parity); `denoising_score` FIELD NAMES in
schemas/records are a schema-compatibility surface — renaming is a
MIGRATION and is NOT authorized by this roadmap (deferred, §16);
dashboards/prompts keep reading today's fields for TIDMAD.
#### 10.5 Fixture
A scalar lower-is-better metric on stub outputs, entering records and
incumbent selection through the metric handle.
#### 10.6 Follow-up
`docs/design/generic_framework/pr_metric_interface.md`.

## 11. Module: Interpretation & Cross-Iteration Knowledge

`nodes/result_interpretation_agent/`, `nodes/interpretation_helpers.py`,
knowledge/vocab/cache channels. (Audits F, A.)

Couplings: score-table prose framing (Log-of-Mean trap restated in TWO
prompts; Impact_Score-descending reading discipline; "file 17"
exemplar); condensed-summary field names (`best_denoising_score` etc.);
outcome bands assuming positive higher-better scalar
(interpretation_helpers.py:284-286 — latent sign bug recorded); metric
grammar `denoising_score`/`file_vector[N]`/`mean(file_vector[N:M])`
(:309-355); "4000 segments" data-volume anchor. The cross-iteration
transport itself (vocab, findings, knowledge cache, fingerprints,
physical rejections) is task-agnostic mechanics.
Target: prompts split framework/module/task blocks (golden-equal for
TIDMAD — 3 of the 4 existing goldens live here); table rendering +
prediction grammar parameterized by the §10 metric handle.
Fixtures (atomic, second pass F4): 11-A metric identity only (stub
metric handle, table stays per-file); 11-B table indexing only (TIDMAD
metric, per-sample rows instead of per-file).
Follow-up: `docs/design/generic_framework/pr_interpretation_task_
blocks.md`.

## 12. Module: Orchestration & Chain

`workflows/model_exploration.py`, `run_one_iteration.py`,
`core/resume.py`. (Audit A.)

Largely task-agnostic already (§1) — with one core/ exception the
first audit missed (finding 10): `core/campaign_artifacts.py` is
task-coupled three ways (denoising_score requirement :39; band-triplet
literal :57; TIDMAD import :88-92) and this module owns its cleanup
(consuming §4's group map and §10's handle). Remaining work: the
module-level
TIDMAD import + full-scope checks parameterized via §4; `file_index=6`
and construction-probe literals (focal/16000) via §4/§5 profiles;
`*denoising_score*` reads via §10 handle; the dead tune→interp protocol
either gains its production caller or is removed (decide in detailed
design — do not keep a dead seam); legacy source-path template retired
or profiled. The caller-resolves-capability pattern
(run_one_iteration:1858) is the correct genericity precedent — the
launcher owns task binding, the workflow stays generic.
Compatibility: iteration choreography byte-stable (k9/l_fail canned
choreographies keep passing unmodified); resume inventory field-stable.
Follow-up: `docs/design/generic_framework/pr_orchestration_task_
binding.md`.

## 13. Module: Task Profile & Prompt Assembly (incl. lit review)

`configs/task_config.yaml` + `workflows/task_config.py` +
`agent/prompts.py` + `agent/prompt_templates/` + lit-review configs.
(Audit B.)

#### 13.1 Current state (the decisive facts)
`task_config.yaml` parameterizes exactly TWO things (task_description,
forward_contract) reaching 5 injection sites. FIFTEEN hardcoded prose
families remain (audit B §2; the PROPOSER family below moved to 6-P,
step 1, per §15.0): the fully-hardcoded PROPOSAL_COMMIT_
PROMPT; the entire loss-generation prompt path (zero task_config
reads); validator prompt + probe literal; planner roster/collapse
advice/data-volume anchors/CH1-CH2 semantics; REFLECTOR_PROMPT (no
TASK_DESCRIPTION at all); personas; SQUID worked examples in lit-review
formats; full-spectrum doctrine; duplicate byte-equal task description
in lit_review_config.yaml (TWO files to edit one task) + stale
SIDERIUS_TASK fallback prose + TIDMAD root paper pin; description.md
files with axion/SQUID prose; hardware/scale numbers contradicting the
runtime hardware block.
#### 13.2 Target
EXTEND the working mechanism, don't replace it (finding 15 corrected a
draft that invented a three-layer assembly with no in-tree precedent):
the production pattern is single template + placeholder substitution
(workflows/task_config.py:150,171; lit-review __init__.py:305,402,627;
proposer template_vars :1561-1614), and it already delivers
task-agnosticism at its five injection sites. Genericization = MORE
placeholders/blocks per node, each landed with its consuming template
in the same PR. The task profile grows per-node BLOCKS (not a
mega-config): each module's detailed design declares which blocks it
consumes. The
lit-review duplicate collapses into one source. Model descriptions get
task-block seams.
#### 13.3 Compatibility — THE golden discipline
For every producing site: `render(today) == render(new assembly +
TIDMAD blocks)` EXACT, whitespace included. Existing goldens (4) are
kept; the missing goldens (planner, reflector, commit, implementor
code/loss, validator, lit-review) are captured in roadmap step 0.
Test disposition (refined by finding 13): (a) VALUE pins that defend
hardcodes (contract-reassertion tokens; "denoising_score must remain")
become PROFILE-PARAMETERIZED pins on rendered output; (b) ABSENCE pins
(e.g. `"TIDMAD dataset" not in PLANNER_PROMPT`,
test_planner_prompt_task_config.py:52-59) STAY template-scoped — their
purpose is anti-hardcode proof of the template layer, and rendered
TIDMAD output legitimately contains SQUID prose; re-targeting them
would make them vacuous. Nothing is deleted.
#### 13.4 Fixtures (ATOMIC ladder, second pass F4)
- 13.4-A task-description text only: the in-tree _ALT_TD string with
  the TIDMAD forward contract, rendered through every producing node
  with zero SQUID residue in the description-derived blocks.
- 13.4-B forward contract only: the in-tree regressor ForwardContract
  (test_task_config.py:267-292) with the TIDMAD description.
#### 13.5 Follow-up
`docs/design/generic_framework/pr_task_profile_prompts.md` (likely
split per node group; the proposer group is 6-P's doc, step 1).

---

## 14. Cross-module convergence ledger

Default: **DO NOT MERGE YET.** A merge becomes a candidate only after
≥2 completed module designs show same semantics, lifecycle, source of
truth, validation, ownership — preferably with contrast-fixture
evidence.

| Concept | Modules needing it | Current meanings | Same semantics? | Candidate future owner | Merge now? | Evidence needed |
|---|---|---|---|---|---|---|
| Model I/O contract / ForwardContract | §5, §6, §7c, §7d, §13 | prompt-rendered dict; probe recipes; estimator terms; decode rule | UNKNOWN | §5 | NO | §5+§6 detailed designs complete |
| SampleSet type + JSON key coercion | §4, §7b, §7c, §10, estimators | dict[int→list[int]] with per-consumer re-int | YES (mechanical) | §4 | NO — a typed wrapper INSIDE §4 is ordinary Stage-A refactoring, but cross-module adoption is a merge and follows the rule | ≥2 completed designs (§4 + one consumer module) |
| Systematic groups (bands) | §4, §8, §11, scripts | anchors triplet / peek triplet / band tables | UNKNOWN (three ad-hoc encodings) | §4 | NO | first group-aware consumer in §8 |
| DELIVERABLE CONTRACT (naming/layout/dtype/attrs/completeness) | §7c (producer), §10 (scoreability reader), §8 (peek reader), §9 (cleanup), scripts | ≥6 inlined template copies; no owner today | YES (one contract) | **UNKNOWN** (Rev 2): §7c and §10 are the candidates. Second-pass refinement (F6): at step 5, §7c may extract the TIDMAD deliverable instance PROVISIONALLY (regime-A adapter) and propose ownership in its design; FINAL ownership is confirmed by the owning design, which also lands the non-HDF5 deliverable rung as part of ITS fixture ladder. §4 keeps only input-identity indexing | NO | the §7c or §10 detailed design + the non-HDF5 deliverable rung (owned by whichever design wins ownership) |
| Metric identity (name/direction/aggregation) | §7a, §10, §11, §12, dashboard | schema field names + implicit max() | YES (single metric today) | §10 | NO | §10 design + stub second metric |
| Sample-shape legality (divisibility) | §4, §6, §7b | 3 enforcement layers | YES | §4 | NO | ≥2 completed designs (§4 + §6, the duplicate site) |
| Seg-size fallback defaults (40000/1000) | §7d, §7e, §9, §6 | bare .get defaults post-B1-resolver | UNKNOWN (deliberate margins vs drift) | §7d resolver | NO | audit in §7d design |
| Value encoding (+128/int8/256) | §4, §5, §7c, §7e, §8 | independent literals | YES conceptually | §4 declares, §5 derives | NO | §4+§5 designs |
| Resource-budget prose (10GB/100M) | §6, §7d | prompt literals vs runtime hardware block | NO (prose vs measured) | NONE — derive from the runtime [HARDWARE CONTEXT] precedent (ml_model_proposal_agent.py:282-284); delete the stale implementor literal | resolved by review | n/a |
| data_shape_class measurement key | §4, §7e | geometry-derived string | YES | UNKNOWN (emit/consume split is a hypothesis) | NO | ≥2 completed designs (§4 + §7e) incl. the key-stability plan |
| Baseline-config authority | §7a prompts, run_comparison, legacy_baseline_configs.json | paper-spec JSON + prompt prose | UNKNOWN | out of scope (frozen paper alignment) | NO | none — stays frozen |

## 15. Incremental migration roadmap

### 15.0 Proposer-first reconciliation (Rev 3 — planner-level conflict, resolved from source)

```text
Prior operator decision (conversational; NOT previously recorded
in-repo — recorded here): after V21, genericization begins with the
PROPOSER, because the proposer defines the hypothesis space; then
proceed downstream. (The nearest in-repo statement is the V21 ledger's
governing judgement, v21_priorities.md:893: V21 "must begin by making
the hypothesis space the agent can explore real, symmetric and
executable" — philosophically aligned.)
Rev-2 order: Dataset (1) → Model/Loss (2) → Candidate Creation (3).
Conflict: planner-level; must be resolved before freeze.
```

Source dependency audit (no architectural preference used):

1. **Independent TODAY (no new upstream contract needed):** the
   proposer's task-content surfaces already have a LIVE injection seam
   — `{TASK_BACKGROUND}` + `render_forward_contract`
   (ml_model_proposal_agent.py:392-433, workflows/task_config.py:171)
   and the known-constraints block is ALREADY parameterized on the
   dataset-config OBJECT (`_format_known_constraints_block(
   DATASET_CONFIG)`, prompts.py:722; call site
   ml_model_proposal_agent.py:1569). The one fully
   hardcoded surface is the COMMIT prompt (zero placeholders).
   Extracting its task facts onto the EXISTING seam is golden-parity
   work with live consumers — no speculative contract. CORRECTED by the
   third review (finding 1): the commit prompt is a plain string with
   ZERO substitution today (passed verbatim at :1385), so extracting it
   is NEW placeholder/render work — an EXTENSION of the live
   single-template+placeholder mechanism (the sanctioned pattern, Rev-2
   finding 15), landed WITH its first consumer (the rendered prompt) in
   the same PR. Its sources of truth already EXIST: shapes/classes/
   task_type from ForwardContract (live, consumed); the loss-legality
   facts from models_format_sandbox's CLASSIFICATION_LOSSES/
   REGRESSION_LOSSES frozensets — today the VALIDATION authority only,
   gaining their first prompt-render consumer in this PR (prompt-side
   loss legality is currently re-prosed in ≥5 more places, which stay
   until their own steps). No dependency on §5's FUTURE config is
   created; §5 still owns the contract's SEMANTICS.
   Forbidden-pattern lists likewise. This slice = "6-P: proposer hypothesis-space
   & prompt surfaces" (it IS the proposer slice of §13, pulled
   forward — single ownership, no duplication).
2. **Genuinely requires §5 (and §4 for legality):** validator/
   implementor PROBE recipes and generated TEMPLATES (the 256/T=64
   literals), custom-loss probe shapes — deriving them needs the model
   I/O contract; inventing that contract from the proposer side would
   be the speculative-abstraction anti-pattern (§0 rule 8).
   Segmentation legality (proposal.py:1113-1128) stays regime-A on the
   singleton until §4 lands its legality function — it does not block
   6-P. This slice = "6-M: candidate-creation mechanics".
3. **What "proposer first" can mean:**
   - **O1 (recommended): 6-P is step 1** — first detailed design AND
     first production module PR, on the existing seam; Dataset and
     Model/Loss follow as steps 2-3; 6-M lands after §5. Honors the
     decision literally; zero speculative contracts; zero consumer-less
     seams; the hypothesis space is genericized before anything
     downstream.
   - O2: proposer first in DESIGN only (its detailed design is written
     first) while implementation stays Dataset→Model→Candidate. Weaker
     reading; only preferable if the operator wants the dataset seam
     landed before ANY prompt extraction.
   - O3: the whole Candidate Creation module first — REJECTED by
     evidence: 6-M's probes/templates need §5; doing them first forces
     inventing the model contract speculatively.
4. **This document adopts O1 as the working order below, subject to
   operator confirmation at roadmap freeze** (a prior operator decision
   is being interpreted, not overwritten; O2 remains open if the
   operator prefers it).

Order rationale otherwise unchanged: dependency (profile producers
before consumers), risk, parity provability, genericity unlocked,
validation cost. Every step leaves master working; every step = its own
detailed design + PR(s) following the §17 checkpoint model.

```text
0. GOLDEN BASELINE HARNESS (test-only, zero production diff).
   Purpose: CAPTURE CURRENT TRUTH before any extraction — a
   compatibility harness, NOT a second benchmark; do not overbuild.
   Its detailed design considers at minimum: all missing
   rendered-prompt goldens (§2.1); shipped task_config resolved
   content; the TIDMAD dataset-profile constants; representative
   serialized-record compatibility; CI-usable scorer/reference pins
   where feasible (the committed reference scalars). Cheap,
   immediately protective.
1. **6-P Proposer hypothesis-space & prompt surfaces** (Rev 3, O1 —
   the proposer slice of §13 pulled forward): commit-prompt task facts
   extracted onto the EXISTING ForwardContract/task-profile seam;
   forbidden-pattern lists; golden parity. Needs only step 0.
2. §4 Dataset & Sample Topology — Stage A (inject profile, TIDMAD
   default; input-identity indexing only — the Deliverable Contract
   stays in the §14 ledger; kill bare-constant imports per the
   old ledger's REMAINING list) → Stage B (atomic ladder §4.8).
3. §5 Model/Loss Contract — Stage A (class-count/encoding into the
   contract; dtype routing by contract, killing fcnet branches per the
   estimator precedent) → Stage B (atomic ladder §5.5).
4. **6-M Candidate-creation mechanics** — probes, templates, generated
   artifacts, FU-A-1 transport (needs steps 2-3), PLUS §13's remaining
   node groups (planner/reflector; validator prompt; implementor loss
   prompts; lit-review + duplicate collapse) with exact golden parity
   → completes §6's and §13's Stage B.
5. §7 Tuner data/execution submodules: 7b data selection → 7d
   resource/time (derived terms) → 7c execution contracts (launch
   mechanics + transport + contract encode/decode ONLY — scorer
   selection and metric semantics stay TIDMAD-bound until step 6; see
   the 7c boundary note).
6. §10 Metric Interface — TIDMAD instance frozen-byte-identical;
   EXTENDS the existing per_file_best metric-identity precedent.
7. §7 Tuner policy submodules: 7a (consumes the step-6 handle) →
   7e measurement.
8. §8 HealthGates task-profile checks (fresh-workspace boundary —
   see the §8.3 sha-lock note).
9. §11 Interpretation task blocks.
10. §12 Orchestration binding cleanup.
11. §9 Execution infrastructure (high blast radius, low gain).
12. TASK COMPOSITION ROOT + regime-B binding (D12; requires ≥3 landed
    module configs — expected viable after step 5): the thin reference
    layer of §0 rule 9, the regime-A→B switch of §2, and the
    per-module fail-closed tests. REQUIRED BEFORE Milestone 1 (§16),
    which binds the composed contrast task through it.
```

The operator's interests are honored in O1 order: the PROPOSER'S
hypothesis-space surfaces are step 1 (immediately after the baseline
harness, per the prior operator decision — §15.0), its mechanics
complete at step 4; the tuner begins at step 5 with its highest-value
submodule first.

### 15.1 Module completion-contract matrix (Rev 3 — the single navigation + definition-of-done surface)

Synchronized after EVERY module merge; never replaces per-module
detailed evidence. Columns: **Final effect** = what is TRUE about
SIDERIUS when the module is done (behavioral outcome, §2-of-the-review
standard); **A** = Stage-A/TIDMAD-parity checkpoint (its global §2
surface); **B** = Stage-B contrast DIMENSION (fixture data belongs to
the detailed design); **C** = live-integration checkpoint (the real
production consumer that proves the seam); **Deps** = must land before;
**Design** = detailed-design doc under `docs/design/generic_framework/`;
**Status**. All checkpoints follow the §17 model (0/A-E).

| Module | Step | Final effect | A (parity) | B (contrast dimension) | C (live integration) | Deps | Design | Status |
|---|---|---|---|---|---|---|---|---|
| Golden baseline harness | 0 | Every behavior later extraction PRs claim to preserve has a trustworthy, reviewable baseline BEFORE any production refactoring | n/a (it CREATES the baselines) | n/a | baselines consumed by every later Stage-A checkpoint | — | `pr0_golden_baseline_harness.md` | PLANNING (first work item at freeze) |
| 6-P Proposer hypothesis-space & prompts | 1 | Proposer prompts DERIVE from the declared task profile: task facts + contract PROSE (shapes/classes/task_type/loss legality) render from existing authorities instead of literals; TIDMAD proposals unchanged. Scope limits (3rd review, F2): the dataset-constraints block stays regime-A on the singleton until step 2; contract SEMANTICS stay §5-owned — 6-P only renders the declaration | rendered proposer prompts (all 3 stages incl. commit) EXACT-equal for TIDMAD + same kwargs reach LLMBridge (§2 nondeterministic surface) | 13.4-A (task-description text) + 13.4-B (declared forward contract, PROSE-rendering only) | the PRODUCTION proposer renders from the profile in a real chain iteration; contract-reassertion pins re-targeted to profile-parameterized form IN THIS PR (its design states the semantic change) | 0 (constraints-block slice completes after step 2) | `pr_proposer_hypothesis_space.md` | NOT STARTED |
| §4 Dataset & sample topology | 2 | A task declares different topology/geometry/groups in config and every consumer resolves it; no module-level dataset constant read anywhere in the loop | resolved profile deep-equals the TIDMAD singleton; SampleSet sha16 goldens; filename renders byte-identical | atomic ladder §4.8 (topology / geometry / groups / truth — one axis per rung) | training engine + sample-set builder consume the RESOLVED profile in production | 0 | `pr_dataset_topology.md` | NOT STARTED |
| §5 Model/loss contract | 3 | A task declares a different model I/O contract (classes, dtype, output forms) and models/losses/probes DERIVE from it; builtins byte-identical under TIDMAD | builtin forwards byte-identical; registry contents identical; guardrail targets extended; PRIOR ON-DISK GENERATED PLUGINS remain loadable or a workspace boundary is declared (§2 records surface) | atomic ladder §5.5 (class count / input contract / output type / custom-loss capability) | executor dtype routing + VRAM-probe recipes consume the contract in production | 0, §4 (encoding declaration) | `pr_model_output_contract.md` | NOT STARTED |
| 6-M Candidate-creation mechanics (+ §13 remainder) | 4 | Generated candidates (plugin/test/description) are produced AND validated against the declared contract with zero task literals; every LLM node's task content comes from the profile | generated plugin byte-identical for a fixed spec; validator verdicts identical; ALL remaining rendered prompts EXACT-equal + same kwargs reach LLMBridge; prior-plugin loadability (§2 records surface) | atomic ladders §6.5 + §13.4 (class count / shape / output type / description text / contract) | production implementor+validator emit/validate a candidate from the profile; all nodes render from it | 1, 2, 3 | `pr_candidate_creation_contract.md` + `pr_task_profile_prompts.md` | NOT STARTED |
| §7b Tuner data selection | 5 | A different topology flows through TrialConfig→SampleSets with tuner code untouched | SampleSet hashes + trial_config JSON deep-equal | dataset-profile axis (reuses 4.8-A through the tuner path) | the production tuner builds its train/eval sets from the resolved profile | 2 | `pr_tuner_data_selection.md` | NOT STARTED |
| §7d Tuner resource/time planning | 5 | Forecast task-terms (class count, decomposition unit, probe shapes) derive from profiles; calibration values unchanged and separately owned | forecasts byte-identical under TIDMAD (deep-equal breakdowns, PR-G pattern); policy identities unchanged | profile-term axis: a contrast profile changes derived terms while calibration stays fixed | production VRAM/time gates price a real attempt from derived terms | 2, 3 | `pr_tuner_resource_time.md` | NOT STARTED |
| §7c Tuner execution contracts | 5 | Engines write/clean deliverables via the (provisional) contract; launch mechanics carry zero task literals; scorer launch untouched (TIDMAD-bound until step 6) | argv/file-IPC byte-identical; artifacts byte-identical; sentinels untouched | deliverable-transport axis (single-axis fixture, §7c) | production training/inference spawns run through the contract | 2, 3 | `pr_tuner_execution_contracts.md` | NOT STARTED |
| §10 Metric interface | 6 | Metrics are named instances (name, direction, aggregation, references, scoreability); the frozen TIDMAD metric is instance #1 byte-identical; records/incumbents consume the handle | frozen-formula pins + offline scalar baseline + legacy parity (real_run); per_file_best metric_id key-set pin | metric-identity axis: a lower-is-better scalar metric on stub outputs through the handle | PRODUCTION SCORING invokes the frozen TIDMAD instance THROUGH the interface (a step-6-available consumer; incumbent-selection consumption is §7a's C at step 7 — 3rd review F5) | 5 (7-family); Deliverable Contract PROVISIONAL extraction (step 5, via §7c) | `pr_metric_interface.md` | NOT STARTED |
| §7a Tuner planning & policy | 7 | Round/attempt/incumbent policy is metric-agnostic (direction/thresholds via the handle); planner/reflector prompts render from the profile | planner/reflector prompts EXACT-equal + same kwargs reach LLMBridge (§2 nondeterministic surface); override-chain resolution deep-equal; record fields unchanged | metric-direction axis (7a fixture: lower-is-better through the policy) | production rounds select incumbents through the handle | 6 | `pr_tuner_policy.md` | NOT STARTED |
| §7e Tuner measurement/verification | 7 | Measurement data-feeding derives from the dataset profile; identity/comparability keys byte-stable | identity hashes/comparability unchanged (PR-G 0.R.12 pattern); store keys stable | measurement data-feeding axis (§7e fixture) | production prephase measurement builds batches from the profile | 2 | `pr_tuner_measurement.md` | NOT STARTED |
| §8 HealthGates | 8 | A task ships its own health-check family: checks declare their task-profile inputs, int8/amplitude checks become inapplicable-by-declaration on non-int8 deliverables while generic checks still FIRE and can block, and per-task thresholds live in task health config; TIDMAD's six checks are the golden instances | TIDMAD verdicts identical on fixture outputs; sha-pin MECHANISM untouched (fresh-workspace boundary for content) | atomic ladder §8.4 (groups / encoding declaration / generic-check firing) | production gate evaluation at tuner round boundaries uses declared inputs | 2, Deliverable Contract reader seam | `pr_health_check_task_profile.md` | NOT STARTED |
| §11 Interpretation | 9 | Interpretation renders from the metric handle + task blocks; prediction grammar metric-parameterized; sign-band fixed | 3 existing interpreter goldens + new ones EXACT-equal + same kwargs reach LLMBridge | atomic 11-A/11-B (metric identity / table indexing) | the production interpretation node renders a real iteration from handle+blocks | 6 | `pr_interpretation_task_blocks.md` | NOT STARTED |
| §12 Orchestration binding | 10 | Task binding lives at the launcher; §12's OWN surfaces (workflow binding, campaign_artifacts, orchestration inputs to resume) carry zero TIDMAD residue — §9's core-infra residue (sandbox dirs/globs, runtime-control fallbacks) clears at step 11 | k9/l_fail choreographies pass unmodified; resume inventory field-stable | launcher-binding axis: a second bound task initializes the loop | run_one_iteration binds a task in production | 1-9 as landed | `pr_orchestration_task_binding.md` | NOT STARTED |
| §9 Execution infrastructure | 11 | Spawn/IPC/limits fully task-free; calibration explicit with defined precedence (env override preserved) | argv/IPC/sentinels byte-identical; rlimits resolve to same TIDMAD values | infra axis: contrast task spawns with zero infra edits | all production spawns | most prior steps | `pr_execution_infrastructure.md` | NOT STARTED |
| Step 12 Task composition + regime B | 12 | A task binds its module configs through a thin reference root; bound tasks fail closed on missing semantics (§2 regime B) | regime-A callers byte-unchanged | binding axis: the composed contrast task binds and fails closed on a removed field | Milestone-1 composed task runs bound | ≥3 module configs (expected after step 5) | `pr_task_composition_binding.md` | NOT STARTED (D12 governs) |
| Deliverable Contract (owner TBD) | 5→11 (STAGED — 3rd review F6) | One owner for deliverable naming/layout/dtype/attrs/completeness; non-HDF5 deliverables expressible | provisional TIDMAD extraction byte-identical | non-HDF5 deliverable rung (owned by winning design) | STAGED consumers as steps land: engines write/clean via it (step 5, §7c's C); scorer reads (step 6); health peeks (step 8); cleanup (step 11) — the row COMPLETES at step 11 | §14 row governs. Tie-break: §7c (step 5, first to need it) PROPOSES ownership; §10's design may counter-propose; if contested, the operator decides | decided by first §7c/§10 design | NOT STARTED (ledger) |

Debt column (tracked here, not repeated per row): §8 fresh-workspace
sha-lock boundary; §12 campaign_artifacts.py (M2 blocker); §10
per_file_best direction+LOG_BASE (M2 blocker); §11 sign-band (M2
blocker); §9 rlimit precedence vs env override; DASHBOARD explicitly
classified PERIPHERAL (per the §16 D1 table) — may remain
TIDMAD-profile-bound at M2.

## 16. Framework-level acceptance criteria (Rev 2 — two milestones)

**MILESTONE 1 — CORE GENERICIZATION.** Reached when, simultaneously:
1. A materially different composed contrast task (accumulated atomic
   fixtures: different topology, encoding, output form, metric) runs
   the intended generic scientific path end-to-end from configs +
   task-owned modules, bound through the composition mechanism (§0 rule 9)
   with fail-closed resolution (§2 regime B) — with an EXPLICITLY
   ENUMERATED list of remaining legacy/peripheral TIDMAD-only surfaces,
   each named, classified (core vs peripheral), and re-tested as
   TIDMAD-profile-only.
2. Every TIDMAD golden (prompts, defaults, SampleSets, scorer scalars,
   records, choreographies) is green on the SAME head.
3. The frozen TIDMAD metric is byte-identical; authority matrix
   unchanged.
4. Guardrail families extended and green: no model-name branches
   (targets grown), no dataset-constant imports outside §4, no
   task-literal in health checks/estimators/templates.
5. Every migrated module has its Stage A parity evidence AND at least
   the required rungs of its atomic fixture ladder landed; no seam is
   consumer-less.

**D1 consumer classification (Rev 3, from source — not filenames):**

| D1 consumer | Evidence | Class |
|---|---|---|
| Tuner incumbent selection + skip/bypass gates | max-based 4-track best :6018-6064; `_best_trial_winner` :1435-1449; delta gates | CORE scientific loop — M2 blocker |
| Workflow best-score comparison | model_exploration.py:2740 bare `>` | CORE — M2 blocker |
| Resume best-pick | core/resume.py:438 `score > best_score` | CORE resume semantics — M2 blocker |
| campaign_artifacts | :39 denoising_score required; :57 band triplet; :88-92 TIDMAD import | CORE (inside core/) — M2 blocker |
| per_file_best | `_row_beats` :478-480 higher-is-better; :310 nonpositive skip; :62 LOG_BASE | CORE incumbent surface — M2 blocker |
| interpretation_helpers sign-band + metric grammar | :284-286; :309-355 | CORE interpretation path — M2 blocker |
| Dashboard (api/models, local_json sort, base direction note) | read-only FastAPI viewer; ZERO imports from the loop (verified: no `import dashboard` anywhere in workflows/nodes/core/execute_tools) | PERIPHERAL UI — may remain TIDMAD-profile-bound at completion if classified in the matrix debt list |
| scripts/ summaries (v18_wave_summary etc.) | offline reporting over artifacts | compatibility-only legacy surface — out of completion scope |

**MILESTONE 2 — FINAL FRAMEWORK-COMPLETE.** Reached only when NO
approved TIDMAD-specific exception remains in the CORE execution /
planning / resume / incumbent-selection / scoring loop. In particular,
metric-name/direction assumptions in workflow comparisons
(model_exploration.py:2740), resume (`core/resume.py:438`), incumbent
selection (the tuner's max-based 4-track best + `_best_trial_winner`),
**`core/campaign_artifacts.py`** (denoising_score requirement :39,
band-triplet literal :57, TIDMAD import :88-92 — the doc's own finding
10, inside core/), **`execute_tools/per_file_best.py`** (a per-file
INCUMBENT selector, not a dashboard: `_row_beats` higher-is-better
:478-480, nonpositive-score skip :310, duplicate LOG_BASE :62), the
**`nodes/interpretation_helpers.py:284-286` sign-band** (the
`sota*(1-margin)` arithmetic invalid for negative/lower-is-better
scores), and every other core reader MUST be migrated — **D1 remains
deferred in SEQUENCING but is NOT exempt from this definition**. Only genuinely peripheral surfaces
(e.g. the read-only dashboard) may remain TIDMAD-profile-bound at
completion, and only if explicitly classified as peripheral in the §15.1
completion-contract matrix's debt list (the dashboard is so
classified there).

## 17. Uniform validation checkpoints (Rev 3 — the per-module definition of done)

Every module passes SIX checkpoints — EXCEPT step 0, which CREATES
the baselines and passes only 0 (trivially), D and E (3rd review F10);
the §15.1 matrix instantiates A-C per module; exact commands/test
implementations belong to detailed designs:

```text
CHECKPOINT 0 — BASELINE AVAILABLE
  the TIDMAD behavior being extracted is actually pinned (step 0
  harness or the module's own pre-captured goldens).
CHECKPOINT A — EXTRACTION PARITY
  module-local config/contract exists; TIDMAD behavior unchanged under
  the STRONGEST applicable §2 surface criterion (each module's matrix
  row names its surface).
CHECKPOINT B — GENERIC CONTRAST
  the rung subset of the module's atomic ladder that its detailed
  design DECLARED REQUIRED (declared upfront in that design; recorded
  in the matrix B cell at completion) is landed — each rung varying
  exactly one axis. §16 criterion 5 requires exactly these declared
  rungs; the two definitions are one (3rd review F8).
CHECKPOINT C — LIVE INTEGRATION
  the matrix row's named REAL production consumer uses the new
  contract; no consumer-less seam survives the PR.
CHECKPOINT D — REGRESSION
  relevant TIDMAD module tests, cross-module compatibility tests,
  mutations (delete-the-hop, precedence reversal), and CI green on the
  exact final head.
CHECKPOINT E — ROADMAP SYNC
  the §15.1 matrix row is updated in the same PR, or in an immediate
  docs follow-up that MERGES BEFORE the next module PR opens (a
  blocking rule — an unbounded deferral is how the 2026-07-28 ledger
  went stale, §0.A).
```

Bounded real Gates: conceptually REQUIRED (decided and bounded by the
detailed design, minimum sufficient evidence) for modules that change
real execution behavior — §7c, §7e, §9, and §8's blocking-verdict
changes; NOT required for prompt/config/metric-handle extractions whose
parity is fully deterministic. The implementation ladder inside each
detailed design remains: audit → baseline → extract → parity → seam
WITH first consumer → contrast rung(s) → de-hardcode (guardrail targets
grow) → mutations → (Gate) → CI → merge → sync. No second scientific
campaign per module.

## 18. Deferred decisions

| # | Decision | Why deferred |
|---|---|---|
| D1 | Renaming `denoising_score` fields / record-schema migration | schema-compatibility surface; needs the §10 design + a migration plan; NOT authorized here |
| D2 | Hybrid output-type disposition (extend generation vs retire) | UNKNOWN intent; decide in §5 with §6 |
| D3 | Which local configs merge (ledger §14) | by rule: after ≥2 completed designs |
| D4 | Physical config-file organization (one file per module vs grouped) | semantic ownership first; decide when ≥3 module configs exist |
| D5 | `tidmad_data_config.yaml` rename | inherited: deployment-touching PR only |
| D6 | Metric-store / measurement-key versioning when geometry varies | needs §7e design |
| D7 | `agent/skills/` → `agent/tools/` rename | inherited deferral; orthogonal |
| D8 | Second real scientific task selection | after the composed contrast task passes §16 Milestone 1 criterion 1; a real task is NOT required per module |
| D9 | Retire vs re-scope collapse_detection_framework_generic.md's unbuilt machinery | needs §8 design; default retire |
| D10 | Dead seams disposition (tune→interp protocol; validation_file_pattern gains consumers in §4/§10 or is dropped) | per owning module's design |
| D11 | CLAUDE.md task-agnostic claim + seam-authority pointer update | with the first landed module PR |
| D12 | Task-composition root's physical representation (file layout/schema; when legacy-adapter defaulting is retired per §2 regime split) | by §0 rule 9: after several module configs exist; the composition design also fixes the binding switch from regime A to regime B |

## 19. Detailed-design documents this roadmap requires

`docs/design/generic_framework/` (new folder; one doc per §15 step,
named in each module section above). The §15.1 table in THIS document
is the ONE status authority — the folder README is an index (links +
a one-line mirror of §15.1 rows), never a second progress meter; the
second adversarial pass flagged that duplicate meters are exactly how
the 2026-07-28 coupling ledger went stale (§0.A).
