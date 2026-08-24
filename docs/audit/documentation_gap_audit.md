# Documentation Gap Audit

**Audited at**: `cfaa5572` (`origin/master`, 2026-08-23) — the landed state, not any
unmerged Step-12 branch.
**Purpose**: the source-grounded evidence base for the documentation system refresh.
**Method**: every claim below was checked against landed source or the filesystem.
Design prose was used only to establish *intent*, never *current behaviour*.

This document is a point-in-time audit. It is not a maintained reference; the
documents it produced are. Once those documents drift, re-run the audit rather
than editing this file.

---

## 1. The shape of the problem, in one table

| surface | volume | audience it actually serves |
|---|---|---|
| `README.md` | 382 lines | first-time human — but positioned as a TIDMAD denoising project |
| `docs/architecture.md` | 1,068 lines | developer; current design mixed with two live `## TODO:` sections and a "Future Evolution" section |
| `docs/README.md` | 122 lines | a design-doc *metadata ledger* (status / owner / depends-on), not navigation |
| `docs/design/**` | **169,847 lines** across 96 files | design + decision history |
| node docs | 7 files, 2,733 lines | developer |
| example packs | 12 files | operator |
| **human learning path** | **0 files** | — |
| **coding-agent retrieval index** | **0 files** | — |
| **required-vs-optional reference** | **0 files** | — |

Design history outweighs every other documentation surface by roughly **40×**.
That is not itself a defect — the history is genuinely valuable and must be kept.
The defect is that it is also the *only* place several current mechanisms are
described, so the archive has become load-bearing for present-day understanding.

**No Markdown tooling exists.** `pyproject.toml` configures ruff, pyright and
pytest; `.github/workflows/ci.yml` runs `ruff check`, `ruff format --check`,
`pyright` and a selective `pytest`. Nothing reads a `.md` file. There is no
`.pre-commit-config.yaml`. Every broken reference catalogued in §6 is therefore
invisible to CI — which is how `docs/README.md` could be edited as recently as
2026-08-16 while carrying 19 dead paths.

---

## 2. First impression — can a newcomer orient? **MISSING / CONTRADICTORY**

| question | verdict | evidence |
|---|---|---|
| What is SIDERIUS? | PRESENT BUT STALE | `README.md:5-9` — "Current target: **denoising the TIDMAD SQUID time-series dataset**". Landed master ships a task-composition manifest, three example packs and a task-neutral execution path. |
| What problem does it solve? | PRESENT BUT TOO NARROW | The README describes the TIDMAD application, not the framework capability. |
| Is it AutoML / agent framework / workflow system? | MISSING | Never stated. A reader must infer it from the 6-agent diagram. |
| What does "composable" mean here? | MISSING | The word "composition" does not appear in `README.md`. |
| Who should use it, and for what? | MISSING | No audience statement, no non-goals. |
| What is NOT an appropriate use? | MISSING | — |

**Contradiction of record**: `README.md:23-27` and `AGENTS.md:7-10` both state that
porting SIDERIUS to a new task "starts with editing `configs/task_config.yaml`".
That was true before Step 10. On landed master, `configs/task_config.yaml` supplies
only `task_description` + `forward_contract`, and is one of **ten** manifest
sections (`workflows/task_composition.py:94-107`). Porting a task now means
authoring a composition manifest.

---

## 3. Supported data / task shapes — **PRESENT BUT SCATTERED**

The framework is contract-driven, not modality-enumerated. Nothing in landed
source branches on a task name; support is decided by whether a task can express
itself through the four `TaskDataPath` methods
(`execute_tools/task_data_path.py:335-376`), a `DatasetProfile`
(`execute_tools/dataset_config.py:466-486`) and an `EvaluationMetric`
(`execute_tools/evaluation_metric.py:495`).

Three shapes are demonstrated by persistent example packs, at **different and
honestly-declared maturity**:

| example | shape | declared maturity on landed master |
|---|---|---|
| TIDMAD | 1-D scientific signal denoising | executed by production at **L4** through the operator surface; the pack itself is a read-only L0/L1 projection (`examples/tidmad/STATUS.md`) |
| Oxford-IIIT Pet | RGB image, 37-way classification | **L2/L3 executable** via the D14-2 harness (`examples/oxford_iiit_pet/STATUS.md`) |
| DAVIS 2017 | RGB spatiotemporal 8→4 future-frame regression | **L2/L3 executable** via the D14-3 harness (`examples/davis_future_prediction/STATUS.md`) |

The maturity distinction is real and load-bearing (see §8): the contrast packs run
through *direct-execution harnesses*, not through the production
train → infer → score subprocess path.

Where this is documented today: split across `docs/design/siderius_generic_framework_upgrade.md`
§22.9a (the frozen task specs), the three `STATUS.md` files (which self-declare as
*mirrors* of that section — three copies of one design-doc section), and the D14
design docs. `README.md` mentions `examples/` **zero times**.

---

## 4. What must a user provide? — **MISSING as a document, CLEAR in source**

This is the single most important missing page. The answer exists precisely, in
one place in code, and nowhere in prose.

Authority: `_MANIFEST_KEYS` / `_REQUIRED_KEYS`, `workflows/task_composition.py:94-123`;
resolution in `compose_run_task_bindings` (`:1308`); activation in
`bind_run_task_composition` (`:1485-1565`).

There is **no Pydantic model for the manifest**. It is validated by hand-written
fail-closed code: a key-set difference refuses unknown keys
(`workflows/task_composition.py:335-342`), and each section has its own resolver.
There is **no version field** — `_MANIFEST_KEYS` contains no `version` or
`schema_version`.

Ten sections, five required:

| section | required | absence semantics |
|---|---|---|
| `task_data_path` | **yes** | run refused |
| `dataset_profile` | **yes** | run refused |
| `metric` | **yes** | run refused |
| `task_config` | **yes** | run refused |
| `task_health` | **yes, as a statement** | may be `{none: true}`, but may not be omitted — omission is `LEGACY_OMITTED`, which resolves TIDMAD's health family, and a composition is forbidden from expressing that state |
| `secondary_metrics` | no | absent and `[]` are the same state `()` — zero record keys, zero rendered bytes |
| `proposal_blocks` | no | proposer receives **no** task science (not TIDMAD's) |
| `implementor_blocks` | no | implementor renders nothing |
| `interpretation_blocks` | no | interpreter renders no task blocks |
| `deliverable` | no | **silently resolves to the shipped TIDMAD naming** (`workflows/task_composition.py:1065`) |

The `deliverable` row is the one place where absence does not mean "nothing".
It is a known defect (F-A4-1) whose narrowing is owned by the unmerged PR-12d;
until then it must be documented as a hazard, not as a default.

`--data_dir` is required for any composed run and fails closed *before* any LLM or
GPU work (`workflows/task_composition.py:1525-1541`, `CompositionDataRootMissing`).

---

## 5. Metric model — **PRESENT BUT SCATTERED, and precise in source**

| question | source answer |
|---|---|
| what determines better? | `MetricSpec.direction`, `Literal["higher", "lower"]` (`execute_tools/evaluation_metric.py:116, 382`). Explicit, never inferred. No `higher_is_better` boolean exists anywhere. |
| who interprets it? | exactly one authority, `MetricOrder` (`execute_tools/metric_order.py:59-104`). Prose renders through `direction_words()` (`:138-147`) rather than re-reading the field. |
| do secondaries influence selection? | **No.** `metric_order.py`, `persisted_ranking.py` and `per_file_best.py` contain zero occurrences of `secondary`. The carrier states the rule: "Secondaries are OBSERVATIONAL: nothing in this tuple may ever become an operand of an ordering expression" (`workflows/task_composition.py:246-249`). Proposer consumption is frozen off (`agent/schemas/proposer_evidence.py:92`). |
| objective vs metric? | different lifecycle roles, not different mathematics. `MetricSpec.id` is an **opaque identity** since PR-12a C5 — `log_loss` is as declarable as `accuracy`. What separates a loss from a metric is the contract (a deliverable, an aggregation, an executable `ScoreabilityContract`), not the name. |
| what if the output cannot be scored? | `ScoreabilityContract.check` runs *before* the arithmetic and yields a structured `NotScoreableResult` (`execute_tools/evaluation_metric.py:198-227, 433-458`) → an `error_scoring` record with `failure_type="not_scoreable"`. |

DAVIS is the clean illustration that the same computation occupies three roles:
MAE is the training objective, the per-epoch validation history, *and* a declared
terminal secondary metric — while MSE is the primary.

Documented today only inside Step 06 / 07b / 09a / 10-P2 design docs and a
`## Evaluation Metric Interface` section of `docs/architecture.md:597`.

---

## 6. Health gates — **PRESENT BUT SCATTERED and mis-stated in three places**

The concept is well-designed and badly reported. The *count of built-in checks*
alone is stated three different ways, all wrong:

| doc | claim | actual |
|---|---|---|
| `README.md:72-81` | "Six shipped checks" | **9** |
| `AGENTS.md` / `CLAUDE.md` | "Built-in checks: `OutputDiversityCheck`, `AmplitudeCollapseCheck`" | **9** |
| — | — | `amplitude_collapse`, `output_diversity`, `output_std`, `pearson_dispersion`, `per_file_output_std`, `spectral_peak_ratio`, `sample_dispersion_floor`, `categorical_distinct_symbols`, `categorical_dominant_fraction` |

(`HealthCheckSkill` is a `Protocol`, not a base class — `execute_tools/health_checks/protocol.py:24`
— which is why a subclass-count never matched.)

Correct current model, from source:

- **Framework policy** (`configs/health_checks.yaml`) owns what a gate *does*:
  role, cadence, short-circuit, `on_pass`/`on_fail`. Its header lists what
  deliberately no longer lives there (`:8-16`).
- **Task policy** (e.g. `configs/task_health/tidmad.yaml`) owns roster,
  thresholds, peek files, value scale and prose. Schema `TaskHealthConfig`,
  frozen, `extra="forbid"`, every field optional
  (`execute_tools/health_checks/_task_health_config.py:348-395`).
- The task's **only** policy choice is `disposition` ∈ {`BLOCKING`,
  `OBSERVATIONAL`} (`_task_health_config.py:62-87`); the framework derives
  everything else, so task and framework cannot disagree.
- Verdicts: `passed` / `failed` / `inapplicable` / `error`
  (`schemas.py:330-364`). `inapplicable` "never blocks — and never counts as a
  pass". `error` on a blocking check fails closed.
- Actions: `continue`, `skip_iter`, `skip_to_formal`, `invalidate_round`;
  severity `SKIP_ITER > SKIP_TO_FORMAL > INVALIDATE_ROUND > CONTINUE`.

**A health gate PASS is not a scientific result.** Nothing in the repository says
this to a newcomer.

---

## 7. Configuration model — **PRESENT BUT SCATTERED**

`configs/` currently presents nine YAML files as if they were peers. They are not:
they have four different owners and three different lifetimes.

| file | owner | user-editable? |
|---|---|---|
| `configs/health_checks.yaml` | framework policy | rarely — changes what failure *does* |
| `configs/task_health/tidmad.yaml` | the task | yes — thresholds live here |
| `configs/task_composition/tidmad.yaml` | the task | yes — the manifest |
| `configs/task_config.yaml` | the task | yes — description + forward contract |
| `configs/task_{proposal,implementor,interpretation}/tidmad.yaml` | the task | yes — prompt science |
| `configs/lit_review_config.yaml` | operator | yes |
| `{workspace}/health_checks_effective.yaml` | **generated** | **no** — composed + sha-pinned at run start |
| `{workspace}/run_invariants_lock.json` | **generated** | **no** — pins scope/gates/config identity |

The in-repo residence of `configs/task_health/tidmad.yaml` is explicitly
"REFERENCE PACKAGING, not a framework dependency" (`:22-24`) — an external task
supplies its own file anywhere on disk. Nothing in user-facing documentation says
this.

---

## 8. Execution model — **PRESENT BUT SCATTERED; one hard limitation undocumented**

`run_workflow` is a straight-line function, not a graph runner
(`workflows/model_exploration.py:1620-1661`; "This is a workflow, not an
orchestrator — the path is fixed and deterministic", `:22-26`). Per iteration:

interpret → *(literature review, optional)* → propose → implement → validate →
tune (plan → train → infer → score → health → reflect, N rounds)

All six are LLM-powered; scope resolution, invariants, gate evaluation and scoring
are deterministic.

**The undocumented limitation.** Only the *training* child receives the task
scope. Verified on landed master:

- `grep -c task_scope`: `train_engine_sandbox.py` = 14,
  `inference_single.py` = **0**, `denoising_score_single.py` = **0**.
- `_task_scope_argv` has exactly one call site, `core/sandbox_executor.py:1622`.
- `denoising_score_single.py` builds, at module level with no guard,
  `sample_set = {args.file_index: list(range(tidmad_topology(dataset_profile)…))}`
  — and `tidmad_topology` fails closed for a profile with no TIDMAD topology.
  **The scoring child is unconditionally TIDMAD-only.**
- `inference_single.py:696,725` iterates file_index → segments via
  `profile_dataset.validation_file_name` — TIDMAD topology.
- `SIDERIUS_PLUGIN_DIRS` is injected by the two Gate harnesses only; zero
  occurrences in `run_chain.sh`, `_chain_common.sh` or `run_one_iteration.py`.

Consequence for documentation: **Pets and DAVIS cannot currently run through the
production chain.** They run through in-process harnesses
(`scripts/run_pets_gate2.py`, `scripts/run_davis_gate2.py`, which call
`run_experiment_streaming` directly). Closing this is exactly what the unmerged
PR-12d is for. Any documentation that implies otherwise is false.

---

## 9. Entrypoints — **PRESENT BUT STALE**

| entrypoint | accepts `--task_composition`? |
|---|---|
| `sdsc_submission_scripts/run_chain.sh` | yes (forwards) |
| `sdsc_submission_scripts/run_one_iteration.py` | yes (`:1063-1078`) |
| `workflows/model_exploration.py` module CLI | yes (`:3380-3387`) |
| `scripts/run_comparison.py` | **no** — TIDMAD-only by construction (imports `TIDMAD`, `NUM_FILES`, `TidmadSandbox`, `TIDMAD_DATA_DIR` at `:53-60`) |

`--healthgate_mode` and `--result_authority` have **no defaults** and are required
for a formal launch (`run_one_iteration.py:1038-1051`, enforced by
`validate_formal_launch`, exit 2). No user-facing document mentions this.

`README.md`'s chain example does not pass `--task_composition` and embeds the
lab-local path `/home/klz/Data/SIDEREIS_DATA/exploration_chain_v1`.

---

## 10. Verified-broken references

Each was checked with `ls`. All are absent. None is visible to CI.

| missing target | cited by |
|---|---|
| `docs/running_chain_test.md` | `sdsc_submission_scripts/README.md` ×3 (calls it "the operator runbook"), `CLAUDE.md`, `AGENTS.md`, `nodes/ml_hyperparameter_tune_agent/…md`, `agent/skills/evaluate_vram_skill/…md` ×2, `examples/tidmad/README.md` |
| `docs/pseudo_test_infra.md` | `docs/architecture.md` ×3, `AGENTS.md`, `CLAUDE.md`, `tests/pseudo_data/README.md` ×2, `docs/audit/unit_tests_rubric_audit.md` |
| `docs/external_agents_for_proposer.md` | `nodes/ml_literature_review/…md` ×3, `reference_data/root_papers_cache/README.md` |
| `docs/run_scoped_plugins.md` | tuner node doc |
| `docs/refine_inference_time_estimator.md` | tuner node doc, `CLAUDE.md` |
| `docs/phase68_orchestrator_memory_and_resume.md`, `docs/audit_and_optimize_token_usage_and_growth.md` | `sdsc_submission_scripts/README.md` |
| `docs/v18_split_run_plan.md` | `docs/architecture.md` |
| `docs/validation_suite_runs.md` | lit-review node doc |
| `docs/commit_plan_*.md` | `README.md` invariant #6 |
| `docs/memories/` + 8 files | `README.md:376`, `docs/README.md` — the directory is gitignored (`.gitignore:58`) |
| 11 `reports/*.md` rows | `docs/README.md` — **every row** of its Reports table |
| `reports/v16_20260630.md` | `reports/health_metrics_scan.md`, `reports/v17_20260717.md` |

Cleared on inspection (suspected, verified fine): `scripts/run_comparison.py` path,
all `configs/*.yaml`, `core/hardware_context.py`, `agent/llm_bridge.py`,
`workflows/*.py`, `sdsc_submission_scripts/{run_chain.sh,run_one_iteration.py}`,
`llm_configs/openai_tiered_{v1,pro}.json`, `reference_data/segment_anchors.json`,
`tools/claude_hooks/`, `tools/example_packs/`.

---

## 11. Contradictions

| # | contradiction | resolution |
|---|---|---|
| C1 | `AGENTS.md` is a stale 22 KB fork of the 87 KB `CLAUDE.md` — same opening, same headings, both stamped `as of 2026-07-23`, but CLAUDE.md has been maintained through Step 12. AGENTS.md still claims the active branch is `feat/enable-partial-file-list` and that master CI is red at `9e503ea`. | `AGENTS.md` is the file coding agents read by convention. Replaced with a short, accurate entry pointer; the rules stay in `CLAUDE.md` as the single authority. |
| C2 | health-check count: 6 / 2 / 9 | 9; stated once, in the health-gate mechanism doc |
| C3 | validator check count: `README.md:53` says 7, `nodes/ml_code_validator_agent/…md` says 8 | node doc is the authority |
| C4 | `docs/memories/` — `README.md` says gitignored, `docs/README.md` says "version-controlled" | `.gitignore:58` sides with `README.md` |
| C5 | two competing "Active branch" claims inside `CLAUDE.md` | operator-owned file; recorded as a follow-up, not edited here |
| C6 | task porting "starts with editing `configs/task_config.yaml`" | superseded by the composition manifest |
| C7 | three `examples/*/STATUS.md` self-declare as *mirrors* of a design-doc section | left as-is; the new support matrix links to them rather than making a fourth copy |
| C8 | two doc indexes (`README.md` §Documentation map and `docs/README.md`) that do not link to each other and disagree | one map, in `docs/README.md`; the README links to it |

---

## 12. Findings recorded, deliberately NOT fixed here

This is a docs-only change. The following are product findings, not documentation
defects, and are left for their owners:

- **DOC-F1** — absence of the `deliverable` manifest section silently resolves to
  TIDMAD's naming template, and the cleanup glob derived from it can delete files
  the run never wrote. Owner: PR-12d seam E (F-A4-1).
- **DOC-F2** — `CLAUDE.md` carries three broken doc references and two
  contradictory "Active branch" statements. Operator-owned file; not edited by
  this PR to avoid conflicting with the in-flight PR-12d / PR-12e work.
- **DOC-F3** — the manifest has no `version` field, so a future incompatible
  manifest change has no declared migration signal. Owner: Step 12 / post-12e.
- **DOC-F4** — `docs/README.md`'s Reports table and memories table were 100 %
  dead. Repaired here, but nothing prevents recurrence: there is no Markdown link
  check in CI. Adding one is a follow-up, not part of this PR.
- **DOC-F5** — `scripts/run_comparison.py` is documented as a general baseline
  runner but is TIDMAD-only by construction. Documented as such; making it
  task-neutral is not a documentation task.
- **DOC-F6** — `sdsc_submission_scripts/run_chain.sh`'s own header comment lists
  `--seed_paths` under "Required flags", while `_chain_common.sh:403-406`
  documents it as optional and omits it entirely for a cold start — which is the
  *required* posture for gate runs. Only `--mode` is actually validated. The
  header comment lives in a production shell script and was not edited by this
  docs-only PR; the correct behaviour is documented in
  `docs/reference/entrypoints.md`.
- **DOC-F7** — `nodes/ml_hyperparameter_tune_agent.md` (199 lines) duplicates
  `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.md`
  (1,319 lines). It self-declares as a legacy pointer, so it was left in place,
  but it remains forkable content that nothing maintains.
