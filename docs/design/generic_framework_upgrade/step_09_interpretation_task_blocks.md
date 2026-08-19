# Step 09 — Interpretation from the metric handle + task blocks (parent design)

## 0. Status and provenance

**DRAFT — REVISION 1. NOT FROZEN. IMPLEMENTATION NOT STARTED.**

Design session 2026-08-19, operator-directed ("STEP 09 DESIGN — generic
result interpretation under the strong external-extensibility invariant").
Produced from source, not from conversational memory.

**Audit anchor: master `bf22827b`** (= origin/master at design time; Step 08
COMPLETE — 08c merged as PR #237 squash `3f4effb5`, post-merge status sync
`bf22827b`; parent §14 A–H closed). Working tree clean at the start of the
audit. Every `file:line` in this document was read at this anchor.

Zero `SOURCE-INSPECTION REQUIRED` markers.

Authority order: roadmap (`siderius_generic_framework_upgrade.md`, §15.1
§11-row + §22) > current source > merged Step-06/07/08 designs/ledgers >
this draft. Where roadmap wording and source differ, the difference is
recorded (§2.10), never silently resolved.

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
`information_gain`. Frozen-semantics question → **Q-09-6**.

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
   interpreter memory/policy, wherever hosted) and records the alternative
   (leave `_cap_knowledge_cache` to Step 10) as operator question Q-09-3.
3. Roadmap V8 row (:1377) lists "dashboard" among remaining direction
   literals — not mentioned in the §11 row; allocated OUT of Step 09 here
   (Step 10+ surface; no interpreter dependency).

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
| `InterpretationInput.metric_spec` (NEW, serialized `MetricSpec` dump or `None`) | workflow-supplied, same regime-A derivation the tuner uses (`derive_tidmad_metric`, `evaluation_metric.py:712`; tuner precedent `ml_hyperparameter_tune_agent.py:541`); Step 12 later supplies it from the composition root | ONE run-scoped ordering + identity authority for every interpreter comparison and rendered line (the 07b `plan(task_render, metric_spec)` pattern) | reference/declaration |
| `ModelRunSummary.training_diagnosis` (NEW, `TrainingDiagnosis \| None`, from the record the summary's best/formal facts came from — one per role as designed in the child) | `ExperimentRecord.training_diagnosis` (`hyperparam_tuning.py:403`) | Rev-5 mandate: agent-facing rendering of diagnosis | verbatim persisted evidence |
| `ModelRunSummary.metric_identity` (NEW: `{metric_id, direction}` from the formal/best record's `metric_result`; refusal summary from `metric_refusal`) | record `:659,674` | evidence-borne identity for consistency rendering + failure classification ("not_scoreable" rounds are failures the interpreter currently cannot name) | normalized evidence |
| existing `summaries` fields (scores, tables, RoundHealth, ordering, conclusions, timing, volumes) | §2.5 | unchanged | projection |
| existing carry-forward memory (cache, vocab, fingerprints, prediction history) | §2.8 | unchanged | memory |
| `task_description` | 04b accessor (unchanged) | prompt context | declaration |
| task interpretation blocks (NEW; see §8/§13) | task-owned declaration | task science in prompts | declaration |

NOT included (considered and refused): raw `all_records` (the summary
projection is the deliberate token boundary — §2.1); `PerSampleEvidence`
enum from HealthCheckContext (a tuner-context statement; the interpreter's
per-sample presence signal is table/vector presence + `metric_result.
per_sample` via `metric_identity`); tuner decision internals
(`resolved_action` etc. — tuner-owned, adjacent debt, not evidence the
interpreter may reinterpret); Health CHECK thresholds beyond what
`PersistedHealthGateResult` already carries (§2.6).

## 5. Exact Step-09 output contract

`InterpretationOutput` keeps its shape; additions are additive:

* **Deterministic metadata (framework-owned)**: existing fields; plus NEW
  `metric_identity` echo (`{metric_id, direction}` actually used for
  ordering this iteration — provenance for the digest reader) and NEW
  per-model failure-classification counts derived from RoundHealth
  provenance + `metric_refusal` (deterministic, never LLM-authored).
* **LLM-authored (clearly bounded)**: key_findings, bottlenecks,
  take_home_message, per-model narrative fields, discovery sentences —
  unchanged in kind; regenerated under direction-correct instructions.
* **Prediction evaluation**: same record shape; outcome computed via
  `MetricOrder` (§6 sign-band fix); `metric` defaults to the bound
  metric id, not the literal `"denoising_score"`.
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

## 9. Strong extensibility audit matrix (A–F per new/modified surface)

| surface | A semantic contract | B binding | C discovery | D config ownership | E registration | F vocabulary |
|---|---|---|---|---|---|---|
| interpreter ordering/identity | OPEN — any `MetricSpec` (direction Literal higher/lower is universal per debt item 13) | `InterpretationInput.metric_spec` VALUE supplied by caller | n/a (value, not code) | caller-owned; regime-A workflow derivation today (same B-class seam as tuner, debt item 12) | none | none new |
| prediction grammar | OPEN — bound metric id + capability-gated per-sample forms | from `metric_spec` + evidence presence | n/a | n/a | none | alias set DELETED, not grown; forms keyed on evidence capability, not task |
| task interpretation blocks | OPEN — declarative prose sections any task can author | task config carrier (Q-09-1): loaded via the 04b accessor pattern | with Step 12 run-scoped task-config binding (missing composition root, class B — NOT a closed contract) | task-owned section (TIDMAD's content moves OUT of node constants) | none | section keys are a FRAMEWORK protocol vocabulary (fixed, small, per-surface not per-task) |
| explicit renderers (interp prompt-templates module) | framework-owned protocol; renders ONLY from authorities (MetricOrder words, diagnosis, health counts, blocks) | function args | n/a | n/a | none | none |
| additive summary/digest fields | typed, task-free (`TrainingDiagnosis`, `{metric_id, direction}`, counts) | record-borne | n/a | n/a | none | none |

Fixed questions: unknown/missing semantics fail closed — a summaries-with-
scores input WITHOUT `metric_spec` refuses ordering (no silent
higher-is-better default; cold-start/no-score paths need no order); no ID
spelling inspected (identity rendered verbatim, ordering from `direction`
only); a fourth task needs NO SIDERIUS source commit for interpretation
semantics ONCE Step 10/12 binds task config run-scoped — today it inherits
exactly the existing B-class task-config seam (debt items 1/12), which
Step 09 must not deepen and does not; Step 10/12 can supply the missing
binding without changing any contract here (values + declarations only —
no interpreter-specific loader exists to replace, by design per brief §3).

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
* **Item 12 (B) — tuner regime-A `derive_tidmad_metric` (`:541`)**: Step 09
  adds ONE analogous workflow-side derivation call to feed
  `InterpretationInput.metric_spec` — same seam, same B class, same Step-12
  owner; recorded as a KNOWN regime-A site, self-flagged in source like the
  tuner's. (Alternative — threading the tuner's spec through
  `HyperparamTuningOutput` — rejected: the digest may cover models tuned in
  prior processes; the run authority is the workflow's, and output schema
  growth for transport duplicates the same value N times.)
* **Items 1/2 (B) — task-config central YAML + ambient TIDMAD fallback**:
  the interpreter already consumes `task_description` via the 04b accessor;
  task blocks ride the SAME carrier and accessor pattern (Q-09-1), so Step
  12's run-scoped task-config binding lifts both at once. Not deepened.
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
   metric_spec`; fail-closed when scores exist but no spec does; identity
   lines rendered via the 07b renderer idiom (`render_metric_identity_line`
   pattern), never from field-name prose. The sign-band becomes
   direction-correct AND sign-safe banding (confirmed =
   `order.is_better(actual, sota)`; partial = worse than sota by at most
   `partial_margin * |sota|` measured as a worse-direction distance —
   well-defined for negative values and for `lower` metrics;
   information_gain = |improvement| when confirmed). Exact band semantics
   frozen at Q-09-6's ruling (§2.4 degeneracy finding).
   The prediction grammar: bound-metric id (aliases deleted), plus
   per-sample forms accepted ONLY when per-sample evidence exists.
2. **Evidence projection (deterministic)** — `ModelRunSummary` gains
   `training_diagnosis` + `metric_identity` (+ refusal/failure counts)
   from the record fields (§4); the builder's selection maxima/minima move
   onto `MetricOrder`.
3. **Prompt assembly (framework) from task blocks (task-owned)** — a NEW
   `agent/prompt_templates/interpretation/rendering.py` owns explicit
   renderers: metric identity/direction words; diagnosis lines (reusing
   `render_training_dynamics_line`'s vocabulary); health counts/fingerprint
   sections (existing generic renderer retained); failure-classification
   lines; evidence-table section gated on table presence. The TIDMAD
   science (Log-of-Mean pedagogy, Impact_Score reading rules, the
   "baseline typically 4000" volume framing, take-home file_index rules)
   moves VERBATIM into TIDMAD's task interpretation blocks; the framework
   prompt keeps only task-free analyst protocol. Task blocks are
   DECLARATIVE PROSE sections under a small fixed framework key set
   (e.g. `evidence_reading` / `per_model_guidance` / `synthesis_guidance` /
   `prediction_guidance`), carried per Q-09-1 and loaded through the 04b
   accessor pattern. **No interpreter plugin loader; no LLM-skill
   abstraction** — the interpretation job here is prompt-borne prose +
   deterministic arithmetic (brief §9); executable task interpretation
   plugins have no forcing case and would preempt Step 10/12 composition.

Renderer/golden discipline = 07b's: every prompt byte-delta is DECLARED,
attributed to an authority, and landed as regenerated goldens in the same
commit; TIDMAD's rendered content stays semantically identical (same
science, now task-owned).

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
| **09a — interpreter evidence & ordering on the metric handle** | D1 interpreter direction consumers; prediction grammar + sign-band; additive summary/digest fields; `metric_spec` threading | Step 06/07 (landed) | `interpretation.py` schemas (additive), `result_interpretation_agent.py` non-prompt code, `interpretation_helpers.py`, `model_exploration.py` (input construction + cache-cap policy), node `.md` | deterministic only; TIDMAD ordering results identical (higher-is-better preserved) | **NO — prompt bytes EXACT (goldens unchanged)** | NOT required | NOT required |
| **09b — interpretation prompts from task blocks via explicit renderers** | prompt assembly protocol; task-block contract + TIDMAD block extraction; diagnosis/metric/health/failure rendering; B/C L1 fixtures; census | 09a | NEW `agent/prompt_templates/interpretation/`, prompt constants/builders, task-config interpretation section + accessor, goldens (declared deltas), guardrail census | prompt rendering only | **YES** | **REQUIRED** (bounded) | NOT required (no data/training/lifecycle claim — §17) |

Merge order 09a → 09b. Each child gets its own detailed design + frozen
invariants + ledger before implementation (the Step-07/08 child pattern);
per-child obligations sketched in §16.

## 16. Child PR contracts (to be detailed in child designs)

**09a** — goal: every interpreter comparison/band/grammar reads the bound
`MetricOrder`/`MetricSpec`; diagnosis + metric identity reach the summary.
Frozen invariants: prompt bytes EXACT (PB-0/PB-7/PB-8 + parity suites
byte-identical; same kwargs reach LLMBridge); D1 field names unchanged;
TIDMAD behavior identical (differential fixture: same digest for a
recorded TIDMAD iteration input); fail-closed ordering without a spec;
no new loader. Validation: unit (hand-computed lower-direction banding;
alias-deletion negatives; capability-gated grammar; fail-closed; additive
schema round-trip), mutation on the banding + fail-closed path, three-task
L1 ordering fixtures (accuracy-higher / mse-lower). Acceptance: zero
interpreter `>`/`<`/`max`/`min` on golden-metric values outside
`MetricOrder` (census with planted offender); goldens byte-identical.

**09b** — goal: the roadmap completion sentence. Frozen invariants: task
blocks declarative; framework prompt task-free (census: no
denoising/PSD/Impact_Score/log-of-mean literals in framework prompt
constants — the banned-vocabulary suite EXTENDED, anti-vacuity probes);
every golden delta declared + attributed; block-section keys fixed
framework vocabulary; missing task blocks = sections omitted (fail-quiet
prose, fail-closed nothing — absence of guidance is legal); B/C L1
rendering fixtures (scalar-only prompts contain NO per-file section, no
file_index instructions; direction words correct for mse). Gate 1 (§17).
Acceptance: 11-A metric-identity rung + 11-B table-indexing rung
(roadmap-named); production node renders a REAL preserved TIDMAD iteration
digest through handle+blocks with declared-delta goldens.

## 17. Validation architecture / evidence economy

* **Unit/deterministic owners**: everything in §16; plus the §18 census.
  No local full suite; ONE canonical exact-final-head PR CI per child
  (stacked-review/single-CI economics decided at implementation per the
  standing rules).
* **Gate 1 (09b only, REQUIRED)** — claim: with the re-owned prompts, a
  REAL LLM produces schema-valid Phase-1/Phase-2 interpretation for (i) a
  REAL preserved TIDMAD iteration digest (production evidence in → real
  synthesis out; satisfies the roadmap "renders a real iteration" at the
  interpretation node's own boundary) and (ii) the Pets-shaped L1 fixture
  (scalar-only, collapse-heavy) — the structured output validates, cites
  the correct direction words, and does not hallucinate per-file levers on
  scalar-only evidence. Bounded: ≤ ~6 LLM calls, one provider config,
  PASS/FAIL from persisted outputs (schema validity + deterministic
  content probes), INCONCLUSIVE on provider failure. Spec written into the
  child ledger before launch.
* **Gate 2 — NOT REQUIRED for either child**: no real
  data/training/inference/subprocess/lifecycle claim changes (the
  interpreter is an in-process LLM node; its persistence is plain JSON
  writes covered by unit + Gate 1's real run). Rerunning TIDMAD/Pets/DAVIS
  training Gates would duplicate Step-06/07/08 authorities (brief §14).
  Operator confirmation requested (Q-09-4).
* Evidence economy: the same failure class is never bought twice — golden
  byte-parity owns 09a's LLM-facing risk (proving there is none); Gate 1
  owns 09b's; censuses own structure.

## 18. Extensibility guardrails / structural census plan (09b, C-last)

Executable, each with a planted-offender probe: (1) framework interpreter
prompt constants/renderers contain no TIDMAD science tokens (moved set
enumerated: Log-of-Mean/Impact_Score/Linear_Weight pedagogy, PSD-4000,
denoising-scalar prose) — extending `test_prompt_banned_vocabulary.py`'s
mechanism; (2) direction interpreted only via `MetricOrder` in interpreter
files (the 07b one-module rule extended to the interpreter surface);
(3) no task-name branch in interpreter/renderer code; (4) task-block
section keys = the fixed framework set (growth is a framework decision);
(5) digest consumers unchanged (no code branches on new fields to steer
workflow — reachability pin). The 08c health-core census stays untouched.

## 19. A/B/C debt triage matrix (findings from THIS design audit)

| finding | class | owner |
|---|---|---|
| `evaluation.py` name tables (§12) | **B** | Step 10 |
| workflow-side `metric_spec` derivation = one more regime-A site (§11) | **B** (created knowingly, self-flagged, same seam as debt item 12) | Step 12 |
| task-block carrier rides central `task_config.yaml` until run-scoped binding (§9 D) | **B** (existing items 1/2, not deepened) | Step 12 |
| `resume.py`/chain-incumbent + dashboard direction literals (§2.3) | **B** (pre-existing, out of scope here) | Step 10 |
| dead tune→interp protocol (`ml_model_tune_to_ml_result_interp`, no production caller) | **C** | post-Step-12 cleanup (or absorbed if Step 10 rewires the edge) |
| interp CLI `main()` ad-hoc entry (`:1832`) with its own input construction | **C** | Step 10/12 (single composition entry) |
| synthesis workspace-string interpolation into prompt (`:638-651`, golden-pinned migration-parity behavior) | **C** (recorded hazard, pinned) | post-Step-12 |
| `boldness` scale-naive arithmetic (§2.3) | **B** (recorded; direction fix only in 09a — scale semantics unchanged, no consumer requires more) | Step 10+ if ever forced |

No A-class findings: nothing here closes a contract Step 09 must build on.

## 20. Risks

* **R-09-1 prompt-regression blast radius** — re-owning prompt science can
  silently change interpretation quality. Mitigation: TIDMAD blocks move
  VERBATIM; declared-delta goldens; Gate 1 on a real preserved digest.
* **R-09-2 direction-flip latency** — a missed `>` literal ships wrong
  ordering for lower-is-better tasks. Mitigation: census (2) with planted
  offender; three-task L1 ordering fixtures.
* **R-09-3 fail-closed ordering breaks legacy ad-hoc callers** (CLI
  `main()`, preflight scripts) that build inputs without a spec.
  Mitigation: audit both call sites in 09a; supply the regime-A derivation
  there explicitly; negative test for the refusal path.
* **R-09-4 task-block carrier dispute** — Q-09-1; both options keep the
  contract open; freeze decides only the carrier.
* **R-09-5 grammar tightening rejects historical prediction records** —
  older digests carry alias metrics. Mitigation: evaluation of a PRIOR
  prediction accepts the alias set read-only for backward records while
  new predictions are constrained (explicit compatibility note in 09a).

## 21. Open questions requiring operator ruling

* **Q-09-1 — task-block carrier**: (A, recommended) an optional
  `interpretation:` section in `configs/task_config.yaml`, loaded via the
  established 04b accessor pattern — one task-declaration carrier, lifted
  wholesale by Step 12's run-scoped binding; (B) a separate task-owned
  file (`task_health.yaml` precedent) referenced from task config. A
  recommended because blocks are prose declarations (like
  `task_description`), not structured rosters/plugins.
* **Q-09-2 — `metric_spec` source**: (A, recommended) workflow-supplied
  input value (regime-A derivation, Step-12-replaceable); (B) record-borne
  only (from `metric_result`) — rejected in draft because refused/failed
  iterations carry no result yet still need ordering words, but the
  operator may prefer evidence-borne-first with input fallback.
* **Q-09-3 — `_cap_knowledge_cache` allocation**: migrate in 09a as
  interpreter-memory policy (recommended) vs leave to Step 10 as workflow
  code (§2.10 item 2).
* **Q-09-4 — Gate disposition confirmation**: Gate 1 required for 09b
  only; Gate 2 not required for either child (§17).
* **Q-09-5 — three-task L1 fixture placement**: extend the existing pack
  `expected/` corpora (07a precedent) vs test-local fixtures (recommended:
  pack `expected/` for the digest/summary fixtures, so B/C evidence stays
  cumulative in the packs).
* **Q-09-6 — prediction-band semantics under the fix (§2.4 finding)**: the
  current relative band is empty for negative sota, so TIDMAD has never
  produced "partial" outcomes in that regime; the corrected sign-safe band
  makes them reachable, shifting future
  `prediction_outcomes_history` / `scientific_accuracy` /
  `information_gain` statistics. Options: (A, recommended) accept the
  corrected band as the fixed semantics (historical counts untouched;
  change documented in the digest via the §5 `metric_identity` provenance);
  (B) preserve the degenerate two-outcome behavior for TIDMAD and apply
  the corrected band only where sota > 0 — rejected in draft as a value
  branch, but listed because it is the strict-parity option.

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

1 YES (blocks + declarations; §13). 2 NO (no per-task enum added; §9 F
column). 3 NO NEW placement — the carrier is the existing single-task
authority, already B-classed (items 1/12); nothing new is framework-owned
per-task. 4 NO (no central import/registry for interpretation semantics).
5 NO after 09b (census §18-1; today's violations enumerated in §2.2).
6 NO (verbatim identity rendering; ordering from direction only). 7 NO
loader created (§13). 8 NO duplication (§3 boundary statements; §7).
9 NO (single digest owner; §8). 10 YES (§10 table). 11 YES (§22). 12 NO
replacement needed (§22).

## 23. Final recommendation / freeze readiness

**STEP 09 IMPLEMENTATION SHAPE: PARENT + 2 CHILD PRs (09a → 09b).**

This parent is ready for operator review of: the ownership map, the I/O
contract, the decomposition, the Gate plan, the six open questions. It is
NOT frozen; child detailed designs (with per-commit checklists, frozen
invariants, ledgers) follow the operator's rulings, per the established
Step-07/08 kickoff protocol. Implementation has NOT started.
