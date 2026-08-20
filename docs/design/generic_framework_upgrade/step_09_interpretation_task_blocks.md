# Step 09 — Interpretation from the metric handle + task blocks (parent design)

## 0. Status and provenance

**REVISION 2 — FROZEN (operator freeze authority granted in the
2026-08-19 review ruling, exercised after the mandated source audits closed
without a new material contradiction).**

**IMPLEMENTATION STATUS: STEP 09 COMPLETE — both children MERGED; Step-09
acceptance CLOSED (2026-08-20).**

| child | status | PR | squash SHA | exact-head CI |
|---|---|---|---|---|
| **09a** — interpreter evidence & ordering on the metric handle | COMPLETE / MERGED 2026-08-19 | #238 | `4cf38dec0934cf22c59c80cc69711d7c2bd0401b` | 32313798097 SUCCESS on `9d85f67b` |
| **09b** — interpretation prompts from `InterpretationTaskBlocks` via explicit renderers | COMPLETE / MERGED 2026-08-20 | #239 | `e9a1f9fbb1c2e882be5b017756e2552a6b9f8d7c` | 32324124087 SUCCESS on `ce3b971d` |

Merged master was verified byte-identical to each validated head. The
per-child evidence, ledgers and findings live in
`step_09_interpretation_task_blocks/pr_09a_interpreter_evidence_ordering.md`
§10 (104 `[x]` / 0 `[ ]`) and
`step_09_interpretation_task_blocks/pr_09b_interpretation_prompts_task_blocks.md`
§22 (72 `[x]` / 0 `[ ]`). **Nothing in this parent's architecture changed
during either child's implementation** — the sections below remain the
freeze-time design and are NOT rewritten as post-implementation
observations.

**What Step 09 delivered.**

* **09a — deterministic evidence, ordering and prediction semantics.** The
  run's `MetricSpec` is transported from the tuner's ONE existing derivation
  (Step 09 adds zero derivation sites) and interpretation FAILS CLOSED
  without it; all 21 interpreter direction consumers read `MetricOrder`,
  with the differential oracle byte-identical across that migration;
  prediction semantics v2 is sign-safe and direction-aware, `unevaluated`
  counts in no pool, and the v1/v2 partition is frozen per field; the
  interpreter's prediction memory now rides the existing canonical lifecycle
  (pre-09a it was carried by nothing — erratum E2); evidence projection adds
  diagnosis, authority-derived failure counts and the typed secondary
  contract with Q-09-7 = B held.
* **09b — task-owned interpretation blocks and explicit rendering.**
  `InterpretationTaskBlocks` (four framework keys, task-owned prose, absent
  ⇒ nothing rendered) reaches the interpreter as a caller-supplied VALUE;
  TIDMAD's science moved VERBATIM into `configs/task_interpretation/tidmad.yaml`
  behind ONE bounded Regime-A adapter whose single task-identity occurrence
  is a constant, not a branch; the framework prompts are task-free (census
  with planted offenders both ways) and the last task-specific Health
  check-id example is gone; explicit renderers give one authority per
  evidence family (metric identity, per-role `TrainingDiagnosis`,
  secondaries in their three states, failure counts); the prediction track
  record is version-aware in BOTH consumer nodes, closing the declared
  Q-09a-3 consequence in which v2 fractions were rendered over the frozen
  v1 denominator. Three-task contrast and the roadmap 11-A/11-B rungs
  landed. **Gate 1 PASS** (one launch, exactly 5 calls, 13/13 checks);
  Gate 2 not required.

**Forward debt is unchanged and preserved with its owners** — see §19; the
09b child §19 carries the same list plus the structural/test hotspots it
recorded. Those hotspots are the input to **Step 09.5**, the repository
structural-debt + test-topology audit the operator sequenced between Step 09
and Step 10 (roadmap §15.1); Step 09.5 is an AUDIT and does not pre-commit
the project to refactoring.

Rev 1 (`6c2802cd`, DRAFT) was reviewed by the operator with the verdict
**APPROVED ARCHITECTURE / REQUIRED REVISION BEFORE FREEZE**: the
architecture and the PARENT + 2 CHILD decomposition (09a → 09b) were
approved; the revision was required to enforce the two forward anti-debt
principles — strong external extensibility (do not deepen central-binding /
task-specific debt) and node-local structural discipline (no more mixed
responsibilities in a god file). Rev 2 applies the ruling's twenty items
(§0.1) and records the three additional source audits it mandated (single
run-metric authority §2.11; secondary-metric carrier §2.12; prediction-
history aggregation §2.13) plus the node-local structure audit (§13a).

**Audit anchor: master `bf22827b`** (Step 08 COMPLETE — 08c PR #237 squash
`3f4effb5` + status sync); rev-2 audits performed at `6c2802cd` (rev-1 doc
commit; production source identical to `bf22827b`). Working tree clean at
the start of each audit. Every `file:line` in this document was read at
this anchor.

Zero `SOURCE-INSPECTION REQUIRED` markers.

Authority order: roadmap (`siderius_generic_framework_upgrade.md`, §15.1
§11-row + §22) > current source > merged Step-06/07/08 designs/ledgers >
this design. Where roadmap wording and source differ, the difference is
recorded (§2.10), never silently resolved.

### 0.1 Operator rulings incorporated (2026-08-19 review)

| item | ruling | landed at |
|---|---|---|
| Q-09-1 task-block carrier | **B refined** — `InterpretationTaskBlocks` is a typed VALUE contract; TIDMAD content lives in ONE dedicated TIDMAD-owned declaration resolved by a bounded compatibility adapter; NO new science in central `task_config.yaml`; no loader/registry; no `examples/` dependency | §4, §9, §13 |
| Q-09-2 metric-spec source | workflow-supplied `InterpretationInput.metric_spec` is the boundary, but NO second `derive_tidmad_metric()` site — route **B** from source audit (§2.11): the tuner's already-resolved `run_metric.spec` rides additively on `HyperparamTuningOutput`, reconciled across outputs | §2.11, §4, §11 |
| metric-spec ↔ record identity | distinct ownership + fail-closed consistency rule | §4a |
| secondary metrics | contract gap CLOSED by audit (§2.12): **no carrier exists in production**; exact typed additive carrier designed; ownership surfaced as Q-09-7 — **RULED B (2026-08-19, §0.2): Step 09 owns the interpreter-side contract; Step 10 owns production transport** | §0.2, §2.12, §4b |
| Q-09-3 `_cap_knowledge_cache` | 09a owns the SEMANTIC migration; helper stays physically in the workflow file; ordering parameterized by the same `MetricOrder` | §7, §16 |
| god-file audit | mandatory parent section; 09a begins with behavior-preserving node-local extraction; one obvious main file preserved | §13a |
| Q-09-6 prediction band | **A** — sign-safe, direction-correct band; exact rule frozen; historical records untouched | §13 ¶1, §16 |
| prediction semantics version | additive framework version id; version-aware aggregation rule frozen from source audit (§2.13) | §5, §8, §13 |
| 09a parity claim | corrected to differential ownership; no "same full digest" claim | §16 (09a) |
| failure rendering | no new closed task-failure enum; counts from existing authorities only | §5, §13 |
| Q-09-4 Gates | 09a none; 09b Gate 1 REQUIRED, Gate 2 NOT | §17 |
| Gate-1 contrast | REAL preserved TIDMAD + DAVIS-shaped (lower, scalar-only) fixture; call count source-grounded | §17 |
| Q-09-5 fixtures | pack `expected/`, labeled L1 synthetic contract-level; zero production dependency on `examples/` | §10, §16 |
| `evaluation.py` | B / Step 10 — APPROVED | §12 |
| decomposition | PARENT + 2 — APPROVED; no third PR | §15 |
| extensibility wording | CONDITIONAL PASS during editing → PASS at freeze (criteria met, §9/§22) | §9, §23 |
| per-milestone god-file rule | recorded as forward discipline | §13a.5 |
| adversarial pass | 18-point re-read performed (§23a) | §23a |

### 0.2 Q-09-7 final operator ruling (2026-08-19) — scope placement, NOT a parent revision

**Q-09-7 = B — RESOLVED.** An operator scope-placement ruling on a contract
this parent already froze (§4b); the parent remains **REVISION 2 — FROZEN**
and is not reopened. Applied narrowly at every surface that previously
carried the A/B ambiguity (§2.12, §4, §4b, §9, §15, §16, §19, §20, §21,
§23, §23a); nothing else in this document changed.

* **Step 09 owns**: the typed secondary-metric interpretation contract;
  the `ModelRunSummary.secondary_metrics` projection;
  present-when-present deterministic evidence; named absence; explicit
  rendering; each secondary metric's own identity/direction words;
  three-task L1 contract evidence.
* **Step 09 does NOT own**: production secondary-metric declaration
  binding; execution of additional metric handles; tuner-side secondary
  scoring; secondary-result persistence into `ExperimentRecord`;
  production workflow transport of secondaries. Those are **B — FORWARD
  CONSTRAINT, OWNER: Step 10**, when the generic workflow/persistence path
  first carries task-declared secondary metrics — preserving the forward
  invariant *open semantic contract now + unified workflow/composition
  later*, rather than an interim Step-09-specific secondary
  evaluation/binding path.
* **The frozen semantic rule is unchanged** (§4b): PRIMARY owns run
  ordering / incumbent comparisons / active-model ordering / prediction
  default; SECONDARIES are observational evidence ONLY, each with its own
  `metric_id` and direction, rendered with its own direction words, never
  affecting primary ordering/policy. Declared-but-unavailable secondary
  evidence is a NAMED ABSENCE; numbers are never fabricated.
* **Three-task Step-09 evidence (09a/09b L1 fixtures)**: TIDMAD — no
  declared secondary metrics; Pets — primary `accuracy` (higher),
  secondary `macro_f1` (higher); DAVIS — primary `mse` (lower), secondary
  `psnr` (higher), secondary `mae` (lower). Pets/DAVIS fixtures use
  carrier-shaped Step-06 authoritative result objects; they are L1
  synthetic / contract-level interpretation evidence, explicitly NOT a
  claim that the production workflow evaluates secondaries. Production
  code retains zero dependency on `examples/`.
* **Step-10 obligation (recorded in §19)**: task-declared secondary
  `MetricSpec`s → binding through the unified task/workflow composition
  mechanism → evaluation through the Step-06 metric protocol →
  `ExperimentRecord` persistence → tuning/workflow transport → the SAME
  Step-09 `secondary_metrics` contract. Step 10 must NOT invent a
  replacement Step-09 schema.

### 0.3 Post-freeze factual errata from the 09a child source audit (2026-08-19) — architecture unchanged

Applied with the 09a child freeze (operator final ruling, "factual source
correction only; frozen Step-09 architecture unchanged"): (a) **§2.3
census +4 sites** (`_render_health_summary_section:219-221`;
`generate_discoveries:444/:450/:455` incl. a second sign-degenerate 5%
band) — 12 → 16 interpreter-side entries, all 09a C3; (b) **§2.13/§8
prediction-pool premise corrected** — at the pre-09a anchor NO production
path carries or restores `prediction_outcomes_history` /
`cumulative_information_gain` (nor `vocab_link_confirmations`); the frozen
target is 09a's NARROW interpreter-owned carry/restore through the existing
canonical path (Q-09a-1 = A narrow), exact per-field v1/v2 spellings in
the child §3.4 (Q-09a-2); (c) §15 09a surfaces + §19 rows updated
accordingly. Both child designs are **REVISION 2 — FROZEN** (2026-08-19)
and both are now MERGED: `step_09_interpretation_task_blocks/
pr_09a_interpreter_evidence_ordering.md` (PR #238) and
`step_09_interpretation_task_blocks/pr_09b_interpretation_prompts_task_blocks.md`
(PR #239). *(This paragraph records what the 09a source audit found AT ITS
ANCHOR; the freeze-time statements are preserved as written and are not
restated as post-implementation observations — only the child status line
is brought current, per §0.)*

## 1. Step-09 mandate (roadmap, verbatim obligations)

Roadmap §15.1, row "§11 Interpretation | 9" (roadmap :1540):

* **Completion contract**: "Interpretation renders from the metric handle +
  task blocks; prediction grammar metric-parameterized; sign-band fixed."
* **Parity criterion**: "3 existing interpreter goldens + new ones
  EXACT-equal + same kwargs reach LLMBridge."
* **Atomic ladder**: "11-A/11-B (metric identity / table indexing)."
* **Production reachability**: "the production interpretation node renders
  a real iteration from handle+blocks."
* **Dependencies**: Step 06 (metric interface).
* **Rev 5 (§22.12)**: "owns agent-facing rendering of diagnosis / golden
  metric / secondary metrics / health / failures / cross-iteration findings
  via explicit renderers (§22.6); **D1 ResultInterpretationAgent direction
  consumers migrate here** (tuner planner/reflector ones are Step 07's —
  Rev 5.1); B/C L1 rendering fixtures."

Additional binding inputs: the strong forward-extensibility invariant
(Step-08 parent §6a.6 / roadmap §22.24, quoted in the debt audit §5); the
Step-08 §15 R5 debt (`evaluation.py` name tables — operator-directed audit,
§12 below); roadmap §22.24.4 claim boundary (after Step 08 the HEALTH
subsystem is out-of-tree extensible; full external-task workflow is NOT
claimable before Step 10/12).

## 2. Current-source audit (at `bf22827b`)

### 2.1 The node and its two-phase shape

`nodes/result_interpretation_agent/result_interpretation_agent.py` (2,144
lines). Phase 1 = one LLM call per ACTIVE model over a condensed
`ModelRunSummary` (never raw records); Phase 2 = one synthesis call over all
per-model summaries; plus vocabulary machinery (dedup LLM calls,
promotion), prediction evaluation, deterministic health-feedback merge, and
a degraded-mode fallback (`:1690-1744`) that persists a digest even when
the LLM fails. Node output is written to
`{workspace}/interpretation_{run_name}.json` (`:1726-1733` degraded path;
success path `:1641-1643` region) — the per-iteration digest.

### 2.2 The prompts are TIDMAD science, hardcoded in the framework

* `PER_MODEL_SYSTEM_PROMPT` (`:56-139`): "denoising scores", "PSD
  segments", the **Log-of-Mean trap** pedagogy, the
  `raw_baseline / ground_truth / model / gain_vs_raw / headroom_vs_gt /
  Linear_Weight / Impact_Score` table grammar and its four reading rules.
* `SYNTHESIS_SYSTEM_PROMPT` (`:386-468`): the same pedagogy again, plus
  output-field instructions that hardwire per-file semantics
  (`per_file_comparison` field; take-home rule (a)/(b) keyed on
  `Impact_Score`/`file_index`; "the aggregate denoising scalar is the log
  of a *sum* of per-segment linear energies").
* `_build_per_model_prompt` (`:239-380`): renders "Raw best score", "Worst
  denoising score", "Training PSD segments: … **(baseline typically uses
  4000)**" (a TIDMAD data-volume literal in the user prompt), per-file
  table sections (conditionally, on table presence), score trajectory with
  per-round gate annotations, and the flag-gated `### HealthGate summary`
  (`_render_health_summary_section`, `:181-238` — generic: renders
  RoundHealth/fingerprints, no task literals).
* `{TASK_DESCRIPTION}` is already authority-fed: substituted from
  `inp.task_description`, populated by the workflow via
  `get_task_description(load_task_config())`
  (`workflows/model_exploration.py:2119`, the 04b accessor).
* `tests/unit/agent/test_prompt_banned_vocabulary.py` already censuses
  PER_MODEL/SYNTHESIS prompts against pre-V9 denoise-bias tokens; it
  deliberately does NOT ban "denoising"/`denoising_score` ("the task name
  in this project") — i.e. today's prompt surface is *sanctioned* TIDMAD
  framing, to be re-owned rather than banned.

### 2.3 The D1 direction consumers owned by Step 09 (exact sites)

Interpreter-side comparisons that re-read metric direction as literals
(the pattern 07b removed from 21 tuner sites via `MetricOrder`):

| site | literal |
|---|---|
| `result_interpretation_agent.py:969,972` | `s.best_denoising_score > current_best / overall_best_score` |
| `:979` | `best_valid_denoising_score > overall_best_valid_score` |
| `:986,988` | `worst_denoising_score < current_worst / overall_worst_score` |
| `:1014,1018,1024` | cache-stats best/valid/worst re-ranking (`>`/`<`) |
| `:2046-2049` | `max(success, key=…denoising_score)` (raw best record) |
| `:2054` | `max(valid_records, key=_required_denoising_score)` |
| `:2057` | `max(valid_formal_records, …)` |
| `:2069` | `min(valid_scores)` (worst) |
| `nodes/interpretation_helpers.py:284-296` | the **sign-band**: `actual > sota` ⇒ confirmed; `actual >= sota*(1-partial_margin)` ⇒ partial — WRONG under a lower-is-better metric (roadmap :1225 "latent sign bug recorded"); `information_gain = delta if confirmed` assumes positive-is-good; `boldness` uses `abs(predicted-sota)/max(abs(sota),1e-6)` (direction-neutral but scale-naive — recorded, unchanged) |
| `interpretation_helpers.py:857-864` (`select_active_models`) | Top-K sort `key=(-score, mt)` — highest-first literal |
| `workflows/model_exploration.py:646-667` (`_cap_knowledge_cache`) | "Keep top-N by best_denoising_score", `sort(reverse=True)` — interpreter-MEMORY truncation policy hosted in the workflow file |
| *(added by the 09a child source audit, 2026-08-19 — factual census update, E1; 12 → 16 entries)* `result_interpretation_agent.py:219-221` (`_render_health_summary_section`) | best-scoring round for the recording diagnostics: `s > best_score` (flag-ON prompt path) |
| `interpretation_helpers.py:444` (`generate_discoveries`) | `sota_score = max(sota_from_prediction, overall_best_score)` — "strictest SOTA" as `max` |
| `interpretation_helpers.py:450` (`generate_discoveries`) | `best_score > sota_score` — "beating the previous SOTA (+delta)" |
| `interpretation_helpers.py:455` (`generate_discoveries`) | `best_score > sota_score * 0.95` — a SECOND relative 5% band, sign-degenerate for negative sota exactly like §2.4; margin 0.05 preserved, direction/sign corrected in 09a (Q-09a-5) |

Explicitly NOT Step 09's (allocation per roadmap V8 row :1377 and Rev 5.1):
`core/resume.py:436` `_pick_best` (`score > best_score`) and the chain
incumbents (`:1359-1370`) — workflow/resume consumers, roadmap §12 → Step
10. The tuner's 21 sites were 07b. Dashboard literals remain Step-10+
surface.

### 2.4 The prediction grammar and its aliases

**Adversarial finding (this design's own pass): the relative band is
sign-DEGENERATE for negative sota, independent of direction.** With
`sota = -2.55` (TIDMAD's actual regime) the partial band
`sota >= actual >= sota*(1-margin) = -2.4225` is EMPTY (`-2.4225 > sota`),
so production outcomes today are effectively confirmed-or-refuted only.
Any direction-correct re-banding (09a) that also fixes the sign
degeneracy makes "partial" REACHABLE for TIDMAD — a visible semantic
change to `prediction_outcomes_history` / `scientific_accuracy` /
`information_gain`. Frozen-semantics question → **Q-09-6 — RULED A**
(§21): fix it, version it, leave history untouched.

**Second production defect (rev-2 audit, from a REAL preserved digest):**
`/home/klz/Data/SIDEREIS_DATA/step07b_gate1_postrefactor/iter_002/
iteration_002/interpretation_iter_002.json` carries
`prediction_evaluation = {metric: "mean denoising_score over validation
files [4,5,6,7,8,9]", predicted_value: 1.2, actual_value: null,
current_sota: 0.0, outcome: "partial", notes: "Could not compute metric
from results."}` and `prediction_outcomes_history = {partial: 1}`. Two
things: the LLM authored a free-form metric string the grammar cannot
parse, AND the uncomputable case is **labelled "partial" and COUNTED** into
the outcome history (`evaluate_prediction` `:233-243` returns
`outcome: "partial"` for `actual is None or sota is None`; the counter at
`result_interpretation_agent.py:1550-1556` counts any of the three labels).
An unevaluable prediction is therefore indistinguishable from a genuine
near-miss in `scientific_accuracy`. The sign-safe band (§13) must also
freeze: **uncomputable ⇒ `outcome: "unevaluated"` (or equivalent named
absence), NOT counted in the three-way history** — the predicted value
`1.2` against `sota 0.0` for a negative-valued metric is exactly the
record that would have been mis-banded had it been computable.

`interpretation_helpers.py:_compute_metric` (`:317-360`): supports
`denoising_score` + hardcoded alias set `_DENOISING_SCORE_ALIASES`
(`:306-312`: "best_score", "overall denoising score", "score", …) →
`results["best_denoising_score"]`; `mean(file_vector[N:M])`;
`file_vector[N]`. `evaluate_prediction` (`:216-305`) defaults
`metric = prediction.get("metric", "denoising_score")`. Under Pets/DAVIS:
the aliases miss (`accuracy`/`mse` → `None` → outcome "partial" with
"Could not compute metric"), the `file_vector[...]` forms address evidence
that does not exist (per_sample is None for BOTH — Step-08b finding), and
the banding is direction-wrong for `mse`. This is the roadmap's "prediction
grammar metric-parameterized; sign-band fixed" obligation, precisely.

### 2.5 The interpreter-visible projection of tuner records

`tuning_output_to_model_run_summary` (`result_interpretation_agent.py:
2006-2140`) reads `HyperparamTuningOutput.all_records` and projects:
scores (`denoising_score`), configs, trajectory, conclusions
(`memory.conclusion`), ordering provenance (`ResolvedOrdering.from_record`),
RoundHealth (deterministic, from persisted gate fields via
`classify_round_provenance` / `build_gate_outcomes` /
`build_collapse_fingerprint` — `:1938-1971`), score tables, timing, PSD
segments, `scientific_authority` of the formal record.

**It does NOT project**: `record.training_history` / `record.training_diagnosis`
(07a fields, `agent/schemas/hyperparam_tuning.py:391,403`) — the diagnosis
is reflector-visible since 07b (compact P3 lines) but INTERPRETER-BLIND
today; and `record.metric_result` / `record.metric_refusal` (Step-06
additive fields, `:659,674`) — the evidence-borne metric identity/direction
never reaches the interpreter. Both gaps are named by the Rev-5 mandate
("rendering of diagnosis / golden metric / secondary metrics / … failures").

### 2.6 Health evidence is already generic at the consumer

`agent/schemas/health_feedback.py` reads persisted
`PersistedHealthGateResult` dicts SELF-DESCRIPTIVELY: worst-case stats come
from the persisted `threshold.metric` name; count-rendering from
`threshold.unit == "count"` (`:403-419`); fingerprints are
`{check_name, signature, metrics, human_readable}` — no gate-id/check-name
mapping, no int8/mV literals (`:100-150` docstrings state the design). The
producer of those `threshold` dicts is `evaluation.py` (§12).

### 2.7 Schemas and the D1-frozen names

`agent/schemas/interpretation.py` (761 lines): `ModelRunSummary`
(`:95-271`), `InterpretationInput` (`:274-489`), `InterpretationOutput`
(`:492-761`). Field names `best_denoising_score` / `worst_denoising_score`
/ `file_vector` / `score_table` etc. are the **D1-frozen record vocabulary**
(Step 06: "the frozen `denoising_score` / `file_vector` / `score_table`
names are unchanged (D1)"); `training_psd_segments` / `eval_psd_segments`
(`:249-257`) are TIDMAD-unit names in the schema. Output carries: LLM
analysis (key_findings/bottlenecks/take_home), the per-model knowledge
cache, the vocabulary system, prediction machinery, deterministic health
feedback (populated REGARDLESS of LLM success — `:708-732`), degraded flag,
evolution stats.

### 2.8 Wiring, protocols, persistence, resume (the memory map)

* The workflow builds `InterpretationInput` INLINE
  (`workflows/model_exploration.py:2097-2120`) and converts tuner outputs
  via `tuning_output_to_model_run_summary` (`:320`). The tune→interp
  protocol (`agent/schemas/protocols/ml_model_tune_to_ml_result_interp.py`)
  has NO production caller (only the protocols package re-export;
  roadmap :214 already records it as dead).
* interp→propose: `ml_result_interp_to_ml_model_propose.local_full_context`
  passes `InterpretationOutput` + workflow-supplied context into
  `ProposalInput` — the planner-visible projection is the digest itself.
* Cross-iteration memory: within one workflow process the loop carries
  `model_knowledge_cache` / `runtime_vocab` / `collapse_fingerprint_history`
  / `previous_proposal_data` forward; ACROSS chain subprocesses
  `core/resume.py::RestoredState` (`:102-220`) restores them **latest-wins**
  from the committed per-iteration digests (docstrings record the
  asymmetry rationale). The digest file is the ONE canonical persisted
  interpretation record; `evolution_log.jsonl` is an append-only metrics
  sidecar; the knowledge cache is truncated by `_cap_knowledge_cache`
  (workflow `:646-667`) and consolidated by `agent/cache_consolidator`
  (PB-8 goldens).
* Node CLI `main()` (`:1832-1899`) builds an input from one tuning-output
  file — an ad-hoc entry point, not the chain path.

### 2.9 The authorities Step 09 consumes (all landed)

* `MetricSpec` / `MetricResult` / `NotScoreableResult` / metric ids +
  directions: `execute_tools/evaluation_metric.py` (`:82,355,390,418`);
  declaration constructors `metric_spec_from_declaration` (`:657`).
* `MetricOrder`: `execute_tools/metric_order.py:59-206` — `is_better`,
  `is_at_least`, `worst(items,key)`, `worst_sentinel`, `comparison_symbol`,
  `direction_words` ("direction may be interpreted in exactly ONE module",
  guard-enforced). The tuner binds ONE per run
  (`ml_hyperparameter_tune_agent.py:541,552`; carried in
  `RunBindings.run_metric/run_order`, `contracts.py:116-120`).
* `TrainingDiagnosis` (`agent/schemas/training_diagnosis.py:68-…`, frozen,
  calibration-free) + `TrainingHistory` (`execute_tools/training_history.py
  :123`, `objective_kind: str` OPEN at `:133`).
* The 07b renderer precedent: `agent/prompt_templates/tuner/rendering.py`
  — `render_metric_identity_line` (`:264`), `render_metric_direction_words`
  (`:246`), `render_training_dynamics_line` (`:280`),
  `render_planner_dynamics_block` (`:339`),
  `render_reflector_dynamics_block` (`:371`), assembled via
  `TunerTaskRender`/`build_tuner_task_render` (`:142,186`).
* Golden corpus: `tests/unit/agent/result_interpretation_agent/goldens/`
  — PB-0 (3 per-model goldens: legacy / collapse / flag-on), PB-7
  (synthesis + dedup), PB-8 (consolidator), plus flag-parity suites
  (`test_health_prompt_parity.py`, `test_step00_prompt_goldens.py` —
  "roadmap step 09 A-surface" per its own docstring, including the
  workspace-string-interpolation hazard note at
  `result_interpretation_agent.py:638-651`).

### 2.10 Roadmap-vs-source differences (recorded, not resolved silently)

1. Roadmap :393-394 cites the inline `InterpretationInput` at
   ":2083-2106"; at this anchor the construction is `:2097-2120` (drifted
   line numbers only; the fact stands).
2. The Rev-5 row says "D1 ResultInterpretationAgent direction consumers
   migrate here". Source shows two ADJACENT consumers whose file ownership
   is ambiguous under that sentence: `select_active_models` /
   `should_recall_per_model` (helpers file — interpreter policy) and
   `_cap_knowledge_cache` (workflow file — but interpreter-MEMORY policy).
   This design allocates BOTH to Step 09 (§7: the semantic owner is
   interpreter memory/policy, wherever hosted) — **Q-09-3 RULED: 09a owns
   the semantic migration; the helper stays physically in the workflow
   file** (§7).
3. Roadmap V8 row (:1377) lists "dashboard" among remaining direction
   literals — not mentioned in the §11 row; allocated OUT of Step 09 here
   (Step 10+ surface; no interpreter dependency).

### 2.11 The run-metric lifecycle — ONE authority, and how its value can travel (rev 2, ruling §2)

Census of every production `derive_tidmad_metric` call (source at the
anchor):

| site | role |
|---|---|
| `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py:541` | the tuner's run-scope binding — `run_metric = derive_tidmad_metric(run_profile, run_deliverable_spec)`; `run_order = MetricOrder(run_metric.spec)` at `:552`; both carried in `RunBindings.run_metric/run_order` (`contracts.py:116-120`) |
| `execute_tools/denoising_score_single.py:180` | the scoring SUBPROCESS re-derives an equal value from `--dataset_profile_json` (the documented parent→child transport; tuner comment `:532-540`: "Not serialized; crosses no process boundary") |
| `core/sandbox_executor.py:2009` | in-process fallback `metric if metric is not None else derive_tidmad_metric(resolve_dataset_profile())` |

All three resolve from the SAME ambient profile
(`resolve_dataset_profile()` = `_ACTIVE_PROFILE.get() or TIDMAD_PROFILE`,
`dataset_config.py:596-613`), so today they cannot disagree — but the
tuner's RESOLVED `MetricSpec` leaves the tuner NOWHERE: `HyperparamTuningOutput`
(`agent/schemas/hyperparam_tuning.py:2665-…`) carries scores, configs,
tables, `all_records`, gate/authority stamps — no metric spec; the only
metric identity that leaves the tuner is the per-record
`metric_result.metric_id/direction` (`:659`).

**Route decision (ruling §2 order A/B/C).** A ("resolve once at an existing
run-level authority and pass the same value to all consumers") does not
exist in source today: there is no run-level object shared by tuner and
interpreter — the tuner IS the run-scope authority, and the interpreter
runs in the workflow loop AFTER it (`model_exploration.py:2687` →
`:2097`). Creating one would be the Step-10/12 composition root. **B is
structurally available with ONE writer and ONE reader**:
`finalize_run_output(bindings, …)` (`records.py:747-…`) already receives
`RunBindings` — which holds `run_metric` — and builds the output dict in
one place (`records.py:863`); the workflow consumes that output at
`:2687-2721`. Therefore: **`HyperparamTuningOutput.metric_spec`
(additive, `MetricSpec` dump, written from `bindings.run_metric.spec`)**;
the workflow reconciles every tuning output's `metric_spec` it feeds the
interpreter (all must be equal — one run, one metric; mismatch = fail
closed) and passes THAT value as `InterpretationInput.metric_spec`. C
(independent interpreter-side derivation) is REJECTED as the ruling
requires. Consequence for the rev-1 debt row "one more regime-A site" —
**deleted**: 09a adds ZERO new derivation sites; the spec's single
derivation remains the tuner's (`:541`), which Step 12 replaces at the
composition root without touching the interpreter.

Legacy/ad-hoc inputs (outputs predating the field; the CLI `main()` and
`scripts/pr3_l2_calibration/preflight.py:107-121` paths): `metric_spec
is None` ⇒ score-bearing interpretation FAILS CLOSED (no ordering
default); those two entry points are audited in 09a and supplied
explicitly (R-09-3).

### 2.12 Secondary metrics — the contract gap, audited (rev 2, ruling §4)

Source at the anchor, every question the ruling poses:

* **Declared where?** Only in reference packs as declaration JSON
  (`examples/oxford_iiit_pet/declared/metric_macro_f1.json`;
  `examples/davis_future_prediction/declared/metric_{psnr,mae}.json`),
  constructible via `metric_spec_from_declaration`
  (`evaluation_metric.py:657`). TIDMAD declares none (Step-06 §16-Q4
  "ACCEPTED: none — no consumer"; `step_06_metric_interface.md:454`).
* **Results stored where?** NOWHERE. `MetricResult` (`:390-417`) is ONE
  result (`metric_id, direction, scalar, per_sample, references_used`);
  `ExperimentRecord` carries exactly ONE `metric_result` (+ exclusive
  `metric_refusal`) (`hyperparam_tuning.py:659-696`); the tuner writes it
  once per attempt (`execution.py:882-915` → `records.py:1110`). A grep for
  "secondary" across `evaluation_metric.py`, the record schema, the
  interpretation schema, the tuner modules and `sandbox_executor.py` finds
  ZERO carriers (the single hit, `runtime.py:846`, is the unrelated RT5
  "secondary guardrails" docstring).
* **Evaluated where?** NOWHERE — no production route invokes a second
  metric handle; the D14 runners evaluate exactly one metric each.
* **Reaching `ModelRunSummary`?** Impossible today — nothing upstream
  exists to project.

Step 06 froze the SEMANTIC stance — "secondary metrics representable as
further `MetricSpec`s … recorded but never consulted by policy" (§6) — and
the roadmap's item 6 ("golden metric drives incumbent/best selection;
secondary metrics are evidence for reasoning") is exactly the rule this
design freezes (§4b). What is MISSING is transport: an evaluation route, a
record carrier, an output/summary projection. **Satisfying the roadmap's
"render secondary metrics" literally therefore requires NEW
evaluation+persistence plumbing upstream of the interpreter (tuner
records), not a reopening of Step-06 semantics** — the carrier SHAPE is
fully determined by Step-06 authorities (§4b) and adds no new vocabulary.
Per the ruling ("do not fabricate one silently"; "determine whether the
narrow additive carrier belongs to 09a"): the carrier is DESIGNED here
(§4b) and its ownership was surfaced as **Q-09-7** — the ONE question
rev 2 could not close from source alone, because it is a scope decision.
**RULED B (2026-08-19, §0.2): Step 10 owns the tuner-side evaluation /
record persistence / workflow transport; Step 09 renders
present-when-present.** Everything interpreter-side is frozen: typed open
collection in, rendered with its own identity/direction, never consulted
for ordering.

### 2.13 Prediction-history aggregation — how old and new records would mix (rev 2, ruling §8)

`result_interpretation_agent.py:1548-1575`: `prediction_outcomes_history`
is DESIGNED as a carried-forward dict of three pooled COUNTS (no per-record
provenance), incremented by the current iteration's `outcome` label
(`:1550-1556`); `scientific_accuracy` = per-bucket fraction of the pooled
total (`:1557-1562`); `cumulative_information_gain` = running sum (`:1571`).
Degraded mode carries the INPUT values forward unchanged (`:1719-1721`).
**FACTUAL SOURCE ERRATUM (09a child audit E2, 2026-08-19 — factual source
correction only; frozen Step-09 architecture unchanged):** rev 2 stated
here that these fields "restore latest-wins from the committed digest
(`core/resume.py` `RestoredState`)". At the anchor that is FALSE: NO
production path populates them — the workflow's inline
`InterpretationInput(...)` (`workflows/model_exploration.py:2097-2120`)
passes none of `prediction_outcomes_history` / `cumulative_information_gain`
/ `vocab_link_confirmations`; the in-process loop (`:2724-2746`) carries
only cache / vocab / fingerprints / proposal; `core/resume.py` has zero
occurrences of the three names; `run_one_iteration.py` forwards none. Every
production digest's pool is therefore exactly ONE outcome (the preserved
`step07b_gate1_postrefactor` digest: `{partial: 1}`). Pre-09a source: no
prediction-pool carry/restore. Frozen Step-09 target (operator ruling
Q-09a-1 = A, narrow): **09a lands the NARROW interpreter-owned carry/restore
of the prediction-memory fields through the EXISTING canonical lifecycle**
(digest → next-iteration workflow carry → existing `RestoredState`
latest-wins), generic resume policy untouched; the E.7
`vocab_link_confirmations` carry stays absent (Step-10 debt, §19).
Consumers: the PROPOSER renders all
three into its prompt ("### Prediction Track Record",
`ml_model_proposal_agent.py:1147-1160`; also whitelisted at `:1681-1683`);
the workflow's lit-review gate documents them as "reserved for future
content-based gating; not consulted in v1" (`model_exploration.py:478-492`).
The interpreter's own synthesis prompt renders
`cumulative_information_gain` (`:717-729`).

Consequences frozen in §8: (i) a corrected band changes FUTURE counts, so
pooling v1 and v2 outcomes into one `scientific_accuracy` scalar would mix
incomparable classifications — the rule is **version-partitioned
additive counters** (no schema migration: the existing three-bucket dict
stays the legacy/v1 pool exactly as carried; NEW outcomes accumulate in an
additive versioned structure; `scientific_accuracy` is computed ONLY within
the current semantics version, and the digest states the version and the
legacy pool size explicitly — exact per-field spellings frozen in the 09a
child §3.4 by operator ruling Q-09a-2); (ii) because the proposer RENDERS these
fields, 09a's corrected band IS reachable in next-iteration prompt CONTENT
even with prompt-TEMPLATE bytes exact — recorded honestly in §16 (09a) per
ruling §9; (iii) uncomputable predictions stop polluting the pool (§2.4
second defect).

## 3. Existing semantic ownership map (who owns what today)

| surface | producer | semantics owner | consumers today | raw vs interpretation | persisted | planner-visible | interpreter-visible |
|---|---|---|---|---|---|---|---|
| `ExperimentRecord.denoising_score/file_vector/score_table` | scoring route (Step 06 handle) | metric (frozen TIDMAD instance) | tuner policy, summary builder, resume, dashboard | raw evidence | yes (records) | via digest projections only | yes (summary) |
| `metric_result`/`metric_refusal` | Step-06 handle | metric | tuner records; **nobody downstream of records** | raw evidence + identity | yes | no | **no (gap)** |
| `training_history`/`training_diagnosis` | trainer (07a) / tuner boundary | framework (calibration-free facts) | tuner reflector (07b P3 compact lines) | raw + deterministic derivation | yes | reflector-only | **no (gap)** |
| `health_gate_results` (`PersistedHealthGateResult`) | `evaluation.py` (tuner exec `:963`; run_comparison `:471`) | Health (Step 08) | candidate eligibility; interpreter RoundHealth | raw evidence | yes | counts/named-absence only (08 policy) | yes (condensed, deterministic) |
| `memory.conclusion` (per-round reflection) | tuner reflector (LLM) | tuner | summary trajectory lines | interpretation (LLM) | yes | yes (trajectory) | yes |
| `ModelRunSummary` | `tuning_output_to_model_run_summary` | **interpreter (Step 09)** | interpreter phases | projection of raw | no (transient; digest carries derived stats) | n/a | yes |
| `InterpretationOutput` digest | interpreter | **interpreter (Step 09)** | proposer (protocol), resume restore, evolution log | mixed: LLM analysis + deterministic feedback | yes (`interpretation_{run}.json`) | yes (via proposer protocol) | self |
| `runtime_vocab` / discoveries / predictions | interpreter (+proposer proposals) | interpreter | proposer, next-iter interpreter | interpretation (structured) | yes (digest) | yes | yes |
| `collapse_fingerprint_history` | interpreter (deterministic merge) | interpreter (V19 PR3 contract) | next-iter interpreter; prompts only when flag ON | deterministic evidence memory | yes | flag-gated | yes |
| chain incumbents / accumulated findings | `core/resume.py` | workflow (Step 10) | next chain subprocess | projection | digests + manifests | yes | partially (restored inputs) |
| interpreter prompts (PER_MODEL/SYNTHESIS + user blocks) | node constants/builders | **today: framework hardcodes TIDMAD science** | LLM | — | goldens | — | — |

**Boundary statements this design freezes (§7):** the interpreter
RECOMMENDS (prose + structured vocabulary/prediction records consumed by
the proposer) and never mutates workflow state: it selects no model, gates
no round, writes no tuner/record fields; the tuner retains
round/candidate/policy authority (07b); the planner/proposer retains
proposal authority; Health retains verdicts; the metric retains scoring;
07a retains diagnosis derivation. Step 09 must not create a second scorer,
second Health classifier, second diagnosis, or an alternate control plane
— its deterministic outputs are PROJECTIONS of persisted evidence, its LLM
outputs are clearly-labelled interpretation.

## 4. Exact Step-09 input contract

All additions are ADDITIVE fields; the D1-frozen names stay (D1 unchanged).

| input | source authority | why Step 09 needs it | nature |
|---|---|---|---|
| `HyperparamTuningOutput.metric_spec` (NEW additive, `MetricSpec` dump; written ONCE from `bindings.run_metric.spec` in `finalize_run_output`, `records.py:747-863`) → `InterpretationInput.metric_spec` (NEW, the reconciled value) | the tuner's existing run-scope binding (`ml_hyperparameter_tune_agent.py:541` — the ONE derivation; §2.11 route B) — the workflow reconciles all outputs' specs (equal or fail closed) and forwards ONE value; Step 12 later supplies the same typed value from the composition root | ONE run-scoped ordering + identity authority for every interpreter comparison and rendered line (the 07b pattern); NO second derivation site | reference/declaration (transported evidence of the run's binding) |
| `ModelRunSummary.training_diagnosis` (NEW, `TrainingDiagnosis \| None`, from the record the summary's best/formal facts came from — one per role as designed in the child) | `ExperimentRecord.training_diagnosis` (`hyperparam_tuning.py:403`) | Rev-5 mandate: agent-facing rendering of diagnosis | verbatim persisted evidence |
| `ModelRunSummary.metric_identity` (NEW: `{metric_id, direction}` from the formal/best record's `metric_result`; refusal summary from `metric_refusal`) | record `:659,674` | evidence-borne identity/provenance; refusal-derived failure rendering ("not_scoreable" rounds are failures the interpreter currently cannot name); consistency check vs the run spec (§4a) | normalized evidence |
| `ModelRunSummary.secondary_metrics` (NEW, typed OPEN collection — §4b) | the additive record carrier (§4b) — production transport is Step 10's (Q-09-7 = B, §0.2); Step 09 projects present-when-present, a declared-but-absent secondary is a NAMED ABSENCE | Rev-5 mandate: render secondary metrics with their own identity/direction | verbatim persisted evidence |
| existing `summaries` fields (scores, tables, RoundHealth, ordering, conclusions, timing, volumes) | §2.5 | unchanged | projection |
| existing carry-forward memory (cache, vocab, fingerprints, prediction history) | §2.8 | unchanged | memory |
| `task_description` | 04b accessor (unchanged) | prompt context | declaration |
| `InterpretationInput.task_blocks` (NEW, typed `InterpretationTaskBlocks` VALUE — §13) | caller-supplied; regime-A compatibility adapter resolves TIDMAD's from ONE dedicated TIDMAD-owned declaration (§13 ¶3); Step 12 supplies it from the external package | task science in prompts, task-owned | declaration (typed value) |

NOT included (considered and refused): raw `all_records` (the summary
projection is the deliberate token boundary — §2.1); `PerSampleEvidence`
enum from HealthCheckContext (a tuner-context statement; the interpreter's
per-sample presence signal is table/vector presence + `metric_result.
per_sample` via `metric_identity`); tuner decision internals
(`resolved_action` etc. — tuner-owned, adjacent debt, not evidence the
interpreter may reinterpret); Health CHECK thresholds beyond what
`PersistedHealthGateResult` already carries (§2.6).

### 4a. Metric-spec ↔ record-borne identity: ownership + fail-closed consistency (FROZEN)

* **Run-bound `metric_spec`** owns ORDERING and the run-level metric
  identity/direction words (every `MetricOrder`, every rendered identity
  line, the prediction default).
* **Record-borne `metric_result.metric_id/direction`** owns EVIDENCE /
  PROVENANCE (which metric actually scored THIS record).
* Rule: whenever a record carries a primary `metric_result`, its
  `metric_id` AND `direction` MUST equal the run-bound spec's. Across the
  outputs that feed one interpretation, every present primary identity
  must agree with the SAME run spec. A mismatch is a deterministic contract
  ERROR (fail closed) raised BEFORE ordering, prediction evaluation and any
  prompt rendering — never a silent preference for either source.
* A `metric_refusal` legitimately carries no `MetricResult`; the run spec
  still supplies identity/direction context for rendering it.
* Score-bearing summaries with NO run spec: fail closed (no silent
  higher-is-better). Cold-start (`inp.cold_start`, the deterministic
  no-LLM branch at `result_interpretation_agent.py:880-907`) and genuinely
  scoreless inputs need no ordering and accept a NAMED absence
  (`metric_spec is None` recorded as such in the digest's `metric_identity`
  provenance).
* 09a owns explicit negative tests for every clause above.

### 4b. Secondary metrics — the exact generic transport (carrier designed; ownership Q-09-7 = B, §0.2)

Step-06 authorities are sufficient to TYPE the carrier with zero new
vocabulary:

```text
record level   (additive, per ExperimentRecord)
  secondary_metric_results: list[MetricResult]            # each with its own metric_id/direction
  secondary_metric_refusals: list[NotScoreableResult]     # refused secondaries, named
tuning-output level (additive)
  secondary_metric_specs: list[MetricSpec]                # the run's declared secondaries (0..n)
summary level  (09a projection)
  ModelRunSummary.secondary_metrics: list[{spec_or_identity, result|refusal}]
                                                          # from the formal/best record(s)
```

Semantic rule (FROZEN, roadmap item 6 + Step-06 §6): PRIMARY owns run
ordering / incumbent comparisons / prediction default; SECONDARIES are
observational evidence ONLY — rendered with their OWN identity and
direction words (their own `MetricOrder` for wording, never for ranking
models), and NEVER consulted by interpreter ordering, active-model
selection, cache capping or prediction evaluation. Declared-but-absent
secondary ⇒ rendered as a named absence, never a number. No task-specific
field anywhere.

Ownership (Q-09-7 = B, RESOLVED — §0.2): the interpreter-side
projection/rendering is 09a/09b; the UPSTREAM half (tuner-side evaluation
of declared secondaries through the same Step-06 handle pattern + record
persistence + workflow transport) is **Step 10's**, when the generic
workflow/persistence path first carries task-declared secondary metrics.
Step 09 renders present-when-present; the three-task fixtures carry
carrier-shaped secondaries built from the packs' declared specs
(Pets `macro_f1` higher; DAVIS `psnr` higher + `mae` lower; TIDMAD none)
— L1 contract evidence, not a production-evaluation claim. The record- and
output-level lines of the carrier above are the contract Step 10 must
land UNCHANGED (it must not invent a replacement Step-09 schema); 09a
lands only the summary-level projection and its consumers.

## 5. Exact Step-09 output contract

`InterpretationOutput` keeps its shape; additions are additive:

* **Deterministic metadata (framework-owned)**: existing fields; plus NEW
  `metric_identity` echo (`{metric_id, direction}` actually used for
  ordering this iteration, or the named absence — provenance for the digest
  reader); NEW `prediction_evaluation_semantics` version id (§8 — the
  framework semantics that produced THIS iteration's prediction outcome:
  legacy records have no field ⇒ `legacy_v1`; Step-09 records carry
  `metric_order_signsafe_v2`, exact repository spelling fixed in 09a's
  child design); NEW versioned outcome counters (§8); NEW per-model
  failure-rendering counts **derived ONLY from existing authoritative
  vocabularies** — `TrainingDiagnosis.state` (`ok/absent/invalid`),
  `ValidationState`, `NotScoreableResult` (refusal present / its verdict),
  Health `CheckVerdict` / `GateAction` / `RoundHealth.provenance`, and
  execution `status`/`failure_reason` presence. **No new closed
  `FailureKind` enum**: the interpreter counts and renders what those
  authorities already state; a fourth task with a novel pathology expresses
  it at its owning layer (a Health check verdict, a refusal, a diagnosis
  state) and the interpreter renders it without source growth.
* **LLM-authored (clearly bounded)**: key_findings, bottlenecks,
  take_home_message, per-model narrative fields, discovery sentences —
  unchanged in kind; regenerated under direction-correct instructions.
* **Prediction evaluation**: same record shape plus the version field;
  outcome computed via `MetricOrder` under the frozen sign-safe band (§13
  ¶1); uncomputable ⇒ `unevaluated` (NOT counted in the three-way
  history, §2.4); `metric` defaults to the bound metric id, not the
  literal `"denoising_score"`.
* **No new authority**: the output still cannot mutate workflow state;
  consumers unchanged (proposer protocol, resume, evolution log).

Answering §5's fixed questions: one typed record (yes — the existing
digest); observations/hypotheses/confidence — key_findings/bottlenecks
carry observations+hypotheses as today (no numeric confidence field is
added; nothing consumes one; adding one would be decoration); recommended
next action — take_home_message + proposer-consumed vocabulary (unchanged);
cross-iteration lessons — discoveries/vocab (unchanged); unresolved
uncertainty — degraded flag + provenance labels (unchanged); failure
classification — the NEW deterministic counts. Parts persisted for
provenance only: scientific_aggregation, evolution_stats, fingerprints
(flag-gated visibility). What prevents a control plane: the consumers —
the proposer reads prose/vocab; no code branches on interpretation fields
to alter tuner/workflow behavior, and the census (§18) pins that.

## 6. Raw evidence vs interpretation boundary

Preserved and sharpened: deterministic health feedback populated regardless
of LLM outcome (existing §3.10 invariant, `interpretation.py:708-732`);
scientific_aggregation computed BEFORE any LLM call (`:543-561` rationale);
NEW deterministic fields follow the same rule. Raw records stay immutable
(the interpreter reads `HyperparamTuningOutput`, writes only its own
digest). LLM text never overwrites deterministic fields; degraded mode
keeps evidence and empties commentary only (`:1690-1744`). Summaries are
additive projections; they never replace records (records remain on disk in
run outputs; `persistence != visibility` — the digest hides nothing that
was persisted elsewhere, it CONDENSES for prompts).

## 7. Tuner / reflector / planner / interpreter ownership boundaries

* **Tuner** (07b): round/attempt policy, incumbent selection, planner +
  reflector prompts, `memory.conclusion`. Step 09 reads conclusions
  verbatim; never re-derives policy.
* **Reflector**: per-round LLM reflection INSIDE the tuner. The interpreter
  is the per-ITERATION cross-model analyst. They own different products
  (round conclusion vs iteration synthesis); both consume the SAME
  persisted diagnosis rather than re-deriving (no second diagnosis).
* **Planner/proposer**: consumes the digest; owns proposals. Unchanged.
* **Interpreter (Step 09)**: the digest — its projections, its prompts,
  its memory policy (active-model selection, cache cap semantics), its
  prediction evaluation, its direction consumers.
* **Workflow/resume (Step 10)**: wiring, restore, chain incumbents
  (`resume.py:436,1359-1370` literals stay Step 10), dashboards.

**Semantic owner ≠ physical file location (Q-09-3 ruling).**
`_cap_knowledge_cache` (`workflows/model_exploration.py:646-667`) is
interpreter-MEMORY truncation/ordering policy hosted in the workflow file.
09a owns its SEMANTIC migration — the comparison is parameterized through
the same run `MetricOrder` (no independent direction literal remains) —
while the helper STAYS physically where it is: retention count (5) and
window semantics unchanged, the public workflow orchestration unchanged,
no code moved merely to make filesystem ownership match semantic
ownership. The same distinction applies to `select_active_models` /
`should_recall_per_model` (helpers file): semantic owner 09a, location
unchanged.

## 8. Cross-iteration memory / persistence / visibility contract

Single-owner audit result (§2.8): there is ONE canonical persisted
interpretation record per iteration (the digest), one restore path
(`RestoredState`, latest-wins, documented asymmetries), one truncation
authority (`_cap_knowledge_cache` + consolidator), and the planner-visible
projection IS the digest via the proposer protocol. Step 09 does NOT add a
second memory: no interpreter-private store, no separate failure-summary
memory. Changes limited to: (a) migrating the two memory-policy direction
literals (§2.3) onto `MetricOrder`; (b) documenting the digest as the
canonical record in the node `.md`; (c) additive digest fields (§5).
Raw evidence remains immutable; summaries remain additive; truncation
rules unchanged (cap=5, consolidator windows) — changing retention numbers
is NOT in scope.

**Prediction-semantics versioning + aggregation rule (FROZEN, from §2.13):**

* Every NEW `prediction_evaluation` record and every digest carries
  `prediction_evaluation_semantics` (framework semantic-version metadata,
  NOT task identity). Absence ⇒ `legacy_v1`. Old persisted digests are
  NEVER rewritten.
* The legacy three-bucket `prediction_outcomes_history` dict is carried
  forward UNCHANGED as the v1 pool. *(Factual erratum, 2026-08-19 — see
  §2.13: the pre-09a source has NO production carry/restore of this dict;
  "restore semantics untouched — `RestoredState` latest-wins" in rev 2
  described an intended lifecycle, not the source. Frozen target by
  operator ruling Q-09a-1 = A narrow: 09a C5 adds the NARROW interpreter-
  owned carry/restore of the prediction-memory fields through the existing
  canonical digest → workflow carry → `RestoredState` latest-wins path;
  generic resume policy, chain-incumbent restoration and every other
  restored field untouched.)* NEW outcomes accumulate in an ADDITIVE
  version-keyed structure (`prediction_outcomes_by_semantics:
  {version: {confirmed, partial, refuted}}`, exact naming fixed in 09a) and
  are NOT added to the v1 dict.
* `scientific_accuracy` is computed ONLY within the CURRENT semantics
  version (`metric_order_signsafe_v2` pool); the digest states the version
  and the legacy pool's size so no reader can mistake a pooled statistic
  for a comparable one. `cumulative_information_gain` likewise: legacy and
  v2 gains are NEVER pooled — the legacy accumulated value is preserved in
  the existing field and the v2 running sum lives in its own additive
  version-keyed field (exact per-field spellings: 09a child §3.4, operator
  ruling Q-09a-2) — no mixed-version single scalar is claimed.
* `unevaluated` outcomes (uncomputable predictions, §2.4) are recorded on
  the prediction record and counted in neither pool.
* Consumers: the proposer's "Prediction Track Record" rendering
  (`ml_model_proposal_agent.py:1147-1160`) reads the digest fields it
  already reads; 09a supplies the versioned fields such that the rendered
  accuracy is the version-pure one and the DIGEST labels it (the
  proposer's rendered `N` still comes from the legacy dict it reads — a
  declared deterministic content delta, operator ruling Q-09a-3; a
  proposer TEMPLATE edit is never made in 09a — if one is needed for an
  honest v1/v2 distinction, implementation STOPS). This is possible
  without a schema migration because all additions are additive and the
  legacy dict is left byte-for-byte as carried.

## 9. Strong extensibility audit matrix (A–F per new/modified surface)

| surface | A semantic contract | B binding | C discovery | D config ownership | E registration | F vocabulary |
|---|---|---|---|---|---|---|
| interpreter ordering/identity | OPEN — any `MetricSpec` (direction Literal higher/lower is universal per debt item 13) | `InterpretationInput.metric_spec` VALUE, reconciled from the tuner's additive `HyperparamTuningOutput.metric_spec` (the ONE existing derivation's value, transported — §2.11 route B) | n/a (value, not code) | the run's binding; Step 12 replaces the tuner's regime-A derivation at the composition root and the SAME value flows — **no new derivation site** | none | none new |
| record ↔ spec consistency (§4a) | framework rule, metric-agnostic | n/a | n/a | n/a | none | none |
| prediction grammar + versioned band | OPEN — bound metric id + capability-gated per-sample forms; band via `MetricOrder` only | from `metric_spec` + evidence presence | n/a | n/a | none | alias set DELETED, not grown; forms keyed on evidence capability, not task; `prediction_evaluation_semantics` is FRAMEWORK version metadata, not task vocabulary |
| secondary metrics (§4b) | OPEN — typed collection of Step-06 `MetricSpec`/`MetricResult`/`NotScoreableResult` | record/output-borne (carrier transport = Step 10, Q-09-7 = B; Step 09 = summary projection, present-when-present) | n/a | task declares secondaries (packs already do, as JSON) | none | none (open ids, universal direction) |
| `InterpretationTaskBlocks` (§13 ¶3) | OPEN — a typed VALUE of declarative prose sections any task can author | caller supplies the value (`InterpretationInput.task_blocks`); regime-A: ONE bounded compatibility adapter resolves TIDMAD's value from ONE dedicated TIDMAD-owned declaration | with Step 12 the external package supplies the value directly — the missing composition root is the ONLY gap (class B; the contract is open); the interpreter never discovers task files itself | task-owned declaration content; **no new science in framework-owned central `task_config.yaml`**; no central per-task table | none | section keys = FIXED framework-protocol set (`evidence_reading`, `per_model_guidance`, `synthesis_guidance`, `prediction_guidance`); growth is a framework decision, never per task |
| explicit renderers (interp prompt-templates module) | framework-owned protocol; renders ONLY from authorities (MetricOrder words, diagnosis, health counts, secondaries, blocks) | function args | n/a | n/a | none | none |
| additive summary/digest fields | typed, task-free (`TrainingDiagnosis`, `{metric_id, direction}`, secondaries, version id, counts from existing authorities) | record-borne | n/a | n/a | none | none (no new failure enum — §5) |

Fixed questions: unknown/missing semantics fail closed — a summaries-with-
scores input WITHOUT `metric_spec` refuses ordering (no silent
higher-is-better default; cold-start/no-score paths use a NAMED absence);
a record identity disagreeing with the run spec fails closed (§4a); no ID
spelling inspected (identity rendered verbatim, ordering from `direction`
only, check ids/provider ids never parsed); a fourth task needs NO
SIDERIUS source commit for interpretation semantics ONCE Step 10/12 binds
the composition root — today TIDMAD's built-in blocks ride a bounded
regime-A adapter that is compatibility plumbing, NOT an extension
mechanism, and NO additional task science enters the central task config
(the existing B-class task-config debt, items 1/12, is not deepened);
Step 10/12 supplies typed values (spec, blocks, secondaries) around the
SAME contracts — no interpreter-specific loader exists to replace, by
design.

**Strong-extensibility verdict: PASS** (the ruling's criteria, each met:
no new central task-science content; no new independent regime-A metric
derivation; no subsystem-specific plugin loader; no task-name branch; no
per-task enum/list growth; no central registration requirement; Step 12
supplies typed values around the same Step-09 contracts rather than
replacing them).

## 10. Three-task contrast analysis (source-grounded)

| evidence axis | TIDMAD | Pets | DAVIS |
|---|---|---|---|
| golden metric | `tidmad_denoising_score`, higher (`evaluation_metric.py:82,700`) | `accuracy`, higher (`examples/oxford_iiit_pet/declared/metric_accuracy.json`) | `mse`, **lower** (`examples/davis_future_prediction/declared/metric_mse.json`) |
| secondary metrics | none declared | `macro_f1` higher | `psnr` higher, `mae` lower |
| per-sample evidence | `file_vector` present; score_table with baseline/GT references | `per_sample=None` (scalar-only; 08b finding) | `per_sample=None` (scalar-only) |
| scoreability | frozen contract + refusal path | Presence contract | Presence contract |
| objective / diagnosis | focal-family CE; diagnosis ok/curves | `objective_kind="ce"` (07a fixtures; D14 runner `LossConfig(loss_type="ce")`) | `objective_kind="smooth_l1"` (runner `beta=0.1`) |
| Health family | 6 int8/mV checks (3 blocking + 3 recording) | 2 categorical blocking (distinct/dominant; real collapse fixture 369/370) | 1 continuous blocking (dispersion 0.04) |
| failure modes seen | OOM, mode collapse, gate invalidation | constant-prediction collapse (accuracy = chance) | none observed (healthy artifact; near-collapse synthetic) |
| artifact semantics | per-file HDF5 denoising | one CSV classification | one npz future-frame regression |

Consequences the contract must survive WITHOUT task branches: direction
varies (DAVIS breaks every `>`-literal and the sign-band); per-sample
evidence is ABSENT for 2 of 3 (every per-file prompt section, the
`file_vector[...]` grammar forms and the Impact_Score pedagogy must be
capability-gated + task-block-owned, never generic assumptions); secondary
metrics exist only as declarations for B/C today (rendered when supplied —
no per-sample assumption); Health shapes differ in count and science
(counts + fingerprints render generically, §2.6 — already proven); the
generic record assumes neither denoising nor classification nor regression
(scores are floats + direction; tables are optional evidence).

Maturity honesty: Pets/DAVIS have NO tuner/workflow integration (Step-08
parent §3.3.3; roadmap §22.24.4). Step 09's three-task evidence is
**L1 rendering/contract fixtures** (Rev-5 row: "B/C L1 rendering
fixtures"): typed `ModelRunSummary`/digest fixtures with lower-direction +
scalar-only + contrast diagnosis/health shapes, driven through the real
builders/renderers — contract-level proof, not full-workflow maturity.

## 11. Historical-debt dependency audit (only what Step 09 touches)

From `step_01_07_extensibility_debt_audit.md` §2:

* **Item 13 (B) — metric surface**: semantic layer open; no
  registry/loader; binding by direct construction. Step 09 depends ONLY on
  the open layer (`MetricSpec`/`MetricOrder` values). No interpreter
  metric loader is created (brief §3). Not deepened; not promoted.
* **Item 12 (B) — tuner regime-A `derive_tidmad_metric` (`:541`)**:
  **Step 09 adds NO new derivation site** (rev-2 correction per the
  operator ruling; rev 1 had proposed one). The tuner's resolved spec is
  transported additively on `HyperparamTuningOutput` (§2.11 route B) and
  reconciled by the workflow — one writer, one reader, the SAME value. The
  rev-1 objection to this route ("the digest may cover models tuned in
  prior processes") is answered by reconciliation: every output feeding one
  interpretation must carry an equal spec (one run = one metric) or the
  interpretation fails closed; prior-process outputs restored by resume
  carry their own stamped spec and are reconciled identically. Per-output
  duplication of one small value is provenance, not debt. Item 12 itself
  remains exactly as accepted (Step-12 owner), not deepened.
* **Items 1/2 (B) — task-config central YAML + ambient TIDMAD fallback**:
  the interpreter keeps consuming `task_description` via the 04b accessor
  (unchanged); **task blocks do NOT ride the central task config** (Q-09-1
  ruling) — TIDMAD's blocks live in ONE dedicated TIDMAD-owned declaration
  resolved by a bounded compatibility adapter, so NO additional task
  science enters the framework-owned central YAML. Not deepened (and not
  widened).
* **Item 15 (SATISFIES)** history/diagnosis and **item 16 (CLOSED)** health
  registration: consumed as-is.
* Items 5 (TaskDataPath), 7 (output-type vocab), 14 (objectives): not on
  Step-09's path; untouched.

No B finding is promoted to A: none of these closed contracts would be
baked into a NEW public contract by this design (the new inputs are typed
values and declarations, both replaceable by the composition root).

## 12. `evaluation.py` debt disposition (Step-08 §15 R5 — mandatory audit)

Source at the anchor: `execute_tools/health_checks/evaluation.py:270`
`evaluate_and_persist_health_gates` — callers: tuner execution
(`nodes/ml_hyperparameter_tune_agent/execution.py:46,963`) and
`scripts/run_comparison.py:58,471`. Its `_threshold` (`:83-106`) and
`_per_file_metrics` (`:109+`) tables dispatch on the six TIDMAD CHECK
names.

* Is it in Step-09's path? **Upstream of it**: it PRODUCES the persisted
  gate records the interpreter condenses. The interpreter-side consumer is
  already declaration-shaped (§2.6: reads `threshold.metric` /
  `threshold.unit` self-descriptively, no name mapping).
* Does Step 09 need generic Health metadata from it? No — everything the
  interpreter renders comes from the persisted record fields that exist
  for ANY check (verdicts, actions, metrics dict, fingerprint inputs);
  for non-tabled checks `threshold` is `None` and the fingerprint
  machinery already tolerates that (`.get("threshold") or {}`,
  `health_feedback.py:408`).
* Would leaving it force Step 09 to encode check knowledge? No. Would
  Step 09 deepen it? No — Step 09 adds no entry and no new caller.
* Reachability note: the tuner path evaluates only the composed TIDMAD
  roster today; the generic 08c checks reach production only through the
  D14 runner stage (which does NOT use `evaluate_and_persist_health_gates`).
  The name tables therefore currently cover exactly the checks that can
  reach them.

**Disposition: B — forward constraint, defer repair. Recommended owner:
Step 10** (workflow/persistence genericization — when a composed non-TIDMAD
roster first reaches the tuner path, threshold/per-file persistence must
become declaration-driven: `threshold_parameter_names` + check `metrics`
already carry the needed facts). Not Step 09 (would be an unforced
production-persistence change in an interpretation PR); not post-Step-12
(it sits on the exact boundary Step 10 must cross). This refines the 08c
review note "Step 9/10" to Step 10, with the source evidence above.

## 13. Proposed architecture

Freeze the interpreter's semantics into three framework-owned protocols
plus one task-owned declaration:

1. **Ordering & identity (deterministic)** — every §2.3 consumer takes the
   run-scoped `MetricOrder` built ONCE from `InterpretationInput.
   metric_spec` (the tuner's transported value, §2.11); fail-closed when
   scores exist but no spec does, and when a record identity disagrees with
   the spec (§4a); identity lines rendered via the 07b renderer idiom
   (`render_metric_identity_line` pattern), never from field-name prose.
   **The prediction band, FROZEN (Q-09-6 = A, the ruling's exact rule):**

   ```text
   distance   = abs(actual - sota)
   band_width = partial_margin * abs(sota)

   if actual is None or sota is None:          # uncomputable (§2.4)
       outcome = unevaluated; information_gain = 0; NOT counted
   elif MetricOrder.is_better(actual, sota):   # strictly better
       outcome = confirmed;   information_gain = distance
   elif distance <= band_width:                # not better, within band (equality included)
       outcome = partial;     information_gain = 0
   else:
       outcome = refuted;     information_gain = 0
   ```

   Properties (all four direction×sign quadrants correct; equality ⇒
   partial; `sota == 0` ⇒ band width 0: exact equality partial, any
   worse value refuted, any better value confirmed). No task/value branch;
   higher/lower is never interpreted outside `MetricOrder`; the absolute
   distance is direction-neutral. The boundary convention `<=` was checked
   against current semantics (`interpretation_helpers.py:285-291`: the old
   partial test is `>=` on the relative bound, i.e. inclusive) — consistent;
   no different convention is required. `boldness` keeps its existing
   scale-naive formula (§19 row; unchanged). Versioned as
   `metric_order_signsafe_v2` (§8). Hand-computed tests (09a): higher/
   positive, higher/negative, lower/positive, lower/negative, equality,
   zero sota, just-inside, just-outside, uncomputable.
   The prediction grammar: bound-metric id (aliases deleted for NEW
   predictions; read-only acceptance when evaluating a PRIOR record that
   carries an alias — R-09-5), plus per-sample forms accepted ONLY when
   per-sample evidence exists.
2. **Evidence projection (deterministic)** — `ModelRunSummary` gains
   `training_diagnosis`, `metric_identity`, `secondary_metrics` (§4b) and
   the authority-derived failure counts (§5) from the record fields; the
   builder's selection maxima/minima move onto `MetricOrder`.
3. **Prompt assembly (framework) from `InterpretationTaskBlocks`
   (task-owned VALUE)** — a NEW `agent/prompt_templates/interpretation/
   rendering.py` owns explicit renderers: metric identity/direction words;
   diagnosis lines (reusing `render_training_dynamics_line`'s vocabulary);
   secondary-metric lines (own identity/direction words, observational
   framing); health counts/fingerprint sections (existing generic renderer
   retained); failure lines from the existing authorities; evidence-table
   section gated on table presence. The TIDMAD science (Log-of-Mean
   pedagogy, Impact_Score reading rules, the "baseline typically 4000"
   volume framing, take-home file_index rules) moves VERBATIM into
   TIDMAD's blocks; the framework prompt keeps only task-free analyst
   protocol. **`InterpretationTaskBlocks`** is a typed, frozen pydantic
   VALUE of declarative prose sections under the FIXED framework key set
   `evidence_reading` / `per_model_guidance` / `synthesis_guidance` /
   `prediction_guidance` (each optional; absent ⇒ section omitted — absence
   of guidance is legal, never an error). It reaches the interpreter as
   `InterpretationInput.task_blocks`, supplied by the CALLER (workflow
   today; the composition root at Step 12); the interpreter never
   discovers task files itself. **Regime-A compatibility (bounded):** ONE
   dedicated TIDMAD-owned declaration file in a production-safe in-repo
   location (exact path fixed in 09b's child design; NOT under `examples/`,
   NOT a new section of the central `task_config.yaml`) is parsed into the
   value by ONE adapter the workflow calls — compatibility plumbing that
   Step 12 replaces, not an extension mechanism; the in-repo location does
   not define how an external package supplies its blocks (it supplies the
   same typed value). No interpreter plugin loader/registry; no task-name
   branch; no `examples/` dependency; **no LLM-skill abstraction** — the
   interpretation job is prompt-borne prose + deterministic arithmetic
   (brief §9); executable task interpretation plugins have no forcing case
   and would preempt Step 10/12 composition.

Renderer/golden discipline = 07b's: every prompt byte-delta is DECLARED,
attributed to an authority, and landed as regenerated goldens in the same
commit; TIDMAD's rendered content stays semantically identical (same
science, now task-owned).

### 13a. Node-local structure / god-file audit (REQUIRED — ruling §6)

**Inventory at the anchor** (`result_interpretation_agent.py`, 2,144
lines; AST spans):

| region | lines | span | responsibility |
|---|---|---|---|
| `PER_MODEL_SYSTEM_PROMPT` / `HEALTH_FEEDBACK_SYSTEM_INSTRUCTIONS` / `SYNTHESIS_SYSTEM_PROMPT` / `DEDUP_SYSTEM_PROMPT` | 56-138 / 161-178 / 386-468 / 739-761 | 83+18+83+23 | prompt constants (TIDMAD science inside) |
| `_build_per_model_prompt` / `_build_synthesis_prompt` / `_build_dedup_prompt` / `_render_health_summary_section` / `_flatten_entry_for_prompt` | 239-379 / 524-732 / 764-782 / 181-236 / 487-510 | 141 / **209** / 19 / 56 / 24 | prompt BUILDING (user-message assembly) |
| evolution-log helpers | 790-849 | 60 | metrics sidecar I/O |
| `ResultInterpretationAgent.run` | 871-1744 | **874** | the god-METHOD: cold-start branch · effective types + descriptions · deterministic pre-computation (~145 lines: best/worst/valid ordering, scientific aggregation, health merge) · LLM Phase 1 (active-set, per-model calls, cache) · Phase 2 synthesis · vocab Phase C (dedup LLM calls, promotion) · E.7 link confirmations · E.4 accuracy · centrifugal metrics · evolution stats · output build + validate · persist · degraded fallback (`except Exception` at `:1665`) |
| `_dedup_promoted` | 1746-1824 | 79 | vocab dedup LLM loop |
| `main` | 1832-1899 | 68 | CLI entry |
| `_required_denoising_score` / `_round_ordering` / `_round_health` / `_collect_health_evidence` / `tuning_output_to_model_run_summary` | 1907-2140 | 9/18/34/30/**135** | evidence projection (records → summary) |

Plus `nodes/interpretation_helpers.py` (1,024 lines: prediction
evaluation, discoveries, vocab promotion/links, active-model policy,
compression) — already a sibling module, but a MIXED one.

**What Step 09 materially grows:** (i) ordering/identity + prediction
semantics (inside `run()`'s pre-computation region, `_compute_metric`,
`evaluate_prediction`, the summary builder, the two memory-policy helpers);
(ii) evidence projection (summary builder: diagnosis, identity,
secondaries, failure counts); (iii) prompt building (all builders + the
constants). Growing these IN PLACE would deepen exactly the mixed
ownership the rule forbids.

**Disposition (frozen):**

* **09a — behavior-preserving node-local extraction FIRST** (its first
  semantic milestone, before any semantic change): the deterministic
  evidence/ordering/projection logic 09a is about to modify moves into
  PRIVATE node-local modules under `nodes/result_interpretation_agent/`
  (the tuner's 07b-C7 precedent: `<node>.py` + `<node>.md` public, private
  modules on an acyclic graph, `tests/unit/nodes/
  test_node_public_boundary.py` rule — private BY OWNERSHIP: the guard
  convention uses plain filenames, not leading underscores; filename
  spelling is not public-API status — 09a child E3). Exact private module names follow
  the 09a source audit, not this parent; the responsibility partition is
  fixed here: **evidence projection** (records → `ModelRunSummary`:
  today's `:1907-2140` + the new diagnosis/identity/secondary/failure
  projections), **ordering/prediction semantics** (the `MetricOrder`
  consumers, the band, the grammar — pulling `evaluate_prediction` /
  `_compute_metric` out of the mixed helpers file into the node's private
  module), and the `run()` deterministic pre-computation region extracted
  behind a typed boundary so `run()` reads as a lifecycle (cold-start →
  project → deterministic pre-compute → Phase 1 → Phase 2 → vocab →
  finalize → persist). Validation: PB-0/PB-7/PB-8 goldens exact, same
  LLMBridge kwargs, import census, public-symbol compatibility (thin
  re-exports from `result_interpretation_agent.py` where the census shows
  external importers — `workflows/model_exploration.py:111`,
  `scripts/pr3_l2_calibration/preflight.py:105`,
  `scripts/pr3_l2_calibration/runner.py:193`, the protocols package
  (`ml_model_tune_to_ml_result_interp.py:26`), and the test suites import
  `tuning_output_to_model_run_summary` and the prompt builders from the
  node module), zero orchestration change. NOT a
  third PR — an early milestone inside 09a.
* **09b** moves prompt BUILDING + constants to
  `agent/prompt_templates/interpretation/rendering.py` (as designed) and
  the TIDMAD science to its declaration; the node retains Phase
  orchestration only.
* **Preserved invariants**: ONE obvious main file
  `result_interpretation_agent.py`; same public node identity
  (`ResultInterpretationAgent`, `run(InterpretationInput) →
  InterpretationOutput`); same CLI/entrypoint (`main()`); same orchestration
  semantics (phase order, degraded-mode contract, persistence path); no
  second public node; no generic utils dumping ground.
* **Intended responsibility boundary after 09a + 09b:** main file =
  lifecycle orchestration + degraded fallback + persistence + CLI; private
  modules = evidence projection · ordering/prediction semantics · vocab/
  memory machinery (existing helpers, re-homed only where 09a touches
  them); `agent/prompt_templates/interpretation/` = rendering protocol;
  task declaration = science. Target is the BOUNDARY, not a line count.
* **§13a.5 Forward discipline (recorded for Steps 10–12):** before EACH
  later generic-framework milestone, inspect any main node/module the step
  will materially grow; if it is a god file or accumulates oversized
  mixed-responsibility functions, improve its node-local private-module
  structure BEFORE adding complexity — preserving one obvious main file,
  the public interface, the CLI/entrypoint and the orchestration role;
  refactor only where the upcoming milestone would otherwise deepen mixed
  ownership, never for aesthetics.

## 14. PR decomposition alternatives

* **A — single PR**: one reviewer must hold deterministic ordering
  semantics AND a full prompt-surface migration AND task-block carrier
  design; Gate-1 evidence would gate deterministic-only changes. Rejected.
* **B — parent + 2 children (RECOMMENDED)**: 09a deterministic evidence &
  ordering (zero prompt bytes); 09b prompt surface + task blocks +
  renderers (all prompt bytes, Gate 1). Clean failure-class split; mirrors
  07a/07b.
* **C — parent + 3 (split memory/prediction machinery out of 09a)**:
  artificial — the prediction sign-band and memory-policy literals are the
  SAME failure class (direction consumers) as the rest of 09a.

## 15. Recommended decomposition: PARENT + 2 CHILD PRs

| PR | semantic owner | deps | key surfaces | prod behavior | LLM-facing | Gate 1 | Gate 2 |
|---|---|---|---|---|---|---|---|
| **09a — interpreter evidence & ordering on the metric handle** | behavior-preserving node-local decomposition of the surfaces it touches (§13a); ONE run `MetricSpec` authority transported + reconciled (§2.11); record/spec consistency (§4a); primary evidence projection + the secondary-metric summary projection rendered present-when-present (§4b; production transport is Step 10's — Q-09-7 = B); ALL interpreter D1 ordering consumers incl. the memory-policy helpers (§7); prediction grammar; versioned sign-safe band (§13 ¶1, §8); additive deterministic digest provenance (§5); three-task deterministic ordering/evidence fixtures | Step 06/07 (landed) | `hyperparam_tuning.py` (additive `metric_spec` ONLY — no secondary carriers in 09a), `records.py` (one writer), `interpretation.py` schemas (additive), `result_interpretation_agent.py` + NEW private node modules, `interpretation_helpers.py`, `model_exploration.py` (input construction + reconciliation + cache-cap semantics), node `.md`; plus — operator ruling Q-09a-1 = A narrow (2026-08-19) — the NARROW interpreter-owned prediction-memory carry/restore through the existing canonical path (`model_exploration.py` loop carry, `core/resume.py` `RestoredState` latest-wins, `run_one_iteration.py` forward; semantic owner interpreter, physical location workflow/resume; generic resume policy untouched) | deterministic only; TIDMAD ordering results identical (higher-is-better); prediction outcomes under v2 semantics | **No prompt-TEMPLATE / prompt-protocol change** (templates + PB-0/PB-7/PB-8 goldens EXACT; same LLMBridge kwargs for a fixed input); **deterministic persisted-memory semantics change where frozen** (v2 band → versioned accuracy fields the PROPOSER renders, §2.13) | NOT required | NOT required |
| **09b — interpretation prompts from `InterpretationTaskBlocks` via explicit renderers** | `InterpretationTaskBlocks` value contract; bounded TIDMAD compatibility declaration + adapter; explicit rendering module; task-free framework prompts; TIDMAD science extraction; diagnosis/primary/secondary/health/failure rendering; B/C L1 rendering fixtures; interpreter structural/extensibility census; Gate 1 | 09a | NEW `agent/prompt_templates/interpretation/rendering.py`, prompt constants/builders (moved), the TIDMAD declaration file + adapter, `InterpretationInput.task_blocks`, goldens (declared deltas), guardrail census | prompt rendering only | **YES** | **REQUIRED** (bounded, §17) | NOT required (no data/training/lifecycle claim — §17) |

Merge order 09a → 09b. Each child gets its own detailed design + frozen
invariants + ledger before implementation (the Step-07/08 child pattern);
per-child obligations in §16. No third PR: the node-local decomposition is
09a's first milestone, not a separate PR.

## 16. Child PR contracts (to be detailed in child designs)

**09a** — goal: every interpreter comparison/band/grammar reads the bound
`MetricOrder`/`MetricSpec`; diagnosis, metric identity and secondaries
reach the summary; the node is structurally cleaner than before.

Milestones (sketch; child design fixes commits): M1 behavior-preserving
node-local extraction (§13a; goldens + kwargs exact, import census,
re-exports) → M2 `HyperparamTuningOutput.metric_spec` (one writer) +
workflow reconciliation + `InterpretationInput.metric_spec` + §4a
consistency (fail-closed) → M3 ordering consumers onto `MetricOrder`
(summary builder maxima/minima, `run()` pre-computation, active-model
selection, recall delta, `_cap_knowledge_cache` comparison) → M4 prediction
grammar + versioned sign-safe band + `unevaluated` + version-partitioned
counters → M5 evidence projection (diagnosis, identity, secondaries
present-when-present — summary projection only, Q-09-7 = B; failure
counts from existing authorities) → M6 three-task
deterministic fixtures (pack `expected/`, L1-labelled) + node `.md`.

Frozen invariants (**differential parity — no "same full digest" claim**):
prompt TEMPLATE bytes EXACT; PB-0/PB-7/PB-8 fixed-input prompt goldens
EXACT; same LLMBridge kwargs for an otherwise identical fixed input; D1
existing field names unchanged; every existing deterministic field NOT
owned by the migration equal to the pre-09a value on the differential
fixture; TIDMAD metric ordering itself (higher-is-better) unchanged;
fail-closed without a spec / on identity mismatch; no new loader; no
orchestration change. ALLOWED/REQUIRED deltas, each declared: additive
metric/diagnosis/secondary/provenance/version fields present with expected
values; prediction-derived fields equal where old and new semantics agree
and differing ONLY on the designed sign-band/uncomputable cases; memory-
policy behavior differing ONLY where the old literal was direction-wrong
(never for TIDMAD). **Reachability stated honestly:** 09a has no
prompt-template change but DOES change deterministic downstream
prompt CONTENT — the versioned accuracy/gain fields the proposer renders
(`ml_model_proposal_agent.py:1147-1160`) and the interpreter's own
"Research Health Metrics" lines (`:717-729`) — on inputs where the
corrected band or the `unevaluated` rule changes an outcome. Gate 1 stays
09b-owned; 09a's prompt-CONTENT delta is deterministic and owned by the
differential fixture.

Validation: unit (hand-computed band matrix — higher/positive,
higher/negative, lower/positive, lower/negative, equality, zero sota,
just-inside, just-outside, uncomputable; alias read-only compatibility;
capability-gated grammar; fail-closed spec absence; identity-mismatch
refusal; reconciliation of multi-output specs; additive schema round-trip;
version-partitioned counters + version-pure accuracy; legacy dict
untouched), mutation on the band + fail-closed + reconciliation paths,
three-task L1 ordering/evidence fixtures (accuracy-higher / mse-lower /
secondaries present-when-present), the node-public-boundary rule, a
direction-literal census over the interpreter surface (planted offender).
Acceptance: zero interpreter `>`/`<`/`max`/`min`/`sort` on golden-metric
values outside `MetricOrder`; goldens byte-identical; the differential
fixture green; every negative test named.

**09b** — goal: the roadmap completion sentence. Frozen invariants:
`InterpretationTaskBlocks` is a typed VALUE with the fixed key set;
TIDMAD content resolves from ONE dedicated TIDMAD-owned declaration via
ONE bounded adapter (no central task-config science, no loader, no
`examples/` dependency); framework prompt task-free (census: no
denoising/PSD/Impact_Score/log-of-mean literals in framework prompt
constants or renderers — the banned-vocabulary suite EXTENDED with
anti-vacuity probes); every golden delta declared + attributed; missing
blocks ⇒ sections omitted (absence of guidance is legal); secondaries and
failures rendered from existing authorities only; B/C L1 rendering
fixtures (scalar-only prompts contain NO per-file section and no
file_index instructions; direction words correct for `mse`; secondaries
rendered in their own directions when supplied). Gate 1 (§17).
Acceptance: 11-A metric-identity rung + 11-B table-indexing rung
(roadmap-named); the production node renders a REAL preserved TIDMAD
iteration through handle+blocks with declared-delta goldens; the §18
census green with planted offenders.

## 17. Validation architecture / evidence economy

* **Unit/deterministic owners**: everything in §16; plus the §18 census.
  No local full suite; ONE canonical exact-final-head PR CI per child
  (stacked-review/single-CI economics decided at implementation per the
  standing rules).
* **Gate 1 (09b only, REQUIRED)** — claim: with the re-owned prompts, a
  REAL LLM produces schema-valid Phase-1/Phase-2 interpretation that (A)
  on a REAL preserved TIDMAD interpretation input still carries and uses
  the task-owned TIDMAD science (Impact_Score-grounded take-home, no prompt
  ownership regression; schema-valid outputs), and (B) on the
  **DAVIS-shaped L1 fixture** (lower-is-better `mse`, scalar-only,
  regression-shaped, with `psnr`/`mae` secondaries supplied) uses the
  correct direction words, does NOT hallucinate per-file levers on
  scalar-only evidence, renders secondaries in their own directions, and
  leaks no denoising/Impact_Score/PSD assumptions. Pets remains REQUIRED
  deterministic L1 rendering evidence (not an LLM call unless the budget
  below admits it without duplication).
  **Call-count projection, source-grounded** (`result_interpretation_agent.py`
  LLM call sites: per-model `:1180` once per RECALLED active model;
  synthesis `:1397` once; dedup `:1797` once per promoted vocab entry
  having existing canonicals): the selected REAL artifact is
  `/home/klz/Data/SIDEREIS_DATA/step07b_gate1_postrefactor/` — two
  models (`wavenet24_fullspectrum_ce_coldstart` cached from the iter-2
  digest; `bidirectional_gated_tcn` as the new summary, 18 records, real
  `training_diagnosis` + `metric_result` on records) ⇒ at most 2
  per-model + 1 synthesis = **3 calls**; the DAVIS fixture, built as ONE
  new model with an empty cache ⇒ 1 + 1 = **2 calls**; dedup 0 (no
  promotions on these inputs — asserted in the spec). **Total 5 calls**
  (Pets, if added, +2 ⇒ 7; not required). One provider config
  (`openai_tiered_pro.json` per the standing Gate rule); PASS/FAIL from
  persisted outputs (schema validity + deterministic content probes:
  direction words present/absent, no `file_index` directive on scalar-only,
  secondaries named with their directions); INCONCLUSIVE on provider
  failure. Spec written into the child ledger before launch.
* **Gate 2 — NOT REQUIRED for either child** (operator-confirmed, Q-09-4):
  no real data/training/inference/subprocess/lifecycle claim changes; the
  interpreter is an in-process LLM node with plain JSON persistence covered
  by unit + Gate 1's real run. No Step-06/07/08 training Gate is rerun.
* Evidence economy: the same failure class is never bought twice —
  template-golden byte-parity + the differential fixture own 09a's risk;
  Gate 1 owns 09b's real-LLM behavior; censuses own structure.

## 18. Extensibility guardrails / structural census plan (09b, C-last)

Executable, each with a planted-offender probe: (1) framework interpreter
prompt constants/renderers contain no TIDMAD science tokens (moved set
enumerated: Log-of-Mean/Impact_Score/Linear_Weight pedagogy, PSD-4000,
denoising-scalar prose) — extending `test_prompt_banned_vocabulary.py`'s
mechanism; (2) direction interpreted only via `MetricOrder` in interpreter
files (the 07b one-module rule extended to the interpreter surface);
(3) no task-name branch in interpreter/renderer code (`tidmad|pets|davis`
tokens; plus no parsing of metric ids / check ids / provider ids for
meaning); (4) task-block section keys = the fixed framework set (growth is
a framework decision); (5) digest consumers unchanged (no code branches on
new fields to steer workflow — reachability pin); (6) the TIDMAD blocks
declaration is read by exactly ONE adapter and the interpreter module
imports no file-discovery of task declarations; (7) secondary metrics
never enter an ordering call (AST: no `secondary_metrics` reference inside
the `MetricOrder`-consuming functions); (8) prediction-evaluation records
carry the version id (schema census). Every item carries an anti-vacuity /
planted-offender proof. The 08c health-core census stays untouched; 09a
adds the direction-literal census (§16) earlier.

## 19. A/B/C debt triage matrix (findings from THIS design audit)

| finding | class | owner |
|---|---|---|
| `evaluation.py` name tables (§12) | **B** | Step 10 |
| ~~workflow-side `metric_spec` derivation (rev 1)~~ — **REMOVED**: route B transports the tuner's single derivation (§2.11); no new site exists | — | — |
| secondary-metric transport absent in production (§2.12) — the roadmap's "render secondary metrics" needs an additive evaluation/persistence carrier upstream of the interpreter | **B — FORWARD CONSTRAINT** (Q-09-7 = B, RESOLVED 2026-08-19, §0.2; open contract; carrier fully typed by Step-06 authorities, §4b) | **Step 10** — when the generic workflow/persistence path first carries task-declared secondaries: declared `MetricSpec`s → binding through the unified task/workflow composition mechanism → Step-06 metric-protocol evaluation → `ExperimentRecord` persistence → tuning/workflow transport → the SAME Step-09 `secondary_metrics` contract (no replacement schema). Step 09 renders present-when-present |
| TIDMAD blocks resolved by a bounded regime-A adapter from an in-repo declaration until the composition root supplies the value (§13 ¶3) | **B** (compatibility plumbing, self-labelled; the contract is the typed value) | Step 12 |
| the tuner's regime-A `derive_tidmad_metric` (debt item 12) — unchanged, now also the ONLY source of the interpreter's spec | **B** (pre-existing, not deepened) | Step 12 |
| `resume.py`/chain-incumbent + dashboard direction literals (§2.3) | **B** (pre-existing, out of scope here) | Step 10 |
| dead tune→interp protocol (`ml_model_tune_to_ml_result_interp`, no production caller) | **C** | post-Step-12 cleanup (or absorbed if Step 10 rewires the edge) |
| interp CLI `main()` ad-hoc entry (`:1832`) + `scripts/pr3_l2_calibration/{preflight,runner}.py` input construction without a spec (R-09-3: supplied explicitly in 09a) | **C** | Step 10/12 (single composition entry) |
| synthesis workspace-string interpolation into prompt (`:638-651`, golden-pinned migration-parity behavior) | **C** (recorded hazard, pinned) | post-Step-12 |
| `boldness` scale-naive arithmetic (§2.3) | **B** (recorded; unchanged in 09a — no consumer requires more) | Step 10+ if ever forced |
| uncomputable predictions counted as `partial` (§2.4, production-observed) | **fixed in 09a** (`unevaluated`, not counted) | 09a |
| prediction-pool production carry/restore ABSENT at the pre-09a anchor (09a child audit E2, 2026-08-19 — the rev-2 premise that `RestoredState` restores it was a factual source error) | **fixed NARROWLY in 09a C5** (operator ruling Q-09a-1 = A: interpreter-owned prediction-memory fields only, through the existing canonical digest → workflow carry → `RestoredState` latest-wins path; generic resume policy, chain-incumbent restoration and every other restored field untouched) | 09a |
| E.7 `vocab_link_confirmations` never carried/restored in production (same audit; vocabulary machinery, not the prediction-memory contract) | **B** (pre-existing workflow-transport gap) | Step 10 |
| *(added at 09b closure, 2026-08-20)* proposer prediction-AUTHORING grammar — new predictions are still not constrained to the bound metric id, and per-sample forms are not capability-gated at authoring time | **B** | Step 10 |
| *(09b closure)* the proposer's OWN task science in `PROPOSAL_REASONING_PROMPT` / `PROPOSAL_COMMIT_PROMPT` — 09b's scope was bounded to the two prediction-track reader surfaces | **B** | Step 10/12 (proposer-side task blocks) |
| *(09b closure)* the TIDMAD interpretation declaration + its bounded adapter (`configs/task_interpretation/tidmad.yaml`, `task_blocks.py`) — self-labelled compatibility PACKAGING; Step 12 replaces the CALL SITE, not the contract | **B** | Step 12 |
| *(09b closure)* production **structural** hotspots recorded by the 09b audit — the proposer node's duplicated legacy/pipeline reader surfaces, `workflows/model_exploration.py`, `ResultInterpretationAgent.run()`, the mixed `nodes/interpretation_helpers.py`, and the merged rendering module — plus test-topology duplication | **B — STRUCTURAL/TEST debt, deliberately separate from the semantic rows above** | **Step 09.5** (repository structural-debt + test-topology AUDIT, sequenced between Step 09 and Step 10; roadmap §15.1). The audit decides whether any repair is a Step-10 prerequisite — it does not pre-commit one |

No A-class findings: nothing here closes a contract Step 09 must build on.

## 20. Risks

* **R-09-1 prompt-regression blast radius** — re-owning prompt science can
  silently change interpretation quality. Mitigation: TIDMAD blocks move
  VERBATIM; declared-delta goldens; Gate 1 on a real preserved digest.
* **R-09-2 direction-flip latency** — a missed `>` literal ships wrong
  ordering for lower-is-better tasks. Mitigation: census (2) with planted
  offender; three-task L1 ordering fixtures.
* **R-09-3 fail-closed ordering breaks legacy ad-hoc callers** (CLI
  `main()`, `scripts/pr3_l2_calibration/{preflight,runner}.py`) that build
  inputs from tuning-output files. Mitigation: they read the SAME
  `HyperparamTuningOutput.metric_spec` the workflow reconciles (outputs
  written after 09a carry it); outputs predating the field ⇒ the refusal
  path (named, tested) — NOT a fresh derivation at those entry points
  (that would be the second site the ruling forbids). Negative test for
  the refusal path.
* **R-09-4 (rev 1: carrier dispute) — RESOLVED** by Q-09-1 ruling (typed
  value + bounded TIDMAD adapter).
* **R-09-5 grammar tightening rejects historical prediction records** —
  older digests carry alias metrics. Mitigation: evaluation of a PRIOR
  prediction accepts the alias set read-only for backward records while
  new predictions are constrained (explicit compatibility note in 09a).
* **R-09-6 secondary-metric scope creep — bounded by Q-09-7 = B (§0.2).**
  09a touches NO tuner-side evaluation, NO record persistence and NO
  workflow transport of secondaries (all Step 10's); 09's rendering is
  present-when-present and the three-task fixtures carry carrier-shaped
  secondaries from the packs' declared specs. Residual risk: a 09a
  implementation "helpfully" adding a secondary evaluator/loader/binding
  path — forbidden (it would create exactly the interim Step-09-specific
  path the ruling rejects); the 09a child design carries the explicit
  prohibition and a census pin.
* **R-09-7 reconciliation false-refusals** — multi-output inputs whose
  specs legitimately differ (a resumed run whose metric binding changed
  between chain segments) would fail closed. Mitigation: one run = one
  metric is the Step-06 invariant (`run_metric` bound once per run); a
  changed binding IS a different run; the refusal names both specs.

## 21. Operator rulings on the rev-1 questions + Q-09-7 (ALL RESOLVED)

All six rev-1 questions are RESOLVED by the 2026-08-19 ruling (§0.1), and
Q-09-7 by the 2026-08-19 final ruling (§0.2):

* **Q-09-1 = B refined** — `InterpretationTaskBlocks` typed VALUE; TIDMAD
  content in ONE dedicated TIDMAD-owned declaration via ONE bounded
  adapter; no central task-config science; no loader. (§13 ¶3, §9)
* **Q-09-2 = route B** — the tuner's single resolved spec rides additively
  on `HyperparamTuningOutput`, reconciled by the workflow; NO second
  derivation. (§2.11, §4)
* **Q-09-3 = 09a owns the semantic migration** of `_cap_knowledge_cache`;
  helper stays in place. (§7)
* **Q-09-4** — 09a: no Gates; 09b: Gate 1 REQUIRED, Gate 2 NOT. (§17)
* **Q-09-5 = pack `expected/`**, L1 synthetic contract-level labelling,
  provenance naming the authorities used, zero production dependency on
  `examples/`. (§10, §16)
* **Q-09-6 = A** — sign-safe direction-correct band, exact rule frozen,
  versioned `metric_order_signsafe_v2`, historical records untouched,
  version-partitioned aggregation. (§13 ¶1, §8)

**Q-09-7 — secondary-metric carrier ownership: RULED B — RESOLVED
(operator, 2026-08-19; full text §0.2).** The audit (§2.12) found NO
secondary evaluation/persistence in production; the carrier shape is
frozen (§4b) and the interpreter contract is identical under both options
that were offered. The operator selected **B**: Step 10 owns the upstream
carrier (declaration binding, additional metric-handle execution,
tuner-side secondary scoring, `ExperimentRecord` persistence, workflow
transport) through the unified task/workflow composition mechanism, and
Step 09 renders present-when-present with the three-task fixtures
carrying carrier-shaped secondaries built from the packs' declared specs
(TIDMAD none; Pets `macro_f1` higher; DAVIS `psnr` higher + `mae` lower).
The roadmap sentence "render secondary metrics" is therefore satisfied at
the interpreter boundary in Step 09 and end-to-end only when Step 10
lands the transport against the SAME Step-09 contract. The rejected
option A (an additive 09a milestone landing tuner-side evaluation +
record carrier + projection together) is recorded here as history only;
09a must NOT introduce a secondary-metric evaluator, loader, task-specific
binding path or new metric derivation site. The freeze was never gated on
this question; 09a's child design opens under B.

## 22. Step-12 forward-compatibility proof

The final out-of-tree package (debt audit §6) carries, for interpretation:
its task config (with `task_description` + interpretation blocks) and its
metric declaration (already `MetricSpec`-constructible from JSON). The
composition root then supplies to the interpreter exactly TWO things this
design already types as inputs: the bound `metric_spec` value and the
task-config-borne blocks. **No Step-09 public contract needs replacement
at Step 12** (§16 anti-debt answer #12 = NO): no interpreter loader exists
to swap, no closed vocabulary must grow (block keys are per-surface, not
per-task; `objective_kind`/metric ids/check names arrive as open strings),
built-ins (TIDMAD blocks) ride the same declaration interface an external
package will use. Temporary compatibility paths, all named: the regime-A
spec derivation (workflow), the central task-config carrier, the alias
read-only path (§20 R-09-5) — each with its Step-10/12 owner in §19.

Fourth-task-with-novel-INTERPRETIVE-COMPUTATION note (adversarial pass J):
a task whose interpretation needs new deterministic computation expresses
it at the layer that owns the computation — metric (result/refusal
fields), Health (checks/views/plugins, extensible since 08), diagnosis
(07a derivation) — all of which the interpreter renders generically;
prose-level novelty is the blocks. Step 09 therefore adds no interpreter
plugin surface for it, and none is left implicit.

### §16-checklist answers (anti-debt, YES/NO with evidence)

1 YES (typed blocks value + declarations; §13). 2 NO (no per-task
enum added — block keys are a fixed framework set; the version id is
framework metadata; failure counts come from existing vocabularies; §9 F
column, §5). 3 NO — no task science is placed in framework-owned central
YAML (Q-09-1 ruling: TIDMAD's blocks live in ONE dedicated TIDMAD-owned
declaration behind a bounded adapter; §13 ¶3). 4 NO (no central
import/registry for interpretation semantics). 5 NO after 09b (census
§18-1; today's violations enumerated in §2.2). 6 NO (verbatim identity
rendering; ordering from direction only; no id parsing — census §18-3).
7 NO loader created (§13). 8 NO duplication (§3 boundary statements; §7;
failure counts derived, never re-diagnosed). 9 NO (single digest owner;
version-partitioned counters are one structure in that digest; §8).
10 YES (§10 table). 11 YES (§22). 12 NO replacement needed (§22).

## 23. Final recommendation / freeze readiness

**STEP 09 IMPLEMENTATION SHAPE: PARENT + 2 CHILD PRs (09a → 09b) — APPROVED
by the operator ruling and FROZEN here.**

Freeze record (ruling §19): all Q-09-1..6 resolved (§21); Q-09-7 was a
scope placement of a frozen contract that did not gate the freeze and is
now RESOLVED = B (§0.2, 2026-08-19);
strong-extensibility verdict **PASS** (§9); A blockers = none (§19); exact
09a/09b ownership (§15/§16); node-local structure disposition (§13a);
exact secondary-metric transport (§4b); exact run MetricSpec authority
(§2.11/§4); prediction semantics + version rule (§13 ¶1, §8); Gate plan
(§17); Step-12 compatibility (§22). Child detailed designs (per-commit
checklists, frozen invariants, ledgers) follow per the established
Step-07/08 kickoff protocol. *(Freeze-time statement, preserved: at the
freeze, implementation had NOT started.)*

**Acceptance record (2026-08-20): STEP-09 ACCEPTANCE CLOSED.** Both child
PRs merged (#238, #239 — §0), each on a green exact-head CI with merged
master verified byte-identical to the validated head; the roadmap's Step-09
obligations are discharged — interpretation renders from the metric handle
+ task blocks, the prediction grammar is metric-parameterized, the sign-band
is fixed, the 11-A/11-B rungs landed, and the production node rendered a
REAL preserved iteration through handle+blocks under Gate 1. No parent
architecture was reopened by either child.

### 23a. Final adversarial consistency pass (ruling §18 — 18 attacks)

1. *TIDMAD science still hardcoded in generic interpreter prompt code?*
   Today YES (§2.2 enumerates it); after 09b NO — census §18-1 with
   planted offenders; the science moves VERBATIM to the TIDMAD declaration.
2. *Did task science merely move into another framework-owned central
   per-task table?* NO — Q-09-1 = B refined: ONE TIDMAD-owned declaration
   read by ONE bounded adapter; the contract is the typed value; no new
   section in `task_config.yaml`.
3. *Two independent run MetricSpec derivations?* NO — route B transports
   the tuner's single derivation (`:541`); census of all
   `derive_tidmad_metric` sites in §2.11 shows Step 09 adds none.
4. *Can a record identity disagree with the bound spec?* Only as a
   fail-closed ERROR before ordering/prediction/rendering (§4a); never a
   silent preference.
5. *Secondaries actually transported or merely named?* Audited: NO
   transport exists today (§2.12); the carrier is TYPED here (§4b);
   ownership RULED — Q-09-7 = B: transport is Step 10's forward
   constraint against this exact carrier, Step 09 renders
   present-when-present (§0.2) — not prose-only.
6. *Could a secondary affect primary ordering?* NO — §4b rule + census
   §18-7 (AST: no `secondary_metrics` reference in `MetricOrder`-consuming
   functions).
7. *Does the interpreter re-derive diagnosis/failure semantics?* NO —
   failure counts are derived ONLY from existing authority vocabularies
   (§5); diagnosis is consumed verbatim (§4).
8. *Prediction semantics versioned?* YES — `prediction_evaluation_semantics`
   (`legacy_v1` absent / `metric_order_signsafe_v2`), §8.
9. *Old/new accuracy records distinguishable?* YES — version-partitioned
   counters; v1 dict untouched; accuracy computed only within v2 and
   labelled (§8).
10. *Does 09a still claim "same full digest"?* NO — differential
    ownership (§16 09a); prompt-CONTENT reachability via the proposer
    stated honestly (§2.13, §16).
11. *Does the node get larger/more mixed?* NO — 09a M1 extracts
    evidence-projection + ordering/prediction into private node modules
    BEFORE semantic change; 09b moves rendering out; boundary stated
    (§13a); one main file preserved.
12. *Science inferred from `tidmad|pets|davis` / metric-id / check-id
    spelling?* NO — census §18-3 (+ the 08c health census stays); identity
    rendered verbatim; ordering from `direction` only.
13. *Any failure enum needing per-task growth?* NO — none introduced (§5).
14. *TIDMAD/Pets/DAVIS fit without identity branches?* YES (§10: direction
    from spec; per-sample sections capability-gated; secondaries
    present-when-present; health counts generic).
15. *Step-12 task supplies `MetricSpec` + `InterpretationTaskBlocks`
    without changing Step-09 contracts?* YES (§22 — the composition root
    supplies typed values; no loader to replace).
16. *Does 09b Gate 1 exercise LOWER-is-better?* YES — the DAVIS-shaped
    fixture (`mse` lower, scalar-only, secondaries) is REQUIRED (§17).
17. *Call-count projection matches the artifacts?* YES — 3 + 2 = 5 calls
    from the three call sites, artifact-grounded (§17).
18. *Every census mutation/anti-vacuity proven?* Planned per item (§18,
    §16) — anti-vacuity probes are acceptance criteria of both children.
