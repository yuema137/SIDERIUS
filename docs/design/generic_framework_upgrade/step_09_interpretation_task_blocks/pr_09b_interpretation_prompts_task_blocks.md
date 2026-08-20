# PR 09b — interpretation prompts from `InterpretationTaskBlocks` via explicit renderers (child design)

## 0. Status and provenance

**REVISION 2 — FROZEN (operator final ruling 2026-08-19: "APPROVED WITH
FOUR MINOR FINAL AMENDMENTS" — freeze authority granted in the ruling and
exercised after the four amendments were applied and the §21a adversarial
pass closed without a new material contradiction). The SEMANTIC design is
frozen and is not reopened by implementation. Implementation has NOT
started; every checkbox in §11 is `[ ]` and the §22 ledger is empty.**

*(Rev 1, DRAFT, was committed at `68cad53c` and reviewed by the operator
the same day; the C1→C6 decomposition and the overall architecture were
APPROVED, Q-09b-1..3 were all ruled YES, and four bounded amendments were
mandated — §0.4. No 09c; the Step-09 parent is not redesigned.)*

Child of the FROZEN Step-09 parent
(`docs/design/generic_framework_upgrade/step_09_interpretation_task_blocks.md`,
REVISION 2 — FROZEN at `432cb51a`; Q-09-7 = B at `205a4170`; post-09a factual
errata §0.3 applied at `a325f33b`). Sibling 09a is COMPLETE / MERGED
(PR #238, squash `4cf38dec`; final PR head `9d85f67b`, exact-head CI
32313798097 SUCCESS).

Authority order: frozen parent (incl. §0.2/§0.3) > current merged source
(§2) > merged Step-06/07/08/09a designs and ledgers > roadmap §11 / §22 >
this design. Where the parent's prose and the merged source differ, the
difference is recorded in §0.3 and the SOURCE governs the commit plan; the
parent's frozen architecture and acceptance are not reopened.

**Audit anchor: master `fd5557ee5c7ac0243371a10a4decaf2178332e2d`**
(== `origin/master` after fetch; working tree clean; the post-merge 09a
status-sync commit). Every `file:line` below was read at this anchor. Line
numbers from the pre-09a era are NOT trusted anywhere in this document —
the 09a refactor moved the interpreter surface. **Zero
`SOURCE-INSPECTION REQUIRED` markers.**

### 0.1 What this PR is, in one paragraph

Today the interpreter's two system prompts hardcode TIDMAD science in
framework-owned constants (the Log-of-Mean pedagogy twice, the
`Impact_Score`/`Linear_Weight` reading discipline, per-file take-home rules,
the "baseline typically uses 4000" volume anchor), while the evidence 09a
projected into the summaries and digest — metric identity/direction, the 07a
training diagnosis, present-when-present secondaries, authority-derived
failure counts, the version-partitioned prediction pools — reaches NO prompt
at all, and the proposer's "Prediction Track Record" renders v2 fractions
over a v1 denominator. 09b (i) moves the prompt constants and builders
behaviour-preservingly into a framework-owned rendering module, (ii)
introduces the typed `InterpretationTaskBlocks` VALUE (fixed key set
`evidence_reading` / `per_model_guidance` / `synthesis_guidance` /
`prediction_guidance`), resolves TIDMAD's blocks from ONE dedicated
TIDMAD-owned declaration via ONE bounded adapter, and migrates the TIDMAD
science VERBATIM into that declaration so the framework prompt keeps only
task-free analyst protocol, (iii) adds explicit deterministic renderers —
one authority per evidence family — for metric identity, training
diagnosis, secondaries, failure counts and the version-aware prediction
track record (fixing the interpreter's own stale "Research Health Metrics"
line and the proposer's two stale reader sites), (iv) proves the rendering
contract on TIDMAD / Pets / DAVIS L1 fixtures plus the roadmap's 11-A /
11-B one-axis rungs, and (v) closes with the REQUIRED bounded Gate 1 — a
real preserved TIDMAD interpretation and a DAVIS-shaped lower-is-better
scalar-only case, **5 real LLM calls** (§13, re-derived from merged source;
the parent's freeze-time projection is corrected in §0.3-D2).

### 0.2 The boundary this PR must not cross

Per the parent §15/§16 (09b row) and the standing rules: 09b owns
prompt/rendering/LLM-facing interpretation presentation only. It does NOT
own: deterministic ordering/prediction/projection semantics (09a — frozen,
landed, not reopened); metric arithmetic (06); tuner policy, incumbent
selection, planner/reflector prompts, `memory.conclusion` (07b); Health
verdicts/evaluation (08); **secondary-metric declaration binding, secondary
evaluation/execution, `ExperimentRecord` secondary persistence, workflow
secondary transport (Step 10 — Q-09-7 = B stays binding)**; the proposer's
prediction-AUTHORING grammar (Step 10, §19); `evaluation.py` name tables
(Step 10); `core/resume.py:436` / chain-incumbent / dashboard direction
literals (Step 10+); generic task composition (Step 12); the repo-wide
structural-debt + test-topology audit (post-09b / pre-Step-10 — recorded
inputs in §19.3, never performed here). 09b adds ZERO task-name branches,
ZERO per-task central registries, ZERO per-task enum/list growth, ZERO
subsystem-specific plugin loader, ZERO framework inference from task-id /
metric-id / check-id spelling, and ZERO new `derive_tidmad_metric*`
production sites. Renderers receive typed authoritative evidence and never
recompute metric scores, Health verdicts, `TrainingDiagnosis`, tuner
ordering or workflow policy.

### 0.3 Parent/roadmap wording vs merged source — differences recorded by this audit (architecture unchanged)

| id | parent/roadmap text | merged source at `fd5557ee` | consequence for 09b |
|---|---|---|---|
| **D1** | roadmap `:1230-1231` "prompts split framework/module/task blocks (**golden-equal for TIDMAD**…)"; roadmap `:1540` "3 existing interpreter goldens + new ones EXACT-equal"; §22.12 `:3310` "3 interpreter goldens EXACT-equal + owned additions" | the frozen parent (which OUTRANKS the roadmap in this child's authority order, as in 09a) deliberately weakened this: parent §13 "every prompt byte-delta is DECLARED, attributed to an authority, and landed as regenerated goldens in the same commit; TIDMAD's rendered content stays **semantically identical**"; parent §16 09b "every golden delta declared + attributed" | C1 (the physical move) is BYTE-EXACT — the roadmap's golden-equal claim holds there; C2–C4 (re-owning + owned additions) regenerate goldens with every delta DECLARED and attributed, per the parent. **CONFIRMED — Q-09b-3 = YES (§0.4)** |
| **D2** | parent §17 Gate-1 call projection: "at most 2 per-model + 1 synthesis = **3 calls**" for the preserved TIDMAD artifact; "the DAVIS fixture, built as ONE new model with an empty cache ⇒ 1 + 1 = **2 calls**" | THREE source facts contradict it: (a) `run()` SKIPS Phase-2 synthesis entirely when `len(effective_types) == 1` (`result_interpretation_agent.py:1408-1419`) — a single-model DAVIS input would never render the synthesis prompt at all; (b) `should_recall_per_model` returns `False` for a cache-hit model with no current summary (`nodes/interpretation_helpers.py:905-906`), so the artifact's cached `wavenet24…` model is a Stability-Filter SKIP (marker, no call), never a second per-model call; (c) consolidator `cache_consolidator.list_merge` calls (fired on active cache hits, `result_interpretation_agent.py:1323-1330`) were not counted — they are 0 for the chosen inputs but the projection method must count them | §13 re-derives the exact counts from merged source: TIDMAD = 2 calls (1 per-model + 1 synthesis; wavenet24 = skip marker), DAVIS = 3 calls (TWO fixture models so synthesis fires: 2 per-model + 1 synthesis), dedup = 0 (input-deterministic, §2.3). Total **5** — numerically equal to the parent's total by coincidence, composition corrected |
| **D3** | parent §15 09b surface list does not name the proposer | the operator-approved 09a closeout assigns the debt to 09b: CLAUDE.md Current State ("the proposer's 'Prediction Track Record' rendering, which pairs v2 FRACTIONS with the v1 DENOMINATOR — the consequence Q-09a-3 explicitly declares and freezes, **owned by 09b's rendering surface**") and the 09a ledger §10.5 ("the proposer's rendering surface is 09b's… Carried forward as a named 09b item"). The earlier parent §20 R-09a-5 note said "09b/Step-10" | C4 includes the proposer's TWO reader sites (legacy renderer `:1146-1165` + pipeline whitelist `:1667-1688`), bounded to the track-record family only. **CONFIRMED — Q-09b-1 = YES (§0.4)** |

None of these reopens the parent's frozen architecture; D2 is a factual
source correction of an evidence-plan number, exactly the class the parent
§0.3 mechanism exists for.

### 0.4 Operator final ruling (2026-08-19) — questions RESOLVED, four amendments applied

| item | ruling | landed at |
|---|---|---|
| **Q-09b-1** | **YES** — C4 owns exactly the proposer's legacy track-record rendering section and the production pipeline interpretation-summary whitelist, and NOTHING else in proposer semantics (prediction-authoring grammar, `PROPOSAL_REASONING_PROMPT`/`PROPOSAL_COMMIT_PROMPT` task science, proposer policy all remain later debt) | §11.4, §19.2 |
| **Q-09b-2** | **YES** — the Gate harness stamps the authoritative TIDMAD `MetricSpec` as TEST-FIXTURE CONSTRUCTION (the Q-09a-7 precedent): production outputs unmodified, no production derivation site added, record-borne identity/direction must still agree with the stamped spec, disagreement still fails closed; no GPU re-production of the artifact | §13.2 |
| **Q-09b-3** | **YES** — the frozen parent governs: C1 byte-exact; C2–C4 prompt bytes change ONLY through declared, attributed semantic migrations/additions, each golden regenerated in the owning commit with its exact rule + before/after delta; an UNDECLARED delta remains a STOP; full prompt byte identity is not claimed after C1 | §0.3-D1, §11 |
| amendment 1 (ruling §2) | the illustrative TIDMAD check-id example in `HEALTH_FEEDBACK_SYSTEM_INSTRUCTIONS` is REMOVED NOW — replaced in C2 with a framework-generic example (existing 08c generic-check vocabulary), a declared C2 golden delta; after 09b NO known task-specific check-id literal remains in the generic interpretation prompt templates | §2.2, §5.4, §11.2, §16, §19.2 |
| amendment 2 (ruling §3) | the census-#3 / bounded-adapter contradiction is FIXED: generic surfaces carry zero task identity; the ONE allowed task-token occurrence is the self-labelled default-path constant in `task_blocks.py`, proven CONFINED by a new executable AST guard (no branch/dispatch/parsing/inference; a second task constant/table/branch turns it RED) | §15, §16 (items 3/3b) |
| amendment 3 (ruling §4) | Gate 1 gains hard OUTPUT-SIDE behavioural probes for both cases (P-A1/P-A2/P-B1/P-B2, §13.4), the DAVIS fixture is strictly dominance-ordered, the probes are rehearsed against planted inverted/correct outputs before launch, and §13.1's claim is aligned to exactly what the probes measure — the one sub-claim the frozen artifact cannot support (table-pedagogy USE on a real table: the artifact carries NO score table, §2.8) is weakened honestly and its correctness class is owned deterministically (three-task fixtures + rung 11-B) | §13 |
| amendment 4 (ruling §6) | per-commit execution tightened: broad interpreter-owner sweeps run exactly TWICE locally (C1 structural move; C5 consolidated closure); C2–C4 run new owning tests + narrow legacy golden/compatibility slices; C6 runs only narrow post-Gate changed-surface checks; repository-wide regression is owned by the ONE exact-final-head PR CI; the inverted `test_impact_aware_framing_present` cells are REPLACED (superseded), not retained | §11.1-§11.6, §17 |
| rendering-module structure (ruling §7) | NO 09c, NO pre-emptive split of `rendering.py`; coherent single responsibility > LOC; the ledger records the final responsibility inventory + LOC; clearly MIXED ownership emerging at implementation ⇒ STOP and disposition | §7 |

## 1. Mandate (frozen parent §15 / §16 09b — quoted obligations)

* **Semantic owner (parent §15)**: "`InterpretationTaskBlocks` value
  contract; bounded TIDMAD compatibility declaration + adapter; explicit
  rendering module; task-free framework prompts; TIDMAD science extraction;
  diagnosis/primary/secondary/health/failure rendering; B/C L1 rendering
  fixtures; interpreter structural/extensibility census; Gate 1."
* **Key surfaces (parent §15)**: "NEW
  `agent/prompt_templates/interpretation/rendering.py`, prompt
  constants/builders (moved), the TIDMAD declaration file + adapter,
  `InterpretationInput.task_blocks`, goldens (declared deltas), guardrail
  census." Plus, by the 09a closeout assignment (§0.3-D3), the proposer's
  prediction-track-record reader sites.
* **Frozen invariants (parent §16 09b)**: `InterpretationTaskBlocks` is a
  typed VALUE with the fixed key set; TIDMAD content resolves from ONE
  dedicated TIDMAD-owned declaration via ONE bounded adapter (no central
  task-config science, no loader, no `examples/` dependency); framework
  prompt task-free (census with anti-vacuity probes, extending
  `test_prompt_banned_vocabulary.py`'s mechanism); every golden delta
  declared + attributed; missing blocks ⇒ sections omitted (absence of
  guidance is legal); secondaries and failures rendered from existing
  authorities only; B/C L1 rendering fixtures (scalar-only prompts contain
  NO per-file section and no `file_index` instructions; direction words
  correct for `mse`; secondaries rendered in their own directions when
  supplied).
* **Acceptance (parent §16 09b)**: the 11-A metric-identity rung and the
  11-B table-indexing rung (roadmap `:1233-1235`); "the production node
  renders a REAL preserved TIDMAD iteration through handle+blocks with
  declared-delta goldens; the §18 census green with planted offenders."
* **Node-local structure (parent §13a)**: "09b moves prompt BUILDING +
  constants to `agent/prompt_templates/interpretation/rendering.py` (as
  designed) and the TIDMAD science to its declaration; the node retains
  Phase orchestration only." One obvious main file preserved; no second
  public node; no utils dumping ground.
* **Gates (parent §17, Q-09-4)**: Gate 1 REQUIRED (bounded, spec §13);
  Gate 2 NOT required (§14).
* **Task-block architecture (parent §13 ¶3, Q-09-1 = B refined)**: typed
  frozen pydantic VALUE with the FIXED framework key set `evidence_reading`
  / `per_model_guidance` / `synthesis_guidance` / `prediction_guidance`
  (each optional; absent ⇒ section omitted); reaches the interpreter as
  `InterpretationInput.task_blocks`, supplied by the CALLER (workflow
  today; the composition root at Step 12); the interpreter never discovers
  task files itself; ONE dedicated TIDMAD-owned declaration in a
  production-safe in-repo location (exact path fixed HERE, §4.2: NOT under
  `examples/`, NOT a new section of central `task_config.yaml`); ONE
  bounded adapter; no plugin loader/registry; no task-name branch; no
  LLM-skill abstraction.

## 2. Source audit (at `fd5557ee`)

### 2.1 The node after 09a — structure inventory

`nodes/result_interpretation_agent/` after PR #238:

| file | lines | role |
|---|---|---|
| `result_interpretation_agent.py` | 2,005 | PUBLIC main: prompt constants + builders (`:113-864`), evolution-log I/O (`:872-931`), `ResultInterpretationAgent` (`:939-1918`; `run()` `:953-1838` = 886 lines; `_dedup_promoted` `:1840-1918`), CLI `main()` (`:1926-2001`) |
| `evidence.py` | 488 | PRIVATE (09a): records → `ModelRunSummary` projections; `reconcile_metric_spec` (`:58`) |
| `ordering.py` | 308 | PRIVATE (09a): `precompute_evidence`, `collect_enriched_fields`, `bind_run_order` |
| `prediction.py` | 362 | PRIVATE (09a): `evaluate_prediction` (`:98-106` signature: `(prediction, actual_results, current_sota=None, partial_margin=0.05, *, order, bound_metric_id)`), `_compute_metric` (`:219`), `is_comparable` (`:283`), `accumulate_prediction_outcomes` (`:288`), `accumulate_information_gain` (`:328`), `prediction_pool_sizes` (`:348`) |
| `__init__.py` | 62 | ten re-exports + the `sys.modules` rebind |
| `nodes/interpretation_helpers.py` | 920 | still MIXED: discoveries (`generate_discoveries` `:222-386`), vocabulary cluster, active-model policy (`select_active_models` `:690-778` defaults top_k=3/last_n=2/delta=0.05; `should_recall_per_model` `:850-920`), `compress_model_summary` (`:781-847`) |

`__all__` (`:75-85`) exports the FOUR prompt constants +
`InterpretationContractError`, `ResultInterpretationAgent`, `main`,
`reconcile_metric_spec`, `tuning_output_to_model_run_summary`.
`_COMPATIBILITY_REEXPORTS` (`:101-111`) holds the nine 09a-moved helpers
with the "shrink, never grow" doctrine comment (`:87-100`).

`run()` lifecycle (886 lines): cold start (`:962-989`, deterministic, no
prompts) → `bind_run_order` (`:997`) → effective types + descriptions
(`:1035-1065`) → `precompute_evidence` (`:1072`) → C6 projections
(`:1101-1118`) → health merge (`:1132-1142`) → try{ Phase 1 per-model loop
(`:1181-1361`) → `collect_enriched_fields` (`:1367`) → Phase 2 synthesis
(`:1408-1457`) → Phase C prediction/discoveries/vocab/dedup/links
(`:1467-1603`) → E.4 accounting (`:1609-1634`) → output build + persist
(`:1648-1735`) } except{ degraded build + persist (`:1736-1838`) }.

### 2.2 The prompt/rendering surface — complete function inventory

For each symbol: inputs → semantic authority → classification → home after
09b. "A" = framework-generic; "B" = TIDMAD task science (moves into the
TIDMAD blocks); "C" = legacy/dead/contradictory (explicit disposition).

| symbol (file:lines) | inputs | authority today | class | deterministic / LLM-instruction | home after 09b |
|---|---|---|---|---|---|
| `PER_MODEL_SYSTEM_PROMPT` (`result_interpretation_agent.py:117-199`) | constant; `{TASK_DESCRIPTION}` slot | framework hardcodes TIDMAD science | MIXED — split table §5.1 | LLM instruction | framework TEMPLATE in `agent/prompt_templates/interpretation/rendering.py`; B-parts → TIDMAD declaration |
| `_build_per_model_system_prompt` (`:202-219`) | `InterpretationInput` | 04b `{TASK_DESCRIPTION}` substitution (`.replace`, `:213`) + flag-gated health-instruction append (`:217-218`) | A | deterministic assembler | rendering module (gains `task_blocks` splices in C2) |
| `HEALTH_FEEDBACK_SYSTEM_INSTRUCTIONS` (`:222-239`) | constant | Step-08 generic health-evidence rules | A, except one illustrative TIDMAD check-id example at `:234` (`"output_diversity_blocking:n_unique_int8_values=1"`) — class B/C residue REPLACED in C2 with a framework-generic example (operator ruling §0.4 amendment 1) | LLM instruction | rendering module |
| `_render_health_summary_section` (`:242-302`) | `ModelRunSummary`, `order` (keyword, 09a C3) | deterministic RoundHealth rendering; no task literals | A | deterministic renderer | rendering module |
| `_build_per_model_prompt` (`:305-461`) | summary, description, advice, flag, `order` | deterministic user-prompt assembly; D1-name labels (`:338-341`); **`(baseline typically uses 4000)` `:355`**; presence-gated table sections `:375-387`; trajectory + gate labels `:390-431` | A except the `:355` parenthetical (B) | deterministic builder | rendering module |
| `SYNTHESIS_SYSTEM_PROMPT` (`:468-550`) | constant; `{TASK_DESCRIPTION}` slot | framework hardcodes TIDMAD science (2nd copy of the pedagogy) | MIXED — split table §5.2 | LLM instruction | framework TEMPLATE; B-parts → TIDMAD declaration |
| `_NARRATIVE_FIELDS_FOR_PROMPT` / `_LIST_FIELDS_FOR_PROMPT` (`:556-566`) | constants | cache-entry display-shape bridging | A | deterministic | rendering module |
| `_flatten_entry_for_prompt` (`:569-592`) | cache entry dict | Commit-6.3 shape bridge | A | deterministic | rendering module |
| `_build_synthesis_system_prompt` (`:595-603`) | `InterpretationInput` | 04b substitution | A | deterministic assembler | rendering module (gains splices in C2) |
| `_build_synthesis_prompt` (`:606-814`) | 20 kwargs of precomputed evidence | deterministic synthesis user prompt; "Training PSD segments" label `:680` (schema-name-derived); presence-gated table sections `:711-717`; compressed blocks `:721-758`; discoveries `:760-780`; **"Research Health Metrics" `:798-812`: renders the LEGACY `cumulative_information_gain` with the FALSE explanation "(total boldness × confirmed across all iterations)" `:810` — the C4-corrected code computes gain = distance-when-confirmed; version-blind** | A except `:807-811` (C — stale + version-blind; §2.4) | deterministic builder | rendering module; the gain lines re-owned by the §6.5 renderer |
| `DEDUP_SYSTEM_PROMPT` (`:821-843`) + `_build_dedup_prompt` (`:846-864`) | constant; `VocabEntry` + canonicals | vocabulary-curator protocol; ML-architecture examples, no task science | A | LLM instruction / deterministic builder | rendering module |
| evolution-log helpers (`:872-931`) | — | persistence sidecar | A | — | STAY in main (persistence, not rendering) |
| `generate_discoveries` (`interpretation_helpers.py:222-386`) | prediction_eval, scores, `order` | deterministic discovery sentences that reach prompts via the vocab (`_build_synthesis_prompt:760-780`) | A except two literals (§2.5) | deterministic | stays in helpers (09a semantic owner); the two literals dispositioned in C4 |

### 2.3 LLM call sites and what determines the call count

| call | site | label | fires when |
|---|---|---|---|
| per-model | `result_interpretation_agent.py:1251-1255` | `interpretation.per_model` | for each `mt` in `effective_types` with `should_recall_per_model(...) == True` and a current summary; cache-hit + not-recalled ⇒ `emit_marker("interpretation.per_model_skipped")` (`:1215-1218`); cache-hit + recalled ⇒ ALSO `consolidate(...)` (`:1323-1330`) which issues `cache_consolidator.list_merge` calls (2 on the 09a C1a fixture) |
| synthesis | `:1450-1454` | `interpretation.synthesis` | ONLY when `len(effective_types) > 1` — the single-model branch (`:1408-1419`) builds a deterministic take-home and SKIPS the call |
| dedup | `:1891-1895` (inside `_dedup_promoted` `:1840-1918`) | `interpretation.dedup` | once per entry promoted THIS run (`promote_candidates`, structural rule `seen_in_runs >= 3`, `:1551`) that has ≥1 existing canonical of the same kind (`:1886-1888`) |

**Call count is fully input-deterministic.** Recall decisions read cached
`_stats` vs the current summary (`interpretation_helpers.py:896-920`);
promotion reads `seen_in_runs` accumulated from the CARRIED vocab and the
`previous_proposal`'s candidates (`:1536-1551`) — no LLM response content
feeds any later call-count decision (response content feeds later PROMPT
CONTENT only). A deterministic stub-bridge dry run over a fixed input
therefore yields the EXACT label sequence a real run will issue — §13 uses
this to pin the Gate-1 manifest.

### 2.4 The prediction-track-record consumers (both nodes, all sites)

The 09a versioned digest fields ALREADY reach the proposer: the
interp→propose protocol dumps the whole output
(`agent/schemas/protocols/ml_result_interp_to_ml_model_propose.py:171-179`,
`"interpretation": output.model_dump()`), and `ProposalInput.interpretation`
is an untyped dict (`agent/schemas/proposal.py:650-653`). Only the READERS
are stale — grep for the seven prediction-field names over
`nodes/ml_model_proposal_agent/` returns exactly SIX hits, all in two
sites:

1. **Proposer legacy renderer** —
   `nodes/ml_model_proposal_agent/ml_model_proposal_agent.py:1146-1165`
   (inside `_build_reasoning_prompt` `:1085-1309`, called from `_run_legacy`
   `:1501`): reads `scientific_accuracy` (v2-only since 09a),
   `cumulative_information_gain` (legacy scalar) and
   `prediction_outcomes_history` (legacy pool); renders
   `Scientific accuracy (N={sum(pred_hist.values())})` — **v2 fractions
   over the v1 denominator**, the exact frozen Q-09a-3 consequence. The sum
   has no key filtering (a future `unevaluated` key in that dict would
   count into N; today none is ever written there).
2. **Proposer pipeline whitelist** — `:1667-1688` (inside `_run_pipeline`
   `:1573`, the production 3-stage path): surfaces the SAME three legacy
   keys as raw JSON into every stage user prompt
   (`_render_stage_user_prompt` `:898-944`); the four 09a versioned names
   appear NOWHERE in the node.
3. **Interpreter's own synthesis prompt** —
   `result_interpretation_agent.py:798-812`: renders the LEGACY
   `cumulative_information_gain` input value (`:1406` passes
   `inp.cumulative_information_gain`) with the stale "(total boldness ×
   confirmed across all iterations)" explanation — the schema description
   was corrected in 09a C4 (`agent/schemas/interpretation.py:1057-1065`),
   the prompt line was not (deliberately: 09a was forbidden prompt bytes).

Pins on these sites:
`tests/unit/agent/ml_model_proposal_agent/test_prompt_context_surfacing.py:158-222`
(`TestBuildReasoningPromptTrackRecord`; the two N-pins at `:199-205`
history `{3,3,0}` ⇒ `"N=6"`, and `:207-213` absent ⇒ `"N=0"`); the byte
golden `goldens/reasoning_prompt_structured_evidence.txt:22-23` asserted by
full-string equality at `test_health_prompt_parity.py:37` (proposer copy —
its fixture sets no prediction fields, so only the IG `0.000` line is in
the golden); the pb3 pipeline-stage goldens
(`test_step00_prompt_goldens.py:338,:359`) currently contain NO prediction
keys (fixture omits them; the `is not None` filter `:1687` drops them).

### 2.5 Deterministic strings that reach prompts and carry task literals

* `interpretation_helpers.py:275` — `metric = prediction_eval.get("metric",
  "denoising_score")` in `generate_discoveries`: one task's metric name as
  the framework display default. **Dead post-09a-C4**: the discovery
  renders only THIS iteration's fresh evaluation, whose record shape
  uniformly carries `metric` (`prediction.py:98-…`, uniform key set).
  Class C — dead default, removed in C4 with a named test.
* `interpretation_helpers.py:371-374` — the timing discovery advice "High
  compute cost — **reduce segmentation_size** or complexity":
  `segmentation_size` is a TIDMAD data-prep hyperparameter named in a
  framework sentence that reaches the synthesis prompt (and the carried
  vocabulary). Class B — reworded task-free in C4 (declared oracle/golden
  delta; the census gains the token).
* `result_interpretation_agent.py:355` — "(baseline typically uses 4000)":
  class B; the volume-context sentence moves into TIDMAD's
  `evidence_reading` block (C2); the framework line keeps the
  schema-derived label only.

### 2.6 The goldens and prompt-pinning tests that constrain 09b

`tests/unit/agent/result_interpretation_agent/goldens/` (13 files): PB-0
`per_model_prompt_{legacy,collapse}.txt`, `per_model_system_prompt.txt`;
flag-ON `per_model_prompt_collapse_flag_on.txt`,
`per_model_system_prompt_flag_on.txt`; PB-7
`pb7_{synthesis,dedup}_{system,user}.txt`; PB-8
`pb8_list_merge_{system,user}.txt` (consolidator — NOT this node's
constants; `agent/cache_consolidator.py` owns them and 09b does not touch
them); the 09a differential oracle
`step09a_differential_digest.json` + `step09a_differential_llm_calls.json`
(labels + sha256(system)/sha256(user) per call, workspace-normalised).

Prompt-importing tests (grep census at the anchor; per-file hit counts):
`test_interpreter_prompt_task_config.py` (28 — the 04b substitution
contract), `test_interpretation_agent.py` (24), `test_step00_prompt_goldens.py`
(12), `test_health_prompt_rendering.py` (7), `test_prompt_banned_vocabulary.py`
(6), `test_health_prompt_parity.py` (5), `test_step09a_c3_order_consumers.py`
(4), `test_compressed_summary_contract.py` (2), plus `agent/llm_bridge.py`
(label-routing stub, 4) and `workflows/model_exploration.py` (2 — the
agent import). Only `LLMBridge` and `open` are `mock.patch`ed on the node
path (09a §2.7 census, unchanged).

`tests/unit/agent/test_prompt_banned_vocabulary.py`: imports the two system
prompts from the node package (`:20-23`); `test_banned_vocabulary_absent`
(`:49-76`, the V9 token scan); **`test_impact_aware_framing_present`
(`:79-91`) REQUIRES `Impact_Score` / `Linear_Weight` / `Log-of-Mean` in
both interpreter system prompts** — this INVERTS under 09b (banned in the
framework template, required in the TIDMAD-ASSEMBLED prompt); the
planner/proposer halves (`:94-100`) pin OTHER nodes' prompts and stay.

### 2.7 Config/declaration precedents (04b task description; 08b task health)

* The interpreter's `task_description` is caller-supplied:
  `workflows/model_exploration.py:2183`
  `task_description=get_task_description(load_task_config())`;
  `load_task_config` / `get_task_description` live in
  `workflows/task_config.py:86/:228`; default path constant
  `configs/task_config.yaml` (`:41`); `configs/task_config.yaml` carries
  ONLY `task_description` (`:10`) + `forward_contract` (`:20`) — **no
  interpretation science enters it (Q-09-1 ruling holds)**.
* The 08b task-owned-declaration precedent this design copies:
  `configs/task_health/tidmad.yaml` (105 lines; top-level keys
  `facts`/`value_scale`/`health_peek_files`/`roster`; NO task-identity key —
  identity is the path); the ONE unconditional default constant
  `LEGACY_DEFAULT_TASK_HEALTH_CONFIG =
  os.path.join("configs", "task_health", "tidmad.yaml")`
  (`execute_tools/health_checks/_composition.py:89`, docstring: "a
  CONSTANT, not a branch… An external task passes its own path and never
  touches this"); the loader lives in the OWNING subsystem
  (`health_checks/config.py:497-530`).
* The workflow's interpreter wiring (all current line numbers):
  `InterpretationInput(...)` built inline at `:2148-2184` (17 fields;
  `metric_spec` `:2151` from `reconcile_metric_spec([*tuning_outputs,
  *iteration_results])` `:2147`; the four C5 prediction-memory fields
  `:2153-2163`); agent constructed/run `:2187-2192`;
  `_cap_knowledge_cache` `:651-657` called at `:2800-2804`; the
  prediction-memory loop carry `:2812-2826`.

### 2.8 The preserved TIDMAD artifact (Gate-1 input facts, read-only)

`/home/klz/Data/SIDEREIS_DATA/step07b_gate1_postrefactor/` (verified at the
anchor):

* `iter_001/iteration_001/wavenet24_fullspectrum_ce_coldstart/run_output_iter_001.json`
  — model `wavenet24_fullspectrum_ce_coldstart`, 3 records, `status:
  completed`; `iter_002/iteration_002/bidirectional_gated_tcn/run_output_iter_002.json`
  — 18 records, `status: partial`. **Both lack `metric_spec`** (pre-09a
  outputs; 44-key schema) — a score-bearing `InterpretationInput` built
  from them REFUSES at construction (09a Q-09a-6, fail closed).
* Every record carries `metric_result` (non-null on 2 / 1 records
  respectively) with `{metric_id: "tidmad_denoising_score", direction:
  "higher", …}` — so a harness-stamped TIDMAD spec SATISFIES the §4a
  identity-agreement clause rather than bypassing it.
* The ONLY digest, `iter_002/iteration_002/interpretation_iter_002.json`
  (35 keys): `model_knowledge_cache` keys = exactly
  `{wavenet24_fullspectrum_ce_coldstart}`; `runtime_vocab` = 23 entries
  (11 feature, 10 capability, 2 discovery; the 2 discoveries are
  `tier="candidate"`); `prediction_evaluation` = the production
  uncomputable-"partial" defect record; `prediction_outcomes_history` =
  `{confirmed: 0, partial: 1, refuted: 0}`.
* The realistic "iteration 3" interpretation input is therefore: summaries
  = [the btcn output], cache + vocab + prediction memory + previous
  proposal from the iter-2 digest/proposal — 2 effective types, ONE
  per-model call (btcn: cache miss + summary), wavenet24 = Stability skip
  (cache hit, no current summary — `interpretation_helpers.py:905-906`),
  synthesis fires (2 types). Machine-local: the Gate harness declares the
  path requirement and SKIPS with a named reason when absent (CLAUDE.md
  portability rules).
* **Probe-grounding facts (verified read-only at the anchor, §13):** the
  artifact carries NO score table anywhere — `best_score_table` /
  `formal_score_table` / `best_valid_score_table` are `null` on BOTH run
  outputs, the wavenet24 cache `_stats.best_score_table` is `null`, and
  the digest's `per_model_score_tables` is `{}` — so the frozen TIDMAD
  Gate input contains ZERO per-file evidence. Scores: btcn
  `best_denoising_score = -2.3322708898096955` vs wavenet24 cached
  `-2.4310203852971433` — btcn is unambiguously better under
  higher-is-better on NEGATIVE values (a magnitude-reader inverts this).
  The carried prediction's metric string ("mean denoising_score over
  validation files [4,5,6,7,8,9]") is `unrecognized` under 09a ⇒ the Gate
  run's evaluation is `unevaluated` (live evidence for the §9 guard). The
  proposal carries 2 `proposed_vocab_candidates` (each seen once) ⇒ 0
  promotions ⇒ 0 dedup calls. A file-token regex over every carried prose
  field (cache narrative fields, digest take-home, all 23 vocab entries)
  finds ZERO file-index tokens — so ANY file-index designation in the Gate
  outputs is fabricated, grounding probe P-A2.

### 2.9 Authorities consumed (all landed; none modified)

`MetricSpec` / `MetricResult` / `NotScoreableResult` / `MetricSpecField` /
`metric_spec_from_declaration` (`execute_tools/evaluation_metric.py`);
`MetricOrder` incl. `direction_words` (`execute_tools/metric_order.py`);
the 07b renderer precedent — `render_metric_direction_words`
(`agent/prompt_templates/tuner/rendering.py:246-261`),
`render_metric_identity_line` (`:264-273`),
`render_training_dynamics_line` (`:280-336`, with explicit degenerate-state
lines "training dynamics: none recorded" / "invalid (non-finite)");
`TrainingDiagnosis` (frozen); the 09a schema layer
(`agent/schemas/interpretation.py`): semantics constants `:59-71`
(`PREDICTION_SEMANTICS_SIGNSAFE_V2` / `…_LEGACY_V1` /
`COMPARABLE_OUTCOMES` / `OUTCOME_UNEVALUATED` — the F-09a-17 single
authority), `PredictionMemory` `:74-108`, `SecondaryMetricEvidence`
`:114-165` (`status` property `scored|refused|unavailable`),
`RecordFailureCounts` `:168-205`, `MetricIdentity` `:208-227`,
`ModelRunSummary` (36 fields; `metric_identity` `:469`,
`best_training_diagnosis` `:482`, `formal_training_diagnosis` `:492`,
`secondary_metrics` `:500`, `failure_counts` `:511`),
`InterpretationInput` (24 fields, all defaulted; `task_description` `:562`;
`metric_spec` `:743` + the fail-closed validator `:756-846`),
`InterpretationOutput` (42 fields; the seven prediction fields `:1057`,
`:1067`, `:1073`, `:1158`, `:1169`, `:1180`, `:1187`;
`per_model_secondary_metrics` `:1198`; `per_model_failure_counts` `:1205`).
Shared test fixtures `tests/helpers/metric_fixtures.py` (`shipped_spec`
`:49`, `direction_only_spec` `:30`, `accuracy_like_spec` `:54`,
`error_like_spec` `:69`). Pack declarations
`examples/{oxford_iiit_pet,davis_future_prediction}/declared/metric_*.json`
and the 09a C7 L1 fixtures
`examples/*/expected/interpretation_evidence_l1_fixture.json`.

## 3. Frozen contracts and invariants 09b must preserve

* **09a semantics are closed.** No change to: `MetricOrder` consumers, the
  v2 band, `unevaluated`, the v1/v2 partition and its per-field semantics
  (Q-09a-2 table), `reconcile_metric_spec`, the input validator, the
  builder projections, `PredictionMemory` transport, any digest FIELD
  semantics. 09b renders these; it never recomputes or reinterprets them.
* **D1 names unchanged** (`best_denoising_score` / `file_vector` /
  `score_table` / …); the cache-entry field names
  (`per_file_analysis` etc., `CacheEntry` schema) unchanged — the 07b
  Q-07b-3 precedent governs: the prompt carries BOTH the frozen field
  label and the rendered metric identity, and renaming fields is not
  rendering work (§19.2).
* **Phase order, the degraded-mode contract, persistence paths
  (`interpretation_{run_name}.json`, evolution log), CLI arguments, the
  `__init__.py` rebind, LLMBridge call labels** — unchanged.
* **The per-model / synthesis JSON OUTPUT field sets are framework
  protocol** (consumed by `CacheEntry`, the flattener, the synthesis
  reader `:1455-1457`) — the field SETS do not change; only instruction
  PROSE moves/changes with declared deltas.
* **Prompt-golden discipline**: C1 is byte-exact (all 13 golden files +
  the 09a oracle untouched); every later byte delta is DECLARED in the
  owning commit, attributed to an authority, and landed as regenerated
  goldens in the same commit; an UNDECLARED delta is a STOP.
* **Q-09-7 = B**: no secondary evaluator/loader/binding/persistence/
  transport anywhere in 09b; secondaries render present-when-present from
  `ModelRunSummary.secondary_metrics` / `per_model_secondary_metrics`
  (production-empty until Step 10; L1 fixtures supply them).
* **REC-3 golden**: 09b appends NO field to `InterpretationOutput` or
  `HyperparamTuningOutput` ⇒ `rec3_schema_field_lists.json` must be
  byte-identical at every commit. (`InterpretationInput` gains
  `task_blocks` — that model is deliberately NOT pinned by REC-3, 09a §2.7.)
* **No new memory**: blocks are caller-supplied declaration VALUES, not
  state; nothing new persists in the digest.

## 4. `InterpretationTaskBlocks` — the exact typed contract

### 4.1 The value type (schema layer)

`agent/schemas/interpretation.py` (beside `MetricIdentity` — the same
frozen-value idiom):

```python
class InterpretationTaskBlocks(BaseModel):
    """Task-owned interpretation guidance — prose VALUES, framework keys.

    The FRAMEWORK owns the key set and where each section renders; the TASK
    owns the prose. Each field is optional: an absent section is a legal
    named absence and renders NOTHING (no header). The interpreter never
    reads task files; the caller supplies this value (workflow regime-A
    adapter today, the Step-12 composition root later).
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_reading: str | None = None      # how to read THIS task's evidence
    per_model_guidance: str | None = None    # Phase-1 per-model analysis guidance
    synthesis_guidance: str | None = None    # Phase-2 cross-model guidance
    prediction_guidance: str | None = None   # prediction-interpretation guidance
```

Plus one validator: a present section must be non-empty after `strip()`
(an empty string is a malformed declaration, refused — never silently
treated as absence). No other normalisation: prose bytes are preserved
verbatim (the migration parity depends on it).

* Key-set growth is a FRAMEWORK decision (parent §9-F); the §16 census pins
  the field set to exactly these four.
* `InterpretationInput.task_blocks: InterpretationTaskBlocks | None = None`
  (appended). `None` ⇒ every section omitted — cold-start, scoreless,
  ad-hoc and pre-09b-shaped callers stay legal.
* Rendering placement (framework-owned, frozen here): `evidence_reading`
  renders in BOTH phase system prompts (it replaces the pedagogy that is
  today restated in two constants — ONE value, two render sites);
  `per_model_guidance` in the Phase-1 system prompt only;
  `synthesis_guidance` and `prediction_guidance` in the Phase-2 system
  prompt only. Framework-owned section headers (`### Task evidence
  guidance`, `### Task analysis guidance`, `### Task synthesis guidance`,
  `### Task prediction guidance`) render ONLY when their section is
  present.

### 4.2 The TIDMAD declaration and the bounded adapter (regime-A)

Copying the 08b packaging doctrine exactly (§2.7):

* **Declaration**: `configs/task_interpretation/tidmad.yaml` — top-level
  keys = the four section names, each a YAML block scalar carrying the
  MIGRATED TIDMAD prose verbatim (§5.3); NO task-identity key (identity is
  the path); a header comment stating the 08b ownership doctrine
  ("everything here is the TASK's science; in-repo residence is REFERENCE
  PACKAGING, not a framework dependency; an external task supplies the
  typed value — or its own file anywhere on disk — with no SIDERIUS
  edit"). NOT under `examples/`; NOT a section of `configs/task_config.yaml`.
* **Adapter**: `agent/prompt_templates/interpretation/task_blocks.py` —
  `load_interpretation_task_blocks(path: str | None = None) ->
  InterpretationTaskBlocks` (path `None` ⇒ the one unconditional default
  constant `LEGACY_DEFAULT_TASK_INTERPRETATION_CONFIG =
  os.path.join("configs", "task_interpretation", "tidmad.yaml")`, the
  `_composition.py:89` idiom — a CONSTANT, not a branch). Parses YAML →
  validates the typed value (`extra="forbid"` refuses unknown keys) —
  fail-closed on a missing/unreadable/malformed file (the workflow must
  never silently interpret TIDMAD without its science). ONE adapter, ONE
  caller class (workflow + the node CLI `main()`, both regime-A); no
  discovery, no registry, no plugin loader; Step 12 replaces the CALL, not
  the contract.
* **Workflow**: `InterpretationInput(..., task_blocks=
  load_interpretation_task_blocks())` beside the existing
  `task_description=` line (`model_exploration.py:2183`) — the same
  regime-A compatibility posture, self-labelled. The pr3 calibration entry
  points and other input builders pass nothing (`None` ⇒ omitted sections —
  legal).

## 5. Framework-vs-task prompt ownership (the exact split)

### 5.1 `PER_MODEL_SYSTEM_PROMPT` (`:117-199`) — block-level classification

| lines | content | class | disposition |
|---|---|---|---|
| 118-124 | analyst role; task statement; `{TASK_DESCRIPTION}` slot | A (one TIDMAD-flavoured axis word: "per-file behaviour" in the coverage list) | framework template; the coverage list reworded task-free ("per-sample behaviour where per-sample evidence exists") — declared delta |
| 126-136 | "You will receive:" — items: architecture description / best+worst scores / best config / trajectory / conclusions (A); **per-file score-table column inventory (`:132-135`) and "PSD segments … baseline" volume item (`:136-137` region)** (B) | MIXED | generic items stay framework; the two B items move VERBATIM into TIDMAD `evidence_reading`; the framework score item is reworded metric-neutral — declared deltas |
| 138-152 | "### Reading the per-file score table — the Log-of-Mean trap" intro + `Linear_Weight` / `Impact_Score` definitions (byte-shared with the synthesis copy `:490-504`) | B | ONE `evidence_reading` value, rendered in both phases — the "restated in TWO prompts" coupling (roadmap `:1221-1222`) collapses to one authority |
| 154-168 | the four per-model reading rules ("Rank the files by Impact_Score…", "this model has reached the dataset ceiling — say so", "Do not memorise file-index labels…") | B | TIDMAD `per_model_guidance`, verbatim |
| 170-188 | the JSON output schema | A skeleton; the `per_file_analysis` instruction string (`:183`) and the `data_sensitivity` volume reference (`:184`, `training_psd_segments`) carry B prose | field SET unchanged (§3); B instruction prose moves into `per_model_guidance`; the framework field instructions become task-free with an explicit named-absence rule ("when the summary carries no per-sample evidence, say so — never invent per-sample claims") — declared deltas |
| 189-198 | Rules block | A except `:191` (bottleneck example "all sampled files saturated against their ground_truth ceiling"), `:194` (Impact_Score ranking rule), `:195` (`training_psd_segments` reference) | B lines move verbatim into `per_model_guidance`; A lines stay |

### 5.2 `SYNTHESIS_SYSTEM_PROMPT` (`:468-550`) — block-level classification

| lines | content | class | disposition |
|---|---|---|---|
| 469-475 | role + task statement + slot | A | framework template |
| 477-488 | "You will receive:" | A except the score-table column pedagogy (`:481-484`) | B item → `evidence_reading`; rest framework (reworded metric-neutral where "scores" implies direction) |
| 490-504 | Log-of-Mean intro + column definitions (2nd copy) | B | the SAME `evidence_reading` value (§5.1) |
| 506-524 | the four cross-model rules (cross-model Impact_Score levers; "declare it explicitly. There is no fixed cutoff"; per-iter re-reading) | B | TIDMAD `synthesis_guidance`, verbatim |
| 526-540 | JSON schema | A skeleton; `per_file_comparison` (`:537`) and `take_home_message` (`:539` — the (a)/(b) `Impact_Score`/`file_index` MUST-rules) carry B prose | field SET unchanged; B prose → `synthesis_guidance` verbatim; framework instructions task-free — declared deltas |
| 542-549 | Rules | A except `:545` (`per_file_comparison` ranking rule) and `:547` (take-home `file_index` example "file 17") | B lines → `synthesis_guidance`; A stay |

### 5.3 TIDMAD block content (the migration inventory — VERBATIM rule)

`configs/task_interpretation/tidmad.yaml` receives, verbatim and complete:
the Log-of-Mean trap section (one copy — C2 records the byte-diff between
today's per-model and synthesis copies and carries the union faithfully:
the intro/column paragraphs are byte-shared, the numbered rules differ per
phase and go to their phase's guidance section), the per-model reading
rules, the per-file table column inventory, the PSD/4000-baseline volume
framing (`:136-137`, `:355`), the `per_file_analysis` /
`per_file_comparison` / `take_home_message` science prose incl. the
(a)/(b) rules and the "file 17" exemplar, and the two B rule-lines from
each Rules block. `prediction_guidance` is **ABSENT for TIDMAD** — the
current interpreter prompts contain no prediction-authoring or
prediction-interpretation prose to migrate (predictions are authored by the
proposer; 09a `prediction.py` records "constraining NEW predictions to the
bound id is a proposer prompt/schema matter"), and inventing new science
during a migration is forbidden. The key is contract-complete and rendered
when a task supplies it; its first content producer is a later owner
(§19.2). "Do not improve TIDMAD scientific wording while migrating" is a
C2 acceptance criterion: the declaration's prose must be a pure
rearrangement of today's sentences (the C2 checklist carries a
sentence-accounting table: every B-classified sentence appears exactly
once in the declaration; every A sentence stays; every reworded framework
line is listed with before/after bytes).

### 5.4 What stays framework and why (named residuals)

* D1-derived labels in user prompts ("Raw best score", "Worst denoising
  score", "Training PSD segments", "### Per-file performance") — frozen
  record vocabulary rendered as labels, presence-gated where the evidence
  is optional; the 07b Q-07b-3 precedent adds the metric-identity line
  BESIDE them (§6.1) rather than renaming them. Scalar-only tasks never
  render the table/volume lines (presence-gated already).
* `HEALTH_FEEDBACK_SYSTEM_INSTRUCTIONS` — generic Step-08 evidence rules.
  Its one illustrative TIDMAD check-id example (`:234`) does NOT stay: C2
  replaces it with a framework-generic example drawn from EXISTING 08c
  generic-check vocabulary —
  `"sample_dispersion_floor_blocking:dispersion=0.0"` — preserving the
  instruction's point (an exact signature string with its numbers) while
  removing the last known task-specific check-id literal from the generic
  interpretation prompt templates (operator ruling §0.4 amendment 1; a
  declared C2 golden delta; Health verdict/action semantics untouched; the
  example is NOT moved into TIDMAD blocks and no new task-specific example
  is invented).
* `DEDUP_SYSTEM_PROMPT` — generic vocabulary-curator protocol.
* The compressed-model, discoveries, expert/human-advice, trajectory and
  gate-label rendering in the user-prompt builders — task-free evidence
  rendering.

## 6. Explicit renderer contracts (one authority per evidence family)

All renderers live in `agent/prompt_templates/interpretation/rendering.py`,
receive TYPED authoritative evidence, delegate every direction word to
`MetricOrder`/`direction_words`, render named absences explicitly, and are
deterministic pure functions (the 07b idiom). None re-derives domain
semantics; none parses ids for meaning.

| family | renderer (new unless noted) | typed inputs | output contract |
|---|---|---|---|
| **metric identity** | REUSE `render_metric_identity_line` + `render_metric_direction_words` (`agent/prompt_templates/tuner/rendering.py:246-273` — the EXISTING one authority; imported, never copied) | `MetricSpec` (input) / `MetricIdentity` (summary) | one line per prompt: ``golden metric `<id>` (<higher/lower> is better)`` rendered in both phase user prompts' headers; per-model summary identity rendered beside the score labels |
| **training diagnosis** | REUSE `render_training_dynamics_line` (`tuner/rendering.py:280-336` — the existing one authority for the line grammar incl. "training dynamics: none recorded") wrapped by a new `render_interpretation_diagnosis_lines(best, formal)` | `ModelRunSummary.best_training_diagnosis` / `formal_training_diagnosis` | ≤2 lines per model in the per-model user prompt (`best:` / `formal:` roles); absent diagnosis renders the explicit absence line; NEVER re-derived |
| **secondary metrics** | `render_secondary_metrics(secondaries)` | `list[SecondaryMetricEvidence]` | one line per secondary: ``secondary `<spec.id>` (<dir> is better): <scalar>`` for `status=="scored"`; ``… : refused (<contract id verbatim>)`` for `refused`; ``… : declared, not evaluated this run`` for `unavailable` — a NAMED absence, never a number; EMPTY list ⇒ section omitted (production today); ordering = declaration order; own direction words per metric; never consulted for any ordering (09a census re-runs) |
| **failure counts** | `render_failure_counts(counts)` | `RecordFailureCounts` | a compact deterministic block keyed ONLY by the existing authority vocabularies (status values, diagnosis states incl. the `diagnosis_missing`-vs-`absent` split, validation states, refusal contract-ids verbatim, gate actions, provenances); zero-count keys omitted; `None` ⇒ omitted; open dicts render unknown future keys verbatim (no enum) |
| **prediction track record** | `render_prediction_track_record(...)` — §9's exact contract; the ONE authority used by the interpreter synthesis builder AND the proposer legacy renderer | the seven digest fields (legacy trio + versioned quartet) | §9 |
| **health evidence** | RETAINED: `_render_health_summary_section` (moved verbatim in C1) + the existing flag-gated instruction block | `ModelRunSummary.round_health`, `order` | unchanged bytes |

Size/truncation: the new per-model additions are O(lines-per-model), each
family ≤ a handful of lines; no unbounded content is introduced (tables and
trajectories keep their existing bounds); no new truncation machinery.
Fail-closed malformed-state behaviour: renderers accept exactly the typed
authorities — a malformed value fails Pydantic upstream, never inside a
renderer; renderers themselves never raise on ABSENCE (absence is a
rendering state, §6 table).

## 7. Node-local structure plan (after 09b)

```text
nodes/result_interpretation_agent/
    result_interpretation_agent.py   PUBLIC — ResultInterpretationAgent lifecycle
                                     (run(): phase sequencing, degraded fallback),
                                     evolution-log I/O, _dedup_promoted (LLM loop),
                                     main() CLI, narrow re-exports
    evidence.py / ordering.py / prediction.py   PRIVATE (09a, unchanged)
agent/prompt_templates/interpretation/
    __init__.py
    rendering.py     framework prompt templates + builders (moved verbatim in C1)
                     + the §6 explicit renderers (C3/C4)
    task_blocks.py   the InterpretationTaskBlocks adapter + the ONE default
                     path constant (C2)
nodes/interpretation_helpers.py      unchanged home (discoveries/vocab/policy)
configs/task_interpretation/tidmad.yaml   the TIDMAD science declaration (C2)
```

* Expected sizes (engineering evidence, not acceptance): main file 2,005 →
  ≈1,250 lines (the ~750-line prompt surface `:113-864` moves out; `run()`
  stays 886 — 09b adds no responsibility to it, threading `task_blocks`
  and renderer outputs through EXISTING call sites); `rendering.py`
  ≈900-1,100 lines but ONE responsibility (prompt building/rendering — the
  tuner's `rendering.py` precedent at 379 lines, larger here because the
  interpreter owns two phases + dedup + health sections); `task_blocks.py`
  ≈120 lines.
* Acceptance is the RESPONSIBILITY boundary: main = lifecycle +
  degraded + persistence + CLI ("the node retains Phase orchestration
  only", parent §13a); rendering module = every prompt byte; declaration =
  every TIDMAD science byte; no `utils.py`, no second public node, no new
  private node module.
* **No pre-emptive split; STOP on mixed ownership (operator ruling §0.4)**:
  `rendering.py` is NOT split to hit a line target — coherent single
  responsibility outranks LOC. The §22 ledger records its FINAL
  responsibility inventory and LOC. If implementation reveals genuinely
  MIXED semantic ownership inside it (not mere length), STOP and
  disposition the boundary; otherwise the scheduled post-09b /
  pre-Step-10 structural audit re-inspects it with real code in hand.
* The node-public-boundary rule is unaffected (`agent/prompt_templates/…`
  is a framework package, not a node-private module — the tuner precedent);
  the banned-vocab / golden tests move their imports to the owning module
  per the C1 disposition; `__all__` keeps the four prompt-constant names as
  narrow re-exports ONLY if an external non-test importer exists at C1's
  fresh census — otherwise test imports MOVE and the re-export is dropped
  (the "shrink, never grow" doctrine, `:87-100`).

## 8. Three-task rendering contrast (+ the 11-A/11-B rungs)

| axis | TIDMAD | Pets | DAVIS |
|---|---|---|---|
| primary | `tidmad_denoising_score`, higher, negative regime | `accuracy`, higher | `mse`, **lower** |
| identity line | "higher is better" | "higher is better" | **"lower is better"** |
| per-sample | table + file_vector present ⇒ table sections render | scalar-only ⇒ NO per-file section, NO table pedagogy | scalar-only ⇒ same |
| task blocks | the migrated declaration (§5.3) | NONE supplied (L1) ⇒ sections omitted; no TIDMAD prose leaks | NONE supplied (L1) ⇒ same |
| secondaries | none ⇒ section omitted | `macro_f1` (higher), scored | `psnr` (higher) scored; `mae` (lower) **declared-unavailable** ⇒ named absence line |
| diagnosis | real/fixture diagnosis lines | `ce` fixture diagnosis | `smooth_l1` fixture diagnosis |
| health | TIDMAD RoundHealth (flag-ON renders counts/fingerprints) | categorical-collapse-shaped RoundHealth | dispersion-shaped RoundHealth |
| prediction rendering | negative-sota v2 wording | n/a (fixture optional) | lower-is-better band wording; "beating" = SMALLER |

Every expected rendering is a HAND-OWNED literal (never read back from the
function under test). Pets/DAVIS remain **L1 rendering/contract fixtures**
(carrier-shaped inputs built from the packs' `declared/` + the 09a C7
`expected/interpretation_evidence_l1_fixture.json`); no workflow-maturity
claim; production keeps zero `examples/` dependency (census re-runs).

**The roadmap rungs (`:1233-1235`), instantiated on the rendering surface:**

* **11-A — metric identity only**: one TIDMAD-shaped input rendered twice —
  once under the shipped spec, once under a stub identity
  (`direction_only_spec()`-style: different id, `lower`); the RENDERED
  prompt pair must differ EXACTLY in the identity/direction-word lines
  (table sections, labels, trajectory, health bytes identical) — proven by
  a line-level diff against a hand-owned expected delta set.
* **11-B — table indexing only**: the TIDMAD metric with the score table's
  rows presented as per-SAMPLE rows instead of per-file (same
  `ScoreComparisonTable` carrier, sample-indexed row labels); the rendered
  prompt must carry the table verbatim from `rendered_markdown` with NO
  framework-injected per-FILE assumption around it — the only diff vs the
  per-file twin is the table's own bytes.

## 9. Prediction-track-record rendering contract (version-aware)

ONE renderer, `render_prediction_track_record(legacy_history,
outcomes_by_semantics, legacy_gain, gain_by_semantics, scientific_accuracy,
pool_sizes)` — consumed by (a) the interpreter synthesis builder (replacing
the `:807-811` gain line) and (b) the proposer legacy renderer (replacing
`:1150-1164`). Exact rendering by history shape:

| shape | rendered |
|---|---|
| **v2-only** (legacy pool 0) | `Scientific accuracy (metric_order_signsafe_v2, N=<v2 pool size>): confirmed=X% partial=Y% refuted=Z%` + `Cumulative information gain (metric_order_signsafe_v2): <v2 sum>` — the N is the v2 pool's own size, never the legacy sum |
| **legacy-only** (v2 pool 0, legacy > 0) | NO accuracy percentages (accuracy is `None` while the v2 pool is empty — an absent hit-rate, never fabricated); one line: `Prediction history: <n> outcome(s) recorded under pre-correction semantics (legacy_v1) — not comparable with current-semantics statistics` + the legacy gain labelled `(legacy_v1)` when non-zero |
| **mixed** | the v2 lines (as v2-only) PLUS the legacy line — two pools, two labels, never one number |
| **empty** (both pools 0, gains 0, accuracy None) | section omitted entirely |
| **`unevaluated`** | never rendered as partial/inconclusive success and never in any N (structural: it is in neither pool — 09a; the renderer adds a guard test, not new logic) |

The stale "(total boldness × confirmed across all iterations)" explanation
(`:810`) is deleted with the line it annotated (the schema description
`interpretation.py:1057-1065` is the corrected authority). The proposer's
pipeline whitelist (`:1667-1688`) gains the four versioned keys
(`prediction_outcomes_by_semantics`, `cumulative_information_gain_by_semantics`,
`prediction_pool_sizes`, `prediction_evaluation_semantics`) so the
production 3-stage path surfaces self-describing honest JSON — additive;
the pb3 goldens move only if their fixtures carry the keys (they do not;
verified §2.4). Version ids render via the schema constants (F-09a-17
single authority) — never re-spelled.

## 10. Secondary and failure rendering (kickoff §10/§11 obligations)

* Secondaries: §6 table — present/refused/unavailable each has an exact
  line; production renders the OMITTED state until Step 10 (honest);
  L1 fixtures exercise all three states; the 09a
  secondaries-never-ordered census re-runs unchanged, and a NEW behavioural
  probe pins that flipping every secondary value changes no rendered
  ORDERING content (only the secondary lines themselves).
* Failures: rendered ONLY from `RecordFailureCounts` — every key an
  existing authority's vocabulary (09a C6); NO new failure enum, NO
  grouping beyond what the counts model already owns; unknown future
  status/action strings render verbatim under their own keys (open dicts).
  A task with a novel pathology expresses it at its owning layer and the
  renderer shows it without source growth.

## 11. Commit decomposition

### 11.0 Standing rules

* Each commit's first item is a bounded re-read of the exact functions it
  edits, at the implementation head; ambiguity or larger scope than this
  design assumes → **STOP and ask before changing the plan**.
* `[ ]` = not done; `[x]` only with recorded evidence (test counts, wall
  time, log path) in §22. **Every box below is `[ ]` at draft/freeze.**
  Pytest verdicts come from complete log files (`> log 2>&1; rc=$?`),
  never a wrapper's exit status.
* Before EVERY commit: stop and show the exact diff summary, staged file
  list, the tests run, and any deviation from this design; wait for
  permission — unless the operator's 09b implementation authorization
  explicitly supersedes this (the 09a §10.0 reconciliation pattern).
  pytest may run freely; the ONLY real-LLM cost in 09b is the C6 Gate-1
  launch, which needs the §13 spec re-confirmed and operator approval per
  the gate standard (`gate_testing_standard.md:148`).
* An UNDECLARED prompt-golden byte delta at any commit is a STOP. The 09a
  differential oracle regenerates ONLY in the commit that declares its
  delta, with the delta enumerated field-by-field / call-by-call in §22.
* Out of scope for every commit: secondary evaluation/loader/binding/
  persistence/transport; proposer prediction-AUTHORING grammar; a new
  metric derivation site; task-name branches; tuner/planner/reflector
  prompts; `evaluation.py`; resume/dashboard literals; retention numbers;
  the repo-wide cleanup. Production-DEFAULT changes (CLI defaults, flags,
  retention/window numbers, provider defaults) are outside every commit;
  the ONLY prompt surfaces 09b may touch are the interpreter
  templates/builders/renderers and the two C4-named proposer reader sites.
* The design document is updated IMMEDIATELY after each implementation or
  test checkpoint (boxes + §22 evidence in the same working session as the
  work), never batched at the end.
* Commit messages: `Step 09b C<n>: …`; a planned commit may split at clean
  boundaries (`-code`/`-tests`/`-docs`) preserving the last split's DoD.

---

### 11.1 C1 — behaviour-preserving move of the prompt surface into the rendering module

**Goal.** Every interpreter prompt constant and builder lives in
`agent/prompt_templates/interpretation/rendering.py` with ZERO byte
changes to any rendered prompt, golden or digest — the roadmap's
"golden-equal" half (§0.3-D1), and the precondition for C2's re-owning to
be reviewable as a pure ownership change. First because every later
commit's declared deltas are measured against a tree where structure has
already settled (the 09a C1a→C1b pattern; the 09a oracle already exists,
so no capture commit is needed).

**Scope.** NEW `agent/prompt_templates/interpretation/{__init__.py,
rendering.py}`; MOVE verbatim from `result_interpretation_agent.py`:
`PER_MODEL_SYSTEM_PROMPT`, `_build_per_model_system_prompt`,
`HEALTH_FEEDBACK_SYSTEM_INSTRUCTIONS`, `_render_health_summary_section`,
`_build_per_model_prompt`, `SYNTHESIS_SYSTEM_PROMPT`,
`_NARRATIVE_FIELDS_FOR_PROMPT`, `_LIST_FIELDS_FOR_PROMPT`,
`_flatten_entry_for_prompt`, `_build_synthesis_system_prompt`,
`_build_synthesis_prompt`, `DEDUP_SYSTEM_PROMPT`, `_build_dedup_prompt`
(`:113-864`); main module imports them (narrow re-exports per the fresh
importer census; `__all__` updated); test imports MOVE to the owning
module per §5-disposition (banned-vocab, goldens, task-config, health
rendering, interpretation-agent suites). Must NOT change: any prompt byte,
any label, `run()` behaviour, evolution-log helpers (STAY in main),
`_dedup_promoted` (stays — it is an LLM loop, not rendering),
`interpretation_helpers.py`, `__init__.py` re-export set semantics.
Depends on nothing.

**Implementation plan.**
- [ ] Re-read `:75-111` (`__all__`/compat), `:113-864` (the full move set)
      and every §2.6 importing test at the implementation head; record the
      fresh import census (file:line per importer) in §22 BEFORE moving.
- [ ] Create the package; move the thirteen symbols VERBATIM (docstrings,
      comments, order preserved); rendering module imports
      (`MetricOrder`, schemas, `ScoreComparisonTable`) added as needed.
- [ ] Main module: import the builders it calls; re-export decision
      executed per the census (production importers → narrow re-export;
      test-only importers → tests move).
- [ ] Update the §2.6 test imports; no assertion changes.
- [ ] Node `.md` "Module layout" section updated.

**Validation plan.**
- [ ] Unit: the 09a differential oracle EXACT (digest + call manifest,
      byte-identical); ALL 13 prompt goldens EXACT (`git status` clean on
      `goldens/`); the whole `tests/unit/agent/result_interpretation_agent/`
      directory; `tests/unit/agent/test_prompt_banned_vocabulary.py`;
      `tests/unit/nodes/test_node_public_boundary.py`;
      `tests/unit/workflows/test_model_exploration.py` (patch targets).
- [ ] Negative: a planted byte edit in one moved constant reds the golden
      suite (proves the goldens still bind the moved bytes) — recorded,
      reverted.
- [ ] Backward-compat: every production importer resolves (fresh census);
      `mock.patch("nodes.result_interpretation_agent.LLMBridge")` still
      intercepts; `main --help` sha256 identical.

**Acceptance criteria.**
- [ ] Zero golden bytes changed; oracle byte-identical; the main file no
      longer defines any prompt constant/builder; the rendering module
      defines each exactly once (single-definition census extended);
      main-file line count recorded before/after.

**Failure and edge cases.** The `sys.modules` rebind means the rendering
module must NOT import the node package (would recreate the 09a inward
hazard in reverse — the rendering module imports SCHEMAS only); a test
patching a moved symbol on the node path — the fresh census says none
exists beyond `LLMBridge`/`open`; if one appears, patch the owning module.

**Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/agent/result_interpretation_agent tests/unit/agent/test_prompt_banned_vocabulary.py tests/unit/nodes/test_node_public_boundary.py tests/unit/workflows/test_model_exploration.py -q > /tmp/09b_c1.log 2>&1; rc=$?` — record counts + wall time.
- [ ] `ruff check` + `ruff format --check`; pyright via the nodeenv node if run locally, else CI-owned (recorded either way).

**Commit boundary.** Structural only; reviewable as "did every byte stay
put while ownership moved?"; no semantic change, no new field, no golden
regeneration.

---

### 11.2 C2 — `InterpretationTaskBlocks` + the TIDMAD declaration + task-free framework templates

**Goal.** The framework prompt code contains no TIDMAD science; TIDMAD's
science reaches the same two system prompts through the typed
caller-supplied VALUE resolved from its own declaration — the parent's
core 09b sentence. Belongs after C1 (bytes settled) and before C3 (new
renderers land on the re-owned template).

**Scope.** `agent/schemas/interpretation.py` (`InterpretationTaskBlocks`;
`InterpretationInput.task_blocks` appended — REC-3 not affected, §3); NEW
`configs/task_interpretation/tidmad.yaml` (§5.3 content, header doctrine);
NEW `agent/prompt_templates/interpretation/task_blocks.py` (adapter +
default constant); `rendering.py`: the two system-prompt constants become
task-free FRAMEWORK TEMPLATES with the §4.1 section splice points; the
builders take `blocks: InterpretationTaskBlocks | None` and render
present sections under framework headers; the `(baseline typically uses
4000)` parenthetical (`:355`-moved) deleted from the volume line (its
sentence now lives in the declaration); the
`HEALTH_FEEDBACK_SYSTEM_INSTRUCTIONS` illustrative example replaced with
the framework-generic `"sample_dispersion_floor_blocking:dispersion=0.0"`
(§5.4 — ruling §0.4 amendment 1; instruction semantics unchanged);
`workflows/model_exploration.py`
(+ the node CLI `main()`) supply
`task_blocks=load_interpretation_task_blocks()`; run() threads
`inp.task_blocks` to the two system-prompt builders; goldens REGENERATED
with every delta declared + attributed (per_model system ×2 variants,
synthesis system, the health-example line in the flag-ON system golden,
the affected user-prompt goldens for the volume line);
the 09a oracle regenerated (prompt shas — declared); banned-vocab test
UPGRADED (§16 census item 1: framework templates must NOT contain the
science tokens or the removed check-id literals; the TIDMAD-ASSEMBLED
prompts MUST carry the migrated science — the
`test_impact_aware_framing_present` cells are REPLACED by this ownership,
not retained). Must NOT change: JSON
output field sets; labels; call labels/count; any deterministic digest
field; Health verdict/action semantics; `configs/task_config.yaml`.
Depends on C1.

**Implementation plan.**
- [ ] Re-read the two constants + builders at the head; produce the
      sentence-accounting table (§5.3) in §22 BEFORE editing: every
      B sentence → its declaration section; every A sentence → kept; every
      reworded framework line → before/after bytes listed.
- [ ] Schema value type + input field (validator: present ⇒ non-empty).
- [ ] Declaration file (verbatim B content per the accounting table) +
      adapter + default constant (fail-closed load).
- [ ] Framework templates + splice rendering (absent ⇒ no header, no
      bytes); builders' signatures gain `blocks` keyword.
- [ ] Replace the health-instruction example with the framework-generic
      signature example (one line; declared golden delta; no other byte of
      that block changes).
- [ ] Workflow + CLI supply the adapter value; pr3/protocol callers
      unchanged (`None`).
- [ ] Regenerate goldens + oracle with the declared-delta table; UPGRADE
      the banned-vocab suite (framework-negative + assembled-positive
      halves, planted offenders both ways; the impact-framing cells
      retired as superseded).

**Validation plan.**
- [ ] Unit: TIDMAD-assembled system prompts contain every migrated science
      sentence exactly once (the accounting table, executable); blocks
      absent ⇒ zero task sections and zero headers (byte-pinned golden for
      the block-less per-model + synthesis system prompts); adapter:
      default path loads the declaration; missing file / malformed YAML /
      unknown key / empty section each refuse with a named error; the
      value round-trips `model_validate(model_dump())`.
- [ ] Unit (04b regression): `{TASK_DESCRIPTION}` substitution unchanged
      (`test_interpreter_prompt_task_config.py` green with moved imports).
- [ ] Census (§16 items 1, 3, 3b, 4, 6): framework rendering module free
      of the enumerated science tokens AND the removed check-id literals
      (planted offender RED); GENERIC surfaces free of task-name tokens
      with the ONE `task_blocks.py` constant exemption; the 3b AST
      confinement guard green with BOTH planted offenders RED (a second
      task constant; an `if "tidmad" in path:` branch); the blocks field
      set == the four keys; exactly ONE adapter reads the declaration path
      (AST census over production modules).
- [ ] Backward-compat: the oracle's declared delta = system-prompt shas
      ONLY (digest byte-identical — blocks change no deterministic field);
      dispatcher labels/call counts unchanged; pr3 preflight green
      (block-less inputs legal).
- [ ] Mutation (recorded): drop one migrated sentence from the declaration
      ⇒ the accounting test RED; render a header for an absent section ⇒
      the omission golden RED.

**Acceptance criteria.**
- [ ] `grep -c` of each enumerated science token over
      `agent/prompt_templates/interpretation/` == 0 while the assembled
      TIDMAD prompt census == the accounting table; goldens regenerated
      once with the full delta table in §22; the declaration is the ONLY
      new YAML and `task_config.yaml` is untouched.

**Failure and edge cases.** A caller passing blocks with all-None sections
(legal — renders nothing); the adapter's default path missing on a
deployment ⇒ fail-closed named error at workflow start (never a silent
science-less TIDMAD prompt); YAML block-scalar trailing-newline handling
recorded in the accounting table (byte discipline); `.replace`-era JSON
braces — templates keep `.replace`/assembly, never `str.format`.

**Verification commands and evidence.**
- [ ] Narrow owner + slice set (ruling §0.4 amendment 4 — NOT the whole
      interpreter directory):
      `.venv/bin/python -m pytest <new C2 owner test> tests/unit/agent/result_interpretation_agent/test_step00_prompt_goldens.py tests/unit/agent/result_interpretation_agent/test_health_prompt_parity.py tests/unit/agent/result_interpretation_agent/test_health_prompt_rendering.py tests/unit/agent/result_interpretation_agent/test_interpreter_prompt_task_config.py tests/unit/agent/result_interpretation_agent/test_step09a_c1a_differential_oracle.py tests/unit/agent/test_prompt_banned_vocabulary.py tests/unit/agent/schemas tests/unit/workflows/test_model_exploration.py tests/unit/scripts/test_pr3_l2p_preflight.py -q > /tmp/09b_c2.log 2>&1; rc=$?`
- [ ] `ruff check` + `ruff format --check`.

**Commit boundary.** Ownership migration only; reviewable as "did the
science move verbatim, is the framework clean, and is every byte delta
declared?".

---

### 11.3 C3 — explicit evidence renderers: identity, diagnosis, secondaries, failures

**Goal.** The 09a-projected evidence becomes LLM-visible through the §6
renderers — the Rev-5 "agent-facing rendering of diagnosis / golden metric
/ secondary metrics / … failures" sentence — as DECLARED additive user-
prompt deltas. After C2 so the additions land on the re-owned template.

**Scope.** `rendering.py`: `render_interpretation_diagnosis_lines`,
`render_secondary_metrics`, `render_failure_counts` (NEW), identity-line
placement (REUSING the tuner renderers — imported); `_build_per_model_prompt`
gains the identity line (from `summary.metric_identity`), the diagnosis
lines, the secondary section (present-when-present) and the failure-counts
block (present-when-present); `_build_synthesis_prompt` gains the run
identity line in its header (from a new `metric_identity` kwarg threaded
from `run()`'s `run_metric_identity`); `run()` threads ONLY existing
computed values (no new computation). Goldens regenerated (user prompts —
declared additive sections; system prompts untouched); oracle regenerated
(user-prompt shas — declared). Must NOT change: ordering, digest fields,
call counts, system-prompt bytes (C2's state), the flag-gated health
sections. Depends on C2.

**Implementation plan.**
- [ ] Re-read the two user-prompt builders + `run()`'s threading sites at
      the head; confirm `ModelRunSummary` carries every input (§2.9).
- [ ] Implement the three renderers per the §6 contracts (typed inputs,
      named absences, direction words via `MetricOrder`/`direction_words`
      only, zero-count omission).
- [ ] Thread into the builders at fixed positions (identity beside the
      score header lines; diagnosis after the volume lines; secondaries +
      failures after the table sections); regenerate goldens/oracle with
      the delta table.

**Validation plan.**
- [ ] Unit (renderers, parameterized over `shipped_spec` /
      `accuracy_like_spec` / `error_like_spec`): identity line words per
      direction; diagnosis lines incl. both named-absence forms;
      secondary lines for scored/refused/unavailable (hand-owned literals);
      failure block for a hand-counted mixed `RecordFailureCounts` incl.
      an unknown future status key; every zero/None omission rule.
- [ ] Unit (builders): a summary with NO diagnosis/secondaries/counts
      renders a prompt containing NONE of the new headers (upgrade-safety
      for legacy-shaped summaries); a fully-evidenced summary renders all
      sections at the pinned positions (golden).
- [ ] Census re-runs: secondaries-never-ordered (09a) green over the new
      code; direction census green (no literal in renderers).
- [ ] Backward-compat: oracle delta = exactly the declared user-prompt
      shas + zero digest changes; PB-0/flag-ON goldens' regeneration diff
      shows ONLY the declared added sections.
- [ ] Mutation (recorded): flip a secondary's direction word source to a
      literal ⇒ census RED; render a number for an `unavailable` secondary
      ⇒ named-absence test RED.

**Acceptance criteria.**
- [ ] Each §6 family has exactly ONE renderer authority (AST census: the
      builders contain no inline diagnosis/secondary/failure formatting);
      every golden delta line attributed to a named renderer in §22.

**Failure and edge cases.** Cached models (no fresh summary) render from
`_stats`-carried counts only when present (09a rule: absent, never
zero-invented); `metric_identity=None` summaries (pre-Step-06 outputs)
render no identity line (named absence covered by the run-level line);
scalar-only summaries hit zero per-file sections (existing presence gates).

**Verification commands and evidence.**
- [ ] Narrow owner + slice set (ruling §0.4 amendment 4):
      `.venv/bin/python -m pytest <new C3 renderer tests> tests/unit/agent/result_interpretation_agent/test_step09a_c1a_differential_oracle.py tests/unit/agent/result_interpretation_agent/test_step00_prompt_goldens.py tests/unit/agent/result_interpretation_agent/test_health_prompt_parity.py tests/unit/agent/result_interpretation_agent/test_health_prompt_rendering.py tests/unit/agent/test_prompt_banned_vocabulary.py -q > /tmp/09b_c3.log 2>&1; rc=$?`
- [ ] `ruff check` + `ruff format --check`.

**Commit boundary.** Additive rendering only; reviewable as "does each
evidence family have one renderer, typed inputs, and a declared golden
delta?".

---

### 11.4 C4 — version-aware prediction track record (interpreter + proposer readers)

**Goal.** No prompt anywhere pools or mislabels v1/v2 prediction
statistics: the §9 renderer replaces the interpreter's stale gain line and
the proposer's `N=<legacy sum>` rendering, and the production pipeline
whitelist surfaces the versioned keys. Closes the named 09a→09b debt
(Q-09a-3 consequence). After C3 (same rendering module, distinct evidence
family); includes the two §2.5 deterministic-string dispositions
(same deterministic-content family).

**Scope.** `rendering.py`: `render_prediction_track_record` (§9);
`_build_synthesis_prompt`: the `:807-811` gain line replaced by the
renderer's lines (new kwargs threaded from `run()`'s existing values —
`inp.*` pools/gains + the computed `pool_sizes`); proposer
`ml_model_proposal_agent.py:1146-1165`: the section body delegates to the
SAME renderer (import from the framework rendering module);
`:1667-1688`: +4 whitelist keys; `interpretation_helpers.py`: delete the
dead `"denoising_score"` display default (`:275`) and reword the timing
advice (`:371-374`) task-free. Tests: UPGRADE
`TestBuildReasoningPromptTrackRecord` (the N-pins become v2-pool pins +
legacy-line pins per §9's four shapes); regenerate
`reasoning_prompt_structured_evidence.txt` (declared), the interpreter
synthesis goldens (declared), the oracle (declared: the synthesis
user-prompt sha + ZERO digest changes). Must NOT change: any digest field
or accounting (09a-frozen); `FalsifiablePrediction`; the proposer's other
sections; pb3 goldens (fixtures carry no prediction keys — verified §2.4;
if regeneration shows movement, STOP: an undeclared consumer exists).
Depends on C3.

**Implementation plan.**
- [ ] Re-read the three reader sites + the proposer test/golden pins at
      the head (fresh line numbers).
- [ ] Renderer per §9 (four shapes, hand-owned literals in its tests).
- [ ] Interpreter synthesis threading; proposer legacy section delegation;
      whitelist +4 keys.
- [ ] The two helper-string dispositions with their named tests.
- [ ] Regenerate the three golden surfaces + oracle with the delta table.

**Validation plan.**
- [ ] Unit (renderer): the §9 four-shape table verbatim as parameterized
      cases (v2-only / legacy-only / mixed / empty) + the `unevaluated`
      guard (a pool-less evaluation changes no rendered N) — hand-owned
      expected strings.
- [ ] Unit (proposer): upgraded N-pins — history `{3,3,0}` legacy +
      empty v2 ⇒ the legacy line with `3 outcome(s)` and NO percentages;
      v2 pool `{3,1,1}` ⇒ `N=5` FROM THE V2 POOL with the version label;
      both-present ⇒ both lines; section-absent gate preserved.
- [ ] Unit (whitelist): the 4 keys surface when present and drop when
      None (the `:1687` filter) — one reachability case through
      `_run_pipeline`'s summary builder.
- [ ] Unit (helpers): a fresh evaluation record always carries `metric`
      (the dead-default removal is safe — pinned); the timing advice
      contains no `segmentation_size` token (census gains the token,
      planted offender RED).
- [ ] Backward-compat: pb3 goldens byte-identical; the interpreter digest
      byte-identical on the oracle (rendering-only); proposer byte golden
      regenerated once with the declared diff.
- [ ] Mutation (recorded): make the renderer sum both pools into one N ⇒
      the mixed-shape test RED; label the legacy line with the v2 id ⇒
      RED.

**Acceptance criteria.**
- [ ] Grep census: `prediction_outcomes_history` is read in the proposer
      ONLY inside the renderer-delegating section and the whitelist (no
      third reader appears); no rendered string pairs a v2 fraction with a
      legacy denominator (the four-shape tests are the proof); the version
      ids appear in renderers ONLY via the schema constants (F-09a-17
      census extended to the rendering module).

**Failure and edge cases.** A digest from a pre-09a chain (legacy-only
shape) renders the honest legacy line — no percentages invented; a
degraded iteration (pools passed through unchanged) renders identically to
its input state; an interpretation dict missing the versioned keys
entirely (oldest digests via the proposer path) ⇒ the legacy-only shape
(`.get` defaults, tested).

**Verification commands and evidence.**
- [ ] Narrow owner + slice set (ruling §0.4 amendment 4; the proposer
      directory runs WHOLE because the proposer is this commit's changed
      authority — that is its owner sweep, not a broad repeat):
      `.venv/bin/python -m pytest <new C4 tests> tests/unit/agent/ml_model_proposal_agent tests/unit/agent/result_interpretation_agent/test_step09a_c1a_differential_oracle.py tests/unit/agent/result_interpretation_agent/test_vocab_feedback.py tests/unit/agent/result_interpretation_agent/test_prediction_evaluation_join.py tests/unit/agent/result_interpretation_agent/test_step00_prompt_goldens.py tests/unit/agent/test_prompt_banned_vocabulary.py -q > /tmp/09b_c4.log 2>&1; rc=$?`
- [ ] `ruff check` + `ruff format --check`.

**Commit boundary.** One evidence family across its two consumer nodes;
reviewable as "is every rendered prediction statistic version-labelled and
version-pure?".

---

### 11.5 C5 — three-task rendering rungs (11-A/11-B), final censuses, node `.md`

**Goal.** The rendering contract proven on the three-task contrast (§8)
and the roadmap's one-axis rungs; every §16 census landed with planted
offenders; the node/module docs current. Last deterministic commit —
documents the settled surface Gate 1 will exercise.

**Scope.** NEW `tests/unit/agent/result_interpretation_agent/
test_step09b_three_task_rendering.py` (parameterized TIDMAD/Pets/DAVIS
over the REAL builders using the 09a C7 pack fixtures + `shipped_spec`;
hand-owned expected prompt fragments; the §8 table as assertions) and
`test_step09b_rung_11a_11b.py` (§8 rung contracts); remaining §16 census
items (2, 5, 7, 8 re-runs; 1/3/4/6 landed in C2) recorded at this head;
`nodes/result_interpretation_agent/result_interpretation_agent.md` +
`agent/prompt_templates/interpretation/` module docs (every flag/default/
placement quoted against merged source — the standing doc-sync rule);
pack `STATUS.md` rows if touched (maturity vocabulary preserved). No
production code beyond what census fixes demand (a census finding here is
a STOP if it implies a production defect). Depends on C4.

**Implementation plan.**
- [ ] Re-read the 09a C7 fixtures + pack governance guards; build the
      three-task prompt cases on the REAL `_build_per_model_prompt` /
      `_build_synthesis_prompt` with blocks = TIDMAD declaration / None /
      None.
- [ ] Hand-own the expected fragments: DAVIS "lower is better" identity
      line; `psnr`-scored + `mae`-named-absence lines; NO
      Impact_Score/Log-of-Mean/PSD/per-file section for Pets/DAVIS; TIDMAD
      science present via blocks only.
- [ ] The 11-A / 11-B rung tests per §8 (line-level diff against
      hand-owned delta sets).
- [ ] Census re-runs + the consolidated census evidence table in §22;
      docs.

**Validation plan.**
- [ ] Unit: the two new suites; `tests/unit/examples` (pack pins
      untouched); the full interpreter directory.
- [ ] Anti-vacuity: the DAVIS expected fragment asserts the direction WORD
      (a TIDMAD-computed twin would fail — the 09a
      hand-computed-smallest-value guard pattern).
- [ ] Backward-compat: zero golden changes (C5 is test/docs only).

**Acceptance criteria.**
- [ ] Every §8 row has a named assertion; 11-A's diff set contains ONLY
      identity/direction lines; 11-B's diff set contains ONLY table bytes;
      every §16 item green with its planted-offender evidence recorded;
      node `.md` quotes each documented behaviour against merged source.

**Failure and edge cases.** Pack fixtures are JSON under `expected/` only
(governance); machine-independent (no absolute paths); the rung inputs
share one builder so the one-axis claim is structural.

**Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/agent/result_interpretation_agent tests/unit/examples -q > /tmp/09b_c5.log 2>&1; rc=$?`
- [ ] `ruff check` + `ruff format --check`.

**Commit boundary.** Evidence + docs only; reviewable as "do three
materially different tasks render correctly through one surface?".

---

### 11.6 C6 — Gate 1 (bounded, §13) + terminal closure

**Goal.** The REQUIRED real-LLM proof (§13's claim, exactly) at the final
executable head, plus ledger/docs closure. Last: Gate evidence must cover
the final executable state.

**Scope.** NEW dual-mode Tier-1 harness
`tests/integration/nodes/test_step09b_interpretation_prompts.py`
(pseudo mode = the deterministic dry-run manifest asserted with the stub
bridge — CI-external, run manually; real mode = the Gate, `@real_run`,
skips without key/artifact); the §13 spec re-confirmed at the head; the
launch (operator-approved unless the implementation authorization grants
it); evidence persisted to
`/home/klz/Data/SIDEREIS_DATA/step09b_gate1_evidence_<YYYYMMDD>/`; §22
closure; then finalize docs → open the formal master-targeting PR → ONE
exact-head CI (no local full suite, no manual dispatch — the standing
validation-economy rules). Depends on C5.

**Implementation plan.**
- [ ] Re-read the §13 spec + the gate standard (`:9-29`, `:127-148`,
      `:444-454`) immediately before launch (roadmap §17.0 item 4);
      confirm the DAVIS fixture names/values (§13.2-B dominance) in the
      spec confirmation.
- [ ] Build the two Gate inputs (§13.2); run the PSEUDO dry-run; commit
      the manifest (labels, counts) as the harness's pseudo expectation.
- [ ] Rehearse the behavioural probes against the planted
      inverted/correct/fabricated synthetic outputs (§13.4
      probe-of-the-probe) — all REDs observed and recorded BEFORE launch.
- [ ] Launch real mode ONCE per approved spec; persist prompts, responses,
      digests, manifest, config, cost.
- [ ] Render the Gate-A digest through the C4 track-record renderer + the
      pipeline summary builder (deterministic, zero calls) and persist the
      rendered section (the §13.3 proposer leg).
- [ ] Decide PASS/FAIL/INCONCLUSIVE from artifacts (§13.4), never exit
      codes; record in §22 + the PR body.

**Validation plan.**
- [ ] The Gate itself (§13.4 criteria), preceded by the mandatory
      probe-of-the-probe rehearsal.
- [ ] Post-Gate: ONLY narrow changed-surface checks (ruling §0.4
      amendment 4) — the harness's pseudo mode + `ruff check` /
      `ruff format --check` on the files the harness/docs commit touched;
      NO repeat of the C5 consolidated closure, NO broad local sweep, NO
      local full suite. Repository-wide regression is owned by the ONE
      exact-final-head PR CI.

**Acceptance criteria.**
- [ ] Gate 1 = PASS per §13.4 with persisted evidence at the named
      destination; the §22 ledger complete; the PR opened with the CI run
      id recorded at the exact final head.

**Failure and edge cases.** Provider outage ⇒ INCONCLUSIVE (relaunch per
spec); artifact path absent on the machine ⇒ the harness SKIPS with the
named reason and the Gate cannot be claimed (never substituted silently);
a label-sequence mismatch vs the dry-run manifest ⇒ FAIL (framework
behaviour drifted, not an LLM-quality question).

**Verification commands and evidence.**
- [ ] Pseudo: `.venv/bin/python -m pytest tests/integration/nodes/test_step09b_interpretation_prompts.py -q > /tmp/09b_gate1_pseudo.log 2>&1; rc=$?` (manual; recorded).
- [ ] Real: the same file with `--real-api-call` (operator-approved launch) `> /tmp/09b_gate1_real.log 2>&1; rc=$?` — verdict from artifacts.

**Commit boundary.** Gate harness + evidence + docs; no production change.

## 12. Per-commit validation ownership (each checkpoint owns ONE property)

| commit | the ONE evidence property it owns |
|---|---|
| C1 | byte-exact structural parity (goldens + oracle unchanged through the move) |
| C2 | ownership migration: task-free framework + verbatim science via blocks, every delta declared |
| C3 | one renderer authority per evidence family; declared additive user-prompt deltas |
| C4 | version-pure prediction rendering across both consumer nodes |
| C5 | three-task + one-axis-rung rendering contract; censuses closed |
| C6 | real-LLM behaviour (Gate 1) + terminal closure |

Broad regression is the ONE exact-final-head PR CI's job (standing rule);
per-commit suites stay targeted (§11 blocks name them).

## 13. Gate 1 — exact design (REQUIRED)

**Standard rows quoted (roadmap §17.0 obligation).**
`docs/gates/gate_testing_standard.md:451` — "New LLM-facing system prompt
| Gate 1" — 09b re-owns both interpreter system prompts: the row matches.
Config: `:16` "real-LLM Gate config = openai_tiered_pro.json" (binding,
2026-08-13; applies to Gate 1). Approval: `:148` "Needs user approval: yes
(real LLM cost)." The 4-GiB/advice interlock (`:33-83`) is inapplicable —
no training subprocess exists in this Gate (LLM-only; no GPU).

**13.1 Claim (aligned to exactly what §13.4 measures — ruling §0.4
amendment 3).** With the re-owned prompts, a REAL LLM produces
schema-valid, non-degraded Phase-1/Phase-2 interpretation such that:

* **(A — TIDMAD, real preserved input)** the task-owned science reaches
  the assembled prompts (construction checks), the structured outputs
  designate the correct best model in TIDMAD's NEGATIVE-score
  higher-is-better regime (btcn −2.3323 over wavenet24 −2.4310 — the sign
  regime where a magnitude-reader inverts; probe P-A1), and the model
  fabricates NO per-file evidence on an input that contains none (probe
  P-A2). **Honest weakening (ruling §4 fallback clause)**: "uses the
  migrated table pedagogy on a real per-file table" is NOT claimable on
  this artifact — it carries no score table anywhere (§2.8) — and that
  correctness class is owned deterministically by the three-task rendering
  fixtures and rung 11-B, not by this Gate.
* **(B — DAVIS, L1 two-model fixture)** the structured outputs designate
  the strictly-dominant lower-mse model as best — lower-is-better actually
  USED, not merely shown (probe P-B1) — with no TIDMAD/per-file leakage in
  either prompts or outputs (probe P-B2); the correct direction words,
  secondary lines (`psnr` higher scored; `mae` a named absence) and
  scalar-only honesty in the PROMPTS are construction checks whose
  deterministic twins live in C5.

The residual real-LLM behaviour — valid structured output, correct
best-model designation under both direction/sign regimes, and
non-fabrication under recomposed prompts — is what deterministic tests
cannot prove, and it is exactly what P-A1/P-A2/P-B1/P-B2 gate.

**13.2 Frozen inputs.**

* **A — TIDMAD (the preserved artifact's iteration-3 shape, §2.8)**:
  summaries = [`bidirectional_gated_tcn` from `run_output_iter_002.json`
  via the REAL builder], cache + 23-entry vocab + prediction memory
  (`{partial: 1}`, gain 0.0) + `previous_proposal` from the iter-2
  digest/proposal; `task_blocks = load_interpretation_task_blocks()`;
  `metric_spec` STAMPED by the harness via
  `tests.helpers.metric_fixtures.shipped_spec()` — the Q-09a-7
  fixture-stamping precedent ("simulated tuner-output writer"), legal
  because the harness is test-fixture construction (not one of Q-09a-6's
  five forbidden production paths) and the records' own
  `metric_result.direction/metric_id` must AGREE with the stamped spec or
  the input contract refuses (§2.8) — the fail-closed clause stays live,
  Q-09b-2. Flag state mirrors the artifact's run.
* **B — DAVIS (L1, fixture-shaped, STRICTLY DOMINANCE-ORDERED)**: TWO
  regression-model summaries (model 1 = the 09a C7 pack fixture's tuning
  output through the real builder; model 2 = a second fixture-authored
  DAVIS-shaped summary in the harness) — two models so Phase-2 synthesis
  FIRES (§0.3-D2a). The fixture is constructed so model 1 is
  UNAMBIGUOUSLY better under `mse` lower: every model-1 round mse is
  strictly lower than every model-2 round mse (total separation, e.g.
  0.0172→0.0170 vs 0.0185→0.0190 — model 2's trajectory also WORSENS,
  so a direction-blind reading calls the wrong model improving), and
  model 1 also has strictly fewer parameters (dominance on the efficiency
  axis too, so ANY best-designation of model 2 is an inversion regardless
  of which axis the LLM reasons on). The two model names are distinct
  tokens chosen for the P-B1 matcher; exact names + values frozen in the
  C6 spec confirmation from the pack fixture. `mse` lower primary;
  secondaries `psnr` scored + `mae` declared-unavailable;
  dispersion-shaped RoundHealth, flag ON; a DAVIS-shaped
  `previous_proposal` predicting `mse` (exercises lower-direction band
  wording in discoveries); empty carried vocab (0 promotions ⇒ 0 dedup);
  `task_blocks = None` (a task without guidance is legal and must not
  inherit TIDMAD prose).

**13.3 Exact call projection (merged-source-derived; §0.3-D2).**

| input | per-model | list_merge | synthesis | dedup | total |
|---|---|---|---|---|---|
| A TIDMAD | 1 (btcn; wavenet24 = stability SKIP marker) | 0 (no active cache hit) | 1 (2 effective types) | 0 (no promotion-ready candidate — pinned by the dry run) | **2** |
| B DAVIS | 2 | 0 | 1 | 0 (empty vocab) | **3** |
| **total** | | | | | **5 calls** |

Active models: A = 2 of 2 (`{bidirectional_gated_tcn,
wavenet24_fullspectrum_ce_coldstart}` — Top-K + Last-N both admit them;
only btcn is RECALLED); B = 2 of 2 (both fresh). The PSEUDO dry-run (same
inputs, stub bridge) is committed BEFORE launch and pins the exact label
sequence — call counts are input-deterministic (§2.3), so any real-run
deviation is a framework regression, not model noise. Token projection:
system prompts ≈2-3k tokens each, user prompts ≈3-8k (TIDMAD tables) ⇒
≈30-60k total tokens; cost well under $1 on `openai_tiered_pro.json`;
runtime projection: single-digit minutes wall time. Pets stays
deterministic-only (§8): its real-LLM failure class (scalar-only +
secondaries under a real model) duplicates B, so adding +3 calls buys no
independent class (parent §17's admission test fails).

**Proposer leg (kickoff-§12 obligation, ZERO extra LLM calls).** The C4
proposer template change joins Gate-1 EVIDENCE deterministically: the
REAL Gate-A digest is fed through the upgraded proposer track-record
renderer (and the pipeline `interpretation_summary` builder) offline, and
the rendered section is PERSISTED with the Gate artifacts — proving a
real-LLM-produced digest renders version-labelled, version-pure statistics
downstream. No proposer LLM call is added: the proposer's residual
real-LLM risk (one labelled-stats section changed inside an otherwise
unchanged prompt) is owned by the C4 deterministic four-shape tests +
byte goldens, and a full proposer pipeline run would add ≥3 calls for no
independent behavioural class.

**13.4 PASS / FAIL / INCONCLUSIVE (from artifacts, never exit codes).**

PASS requires ALL of the following, each read from the persisted evidence:

* **Framework checks**: (1) real label sequence == the committed dry-run
  manifest (call counts are input-deterministic, §2.3 — deviation is a
  framework regression); (2) both digests validate as
  `InterpretationOutput` with `is_degraded == False`.
* **Construction checks (prompt-side, on the persisted transcripts)**:
  (3) A: both assembled system prompts contain the migrated science
  markers (`Impact_Score`, `Linear_Weight`, `Log-of-Mean` — block-sourced)
  and the identity line says "higher is better"; B: prompts contain
  "lower is better", the `psnr` (higher) / `mae` named-absence secondary
  lines and the diagnosis lines, and contain NONE of
  `Impact_Score|Linear_Weight|Log-of-Mean|PSD|per-file score table|file_index`.
  These verify prompt CONSTRUCTION on the real inputs (their deterministic
  twins live in C2/C5) — they support the Gate but are not its residual
  claim.
* **Behavioural probes (output-side, hard — the residual claim; ruling
  §0.4 amendment 3)**:
  * **P-A1 (TIDMAD designation, negative-score higher regime)**: the
    shared deterministic designation matcher over the synthesis-derived
    LLM fields (`take_home_message`, `key_findings`,
    `efficiency_comparison`): every sentence that designates a best/
    better/leading model BY NAME (hand-listed superlative set; sentence =
    newline/period split) must designate `bidirectional_gated_tcn`
    (−2.3323) and NEVER `wavenet24_fullspectrum_ce_coldstart` (−2.4310);
    at least ONE designating sentence must exist (the synthesis schema
    REQUIRES cross-model comparison referencing actual scores — silence
    means the instruction was not followed).
  * **P-A2 (TIDMAD non-fabrication)**: the btcn per-model response's
    `per_file_analysis` and the synthesis `per_file_comparison` contain NO
    file-index designation (regex `file[\s_\-]*(?:index)?[\s#]*\d+`,
    case-insensitive) — the frozen input contains ZERO per-file evidence
    and ZERO file-index tokens in any carried prose (§2.8), so any file
    citation is fabricated.
  * **P-B1 (DAVIS designation, lower-is-better USED)**: the same matcher
    over the same three fields: every best-designating sentence names the
    strictly-dominant lower-mse model and NEVER the dominated one; at
    least ONE designating sentence must exist (the `efficiency_comparison`
    instruction mandates identifying the best architecture, and the
    dominance construction makes any dominated-model designation an
    unambiguous inversion on either axis).
  * **P-B2 (DAVIS output no-leakage)**: the digest's LLM-authored fields
    (`key_findings`, `bottlenecks`, `take_home_message`,
    `per_file_comparison`, `efficiency_comparison`) contain no
    `Impact_Score` / `file_index` / `file <N>` token (per-file-lever
    hallucination screen on a scalar-only task).
  * **Probe-of-the-probe (pre-launch, mandatory)**: the matcher and both
    regex probes are rehearsed against planted synthetic outputs — an
    INVERTED designation (RED), a CORRECT designation (GREEN), a
    fabricated file citation (RED) — committed with the harness, so the
    probes are proven to bite before any real call is spent. No brittle
    free-text exact-phrase gating; the model is never required to repeat
    a specific token (e.g. "Impact_Score") to pass.

A qualitative reading of both outputs is RECORDED as evidence but gates
nothing.

* FAIL: any hard probe or framework/construction check fails, a call
  errors past the bridge envelope with the framework at fault, or the
  label sequence deviates.
* INCONCLUSIVE: provider outage / quota / infrastructure failure before
  evidence lands — relaunch per the same frozen spec.
* Evidence destination:
  `/home/klz/Data/SIDEREIS_DATA/step09b_gate1_evidence_<YYYYMMDD>/`
  (prompt transcripts, raw responses, both digests, the manifest, the
  config used, cost/latency notes) + the §22 record. The preserved
  `step07b_gate1_postrefactor/` inputs are READ-ONLY (never overwritten —
  the standing non-destructive rule).

**Budget statement**: Gate 1 = ONE launch of 5 calls (< $1); Gate 2 = 0;
real training/inference/GPU = 0; within every standing budget.

## 14. Gate 2 — NOT REQUIRED

Quoting the assignment table (`gate_testing_standard.md:446-454`): 09b's
commits are "New LLM-facing system prompt | Gate 1" and "New
loader/renderer (pure Python) | Unit only" rows; nothing matches Gate 2's
real-training rows. The parent's operator ruling (Q-09-4, §17) states it
directly: "Gate 2 — NOT REQUIRED for either child: no real
data/training/inference/subprocess/lifecycle claim changes; the
interpreter is an in-process LLM node with plain JSON persistence covered
by unit + Gate 1's real run. No Step-06/07/08 training Gate is rerun."
Source audit at `fd5557ee` found no new lifecycle claim: 09b touches no
training, inference, data path, Health execution, scorer execution or
workflow lifecycle. **Flip condition** (recorded per roadmap §17.0 item 3):
if implementation somehow acquires a real training/data/subprocess claim,
STOP — that is a scope violation of §0.2 before it is a Gate question.

## 15. Strong-extensibility audit matrix (A–F per new/modified surface)

| surface | A semantic contract | B binding | C discovery | D config ownership | E registration | F vocabulary |
|---|---|---|---|---|---|---|
| `InterpretationTaskBlocks` + `InterpretationInput.task_blocks` | OPEN — a typed VALUE of declarative prose any task can author | caller supplies the value; regime-A adapter resolves TIDMAD's | NONE — the interpreter never discovers task files; the adapter reads ONE named path | task owns the prose in ITS file; framework owns keys/placement; central `task_config.yaml` untouched | none | the four FIXED framework keys; growth is a framework decision (census-pinned) |
| the TIDMAD declaration + adapter | compatibility packaging (self-labelled, §19 → Step 12) | ONE unconditional default constant (the `_composition.py:89` idiom — a constant, not a branch) | n/a | TIDMAD-owned file; external tasks never touch it | none | none |
| framework prompt templates + splice points | framework-owned protocol, task-free (census 1) | function args | n/a | n/a | none | none |
| §6 renderers | render ONLY typed authorities; direction via `MetricOrder` only; ids verbatim, never parsed | function args | n/a | n/a | none | none new (failure keys = existing authority vocabularies; version ids = the schema constants) |
| §9 track-record renderer + proposer whitelist keys | version-labelled rendering of existing digest fields | reads the digest dict the protocol already dumps | n/a | n/a | none | the two existing version ids only |
| three-task fixtures / rungs | L1 contract evidence | test-only | n/a | pack `expected/` JSON only | none | none |

Fixed questions: a fourth out-of-tree task supplies its own
`InterpretationTaskBlocks` VALUE (or reuses the YAML format at its own
path) with **zero SIDERIUS source edits** once Step 10/12 binds the
composition root — nothing in 09b keys on task identity; Step 12 SUPPLIES
the same typed value to the same `InterpretationInput.task_blocks` field —
**no Step-09b public contract needs replacement (required answer: NO,
met)**; unknown/missing semantics fail closed (malformed declaration
refused; spec-less score-bearing inputs already refused by 09a) or render
as NAMED absences (absent blocks/sections/secondaries/diagnosis); no id
spelling is ever parsed for meaning. The ONE task-identity occurrence in
the whole interpreter surface is the self-labelled adapter default-path
constant, and census 3b proves it is a constant, not a branch: it
participates in no conditional, no dispatch, no inference, and a second
task constant/table/branch is RED (ruling §0.4 amendment 2 — the census
and the parent-approved adapter no longer contradict). Verdict: **PASS**
(every §0.2 zero holds by construction + census).

## 16. Structural census plan (parent §18, instantiated — each with a planted offender)

| # | census | owner commit | mechanism |
|---|---|---|---|
| 1 | framework interpreter prompt constants/renderers contain no TIDMAD science tokens (enumerated: `Log-of-Mean`, `Impact_Score`, `Linear_Weight`, `PSD`, the 4000-volume anchor, `segmentation_size`, and the TIDMAD check-id literals removed by amendment 1: `output_diversity_blocking`, `n_unique_int8_values`; "denoising" stays sanctioned as D1 field-name vocabulary per the existing suite's doctrine) — AND the assembled TIDMAD prompts DO contain the migrated set (the `test_impact_aware_framing_present` cells are REPLACED by this framework-negative / TIDMAD-assembled-positive ownership, not retained) | C2 (+C4 token) | UPGRADED `test_prompt_banned_vocabulary.py` halves; planted offenders both directions |
| 2 | direction interpreted only via `MetricOrder` across the interpreter surface INCLUDING `agent/prompt_templates/interpretation/` | C3/C5 re-run | the 09a C3 AST census extended to the new package |
| 3 | GENERIC surfaces (the node package, `rendering.py`, the interpretation schemas) carry ZERO task-name tokens (`tidmad`/`pets`/`davis`), zero task-id parsing, zero task-specific semantic dispatch; the ONE allowed task-token occurrence in the interpreter surface is the self-labelled default-path constant in `task_blocks.py` (the parent-approved bounded adapter — the census must not reject the approved implementation, and the exception is never satisfied by lexical tricks) | C2 | token census with the single named exemption, planted offender in a generic surface |
| 3b | the allowed occurrence is CONFINED: AST guard over `task_blocks.py` proving the task token appears only in ONE module-level string-constant assignment; that constant is referenced by no `If`/`Compare`/`Match`/mapping node and participates in no dispatch, task-id inference or semantic selection; a SECOND task-token constant, a task table, or a branch on the token turns the guard RED | C2 | executable AST/structural guard; two planted offenders (second constant; `if "tidmad" in path:` branch) |
| 4 | task-block section keys == the fixed four | C2 | schema field-list assertion |
| 5 | digest consumers unchanged — no production code branches on the 09b-touched fields to steer workflow behaviour | C5 | grep/AST census over `workflows/ core/ nodes/` (reachability pin) |
| 6 | the TIDMAD declaration is read by exactly ONE adapter; the interpreter imports no task-file discovery | C2 | production-module AST census of the path constant + `yaml` reads |
| 7 | secondaries never enter an ordering call | C5 re-run | the 09a C6 census, unchanged, green over new code |
| 8 | prediction version ids spelled only at the schema authority | C4 | the F-09a-17 single-authority census extended to `rendering.py` + the proposer |
| — | production imports no `examples/` | C5 re-run | existing pack-governance census |
| — | no new `derive_tidmad_metric*` production site | C6 re-run | the 09a C2 production census, unchanged (the Gate harness lives under `tests/`) |

## 17. Test-redundancy / evidence-economy plan

Primary-owner map (one cheapest authoritative owner per invariant; a
second owner only for a distinct failure mode):

| invariant | PRIMARY owner | independent structural owner | Gate-1 owner |
|---|---|---|---|
| structural move parity | goldens + 09a oracle (C1) | node/package import censuses | — |
| science migrated verbatim & complete | the C2 sentence-accounting test | census 1 (token absence/presence) | A-case probes (real LLM still uses it) |
| absent blocks ⇒ omitted | block-less byte golden | — | B-case probes |
| renderer families | per-renderer unit tests (parameterized specs) | census 2/7/8 | — |
| version-pure track record | §9 four-shape tests (renderer) + proposer pins | census 8 | — |
| three-task / direction / scalar-only rendering | C5 parameterized suite + 11-A/11-B rungs | — | B-case (behavioural half only) |
| real-LLM validity under recomposed prompts | — | — | Gate 1 (the ONLY owner) |

Explicitly NOT added: no second golden family duplicating the oracle; no
integration test in CI (the C6 harness is manual, ledger-recorded); no
per-token × per-prompt assertion matrices (the existing single-property
scan pattern is kept); no full-suite runs (ONE exact-final-head PR CI).

**Per-commit execution principle (FROZEN — ruling §0.4 amendment 4):** the
broad interpreter-owner sweep runs locally exactly TWICE — C1 (the whole
prompt surface physically moves, so the move's blast radius justifies it)
and C5 (the ONE consolidated deterministic closure: three-task rendering,
rungs, censuses, interpreter + examples compatibility). C2–C4 run their
NEW owning tests plus the narrow legacy golden/compatibility slices whose
failure class each commit can affect (commands frozen in §11.2-§11.4; the
C4 proposer directory is that commit's changed-authority owner sweep, not
a broad repeat). C6 runs only narrow post-Gate changed-surface checks.
Repository-wide regression = the ONE exact-final-head formal PR CI; no
local full suite; no manual CI dispatch.

Runtime impact estimate, recorded now and measured in §22: ≈+90-130 unit
cases (renderers ≈45, blocks/adapter ≈20, three-task+rungs ≈35, proposer
upgrades ≈10, censuses ≈10) and 6-8 regenerated golden files. Superseded
cells are RETIRED, not stacked: the inverted
`test_impact_aware_framing_present` cells are REPLACED by the C2
framework-negative / TIDMAD-assembled-positive ownership; no independent
failure class is deleted to buy count.

## 18. Risks

* **R-09b-1 prompt-quality regression from recomposition** — the science
  is byte-verbatim but its POSITION changes (field instructions → guidance
  sections). Mitigation: the sentence-accounting table; Gate-1 claim A on
  the real preserved input; declared per-golden diffs the operator reviews
  at C2.
* **R-09b-2 hidden importer breaks at the C1 move** — mitigation: fresh
  import census before moving; narrow re-exports for production importers;
  the boundary/patch-target censuses (09a precedent).
* **R-09b-3 the proposer edit ripples beyond the track record** — bounded
  by scope (§11.4): one section + one whitelist; pb3 goldens pinned
  byte-identical as the tripwire; any movement = STOP.
* **R-09b-4 Gate-1 input refusal** — pre-09a artifact outputs lack
  `metric_spec`; mitigated by the Q-09a-7-precedent stamping (Q-09b-2) with
  the identity-agreement clause left LIVE as the safety check.
* **R-09b-5 blocks-absent TIDMAD run** — a workflow misconfiguration could
  interpret TIDMAD without its science; mitigated: the adapter fails
  closed on a missing/malformed declaration, and the workflow supplies it
  unconditionally (regime-A constant).
* **R-09b-6 golden churn obscures review** — every regeneration carries a
  delta table attributed line-by-line to C2/C3/C4 rules; an undeclared
  delta is a STOP (standing rule).
* **R-09b-7 rendering-module god file** — ≈1,000 lines but ONE
  responsibility (§7); the acceptance is the boundary, and `task_blocks.py`
  keeps the adapter separate; recorded for the post-09b audit if it grows
  mixed concerns.

## 19. Debt triage (A / B / C) and post-09b audit inputs

### 19.1 A — blockers before 09b

None found. (The Gate-1 input question is a design decision, Q-09b-2, not
a blocker.)

### 19.2 B — forward constraints (recorded, NOT absorbed)

| finding | owner |
|---|---|
| proposer prediction-AUTHORING grammar (constrain new predictions to the bound metric id; per-sample forms only with evidence) — deferred by 09a's own note in `prediction.py` | Step 10 |
| `PROPOSAL_REASONING_PROMPT` / `PROPOSAL_COMMIT_PROMPT` carry the proposer's OWN task science ("signal denoising" `:284`, "256 denoising bins" `:341`) — the proposer node's prompt surface is not 09b's | Step 10/12 (proposer-side task blocks) |
| `evaluation.py` per-check-NAME threshold tables | Step 10 (parent §12, unchanged) |
| `core/resume.py:436` / chain-incumbent / dashboard direction literals | Step 10 (unchanged) |
| production secondary transport (Q-09-7 = B) | Step 10 (unchanged) |
| `vocab_link_confirmations` never carried in production | Step 10 (unchanged) |
| scale-naive `boldness` | Step 10+ (unchanged) |
| the TIDMAD interpretation declaration + adapter (created HERE, self-labelled compatibility packaging) + the tuner's regime-A metric binding | Step 12 |
| D1/cache display vocabulary (`per_file_analysis`, `per_file_comparison`, "Worst denoising score" labels, `training_psd_segments` schema names) — rendered-beside-identity per the 07b precedent, renaming is not rendering work | post-Step-12 vocabulary cleanup, if ever |
| ~~`HEALTH_FEEDBACK_SYSTEM_INSTRUCTIONS`'s illustrative TIDMAD check-id example~~ — **FIXED in 09b C2** (operator ruling §0.4 amendment 1: replaced with a framework-generic example; no known task-specific check-id literal remains in the generic interpretation prompt templates after 09b) | 09b C2 |

### 19.3 C — later cleanup + hotspots recorded for the post-09b repo-wide audit

* the dead tune→interp protocol (no production caller — parent §19,
  unchanged);
* the node CLI `main()` ad-hoc entry (unchanged);
* the synthesis workspace-string interpolation hazard (`:721-758` region,
  golden-pinned — unchanged);
* **hotspots for the scheduled audit (inputs, not 09b work)**: the
  proposer node — 2,372-line single file with DUPLICATED legacy/pipeline
  prompt paths reading the same interpretation fields at two sites
  (`:1106-1108` + `:1672-1673`; `:1146-1165` + `:1681-1688`) — the exact
  two-readers shape C4 must edit in both places;
  `nodes/interpretation_helpers.py` still mixes discoveries/vocab/policy;
  `run()` at 886 lines (LLM phases inline — acceptable per parent §13a,
  but the largest remaining method on this node);
  `workflows/model_exploration.py` at 3,137 lines.

## 20. Step-12 compatibility

The composition root will supply, for interpretation, exactly THREE typed
values this design already declares as inputs: the bound `metric_spec`
(09a), the `task_description` (04b) and the `task_blocks` VALUE (09b). The
regime-A adapter and its default-path constant are the ONLY compatibility
plumbing, quarantined in `task_blocks.py` and self-labelled — Step 12
replaces the CALL SITE, not the contract; the YAML format is packaging an
external task MAY reuse but never must (it can construct the value
directly). No interpreter loader/registry exists to swap; the four section
keys are per-surface framework protocol, not per-task vocabulary; renderers
key on typed evidence and universal direction words. **Does Step 12 merely
SUPPLY `InterpretationTaskBlocks`? YES. Would it need to replace a Step-09b
public contract? NO.**

## 21. Operator questions — ALL RESOLVED (final ruling 2026-08-19)

| id | question (as posed at rev 1) | RULING |
|---|---|---|
| **Q-09b-1** | proposer track-record scope (§0.3-D3): does C4 edit BOTH proposer reader sites per the 09a closeout assignment? | **YES — RESOLVED**: C4 owns exactly the legacy track-record section + the pipeline interpretation-summary whitelist and NOTHING else in proposer semantics; prediction-authoring grammar, `PROPOSAL_REASONING_PROMPT`/`PROPOSAL_COMMIT_PROMPT` task science and proposer policy remain later debt (§0.4) |
| **Q-09b-2** | Gate-1 input construction: stamp `metric_spec` on the PRE-09a preserved outputs via the Q-09a-7 fixture-stamping precedent? | **YES — RESOLVED**: test-fixture construction; production outputs unmodified; no production derivation site; record-borne identity must still agree; disagreement still fails closed; no GPU re-production (§0.4) |
| **Q-09b-3** | golden reading (§0.3-D1): C1 byte-exact, C2–C4 declared+attributed deltas under the frozen parent? | **YES — RESOLVED**: the frozen parent governs; every changed golden carries its owning rule + before/after delta + same-commit regeneration; an undeclared delta is a STOP; no full-byte-identity claim after C1 (§0.4) |

Open operator questions: **0**.

## 21a. Final adversarial consistency pass and freeze record (operator ruling §8 — 22 attacks)

Each attack re-read against the FULL amended design at freeze; verdicts:
PASS (the design already holds), CORRECTED (fixed by a §0.4 amendment), or
FINDING (recorded with owner).

1. *TIDMAD science remaining in generic framework prompts?* PASS after
   C2 — census 1 (enumerated science tokens + the removed check-id
   literals) with planted offenders; the last known task-specific
   check-id literal is removed by amendment 1 (CORRECTED — rev 1 had kept
   it as a residual).
2. *Task science moved into a central framework task table instead of
   blocks?* PASS — one task-owned YAML with path-identity (08b doctrine);
   `task_config.yaml` untouched; census 6.
3. *Any task-name semantic branch?* PASS — census 3 (generic surfaces
   zero task tokens) + 3b (no `If`/`Compare`/`Match`/mapping touches the
   one constant).
4. *The one bounded adapter becoming a hidden central task catalog?*
   PASS (CORRECTED wording by amendment 2) — census 3b turns RED on a
   second task constant, a task table, or a branch; the constant resolves
   a default path and nothing else.
5. *Task-block keys growing per task?* PASS — census 4 pins the four
   fields; growth is a framework decision (parent §9-F).
6. *Renderers re-deriving metric / diagnosis / Health semantics?* PASS —
   typed authorities in; the diagnosis line is IMPORTED from the 07b
   authority; direction words only via `MetricOrder` (census 2); health
   rendering retained verbatim.
7. *Secondary evidence reaching ordering?* PASS — the 09a
   secondaries-never-ordered census re-runs plus the C3 behavioural
   inertness probe.
8. *Scalar-only Pets/DAVIS receiving per-file instructions?* PASS — the
   pedagogy is block-owned (absent for both), table sections are
   presence-gated, the framework field instruction carries the
   named-absence rule; C5 fixtures + Gate P-B2/P-A2.
9. *Lower-is-better DAVIS rendered or interpreted backwards?* PASS —
   rendering owned by C5 fixtures + rung 11-A (deterministic);
   INTERPRETATION owned by Gate P-B1 on the strictly-dominant fixture
   (CORRECTED — rev 1 had only prompt-presence checks).
10. *TIDMAD v1/v2 prediction history pooled or mislabeled?* PASS — the §9
    four-shape contract with hand-owned literals; C4 mutations (one-N
    pooling RED; v2-label-on-legacy RED); version ids only via the schema
    constants (census 8).
11. *`unevaluated` rendered as partial?* PASS — structurally in neither
    pool (09a); the §9 guard test; the Gate-A input's own prediction is
    genuinely `unevaluated` (the artifact's unparseable metric string,
    §2.8) — live evidence at the Gate.
12. *Proposer C4 edit leaking beyond the two approved reader surfaces?*
    PASS — scope pins: pb3 goldens byte-identical tripwire; the grep
    census (the prediction-field reader set stays exactly the renderer
    delegation + the whitelist); movement = STOP.
13. *Proposer prediction-AUTHORING semantics entering 09b?* PASS — §0.2
    exclusion + §19.2 row (Step 10); Q-09b-1 ruling restates it.
14. *Gate-1 PASS criteria proving only prompt construction?* CORRECTED by
    amendment 3 — P-A1/P-A2/P-B1/P-B2 are hard OUTPUT-side behavioural
    probes with pre-launch planted-output rehearsal; construction checks
    remain but no longer carry the claim; the unclaimable table-USE clause
    is weakened honestly in §13.1 with its deterministic owner named.
15. *Gate call count drifting from the input-deterministic five-call
    manifest?* PASS — §2.3 (no LLM response feeds call-count decisions);
    the committed dry-run manifest; deviation = FAIL; `list_merge = 0`
    and `dedup = 0` frozen for the inputs (2 carried candidates, each
    seen once — §2.8).
16. *Production importing `examples/`?* PASS — pack-governance census
    re-runs at C5; the Gate harness lives under `tests/`.
17. *Another `derive_tidmad_metric*` site appearing?* PASS — the 09a
    production census re-runs at C6; the harness stamps via
    `tests.helpers.metric_fixtures` (Q-09b-2).
18. *A new interpreter-specific plugin/registry/loader ecosystem?* PASS —
    one adapter function + one constant; no discovery, no registry; the
    interpreter never reads task files.
19. *`rendering.py` acquiring mixed ownership rather than one coherent
    responsibility?* GUARDED — single responsibility (prompt
    construction); the ledger records the final inventory + LOC; mixed
    ownership at implementation = STOP (§7, ruling §7); re-inspected by
    the scheduled post-09b audit.
20. *Duplicated tests proving the same failure class at multiple layers?*
    CORRECTED by amendment 4 — broad sweep exactly twice (C1/C5);
    C2–C4 narrow owner+slice commands frozen; superseded
    `test_impact_aware_framing_present` cells REPLACED; no independent
    failure class deleted.
21. *Step-10 secondary/evaluation/resume work leaking into 09b?* PASS —
    Q-09-7 pins re-run (no evaluator/loader/binding/persistence/
    transport); the whitelist additions surface PREDICTION fields the
    protocol already transports; resume untouched.
22. *Step 12 needing to REPLACE rather than SUPPLY the
    `InterpretationTaskBlocks` contract?* PASS — §20: the composition
    root supplies the same typed value; required answer NO, met.

**Freeze record.** Q-09b-1..3 = YES, RESOLVED (§0.4); strong-extensibility
verdict PASS (§15); A blockers NONE (§19.1); implementation shape = ONE
09b child PR, C1→C2→C3→C4→C5→C6 (§11); Gate 1 REQUIRED (one bounded
five-call launch, §13), Gate 2 NOT REQUIRED (§14); the four ruling
amendments applied (§0.4); per-commit validation economy frozen (§17);
the repo-wide structural/test-topology audit remains scheduled AFTER 09b
merge / BEFORE Step 10 and is NOT performed here (§19.3 records its
inputs). Zero `SOURCE-INSPECTION REQUIRED` markers; zero unresolved
`Q-09b-*`; zero material contradictions; every implementation box `[ ]`;
the §22 ledger empty. **Implementation has NOT started.**

## 22. Live implementation ledger (scaffold — empty at REVISION 2 — FROZEN)

*(filled per commit during implementation; every §11 box is `[ ]` at
freeze; nothing below may be written before the corresponding work ran,
and every entry carries test counts, wall time and log paths)*

### 22.0 Implementation-context provenance
*(branch, base SHA, design-confirmation record — at implementation start)*

### 22.1 C1 — structural move
*(import census; before/after line counts; oracle/golden parity evidence)*

### 22.2 C2 — task blocks + TIDMAD migration
*(sentence-accounting table; declared golden deltas; census 1/3/4/6 evidence)*

### 22.3 C3 — evidence renderers
*(renderer test counts; declared user-prompt deltas)*

### 22.4 C4 — version-aware track record
*(four-shape evidence; proposer pin upgrades; declared deltas)*

### 22.5 C5 — three-task rungs + censuses + docs
*(rung evidence; consolidated census table)*

### 22.6 C6 — Gate 1 + closure
*(dry-run manifest; launch approval; artifacts; PASS/FAIL/INCONCLUSIVE;
PR + exact-head CI id)*

### 22.7 Findings (F-09b-*)
*(numbered, with dispositions — the 09a pattern)*
