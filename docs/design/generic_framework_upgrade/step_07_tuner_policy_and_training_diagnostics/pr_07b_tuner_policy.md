# Step 07 — PR 07b: Tuner policy on the golden metric + planner/reflector rendering (Gate 1) — detailed design

| Field | Value |
|---|---|
| Parent | `../step_07_tuner_policy_and_training_diagnostics.md` (revision 2, FROZEN 2026-08-15) §8.3 — the 07b acceptance contract; §2.2/§2.3 census; §12.1/§12.2/§12.6 invariants; §18 OD-S7-6 (deferred to this child); §20 WHAT/HOW line |
| Roadmap | §7a (couplings, target, Rev 5 policy half), §22.6 (persistence ≠ prompt visibility; consumer split item 5), §22.7 (no hidden multi-objective), §22.8, §22.9a (Pets accuracy↑ / DAVIS mse↓ golden metrics via the PR0 `declared/metric_*.json`), §22.12 row 07b, §22.13 (Gate corpus breadth); §15.1 step-7 row (`§7a`) |
| Design base | `787afa08` (master; 07a MERGED `65804b3d` + finalizer) — every source line below was re-read at this head |
| Depends on | 07a MERGED (record fields `training_history` / `training_diagnosis`, `TrainingDiagnosis` schema, Stub/pseudo multi-epoch histories, hidden-key sets); Step 06 MERGED (`MetricSpec.direction`, `run_metric` bound at run scope); Step 00 goldens PB-1/PB-2/WF-1/WF-2/REC; PR0 packs (`declared/metric_*.json`) |
| Decomposition | ONE PR. Frozen scope = six commits **C1 → C6** (§15); **C7 / C7d** were ADDED later by the operator scope amendment (2026-08-16) and are NOT part of the frozen decomposition — §15 carries their checklist separately. Frozen six: replay oracle · P1-order + validity · P1-scale + attempt-transition disposition · P2 authority-rendered task blocks + OD-1 · P3 owned rendering deltas + bridge surfaces · rungs / packs / docs / Checkpoint E + Gate 1 |
| Gates (ORIGINAL, frozen 2026-08-15) | Gate 1 **REQUIRED, ≥ 2 rounds** (P3 changes LLM-facing SYSTEM prompt bytes; parent §11 row 07b; OD-20-6) · Gate 2 **NOT REQUIRED** (no execution-launch change; flip: any training/inference/scoring launch or execution change → Gate 2) |
| Gates (as RUN) | Gate 1 **PASS** twice — pre-refactor §14.6b, post-refactor §14.11 · Gate 2 **PASS** §14.13. Gate 2 was NOT required by the frozen disposition above and was not triggered by its flip; it was **ADDED by the operator C7 scope amendment (2026-08-16)** as regression evidence that the structural decomposition preserved the real execution path. The original disposition is preserved above exactly as frozen. |
| Design status | **FROZEN — OPERATOR APPROVED 2026-08-15 — Revision 2.** Revision 1 reviewed (APPROVE WITH TARGETED REVISION); revision 2 applied the three blockers (unified bridge / WF contract, `MetricOrder` complete API + signed-delta semantics, reflector diagnosis-only transport) and three corrections (Checkpoints B / D explicit, Gate-1 posture frozen from source with the rounds-vs-iterations distinction and the "executed" definition, B-07b-2 without task-type phrasing) plus one final non-architectural consistency pass at freeze (§3.1 file-table wording; §7 / §10 Gate-1 round-vs-iteration wording); §16 records the operator's dispositions of Q-07b-1..9.
| Implementation status | **COMPLETE — READY FOR OPERATOR REVIEW (2026-08-16).** C1–C6 landed the frozen 07b scope; **C7 / C7d** (tuner node structural decomposition) were ADDED by operator scope amendment 2026-08-16 and are recorded in §14.9–§14.9.5. §14 is the ledger and is populated end to end (§14.0–§14.13). Final **executable** HEAD `cb1a885a`; final **PR** HEAD `307fa0ce917c0afbd6ee5425fae7ef902b267019` — everything between the two is documentation and gate-advice JSON only, no executable production change. PR **#216**; exact-head CI **31989125173 SUCCESS** (ruff · ruff format · pyright strict · pytest); clean tree. Terminal validation at `cb1a885a`: 9,787 passed / 3 skipped / 0 failed from a clean tree. **Not merged** — merge is the operator's. |

`[ ]` = not done · `[x]` = done **and** verified with recorded evidence.

**What this child FREEZES (HOW) — operator approved 2026-08-15 (revision 2)**: the ONE order authority
and its consumer list (§3.2), the per-rule classification of every
scale-sensitive policy (§3.3), the invalidated-result outcome mechanism
(§3.4), the `AttemptTransition` / `AttemptDecision` disposition (§3.5), the
per-block P2 rendering table — which authority owns which rendered token
and which literals stay with a recorded gap (§3.6), the file-by-file P3
declared byte deltas (§3.7), the diagnosis rendering content at both LLM
surfaces (§3.8), the bridge / kwarg surface deltas (§3.9), the OD-1
disposition (§3.10), the test-infra shape (§3.11), the example-pack
projection (§3.12), the rungs (§6), the Gate plan (§10) and the stop
conditions (§13). **What stays the parent's**: the semantic requirements
(§8.3 P1-order / P1-scale / P1-validity / P2 / P3, Checkpoints 0–D, Gate
disposition) — this child instantiates them and does not reinterpret them.
**NOT frozen**: exact test-file decomposition, helper names, source line
numbers (reading aids at `787afa08`; re-read before each commit).

---

## 0. Pre-design source audit (at `787afa08`)

Every fact below was read at the cited line (three parallel read-only
audits + the author's spot checks of every load-bearing line). The parent's
§2.2/§2.3 census (at `03225ac9`) is CONFIRMED; only line numbers moved
(07a added ~70 lines to the tuner and ~30 to `agent/prompts.py`).

### 0.1 Metric-direction consumers in the tuner (`nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py`, 7,249 lines)

| # | Site | Line | Exact expression | Consumer / role |
|---|---|---|---|---|
| 1 | `_best_trial_winner` | `:1558` | `max(candidates, key=lambda r: r["denoising_score"])` over `is_valid_candidate ∧ is_trial ∧ memory.time_mode=="trial"` `:1548-1555` | trial winner → skip gate `:4364-4372`, bypass gate `:5147-5157`, formal inheritance (`_apply_mode_override_chain`) |
| 2 | `_should_skip_formal` | `:1594-1597` | `winner is None → True`; disabled sentinel `threshold == float("-inf") → False`; **`winner["denoising_score"] < threshold`** | skip gate; banner hardcodes `<` `:4384-4390` |
| 3 | `_should_bypass_formal_time_budget` | `:1615-1617` | disabled sentinel `threshold == float("inf") → False`; **`winner["denoising_score"] >= threshold`** | bypass gate; banner hardcodes `>=` `:5163-5176` |
| 4 | `_resolve_formal_comparison_thresholds` | `:1636`, `:1660-1663` | gates off → `(None,None,None,"gates_disabled")`; **bootstrap `float("-inf")` ×3 + `"negative_infinity_bootstrap"`**; else `(ref, ref + skip_min_delta, ref + bypass_min_delta, "restored_valid_formal_incumbent")` | resolved ONCE per run `:4153-4158`; persisted `run_config` `:4168-4175`, output `:6511-6516`; deltas = `agent_input.skip_formal_min_delta` (default `-1.0`, docstring "dB"), `agent_input.bypass_formal_time_budget_min_delta` (default `0.0`) — `agent/schemas/hyperparam_tuning.py:1530-1556`; `-inf` / `+inf` documented as the operator's disable values |
| 5 | planner score-table incumbent | `:4469-4473` | `max(_records_with_table, key=denoising_score)` → `score_table_md` into `brain.plan` `:4500` | which comparison table the planner SEES |
| 6 | collapse penalty | `:2041` (`_apply_degeneracy_reaction` `:1984`) | `score_results["denoising_score"] = penalty_score` on a degenerate FORMAL round; value = `agent_input.degenerate_penalty_score` (`None` → nulls the score; float "e.g. `-5.0`" — schema `:1602-1620`); `_merge_score_validity_failure` `:2200-2218` classifies any non-finite / None as collapse regardless of direction | record's `denoising_score` (planner-visible); status becomes `failed_mode_collapse` |
| 7 | reflection block | `:5787-5900` | baseline substring `"baseline" in exp_id` `:5794-5796`; `best_score = max(all_scores)` `:5799`; best record `max(successful, key=…)` `:5800-5802`; **rank `sorted(all_scores, reverse=True)`** `:5803-5808`; `worst_score = min(all_scores)` `:5848`; `score_range = best − worst` `:5849-5857`; **5 % band `score_threshold = best − 0.05·range`** `:5858-5860`; `is_more_efficient = current >= score_threshold ∧ (fewer params ∨ fewer epochs)` `:5861-5878`; **`is_new_best = current > best`** `:5890-5891`; `baseline_score` `:5885-5887` | `reflection_context` → `brain.reflect` `:5930` (WF-2 pins the 23 context keys) |
| 8 | **LOSS rank (lower-is-better, NOT a metric consumer)** | `:5817-5824`, `:5895` | `sorted(all_same_loss_finals)` ascending → `same_loss_loss_rank`; `min(same_loss_finals)` → `best_same_loss_final_loss` | must NOT flip with metric direction |
| 9 | finalization (5 tracks) | `:6407-6445` | `successful_records` = `status=="success" ∧ finite denoising_score` `:6449-6456`; `top_record`, `formal_top_record`, `valid_top_record` (`is_valid_candidate`), `valid_formal_top_record`, `valid_trial_top_record` — all `max(…, key=denoising_score)` | `HyperparamTuningOutput` projection `:6520-6555` (`best_*`, `best_formal_*`, `best_valid_*`, `best_valid_formal_*`, `best_valid_trial_*`) |
| 10 | `run_metric` | bound `:3923` (`derive_tidmad_metric(run_profile, run_deliverable_spec)`); read ONCE at `:5501` (`sandbox.evaluate_metric`) | **`run_metric.spec.direction` is never read** — direction reaches only the persisted `metric_result` payload `:5985` |
| — | non-score `max`/`min` (excluded) | `:1218, :1226, :1457, :1954, :2619, :2997, :3554, :4637-4639` | round indices / counts / budgets — not direction consumers |

**23 direction-bearing expressions in total** (items 1–7, 9), of which 21
must consume the order authority and 2 (item 8) must not.

### 0.2 `AttemptTransition` / `AttemptDecision` and the `resolved_action` hazard (OD-S7-6)

| Fact | Evidence |
|---|---|
| `AttemptTransition(StrEnum)` `PROCEED / RETRY_ATTEMPT / TERMINATE_RUN` | `:364-376` |
| `AttemptDecision` frozen dataclass; `admission_refused` classmethod; its own docstring names the hazard ("round-scoped, written five levels deep inside scoring, never reset between attempts") | `:379-414` |
| **Production consumers: ZERO** — repo-wide grep hits only `tests/unit/agent/tune_ml_hyperparam_agent/test_control_boundary.py:30,31,423-447` and design docs | grep |
| `RoundDecision` + `_decide_round_outcome` ARE wired (`:416-450`, call `:6316-6321`) and consume the outer `resolved_action` | |
| `resolved_action` in `run()`: declared round-scoped `:4345` (`while` loop `:4334`); written ONLY inside the health-gate branch `:5577` (gates on) / `:5604` (gates off), 7 nesting levels below `run()` (`for attempt :4399 → try :4407 → try :5385 → try :5461 → if anchor_map_data :5462 → if health_gate_enabled :5544`); read `:5595` and `:6319` | an attempt that leaves before `:5544` (admission refusal, OOM / time skip, exception) lets `:6319` read the LAST SCORED attempt's action; comment `:4337-4344` documents "Stays CONTINUE when all attempts crash" |

### 0.3 The prompt surface (`agent/prompts.py`, `agent/llm_bridge.py`)

| Family | Lines (`agent/prompts.py`) | Content | 07b disposition |
|---|---|---|---|
| template mechanics | `PLANNER_PROMPT` `:10-221` (SYSTEM, plain str; tokens `{TASK_DESCRIPTION}` `:14`, `{available_losses_block}` `:176`, `{SCORE_COMPARISON_TABLE}` `:215` substituted by `str.replace` in `LLMBridge.plan` `:864-871`); `REFLECTOR_PROMPT` `:223-310` (SYSTEM; one token `:267`, substituted in `reflect` `:949-952`); planner USER f-string `:1272-1307` (`get_planner_user_prompt` `:938-1307`); reflector USER `:1326-1395` (`get_reflector_user_prompt` `:1310`) | | the substitution seam already exists — P2/P3 tokens follow the SAME mechanism |
| **direction wording (P3, OWNED deltas)** | SYSTEM planner `:12` "maximize the `denoising_score`", `:37` "maximize score"; SYSTEM reflector `:244` "Best Score So Far", **`:245` "GOOD if … HIGHER than the best score so far"**, **`:247` "BAD if … LOWER"**, `:298-300` "beats the best score" / "≥95% of the best score"; USER reflector `:1352` "denoising_score rank … (1 = best)" | higher-is-better literals | rendered from the handle (§3.7) |
| metric-name literal | SYSTEM `:12, :68, :108, :233, :245`; USER `:1350, :1352, :1378`; `_CONDENSED_KEYS` `:857` (record key, NOT prose) | `denoising_score` = the RECORD FIELD name (frozen D1) and the prompt's metric noun | field name stays (records carry it); metric IDENTITY (`spec.id`) rendered additionally (§3.7) |
| "score = validation" compensating text | planner SYSTEM `:106-113` (`### TRAINING vs VALIDATION — CRITICAL:` + over/under-fitting reading rules), adjacent `:60-63`; reflector SYSTEM `:231-240` (`### CRITICAL — GAP ANALYSIS`), `:279-282`; reflector USER `:1377-1379` (⚠ NOTE), `:1384` | the pre-07a compensator | replaced by rendered `TrainingDiagnosis` lines (§3.8) — declared P3 delta |
| task-content literals (P2) | roster `:16-21` (5 models + one-liners), `:1293` (6 names `punet \| fcnet \| transformer \| wavenet \| rnn \| gated_fno`); BASELINE RULE `:23-28`; COLLAPSE ADVICE `:67-93` (gate names `output_diversity` `:72`, `amplitude_collapse` `:74`, class-127 `:73`, focal `alpha=0.5`/`gamma=2.0` `:76-77`, lr ladder `:78-79`, AdamW `:80-81`, finite-negative `:90-93`); EFFICIENCY 5 % `:95-104`, `:64-65`, reflector `:288-307`, USER `:1344`; anchors 4000 / 200 `:169-170`, reflector `:271-275`, 20× `:158-159`; loss list `:182-184`, USER `:1071-1085`, `:1305`; CH1/CH2 + log-space `:186-217`, reflector `:250-265`; `[B, 256, T]` / `[B, T]` / HYBRID `:1068-1087` (force-model branch keyed by `plugin_loader.get_output_type` `:1046-1067`) | | per-block table §3.6 |
| history filter | `_CONDENSED_KEYS` `:852-866`, `_CONDENSED_MEMORY_KEYS` `:867-873`, `_PLANNER_HIDDEN_RECORD_KEYS` `:890-892` (four keys after 07a), `_planner_visible` `:895-904`, `_truncate_memory_history` `:907-935`; comment `:884-889` "07b RENDERS selected facts with direction wording" | | 07b renders diagnosis THROUGH an owned renderer while the raw keys stay hidden (§3.8) |
| bridge | `LLMBridge.plan` `:765-793` (25 params; `task_description` `:791`, `score_table_md` `:790`, `registry` `:793`); `LLMBridge.reflect` `:921-926` (`exp_id, hypothesis, actual_results, reflection_context`); labels `tuner.planner` `:919`, `tuner.reflector` `:960-967`; NO force_model branch in the bridge (SYSTEM prompt identical for all `force_model`) | tuner calls `:4476-4516` (`memory_history` positional + 24 kwargs) and `:5930` (4 positional) | §3.9 |

### 0.4 Step-00 goldens and existing pins

| Surface | Fact | 07b consequence |
|---|---|---|
| PB-1 (`pb1_planner_auto_system.txt` 13 608 B, `pb1_planner_auto_user.txt`, `pb1_planner_force_punet_user.txt`), PB-2 (`pb2_reflector_system.txt`, `pb2_reflector_user.txt`) — `tests/unit/agent/llm_bridge/goldens/`; fixture surface `test_step00_prompt_goldens.py:51-201` (`_HISTORY_3` 3 punet records with scores `-2.91 / None / -2.55`; `planner_fixture_kwargs`; `_REFLECT_ACTUAL_RESULTS`; `_REFLECT_CONTEXT` incl. `rank:1`, `is_new_best:True`, `best_score_so_far:-2.91`, `training_psd_segments:200`, `baseline_psd_segments:4000`) | direction/metric bytes at: pb1 system **3, 28**, 59, 99, 102; pb1 user 9 (epochs "higher values are clamped" — NOT a metric direction), 34/61/88 (fixture JSON); pb2 system **11, 22, 23, 25**, 63, 76, **79**, 80, 88; pb2 user 6, **25, 33**, 68 | the P3 declared delta list (§3.7) is written against THESE lines |
| WF-1 `wf1_plan_kwarg_key_set.json` (22 kwarg names — `plan()` kwargs, `memory_history` positional), `wf1_plan_call_round1_surface.json`; WF-2 `wf2_reflect_call_surfaces.json` (`actual_results_keys` = 9; `reflection_context_keys` = 23) | | §3.9 declared-additive deltas |
| **OD-1** `test_pb1_full_window_boundary_is_the_deferral_line` `:247-270`: the condensed branch of `_truncate_memory_history` iterates the `_CONDENSED_KEYS` / `_CONDENSED_MEMORY_KEYS` **frozensets** → dict key ORDER, hence `json.dumps(indent=2)` bytes for a > 3-record history, are not byte-stable across processes; the ≤ 3-record PB-1 fixture never enters that branch; deferral "owned by the step-07a predecessor fix" → 07b | §3.10 closes it |
| existing template pins: `tests/unit/agent/test_prompt_banned_vocabulary.py` (imports live constants; `denoising_score` intentionally NOT banned); `test_planner_prompt_task_config.py:45-72` (`{TASK_DESCRIPTION}` / `{SCORE_COMPARISON_TABLE}` presence, pre-T4a residue absence, **`test_denoising_score_field_name_preserved` — a PRESENCE pin on `denoising_score` in `PLANNER_PROMPT`**); `test_llm_bridge.py:824-850`; `test_planner_resource_budgets.py:36-59`; source-slice scans (`test_preflight_inconclusive.py:183-203`); `tests/unit/workflows/test_step04b_task_description_single_source.py` (residue assertions SCOPED to headings, whole-prompt absence explicitly a test-design error) | | the P2 absence pins follow the scoped-slice pattern; the field-name presence pin STAYS true |
| selection pins: `test_delta_gates.py` (defaults; resolver; edges; sentinels; anti-phantom parametrized over VALUES `[5.5763, 5.5762667, 0.0]`, direction NOT parametrized), `test_formal_launch_decision.py` (12-row MATRIX; "never both open" sweep; 3 real-`run()` tests), `test_valid_trial_winner_drives_formal.py`, `test_valid_candidate_selection.py`, `test_gate_integration.py` (`_merge_score_validity_failure` parametrized `[None, -inf, +inf, nan]` → collapse), `test_degeneracy_handling.py` (`-2.5` hardcoded as "worse"), `test_tuning_agent.py:297, 376-423, 1945-2030`, `test_step06_c2_tuner_metric_binding.py` (a `lower` handle bound at run scope reaches the SCORING seam — no comparison flip asserted; literal `"higher"` at `:70`), `test_control_boundary.py:423-461` (`AttemptDecision`) | none direction-parametrized | §9 dispositions |
| **replay corpus**: NO checked-in `run_output_*.json` with `all_records` (`tests/unit/core/fixtures/step00_replay_workspace/.../run_output_iter_001.json` has none) | | Checkpoint 0 CAPTURES it (§5, C1) |

### 0.5 Landed authorities a renderer / policy may read (§12.6 "render only what a landed authority owns")

| Authority | Surface | Owns |
|---|---|---|
| `execute_tools/evaluation_metric.py` | `MetricDirection = Literal["higher","lower"]` `:110`; `MetricSpec` `:355-387` (`id`, `direction`, `aggregation`, `transform`, `transform_params`, `references`, `scoreability`; `frozen`, `extra="forbid"`; **NO human-readable name / units / bounds / worst-value field**); `EvaluationMetric.spec` `:489-490`; `derive_tidmad_metric_spec` (direction `"higher"` `:573`, `transform="log"`, references `("anchor_map","raw_baseline","ground_truth")`) | metric identity + ORDER direction; the tuner binds it at `:3923` |
| Step-06 fixtures | `test_step06_c6_stage_b_direction_rung.py::_direction_only_metric` `:79-87` (shipped spec `model_copy(update={"id": "step06_tidmad_denoising_score_lower", "direction": "lower"})`); `_contrast_metric` `:109-117`; `test_step06_c2_tuner_metric_binding.py::_ContrastHandle` + `_bind_once` monkeypatch of `derive_tidmad_metric` `:73-107` | the ready-made lower-direction fixtures |
| 07a schemas | `TrainingDiagnosis` fields (`agent/schemas/training_diagnosis.py:68-135`: `state`, `validation_state`, `comparability`, epochs, `truncated`, `train_first/last/min(+epoch)`, `validation_first/last/min`, `best_validation_epoch`, degradation (+`_rel`), `validation_degraded_after_best`, gap (+`_rel`), `train_trend`, `validation_trend`, `flat_rel_tol`); `TrainingHistory` (`execute_tools/training_history.py:123-158`) | the diagnosis facts 07b may render |
| Dataset profile | `DatasetConfig.num_files / segments_per_file / psd_segment_length` (`dataset_config.py:42-48`), `ChannelIdentity` `:338-379`, `ValueEncoding.num_classes` `:406-409`; run-bound `resolve_dataset_profile()` `:596`; the tuner holds `run_profile` | anchors (full scope = `num_files × segments_per_file` = 4 000 under TIDMAD) |
| Model-I/O contract | `TensorContract.render_shape()` `:206-213` → `"[B, 256, T]"`, `.render()` `:215-217`; `ModelIOContract.output_semantic` `:262-282`, `class_cardinality` `:295-309`; `workflows/task_config.py::run_bound_model_io_contract` `:196-225`; the tuner holds `run_model_io` | output-contract shape tokens |
| HealthGate effective config | `execute_tools/health_checks/config.py::load_health_gates_config` `:300-324` → `cfg.health_gates[*].id / gate_role / checks[*].name`; `materialize_effective_config` `:414-503` (`{workspace}/health_checks_effective.yaml`); registry `all_registered()` `registry.py:53`; TIDMAD checks `output_diversity`, `output_std`, `amplitude_collapse` (blocking) + 3 recording (`configs/health_checks.yaml:26-147`) | gate / check NAME tokens |
| Loss authority | `LossConfig.loss_type: Literal["focal","focal_cw","ce","smooth_l1","custom"]` (`models_format_sandbox.py:637`), field defaults `alpha=0.5`, `gamma=2.0` `:640-641`; `CLASSIFICATION_LOSSES` / `REGRESSION_LOSSES` `:384-387` | built-in loss list + focal defaults |
| Model roster | `MODEL_REGISTRY` insertion order `punet, fcnet, transformer, wavenet, rnn, gated_fno` (`models_sandbox.py:732-739`); `BUILTIN_OUTPUT_TYPES` `:745-752`; owned `ml_models/{model}/description.md` for all six built-ins (title line, e.g. "# PUNet — Positional U-Net") via `get_model_description` | roster NAMES (+ owned titles); the prompt's one-line roster descriptions have NO landed owner |
| Task config | `configs/task_config.yaml` — `task_description`, `forward_contract` (+`task_type`); **no metric / score / direction field** (comment `:64-67` names `metric_name` as out of scope) | already substituted (`{TASK_DESCRIPTION}`) |
| Genericity contract | Seam 4 "not yet generic … direction-sensitive policy consumers (Step 07b under the Q2 lettering / D1)" `:159-162`; Seam 3 task pack PLACEHOLDER `:134-146` | 07b closes the Seam-4 line; the un-owned prose blocks are Seam-3 gaps |
| Step 01 §13.4 residue rule | `step_01_proposer_hypothesis_space.md:1180-1187, :1266-1281` — residue assertions SCOPED to derived blocks + a POSITIVE presence assertion; whole-prompt absence forbidden | the shape of every 07b rendering pin |

### 0.6 What the parent already decided (consumed, not re-derived)

One order authority = `MetricSpec.direction`, ordering semantics only, no
second direction field, no rename (D1 not authorized); scale-sensitive rules
classified per rule from source (generic / declared / derived /
inapplicable-fail-closed), never generic by sign-flip; the invalidated
outcome (never a better incumbent under either direction) is frozen, its
mechanism is the child's; `AttemptTransition` wire-or-remove from source,
never a third state; P2 renders only landed-authority facts, EXACT bytes
under TIDMAD, un-owned facts stay TIDMAD-rendered-from-current-owner or
are omitted for a contrast declaration with the gap recorded; P3 = the ONLY
authorized PB-1/PB-2 byte deltas, declared file-by-file before the change;
Gate 1 ≥ 2 rounds, Gate 2 not required; `run()` gains no branching; the
loss rank stays lower-is-better and untouched.

### 0.7 Operator review of revision 1 (2026-08-16) — corrections applied in this revision

Verdict: **APPROVE WITH TARGETED REVISION — NOT YET FREEZE.** Decomposition,
the six commits, the P1 census, the per-rule scale classification, the
three-track coverage and the Gate disposition stand. Six corrections:

| # | Class | Correction | Where |
|---|---|---|---|
| 1 | **BLOCKER** | The bridge / WF contract was self-contradictory (§3.9 listed only `metric_spec` while C4 adds `task_render` and C5 counts 24 kwargs). ONE final contract: `plan(..., task_render, metric_spec)` (WF-1 22 → 23 at C4 → 24 at C5); `reflect(..., metric_spec, training_diagnosis)`; `task_render=None` and `metric_spec=None` both FAIL CLOSED at a real render (no silent TIDMAD fallback) | §3.9, C4, C5 |
| 2 | **BLOCKER** | `MetricOrder` API incomplete: `worst(items, key)` and `toward_worse(ref, magnitude)` are now first-class members of the ONE authoritative table (no "opposite-direction order" construction); `toward_better(ref, signed_delta)` semantics frozen — `signed_delta` is a coordinate on the better-direction axis (positive = toward better, negative = toward worse) | §3.2, §3.3 |
| 3 | **BLOCKER** | Reflector transport hole (`history_meta` was rendered but not transported): the reflector renders the `TrainingDiagnosis` ONLY (it already carries `comparability`); the planner renders diagnosis + the record's `training_history.objective_kind`; no additional `TrainingHistory` transport; renderer signature `render_training_dynamics_line(diagnosis, objective_kind: str \| None)` | §3.8, C5 |
| 4 | SHOULD FIX | Checkpoints B and D made EXPLICIT and mapped item-by-item to the parent (§6 → Checkpoint B; §8 → Checkpoint D); C6 acceptance enumerates Checkpoints 0 / A / B / C / D / E | §6, §8, C6 |
| 5 | SHOULD FIX | Gate-1 health posture source-audited and FROZEN now (not at readiness): `--no-health_gate_enabled` (records self-describe `health_gate_enabled=False` → `classify_candidate_health` returns VALID for successful finite-score records, `candidate_eligibility.py:169-175`) + `--enable_chain_incumbent_formal_gates` + `--num_iterations 2 --max_rounds 2`; "executed" DEFINED as "the decision helpers are reached and their resolved values / verdicts are recorded", not "both mutually exclusive actions become True" | §0.5, §7, §10, Q-07b-8 |
| 6 | SHOULD FIX | B-07b-2 no longer claims "classification / regression phrasing" — `MetricSpec` owns no task type; the rung asserts metric id, direction words, diagnosis lines and P2 task tokens as available | §6 |

Gate-1 posture audit (for correction 5): `HealthGateMode = Literal["blocking",
"observe_only"]` (`agent/schemas/hyperparam_tuning.py:48`) is a SEPARATE axis
from the subsystem switch `health_gate_enabled` (`:52`, DS4–DS6);
`classify_candidate_health` (`execute_tools/health_checks/candidate_eligibility.py:148-200`)
returns INVALID for non-success / non-finite records, VALID when the record
self-describes `health_gate_enabled=False` (`:169-175`), UNKNOWN when a
required blocking gate is missing / not run, INVALID on a failed blocking
check or `would_invalidate_under_production_policy` (`:194-198`) — so under
pseudo training (no deliverables → the peeks fail) BOTH `blocking` and
`observe_only` yield INVALID / collapse (the Step-06 Gate-1 experience),
while `--no-health_gate_enabled` yields VALID stub successes with NO
production health semantics modified. `sdsc_submission_scripts/run_chain.sh`
forwards `--is_pseudo_training` (`_chain_common.sh:378/485`),
`--no-health_gate_enabled` (`:307/505`), `--enable_chain_incumbent_formal_gates`
(`:316/557`) and `--num_iterations` (`:280`); iteration 2 of a chain receives
the reconstructed valid formal incumbent as `current_run_best_formal_score`
(`workflows/model_exploration.py:2654-2655, :2772-2774`) — the
`restored_valid_formal_incumbent` (non-sentinel) reference; iteration 1 uses
the bootstrap sentinel. The skip helper is reached at every formal-round
boundary when `force_formal_round` is on (`:4365-4372`, default True); the
bypass helper is reached ONLY when a formal round's time check is infeasible
(`:5147-5157`) — not guaranteed under pseudo training, hence NOT a Gate-1
PASS requirement (covered deterministically by B-07b-1 / 1s).

---

## 1. Capability / final effect

> Every ordering decision the tuner makes about the golden metric — trial
> winner, skip / bypass orientation and their disabled sentinels, the
> bootstrap sentinel, the planner's score-table incumbent, the reflector's
> best / rank / new-best / efficiency band, and the five `best_*`
> finalization tracks — flows from ONE order authority derived from
> `run_metric.spec.direction`; every scale-sensitive rule is classified and
> resolves from its declared owner (or fails closed) with every TIDMAD value
> unchanged; a pathologically invalidated result never becomes a better
> incumbent under either direction; the two consumer-less attempt-transition
> types are removed and the `resolved_action` hazard is recorded with an
> owner; the planner / reflector task-content blocks whose facts have a
> landed owner render from that owner byte-exact under TIDMAD; the
> direction wording, the metric identity and compact `TrainingDiagnosis`
> lines render from the handle and the 07a record — the ONLY authorized
> PB-1/PB-2 deltas — through owned, boundary-tested renderers, with WF-1 /
> WF-2 exact except declared additive keys; the OD-1 condensed-branch byte
> instability is closed.

The precise invariants:

1. **One order authority.** `metric_order.MetricOrder` (name is this
   child's) is constructed from `run_metric.spec` once per run and is the
   ONLY place `direction` is interpreted; the 21 ordering sites of §0.1
   call it; the 2 loss-rank sites do not. No `higher_is_better` flag, no
   per-site literal, no rename.
2. **Replay parity under `higher`.** Every selection, threshold, sentinel,
   reflection-context value and `best_*` output is deep-equal to the
   Checkpoint-0 replay oracle captured BEFORE the first production edit.
3. **Strict ordering inversion under `lower`.** Identical records, only
   `direction` flips → the ordinal consumers invert exactly and the loss
   rank does not (rung B-07b-1).
4. **Scale rules classified, TIDMAD values unchanged.** §3.3 table; each
   rule's classification is executable (a declared rule reads its owner, an
   inapplicable rule fails closed with a recorded reason) — rung B-07b-1s.
5. **Invalidated results never win.** A `failed_mode_collapse` /
   non-finite / `None`-scored record enters no incumbent selection under
   either direction (§3.4).
6. **No third state.** `AttemptTransition` / `AttemptDecision` removed;
   retry / round semantics byte-unchanged (§3.5).
7. **P2 byte-exact under TIDMAD; contrast renders differently.** Rendered
   task blocks come from landed authorities; the template constants carry
   no literal for a rendered token (scoped absence pins); un-owned facts are
   recorded gaps, not invented fields.
8. **P3 = the declared deltas and nothing else.** PB-1/PB-2 regenerated in
   the same commit with the three-part note; the diff is exactly §3.7's
   list.
9. **Persistence ≠ visibility, still.** The raw `training_history` /
   `training_diagnosis` / `metric_*` keys stay hidden at both renders; what
   the LLM sees is the owned renderer's output (boundary tests).
10. **`run()` gains sequencing calls only**; the reflection block and the
    finalization selection become typed, independently testable boundaries
    with replay parity.

---

## 2. Source evidence for the design decisions

§0 tables. Frozen semantics: parent §8.3, §12.1/§12.2/§12.6; roadmap §7a,
§22.6 item 5, §22.7, §22.12 row 07b, §22.13. Gate table: standard `:371`
(quoted in parent §11). Residue rule: Step 01 §13.4 / §9.5.

## 3. Scope

### 3.1 Files expected to change (categories fixed; names are this child's)

```text
execute_tools/metric_order.py                NEW — MetricOrder: the ONE order authority derived from MetricSpec.direction
                                             (is_better / is_at_least / best / worst / rank / worst_sentinel /
                                             best_sentinel / toward_better / toward_worse — the §3.2 table) — pure,
                                             importable by the tuner today and by
                                             the D1 peripheral consumers later (never imported by execute_tools scoring)
nodes/ml_hyperparameter_tune_agent/
    ml_hyperparameter_tune_agent.py          P1: order-authority consumers (§0.1 items 1-7, 9); scale-rule resolution;
                                             extracted `_build_reflection_context(...)` and `_select_best_records(...)`
                                             typed boundaries (parity by replay); AttemptTransition / AttemptDecision
                                             REMOVED; run() sequencing only
agent/schemas/hyperparam_tuning.py           docstring wording of skip/bypass/penalty inputs generalized ("in the golden
                                             metric's units — dB under TIDMAD"); NO schema field change; NO default change
agent/prompt_templates/tuner/rendering.py    NEW — owned renderers: metric direction/identity block, TrainingDiagnosis
                                             lines (planner history + reflector current attempt), authority-rendered task
                                             blocks (roster names, anchors, output-contract shapes, loss list, gate names)
agent/prompts.py                             PLANNER_PROMPT / REFLECTOR_PROMPT gain tokens for the rendered blocks; the
                                             P3 wording deltas; `_truncate_memory_history` deterministic key order (OD-1);
                                             planner user prompt gains the diagnosis block (from the record, before hiding)
agent/llm_bridge.py                          plan(..., task_render=None, metric_spec=None) / reflect(..., metric_spec=None,
                                             training_diagnosis=None): substitution of the new tokens (declared additive
                                             kwargs — the ONE contract of §3.9; WF-1 22 → 23 (C4) → 24 (C5); WF-2 additive;
                                             both None → fail closed at a real render)
tests/unit/agent/tune_ml_hyperparam_agent/goldens/   NEW sel1_* replay goldens (Checkpoint 0); WF-1/WF-2 regenerated
                                             additively (three-part note); PB-1/PB-2 regenerated with the P3 deltas
tests/unit/...                               new families (§9); selection pins UPGRADED direction-parametrized;
                                             template absence pins; boundary tests at BOTH renders; rungs
examples/{tidmad,oxford_iiit_pet,davis_future_prediction}/README.md, STATUS.md   policy / rendering rows (L1 for B/C)
docs/design/genericity_contract.md           Seam 4 "not yet generic" line closed for the tuner consumers; Seam 3 gap list
nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.md, docs (README index rows, this ledger, parent §8.3
                                             status, roadmap §15.1/§22.12 at Checkpoint E)
```

### 3.2 The ONE order authority and its consumers (FROZEN on approval — instantiates P1-order)

```text
MetricOrder(spec: MetricSpec)                       # execute_tools/metric_order.py — the ONE authoritative API
  direction                       = spec.direction                    ("higher" | "lower")
  is_better(a, b)                 = a > b   if higher  else a < b
  is_at_least(a, b)               = a >= b  if higher  else a <= b
  best(items, key)                = max(...) if higher else min(...)  (ties: FIRST item wins — today's max() semantics)
  worst(items, key)               = min(...) if higher else max(...)  (ties: FIRST item wins — today's min() semantics)
  rank(values, x)                 = 1 + #(v strictly better than x)   (== today's sorted(reverse=True).index(x)+1 under higher)
  worst_sentinel                  = -inf if higher else +inf          (the "nothing is worse" value)
  best_sentinel                   = +inf if higher else -inf          (the "nothing is better" value)
  toward_better(ref, signed_delta)= ref + signed_delta if higher else ref - signed_delta
        # signed_delta is a COORDINATE ON THE BETTER-DIRECTION AXIS in the metric's units:
        # positive = toward better, negative = toward worse (so a declared skip margin of -1.0 moves the
        # threshold to the WORSE side under BOTH directions)
  toward_worse(ref, magnitude)    = toward_better(ref, -magnitude)   (magnitude >= 0; the efficiency band uses it)
```

Every member interprets `direction` in this ONE class; no consumer may
construct a second `MetricOrder` with the opposite direction to obtain the
worst (that would be a second interpretation site).

Consumers (each rewired to the authority; under `higher` byte-identical
results — replay oracle):

| §0.1 site | Today | 07b |
|---|---|---|
| 1 trial winner `:1558` | `max(key=score)` | `order.best(candidates, key=score)` |
| 2 skip gate `:1594-1597` | `threshold == -inf → disabled`; `winner < threshold` | `threshold == order.worst_sentinel → disabled`; `order.is_better(threshold, winner)` (winner strictly WORSE than the threshold) |
| 3 bypass gate `:1615-1617` | `threshold == +inf → disabled`; `winner >= threshold` | `threshold == order.best_sentinel → disabled`; `order.is_at_least(winner, threshold)` |
| 4 bootstrap `:1660-1661` | `-inf ×3` | `order.worst_sentinel ×3` (source string unchanged: `"negative_infinity_bootstrap"` is a PROVENANCE label — under `lower` it names a `+inf` bootstrap; the label is kept for record compatibility and its meaning documented: "the worst-value bootstrap") |
| 4 thresholds `:1660-1663` | `ref + delta` | `order.toward_better(ref, delta)` — see §3.3 row 1 for why the OPERATOR's `-inf` / `+inf` disable convention is preserved under both directions |
| 5 planner table incumbent `:4469-4473` | `max` | `order.best` |
| 7 reflection `best_score`, `best_record`, `rank`, `worst_score`, `is_new_best` | `max / sorted(reverse=True) / min / >` | `order.best / order.rank / order.worst / order.is_better` |
| 9 finalization 5 tracks | `max` | `order.best` (per track, same filters) |
| skip / bypass banners `:4384-4390`, `:5163-5176` | hardcoded `<` / `>=` | the banner renders the order's operator symbol (`<` under higher, `>` under lower); a formatting-only change on stdout, not an LLM surface |

Excluded by design: the LOSS rank (§0.1 item 8) — lower-is-better by
definition of a loss, unrelated to the golden metric — pinned by a test that
flips the metric direction and asserts the loss rank does NOT move.

`is_valid_candidate` (record validity from HealthGate evidence) is
direction-free and untouched.

### 3.3 Scale-sensitive rules — per-rule classification (FROZEN on approval — instantiates P1-scale)

The parent's frozen boundary: no scale-sensitive rule is claimed generic
merely because its sign flips. Each rule below is source-audited and
classified (i) framework policy with a metric-independent definition, (ii)
task/policy-owned DECLARED parameter, (iii) DERIVED from a metric-defined
scale, (iv) inapplicable → fail closed. Under TIDMAD every resolved value is
identical (replay oracle).

| Rule (source) | Today | Classification | 07b resolution | TIDMAD value |
|---|---|---|---|---|
| 1. `reference + skip_min_delta` / `reference + bypass_min_delta` (`:1660-1663`; inputs `skip_formal_min_delta=-1.0`, `bypass_formal_time_budget_min_delta=0.0`, docstrings say "dB") | additive margin, higher-is-better | **(ii) DECLARED** — the operator declares the margins IN THE GOLDEN METRIC'S UNITS for the campaign (the schema field docstrings say "dB" because TIDMAD's metric is log-space; the unit belongs to the bound metric, not to the framework); the ORIENTATION is the order authority's | `threshold = order.toward_better(reference, delta)`: higher → `ref + delta`; lower → `ref − delta`. The operator's documented disable values keep their meaning under BOTH directions: skip `delta=-inf` → `ref − (−inf) = +inf` under lower = the worst sentinel (disabled); bypass `delta=+inf` → `ref − inf = −inf` = the best sentinel (disabled). Docstrings re-worded "in the golden metric's units (dB under TIDMAD)"; defaults UNCHANGED (a production-default change is out of scope) | `ref − 1.0`, `ref + 0.0` — identical |
| 2. bootstrap sentinel `-inf` (`:1660`) | worst value under higher | **(i) generic** — "no incumbent yet = the worst possible reference" is an ORDER fact | `order.worst_sentinel` | `-inf` — identical |
| 3. disable sentinels (`:1595`, `:1615`) | `-inf` (skip) / `+inf` (bypass) | **(i) generic** — skip disabled ⇔ threshold is the worst value; bypass disabled ⇔ threshold is the best value | compare with `order.worst_sentinel` / `order.best_sentinel` | identical |
| 4. 5 % efficiency band `score_threshold = best − 0.05·(best − worst)` (`:5848-5860`) + `is_more_efficient` (`:5861-5878`) | fraction of the observed RANGE toward the worse side | **(i) generic, metric-independent DEFINITION** — the band is normalized by the OBSERVED range of this run's scores (scale-free by construction; no metric constant enters); the constant `0.05` is FRAMEWORK policy (the prompts state "5 %" — same constant, one named module constant `EFFICIENCY_BAND_FRACTION`) | `range = |best − worst|`; `threshold = order.toward_worse(best, 0.05·range)` (higher → `best − 0.05·range`; lower → `best + 0.05·range`); `is_more_efficient = order.is_at_least(current, threshold) ∧ (fewer params ∨ fewer epochs)`; single-score case (`range None`) → `threshold = best` (unchanged) | identical |
| 5. collapse penalty `degenerate_penalty_score` (`:2041`; schema `:1602-1620`; `None` default) | `None` → nulls the score; float "typically large negative" → "strictly below healthy" | **(ii) DECLARED with an executable validity guard** — the float is the operator's, in the metric's units and orientation; the OUTCOME the parent freezes (an invalidated result never becomes a better incumbent) does NOT depend on the value: a penalized record has `status="failed_mode_collapse"` and every incumbent selection filters `status=="success"` (`:6449-6456`, `:5790-5793`) or `is_valid_candidate` (`:1548`, `:6425`) — source-proven (§3.4). Residual hazard: the PLANNER sees the penalized value in history; under `lower` a "large negative" penalty would READ as excellent. 07b adds a fail-closed startup check: a finite float penalty is accepted only if it is on the WORSE side of the metric's worst observed/declared reference — but no such reference exists at startup, so the honest executable rule is: **a finite float penalty is admissible under `higher` as today (the documented convention); under `lower` a finite float penalty is REFUSED at startup with a recorded reason (`degenerate_penalty_score` semantics are declared for a higher-is-better metric; use `None`) — inapplicable/fail-closed (iv) for that direction until Step 08 owns validity semantics** | `None` default → identical; a configured `-5.0` under `higher` → identical |
| 6. `is_new_best = current > best` (`:5890-5891`) | ordering | (i) via `order.is_better` | identical |
| 7. baseline `"baseline" in exp_id` (`:5794-5796`, prompt `:25`) | naming convention | not scale-sensitive; framework convention (exp_id naming) — unchanged | identical |
| 8. loss rank (`:5817-5824`, `:5895`) | ascending / min | not a metric rule — unchanged | identical |
| 9. `_json_safe_reference` non-finite → `None` (`:1666-1694`) | storage image | unchanged (works for `+inf` too) | identical |

**Stop check (parent):** no rule needed a new task-config field, a new
schema field or a `relative_tolerance`-style invention; row 5 fails closed
under `lower` rather than reinterpreting a value.

### 3.4 Invalidated-result outcome (FROZEN — instantiates P1-validity)

The frozen OUTCOME: a pathologically invalidated result never becomes a
better incumbent under either direction. Mechanism (source): (a) status —
`_apply_degeneracy_reaction` marks the round `failed_mode_collapse`
(`:5967-5968` record status) and every `best_*` track requires
`status=="success"` + finite score (`:6449-6456`); the reflection block's
`successful` filter requires `status=="success"` (`:5790-5793`); (b)
validity — `_best_trial_winner` and the `valid_*` tracks require
`is_valid_candidate` (HealthGate evidence); (c) non-finite / `None` scores
are collapse per `_merge_score_validity_failure` (`:2200-2218`) and are
filtered by (a). 07b keeps (a)–(c) exactly and PINS them direction-
parametrized (rung B-07b-1s: a collapse record with a penalty that would
be "best" under the bound direction never wins any track, never becomes the
trial winner, never the reflection best). Validity semantics stay Step
08's; nothing here folds validity into the order authority.

### 3.5 `AttemptTransition` / `AttemptDecision` — REMOVE (FROZEN on approval — disposes OD-S7-6)

Source (§0.2): zero production consumers; the round-outcome consumer
`_decide_round_outcome` is already wired and reads the OUTER
`resolved_action`; wiring the two types "through an extracted
attempt-transition boundary that also resets `resolved_action` per attempt"
would CHANGE round outcomes in the crash-after-a-scored-attempt case (today
`:6319` reads the last SCORED attempt's action; a per-attempt reset would
read `CONTINUE`) — a retry/round-semantics change the parent forbids in 07b
("if wired, retry/round semantics provably unchanged" cannot be met while
also fixing the hazard). Therefore: **REMOVE** `AttemptTransition`,
`AttemptDecision` (`:364-414`) and their tests (`test_control_boundary.py::TestAttemptDecision`),
delete the roadmap-named "third state"; RECORD the `resolved_action`
hazard as a known defect with a proposed fix and an OWNER (a dedicated
round-semantics correction requiring an operator decision on the intended
outcome — NOT 07b/07c) in §14 and the parent §8.3 status; retry / round
semantics byte-unchanged (existing round/attempt tests + replay oracle are
the evidence). `RoundDecision` / `_decide_round_outcome` stay.

### 3.6 P2 — authority-rendered task blocks (FROZEN on approval)

Rule: a token renders from a landed authority ONLY; under TIDMAD the
rendered bytes equal today's literal (PB-1/PB-2 unchanged by P2 — asserted
by regenerating NOTHING for P2: the goldens must still pass after C4); a
contrast declaration renders differently (rung B-07b-3); the template
constant no longer contains the literal for any RENDERED token (scoped
absence pins). Facts with NO landed owner stay as literals with the gap
recorded (Seam 3 task pack, Step 08 health semantics, Step 12) — never an
invented field.

| Block (`agent/prompts.py`) | Rendered token(s) | Authority | Byte-exact under TIDMAD | Disposition |
|---|---|---|---|---|
| model roster names (USER `:1293` `punet \| fcnet \| transformer \| wavenet \| rnn \| gated_fno`) | `{BUILTIN_MODEL_ROSTER}` | `MODEL_REGISTRY` built-in insertion order (`models_sandbox.py:732-739`) — the six built-ins in exactly that order (plugins are NOT part of the roster today and stay out) | `" \| ".join(...)` == the literal ✓ | RENDER |
| SYSTEM roster block with one-liners (`:16-21`, five models) | — | model NAMES owned (registry / `description.md` titles); the one-line descriptions have NO owner | — | KEEP literal; gap recorded (Seam 3 task pack: per-model roster line) |
| segment anchors — full scope "4000" (`:169-170`, reflector `:271`, `:274-275`), "200 vs 4000", "20× less data" (`:158-159`) | `{FULL_SCOPE_SEGMENTS}` (= `num_files × segments_per_file` = 4 000), `{DEFAULT_TRIAL_SEGMENTS}` (= `round(default trial_portion × full)` = 0.05·4 000? **NO** — the schema default `trial_portion=0.02` (`hyperparam_tuning.py:825-830`) gives 80, not 200; "200" is the 0.05-portion example, i.e. `TrialConfig`'s example, not a default) | profile (`run_profile.dataset`) owns 4 000; **200 has NO landed owner as a default** | 4 000 ✓; 200 ✗ | RENDER the full-scope number from the profile; the "200"/"20×"/"0.05 to 0.2" illustrations KEEP their literal form as an EXAMPLE sentence keyed off the rendered full scope ("e.g. 200 of {FULL_SCOPE_SEGMENTS}") — bytes identical under TIDMAD; gap recorded (example-portion prose, Seam 3) |
| output-contract shape in the force-model branch (`:1070` "CLASSIFIER (output [B, 256, T])") | `{OUTPUT_CONTRACT_SHAPE}` | `run_model_io.output.render_shape()` (`model_io_contract.py:206-213`) — the tuner already holds `run_model_io` | `"[B, 256, T]"` ✓ | RENDER (bridge/prompt builder receives the rendered string; a `None` contract → the branch omits the shape token — the pre-Step-03 adapter shape) |
| regressor `[B, T]` / HYBRID lines (`:1077`, `:1083`) | — | the regressor's output shape is task semantics (denoising regressor emits the input's shape) — owned by Step 03's DQ-3 catalogue, not by a run-bound authority | — | KEEP literal; gap recorded (Step 03 catalogue / Seam 3) |
| built-in loss list (`:182-184` "(`focal`, `focal_cw`, `ce`, `smooth_l1`)"; USER `:1071-1085`, `:1305`) | `{BUILTIN_LOSS_TYPES}` (+ per-semantic subsets) | `LossConfig.loss_type` Literal minus `custom` (`models_format_sandbox.py:637`) in declaration order; `CLASSIFICATION_LOSSES` / `REGRESSION_LOSSES` `:384-387` for the classifier / regressor subsets | order `focal, focal_cw, ce, smooth_l1` ✓ (subset lines: `ce/focal/focal_cw` at `:1071` — the CURRENT literal order is `ce, focal, focal_cw`; the render must reproduce it → the subset renders `sorted(...)`? No: `CLASSIFICATION_LOSSES` is a set; the render uses the LITERAL ORDER of the Literal filtered by the set = `focal, focal_cw, ce` ≠ today's `ce/focal/focal_cw` → **byte delta** → NOT rendered in P2; recorded as a P3-adjacent decision: KEEP the subset literals, render only the four-built-ins list at `:182-184` where the order matches) | RENDER `:182-184`; KEEP `:1071-1085`, `:1305` (gap: subset ordering prose) |
| focal defaults `alpha=0.5`, `gamma=2.0` in collapse advice (`:76-77`, `:86-87`) | `{FOCAL_ALPHA_DEFAULT}`, `{FOCAL_GAMMA_DEFAULT}` | `LossConfig` field defaults (`:640-641`) | `0.5` / `2.0` ✓ | RENDER |
| gate-name tokens in collapse advice (`:72` `output_diversity`, `:74` `amplitude_collapse`) | `{GATE_OUTPUT_DIVERSITY}`, `{GATE_AMPLITUDE_COLLAPSE}` — the check NAMES | the EFFECTIVE health config (`load_health_gates_config` → `checks[*].name`); the tuner materializes it at startup | names identical ✓ | RENDER the NAME tokens; the surrounding explanatory prose (class-127 mode collapse, PSD-amplitude wording) KEEPS its literal form — Step 08 owns generic health semantics; when the effective config lacks a check of that name the sentence is OMITTED (recorded) |
| lr ladder, Adam→AdamW, "finite negative is not collapse" (`:78-93`) | — | framework tuning heuristics; `:90-93` is a sign-direction claim ("below the anchor ceiling") | — | KEEP; `:90-93` is re-worded by P3 (direction) — see §3.7 |
| CH1/CH2 + log-space (`:186-217`), reflector `:250-265` | — | TIDMAD metric prose; `MetricSpec` owns id/direction/aggregation/transform/references but NO prose | — | KEEP literal; gap recorded (Seam 3 / Step 12 metric prose) |
| BASELINE REFERENCE RULE `:23-28` | — | exp_id naming convention (framework) | — | KEEP |
| EFFICIENCY 5 % text `:95-104`, `:288-307`, USER `:1344` | `{EFFICIENCY_BAND_PCT}` | the framework constant of §3.3 row 4 (`EFFICIENCY_BAND_FRACTION`) | `5` ✓ | RENDER (one constant, prompt and policy agree by construction) |
| `{TASK_DESCRIPTION}`, `{SCORE_COMPARISON_TABLE}`, `{available_losses_block}` | — | already tokens | — | unchanged |

Reachability: the tuner passes the rendered facts through the SAME
substitution path the bridge already uses (`str.replace` on the SYSTEM
constants; the USER builder receives the roster / shape strings). No new
task-config field; no `examples/` read at runtime.

### 3.7 P3 — the ONLY authorized PB-1/PB-2 byte deltas (FROZEN on approval; declared file-by-file BEFORE the change)

Rendered from the handle (`spec.direction`, `spec.id`) and the 07a record.
Wording is the child's; the SET of touched lines is frozen. Each delta is
regenerated in C5 with the three-part note; anything outside this list
that changes a golden byte is a defect.

| Golden | Line(s) at `787afa08` | Today | 07b render |
|---|---|---|---|
| `pb1_planner_auto_system.txt` | 3 (`prompts.py:12`) | "Your goal is to maximize the `denoising_score` metric …" | "Your goal is to {maximize\|minimize} the `denoising_score` metric (golden metric `{spec.id}`; {higher\|lower} is better) …" |
| " | 28 (`:37`) | "Goal: maximize score with sufficient data." | "Goal: {maximize\|minimize} the score with sufficient data." |
| " | 99-104 (`:106-113` TRAINING vs VALIDATION block) | "final_loss/loss_history = TRAINING; denoising_score = VALIDATION; Low training loss + poor denoising score → overfitting …" | REPLACED by "### TRAINING DYNAMICS (per experiment, from its training history)" — explains the compact per-record `training dynamics` line the USER prompt now carries (train R2 first→last + trend, validation R3 first→last + trend, best validation epoch, degradation after best, train–validation gap when comparable) and how to read it WITHOUT calibrated labels; direction words for the METRIC rendered ("does not move toward {higher\|lower}") |
| " | 89-90 area (`:90-93` "finite negative … below the anchor ceiling") | sign-direction claim | re-worded direction-neutral: "a finite score is NOT collapse; only `-inf`/`None` with a failure reason is" — the "below the anchor ceiling" clause is TIDMAD-metric prose → KEEP that half literal (P2 gap) but drop the sign generalization? **Decision: keep the sentence, replace only "negative" with "finite" — a declared byte delta on line 89** |
| `pb1_planner_auto_user.txt`, `pb1_planner_force_punet_user.txt` | after the `### Current Research Memory:` JSON block | (none) | NEW block "### Training dynamics (last {N} experiments)" — one compact line per verbatim-window record that carries a `training_diagnosis` (07a); records without it: "no training history"; the JSON block itself UNCHANGED (raw keys still hidden) |
| `pb2_reflector_system.txt` | 11 (`:233`), 22-25 (`:244-247`), 79-80 (`:298-300`), 63 (`:282` "lower final_loss" — LOSS, stays) | "denoising_score = VALIDATION dataset"; "GOOD if HIGHER than the best score so far"; "BAD if LOWER"; "beats the best score"; "≥95% of the best score" | GAP ANALYSIS block (`:231-240`) REPLACED by "### TRAINING DYNAMICS" reading guidance (facts, no calibrated labels); `:245/:247` → "A result is GOOD if its score is {HIGHER\|LOWER} than the best score so far … BAD if it is {LOWER\|HIGHER} than most previous scores"; `:298-300` → "beats the best score (in the {higher\|lower}-is-better sense)" / "within {EFFICIENCY_BAND_PCT} % of the best score's range"; a metric identity line "(golden metric `{spec.id}`)" |
| `pb2_reflector_user.txt` | 25-26 (`:1377-1379` ⚠ NOTE), 33 (`:1352` rank) | "final_loss/loss_history above = TRAINING … denoising_score above = VALIDATION" | ⚠ NOTE REPLACED by the rendered "TRAINING DYNAMICS (this experiment)" block from `training_diagnosis` (07a; `absent` → "no training history recorded"); rank line unchanged ("(1 = best)" is direction-correct because `rank` now comes from the order authority) + one line "golden metric: `{spec.id}` ({higher\|lower} is better)" |

Everything else in the five goldens is byte-identical (P2 renders equal
bytes; no other line moves). The `denoising_score` FIELD name stays in
prompts and records (D1 not authorized); `test_denoising_score_field_name_preserved`
stays green.

### 3.8 Diagnosis rendering — content and mechanism (FROZEN on approval)

- Source of truth: the 07a record fields (`ExperimentRecord.training_diagnosis`; for the PLANNER additionally the
  record's `training_history.objective_kind` as a label) — never recomputed (§22.6 item 3). `comparability` is a
  field of `TrainingDiagnosis` itself, so NO extra `TrainingHistory` transport is needed anywhere.
- Renderer: `agent/prompt_templates/tuner/rendering.py::render_training_dynamics_line(diagnosis: TrainingDiagnosis,
  objective_kind: str | None) -> str` — ONE compact line, e.g.
  `[focal] train R2 2.90→2.35 (decreasing, 5 ep) · val R3 2.95→2.62 (decreasing; best ep 3, +0.07 after best) · gap +0.27 (comparable)`;
  with `objective_kind=None` the `[…]` label is omitted (the REFLECTOR path — it deliberately renders R2/R3
  generically and does not render the objective family; the reflector's `actual_results` already carries
  `final_loss` / `loss_history` under the run's own loss config);
  `absent` → `training dynamics: none recorded`; `invalid` → `training dynamics: invalid (non-finite)`;
  `comparability != established` → the gap clause reads `gap n/a (not comparable)`. NO overfitting / plateau /
  converged / underfitting words (07a rule; a test asserts the vocabulary is absent from the renderer's output).
- Planner: the block is built by `get_planner_user_prompt` from the SAME `windowed` records BEFORE `_planner_visible`
  strips the hidden keys — the raw `training_diagnosis` / `training_history` keys stay hidden from the JSON dump
  (Step-06/07a boundary tests keep passing; a new boundary test asserts the block is present AND the raw keys are absent).
- Reflector: the tuner passes the CURRENT attempt's diagnosis (the value it derived at the boundary in 07a) to
  `brain.reflect(..., training_diagnosis=<TrainingDiagnosis | None>)` — the ONLY diagnosis transport to the
  reflector; the bridge renders the block via `render_training_dynamics_line(diagnosis, objective_kind=None)`;
  `actual_results` stays the legacy payload (WF-2 `actual_results_keys` EXACT).
- Cadence / persistence unchanged; nothing new is written to records.

### 3.9 Bridge / kwarg surface deltas (FROZEN on approval — declared additive)

The ONE final contract (both commits together):

```text
LLMBridge.plan(memory_history, ..., <22 existing kwargs>,
               task_render:  TunerTaskRender | None = None,     # C4 (P2 tokens)   → WF-1 kwarg key set 22 → 23
               metric_spec:  MetricSpec | None = None)          # C5 (P3 tokens)   → WF-1 kwarg key set 23 → 24
LLMBridge.reflect(exp_id, hypothesis, actual_results, reflection_context=None,
                  *, metric_spec: MetricSpec | None = None,               # C5
                  training_diagnosis: TrainingDiagnosis | None = None)   # C5
                  # WF-2: actual_results_keys EXACT (9); reflection_context_keys EXACT (23);
                  # the two kwargs are recorded ADDITIVELY in the WF-2 call-surface golden
```

- **Fail-closed at a real render.** `task_render=None` (after C4) and `metric_spec=None` (after C5) raise
  `ValueError` at `plan` / `reflect` before any LLM call — the templates depend on the tokens and there is NO silent
  fallback to TIDMAD literals (that would hardcode TIDMAD in the bridge). The `None` defaults exist ONLY so the WF
  kwarg surface is additive and the pseudo / stub bridges' dispatch is unchanged; the tuner ALWAYS passes
  `run_metric.spec` and the run-scoped `TunerTaskRender`; the PB fixtures pass the shipped spec
  (`derive_tidmad_metric_spec(TIDMAD_PROFILE)`) and a TIDMAD `TunerTaskRender` built from the shipped authorities.
- `TunerTaskRender` (typed, frozen; built ONCE at run scope by the tuner from `run_profile`, `run_model_io`, the
  materialized effective health config and the built-in registry): the rendered strings of §3.6 — roster, full-scope
  segments, output-contract shape (or `None`), built-in loss list, focal defaults, gate-name tokens (or `None` per
  missing check), efficiency band pct.
- WF-1 regenerated additively in C4 (23) and again in C5 (24); WF-2 in C5; each with the three-part note.

### 3.10 OD-1 — condensed-branch byte stability (FROZEN on approval — CLOSED here)

`_truncate_memory_history` builds condensed entries by iterating
`_CONDENSED_KEYS` / `_CONDENSED_MEMORY_KEYS` (frozensets) → hash-order key
sequence → `json.dumps` bytes unstable across processes for > 3 records.
07b: iterate the RECORD's own key order filtered by membership (a
`tuple` of allowed keys is NOT the fix — the record order is the stable
authority the verbatim window already uses); ≤ 3-record renders unchanged
(PB-1 stays exact); a NEW 4-record golden `pb1_planner_history4_user.txt`
pins the condensed branch byte-exactly for the first time. This is an
LLM-visible byte change for ≥ 4-record histories (from unstable to stable)
— covered by this PR's Gate 1.

### 3.11 Test infrastructure

- `RecordingSandbox` / `StubSandbox`: no change needed (07a histories exist); the pseudo tuner harness
  (`run_bounded_pseudo_iteration`) is the replay driver.
- Direction fixtures: reuse `test_step06_c6_stage_b_direction_rung.py::_direction_only_metric` (promote to a shared
  helper `tests/helpers/metric_fixtures.py` — KEEP the original test importing it) and the `_bind_once`
  monkeypatch pattern of `test_step06_c2_tuner_metric_binding.py` to bind a `lower` handle at run scope.
- No test may read the order authority back to assert its own inputs: expected winners / ranks / thresholds are
  literals.

### 3.12 Example packs (parent §8.3 "examples extended")

- `examples/tidmad/`: README task row "golden metric … direction HIGHER … **policy consumes the direction from 07b**";
  STATUS "metric-direction policy / planner-reflector rendering: production-backed from 07b" (the row currently says
  "not yet landed — Step 07b").
- `examples/oxford_iiit_pet/`, `examples/davis_future_prediction/`: STATUS row "policy / rendering: L1 — the pack's
  `declared/metric_*.json` MetricSpec (accuracy↑ / mse↓) is consumed by rungs B-07b-1 (ordering) and B-07b-2
  (rendering phrasing) — no executable path (D14)". No new fixture files (the DECLARED MetricSpecs already exist —
  no consumer-less file); the rung loads them from the packs.

### 3.13 Non-goals (must remain unchanged)

D1 rename (`denoising_score` field / output names) — NOT authorized; peripheral
direction consumers (`core/resume.py`, `workflows/model_exploration.py`,
`nodes/interpretation_helpers.py`, `execute_tools/per_file_best.py`,
`core/campaign_artifacts.py`, dashboard) — Steps 09/10/M2; secondary metrics
as policy (§22.7 — evidence only; 07b renders NO secondary metric because
none is produced under TIDMAD today); Step 08 health semantics (no B/C
health advice invented); Step 09 interpreter rendering; 07c measurement;
retry / round / timeout / signal / admission semantics; scoring / Step 06;
production DEFAULT changes (skip/bypass deltas, penalty default, 5 %
constant value); `TrainingDiagnosis` fields (07a frozen); records; any new
task-config field or `examples/` runtime read; `run()` branching.

---

## 4. Consumers — production selection IS the first consumer (parent §7 row 2)

```text
run_metric.spec (bound :3923)  →  MetricOrder (once per run)
   → _best_trial_winner / skip / bypass / bootstrap        (round loop)
   → planner score-table incumbent                          (planner input)
   → _build_reflection_context (best / rank / band / new-best)  → brain.reflect (+ metric_spec, + diagnosis)
   → _select_best_records (5 tracks)                        → HyperparamTuningOutput
run_metric.spec + run_model_io + run_profile + effective health config + LossConfig authority + registry
   → owned renderers → PLANNER_PROMPT / REFLECTOR_PROMPT tokens (bridge substitution)
record.training_diagnosis (07a) → renderer → planner history block + reflector block (raw keys still hidden)
```

## 5. Checkpoint 0 / Checkpoint A — Stage-A parity

- **Checkpoint 0 (BEFORE the first production edit, C1, test-only):** (a) the **selection replay oracle**: a
  checked-in corpus of `all_records` histories (synthetic, hand-authored — incl. `-inf`, `None`, `nan`, penalized
  collapse, invalid-candidate, trial/formal mix, ties) plus the pseudo-harness run outputs, driven through the CURRENT
  production paths (`_best_trial_winner`, `_should_skip_formal`, `_should_bypass_formal_time_budget`,
  `_resolve_formal_comparison_thresholds` directly; the reflection context and `best_*` outputs through
  `run_bounded_pseudo_iteration` at the reflect boundary and the output) → goldens `sel1_gate_helpers.json`,
  `sel1_reflection_context.json`, `sel1_best_tracks.json` (`_captured_at` provenance); (b) PB-1/PB-2/WF-1/WF-2
  sha256s at `787afa08` + the §3.7 declared-delta list; (c) OD-1: the 4-record condensed render captured as UNSTABLE
  evidence (two-process byte comparison recorded in the ledger, not a golden).
- **Checkpoint A:** replay deep-equal under `higher` after C2/C3; every threshold / band / penalty value identical;
  PB-1/PB-2 exact after C4 (P2 renders equal bytes) and exact-except-declared after C5; WF-1/WF-2 exact or
  declared-additive; REC-2/REC-3 unchanged (no record change); `run()` AST branch count not increased (recorded);
  existing round/attempt/retry tests green.

## 6. Checkpoint B — Stage-B rungs (declared REQUIRED by the parent §8.3 Checkpoint B; item-by-item)

- **B-07b-1 ORDERING-direction axis (L1, STRICT one axis):** identical records / history, only `direction` flips
  (`_direction_only_metric` bound at run scope + the helpers called with both orders) → trial winner, skip / bypass
  orientation and sentinels, bootstrap sentinel side, planner table incumbent, reflection best / rank / new-best /
  worst, and all five `best_*` tracks invert EXACTLY (expected ids / values as literals); the loss rank and
  `best_same_loss_final_loss` do NOT move. Scale arithmetic is NOT asserted here.
- **B-07b-1s policy-semantics rung (L1, separate):** for each §3.3 row on an accuracy-like `higher` metric in
  [0, 1] and an MSE-like `lower` metric near 0 (values chosen so raw-score defaults would be wrong): row 1 resolves
  from the declared deltas with the correct orientation and the disable values keep their meaning; rows 2/3
  sentinels; row 4 band normalized by range (a raw-score `best − 0.05` mutation → RED); row 5 penalty guard
  (finite float under `lower` refused with the recorded reason; `None` accepted); the invalidated outcome (§3.4)
  under both directions.
- **B-07b-2 rendering axis (L1):** planner + reflector rendered (BoundaryRecorderBridge) for (i) the `lower`
  direction-only spec, (ii) the Pets `declared/metric_accuracy.json` (`accuracy`, `higher`) and (iii) the DAVIS
  `declared/metric_mse.json` (`mse`, `lower`), each with the pack's 07a fixture diagnosis
  (`examples/*/expected/training_diagnosis_l1_fixture.json`) and a contrast `TunerTaskRender` → SCOPED assertions
  (Step-01 §13.4): the direction block renders the declared direction words with no higher-is-better residue under
  `lower`, the metric id renders verbatim, the diagnosis lines are present, the P2 task tokens render from the
  contrast render object as available, and NO calibrated label word appears. **No "classification" /
  "regression" phrasing is asserted — `MetricSpec` owns no task type and no landed authority supplies that word to
  the tuner prompt** (Seam 3 gap); whole-prompt absence is not asserted.
- **B-07b-3 task-content axis (L1):** the Step-02 3-file contrast profile + a contrast model-I/O contract + an
  effective health config with renamed checks → different roster / anchor / contract / gate-name tokens; the
  TEMPLATE constants carry no literal for any rendered token (template-scoped absence pins on `PLANNER_PROMPT` /
  `REFLECTOR_PROMPT` for `4000`, `[B, 256, T]`, `punet | fcnet`, `output_diversity`, `alpha=0.5`, `5%`); the KEPT
  literals of §3.6 are NOT asserted absent (they are recorded gaps).

## 7. Checkpoint C — Gate 1 (≥ 2 TUNER ROUNDS; `--num_iterations 2` is additional chain-level coverage)

Real gpt-5.5 planner / reflector / proposer / implementor / validator, pseudo
training (StubSandbox — 07a multi-epoch histories, so diagnosis lines render
from a real trajectory), TWO iterations × TWO rounds; PLUS the deterministic
replay. **Posture FROZEN from source (§0.7 correction 5):**

```text
bash sdsc_submission_scripts/run_chain.sh --mode lilab --workspace <scratch>/07b_gate1 --run_name gate1_07b
    --num_iterations 2 --max_rounds 2 --max_proposal_attempts 3 --max_epochs 1
    --data_scope 4-9 --is_pseudo_training --no-health_gate_enabled --enable_chain_incumbent_formal_gates
    --llm_config llm_configs/openai_tiered_pro.json                                   (cold start; no --seed_paths)
```

- `--is_pseudo_training`: StubSandbox trains nothing, scores stub values, emits 07a histories.
- `--no-health_gate_enabled` (an EXISTING DS6c posture; `_chain_common.sh:307/505`): records self-describe
  `health_gate_enabled=False` and `classify_candidate_health` classifies successful finite-score records VALID
  (`candidate_eligibility.py:169-175`) — the ONLY existing posture under which pseudo records are valid candidates
  (`blocking` and `observe_only` both invalidate them because pseudo training writes no deliverables); NO production
  health semantics are modified and no 07b health exception is invented. The DS8 `--health_gate_files` pairing is not
  required when the subsystem is disabled (`run_one_iteration.py:1837`).
- `--enable_chain_incumbent_formal_gates`: the delta gates consume the chain incumbent — iteration 1 resolves the
  bootstrap (worst-sentinel) reference, iteration 2 the `restored_valid_formal_incumbent` reference reconstructed
  from iteration 1's valid formal record (`workflows/model_exploration.py:2654-2655, :2772-2774`).
- `--max_rounds 2` with the default `--force_formal_round`: round 2 is formal, so the skip helper is reached at the
  formal-round boundary (`:4365-4372`) in BOTH iterations (sentinel in iteration 1, non-sentinel in iteration 2), the
  trial winner is resolved, and the round-2 planner receives the round-1 record's rendered dynamics line + the
  incumbent score table.
- Bypass: reached ONLY when a formal round's time check is infeasible (`:5147-5157`) — not guaranteed under pseudo
  training; bypass being infeasible in the bounded Gate is NOT a failure when the deterministic B-07b-1 / 1s evidence
  is green; if reached, its verdict is recorded.
- Bounds / cost: two Step-06-shaped iterations ≈ 8–16 min, ≈ $0.6, hard timeout 40 min; no GPU work.
- **Rounds vs iterations (FROZEN distinction).** The parent's / this child's "Gate 1 ≥ 2 rounds" means TUNER
  ROUNDS: PASS requires at least ONE tuner invocation to actually complete
  `round 1 → persisted / rendered round-1 result → round-2 planner invocation`, so that the round-2 planner message
  demonstrably contains the rendered round-1 training-dynamics evidence. `--num_iterations 2` alone NEVER satisfies
  the ≥ 2-round criterion; it is ADDITIONAL chain-level coverage whose purpose is to exercise both reference
  regimes where source / runtime behaviour permits (iteration 1: bootstrap / no-restored-incumbent; iteration 2:
  `restored_valid_formal_incumbent`) — it does not replace the within-tuner round-1 → round-2 requirement.
- **PASS evidence is recorded SEPARATELY:**
  A. tuner-round evidence — at least one iteration reached round 2; the round-2 planner received the round-1 rendered
     dynamics; the reflector received the current diagnosis block; raw hidden keys absent from every message;
  B. policy / reference evidence — the ordering / incumbent helpers were reached; `formal_comparison_reference_source`
     / thresholds / banners / `best_*` values recorded as this design requires; the bootstrap and restored-reference
     regimes reported honestly if both are reached (iteration 2 not reaching the restored regime is recorded, not
     failed, provided A holds and the deterministic evidence is green).
- **"Executed" DEFINITION (PASS criterion):** the decision helpers are REACHED and their resolved values / verdicts
  are RECORDED — `formal_comparison_reference_source` / `resolved_skip_formal_threshold` /
  `resolved_bypass_formal_threshold` / `formal_reference_score` in each `run_output`, the `[SkipFormal]` /
  winner banners in the chain log, the five `best_*` tracks — NOT that both mutually exclusive actions (skip AND
  bypass) become `True`.
- PASS artifacts: standard Gate-1 criteria + the 07b property — a passive `_chat_json` tee (the Step-06 shape) shows
  every planner message with the direction block and the round-2 planner with the round-1 dynamics line, every
  reflector message with the dynamics block, and ZERO raw hidden keys (`training_history`, `training_diagnosis`,
  `metric_result`, `metric_refusal`) in any message; both `run_output_*.json` validate; iteration 2's
  `formal_comparison_reference_source == "restored_valid_formal_incumbent"`.
- If the frozen posture cannot produce valid stub successes at readiness (a source drift), STOP and re-plan the
  harness — never invent a 07b-specific health exception.

## 8. Checkpoint D — mutation / reachability validation (each row is a named mutation or reachability proof; parent §8.3 Checkpoint D item-by-item)

Parent Checkpoint D items → this child: **direction mutations per family**
(rows 1–2), **sentinel mutation** (row 2), **scale-rule mutation** (row 3),
**invalidated-result outcome mutation** (row 5), **template-literal
reintroduction** (row 7), **reachability — production path uses the order
authority** (row 1), attempt-transition parity → not applicable (REMOVED;
retry/round tests are the parity evidence). Additional child rows: raw-key
leak, calibrated vocabulary, bridge fail-closed, WF surfaces, OD-1
second-process, `run()` branch count.

| Failure / mutation | Behaviour |
|---|---|
| a consumer bypasses the order authority (keeps `max` / `<`) — flip ONE ordering comparison per family | strict rung RED (direction flip does not invert that consumer); reachability: `MetricOrder` monkeypatched to a sentinel-returning object → production selection RED |
| sentinel mutation (`-inf`↔`+inf` under `lower`) | rung RED |
| a scale rule silently reverts to a raw-score default | policy-semantics rung RED |
| penalty float under `lower` | refused at startup with the recorded reason (never a "better" incumbent read by the planner) |
| invalidated result becomes an incumbent | validity outcome test RED under both directions |
| loss rank flips with the metric | pinned test RED |
| a P2 token renders a different byte under TIDMAD | PB-1/PB-2 goldens RED at C4 (nothing regenerated in C4) |
| a P3 delta outside §3.7 | golden diff review + the declared-delta list in the ledger; test that the diff of the regenerated goldens touches ONLY the declared lines (line-set assertion recorded, not a test — reviewed) |
| raw `training_history` / `training_diagnosis` / `metric_*` keys leak into a render | boundary tests RED (both renders) |
| a calibrated label word rendered from the diagnosis | renderer vocabulary test RED |
| `metric_spec=None` or `task_render=None` at a real render | bridge `ValueError` (fail closed) |
| WF-1/WF-2 kwarg surface changes beyond the declared additive keys | goldens RED |
| OD-1 condensed order still unstable | 4-record golden RED under a second process (test runs the render in a subprocess and compares) |
| `run()` gains a branch | AST count recorded; CI pyright |
| Gate 1 planner / reflector reject the new prompt shape (schema failure) | Gate 1 FAIL — diagnose; wording is the child's to fix; rerun after a substantive fix only |

## 9. Test disposition

New families (each names the defect only it catches): order authority
(pure); consumer rewiring + reachability; strict ordering rung; policy-
semantics rung; validity outcome; loss-rank non-flip; scale-rule
classification pins; renderer units (direction block, diagnosis line,
task tokens); template absence pins (scoped); boundary tests at BOTH renders
(present block + absent raw keys); OD-1 subprocess byte-stability; bridge
fail-closed; WF-1/WF-2 additive; rungs B-07b-2/3; pack pins. **UPGRADED
(direction-parametrized REWRITE, per parent §14):** `test_delta_gates.py`
(sentinels, resolver, edges, anti-phantom gains a direction axis),
`test_formal_launch_decision.py` (MATRIX under both directions),
`test_valid_trial_winner_drives_formal.py`, `test_valid_candidate_selection.py`,
`test_degeneracy_handling.py` (`-2.5` is "worse" ONLY under higher; adds
the `lower` refusal), `test_tuning_agent.py` selection assertions,
`test_step06_c2_tuner_metric_binding.py` (the literal `"higher"` at `:70`
stays for the shipped path; add the flip assertion). **KEPT:**
`test_gate_integration.py`, `test_prompt_banned_vocabulary.py`,
`test_planner_prompt_task_config.py` (field-name presence stays true),
Step-06/07a boundary tests (extended, not replaced), REC goldens.
**DELETED:** `test_control_boundary.py::TestAttemptDecision` (the types are
removed) — `TestRoundOutcome` stays.

## 10. Gates — from the standard's table (parent §11)

| Commit type | Typical gate |
|---|---|
| New LLM-facing system prompt | Gate 1 |
| Checkpoint (end of feature) | Gate 2 |

- **Gate 1 REQUIRED, ≥ 2 TUNER ROUNDS** (P3 changes SYSTEM prompt bytes; OD-20-6): ONE bounded run at the final
  executable head after C6, real `openai_tiered_pro.json`, pseudo training, `--no-health_gate_enabled` (no
  07b-specific health exception), cold-start; `--num_iterations 2` = additional chain-level reference-regime coverage,
  never a substitute for the within-tuner round-1 → round-2 evidence (§7); PASS = the standard's Gate-1
  criteria + the 07b property (§7: round-2 planner receives round-1's rendered dynamics line and direction wording;
  reflector receives the diagnosis block; no raw hidden key in any message; the trial-winner / skip / incumbent
  helpers reached with their resolved values recorded — bootstrap in iteration 1, restored incumbent in iteration 2;
  bypass recorded if reached). **NOT launched without operator approval at launch** (or a
  pre-authorizing Implementation Working Rules contract, as 07a's did for its Gate 2).
- **Gate 2 NOT REQUIRED**: no execution launch changes; deterministic replay proves policy parity. Flip: any change
  to training / inference / scoring launches → Gate 2 (and this design is wrong — STOP).
- Corpus breadth (§22.13): TIDMAD executable at the LLM seam; Pets / DAVIS contribute B-07b-1/1s/2 (L1) with the
  reason recorded (D14 not landed).

## 11. Validation budget

Targeted unit families per commit; the full unit suite ONCE at the final
executable head from a clean tree; exact-head CI once; ONE Gate 1 (~3–8 min,
~$0.3, per the Step-06 precedent; bounded by `max_rounds 2`, pseudo
training); no Gate 2; no real training.

## 12. Rollback boundary

Reverting the PR restores the literal `max`/`<`/`-inf` sites, the two
removed types, the prompt literals and the pre-07b goldens; nothing else
depends on `MetricOrder` (D1 peripheral consumers are still literal —
Steps 09/10 will import it later).

## 13. Stop conditions

Parent §8.3 stops: ordering cannot be expressed without a second direction
field or a metric rename; a scale-sensitive rule can be made honest only by
inventing a task-config field (→ operator); a P2 block needs a fact no
LANDED authority declares (→ record the gap / omit — never invent B/C
health semantics); a PB delta appears that is not attributable to P3;
retry / round semantics would change; the new logic would have to live
inside `run()`. Child stops: `metric_spec` cannot reach the bridge without
a WF-1/WF-2 change beyond additive; the penalty rule cannot be made
fail-closed without a schema field; the OD-1 fix cannot keep ≤ 3-record
bytes exact; Gate 1 semantic FAIL not repairable by wording; a production
file outside §3.1 must change materially; > ~1 h or material cost for any
single validation.

---

## 14. Implementation ledger

| Field | Value |
|---|---|
| Implementation branch | `step07-pr07b-tuner-policy` |
| Implementation base | `f17bbdb87e79ee823c969cee63df37bc99437d70` (`f17bbdb8`, master; `origin/master == HEAD`, clean tree at branch creation) |
| Authorization | Implementation Working Rules contract for Step 07 PR 07b (operator, 2026-08-16) — autonomous C1→C6, Gate 1 PRE-AUTHORIZED, Gate 2 forbidden, never merge |
| Source drift vs the design base | **NONE.** `git diff --stat 787afa08 f17bbdb8` touches only `docs/**` + `CLAUDE.md` (5 files, all documentation), so every source line number quoted in §0 is exact at the implementation base. |

### 14.0 — Checkpoint 0 (C1, test-only)

**Commit `98b74c07` — `test(step07/07b): C1 Checkpoint 0 — selection/threshold/reflection replay oracle`.**

**Files added (no production diff):**

```text
tests/unit/agent/tune_ml_hyperparam_agent/fixtures/sel1_histories.json        corpus (12 histories + 8 threshold + 7 gate scenarios)
tests/unit/agent/tune_ml_hyperparam_agent/goldens/sel1_gate_helpers.json      SEL-1a
tests/unit/agent/tune_ml_hyperparam_agent/goldens/sel1_reflection_context.json SEL-1b
tests/unit/agent/tune_ml_hyperparam_agent/goldens/sel1_best_tracks.json       SEL-1c
tests/unit/agent/tune_ml_hyperparam_agent/test_step07b_c1_selection_replay.py 5 tests
```

**Corpus case coverage** (each history names ONE input class; `test_corpus_covers_every_required_case`
pins the id set against a hardcoded tuple, never against the fixture itself):
`h_empty` · `h_simple_trials` · `h_tie_first_wins` · `h_none_score` · `h_neg_inf` ·
`h_pos_inf` · `h_nan` · `h_collapse_penalty` · `h_invalid_candidate` (gate-failed AND
gates-missing, both outscoring the valid record) · `h_trial_formal_mix` ·
`h_time_mode_mismatch` · `h_no_successes`. Non-finite scores travel as the sentinel
strings `__neg_inf__` / `__pos_inf__` / `__nan__` so the fixture stays strict-JSON
parseable (the same reason `_json_safe_reference` refuses to persist bare `Infinity`).

**Captured values worth naming** (full goldens in the files):

| Surface | Captured fact |
|---|---|
| `h_simple_trials` winner | `t_high` @ `-2.55` (argmax) — becomes the argmin `t_low` @ `-3.4` under the C2 strict rung |
| `h_tie_first_wins` winner | `t_tie_a` — `max()`'s FIRST-wins semantics, which `MetricOrder.best` must preserve |
| `h_collapse_penalty` winner | `t_ok2` @ `-2.7`; the `failed_mode_collapse` record at `-5.0` is not a candidate (under `lower` it would otherwise read as the best score — §3.4) |
| `h_pos_inf` / `h_neg_inf` / `h_nan` / `h_none_score` | all resolve to the finite `t_ok` @ `-3.0`; non-finite scores are filtered by validity BEFORE any ordering |
| `h_trial_formal_mix` winner | `t_only` @ `-3.3` although two formal records score `-1.2` / `-1.8` |
| skip/bypass sentinels (`h_simple_trials`) | `threshold=-inf` → skip **False** / bypass **True**; `threshold=+inf` → skip **True** / bypass **False** — the asymmetric disable convention C2 must reproduce through `worst_sentinel` / `best_sentinel` |
| threshold resolver | `gates_off_*` → `(None,None,None,"gates_disabled")`; `bootstrap` → `-inf ×3` + `"negative_infinity_bootstrap"`; `restored_defaults` (ref `-2.5`, deltas `-1.0`/`0.0`) → skip `-3.5`, bypass `-2.5`; `restored_skip_disabled` (delta `-inf`) → skip `-inf`; `restored_bypass_disabled` (delta `+inf`) → bypass `+inf` |
| reflection context (pseudo run, 2 reflect calls) | round 1: `best_score_so_far=None`, `rank=None`, `is_new_best=True`, `is_more_efficient=False`, `same_loss_loss_rank=1`; 23 keys both calls |
| five `best_*` tracks (pseudo run) | `best_exp_id=…_002` @ `0.65`, `best_formal_denoising_score=0.65`, `best_valid_exp_id=…_002`, `best_valid_formal_exp_id=…_003`, `best_valid_trial_exp_id=…_002` (the `_002`/`_003` tie at `0.65` re-proves first-wins at the finalization seam) |

**`run()` AST branch-node baseline: 244** (`HyperparamTuningAgent.run`, lines
3836–6657 = 2 822 lines; node set `If/For/While/Try/ExceptHandler/With/BoolOp/IfExp/
comprehension/Assert/Match/match_case`). Pinned by
`test_run_branch_count_not_increased` — it fails the moment a later commit puts a new
policy branch in the orchestrator instead of behind an extracted boundary.

**Baseline sha256 (at `f17bbdb8`) — PB-1 / PB-2 / WF-1 / WF-2:**

```text
a691a7f5eecce5a81cb5e802110bc8c9708d2ab4a69e52c850a2f61d9e4c8e62  pb1_planner_auto_system.txt
3b8677e8861aa0b01d1684fe684b5f23f85c0d5f752e75b89602597cffff198e  pb1_planner_auto_user.txt
b0cb4d90933cefe950154e9ab0ecc701974e9ee52150e0214aa281f9957f3aba  pb1_planner_force_punet_user.txt
3566caec033e4a42c137ef2c39960e4e98177676ce6c1a89f38abc125e1f95ac  pb2_reflector_system.txt
81fa5f496a412a1118dfd141b670da335206594ecb65c83cc56f65f3000e3e06  pb2_reflector_user.txt
ee7403bd6d6e12620789e3da6b24dbb3b168fc04fc2e98cf54efe1600425b530  wf1_plan_kwarg_key_set.json      (22 kwargs)
5e8943f68de20209a84e0b349466e1dc0d9bac740b142ae9ada829e294682c53  wf1_plan_call_round1_surface.json
bbf33b097b999f6ec1bf643d8438bcb629bc8106109fd154c661241dffe8868b  wf2_reflect_call_surfaces.json  (actual_results 9 / reflection_context 23)
```

**Declared §3.7 P3 delta line-set — verbatim, re-read at `f17bbdb8`.** The design's
§3.7 table cites the goldens' line numbers as *reading aids* (§"NOT frozen"); two of
them had drifted and are CORRECTED here. The SET of touched semantic lines is
unchanged — no line is added to or removed from the frozen scope.

| Golden | Declared line(s) | Current bytes |
|---|---|---|
| `pb1_planner_auto_system.txt` | 3 | `Your goal is to maximize the \`denoising_score\` metric across hyperparameter configurations for the following task:` |
| " | 28 | `  loss_type, and regularization. Goal: maximize score with sufficient data.` |
| " | **81–82** (§3.7 said "89-90 area" — corrected) | `- A finite negative score such as \`-3.14\` is NOT collapse. It is valid,` / `  low-but-real performance below the anchor ceiling.` — only "negative" → "finite" per §3.7's decision |
| " | **97–104** (§3.7 said 99-104 — corrected: the block's `###` heading and its `final_loss` line are part of the replaced block) | `### TRAINING vs VALIDATION — CRITICAL:` … `    - Both improve together → the direction is correct, continue exploring.` |
| `pb1_planner_auto_user.txt`, `pb1_planner_force_punet_user.txt` | after the `### Current Research Memory:` JSON block | NEW dynamics block (no existing line changes) |
| `pb2_reflector_system.txt` | **9–11** (§3.7 said 11; the `### CRITICAL — GAP ANALYSIS` heading and its `final_loss` line are part of the replaced block) | `### CRITICAL — GAP ANALYSIS (Generalization Gap):` / `- \`final_loss\` and \`loss_history\` are measured on the **TRAINING dataset**.` / `- \`denoising_score\` is measured on the **VALIDATION dataset**.` |
| " | 23, 25 | `- A result is GOOD if its denoising_score is HIGHER than the best score so far.` / `- A result is BAD if it is LOWER than most previous scores.` |
| " | 79–80 | `A configuration is only "Better" if it beats the best score. But a configuration is` / `"Valuable" if it achieves ≥95% of the best score with <50% of the parameters or training` |
| " | 63 — **NOT a delta** | `- When loss_type is the same, a lower final_loss relative to previous same-loss experiments is a positive signal.` (LOSS direction, stays) |
| `pb2_reflector_user.txt` | 24–26 | `  ⚠ NOTE: final_loss/loss_history above = TRAINING dataset.` / `           denoising_score above = VALIDATION dataset (different data).` / `           Reason about the gap between them to detect overfitting or underfitting.` |
| " | 33 — **unchanged text**, direction-correct via the order authority | `  denoising_score rank  : 1 / 3 (1 = best)` |
| " | new | one metric-identity line |

Anything outside this set that moves a golden byte in C4/C5 is a defect (§8 row 8).

**OD-1 baseline instability — reproduced, recorded as evidence (not a golden).**
`_truncate_memory_history` (`agent/prompts.py:926-935`) builds condensed entries with
`{k: rec[k] for k in _CONDENSED_KEYS if k in rec}` — frozenset iteration. Rendering the
FIRST condensed entry of a 4-record history under five hash seeds produced **five
distinct key orders**:

```text
PYTHONHASHSEED=0  {"status","is_trial","model_type","exp_id","failure_reason","denoising_score"} / memory {"conclusion","hypothesis","round_index"}
PYTHONHASHSEED=1  {"status","model_type","is_trial","exp_id","denoising_score","failure_reason"} / memory {"hypothesis","round_index","conclusion"}
PYTHONHASHSEED=2  {"is_trial","exp_id","failure_reason","model_type","denoising_score","status"} / memory {"round_index","conclusion","hypothesis"}
PYTHONHASHSEED=3  {"model_type","exp_id","is_trial","failure_reason","denoising_score","status"} / memory {"hypothesis","round_index","conclusion"}
PYTHONHASHSEED=4  {"exp_id","status","model_type","denoising_score","failure_reason","is_trial"} / memory {"conclusion","hypothesis","round_index"}
```

`json.dumps(indent=2)` bytes therefore differ across processes for ≥ 4-record
histories. The ≤ 3-record PB-1 fixture never enters the branch, which is why no golden
ever caught it. C4 closes it by record-own-order iteration + a 4-record golden pinned
across a subprocess.

**Validation.**

```text
.venv/bin/python -m pytest tests/unit/agent/tune_ml_hyperparam_agent/test_step07b_c1_selection_replay.py -q
  → 5 passed in 1.71s, rc=0   (/tmp/07b_c1.log)
ruff check . / ruff format --check .   → clean (see below)
```

**Deviations at C1: NONE** beyond the two golden line-number corrections recorded
above (reading aids, explicitly not frozen). C1 contains no production diff
(`git diff --stat` over `nodes/`, `agent/`, `execute_tools/`, `workflows/` = empty).

---

### 14.1 — C2: `MetricOrder` + every ordering consumer + validity outcome (P1-order)

**Commit `41baf643` — `feat(step07/07b): C2 — MetricOrder, the one golden-metric order authority`.**

**Production diff**

```text
execute_tools/metric_order.py                                    NEW, 200 lines — the ONE authority (§3.2 API)
nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py
      + run_order = MetricOrder(run_metric.spec)                 bound at run scope beside run_metric (:3924)
      + _identity / _score_of                                    ordering key functions
      + _build_reflection_context(...)                           EXTRACTED from run() (139 inline lines → a typed helper)
      + BestTracks / _select_best_records(...)                   EXTRACTED from run() (47 inline lines → a frozen dataclass + helper)
      ~ _best_trial_winner / _should_skip_formal /               gained `order`; max()/</>= /±inf → the authority
        _should_bypass_formal_time_budget
      ~ planner score-table incumbent, skip + bypass banners     order.best / order.comparison_symbol / order.at_least_symbol
```

`_resolve_formal_comparison_thresholds` is deliberately UNTOUCHED at C2: its
`ref + delta` arithmetic and its `-inf` bootstrap are SCALE rules and belong to C3,
so the C2 diff stays ordering-only exactly as the commit plan requires.

**The extraction was done in two steps, with evidence at each** (design §17 finding 14):

| Step | What changed | C1 replay |
|---|---|---|
| 1 — VERBATIM extraction | the two blocks moved out of `run()` with their `max` / `sorted(reverse=True)` / `min` intact; gate helpers rewired | `5 passed in 1.59s`, rc=0 — deep-equal |
| 2 — authority rewire | `best` / `worst` / `rank` / `is_better` inside the extracted helpers | `5 passed in 1.62s`, rc=0 — still deep-equal |

**Consumer migration — the §0.1 census, item by item**

| §0.1 site | 07b | Commit |
|---|---|---|
| 1 trial winner | `order.best(candidates, key=_score_of)` | C2 |
| 2 skip gate + its disabled sentinel | `order.is_better(threshold, score)`; `threshold == order.worst_sentinel` | C2 |
| 3 bypass gate + its disabled sentinel | `order.is_at_least(score, threshold)`; `threshold == order.best_sentinel` | C2 |
| 4 bootstrap sentinel + `ref + delta` | — | **C3** (scale) |
| 5 planner score-table incumbent | `run_order.best(_records_with_table, key=_score_of)` | C2 |
| 7 reflection `best_score` / `best_record` / `rank` / `worst_score` / `is_new_best` | `order.best` / `order.rank` / `order.worst` / `order.is_better` | C2 |
| 7 reflection `is_more_efficient` + the 5 % band | — | **C3** (scale) |
| 8 LOSS rank (`sorted` ascending, `min`) | UNCHANGED, and pinned unchanged | C2 |
| 9 five `best_*` tracks | `order.best` per track, same filters | C2 |

**Deviation (bounded).** `MetricOrder` carries two members the §3.2 table does not
list: `comparison_symbol` (`<` / `>`) and `at_least_symbol` (`>=` / `<=`). The
frozen table's row for the banners says the banner "renders the order's operator
symbol", and the bypass banner needs the at-least form. Both are FORMATTING ONLY
(stdout, never an LLM surface, never a decision) and both live INSIDE the one
authority, so they add no second interpretation site — which is the invariant the
table exists to protect. *Source evidence*: skip banner `:4384-4390` hardcoded `<`,
bypass banner `:5163-5176` hardcoded `>=`. *Validation*:
`TestBannerSymbols`. Under `higher` the rendered bytes are unchanged.

**Test disposition applied at C2**

| Module | Disposition |
|---|---|
| `tests/helpers/metric_fixtures.py` | NEW — `direction_only_spec` / `direction_only_metric` promoted from Step 06's C6a rung (§3.11); the Step-06 module imports them, so its rung still binds the identical one-axis handle |
| `tests/unit/execute_tools/test_metric_order.py` | NEW, 18 tests — the authority as a pure object |
| `tests/unit/agent/tune_ml_hyperparam_agent/test_step07b_c2_order_consumers.py` | NEW, 35 tests — rung **B-07b-1**, loss-rank non-flip, §3.4 validity outcome, reachability |
| `test_delta_gates.py`, `test_valid_candidate_selection.py` | UPGRADED — module helpers take `order`, defaulting to the shipped `HIGHER_ORDER`, so every pre-07b assertion states exactly the property it stated before |
| `test_formal_launch_decision.py` | UPGRADED — same, plus the structural single-resolution test now also pins `order=run_order` at ≥ 3 call sites and `run_order = MetricOrder(run_metric.spec)` in the tuner |
| `test_valid_trial_winner_drives_formal.py`, `test_force_formal_round.py`, `test_m6_probe_unavailable_fails_closed.py`, `tests/integration/workflows/test_chain_incumbent_pseudo.py` | UPGRADED — mechanical `order=` plumbing at the shipped order |
| `tests/unit/execute_tools/test_step06_c5_boundary_and_structure.py` | UPGRADED — see below |

**Step-06 C5 guard: migrated, not silenced.** Step 06 left an executable list of
direction consumers it did NOT reach, with the instruction *"if one of these goes
red, someone migrated a consumer: record it as reached, do not silence the guard."*
Five of its assertions went red at C2, and both were the guard working:

1. `test_no_production_surface_executes_a_direction_literal_outside_the_metric_module`
   — `metric_order.py` executes `"higher"` once. The guard now allows exactly TWO
   modules and states the split: the metric module DECLARES the vocabulary, the
   order module INTERPRETS it. Any third is still an offender.
2. The four tuner rows of `NOT_REACHED_DIRECTION_CONSUMERS` moved to a new
   `MIGRATED_TO_THE_ORDER_AUTHORITY` table whose assertion is INVERTED — the
   hardcoded comparison must now be ABSENT and `MetricOrder` present. Deleting the
   rows would have erased the evidence that the migration happened, which is the
   drift §16-Q6 exists to prevent. The D1 rows (chain / resume / `per_file_best` /
   dashboard) are untouched debt and still hold their literals.

**Mutation / reachability evidence (Checkpoint D rows 1, 2, 5, 6).** Nine mutations,
each applied to EXACTLY ONE site (asserted: the sweep refuses to run if the target
string occurs 0 or ≥ 2 times), `__pycache__` cleared before every run, baseline
restored and re-proved green afterwards
(`47 passed in 2.84s`, rc=0, `git status --short` empty). Selection:
`test_step07b_c2_order_consumers.py` + `test_step06_c5_boundary_and_structure.py`.

| # | Mutation | Defect it stands for | Observed |
|---|---|---|---|
| M1 | `_best_trial_winner` reverts to a bare `max` | a consumer never joined the authority | **RED** 2 failed / 45 passed |
| M2 | skip disabled-sentinel back to the `-inf` literal | under `lower` the skip gate stays permanently armed | **RED** 1 / 46 |
| M3 | bypass disabled-sentinel back to the `+inf` literal | under `lower` the bypass stays permanently disabled | **RED** 1 / 46 |
| M4 | skip comparison back to `<` | the gate fires on the wrong side under `lower` | **RED** 2 / 45 |
| M5 | `is_new_best` back to `>` | the reflector calls the worst result a new best | **RED** 3 / 44 |
| M6 | reflection `rank` back to `sorted(reverse=True)` | the LLM is shown an inverted leaderboard | **RED** 2 / 45 |
| M7 | `valid_records` filter dropped | an invalidated result becomes an incumbent (§3.4) | **RED** 2 / 45 |
| M8 | loss rank routed THROUGH the metric order | the worst training run of a loss family reported as its best | **RED** 3 / 44 |
| M9 | the five `best_*` tracks back to bare `max` | finalization ignores the declared direction | **RED** 2 / 45 |

Every mutation was RED, so no test in this commit is decoration. M8 is the
inverse-shaped proof the others cannot give: it fails BECAUSE the loss stayed put,
which is the only way to pin "this one must NOT migrate".

Reachability is separate from all nine: `test_the_production_run_reaches_the_order_authority`
swaps `MetricOrder` for a recording double inside the production module and drives a
real bounded tuner iteration, then asserts the reached member set is exactly
`{best, worst, rank, is_better}`. The sentinels are asserted ABSENT there and the
reason recorded: that harness runs with `enable_chain_incumbent_formal_gates` off, so
`_should_skip_formal` short-circuits before the sentinel comparison. Asserting a path
the run does not take would have been a false reachability claim; the sentinels'
reachability is the gate-helper rung's, and in production Gate 1's
`--enable_chain_incumbent_formal_gates`.

**Validation.**

```text
.venv/bin/python -m pytest tests/unit/agent/tune_ml_hyperparam_agent/test_step07b_c1_selection_replay.py \
      tests/unit/agent/tune_ml_hyperparam_agent/test_step07b_c2_order_consumers.py \
      tests/unit/execute_tools/test_metric_order.py -q -p no:randomly
  → 58 passed in 1.94s, rc=0
.venv/bin/python -m pytest tests/unit/agent/tune_ml_hyperparam_agent tests/unit/execute_tools \
      tests/unit/agent/llm_bridge tests/unit/workflows tests/unit/core -q -p no:randomly
  → 5040 passed, 3 skipped in 447.16s (0:07:27), rc=0   (/tmp/07b_c2_all.log)
ruff check . / ruff format --check .   → clean
```

Backward compatibility: C1 replay goldens deep-equal; PB-1/PB-2/WF-1/WF-2 untouched
(no prompt or bridge change in C2); REC goldens untouched (no record change);
`run()` AST branch count **198 ≤ 244** (the two extractions moved 46 branch nodes out
of the orchestrator; the sequencing calls added none).

**Process incident, recorded because it cost work.** The first mutation sweep used
`git checkout -- <file>` to restore each mutated site. On an UNCOMMITTED tree that
restores to `HEAD`, so it discarded the whole C2 production edit rather than the
mutation. The edits were reapplied deterministically from the transcript with
per-replacement count assertions. **Rule adopted for the rest of this PR: commit the
semantic checkpoint BEFORE any mutation sweep** — which is also what CLAUDE.md's
"final validation runs from a clean tree" rule implies, and what makes a mutation's
`git checkout` restore the intended baseline.

---

### 14.2 — C3: classified scale rules + penalty guard + `AttemptTransition` REMOVE (P1-scale)

**Commit `f10c9bc4` — `feat(step07/07b): C3 — the scale-sensitive rules, classified`.**

**§3.3 row-by-row, as implemented**

| Row | Class | Implementation | TIDMAD value |
|---|---|---|---|
| 1 declared skip / bypass margins | (ii) DECLARED | `_resolve_formal_comparison_thresholds(..., order)` → `order.toward_better(reference, delta)`. `signed_delta` is a coordinate on the better-direction axis, so `-1.0` loosens under BOTH directions and the operator's `-inf` / `+inf` disable values still resolve to that metric's worst / best sentinel | `ref−1.0` / `ref+0.0` — **identical** |
| 2 bootstrap sentinel | (i) generic | `order.worst_sentinel`. The source string `negative_infinity_bootstrap` is KEPT: it is a provenance label persisted on records, so renaming it is a record-vocabulary change (D1-adjacent, not authorised). Documented as "the worst-value bootstrap" | `-inf` — identical |
| 3 disable sentinels | (i) generic | already at C2 (`order.worst_sentinel` / `order.best_sentinel` in the two gates) | identical |
| 4 efficiency band | (i) generic, metric-independent DEFINITION | `EFFICIENCY_BAND_FRACTION = 0.05` (ONE named module constant, exported for C4's prompt renderer); `score_range = abs(best − worst)`; `score_threshold = order.toward_worse(best, EFFICIENCY_BAND_FRACTION * range)`; `is_more_efficient` uses `order.is_at_least`. Single-distinct-score path (`range is None` → threshold = best) unchanged | `best − 0.05·range` — identical |
| 5 collapse penalty | (ii) DECLARED + (iv) inapplicable → FAIL CLOSED | `_validate_penalty_for_direction(agent_input, order)` raises `ValueError` for a finite float under a metric the convention does not describe; `None` always accepted; `_apply_degeneracy_reaction` itself unchanged and direction-free | `None` default and a configured `-5.0` under `higher` — identical |
| 6 `is_new_best` | ordering | C2 | identical |
| 7 baseline `"baseline" in exp_id` | naming convention | untouched | identical |
| 8 loss rank | not a metric rule | untouched, and pinned unchanged | identical |
| 9 `_json_safe_reference` | storage image | untouched (`math.isfinite` already covers `+inf`) | identical |

**The penalty guard's refusal path.** The design requires it "routed through the
EXISTING startup-validation failure path". Audited: the tuner's startup refusal is
`validate_runtime_config` (`agent/schemas/hyperparam_tuning.py:2322`) raising
`ValueError` at `run()` entry, before any LLM call, sandbox construction or file I/O.
`validate_runtime_config` cannot host the check — it is shared with the workflow
pre-flight and takes no metric — so the guard is a tuner-local typed helper invoked
on the SAME line block, immediately after `validate_runtime_config`, raising the same
`ValueError`. Reachability is pinned structurally
(`test_the_refusal_is_reached_from_production_startup` asserts the call site exists
AND precedes the round loop, so a guard moved after the first LLM call fails).

**Deviation (bounded).** `MetricOrder.penalty_convention_applies` is a member the
§3.2 table does not list. It exists because the alternative was worse: the guard
otherwise needs `order.direction == "higher"` in the tuner, which is a direction
literal outside the metric/order modules and would have re-created exactly the
second-authority pattern 07b removes (and would have failed Step 06's C5 guard,
correctly). The member is phrased as a POLICY question — "does this declared
convention have a meaning under the bound metric?" — not as a direction flag, has
exactly one caller, and lives inside the one authority. *Validation*:
`TestPenaltyConventionPredicate`. Its `_higher` source is the same private flag every
other member reads, so no second interpretation exists.

**`AttemptTransition` / `AttemptDecision` — REMOVED (§3.5, Q-07b-1).**
Repo-wide grep after the change: zero references outside the replacement comment.
The `resolved_action` hazard is recorded WHERE THE NEXT READER MEETS IT — a
`KNOWN DEFECT` note at the declaration inside `run()` naming the mechanism (round-
scoped, written seven nesting levels down, only on the branch that reaches health-gate
evaluation, never reset between attempts), the proposed fix (carry per attempt;
distinguish "no action produced" from `CONTINUE`), why 07b may not apply it (it
changes round outcomes in the crash-after-a-scored-attempt case) and its owner (a
dedicated round-semantics correction requiring an operator decision — neither 07b's
nor 07c's). `tests/…/test_control_boundary.py::TestAttemptDecision` DELETED with the
reason in place of it; `TestRoundOutcome` untouched and green (42 passed).

**Schema docstrings** (`agent/schemas/hyperparam_tuning.py`): `skip_formal_min_delta`,
`bypass_formal_time_budget_min_delta` and `degenerate_penalty_score` re-worded — units
are the golden metric's ("dB under TIDMAD, whose metric is log-space"), the margins
are coordinates on the better-direction axis, and the `lower` refusal is documented.
**No field added, no default changed**, so REC-3's schema field lists are unchanged.

**Rung B-07b-1s** — `tests/unit/agent/tune_ml_hyperparam_agent/test_step07b_c3_scale_rules.py`,
28 tests, deliberately on NON-TIDMAD scales (accuracy-like `higher` in [0, 1],
MSE-like `lower` near 0) because TIDMAD's log-space values around −3 are exactly where
a TIDMAD-tuned default still looks right. Each test names the number a wrong
implementation would produce, e.g.: a raw `ref + delta` resolves the MSE skip
threshold to 0.009 — *tighter* than the incumbent, so a genuinely regressed trial
still buys a formal round; a raw `best − 0.05·range` on the MSE metric resolves to
0.008, better than the run's best, so the efficiency signal would be permanently dead;
a raw `best − 0.05` on the accuracy metric widens the band eightfold.

**Validation.**

```text
.venv/bin/python -m pytest tests/unit/agent/tune_ml_hyperparam_agent/test_step07b_c3_scale_rules.py -q -p no:randomly
  → 28 passed in 1.40s, rc=0
.venv/bin/python -m pytest tests/unit/execute_tools tests/unit/agent/tune_ml_hyperparam_agent -q -p no:randomly
  → 2283 passed, 1 skipped in 329.32s, rc=0   (/tmp/07b_c3b.log)
ruff check . / ruff format --check .   → clean (931 files)
```

C1 replay deep-equal under `higher` after C3 (the range-normalised band and the
`toward_better` margins reproduce every captured value); `run()` AST branch count
**198 ≤ 244**; PB/WF/REC untouched (no prompt, bridge or record change in C3).

**Mutation evidence (Checkpoint D rows 3, 4).** Nine mutations, each applied to
EXACTLY ONE asserted site, caches cleared, baseline restored and re-proved green
(`68 passed in 1.89s`, rc=0, `git status --short` empty). Selection: the C3 rung +
the C1 replay + `test_delta_gates.py` + `test_degeneracy_handling.py`.

| # | Mutation | Defect it stands for | Observed |
|---|---|---|---|
| N1 | margins revert to raw `ref + delta` | a declared rule silently reverts to a raw-score default | **RED** 4 failed / 64 passed |
| N2 | bootstrap reverts to the `-inf` literal | a fresh minimised-metric chain is budget-blocked forever (the v15 failure) | **RED** 1 / 67 |
| N3 | band reverts to a raw `best - 0.05` | the band stops being range-normalised — eight times too wide on an accuracy metric | **RED** 3 / 65 |
| N4 | band keeps the fraction but drops the direction | correct width, wrong side — dead efficiency signal on every minimised metric | **RED** 1 / 67 |
| N5 | range loses its `abs` | a signed range flips the band's sign under `lower` | **RED** 1 / 67 |
| N6 | band comparison reverts to `>=` | the "clears the bar" test faces the wrong way | **RED** 1 / 67 |
| N7 | penalty guard fails OPEN | a finite penalty reaches the planner as the campaign's best score | **RED** 2 / 66 |
| N8 | penalty guard NEGATES instead of refusing | policy invented on the operator's behalf | **RED** 2 / 66 |
| N9 | the startup guard is never called | a guard nobody calls is a comment | **RED** 1 / 67 |

N4 and N5 are the pair worth naming: both keep the range normalisation the design
asks for and would pass any test that only checked "the band is a fraction of the
range". Only a direction-aware expectation separates them.


### 14.3 — C4: authority-rendered task blocks, byte-exact under TIDMAD + OD-1 (P2)

**Commit `50a88b50` — `feat(step07/07b): C4 — task content rendered from its authority`.**

**Production diff**

```text
agent/prompt_templates/tuner/__init__.py      NEW
agent/prompt_templates/tuner/rendering.py     NEW — 5 renderers, frozen TunerTaskRender,
                                              build_tuner_task_render, and the ONE
                                              EFFICIENCY_BAND_FRACTION / EFFICIENCY_BAND_PCT
agent/prompts.py                              PLANNER/REFLECTOR tokens; render_collapse_advice;
                                              _builtin_roster; the planner USER builder takes
                                              task_render; OD-1 key order in _truncate_memory_history
agent/llm_bridge.py                           plan(..., task_render=None) + fail-closed + token
                                              substitution; reflect() substitutes the band constant
nodes/…/ml_hyperparameter_tune_agent.py       builds ONE TunerTaskRender at run scope and passes it;
                                              imports EFFICIENCY_BAND_FRACTION instead of defining it
```

**P2 ACCEPTANCE — MET.** After C4 the five Step-00 prompt goldens are byte-identical to
§14.0, with **nothing regenerated**:

```text
a691a7f5…c8e62  pb1_planner_auto_system.txt          UNCHANGED
3b8677e8…f198e  pb1_planner_auto_user.txt            UNCHANGED
b0cb4d90…f3aba  pb1_planner_force_punet_user.txt     UNCHANGED
3566caec…e1f95ac pb2_reflector_system.txt            UNCHANGED
81fa5f49…000e3e06 pb2_reflector_user.txt             UNCHANGED
```

That equality IS the acceptance criterion: every rendered token reproduces the literal it
replaced, so a P2 mistake shows up as a golden failure with no regeneration to hide behind.

**Rendered tokens and their authorities** (TIDMAD values, all byte-identical to the pre-C4
literals):

| Token | Authority | TIDMAD value |
|---|---|---|
| `{BUILTIN_MODEL_ROSTER}` (USER) | `MODEL_REGISTRY` order ∩ `BUILTIN_OUTPUT_TYPES` | `punet \| fcnet \| transformer \| wavenet \| rnn \| gated_fno` |
| `{FULL_SCOPE_SEGMENTS}` (planner SYSTEM) | run-bound `DatasetConfig` | `4000` |
| `{OUTPUT_CONTRACT_SHAPE}` (USER, force-model branch) | run-bound `ModelIOContract.output.render_shape()` | `[B, 256, T]` |
| `{FOCAL_ALPHA_DEFAULT}` / `{FOCAL_GAMMA_DEFAULT}` | `LossConfig` field defaults | `0.5` / `2.0` |
| `{GATE_OUTPUT_DIVERSITY_ADVICE}` / `{GATE_AMPLITUDE_COLLAPSE_ADVICE}` | the run's EFFECTIVE health config | both present → both sentences render |
| `{EFFICIENCY_BAND_PCT}` (planner + reflector SYSTEM, reflector USER) | `EFFICIENCY_BAND_FRACTION` | `5` |

The plugin-loaded registry is filtered by `BUILTIN_OUTPUT_TYPES`, so a workspace with 90
agent-generated plugins still renders the six built-ins in registry order — verified against a
live plugin-loaded interpreter, not only in the fixture.

**Where the run-scope build sits, and why.** `build_tuner_task_render` is called immediately
AFTER the effective-config path swap (`agent_input.health_checks_config = _effective_config_path`).
Built any earlier, the check names would come from the SHIPPED default rather than from the
config this run actually evaluates — the prompt would advise the planner about gates the run does
not run, which is precisely the failure §3.6's omission rule exists to prevent.

**Deviations from §3.6 (two, both bounded, both forced by P2's own byte rule).**

| # | §3.6 says | What was done, and why |
|---|---|---|
| 1 | RENDER the built-in loss list at `prompts.py:182-184` | **KEPT literal.** §3.6 quotes the literal unwrapped, but the shipped bytes WRAP MID-LIST — `pb1_planner_auto_system.txt:175-176` is `…the four built-ins (\`focal\`, \`focal_cw\`, \`ce\`,` / `` `smooth_l1`) — see the COMPATIBILITY section… ``. A single-token render moves the newline, i.e. an undeclared PB-1 delta, which P2's own acceptance rule and the frozen stop conditions forbid. Embedding the wrap inside the renderer was rejected: the next task pack would inherit TIDMAD's line wrapping from an "authority". `render_builtin_loss_types` was REMOVED rather than left consumer-less. Gap recorded beside §3.6's existing subset-ordering gap. |
| 2 | RENDER the full-scope anchor at reflector `:271`, `:274-275` | **KEPT literal.** §3.9 — corrected by an operator BLOCKER at revision 2 — is the ONE bridge contract, and it gives `reflect()` no `task_render`; adding one is an explicit stop condition ("WF-1/WF-2 changes beyond the frozen additive contract"). Only the PLANNER renders `{FULL_SCOPE_SEGMENTS}`. `{EFFICIENCY_BAND_PCT}` DOES render at both surfaces because it is a framework constant needing no transport. Gap recorded (Seam 3). |

Both are the §3.6 rule applied to itself: *a token renders from a landed authority, or it stays
a literal with the gap recorded*. Neither invents a field; neither changes a TIDMAD byte.

**Deviation 3 (placement).** `EFFICIENCY_BAND_FRACTION` moved from the tuner (where C3 put it)
to `agent/prompt_templates/tuner/rendering.py`. The import runs one way — the tuner imports the
renderers, and `agent/prompts.py` needs the percentage — so a constant in the tuner would make
`prompts.py → tuner → llm_bridge → prompts` a cycle. It is still exactly ONE symbol with two
consumers, which is what §3.3 row 4 requires; only its address changed.

**OD-1 CLOSED.** `_truncate_memory_history` now iterates the RECORD's own key order filtered by
`_CONDENSED_KEYS` membership. Before: 5 distinct key orders across 5 `PYTHONHASHSEED`s. After: 4
seeds → 1 byte-identical render. Sorting was rejected as a different defect — it would serialise
the same record one way inside the verbatim window and another way outside it. New golden
`pb1_planner_history4_user.txt` (7 735 chars) captured at this commit, clean tree; the ≤ 3-record
PB-1 goldens are untouched because that branch is never entered.

**WF-1 22 → 23, additive.** One new kwarg name, `task_render`; every pre-existing name and value
unchanged. `wf1_plan_call_round1_surface.json` pins it by CONTENT (`model_dump()`, unlike
`registry` which is pinned by type name) — its fields ARE the task facts the planner is told, so
a drift in any of them is what the baseline exists to catch. Both goldens carry the three-part
note. WF-2 untouched (no reflector surface change in C4).

**Test disposition.** NEW `tests/unit/agent/llm_bridge/test_step07b_c4_task_rendering.py` (17).
UPGRADED: `test_step00_prompt_goldens.py` gains `tidmad_task_render()` built from the SAME
shipped authorities production uses, so the goldens stay a production-truth pin;
`test_step00_choreography_baselines.py` projection; `test_llm_bridge.py`,
`test_plugin_source_excerpt.py`, `test_record_usage.py`, `test_stub_llm_bridge.py` thread the
kwarg. `StubLLMBridge` inherits the real `plan()`, so `--is_pseudo_llm` runs also need the
render — and get it, because the tuner always supplies it.

**Validation.**

```text
python -m pytest tests/unit/agent/llm_bridge -q -p no:randomly
  → 130 passed in 1.78s, rc=0   (PB goldens green, sha256 unchanged)
python -m pytest tests/unit/agent tests/unit/nodes tests/unit/workflows tests/unit/execute_tools \
      -q -p no:randomly
  → 5490 passed, 1 skipped in 406.00s (0:06:46), rc=0   (/tmp/07b_c4_all2.log)
ruff check . / ruff format --check .   → clean (934 files)
```

**One diagnosis worth keeping.** The first WF-1 run failed with an EMPTY diff — the deep-compare
said "diverged", the rendered diff showed nothing. Cause: `model_dump()` keeps
`gate_check_names` a `tuple`, the golden round-trips it through JSON as a `list`, and
`json.dumps(..., default=str)` renders the two identically. Fixed with `model_dump(mode="json")`.
Recorded because an empty diff is the least debuggable failure a golden can produce, and any
future tuple-valued projection will hit it.

**Mutation evidence (Checkpoint D rows 7, 12, 13).** Ten mutations, each applied to EXACTLY ONE
asserted site, caches cleared, baseline restored and re-proved green (`131 passed in 1.92s`,
`git status --short` clean). Selection: the C4 module + the PB goldens + the WF-1 baselines.

| # | Mutation | Defect it stands for | Observed |
|---|---|---|---|
| P1 | a rendered literal reinstated beside its token | the value silently stops coming from the authority while every golden stays green | **RED** 2 failed / 33 passed |
| P2 | the roster returns a hardcoded six-name list | a contrast task is told TIDMAD's architectures | **RED** 3 / 32 |
| P3 | full-scope segments returns `4000` | a 3-file task is told it should train on 4 000 segments | **RED** 3 / 32 |
| P4 | a missing contract renders `[B, 256, T]` anyway | a guessed shape makes every plan the planner produces invalid | **RED** 1 / 34 |
| P5 | collapse advice ignores the effective config | the planner is told to read a `failure_reason` the run can never emit | **RED** 1 / 34 |
| P6 | the bridge falls back instead of failing closed | TIDMAD hardcoded into the framework's prompt layer | **RED** 1 / 34 |
| P7 | OD-1 reverts to frozenset iteration | prompt bytes stop being reproducible across processes | **RED** 3 / 32 |
| P8 | OD-1 "fixed" by sorting the keys | the same record serialised one way inside the verbatim window and another way outside it | **RED** 2 / 33 |
| P9 | the prompt's band percent drifts from the policy constant | the agent optimises against a rule the tuner does not apply | **RED** 2 / 33 |
| P10 | focal defaults become literals | the reset advice desynchronises from what a reset produces | **SURVIVED → fixed → RED** 1 / 26 |

**P10 SURVIVED the first sweep, and that is the most useful result in this commit.**
`render_focal_defaults` replaced by `return ("0.5", "2.0")` passed every test in the module. The
reachability test compared the renderer against `LossConfig.model_fields["alpha"].default` — the
same value from the same place, so it agreed with the literal too. Classification: **REAL GAP in
the test architecture**, not an equivalent mutation. The only assertion that separates a render
from a literal PERTURBS the authority, so the test now monkeypatches the shipped defaults to
`0.25` / `3.5` and asserts the render follows. P10 is RED at `1 failed / 26 passed`.

P8 is worth naming beside P7: both close OD-1's instability, and only a record-order expectation
tells them apart. Sorting would have produced stable bytes and passed a naive stability test
while introducing a different defect.


### 14.4 — C5: direction / identity / diagnosis rendering + the final bridge surfaces (P3)

**Commit `a6b9e811` — `feat(step07/07b): C5 — the prompts state the declared direction`.**

**The declared §3.7 deltas, and NOTHING else.** Every regenerated golden line was reviewed
against the frozen list captured in §14.0. The diff is:

| Golden | Declared line(s) | Delta as landed |
|---|---|---|
| `pb1_planner_auto_system.txt` | 3 | `…to maximize the \`denoising_score\` metric (golden metric \`tidmad_denoising_score\` (higher is better)) across…` |
| " | 28 | `Goal: maximize the score with sufficient data.` |
| " | 81 | `A finite score such as \`-3.14\` is NOT collapse` — only "negative" → "finite", exactly as §3.7 decided |
| " | 97–104 | `### TRAINING vs VALIDATION — CRITICAL` → `### TRAINING DYNAMICS (per experiment, from its training history)`, with the direction word rendered ("does not move toward higher") |
| `pb1_planner_auto_user.txt`, `pb1_planner_force_punet_user.txt` | after the history JSON | NEW `### Training dynamics (last 3 experiments)` block; **the JSON block itself is byte-unchanged** |
| `pb2_reflector_system.txt` | 9–11 | `### CRITICAL — GAP ANALYSIS` → `### CRITICAL — TRAINING DYNAMICS` |
| " | new | `- The \`denoising_score\` field carries the golden metric \`…\` (higher is better).` |
| " | 23, 25 | direction-rendered; **byte-identical under TIDMAD** (`HIGHER`/`LOWER`), which is the point |
| " | 79–80 | `beats the best score (in the higher-is-better sense)` / `within 5% of the best score's observed range` |
| `pb2_reflector_user.txt` | 24–26 | the ⚠ NOTE → `### TRAINING DYNAMICS (this experiment)` + the rendered line |
| " | new | `golden metric \`tidmad_denoising_score\` (higher is better)` in the comparison context |
| " | 33 | rank line UNCHANGED — "(1 = best)" is already direction-correct because `rank` comes from the order authority |

No line outside this set moved. Line 63 of the reflector system prompt (`a lower final_loss …`)
is untouched, as §14.0 declared: it is LOSS direction, not metric direction.

**The fixture change that strengthened the goldens.** `_HISTORY_3`'s record 003 now carries a
real 07a `training_history` + `training_diagnosis`. Two effects, both wanted: PB-1 pins a
RENDERED dynamics line rather than only the `none recorded` path, and the history JSON above it
is **byte-unchanged** — the hidden-key contract proved on a golden, not only in a boundary test.

**Bridge surfaces — the frozen §3.9 contract, exactly.**

```text
plan(...,  task_render: TunerTaskRender | None = None,   # C4  WF-1 22 -> 23
           metric_spec: MetricSpec | None = None)        # C5  WF-1 23 -> 24   ✔ 24 measured
reflect(exp_id, hypothesis, actual_results, reflection_context=None, *,
           metric_spec: MetricSpec | None = None,
           training_diagnosis: TrainingDiagnosis | None = None)
           # WF-2 actual_results_keys == 9 EXACT ✔ · reflection_context_keys == 23 EXACT ✔
```

Both `None` values raise at a real render. The refusal messages say what the caller must supply
AND why there is no default — for `metric_spec` the reason is that "maximize" is not a partial
truth but an inverted goal on a minimised metric.

**Diagnosis transport (§3.8), as implemented.** The planner block is built inside
`get_planner_user_prompt` from `memory_history[-PLANNER_FULL_WINDOW:]` — the RAW window, before
`_truncate_memory_history` strips the hidden keys. `PLANNER_FULL_WINDOW` is now ONE symbol shared
with the truncation itself, so the block and the JSON beside it cannot disagree about which
experiments are "recent". The reflector receives the `TrainingDiagnosis` ONLY; its renderer is
called with `objective_kind=None`, and no `TrainingHistory` reaches it.

**Boundary tests UPGRADED, not replaced (§9 "KEPT ... extended").** Two needed real thought:

* `test_step06_planner_boundary::test_the_planner_prompt_is_byte_identical_with_and_without_the_payload`
  went red — correctly. Whole-prompt equality is now FALSE BY DESIGN, because 07b renders a
  summary of the payload; a test asserting it would have been asserting that the feature does
  nothing. The claim was restated where it is still true and is now SHARPER: the history JSON and
  all surrounding prose are byte-identical, the owned dynamics block deliberately differs, and the
  raw-key absence assertions still run against the FULL prompt. It additionally asserts
  `loaded != plain`, so the equality cannot be achieved by rendering nothing.
* `test_step00_prompt_goldens::test_pb1_full_window_boundary_is_the_deferral_line` was OD-1's
  deferral record. OD-1 is closed, so the test was renamed to what it still pins — which branch
  each history length takes — with the history preserved, and its identity assertion now compares
  against `_planner_visible`'s projection plus a non-vacuity guard.

**Test-harness widening.** `RecordingLLMBridge.reflect` gained `**kwargs` and records them as a
SIXTH tuple element, so WF-2 can pin the additive kwargs without disturbing the 5-element shape
every existing consumer indexes into.

**Validation.**

```text
python -m pytest tests/unit/agent/llm_bridge/test_step07b_c5_rendering.py -q -p no:randomly
  → 38 passed in 1.20s, rc=0
python -m pytest tests/unit/agent -q -p no:randomly
  → 4126 passed in 283.47s, rc=0
python -m pytest tests/unit/agent tests/unit/nodes tests/unit/workflows tests/unit/execute_tools \
      tests/unit/core -q -p no:randomly
  → 7955 passed, 3 skipped in 512.86s — with ONE failure, diagnosed below, then
    5260 passed / 1 skipped in 371.09s over the affected suites after the fix
ruff check . / ruff format --check .   → clean (935 files)
```

**The one C5 failure, and why it was the most valuable result of the commit.**
Step 06's C5 guard (`test_no_production_surface_executes_a_direction_literal_outside_the_metric_module`)
went red on `agent/prompt_templates/tuner/rendering.py`. The cause was real, not cosmetic:
`render_metric_direction_words` computed its words from `spec.direction == "higher"` — a THIRD
module reading the declaration, which is precisely the pattern 07b exists to remove and which
every behavioural test would have passed. The fix is structural, not an allowance: the words moved
onto `MetricOrder.direction_words`, and the renderer delegates. The guard's order-module clause is
now an exact multiset (`higher ×3, lower ×2`) rather than an open allowance, so this module cannot
quietly grow into a second authority either.

That guard has now caught two genuine 07b defects (this one, and C2's un-migrated tuner rows). It
is worth keeping exactly as strict as it is.

**Mutation evidence (Checkpoint D rows 9, 10, 11).** Ten mutations, each applied to EXACTLY ONE
asserted site, caches cleared, baseline restored and re-proved green (`169 passed`,
`git status --short` clean).

| # | Mutation | Defect it stands for | Observed |
|---|---|---|---|
| Q1 | direction words hardcode maximize/higher/lower | TIDMAD's convention reinstated as the framework's | **RED** 7 failed / 48 passed |
| Q2 | the identity line drops the direction | the metric is named but the goal is left implicit | **RED** 9 / 46 |
| Q3 | the planner block is built AFTER the hidden keys are stripped | the dynamics block silently renders "none recorded" forever | **RED** 4 / 51 |
| Q4 | the raw diagnosis is dumped instead of rendered | the Step-06 leak, repeated with 07a's payload | **RED** 5 / 50 |
| Q5 | the renderer emits a calibrated label | a threshold nobody declared, presented as a finding | **RED** 7 / 48 |
| Q6 | an absent history renders nothing | "no history" reads to the LLM as "unremarkable training" | **RED** 5 / 50 |
| Q7 | `plan()` falls back instead of failing closed | a minimised campaign told to maximise | **RED** 1 / 54 |
| Q8 | `reflect()` falls back instead of failing closed | every regression praised | **RED** 1 / 54 |
| Q9 | the reflector is handed the TrainingHistory too | the transport §3.8 explicitly refuses | **RED** 1 / 54 |
| Q10 | the objective label leaks into the reflector line | the reflector-only distinction collapses | **RED** 1 / 54 |

Q3 is the one worth naming: it produces a prompt that is *structurally* correct — the heading is
there, one line per record — and says "none recorded" for every experiment forever. Only an
assertion on the rendered CONTENT catches it, which is why the boundary test asserts the real line
`[focal] train 0.02->0.01` and not merely that the block exists.


### 14.5 — Gate-1 readiness packet (Checkpoint C)

Written BEFORE launch, per the Working Rules and the Gate standard.

**Approval provenance.** The Implementation Working Rules contract for this PR
(operator, 2026-08-16) PRE-AUTHORIZES exactly ONE bounded Gate 1 and forbids Gate 2.
The Gate standard's `Needs user approval: yes` is satisfied by that contract; the repository's
launch hook additionally requires the approval to be recorded explicitly at the command
(`SIDERIUS_ALLOW_LAUNCH=1`), which this run does.

**The ONE property this Gate proves.** That a real LLM, given the P3-changed SYSTEM prompts,
produces structurally valid planner and reflector output — and, specifically to 07b, that a
SECOND tuner round's planner message actually carries the FIRST round's rendered training-dynamics
line and the correct metric-direction wording. Deterministic tests cannot prove that: they pin the
renderers and the boundary, but not that a frontier model still returns a schema-valid
`ExperimentPlan` after the compensating "Low training loss + poor score → overfitting" rule was
REPLACED by facts, nor that the round-1 → round-2 transport survives a real run.

**Why Gate 2 is not required and is NOT run.** 07b changes no training, inference or scoring
LAUNCH or execution semantics. The one production behaviour change outside prompts is ordering /
threshold resolution, and its parity under TIDMAD is proved deterministically by the C1 replay
oracle.

**Source re-audit at the final executable head** (all confirmed at `a6b9e811`, not from memory):

| Flag | Parsed at | Effect |
|---|---|---|
| `--mode lilab` | `_chain_common.sh:335` | foreground subprocess |
| `--num_iterations 2` | `:280` | two chain iterations |
| `--max_rounds 2` | forwarded to the tuner | round 2 is the forced formal round |
| `--is_pseudo_training` | `:378` → `APP_ARGS:485` | StubSandbox; 07a multi-epoch histories, so the dynamics lines render from a real trajectory |
| `--no-health_gate_enabled` | `:307` (`HEALTH_GATE_ENABLED=0`) → `APP_ARGS:505` | records self-describe `health_gate_enabled=False` (stamped at `ml_hyperparameter_tune_agent.py:4504, 6322, 6672`), so `classify_candidate_health` (`candidate_eligibility.py:169-175`) returns VALID for successful finite-score records — the ONLY existing posture under which pseudo records are valid candidates. No production HealthGate code is touched and no 07b-specific exception exists. |
| `--enable_chain_incumbent_formal_gates` | `:316` → `APP_ARGS:557` | the delta gates consume the chain incumbent: iteration 1 the bootstrap (worst-sentinel) reference, iteration 2 the restored valid formal incumbent |
| `--data_scope 4-9` | forwarded | partial scope; legal because the chain's `FORMAL_STRATEGY` default is `snapshot` (`:130`) and the health subsystem is disabled, so `validate_runtime_config`'s two partial-scope refusals do not apply |
| `--llm_config llm_configs/openai_tiered_pro.json` | forwarded | gpt-5.5 for planner, reflector, proposer, implementor, validator (binding policy, standard §"Real-LLM Gate config") |

Cold start — **no `--seed_paths`** (operator rule 2026-07-27).

**Exact command** — the frozen §7 command, after the audit above, with the launch approval
recorded at the command per the repository hook:

```text
SIDERIUS_ALLOW_LAUNCH=1 bash sdsc_submission_scripts/<chain launcher> --mode lilab \
    --workspace /home/klz/Data/SIDEREIS_DATA/step07b_gate1 --run_name gate1_07b \
    --num_iterations 2 --max_rounds 2 --max_proposal_attempts 3 --max_epochs 1 \
    --data_scope 4-9 --is_pseudo_training --no-health_gate_enabled \
    --enable_chain_incumbent_formal_gates \
    --llm_config llm_configs/openai_tiered_pro.json
```

**Bounds owned by the HARNESS, not the planner**: 2 iterations × 2 rounds × ≤ 3 proposal
attempts, `--max_epochs 1`, 6-file scope, pseudo training (no GPU work, no real training loop).
Expected ≈ 8–16 min, ≈ $0.6. **Hard stop at 40 min** — a longer run is a validation-DESIGN finding,
not a reason to wait.

**PASS evidence, recorded SEPARATELY (§7):**

*A — within-tuner round evidence (REQUIRED).* At least ONE tuner invocation completes
round 1 → persisted/rendered round-1 result → round-2 planner invocation, and the round-2 planner
message contains the round-1 rendered dynamics line; the direction wording is present; the
reflector message contains the current diagnosis block; NO raw `training_history` /
`training_diagnosis` / `metric_result` / `metric_refusal` key appears in any message. Two outer
iterations without a round-2 tuner invocation do NOT satisfy this.

*B — policy / reference evidence.* The ordering / incumbent helpers are REACHED and their resolved
values recorded: `formal_comparison_reference_source`, `resolved_skip_formal_threshold`,
`resolved_bypass_formal_threshold`, `formal_reference_score` in each `run_output`, the
`[SkipFormal]` / winner banners in the chain log, and the five `best_*` tracks. "Executed" means
reached with the verdict recorded — NOT that skip and bypass both evaluate True, which are mutually
exclusive. Bypass is reachable only when a formal round's time check is infeasible, which pseudo
training does not guarantee; its absence is recorded, not failed, because B-07b-1 / 1s cover it
deterministically.

**Failure classification decided in advance:** a schema-invalid plan or reflection on the new
wording is a semantic FAIL owned by 07b (the wording is the child's to fix; rerun only after a
substantive fix, never a reroll of unchanged bytes). Pseudo records collapsing despite
`--no-health_gate_enabled` is a HARNESS incompatibility → STOP and re-plan, never a 07b-specific
health exception. An API/transport error is transient under the standard's rule.


### 14.6 — Gate-1 attempt 1: INCONCLUSIVE (harness), and the finding it produced

| Field | Value |
|---|---|
| Executable HEAD | `a6b9e811` (C5); docs head `63fb3b4f` |
| Command | the §14.5 packet's command, verbatim, with `SIDERIUS_ALLOW_LAUNCH=1` |
| Workspace | `/home/klz/Data/SIDEREIS_DATA/step07b_gate1` (PRESERVED) |
| Log | `/tmp/07b_gate1.log` |
| Wall time | 10 min 4 s (14:43:30 → 14:53:34), chain exit code 0 |
| Cost | 461 751 tokens over 19 real gpt-5.5 calls (iter 1: 215 866; iter 2: 245 885) |
| Verdict | **INCONCLUSIVE — the required criterion A could not be reached under the frozen posture.** NOT a semantic FAIL: nothing 07b changed misbehaved. |

**What happened.** Both iterations ran exactly ONE tuner round. The chain completed cleanly and
every 07b surface behaved, but `ROUND 2/2` never started, so the round-1 → round-2 planner
evidence criterion A requires does not exist.

**Root cause — a pre-07b coupling, found by reading the log and the record, not guessed:**

```text
no --trial_time_budget_minutes / --formal_time_budget_minutes in the frozen §7 command
  -> "[time-gate disabled / trial|formal] ... will not gate ... rounds"   (log :229-230, :538-539)
  -> time_check is None at the round boundary
  -> ml_hyperparameter_tune_agent.py:6238 `if time_check is not None:` is FALSE
  -> memory.time_mode is NEVER STAMPED on the record        (the write lives at :6244, inside that guard)
  -> _best_trial_winner's two-field agreement rule (:1556-1562) can never be satisfied
  -> winner is None -> _should_skip_formal returns True (the D-C3 "no evidence" branch)
  -> `break` -> "Completed 1 research rounds. Loop terminated."
```

The round-1 record confirms every link: `status=success`, `denoising_score=-2.4310…`,
`is_trial=True`, `health_gate_enabled=False`, `best_valid_trial_exp_id` SET (so the record IS a
valid candidate — the `--no-health_gate_enabled` posture worked exactly as §14.5 predicted) — and
`memory.time_mode = None`.

**This is not a 07b regression.** The two-field agreement rule is pre-07b, is quoted in this
design's own §0.1 census, and C1's corpus carries a dedicated `h_time_mode_mismatch` case for it.
C2 preserved it verbatim (replay deep-equal). `git log -S` dates the `time_mode` write to the
pre-Step-00 node restructure (`081d6512`). 07b neither introduced nor could have prevented it.

**What DID work in this run** (recorded because it is real evidence, just not the required kind):

* the `--no-health_gate_enabled` posture yielded VALID pseudo records — the exact property §14.5
  had to audit from source, now confirmed at runtime;
* `formal_comparison_reference_source = "negative_infinity_bootstrap"` in iteration 1, i.e. the
  C3 bootstrap sentinel resolved through the order authority on a real run;
* the round-1 record carries a `training_diagnosis` (07a), so the planner's dynamics block had
  real content to render;
* 19 real gpt-5.5 calls across planner, reflector, proposer, implementor and validator completed
  with schema-valid output on the P3-changed prompts — every round-1 planner message and every
  reflector message rendered without a single schema failure.

**FINDING (production, recorded — NOT fixed here).** The coupling above is not only a harness
inconvenience. With `--enable_chain_incumbent_formal_gates` ON and both time budgets OFF —
a configuration the CLI accepts and the chain defaults to — `memory.time_mode` is never stamped,
so `_best_trial_winner` is unconditionally `None` and **every forced formal round is skipped for
"no evidence"**, in every iteration, forever. The campaign silently never produces a formal score.
Owner: the same round/gate-semantics correction that owns the `resolved_action` hazard (§3.5) —
it is neither 07b's (which may not change retry/round semantics) nor 07c's. Two candidate fixes,
both needing an operator decision: stamp `time_mode` unconditionally from `plan.is_trial` (it is a
property of the PLAN, not of the gate), or drop the `memory.time_mode` half of the agreement rule
now that `is_trial` is a typed record field.

**Disposition.** Per the Working Rules early-stop list — *"Gate 1 cannot reach a real tuner
round 2 within the frozen bounded harness"* — this is a STOP, not an autonomous re-plan. The
minimal correction is a HARNESS parameter and touches no production code:

```text
+ --trial_time_budget_minutes 20 --formal_time_budget_minutes 120
```

which is also the standard baseline posture in `CLAUDE.md` ("Without them, a badly-chosen
`trial_portion` from the LLM planner can produce multi-hour trial rounds"). With the time gate
live, `time_mode` is stamped, the trial winner resolves, the skip gate evaluates on a real
threshold instead of the no-evidence branch, and round 2 runs as the forced formal round. The
tested SHA does not change, so this is a rerun after a substantive harness fix under the Gate
standard's rule — not a reroll of unchanged bytes.

**Awaiting operator authorization** for that one corrected rerun (≈ 10 min, ≈ 460 k tokens
expected, same bounded envelope). Artifacts from attempt 1 are preserved at
`/home/klz/Data/SIDEREIS_DATA/step07b_gate1`.


#### 14.6a — Gate-1 attempt 2: OPERATOR-APPROVED harness correction

**Approval.** The operator reviewed §14.6 and accepted attempt 1 as
**INCONCLUSIVE — HARNESS REACHABILITY**, explicitly *not* a 07b semantic failure, and accepted the
source-grounded finding as pre-07b behaviour that **MUST NOT be fixed in this PR**. Exactly ONE
corrected rerun is authorized, at the SAME executable HEAD and the SAME frozen Gate semantics,
adding ONLY the two time-budget flags. The PASS criteria are unchanged.

**Pre-launch checks, in the order the operator required:**

| # | Check | Result |
|---|---|---|
| 1 | executable HEAD still `a6b9e811` | `a6b9e811a6f8ecf075bea928ce0fb5f68870f5d4`. `git diff --stat a6b9e811 HEAD` over `nodes/ agent/ execute_tools/ workflows/ core/ ml_models/ scripts/ sdsc_submission_scripts/ dashboard/` returns ONLY `ml_hyperparameter_tune_agent.md` — a markdown doc. **No executable code changed since C5.** |
| 2 | working tree clean | `git status --short` empty |
| 3 | attempt-1 artifacts preserved | `/home/klz/Data/SIDEREIS_DATA/step07b_gate1`, 760 K, 2 `run_output_*.json` — untouched, not deleted, not modified |
| 4 | NEW workspace for attempt 2 | `/home/klz/Data/SIDEREIS_DATA/step07b_gate1_attempt2`, run name `gate1_07b_attempt2` — confirmed absent before launch (cold start) |
| 5 | this record | written before launch |
| 6 | command = attempt 1 + only the two flags | see below |
| 7 | the two flags re-audited from CURRENT source | `_chain_common.sh:93-94` (default empty == omit == Python `None`), parsed at `:310-311`, forwarded at `:527-533` **only when non-empty**, and accepted by `run_one_iteration.py:1172, 1178`. Nothing else in the command changes. |

**The corrected command** (delta from attempt 1 is exactly the workspace/run identity and the two
flags — no production code, no prompt bytes, no policy, no Gate criteria):

```text
SIDERIUS_ALLOW_LAUNCH=1 bash sdsc_submission_scripts/<chain launcher> --mode lilab \
    --workspace /home/klz/Data/SIDEREIS_DATA/step07b_gate1_attempt2 \
    --run_name gate1_07b_attempt2 \
    --num_iterations 2 --max_rounds 2 --max_proposal_attempts 3 --max_epochs 1 \
    --data_scope 4-9 --is_pseudo_training --no-health_gate_enabled \
    --enable_chain_incumbent_formal_gates \
    --trial_time_budget_minutes 20 --formal_time_budget_minutes 120 \
    --llm_config llm_configs/openai_tiered_pro.json
```

**Why this reaches round 2**, stated as a prediction before the run so the result can falsify it:
with the budgets set, `evaluate_time_skill` gates both modes, so `time_check` is not `None` at the
round boundary, so `ml_hyperparameter_tune_agent.py:6244` stamps `memory.time_mode`, so
`_best_trial_winner`'s two-field agreement resolves the round-1 record as the winner, so
`_should_skip_formal` evaluates a real threshold instead of taking the "no valid trial winner"
branch — and round 2 runs as the forced formal round.

**Standing constraints for this attempt** (operator): no reroll if a genuine 07b semantic failure
appears — STOP; no second harness change if round 2 is still unreachable — STOP and report the new
source-grounded blocker; no Gate 2; no real training.


#### 14.6b — Gate-1 attempt 2: **PASS**

| Field | Value |
|---|---|
| Executable HEAD | `a6b9e811` (unchanged from attempt 1 — only `.md` and a test file differ) |
| Workspace | `/home/klz/Data/SIDEREIS_DATA/step07b_gate1_attempt2` (attempt 1 preserved separately) |
| Log | `/tmp/07b_gate1_a2.log`, chain exit code 0 |
| Wall time | 40 min 54 s (14:56 → 15:24), within the 40-min-per-attempt envelope's intent; iteration 1 spent 20 min on 16 guardrail-rejected formal attempts (see below) |
| Cost | ~19 real gpt-5.5 calls per iteration across planner / reflector / proposer / implementor / validator |
| Verdict | **PASS** — criterion A satisfied by iteration 2; criterion B recorded in full |

**The prediction in §14.6a held.** With the time gate live, `memory.time_mode` is stamped
(`trial` on round-1 records, `formal` on round-2 records — visible on every record in both
iterations, where attempt 1 had `None`), `_best_trial_winner` resolved the winner, and the skip
gate stopped taking the no-evidence branch. Iteration 1's log shows
`[FORMAL OVERRIDE] strategy=full_clone winner='…_iter_001_001' score=-2.4310` — the winner
resolving, which is precisely what attempt 1 could not do.

---

**A — WITHIN-TUNER ROUND EVIDENCE (the REQUIRED criterion): SATISFIED.**

Iteration 2 completed a full tuner cycle: `completed_rounds: 2`, `status: completed`,
`ROUND 1/2 … Round 1/2 Complete. Score: -2.3323` → `ROUND 2/2 … Round 2/2 Complete.
Score: -2.3869`. Both records carry `training_diagnosis.state == "ok"`.

*Round-2 planner content.* Rebuilt through the PRODUCTION builder
(`agent/prompts.py::get_planner_user_prompt`) from the run's own persisted round-1 record — the
same input the bridge passed at round 2:

```text
### Training dynamics (last 1 experiments)
- multiscale_spectral_unet_tcn_v1_iter_002_001: [custom] train 10.94->3.90 (decreasing, 5 ep)
  · val 12.49->5.58 (decreasing; best ep 3, +0.26 after best) · gap n/a (not comparable)
```

Real values from a real 5-epoch pseudo trajectory, the objective-family label from the record's
`training_history.objective_kind`, the best-validation epoch and the post-best drift — and the
`gap n/a (not comparable)` branch, exercised at runtime because this run's R2/R3 comparability
was `not_established`. That is a live instance of the branch C5 pinned deterministically.

*Direction wording*, rendered from the bound handle:

```text
Your goal is to maximize the `denoising_score` metric (golden metric `tidmad_denoising_score`
  (higher is better)) across hyperparameter configurations for the following task:
  loss_type, and regularization. Goal: maximize the score with sufficient data.
- The `denoising_score` field carries the golden metric `tidmad_denoising_score` (higher is better).
- A result is GOOD if its denoising_score is HIGHER than the best score so far.
- A result is BAD if it is LOWER than most previous scores.
```

*Reflector*, for the round-2 attempt:

```text
### TRAINING DYNAMICS (this experiment)
  train 8.89->3.76 (decreasing, 5 ep) · val 10.16->4.91 (decreasing; best ep 3, +0.16 after best)
  · gap n/a (not comparable)
```

*Hidden-key leak: ZERO.* `training_history`, `training_diagnosis`, `metric_result`,
`metric_refusal`, `objective_config_fingerprint`, `flat_rel_tol` and `objective_kind` are all
ABSENT from both messages, while the round-1 record demonstrably CARRIES `training_history`,
`training_diagnosis` and `metric_result` — so the absence is the boundary working, not an empty
payload.

*Honest scope of this evidence.* No `_chat_json` tee was enabled (that would have been a second
harness change, which the operator gated), so the blocks above are rendered through the production
functions from the run's persisted artifacts rather than captured off the wire. What the run
itself proves directly is that every planner and reflector call at every round returned
schema-valid output on the P3-changed prompts — 4 tuner rounds and 2 reflections across the two
iterations, zero parse or validation failures — and that the records the renderers consume exist
with the content shown.

---

**B — POLICY / REFERENCE EVIDENCE.**

| Surface | Iteration 1 | Iteration 2 |
|---|---|---|
| `formal_comparison_reference_source` | `negative_infinity_bootstrap` | `negative_infinity_bootstrap` |
| `formal_reference_score` / skip / bypass thresholds | `null` ×3 (the `_json_safe_reference` image of the worst sentinel) | `null` ×3 |
| trial winner resolved | YES — `[FORMAL OVERRIDE] … winner='…_iter_001_001' score=-2.4310` | YES |
| `best_exp_id` / `best_denoising_score` | `…_iter_001_001` / `-2.4310` | `…_iter_002_001` / **`-2.3323`** |
| `best_formal_denoising_score` | `None` | `-2.3869` |
| `best_valid_exp_id` / score | `…_001` / `-2.4310` | `…_002_001` / `-2.3323` |
| `best_valid_formal_exp_id` / score | `None` | `…_002_002` / `-2.3869` |
| `best_valid_trial_exp_id` / score | `…_001` / `-2.4310` | `…_002_001` / `-2.3323` |

Iteration 2 is the informative row: the five tracks do NOT collapse to one record. The trial
scored `-2.3323` and the formal `-2.3869`, so `best_*` (unfiltered) and `best_valid_trial_*`
selected the TRIAL record while `best_valid_formal_*` selected the FORMAL one — the order
authority choosing the higher value under `higher`, on real data, with the filters intact.

*Regimes reported honestly.* BOTH iterations resolved the BOOTSTRAP reference, not the restored
incumbent. Iteration 1 produced no valid FORMAL record (all 16 formal attempts were rejected
before training, below), so iteration 2 had no incumbent to restore. The
`restored_valid_formal_incumbent` regime was therefore NOT exercised by this Gate. Per §7 and the
operator's criteria this is recorded, not failed: it is covered deterministically by the C1 replay
corpus (`restored_*` scenarios) and by rung B-07b-1s (both directions).

*Bypass* was not reached — it fires only when a formal round's time check is infeasible, which did
not occur. Recorded, not failed, exactly as §7 provides; B-07b-1 / 1s cover it deterministically.

*Skip gate*: reached at the formal-round boundary in both iterations with a real winner and a
sentinel threshold, and it correctly did NOT fire (a bootstrap threshold is the worst value, so no
winner can be worse than it) — the C2/C3 sentinel semantics on a live run.

---

**SECOND FINDING (production, recorded — NOT fixed here).** Iteration 1 burned all 16 formal
attempts on:

```text
[Guardrails §5] SKIPPED: formal batch_size 2 below min_formal_batch_size 4
```

The planner explicitly proposed `batch_size=4` from attempt 2 onward and said so in its reasoning,
but `formal_round_strategy=full_clone` INHERITS `batch_size` from the trial winner (`=2`), so the
guardrail kept seeing 2 and every attempt was rejected before training. The planner cannot escape
it: the inheritance overwrites the very field the guardrail rejects. Unrelated to 07b (no
ordering, scale rule, renderer or bridge surface is involved) and not fixed here. Owner: the
formal-round-strategy / RT5-guardrail interaction — an operator decision on whether `full_clone`
should exempt fields a launch guardrail constrains, or whether the guardrail should be evaluated
before inheritance.

**The tuner structural decomposition intentionally preserves the pre-existing
`memory.time_mode` / no-time-budget coupling. That defect is not corrected here; it is
reserved for the immediately following dedicated Step-07 round-state semantics
correction PR.**

**Deferred debt carried forward from attempt 1**, restated as the operator required:

```text
enable_chain_incumbent_formal_gates=True + trial/formal time budgets disabled
  -> memory.time_mode remains unset
  -> a valid trial can never become _best_trial_winner
  -> the forced formal round is skipped forever as "no evidence"
```

NOT fixed in 07b.


### 14.7 — Terminal deterministic validation (final executable head `a6b9e811`)

```text
python -m pytest tests/unit -q -p no:randomly          (clean tree, docs head 63fb3b4f)
  → 9770 passed, 3 skipped, 405 warnings in 679.30s (0:11:19), rc=0     /tmp/07b_full.log
ruff check .            → All checks passed!
ruff format --check .   → 936 files already formatted
```

The suite ran from a CLEAN tree (`git status --short` empty), per the standing rule — a
work-in-progress tree makes the full-suite result meaningless.

**`pyright` could NOT be run locally, verified rather than assumed** (CLAUDE.md's
environment-assumptions rule: check the tool can actually run before claiming a local check).
`.venv/bin/pyright` exists and `--version` succeeds (`v10.19.0` — that is the NODE version it
reports, not pyright's), but an actual analysis run dies immediately in the bundled JavaScript:

```text
.venv/lib/python3.12/site-packages/pyright/dist/dist/vendor.js:2
SyntaxError: Unexpected token =
    at Module._compile (internal/modules/cjs/loader.js:723:23)
```

Node 10.19 cannot parse pyright 1.1.409's bundle. So the local static evidence for this PR is
ruff + `ruff format --check` only, and **exact-head CI is the authoritative pyright verdict** — it
is not being skipped, it is being run where it can run.

Checkpoint-D mutation total across C2–C5: **38 mutations, 37 RED on the first sweep, 1 SURVIVOR**
(C4's `render_focal_defaults`), classified as a real gap in the test architecture, fixed by
perturbing the authority, and re-proved RED.



### 14.8 — Checkpoint E: the ladder, state by state

| Checkpoint | State | Evidence |
|---|---|---|
| **0** — pre-edit baselines | **PASS** | §14.0. 12-history corpus + SEL-1a/1b/1c goldens captured at `f17bbdb8` against byte-unchanged production; PB-1 (3) / PB-2 (2) / WF-1 (2) / WF-2 sha256 recorded; the §3.7 declared-delta line-set transcribed verbatim (two drifted reading-aid line numbers corrected); OD-1 instability reproduced across 5 hash seeds; `run()` branch baseline 244. C1 is test-only — `git diff` over production empty. |
| **A** — Stage-A parity | **PASS** | Replay deep-equal under `higher` after C2 (twice: verbatim extraction, then the authority rewire) and after C3 (the range-normalised band and `toward_better` margins reproduce every captured value). PB-1/PB-2 sha256 IDENTICAL to §14.0 after C4 — nothing regenerated. PB regenerated in C5 ONLY on the §3.7 lines, diff reviewed line by line (§14.4 table). WF-1 22 → 23 → 24 additive; WF-2 `actual_results_keys` 9 EXACT / `reflection_context_keys` 23 EXACT. REC goldens untouched (no record change). `run()` AST branch count **244 → 198**. |
| **B** — Stage-B rungs | **PASS** | **B-07b-1** ordering axis (`test_step07b_c2_order_consumers.py`, 35): every ordinal consumer inverts exactly, ties stay first-wins, the loss rank does NOT move, invalid/non-finite records scored to win under the bound direction still never win. **B-07b-1s** scale axis (`test_step07b_c3_scale_rules.py`, 28) on accuracy-like ↑ and MSE-like ↓ scales. **B-07b-2** rendering axis (`test_step07b_c5_rendering.py`, 38) over the `lower` spec + Pets `accuracy`↑ + DAVIS `mse`↓, each from the pack's OWN `declared/metric_*.json` and 07a fixture. **B-07b-3** task-content axis (`test_step07b_c4_task_rendering.py`, 27) with a contrast profile / contract / renamed health checks. |
| **C** — Gate 1 | **PASS** | §14.6b, attempt 2. Attempt 1 (§14.6) is preserved as INCONCLUSIVE — harness reachability, operator-accepted. |
| **D** — mutation / reachability | **PASS** | 38 mutations across C2–C5, each applied to exactly ONE asserted site with caches cleared and the baseline restored and re-proved green. 37 RED on the first sweep; ONE survivor (C4's `render_focal_defaults`) classified as a real gap in the test architecture, fixed by perturbing the authority, re-proved RED. Full matrices in §14.1 / §14.2 / §14.3 / §14.4. Every family the parent's Checkpoint D names is covered: direction comparison, sentinels, scale rules, invalidated outcome, template-literal reintroduction, authority-bypass reachability, raw-key leak, calibrated vocabulary, fail-closed render authorities, OD-1 cross-process, `run()` branch count. `AttemptTransition` parity is N/A (REMOVED); round/retry parity is green via the untouched round/attempt suites. |
| **E** — governance | **PASS** | Pack rows (TIDMAD production-backed; Pets/DAVIS L1, no execution claim) + `tests/unit/examples/test_step07b_pack_pins.py` checking each claim against the thing it claims about; the tuner node `.md`; `docs/design/genericity_contract.md` Seam 4 closed for the tuner consumers and Seam 3 gaining a recorded gap table; README index, `docs/README.md`, roadmap §15.1/§22.12, parent §8.3 and `CLAUDE.md` rows. Terminal validation §14.7: full unit suite **9770 passed / 3 skipped / rc=0** from a clean tree; ruff and format clean. |

**Deviations from the frozen design: THREE, all bounded, all recorded with source evidence.**

1. §14.3 — the built-in loss list at `PLANNER_PROMPT` stays literal. §3.6 says RENDER, but the
   shipped bytes wrap mid-list, so a single-token render moves an LLM-visible byte that P2's own
   acceptance rule forbids. `render_builtin_loss_types` was removed rather than left
   consumer-less; the gap joins §3.6's existing loss-prose gaps.
2. §14.3 — the reflector's full-scope anchor stays literal. §3.9 (an operator BLOCKER correction)
   gives `reflect()` no `task_render`, and widening it is an explicit stop condition.
3. §14.1 / §14.2 / §14.4 — three members added to the ONE order authority: the two banner symbols,
   `direction_words`, and `penalty_convention_applies`. Each keeps an interpretation of
   `direction` from escaping into a second module; the third exists because the alternative was
   `order.direction == "higher"` inside the tuner, which Step 06's C5 guard correctly rejects.

**Deferred debt discovered during implementation, recorded and NOT fixed** (all outside 07b's
authority, all needing an operator decision on intended semantics):

1. `resolved_action` is round-scoped, written seven nesting levels down and never reset between
   attempts, so an attempt that leaves early inherits the last SCORED attempt's gate action (§3.5;
   note at the declaration in `run()`).
2. Chain-incumbent gates ON + time budgets OFF ⇒ `memory.time_mode` never stamped ⇒ every forced
   formal round skipped forever as "no evidence" (§14.6).
3. `formal_round_strategy=full_clone` inherits `batch_size` from the trial winner, so the RT5
   `min_formal_batch_size` guardrail can reject every formal attempt no matter what the planner
   proposes (§14.6b).


---

## 14.9 — C7: tuner node structural decomposition (operator scope amendment, 2026-08-16)

**Authority.** An operator SCOPE AMENDMENT to the current 07b PR, not a design revision. The
frozen revision-2 semantic sections are untouched and no revision 3 exists. C7 is a **structural
decomposition with ZERO intended behaviour change**; the amendment additionally moves all live Gate
closure to the post-refactor executable head and adds ONE bounded Gate 2 as a refactor-regression
check.

**State when the amendment arrived** (the amendment quoted `3d7af91b`; the branch had moved on):

| Fact | Value |
|---|---|
| HEAD | `4b13a548` — the pyright fix; `8c18eeb8` was pushed |
| Gate 1 | **already rerun and PASSED** at executable head `a6b9e811` (§14.6b), with exactly the corrected posture the amendment authorizes |
| PR | **#216 already OPEN**; exact-head CI `31976419268` FAILED on two pyright errors, fixed in `4b13a548` |

Nothing is discarded: under the amendment the live Gates move to the post-C7 head, so §14.6b
becomes **pre-refactor** Gate evidence and the new head earns its own Gate 1 + Gate 2. Attempt 1's
workspace and ledger entry (§14.6) remain untouched, as required.

### 14.9.0 — Decomposition audit (recorded BEFORE any production movement)

**Baseline shape** (`nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py`):

```text
file                                  7,430 lines
HyperparamTuningAgent                 2,786   [4053-6838]
HyperparamTuningAgent.run             2,714   [4125-6838]
main                                    578   [6849-7426]
92 top-level symbols (AST inventory: /tmp/claude-1004/c7_baseline/inventory.txt)
```

**Ownership table.** Every top-level symbol classified. Five node-local modules, at the bound the
amendment sets — no `utils`/`helpers`/`common`/`misc`.

| Module | Owns (symbol — lines) |
|---|---|
| **`policy.py`** — decisions on already-computed values; no I/O, no runtime APIs | `_build_reflection_context` 175 · `_apply_mode_override_chain` 153 + `_strategy_full_clone` 22 / `_strategy_hybrid_params` 12 / `_strategy_independent` 7 / `_canonical_strategy` 7 / `_LEGACY_STRATEGY_ALIASES` / `_FORMAL_STRATEGY_REGISTRY` · `_validate_data_config` 63 · `_resolve_formal_comparison_thresholds` 61 · `_apply_degeneracy_reaction` 59 · `_gate_results_to_score_meta` 52 · `_resolve_sample_set_cfg` 48 · `_compute_termination_state` 45 · `_should_skip_formal` 42 · `_validate_penalty_for_direction` 38 · `_select_best_records` 38 + `BestTracks` 28 · `_latest_trial_inference_marginal` 31 · `_best_trial_winner` 29 · `_decide_round_outcome` 24 + `RoundDecision` 6 + `_should_break_iteration` 4 + `_should_skip_to_formal` 8 · `_apply_plan_overrides` 24 · `_should_bypass_formal_time_budget` 23 · `_merge_score_validity_failure` 23 · `_json_safe_reference` 23 · `_non_retryable_termination_message` 14 · `_fmt_reference` 8 · `_identity` 3 · `_score_of` 3 |
| **`runtime.py`** — coordination of runtime-control / preflight APIs; owns none of their science | `_resolve_time_check_probe_request` 209 · `_handle_prephase_gpu_measurement` 168 + `PrephaseOutcome` 22 + `_prephase_device_snapshot` 13 + `_prephase_worker_memory_limit_bytes` 12 + `PREPHASE_*` constants · `_derive_calibration_from_observation` 113 + `_append_runtime_observation` 22 · `_resolve_guardrail_steps` 70 · `_check_and_record_guardrail_skip` 62 · `_attach_realized_memory` 62 · `_build_runtime_policy` 60 · `_build_admission_policy` 59 · `_build_guardrail_rejection_record` 47 · `_run_time_preflight` 45 · `_handle_in_subprocess_rejection` 39 + `_build_in_subprocess_rejection_record` 54 · `_evaluate_step_guardrails` 35 · `_raise_if_preflight_blocks` 34 + `PREFLIGHT_CONSUMER_ACTIONS` + `_BLOCKED_KIND_FOR_STATUS` · `_oom_memory_wording` 32 · `is_evidence_refusal` 25 · `_apply_epoch_bound` 25 · `_raise_if_inconclusive` 24 · `_vram_skip_memory_extra` 23 + `_time_skip_memory_extra` 23 · `_resolve_effective_epochs` 22 · `_may_advise_resource_reduction` 19 · `_attach_runtime_evidence` 16 · `_raise_if_wall_clock_timeout` 15 + `WallClockTimeoutError` 9 + `_apply_watchdog_failure_fields` 10 · `_runtime_phase_for` 13 · `RuntimeEvidenceChannelError` 13 + `_raise_if_evidence_channel_failure` 11 · `_attribution_reason` 6 · `_is_cuda_oom` 3 |
| **`records.py`** — record construction and the one persist/validate seam | `_build_scoring_failure_record` 93 · `_build_execution_failure_record` 85 + `_PHASE_FAILURE_TEXT` · `_build_resource_admission_record` 77 + `RESOURCE_ADMISSION_STATUS` / `RESOURCE_ADMISSION_REASONS` / `_STATUS_FOR_REASON` / `INFRASTRUCTURE_FAILURE_STATUS` · `_handle_admission_refusal` 53 · `_build_denoised_filename` 50 · `_build_skip_record` 47 · `_interpret_training_status` 46 · `_validate_history_and_lock` 35 · `_emit_record` 29 · `_resume_progress` 27 · `_classify_attempt_failure` 22 · `_copy_seed_plugin` 21 |
| **`feedback.py`** — evidence assembled FOR the next planner/proposer | `_build_gate_exhaustion` 167 · `_build_trial_validity_feedback` 111 · `_render_gate_exhaustion_summary` 92 · `_render_gate_exhaustion_trigger_b_summary` 74 · `_collect_disallowed_patterns` 51 |
| **`cli.py`** — argparse surface and args → `HyperparamTuningInput` | the parser and argument assembly extracted from `main` 578 + `PARTIAL_CAMPAIGN_EXIT_CODE` |
| **`ml_hyperparameter_tune_agent.py`** (main, stays) | `HyperparamTuningAgent` + `run` + `__init__` + `set_run_context` · `_run_skill` 11 · `_serialize_expert_advice` · `SIDERIUS_ROOT` · a thin `main()` |

Approximate movement: policy ≈ 900, runtime ≈ 1 250, records ≈ 600, feedback ≈ 500, cli ≈ 500.

**Blocks that STAY inline in `run()`, decided from source, not line count.** Sequencing that reads
arbitrary outer state (the attempt loop's `resolved_action`, `consecutive_fails`,
`completed_rounds`, the physical-rejection buffer) is NOT extracted: pulling it out would need the
"giant mutable context" the amendment forbids, and the `resolved_action` hazard (§3.5) makes its
exact scoping load-bearing — a refactor that changed when it is read would be a semantic change
disguised as cleanup.

**Dependency direction** (enforced, one-way):

```text
ml_hyperparameter_tune_agent.py  ->  policy / runtime / records / feedback / cli
                                 ->  agent schemas · execute_tools · core · skills
```

No node-local submodule imports the main module. `MetricOrder` does NOT move: its authority stays
`execute_tools/metric_order.py`.

**Pre-refactor oracles captured** (`/tmp/claude-1004/c7_baseline/`): CLI `--help`
(33 815 bytes, sha256 `c496948d…f153`), sha256 of all 18 PB/WF/REC goldens, the AST inventory, and
the deterministic pseudo-iteration + C1 replay outputs used as the differential oracle.


### 14.9.1 — C7 implementation: what moved, what did not, and why

**Result.**

| | before | after |
|---|---|---|
| `ml_hyperparameter_tune_agent.py` | 7 430 | **3 170** |
| `HyperparamTuningAgent.run` | 2 714 | **2 714** (unchanged — see the obstacle below) |
| `main` | 578 | **11** |
| node-local modules | 0 | **5** (`policy` 1 205 · `runtime` 1 583 · `records` 714 · `feedback` 541 · `cli` 619) |

**Dependency graph — one-way, verified by `ruff`'s F821 pass over the package:**

```text
ml_hyperparameter_tune_agent.py   (imports all five)
        |
        +-- runtime.py  -->  records.py , policy.py
        +-- policy.py   (leaf)
        +-- records.py  (leaf)
        +-- feedback.py (leaf)
        +-- cli.py      (leaf)
```

No submodule imports the main module. `MetricOrder` did not move — its authority is still
`execute_tools/metric_order.py`.

**The cut that took three attempts, and what decided it.** The first split put every
record-emitting handler in `records` and every runtime concern in `runtime`, which produced a
genuine cycle: `_handle_prephase_gpu_measurement` (runtime) BUILDS and EMITS a resource-admission
record, while `_classify_attempt_failure` (records) tests `isinstance(exc, WallClockTimeoutError)`
(runtime). Neither direction alone resolved it. The rule that did:

> **`records` BUILDS; `runtime` EMITS.**

`records` became the lowest layer — record builders, the status vocabulary, the single
`_emit_record` persist seam, and the prose helpers that shape record fields — and imports nothing
node-local. Every handler that *evaluates a runtime verdict and then persists a record*
(`_handle_admission_refusal`, `_handle_in_subprocess_rejection`,
`_check_and_record_guardrail_skip`, `_classify_attempt_failure`) sits in `runtime`, which may
import `records`. The cycle disappears because the dependency now follows the direction the data
actually flows.

**The package's `sys.modules` rebind, discovered by probe rather than assumed.**
`nodes/ml_hyperparameter_tune_agent/__init__.py` ends with
`sys.modules[__name__] = _impl`, so after import the package path IS the main module and is no
longer a package. Empirically (a throwaway `_probe.py`): importing
`nodes.ml_hyperparameter_tune_agent.<submodule>` from outside raises
`ModuleNotFoundError: … is not a package`, and importing the submodule FIRST fails too, because
the parent `__init__` rebinds before the submodule loads. What works — and what this refactor
relies on — is that the MAIN module imports each submodule at its top, i.e. while `__init__` is
still executing and the package is still a package; `sys.modules` is then populated with the
dotted names and every later external import resolves. **Consequence for future work: a node-local
submodule here is only reachable because the main module imports it.** The `__all__` block in the
main module is not decoration either — it declares the moved names as deliberate re-exports so
`ruff` does not prune them and `mock.patch("nodes.ml_hyperparameter_tune_agent.X")` keeps
resolving, which a large body of tests depends on.

**`run()` was NOT reduced. The obstacle, precisely.** `run()` is three phases —
initialization (~528 lines), the round loop (1 952), finalization (~234) — and the round loop is a
single 1 793-line `try:` inside the attempts `for`. Extracting that body is blocked by something
stronger than parameter count:

```python
# Phase 6.8 §2 Layer C (Commit 4) — per-round cleanup. Drop local refs to the
# largest per-round transients before the next round's plan() call so
# inter-round RSS stays flat. NameError-guarded because early-exit paths leave
# some names unbound.
with suppress(NameError):
    del train_results
...  # seven of them
```

Those seven guarded `del`s are a **documented memory-management mechanism**, and they run once per
ROUND while the names are bound once per ATTEMPT. Moving the attempt body into a function would
drop those references per attempt instead of per round — changing peak RSS behaviour that a design
document specifically establishes. The `NameError` guards also prove the block deliberately relies
on function-scope leakage across early-exit paths.

So extracting it would either (a) change documented memory semantics, or (b) require passing the
round's mutable state through a large context object — both explicitly forbidden by the amendment.
**Reported rather than forced.** The honest reductions were taken instead: 4 260 lines left the
main module, `main()` went 578 → 11, and a reviewer now reads the lifecycle in one file with the
implementations one hop away.

**What is left large, and why**: `run()` 2 714 (above); `_resolve_time_check_probe_request` 209 and
`_handle_prephase_gpu_measurement` 168 in `runtime` (each one coherent probe/measurement
protocol); `_build_reflection_context` 175 in `policy` (the 23-key WF-2 surface, built in one
place on purpose); `_build_gate_exhaustion` 167 in `feedback`.

### 14.9.2 — Zero-semantic-change evidence

| Oracle | Result |
|---|---|
| Differential PRE/POST pseudo run — 13 surfaces (`run_output`, all records, `best_*`, reflection contexts, C1 gate-helper replay, plan kwarg key sets, reflect `actual_results`/`reflection_context`/additive kwargs, call counts, `run()` branch count) | **DEEP-EQUAL** after C7a and again after C7b, with only timestamps/paths/durations normalised |
| CLI `--help` | **BYTE-IDENTICAL** (33 815 bytes, sha256 `c496948d…f153`) after both commits |
| PB-1 (3) / PB-2 (2) / WF-1 (2) / WF-2 / REC goldens — 18 files | **all sha256 UNCHANGED**; nothing regenerated |
| `ruff check` / `ruff format --check` | clean |

Not one golden was regenerated for C7, by design: a structural refactor that needs a golden
rewritten is not a structural refactor.

### 14.9.3 — Standing rule adopted (operator, 2026-08-16)

This is a **continuing architecture-hygiene rule for the generic-framework upgrade**, not a
one-off for the tuner. Before adding another major capability to a node:

1. inspect the current module/function complexity;
2. if the structure is healthy — add the feature normally;
3. if a god-file trend is emerging — first perform a behaviour-preserving coarse decomposition;
4. preserve the public interface, the main node file, `run()`/entrypoint semantics, the CLI, the
   data contracts and the execution order;
5. prove before/after parity;
6. only then continue with the next semantic feature.

The signals are semantic, not a line count (1 500 lines can be fine; 600 can be a mess): one file
holding several unrelated responsibilities; a function needing thousands of lines to express a
lifecycle; having to understand unrelated runtime/scoring/record code to change one policy; a type
checker that can no longer analyse a function reliably; helper count rising while ownership stays
unclear; new features only expressible as another branch in the same orchestrator.

And the other half of the rule, equally binding: **a refactor must not change the node's external
identity.** The node keeps ONE main file that still owns the public class, `run()`, the CLI
entrypoint, the high-level orchestration and the lifecycle ordering. Submodules extract ownership
that has *already* become clear; they never turn the main file into a forwarding shell.

> modularity ≈ semantic ownership — not modularity = more files.


### 14.9.4 — C7d attempt: the vertical decomposition, measured

The operator's follow-up correctly identified that pass 1 fixed the horizontal
spread and left the vertical monolith: 86 % of the main file is still `run()`.
The proposed cut — `planning.py::prepare_attempt`, `execution.py::execute_attempt`,
`finalize_run_output` into `records.py` — was mapped against the source, and the
seams are exactly where the amendment says they are. The `try:` inside the attempt
loop divides cleanly at `failure_stage = "guardrails"` and at
`print("\nGenerating Research Memory...")`.

**One earlier blocker is retracted.** §14.9.1 reported that the attempt body could not
be extracted because the seven `with suppress(NameError): del …` statements are a
documented per-round memory mechanism. That objection does NOT apply to the operator's
design: phases that RETURN values which `run()` re-binds leave the `del`s operating on
`run()`'s own locals, so the flat-RSS behaviour survives. The design is sound; what
follows is a different obstacle.

**Measured coupling of each phase to `run()`'s locals** (AST: names read but not bound
inside the block, excluding builtins and module-level symbols):

| Phase | lines | inputs it reads from `run()` |
|---|---|---|
| PLANNING (observe → plan → overrides → TrialConfig / sample sets) | 414 | **28** |
| EXECUTION (guardrails → preflight → train → infer → score → health) | 962 | **45** |
| REFLECT + COMMIT (reflection → record construction → emit → bookkeeping) | 345 | **48** |
| FINALIZATION (termination → tracks → feedback → output dict → persist) | 232 | **48** (35 excluding builtins/imports) |

The amendment's own rule:

> If extracting a block requires passing ~20 unrelated locals: the boundary is
> probably wrong. Do not create a giant mutable context merely to hide those
> parameters.

Every phase exceeds it; three exceed it by more than double. Hiding 45 parameters
behind a context object is the move the amendment explicitly forbids, and passing 45
arguments is not an interface anyone would defend.

**The one nuance worth the operator's attention.** PLANNING's 28 inputs are not 28
unrelated things. Roughly 21 are RUN-SCOPED — bound once in `run()`'s first ~530 lines
and never mutated afterwards (`agent_input`, `brain`, `sandbox`, `run_metric`,
`run_order`, `run_profile`, `run_task_render`, `run_model_io`, the four budgets,
`resolved_data_scope`, `scope_is_partial`, `model_type_setting`, `config_manual_data`,
`expert_advice_str`, `model_description`, `run_name`, `file_index`, `max_rounds`,
`trial_allowed`, `self`). Only ~7 are per-attempt (`iteration`, `attempt_in_round`,
`total_attempts`, `N`, `is_formal_round`, `formal_trial_winner`).

So there is a real, non-god-object type hiding here: a FROZEN `RunScope` holding the
authorities `run()` establishes in phase 1. It is immutable, it is a concept the code
already has (the amendment itself calls phase 1 "establish run authorities /
services"), and it would make PLANNING a genuine `prepare_attempt(scope, round_ctx)`.
It would NOT rescue EXECUTION or REFLECT+COMMIT, whose inputs are dominated by
per-attempt mutable state (`train_status`, `score_results`, `time_check`,
`resource_check`, `active_params`, `record_params`, `trial_config`, `ordering`, …).

**This is a genuine architecture decision, not an implementation detail**, so it is
referred rather than taken:

* **Option A — introduce a frozen `RunScope`.** PLANNING becomes extractable
  (~414 lines out of `run()`), and a later pass could split EXECUTION at its internal
  seams (preflight / train / infer+score) into several narrower phases that each take
  the scope plus a small typed input. Cost: one new type that is passed widely, which
  is the shape the amendment warned about even though this one is immutable.
* **Option B — stop here.** `run()` stays ~2,700 lines; the horizontal decomposition
  and the public boundary stand on their own, and the vertical pass waits for a PR that
  can also restructure the per-attempt state it depends on.

Until that is decided, no extraction is performed: doing half of Option A would leave
the node with a widely-passed new type AND a 2,300-line `run()`, which is worse than
either endpoint.

> **Superseded by §14.9.5.** The operator chose option A-prime (a bounded frozen
> carrier, not the original A), which makes the measurement above the *input* to
> the design rather than a blocker. The answers immediately below describe the
> pre-C7d head and are kept as the record of what was true when the question was
> referred; §14.9.5 answers them again at the head that ships.

**Answers to the amendment's final review questions, at the PRE-C7d head:**

1. *Lifecycle readable from `<node>.py` + `<node>.md` alone?* Partly. The file-level
   responsibilities and the phase ORDER are visible, and the `.md` documents the
   contract — but `run()` still inlines the phase implementations, so the honest answer
   is **not yet**.
2. *One coherent responsibility per internal module?* **Yes** — `policy`, `runtime`,
   `records`, `feedback`, `cli`, each documented at its head.
3. *External production code importing an internal submodule?* **No** — audited and now
   enforced by `tests/unit/nodes/test_node_public_boundary.py`.
4. *Internal submodule importing the main module?* **No** — enforced by the same test,
   plus an acyclicity check over the private graph.
5. *Is `run()` orchestration rather than implementation?* **No, not yet.** This is the
   open item.
6. *Did we avoid a giant context/state object?* **Yes** — and the measurement above is
   why question 5 is still "no".
7. *External Python / CLI / record / prompt interfaces unchanged?* **Yes** — CLI
   `--help` byte-identical, 18 goldens sha256-unchanged, no record change.
8. *PRE vs POST deterministic outputs equal?* **Yes** — the 13-surface differential
   oracle is deep-equal after every C7 commit.

### 14.9.5 — C7d: the vertical decomposition, as built (operator decision A-prime)

**Decision recorded.** *A-prime — a bounded frozen carrier for run-scoped stable
bindings only, then continue splitting along lifecycle seams.* Option B was
rejected because it would have left the node at ~3,170 lines with `run()` still
occupying 86 % of the main file; the original A was rejected because a context
object holding 45-48 mutable locals is the god context the amendment forbids.

**Why the measurement was not a veto.** 28/45/48 raw locals are not accepted as
proof that a seam is wrong — they are proof that the code lacked the distinction
between *bindings the run establishes once* and *state the loop mutates*. Naming
that distinction removes most of the coupling without hiding any of it:

```text
bad context    = every mutable local in one bag
good carrier   = the data boundary of ONE real lifecycle concept
```

#### The carriers (`contracts.py`, data boundaries only)

| Carrier | Kind | What it is |
|---|---|---|
| `RunBindings` | frozen | the authorities, services and facts resolved once at startup |
| `PreparedAttempt` | frozen | everything planning DECIDED for one attempt |
| `AdmissionOutcome` / `TrainingOutcome` / `AttemptExecution` | frozen | one per execution phase: a control decision plus that phase's products |
| `AttemptIdentity` | frozen | round index, attempt index, formal-or-not |
| `RunExitSnapshot` | frozen | the nine end-of-loop facts the output is built from |
| `AttemptSignal` | enum | `PROCEED` / `NEXT_ATTEMPT` / `END_ROUND` |
| `AttemptStage` | **mutable, one field** | how far the attempt got — see below |

`RunBindings` carries **zero** mutable loop, round or attempt state, and that is
enforced at construction rather than by convention: `FORBIDDEN_BINDING_FIELDS`
(28 names — counters, `plan`, `resolved_action`, the termination flags, the
per-attempt results) is checked in `__post_init__`, because a widely-passed
object is exactly the thing someone adds a field to "just this once".

`AttemptStage` is the single deliberate exception to immutability, and it exists
for a reason no return value can serve: `run()`'s exception handler stamps
`failure_stage` on the failure record and classifies the exception by it, and on
the raising path there is no return. One field, one writer at a time.

#### The control-flow translation, and why it is not a redesign

The execution region contained 15 loop-control exits. Every one of them sat
**directly** in the attempt loop — none inside a nested loop — which is what
makes the translation 1:1 rather than a restructuring:

```text
11 x continue  ->  return X.next_attempt()   ->  run(): if ... NEXT_ATTEMPT: continue
 4 x break     ->  return X.end_round(...)   ->  run(): if ... END_ROUND:    break
 3 x raise     ->  UNCHANGED — propagates into run()'s handler exactly as before
```

`raise` is deliberately not translated: the `try`/`except` that classifies
attempt failures stays in `run()`. Retry counts, round transitions, phase order,
timeout and signal semantics are untouched.

#### Module tree, before and after

```text
BEFORE C7 (one file)              AFTER C7d
7,430  ml_hyperparameter_tune_agent.py   1,473  ml_hyperparameter_tune_agent.py  PUBLIC
                                          348  contracts.py                     carriers
                                          512  planning.py                      phase
                                        1,143  execution.py                     phase x3
                                        1,304  records.py                       BUILDS
                                        1,583  runtime.py                       EMITS
                                        1,205  policy.py
                                          541  feedback.py
                                          621  cli.py
```

| Metric | pre-C7 | post-C7 | post-C7d |
|---|---|---|---|
| main file | 7,430 | 3,170 | **1,473** |
| `run()` | 2,714 | 2,714 | **1,011** |
| `run()` branch nodes | 198 | 198 | **64** |
| largest function | `run()` 2,714 | `run()` 2,714 | `run()` 1,011, then `run_admission_preflight` 512 |

`run()` is inside the operator's 900-1,100 band. It was not driven lower: the
target was orchestration that reads as a lifecycle, not a line count.

#### Dependency direction (acyclic, enforced)

```text
main ──> planning ──┐
     ├─> execution ─┼─> records ──> policy, feedback
     ├─> runtime ───┘        └────> contracts
     └─> cli                 (contracts is a leaf)
```

Two cycles were caught and resolved **by moving the concept, not the import**:

* `records -> planning` for `PreparedAttempt` — resolved by moving the carrier
  into `contracts.py`, where the amendment placed it;
* the record's emission tail — `_attach_realized_memory`, `_emit_record`,
  `_append_runtime_observation`, `_derive_calibration_from_observation` — stays
  in `run()`, because three of the four live in `runtime.py`, which imports
  `records.py`. `records` BUILDS, `runtime` EMITS: the record dict is the seam.

#### `RunBindings` final field list, classified

* **Authorities** (7): `run_profile`, `run_model_io`, `run_deliverable_spec`,
  `run_metric`, `run_order`, `run_task_render`, `registry`.
* **Services** (3): `sandbox`, `brain`, `agent_input`.
* **Stable resolved run facts** (23): `run_name`, `workspace`, `file_index`,
  `max_rounds`, `model_type_setting`, `trial_allowed`, `resolved_data_scope`,
  `scope_is_partial`, `expert_advice_str`, `config_manual_data`,
  `model_description`, four budgets, three round/attempt budget settings, the
  four once-resolved formal-comparison values, `hardware_context`,
  `device_identity`, `time_data_dir`, `anchor_map_data`, `reference_scores`,
  `started_at`, `health_checks_config_source`, `health_config_sha256`.
* **Mutable loop / round / attempt state**: **zero**, structurally.

Each of the five fields added for the execution phases was verified from source
to be bound exactly once before the round loop and never rebound.

#### Test disposition (the deferred pass, done once)

Held deliberately until the layout was final. `1,187 errors + 39 failures ->
1,188 passed` in the tuner package, in three categories, none of which weakens a
check:

1. **Patch targets follow the call site.** A stub aimed at the node's public
   module binds a name nothing calls; the package conftest's own docstring
   records that such a stub *hangs* rather than fails.
2. **Source scans read the node, not one file.** `tests/helpers/tuner_source.py`
   gains the three new modules plus `tuner_lifecycle_source()` — `run()` and
   every phase it executes. Reachability tests use the latter, because "the node
   contains this call" is satisfiable by dead code and "the lifecycle contains
   it" is not.
3. **Assertions restated at the right level.** Prephase branches accept the
   returned control decision as well as `break`/`continue` (a branch issuing
   neither, or the wrong one, still fails); the ceiling-provenance test compares
   AST containment instead of byte offsets, which across two modules measured
   file order rather than execution order; two indentation-pinned literals became
   whitespace-insensitive on the argument that carries the meaning.

**Two node-wide collaborators gained a single binding.** `_run_skill` (called
from three modules) and `_emit_record` (four) now resolve through their owning
module. Per-module `from X import name` gave each module its own snapshot, so a
stub installed for one silently missed the others — a reachability hole C7a
opened and this closes. Behaviour-neutral; both remain re-exported from the main
module for `__init__.py`.

#### Evidence

* Differential PRE/POST oracle over 13 surfaces: **12/12 behavioural surfaces
  deep-equal** after every C7d commit. Only `run_branch_nodes` moves, which is
  the structural metric and the point of the exercise.
* `tests/unit/nodes/test_node_public_boundary.py`: 16 passed — no external
  production import of node internals, no submodule importing the main module,
  private graph acyclic, `__all__` free of private names.
* Tuner package: 1,188 passed.
* ruff + ruff format clean across `nodes/` and `tests/`.

#### The amendment's review questions, answered at the shipping head

1. *Lifecycle readable from `<node>.py` + `<node>.md` alone?* **Yes.** `run()`
   now reads plan -> admission -> train -> infer/score/health -> reflect ->
   build record -> emit -> finalize.
2. *One coherent responsibility per internal module?* **Yes** — eight, each
   documented at its head.
3. *External production code importing an internal submodule?* **No** — enforced.
4. *Internal submodule importing the main module?* **No** — enforced.
5. *Is `run()` orchestration rather than implementation?* **Yes** — 1,011 lines,
   64 branch nodes, and `brain.reflect(...)` still visible in it as required.
6. *Did we avoid a giant context/state object?* **Yes** — structurally, via
   `FORBIDDEN_BINDING_FIELDS`.
7. *External Python / CLI / record / prompt interfaces unchanged?* **Yes.**
8. *PRE vs POST deterministic outputs equal?* **Yes.**

#### Carried forward, deliberately not fixed here

> The tuner structural decomposition intentionally preserves the pre-existing
> `memory.time_mode` / no-time-budget coupling. That defect is not corrected
> here; it is reserved for the immediately following dedicated Step-07
> round-state semantics correction PR.

Also untouched, as instructed: the `resolved_action` round-scoped staleness
hazard, and 07a's validation time missing from the watchdog deadline prediction
(ADDED 07c scope).

---

### 14.10 — Post-refactor Gate readiness packet (Gate 1 rerun + the bounded Gate 2)

Both gates run on the SAME final executable HEAD, after the terminal full-suite
run from a clean tree. Gate 1 first.

#### Gate 1 — rerun at the post-refactor head

Identical to the operator-approved attempt-2 command except the workspace and
run identity. Cold start, no `--seed_paths`.

```text
SIDERIUS_ALLOW_LAUNCH=1 bash sdsc_submission_scripts/run_chain.sh --mode lilab \
    --workspace /home/klz/Data/SIDEREIS_DATA/step07b_gate1_postrefactor \
    --run_name gate1_07b_postrefactor \
    --num_iterations 2 --max_rounds 2 --max_proposal_attempts 3 --max_epochs 1 \
    --data_scope 4-9 --is_pseudo_training --no-health_gate_enabled \
    --enable_chain_incumbent_formal_gates \
    --trial_time_budget_minutes 20 --formal_time_budget_minutes 120 \
    --llm_config llm_configs/openai_tiered_pro.json
```

PASS criterion is unchanged from attempt 2: real within-tuner round evidence,
at least 2 TUNER rounds. The time budgets stay because the `memory.time_mode`
coupling is deliberately NOT fixed in this PR.

#### Gate 2 — bounded, real training. OPERATOR DECISION on posture

**`--runtime_watchdog` is intentionally OMITTED.** Operator decision, recorded
here in full because it is a deliberate deviation from the Gate standard's
canonical command and must not read as a quietly bypassed 07b bug:

> **Operator-approved functional-execution posture.** The purpose of this
> Gate 2 is to verify that the C7 structural refactor preserved the REAL
> production execution path:
>
> ```text
> real LLM -> real training -> validation -> inference -> scoring
>          -> HealthGate / record persistence
> ```
>
> The runtime watchdog is NOT part of the semantic change being validated here.
> A pre-existing 07a finding already established that the current watchdog
> deadline model does not account for the full validation pass; with the
> watchdog enabled, bounded real attempts have been terminated DURING
> validation. That accounting defect is explicitly deferred to 07c and MUST NOT
> be fixed in 07b.
>
> Enabling the watchdog here would therefore confound *refactor correctness*
> with *known watchdog-accounting debt*.
>
> This is NOT permission to alter runtime/watchdog production semantics.

```text
bash sdsc_submission_scripts/run_chain.sh \
    --mode lilab \
    --workspace /tmp/gate2_$(date +%s) \
    --run_name gate2_07b_postrefactor \
    --num_iterations 1 --max_rounds 1 --max_proposal_attempts 3 --max_epochs 1 \
    --data_scope 4-9 --health_gate_files 4,5,6,7,8,9 \
    --validation_max_portion 0.01 \
    --validation_max_train_samples 2000 \
    --validation_max_phase_seconds 900 \
    --no-force_formal_round \
    --trial_vram_budget_gb 4 --formal_vram_budget_gb 4 \
    --advice advice/gate/gate_07b_structural_refactor_advice.json \
    --llm_config llm_configs/openai_tiered_pro.json
```

Two deltas from the canonical command beyond the watchdog, both from the
operator decision recorded in §14.11, and both required for the Gate to be about
wiring rather than about model size:

* `--trial_vram_budget_gb 4 --formal_vram_budget_gb 4` (canonical: 24/24). The
  standard's "be generous on GPU VRAM" was always relative to a production
  campaign; a wiring test wants the smallest model that honestly runs.
* `--advice advice/gate/gate_07b_structural_refactor_advice.json`, which states
  the same 4 GiB limit in the proposer's own terms plus the "NOT a scientific
  campaign" mindset that the `advice/gate/` convention already establishes.
  Without it the proposer optimises for science and gets refused at pre-flight —
  which is exactly what happened in Gate 1 (§14.11).

Omission verified from source, not assumed: `_chain_common.sh:107` defaults
`RUNTIME_WATCHDOG=0`, `:315` sets it only when the flag is passed, and `:552`
forwards `--runtime_watchdog` to the app only when it is 1. Omitting the flag
therefore leaves the watchdog disabled, which is also its production default
(`docs/design/runtime_estimation_and_watchdog.md` §4).

Canonical in every other respect: cold start (no `--seed_paths`), paired
`--data_scope` + `--health_gate_files` per the DS8 partial-scope rule, and no
`--data_dir` (the launcher resolves it and refuses before any spend).

**The PASS requirement is NOT relaxed by the omission.** At least one REAL
production attempt must reach:

```text
training completion -> validation completion -> inference completion
    -> scoring completion -> persisted record -> HealthGate evaluated / outcome recorded
```

A scientifically poor or HealthGate-INVALID candidate still constitutes valid
functional Gate evidence, provided the full execution path completes — which is
consistent with the Gate standard's statement that Gate 2 is functional
validation, not a miniature scientific campaign.

**Standing constraints for this Gate 2** (operator): do not trivialize
validation to make the run pass — that would change the execution path the Gate
is supposed to cover; do not fix the watchdog debt here; do not run a second
watchdog-on Gate for comparison. One bounded run.

---

### 14.11 — Gate 1 at the post-refactor head: **PASS**, plus a Gate-posture defect found

| Field | Value |
|---|---|
| Executable HEAD | `cb1a885a` (clean tree at launch) |
| Workspace | `/home/klz/Data/SIDEREIS_DATA/step07b_gate1_postrefactor` (cold start, 0 seed paths) |
| Log | `/tmp/claude-1004/gate1_postrefactor.log`, `CHAIN_RC=0` |
| Wall time | ~21 min (vs 40 min 54 s for the pre-refactor attempt 2) |
| Cost | 34 real gpt-5.5 calls across both iterations |
| Verdict | **PASS** — criterion A satisfied by iteration 1; iteration 2 recorded in full |

**Criterion A — within-tuner round evidence: SATISFIED.** From
`iter_001/.../run_output_iter_001.json`, not from the log:

```text
status=completed  completed_rounds=2
  skipped_time_risk   time_mode='trial'
  success             time_mode='trial'   score=-2.4310   <- round 1
  success             time_mode='formal'  score=-2.9588   <- round 2
[FORMAL OVERRIDE] strategy=full_clone winner='..._iter_001_002' score=-2.4310
```

Two real tuner rounds with the round-1 -> round-2 transition driven by a
resolved formal winner, `memory.time_mode` stamped on every record. The scores
are pseudo-training stub outputs and carry NO scientific meaning; they are
evidence that rounds completed.

**Criterion B — iteration 2: `partial`, 1 completed round.** Its formal round
was refused 15 times as `skipped_time_risk` (`time_mode='formal'`). This is NOT
a refactor regression: §14.6b records the same phenomenon at the PRE-refactor
head ("iteration 1 spent 20 min on 16 guardrail-rejected formal attempts").
Reproducing a known pre-existing behaviour is parity evidence, not a new defect.

#### A Gate-posture defect this run exposed — `--advice` was not passed

**Previous assumption.** The Gate-1 command inherited from attempt 2 was
complete as-is, so the post-refactor rerun needed only a new workspace.

**Audit evidence.** Iteration 2's first two attempts died at the structural
pre-flight:

```text
Loop Error: worker tree reached 25.183 GiB against a 24.0 GiB allowance
Loop Error: worker tree reached 24.881 GiB against a 24.0 GiB allowance
```

The proposer had chosen a 24-block dilated TCN. Auditing why, `advice/` turns
out to hold an established convention — `advice/gate/*.json`, a `mindset` +
`propose` bundle whose existing members say exactly what a Gate needs:

> "capability validation fixture (NOT a scientific campaign) ... Scientific
> quality is NOT under test ... Propose ONE small, conservative,
> obviously-trainable model ... roughly 10k-500k parameters"

No `--advice` was passed. With no Gate mindset injected the proposer runs its
default posture — optimise for science — and a 24-block TCN is a perfectly
sensible SCIENTIFIC proposal. The Gate never told it otherwise. The Gate
standard already names the consequence (§"Gate 2 parameter plans"):

> **be generous on GPU VRAM, stingy on wall time** — a VRAM-gate rejection
> wastes a whole Gate attempt.

**Corrected understanding.** A VRAM refusal burning Gate attempts is a POSTURE
defect, not candidate bad luck, and the repository already had the mechanism to
prevent it.

**Implementation consequence.** `advice/gate/gate_07b_structural_refactor_advice.json`
is added and is passed to Gate 2 via `--advice`.

**Operator decision (2026-08-16): Gate 1 and Gate 2 limit each model to 4 GiB
of GPU VRAM.** Both halves are required or the constraint is unreachable: the
budget flags enforce it (`--trial_vram_budget_gb 4 --formal_vram_budget_gb 4`)
and the advice states the same number, so the proposer can aim at it instead of
discovering it by refusal. This tightens the standard's 24/24 for Gate runs —
"generous" was always relative to a production campaign, and a wiring test
needs the smallest model that honestly runs, not the largest that fits.

#### OPERATOR DISPOSITION — Gate-1 advice omission (2026-08-16, at review)

Recorded explicitly so the finding cannot later be misread as a defect in the
07b property itself:

* **Gate 1 remains ACCEPTED. No rerun.**
* The missing gate advice and the 4-GiB posture were a **Gate-HARNESS posture
  defect**, not a failure of the 07b property under test.
* Gate 1's required acceptance property was **directly established** by the
  persisted round-1 → round-2 evidence, produced with real LLM calls
  (`iter_001` run-output: `completed_rounds=2`, `memory.time_mode` stamped
  `trial` then `formal`, `[FORMAL OVERRIDE]` resolving the winner).
* **Canonical future Gate posture** uses BOTH halves: the gate advice file and
  the matching 4-GiB enforcement/declaration. Now binding in
  `docs/gates/gate_testing_standard.md`.

**Gate 1 is NOT re-run.** Its required property is established twice over
(iteration 1's two rounds; iteration 2's planner correctly self-correcting
24 -> 16 blocks after reading the refusal, which is itself evidence the
reflect -> plan feedback path survived the decomposition). Re-running would
spend ~20 min and 34 more real LLM calls to re-establish an already-established
property — the minimum-sufficient-evidence rule says no. The posture fix lands
where it actually matters: Gate 2, where a refused attempt wastes real training.

---

### 14.12 — Gate 2 attempt 1: REFUSED BEFORE TUNER/GPU EXECUTION by a schema interlock

**Cost, stated precisely:** ~9 min wall time and **3 real LLM calls** (propose / implement / validate) were consumed before the refusal; **zero GPU and zero training spend**. It is "refused before tuner/GPU execution", NOT "no spend".

`CHAIN_RC=0`, manifest `status=failed`, no tuner round, no GPU work. Not a
failure of the refactor and not a failure of the run — a configuration error in
the Gate command, caught after the proposal/implementation/validation LLM stages
and before any tuner round or training began.

```text
pydantic_core.ValidationError: 1 validation error for HyperparamTuningInput
  Value error, validation_max_phase_seconds requires runtime_watchdog_enabled=True:
  the watchdog is what enforces the deadline, so without it the ceiling would be
  recorded and never applied.
```

**Previous assumption.** §14.10's Gate 2 command took the Gate standard's
canonical command and removed `--runtime_watchdog` per the operator's posture
decision, leaving everything else intact.

**Audit evidence.** `agent/schemas/hyperparam_tuning.py:2114-2129`,
`_validate_validation_wall_clock`, whose docstring states the principle
directly:

> A hard bound nothing enforces is worse than no bound. …accepting the ceiling
> with the watchdog off would let a Gate command record a wall-clock limit, run
> past it, and still report the run as bounded.

The Gate standard describes the same pair as a unit — "the
`--validation_max_phase_seconds` + `--runtime_watchdog` **fuse**". They are one
mechanism, not two flags.

**Corrected understanding.** Omitting the watchdog REQUIRES omitting
`--validation_max_phase_seconds`. The audit also confirms this is the only such
interlock: `validation_max_portion` and `validation_max_train_samples` have no
watchdog dependency, and the standard names the latter "**the Gate's primary
sizing mechanism**".

**Implementation consequence.** Gate 2 relaunched without the phase-seconds
fuse. Validation stays bounded by the two mechanisms that actually size it —
`--validation_max_portion 0.01` and `--validation_max_train_samples 2000` — so
this does NOT trivialize validation, which the operator explicitly ruled out.

**Cost of the mistake.** ~9 min and 3 real LLM calls (propose / implement /
validate) — a real, non-zero cost; **zero GPU and zero training spend**. The
interlock did exactly what it exists for. The
failed workspace is preserved at
`/home/klz/Data/SIDEREIS_DATA/step07b_gate2_postrefactor`; attempt 2 uses
`…_a2` so no evidence is overwritten.

**Standard updated**: the binding policy block in
`docs/gates/gate_testing_standard.md` now records that dropping the watchdog
means dropping the phase-seconds fuse with it.

---

### 14.13 — Gate 2 attempt 2 (bounded, real training): **PASS**

| Field | Value |
|---|---|
| Executable HEAD | `cb1a885a` (unchanged since the terminal validation; everything after is `.md` / advice JSON) |
| Workspace | `/home/klz/Data/SIDEREIS_DATA/step07b_gate2_postrefactor_a2` (cold start, 0 seed paths; attempt 1 preserved separately) |
| Log | `/tmp/claude-1004/gate2_a2.log`, `CHAIN_RC=0` |
| Wall time | ~7 min 30 s (19:42:58 → 19:46:17 for the iteration, plus proposal/implementation) |
| Cost | 7 real gpt-5.5 calls |
| Posture | production (pseudo off), `--data_scope 4-9` + `--health_gate_files 4,5,6,7,8,9`, **4 GiB** trial/formal, gate advice file, watchdog and the phase-seconds fuse both omitted |
| Verdict | **PASS** — the full execution path completed |

**The operator's PASS chain, each link evidenced from the persisted record, not
from the log:**

```text
training completion    train_time_s=42.6   train_objective=[3.4451]
        v
validation completion  validation_objective=[4.4098]  validation_samples=12000
                       validation_seconds=[32.23]     comparability=established
        v
inference completion   inference_time_s=11.7
        v
scoring completion     scoring_time_s=5.2
                       metric_result={metric_id: tidmad_denoising_score,
                                      direction: higher, scalar: -3.2917,
                                      references_used: [anchor_map]}
        v
persisted record       status=failed_mode_collapse, score_table, file_vector,
                       training_history, training_diagnosis, validation_workload_ceiling
        v
HealthGate outcome     health_gate_enabled=True, healthgate_mode=blocking
                       [output_diversity_blocking] any_pass failed — per-file
                       file_4..file_9 = 6 unique int8 (threshold > 25);
                       class-127 collapse
```

`completed_rounds=1`, `status=completed`, `best_denoising_score=None`.

**The candidate collapsed, and that is a PASS.** A tiny 8-block TCN given one
epoch of a 1 % slice producing a constant class-127 output is the expected
scientific outcome, and the operator's criterion says so explicitly: a
HealthGate-INVALID candidate is still valid functional evidence provided the
full execution path completes. What is under test is the path, and every stage
of it ran with real work.

**What this proves about C7 specifically.** Every extracted boundary executed
against real training, real inference and real scoring, in order:
`run_admission_preflight` → `run_training` → `run_inference_scoring_health`
(which carries the Step 06 metric route and the health gates) →
`build_attempt_record` → `finalize_run_output`. The Step 06 metric handle is
visible in `metric_result` with `direction: higher` sourced from `MetricSpec`,
and 07a's R3 validation pass is visible in `training_history` with
`comparability: established` — i.e. 07a and 07b's own contracts both still hold
through the decomposed node under real load.

**Two recorded, expected observations:**

* `memory.time_mode` is `None`. Gate 2 passes no time budgets, so the time gate
  is disabled and the field is never stamped — this is exactly the
  carried-forward coupling defect, reproducing on cue. Not fixed here; it is
  reserved for the round-state semantics correction PR.
* Omitting the watchdog was load-bearing, not cosmetic: the validation pass took
  **32.2 s** and completed. Under 07a's watchdog model that time is unpriced,
  which is precisely how 3 of 4 attempts died there. The posture decision let
  this Gate measure the refactor instead of re-measuring 07c's debt.

**Note on the manifest.** `iter_001/manifest.json` reports
`status=no_records` / `best_score=None` — correct and consistent: the chain
admits only scientifically valid candidates as iteration results, and a
mode-collapsed candidate is not one. The tuner's own `run_output` is the
functional evidence, and it reports `status=completed`.

---

### 14.14 — Finalizer: provenance, preserved evidence, and what stays deferred

Doc-only finalizer pass, operator-directed at review (2026-08-16). **No
executable production code was modified, no Gate was re-run, and no deferred
semantic defect was fixed.**

#### Final provenance

| Field | Value |
|---|---|
| Final **executable** HEAD | `cb1a885a` |
| Final **PR** HEAD | `307fa0ce917c0afbd6ee5425fae7ef902b267019` (+ this finalizer) |
| Between the two | documentation and gate-advice JSON **only** — no executable production change |
| PR | **#216** |
| Exact-head CI | **31989125173 SUCCESS** — ruff · ruff format · pyright (strict, blocking) · pytest |
| Working tree | clean |
| Terminal validation | 9,787 passed / 3 skipped / 0 failed, full `tests/unit` from a clean tree at `cb1a885a` |
| Merge | **NOT merged.** Merge is the operator's. |

#### Preserved evidence — do not rewrite or delete

All five Gate records stand as written, including the two that did not succeed.
A Gate history that keeps only its successes is not evidence:

| § | Record | Outcome |
|---|---|---|
| §14.6 | Gate 1, attempt 1 (pre-refactor) | **INCONCLUSIVE** — harness reachability |
| §14.6b | Gate 1, attempt 2 (pre-refactor, corrected) | **PASS** |
| §14.11 | Gate 1, post-refactor | **PASS** + the Gate-posture defect it exposed |
| §14.12 | Gate 2, attempt 1 | **REFUSED before tuner/GPU execution** by a schema interlock |
| §14.13 | Gate 2, attempt 2 | **PASS** — bounded real training |

Their workspaces are likewise preserved and were never overwritten: each attempt
ran in its own directory (`…_attempt2`, `…_postrefactor`, `…_postrefactor_a2`).

#### Explicitly DEFERRED and UNCHANGED by this PR

Each would change round, gate or runtime semantics, which 07b is not permitted
to touch. None was modified by the decomposition, and none is modified here:

1. **`memory.time_mode` / disabled-time-budget coupling.** Without time budgets
   the field is never stamped, so the two-field winner rule is unsatisfiable and
   the skip gate takes its "no evidence" branch. Reproduced on cue in Gate 2
   (§14.13). Reserved for the immediately following dedicated Step-07
   round-state semantics correction PR.
2. **`resolved_action` stale-attempt hazard.** Round-scoped, written seven
   nesting levels down, never reset between attempts; the hazard is recorded at
   its declaration with a proposed fix and an owner.
3. **Validation-time / watchdog accounting debt.** `T_deadline` carries no
   `T_val` term, so the watchdog can kill inside the un-priced validation pass.
   **Owned by 07c** (parent §8.4).

> The tuner structural decomposition intentionally preserves the pre-existing
> `memory.time_mode` / no-time-budget coupling. That defect is not corrected
> here; it is reserved for the immediately following dedicated Step-07
> round-state semantics correction PR.

---

## 15. Commit plan — per-commit checklists

**Six commits.** C1 replay oracle (test-only) · C2 order authority +
consumers + validity (+ strict rung) · C3 scale-rule classification +
attempt-transition removal (+ policy-semantics rung) · C4 P2 authority-
rendered blocks + OD-1 (+ rung B-07b-3, PB exact) · C5 P3 owned deltas +
bridge surfaces + goldens (+ rung B-07b-2, boundary tests) · C6 packs +
docs / Checkpoint E + terminal validation + Gate 1. Each leaves the tree
green and independently reviewable.

Before every commit: stop and show the exact diff summary, staged file list,
tests run (counts / wall time from the log, never a wrapper's exit code) and
any deviation from this design — unless an Implementation Working Rules
contract overrides the interactive cadence, in which case the same evidence
is recorded in §14 before each autonomous commit.

---

### C1 — Checkpoint 0: selection / threshold / reflection replay oracle (test-only)

**1. Goal.**
Capture, BEFORE any production edit, the exact outputs of every policy
consumer 07b will rewire — trial winner, skip / bypass, resolved
thresholds, reflection context, five `best_*` tracks — over a corpus that
contains the awkward values (`-inf`, `None`, `nan`, penalized collapse,
invalid candidates, ties, trial/formal mix), so C2/C3 can prove deep-equal
parity under `higher`.
*Why this commit and not another*: the oracle must predate the edit it
guards (Step-00 §17: goldens captured by an explicit test-only act with
provenance); no such corpus exists (§0.4).

**2. Scope.**
- NEW `tests/unit/agent/tune_ml_hyperparam_agent/fixtures/sel1_histories.json` (hand-authored `all_records`
  histories) and goldens `goldens/sel1_gate_helpers.json`, `sel1_reflection_context.json`, `sel1_best_tracks.json`
  (`_captured_at` = `787afa08` + note).
- NEW `tests/unit/agent/tune_ml_hyperparam_agent/test_step07b_c1_selection_replay.py`: drives the CURRENT helpers
  directly and the reflection / finalization paths through `run_bounded_pseudo_iteration` (RecordingSandbox with
  canned scores from the corpus) capturing `reflection_context` at the reflect boundary (BoundaryRecorderBridge or
  the RecordingLLMBridge capture) and the output's `best_*` fields.
- Ledger §14.0: PB-1/PB-2/WF-1/WF-2 sha256s; the §3.7 declared-delta list frozen against golden lines; OD-1
  two-process instability evidence.
- Non-goals: no production change; no golden regeneration.
- Dependencies: none (07a merged).

**3. Implementation plan.**
- [x] Re-read `ml_hyperparameter_tune_agent.py:1534-1704, 1984-2042, 4140-4180, 4360-4400, 4460-4475, 5140-5185, 5787-5900, 6400-6560` and `tests/helpers/step00_pseudo_iteration.py`. **NO source drift**: `git diff --stat 787afa08 f17bbdb8` is docs-only, so every §0 line number is exact at the implementation base.
- [x] Corpus authored — 12 histories, `fixtures/sel1_histories.json`; goldens `sel1_gate_helpers.json` / `sel1_reflection_context.json` / `sel1_best_tracks.json` captured through the CURRENT code with `_captured_at` provenance; sha256s, the verbatim §3.7 delta line-set and the 5-seed OD-1 instability recorded in §14.0.
- [x] `test_step07b_c1_selection_replay.py` — 5 tests (corpus checklist against a hardcoded id tuple, the three replays, and the `run()` AST branch guard at the measured baseline 244). 5 passed / 1.71 s / rc 0.

**4. Validation plan.** Unit: the new module green; the pseudo harness runs. No negative tests (capture commit). Backward-compat: none touched.

**5. Acceptance criteria.** Corpus covers every listed case (a checklist test asserts each case id is present); goldens carry provenance; §14.0 lists the sha256s and the declared P3 delta lines verbatim; no production diff.

**6. Failure and edge cases.** A pseudo run whose scores are all `None` (no successes) → `best_*` all `None` captured; a tie in the trial winner (two equal scores) → the FIRST wins today — captured so C2 must preserve `max()`'s first-wins semantics.

**7. Verification commands and evidence.**
- `.venv/bin/python -m pytest tests/unit/agent/tune_ml_hyperparam_agent/test_step07b_c1_selection_replay.py -q > /tmp/07b_c1.log 2>&1; rc=$?; tail -20 /tmp/07b_c1.log`
- Evidence in §14: counts, wall time, rc, sha256s.

**8. Commit boundary.** tests + goldens + ledger only; stop and show (or record per the Working Rules override).

---

### C2 — P1-order: `MetricOrder` + every ordering consumer + validity outcome + strict rung B-07b-1

**1. Goal.**
Introduce the ONE order authority and route the 21 ordering sites through
it (§3.2), extract the reflection-context and best-track selection into
typed boundaries with replay parity, and pin the invalidated-result outcome
under both directions — the "policy selects by direction" half.
*Why this commit and not another*: ordering is a pure inversion with an
exact oracle (replay + strict rung); mixing the scale rules in would let a
scale mutation hide behind an ordering assertion (the C6a lesson).

**2. Scope.**
- NEW `execute_tools/metric_order.py` (§3.2 API; docstrings name the frozen semantics; `toward_better` /
  `toward_worse` included here because C3 needs them, but C2 does NOT yet route the thresholds through them — the
  threshold arithmetic stays `ref + delta` in C2 so the C2 diff is ordering-only).
- Tuner: `run_metric` → `run_order = MetricOrder(run_metric.spec)` at run scope (beside `:3923`); helpers
  `_best_trial_winner(records, order)`, `_should_skip_formal(..., order)`, `_should_bypass_formal_time_budget(..., order)`
  gain the `order` parameter (sentinels compared to `order.worst_sentinel` / `order.best_sentinel`; comparisons via
  the authority); planner table incumbent via `order.best`; NEW `_build_reflection_context(...) -> dict` (extracted
  from `:5787-5900`, all ordering via the authority; the loss rank untouched inside it) and NEW
  `_select_best_records(records, order) -> BestTracks` (extracted from `:6407-6445`); `run()` calls them
  (sequencing only). Banners render the order's operator symbol.
- Tests: `tests/unit/execute_tools/test_metric_order.py` (pure API incl. tie semantics, sentinels, rank);
  `tests/unit/agent/tune_ml_hyperparam_agent/test_step07b_c2_order_consumers.py` (replay deep-equal under `higher`
  vs C1 goldens; strict rung B-07b-1 with the `_direction_only_metric` handle bound via `_bind_once`; loss-rank
  non-flip; validity outcome under both directions; reachability: `MetricOrder` monkeypatched to a sentinel object
  → every consumer RED); UPGRADE the existing selection pins to `@pytest.mark.parametrize("direction", ["higher","lower"])`
  where they pin ordering (§9).
- Non-goals: no scale-rule change (C3), no prompt change, no record change, no `AttemptTransition` change (C3).
- Dependencies: C1.

**3. Implementation plan.**
- [x] §0.1 sites re-read and confirmed (23 direction-bearing expressions; 21 to migrate, 2 loss-rank to leave); Step-06 C6a fixture and the `_bind_once` pattern re-read.
- [x] `execute_tools/metric_order.py` implemented (§3.2 API + the two banner symbols, §14.1 deviation); `_direction_only_metric` promoted to `tests/helpers/metric_fixtures.py` and re-imported by the Step-06 rung, which stays green.
- [x] Two evidence points, both recorded: verbatim extraction → replay 5 passed / 1.59 s; authority rewire → replay 5 passed / 1.62 s.
- [x] Gate helpers, planner score-table incumbent and both banners rewired. `run()` AST branch count **244 → 198** (the two extractions moved 46 branch nodes out of the orchestrator; sequencing added none).
- [x] `test_metric_order.py` (18) + `test_step07b_c2_order_consumers.py` (35). Selection pins upgraded in `test_delta_gates.py`, `test_valid_candidate_selection.py`, `test_formal_launch_decision.py`, `test_valid_trial_winner_drives_formal.py`, `test_force_formal_round.py`, `test_m6_probe_unavailable_fails_closed.py`, `test_chain_incumbent_pseudo.py`. Step-06's C5 guard MIGRATED, not silenced (§14.1). 9/9 mutations RED.

**4. Validation plan.**
- Unit: the new modules; the upgraded pins; `tests/unit/agent/tune_ml_hyperparam_agent` (round/attempt/retry semantics untouched — green as evidence).
- Pseudo: `run_bounded_pseudo_iteration` replay deep-equal.
- Negative: reachability mutation; a consumer left on `max` → strict rung RED (proved by temporarily reverting one site during development, recorded).
- Backward-compat: C1 replay goldens byte-equal; REC-2/REC-3 unchanged; PB/WF unchanged.
- Gates: none.

**5. Acceptance criteria.**
- Under `higher`: every C1 golden deep-equal (winner ids, skip/bypass booleans, thresholds, reflection context values incl. `rank`/`is_new_best`/`is_more_efficient`, five `best_*` tracks).
- Under `lower` (strict rung): with identical records the trial winner is the argmin, `rank` counts strictly-lower scores, `is_new_best` flips, sentinels are `+inf` (bootstrap / skip-disabled) and `-inf` (bypass-disabled), all five tracks are argmin, the planner table comes from the argmin record; the loss rank and `best_same_loss_final_loss` identical to `higher`.
- Ties: first-wins preserved (replay case).
- `run()` AST branch count ≤ base; ruff / format clean; pyright on CI.

**6. Failure and edge cases.** All scores `None` → winner `None`, tracks `None` (both directions); a single score → `rank 1`, `range None`; `nan` score → filtered as non-finite before ordering (existing filters); a `+inf` score under `lower` is the worst value (never wins).

**7. Verification commands and evidence.**
- `.venv/bin/python -m pytest tests/unit/execute_tools/test_metric_order.py tests/unit/agent/tune_ml_hyperparam_agent -q > /tmp/07b_c2.log 2>&1; rc=$?; tail -20 /tmp/07b_c2.log`
- ruff / format; evidence in §14.

**8. Commit boundary.** one new module + tuner ordering + tests; no scale rules, no prompts; stop and show / record.

---

### C3 — P1-scale: classified scale rules + penalty guard + `AttemptTransition` REMOVE + rung B-07b-1s

**1. Goal.**
Make each scale-sensitive rule's classification executable (§3.3): signed
declared margins with the operator's disable convention preserved,
range-normalized efficiency band with ONE named constant, the penalty guard
(fail closed under `lower`); remove the consumer-less attempt-transition
types and record the `resolved_action` hazard (§3.5).
*Why this commit and not another*: scale rules are a distinct failure class
(a value can be wrong while the ordering is right); the removal is a
control-flow-neutral deletion whose parity evidence is the existing
round/attempt tests — it rides with the policy commit because it is the
same file and the same "no third state" acceptance.

**2. Scope.**
- Tuner: `_resolve_formal_comparison_thresholds(..., order)` uses `order.toward_better(ref, delta)`; the band in
  `_build_reflection_context` uses `EFFICIENCY_BAND_FRACTION = 0.05` (named constant exported for the prompt
  renderer) and `order.toward_worse`; startup guard `_validate_penalty_for_direction(agent_input, order)` (a typed
  helper; refuses a finite float penalty under `lower` — routed through the EXISTING startup-validation failure path,
  recorded in §14); delete `AttemptTransition` / `AttemptDecision`; add the hazard note next to `resolved_action`
  `:4337-4345`.
- `agent/schemas/hyperparam_tuning.py`: docstrings of `skip_formal_min_delta`, `bypass_formal_time_budget_min_delta`,
  `degenerate_penalty_score` re-worded (units = the golden metric's; the `lower` refusal documented); NO field, NO
  default change.
- Tests: `test_step07b_c3_scale_rules.py` — rung B-07b-1s (accuracy-like `higher` in [0,1]; MSE-like `lower` near 0)
  per §3.3 row; disable-value meaning under both directions; band mutation (raw-score `best − 0.05` → RED);
  penalty guard (both directions); the C1 replay still deep-equal under `higher`; DELETE `TestAttemptDecision`;
  UPGRADE `test_delta_gates.py` / `test_formal_launch_decision.py` / `test_degeneracy_handling.py` with the direction
  axis.
- Non-goals: no prompt change; no default change; no round-semantics change (the hazard is recorded, not fixed).
- Dependencies: C2.

**3. Implementation plan.**
- [x] All re-read. Startup refusal path audited: `validate_runtime_config` (`agent/schemas/hyperparam_tuning.py:2322`) raises `ValueError` at `run()` entry before any LLM call — but is shared with the workflow pre-flight and takes no metric, so the penalty guard is a tuner-local helper invoked on the SAME block (§14.2).
- [x] Rows 1/2/3/4/5 implemented (§14.2 table, every TIDMAD value proved identical); `EFFICIENCY_BAND_FRACTION` is ONE symbol; `_validate_penalty_for_direction` fails closed; three schema docstrings generalised with NO field or default change; `AttemptTransition`/`AttemptDecision` removed (repo-wide grep = 0) with the `resolved_action` hazard recorded at its declaration inside `run()`.
- [x] `test_step07b_c3_scale_rules.py` (28, rung B-07b-1s on accuracy-like and MSE-like scales); `test_delta_gates.py` gains the direction axis on the disable convention; `test_degeneracy_handling.py` gains the startup-refusal pairing; `TestAttemptDecision` DELETED with the reason in its place, `TestRoundOutcome` untouched (42 passed). 9/9 mutations RED.

**4. Validation plan.** Unit: new + upgraded families; `tests/unit/agent/tune_ml_hyperparam_agent` green (round/attempt semantics). Pseudo: replay deep-equal. Negative: band mutation; penalty under `lower`; a raw `ref + delta` reintroduction under `lower` → rung RED. Backward-compat: TIDMAD values identical (replay); schema JSON unchanged (docstrings only — REC-3 field lists unchanged). Gates: none.

**5. Acceptance criteria.** Row-by-row: (1) `higher`: `ref−1.0 / ref+0.0` identical; `lower`: `ref+1.0 / ref−0.0`; skip `delta=-inf` disables under both, bypass `delta=+inf` disables under both; (2)/(3) sentinels per §3.2; (4) band threshold = `best ∓ 0.05·range` by direction; `is_more_efficient` inverts orientation only; single-score unchanged; the prompt constant and the policy constant are ONE symbol; (5) `None` accepted both ways, finite float accepted under `higher`, REFUSED under `lower` with the recorded reason before any LLM call; the invalidated outcome holds (§3.4) under both; `AttemptTransition` / `AttemptDecision` gone from production (grep = 0), `TestRoundOutcome` green, retry / round tests green; the hazard note present.

**6. Failure and edge cases.** `reference=None` with gates on → bootstrap (unchanged); `range == 0` (all scores equal) → `range None` path (unchanged); penalty `None` + `lower` → fine; a run resumed with a persisted `formal_reference_score=+inf`-bootstrapped output under `lower` → `_json_safe_reference` writes `null` exactly as it does for `-inf` today.

**7. Verification commands and evidence.**
- `.venv/bin/python -m pytest tests/unit/agent/tune_ml_hyperparam_agent -q > /tmp/07b_c3.log 2>&1; rc=$?; tail -20 /tmp/07b_c3.log`
- ruff / format; evidence in §14.

**8. Commit boundary.** scale rules + guard + removal + tests + docstrings; no prompts; stop and show / record.

---

### C4 — P2: authority-rendered task blocks (byte-exact under TIDMAD) + OD-1 + rung B-07b-3

**1. Goal.**
Render the §3.6 tokens from their landed authorities through owned renderers
with EXACT bytes under TIDMAD (PB-1/PB-2 must pass UNCHANGED at the end of
this commit), pin the template constants free of the rendered literals, and
close OD-1.
*Why this commit and not another*: P2 is the "renders from the profile"
half whose acceptance is BYTE EQUALITY — keeping it separate from P3 (whose
acceptance is a declared byte CHANGE) makes every P2 mistake visible as a
golden failure with no regeneration to hide behind.

**2. Scope.**
- NEW `agent/prompt_templates/tuner/rendering.py`: `render_builtin_model_roster()`, `render_full_scope_segments(profile)`,
  `render_output_contract_shape(contract)`, `render_builtin_loss_types()`, `render_focal_defaults()`,
  `render_gate_name_tokens(effective_health_config)`, `EFFICIENCY_BAND_PCT` (from the C3 constant); each pure, typed.
- `agent/prompts.py`: the §3.6 RENDER tokens replace the literals in `PLANNER_PROMPT` / `REFLECTOR_PROMPT` /
  the USER builder (roster at `:1293`; shape at `:1070`); `_truncate_memory_history` iterates the record's own key
  order (OD-1).
- `agent/llm_bridge.py`: `plan(..., task_render: TunerTaskRender | None = None)` — the tuner builds the typed
  `TunerTaskRender` ONCE at run scope and passes it as ONE new kwarg (declared additive; WF-1 22 → 23 here; C5 adds
  `metric_spec` → 24 — the ONE final contract of §3.9); `task_render=None` at a real render → `ValueError`.
- Tests: `test_step07b_c4_task_rendering.py` (renderer units; TIDMAD byte-equality of each token vs the pre-C4
  literal captured in C1's ledger; template absence pins scoped to the rendered tokens; rung B-07b-3 with the
  Step-02 3-file contrast profile + a contrast contract + a renamed-check health config; OD-1: subprocess
  two-render byte equality for a 4-record history + NEW golden `pb1_planner_history4_user.txt` captured in THIS
  commit with provenance); WF-1 regenerated additively (three-part note); PB-1/PB-2 UNCHANGED (asserted by sha256
  in the ledger).
- Non-goals: no direction / metric / diagnosis wording (C5); no new task-config field; the KEPT literals of §3.6 stay.
- Dependencies: C3 (the band constant).

**3. Implementation plan.**
- [x] All re-read. `render_shape` lives at `agent/schemas/model_io_contract.py:206` (not `execute_tools/`); the shipped effective health config declares 3 blocking + 3 observational checks.
- [x] `agent/prompt_templates/tuner/rendering.py` — five renderers + frozen `TunerTaskRender` + `build_tuner_task_render`. The tuner builds it ONCE, immediately AFTER the effective-config path swap (built earlier the check names would come from the shipped default, not from what the run evaluates). `plan(task_render=None)` raises `ValueError` before any render.
- [x] Tokens substituted through the SAME `str.replace` seam the task description already used. OD-1 closed by record-own key order — 4 hash seeds now produce identical bytes (5 distinct orders before).
- [x] `test_step07b_c4_task_rendering.py` (17: per-token byte equality, scoped absence pins BOTH ways, rung B-07b-3, fail-closed, OD-1 subprocess stability, renderer reachability); `pb1_planner_history4_user.txt` captured (7 735 chars); WF-1 regenerated additively **22 → 23** with the three-part note. **PB-1 (3) and PB-2 (2) sha256 IDENTICAL to §14.0 — nothing regenerated.**

**4. Validation plan.** Unit: renderers; absence pins; byte-equality per token. Pseudo: PB-1/PB-2 goldens PASS unchanged (the acceptance); the pseudo tuner iteration renders. Negative: a template literal reintroduced → absence pin RED; a token rendering a different byte → PB golden RED; a `None` contract → shape token omitted (no crash). Backward-compat: PB-1/PB-2 sha256 identical to §14.0; WF-2 unchanged. Gates: none (P2 changes no byte under TIDMAD; the OD-1 ≥ 4-record change is covered by C6's Gate 1).

**5. Acceptance criteria.** PB-1 (3) / PB-2 (2) sha256 == §14.0 after C4; the five rendered tokens equal their pre-C4 literals under TIDMAD (per-token test); `PLANNER_PROMPT` / `REFLECTOR_PROMPT` contain none of the rendered literals; the contrast rung renders different roster / anchor / shape / gate-name / loss-list tokens; the OD-1 4-record render is byte-identical across two processes and matches the new golden; WF-1 kwarg set = 23 with the note.

**6. Failure and edge cases.** Effective health config without `output_diversity` / `amplitude_collapse` checks → the two advice sentences omitted (documented); a plugin-extended registry → roster still the six built-ins (documented; plugins are proposed, not rostered); `run_model_io is None` (a task without a contract) → shape omitted; profile with a different `num_files × segments_per_file` → the number renders.

**7. Verification commands and evidence.**
- `.venv/bin/python -m pytest tests/unit/agent -q > /tmp/07b_c4.log 2>&1; rc=$?; tail -20 /tmp/07b_c4.log`
- `sha256sum tests/unit/agent/llm_bridge/goldens/*` before/after (must be identical); ruff / format; evidence in §14.

**8. Commit boundary.** renderers + tokens + OD-1 + WF-1 additive + tests; no P3 wording; stop and show / record.

---

### C5 — P3: direction / identity / diagnosis rendering + bridge surfaces + PB/WF regeneration + rung B-07b-2

**1. Goal.**
Render the direction wording, the metric identity and the compact
`TrainingDiagnosis` lines at BOTH LLM surfaces from the handle and the 07a
record — exactly the §3.7 declared deltas — with the raw keys still hidden,
WF-1/WF-2 additive-only, and PB-1/PB-2 regenerated with provenance.
*Why this commit and not another*: it is the ONLY commit that changes LLM-
visible bytes on purpose; isolating it makes the golden diff reviewable
line-by-line against §3.7 and is what Gate 1 evaluates.

**2. Scope.**
- `agent/prompt_templates/tuner/rendering.py`: `render_metric_direction_words(spec)`,
  `render_metric_identity_line(spec)`, `render_training_dynamics_line(diagnosis, objective_kind: str | None)`,
  `render_planner_dynamics_block(records)` (diagnosis + each record's `training_history.objective_kind`),
  `render_reflector_dynamics_block(diagnosis)` (calls the line renderer with `objective_kind=None` — no extra
  transport, §3.8); a vocabulary guard test (no calibrated-label words).
- `agent/prompts.py`: the §3.7 wording deltas; the planner USER dynamics block (from the windowed records BEFORE
  hiding); the reflector USER block; the two SYSTEM compensating blocks replaced.
- `agent/llm_bridge.py`: `plan(..., task_render=…, metric_spec=None)` (the second new kwarg — WF-1 23 → 24),
  `reflect(..., metric_spec=None, training_diagnosis=None)`; `ValueError` when `metric_spec is None` at a real render;
  substitution of the direction / identity tokens (§3.9 is the ONE contract).
- Tuner: passes `run_metric.spec` to `plan` and `reflect`; passes the attempt's `training_diagnosis` (already
  derived at the 07a boundary) to `reflect` — sequencing only.
- Goldens: PB-1 (3 files) + PB-2 (2 files) + `pb1_planner_history4_user.txt` regenerated with the three-part note;
  WF-1 (24 kwargs) / WF-2 (call surface gains the two kwargs; `actual_results_keys` and `reflection_context_keys`
  UNCHANGED) regenerated additively; `test_step00_prompt_goldens.py` fixture surface passes the shipped spec.
- Tests: `test_step07b_c5_rendering.py` — renderer units (each direction; identity; diagnosis line for
  ok/absent/invalid/not-comparable; vocabulary guard); UPGRADED boundary tests: planner (block present, raw keys
  absent — extends `test_step06_planner_boundary.py`) and reflector (extends `test_step07a_reflector_boundary.py`:
  diagnosis block present, `actual_results` keys exact); bridge fail-closed; rung B-07b-2 (the `lower` spec, Pets
  accuracy↑, DAVIS mse↓ with the pack `expected/training_diagnosis_l1_fixture.json` — scoped residue assertions);
  the golden diff reviewed against §3.7 (line list recorded in §14).
- Non-goals: no policy change; no record change; no secondary-metric rendering; no interpreter rendering.
- Dependencies: C4.

**3. Implementation plan.**
- [x] All re-read, including the two pack `declared/metric_*.json` (Pets `accuracy` ↑, DAVIS `mse` ↓) and both `expected/training_diagnosis_l1_fixture.json`, which the rung consumes directly rather than through a new fixture.
- [x] `render_metric_direction_words` / `render_metric_identity_line` / `render_training_dynamics_line` / `render_planner_dynamics_block` / `render_reflector_dynamics_block` + the `CALIBRATED_LABELS` guard list; the §3.7 prompt deltas; `plan(metric_spec)` and `reflect(metric_spec, training_diagnosis)` both fail closed; the tuner passes `run_metric.spec` at both surfaces and the attempt's already-derived diagnosis at the reflector — sequencing only, `run()` branch count unchanged.
- [x] All six goldens regenerated in THIS commit with three-part notes; the diff was reviewed line by line and matches §3.7 exactly (table in §14.4). WF-1 **23 → 24**; WF-2 `actual_results_keys` **9 EXACT**, `reflection_context_keys` **23 EXACT**, the two new values recorded as ADDITIVE kwargs.
- [x] `test_step07b_c5_rendering.py` (38): direction/identity renderers across four declarations, the dynamics line in ok/absent/invalid/train-only/not-comparable states, the calibrated-vocabulary guard parametrized over all ten words, both fail-closed refusals, both boundary surfaces, and rung B-07b-2 over the `lower` spec + Pets accuracy↑ + DAVIS mse↓. Step-06 planner and 07a reflector boundary tests UPGRADED, not replaced.

**4. Validation plan.** Unit: renderers; boundary tests; bridge; rung. Pseudo: the pseudo tuner iteration renders both surfaces (RecordingLLMBridge captures) with the block present. Negative: raw key leak → RED; calibrated word → RED; `metric_spec=None` → `ValueError`; a delta outside §3.7 → reviewed diff (recorded). Backward-compat: `actual_results_keys` (9) and `reflection_context_keys` (23) unchanged; REC goldens unchanged; `test_denoising_score_field_name_preserved` green. Gates: Gate 1 at C6 (after docs), not here.

**5. Acceptance criteria.** The regenerated PB-1/PB-2 diffs touch exactly the §3.7 lines (+ the new blocks) and nothing else (line list in §14); under the `lower` spec the direction block reads "minimize … lower is better" and contains no "HIGHER … GOOD" residue in the scoped block; the planner dynamics block lists one line per verbatim-window record with a diagnosis and "none recorded" otherwise; the reflector block renders the current attempt's diagnosis; no calibrated label words; WF-1 = 24 kwargs, WF-2 surface additive with the two kwargs; boundary tests green at both renders.

**6. Failure and edge cases.** A record with `training_diagnosis.state="absent"` (legacy producer) → "none recorded" line; `invalid` → invalid line; a `TrainingDiagnosis` with `validation_state="absent"` → train-only line; a history window with zero diagnosis-carrying records → the block header + "none recorded" (kept, so the golden shape is stable); `spec.id` with unusual characters → rendered inside backticks verbatim.

**7. Verification commands and evidence.**
- `.venv/bin/python -m pytest tests/unit/agent tests/unit/nodes -q > /tmp/07b_c5.log 2>&1; rc=$?; tail -20 /tmp/07b_c5.log`
- `sha256sum` of the goldens before/after + the line-level diff summary; ruff / format; evidence in §14.

**8. Commit boundary.** rendering + bridge + goldens + tests; no policy; stop and show / record.

---

### C6 — Packs, node/skill docs, Checkpoint E, terminal validation, Gate 1

**1. Goal.**
Advance the three example packs honestly, synchronize the governance
surfaces (this ledger, parent §8.3, README rows, roadmap §15.1/§22.12,
genericity contract Seam 4 line, tuner `.md`), run the terminal validation,
and — with approval — the ONE Gate 1 at ≥ 2 rounds.
*Why this commit and not another*: docs and packs consume the finished
behaviour; the Gate evaluates the final executable head.

**2. Scope.**
- Packs (§3.12): TIDMAD README/STATUS rows; Pets / DAVIS STATUS rows (L1 via `declared/metric_*.json` consumed by
  B-07b-1/2); `tests/unit/examples/test_step07b_pack_pins.py` (string pins) — no new fixture files.
- `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.md`: order authority, scale-rule
  classification table, penalty guard, removed types + hazard note, what the LLMs see (direction / identity /
  dynamics blocks; hidden raw keys); `docs/design/genericity_contract.md` Seam 4 line ("tuner direction consumers
  landed 07b; peripheral consumers Steps 09/10/M2") + Seam 3 gap list (the KEPT literals of §3.6).
- Docs: this child's header + §14; parent §8.3 status; README index row 07b; `docs/README.md` row; roadmap
  §15.1 / §22.12 rows; `CLAUDE.md` current state.
- Terminal validation: full unit suite ONCE from a clean tree at the final executable head; ruff / format
  repo-wide; exact-head CI.
- **Gate 1** (§10) — readiness packet in §14 (property; the source-audited health-gate posture that lets stub
  records be `success`; command; bounds `max_rounds 2`, pseudo training, `openai_tiered_pro.json`; expected 3–8
  min / ~$0.3; PASS artifact = run_output records + the `_chat_json` tee showing direction wording + dynamics
  blocks present and no raw hidden key), operator approval, launch, result recorded.
- Non-goals: no production code beyond doc-string touch-ups; no new golden.
- Dependencies: C1–C5.

**3. Implementation plan.**
- [x] Pack rows + `tests/unit/examples/test_step07b_pack_pins.py` (16); tuner node `.md` (order authority + consumer table, scale classification, what the LLMs see, fail-closed bridge, the removed types); genericity contract Seam 4 closed for the tuner consumers + Seam 3 gap table; README / docs/README / roadmap §15.1 / parent §8.3 / CLAUDE.md rows; §14.0–§14.8.
- [x] Full suite from a clean tree at the post-C7 head `cb1a885a`: **9,787 passed, 3 skipped, 0 failed** (`/tmp/claude-1004/full_final.log`; verdict read from the log, not the wrapper exit code). ruff + `ruff format --check` clean repo-wide. CLI `--help` byte-identical to the pre-C7 baseline; all 18 PB/WF goldens sha256-unchanged. Pushed ONCE at `307fa0ce917c0afbd6ee5425fae7ef902b267019`; PR **#216**; exact-head CI **31989125173 SUCCESS** (ruff · ruff format · pyright strict · pytest); clean tree.
- [x] Readiness packet §14.5 → attempt 1 INCONCLUSIVE (harness reachability, §14.6) → operator-approved harness correction §14.6a → attempt 2 **PASS** §14.6b, with evidence A and B recorded separately and both new production findings deferred.

**4. Validation plan.** pins; full suite once; CI once; Gate 1 once (approved).

**5. Acceptance criteria — the parent's checkpoint ladder, each explicit.**
- Checkpoint 0 ✓ (C1 goldens + sha256s + declared-delta list recorded in §14.0).
- Checkpoint A ✓ (replay deep-equal under `higher`; PB exact except the §3.7 deltas; WF-1 = 24 / WF-2 additive-and-declared; REC unchanged; `run()` branch count not increased) — §14 evidence from C2–C5.
- Checkpoint B ✓ (B-07b-1, B-07b-1s, B-07b-2, B-07b-3 green — §6).
- Checkpoint C = Gate 1 PASS with the frozen posture and "executed" definition (§7).
- Checkpoint D ✓ (every §8 mutation / reachability row green — recorded per commit).
- Checkpoint E ✓ (pack pins green; PR0 governance guards green; node/skill/contract/governance docs synchronized; full-suite log 0 failed from a clean tree; exact-head CI green).

**6. Failure and edge cases.** Gate 1 planner returns a schema-invalid plan on the new wording → FAIL, wording fix, rerun after the fix (never a reroll of unchanged bytes); pseudo records collapse because the health-gate posture peeks absent deliverables → the readiness packet must have fixed the posture (else the Gate is inconclusive for the incumbent path and is re-planned, not rerolled).

**7. Verification commands and evidence.**
- `.venv/bin/python -m pytest tests/unit -m "not real_run" -q > /tmp/07b_full.log 2>&1; rc=$?; tail -20 /tmp/07b_full.log`
- Gate 1: the readiness packet's command; artifacts read from the workspace; recorded in §14.

**8. Commit boundary.** packs + docs; the Gate is evidence, not code; stop and show / record.

---

### C7 — Tuner node structural decomposition (operator scope amendment, 2026-08-16)

Added to this PR after C6 by operator amendment, then extended by the C7d
follow-up (decision A-prime). Zero semantic change is the defining constraint;
the differential oracle is the evidence, and every commit below re-ran it.

Split into eight git commits at clean boundaries, per the standing rule that a
planned commit is a logical unit:

| Commit | What landed | Evidence |
|---|---|---|
| `3d718101` C7 | five owned submodules (`policy`, `runtime`, `records`, `feedback`, `cli`); main 7,430 -> 3,170 | oracle 13/13 |
| `989b16d4` C7c | the node public-boundary rule made executable; `__all__` 17 public vs 83 `_COMPATIBILITY_REEXPORTS` | 16 boundary tests |
| `857a4927` | the C7d measurement and the decision it referred | doc only |
| `4f8449ee` C7d-1 | `contracts.py` + `RunBindings`; `planning.prepare_attempt` out of `run()` | oracle 12/12, branch nodes 198 -> 166 |
| `96e9b6eb` C7d-2 | `records.finalize_run_output` + `RunExitSnapshot` | oracle 12/12, 198 -> 137 |
| `d5f3681e` C7d-3 | the three execution subphases + the 1:1 control-signal translation | oracle 12/12, 198 -> 80 |
| `a9038635` C7d-4 | `records.build_attempt_record`; `PreparedAttempt` -> `contracts` | oracle 12/12, 198 -> 64 |
| `b5137bf8` C7d-5 | the deferred structural test pass, done once | tuner package 1,188 passed |

**Definition of done.** `run()` reads as a lifecycle and nothing else; every
internal module has one documented responsibility; the private graph is acyclic
and enforced; no external production code imports a node internal; no internal
module imports the main module; `brain.reflect(...)` still visible in `run()`;
zero mutable lifecycle state on `RunBindings`, structurally enforced; CLI,
record, prompt and Python interfaces unchanged; the three carried-forward
defects untouched. Full record: §14.9 - §14.9.5.

---

### Deferred to later PRs (NOT in 07b)

- Peripheral direction consumers (`core/resume.py`, `workflows/model_exploration.py`, `nodes/interpretation_helpers.py`, `execute_tools/per_file_best.py`, dashboard, `core/campaign_artifacts.py`) — **Steps 09 / 10 / M2** (they may import `MetricOrder`).
- The `resolved_action` round-outcome hazard fix — **a dedicated round-semantics correction** (operator decision on the intended outcome in the crash-after-scored-attempt case).
- Roster one-liners, CH1/CH2 metric prose, regressor/hybrid shape catalogue, subset loss ordering, class-127 / PSD-amplitude health prose — **Seam 3 task pack (Step 12) / Step 08**.
- Secondary-metric evidence rendering (none produced under TIDMAD today) — **Step 09 / Step 12**.
- Validation pricing (07a Gate-2 finding) — **07c**.

### Explicitly NOT re-opened

07a semantics (diagnosis fields, hiding mechanism, record fields); Step 06 (metric handle, scorer); D1 rename; the Step-00 golden regeneration rule (§17 rule 3); Q2 lettering; the schema defaults of the skip / bypass / penalty inputs.

---

## 16. Operator decisions — DISPOSED at the revision-1 review (2026-08-16)

| ID | Question | Recommendation (rev 1) | **Operator disposition** |
|---|---|---|---|
| **Q-07b-1** | `AttemptTransition` / `AttemptDecision`: REMOVE (types + tests) and record the `resolved_action` hazard with a proposed owner — vs WIRE with a per-attempt reset (changes round outcomes in the crash-after-scored-attempt case) | **REMOVE** (§3.5) | **APPROVED** |
| **Q-07b-2** | Penalty float under `lower`: fail closed at startup vs accept verbatim vs reinterpret (negate) | **fail closed** (§3.3 row 5) | **APPROVED** |
| **Q-07b-3** | Metric identity in prompts: keep the `denoising_score` FIELD noun and ADD the `spec.id` identity line vs render `spec.id` as the noun | keep field + add identity (§3.7) | **APPROVED** |
| **Q-07b-4** | Bridge surfaces: declared additive KWARGS vs new keys inside `reflection_context` / `task_description` | kwargs (§3.9) | **APPROVED WITH CORRECTION** — the final surface unified: `plan(task_render, metric_spec)`, `reflect(metric_spec, training_diagnosis)`, both fail-closed on `None` at a real render (§0.7 item 1) |
| **Q-07b-5** | OD-1: close by record-order iteration + a 4-record golden vs record why not | close (§3.10) | **APPROVED** |
| **Q-07b-6** | The two SYSTEM compensating blocks: REPLACE vs keep AND add | REPLACE (parent §8.3 P3) | **APPROVED** |
| **Q-07b-7** | Efficiency band constant `0.05`: framework generic (range-normalized) — classification (i) | confirm (§3.3 row 4) | **APPROVED** |
| **Q-07b-8** | Gate-1 posture and the incumbent / skip / bypass property | confirm (§7) | **APPROVED WITH CORRECTION** — the exact existing posture is FROZEN NOW (`--no-health_gate_enabled` + `--enable_chain_incumbent_formal_gates`, 2 iterations × 2 rounds) and "executed" is DEFINED (helpers reached + resolved values recorded; not both exclusive actions True) — §0.7 item 5, §7 |
| **Q-07b-9** | The "200 vs 4000" example anchors: render only 4 000 from the profile vs derive "200" from a default that does not exist | render 4 000 only (§3.6) | **APPROVED** |

Three further corrections were required WITHOUT new operator decisions and
are applied in this revision: `MetricOrder.worst` / `toward_worse` + the
signed-delta semantics (§3.2); the reflector renders `TrainingDiagnosis`
only, no `history_meta` transport (§3.8); Checkpoints B and D explicit
(§6, §8) and enumerated in C6; B-07b-2 without the classification /
regression phrasing claim (§6). Revision 2 was **FROZEN by the operator
(APPROVED FOR FREEZE, 2026-08-15)** after ONE final non-architectural
consistency pass (no revision-3 round): §3.1 file-table wording aligned with
§3.2 / §3.9, and the Gate-1 rounds-vs-iterations distinction + separate
PASS-evidence recording made explicit in §7 / §10.

## 17. Adversarial self-review (this child)

| # | Finding | Disposition |
|---|---|---|
| 1 | A `higher_is_better` boolean would re-create the "second direction field" the parent forbids | `MetricOrder` wraps the ONE spec; no boolean stored on records or inputs |
| 2 | Rewiring `max` sites one by one risks missing one — the census would then be silently wrong | the strict rung flips direction and asserts EVERY listed consumer inverts; reachability mutation replaces the authority with a sentinel object |
| 3 | The threshold arithmetic `ref + delta` looks generic under sign-flip — exactly the trap the parent named | classified DECLARED (units are the metric's; the operator owns the number); the disable convention proved under both directions |
| 4 | Negating the penalty under `lower` "to make it generic" | refused: fail closed instead; the invariant is structural |
| 5 | Rendering the roster / anchors / advice from authorities could quietly change TIDMAD bytes | P2's acceptance is that the goldens PASS UNCHANGED at the end of C4 — nothing regenerated |
| 6 | Un-owned facts (roster one-liners, CH1/CH2 prose, class-127) tempt an invented task-config field | recorded gaps (Seam 3 / Step 08); literals stay; the contrast rung asserts only the rendered tokens |
| 7 | Rendering the diagnosis by dumping the record key would repeat the Step-06 leak | owned renderer; raw keys stay hidden; boundary tests at both renders |
| 8 | Calibrated words could sneak into the dynamics reading guidance | vocabulary guard test on the renderer output; guidance is facts + direction |
| 9 | Passing `metric_spec=None` silently rendering TIDMAD words would hardcode TIDMAD in the bridge | `ValueError` at a real render |
| 10 | Wiring `AttemptTransition` "properly" is a control-flow rewrite of `run()` | REMOVE; hazard recorded with owner |
| 11 | OD-1 "fix" by sorting keys would change ≤ 3-record bytes? No — the condensed branch is never taken for ≤ 3 records | record-order iteration; PB-1 exact; new 4-record golden |
| 12 | The `"negative_infinity_bootstrap"` provenance string is direction-specific | kept as a stable label (record compatibility) with its meaning documented as "worst-value bootstrap" — a rename would be a record-vocabulary change (D1-adjacent) |
| 13 | Gate 1 in pseudo mode collapses every record (Step-06 precedent) and would not exercise incumbents | the readiness packet must audit and fix the health-gate posture BEFORE launch (Q-07b-8) |
| 14 | Extracting the reflection block could change `reflection_context` values | verbatim extraction first, replay deep-equal, THEN the authority rewire — two evidence points inside C2 |
| 15 (operator) | Two competing bridge contracts (`metric_spec` only vs `task_render` + `metric_spec`) | unified in §3.9; both fail closed on `None` |
| 16 (operator) | `worst` obtained by an opposite-direction order would be a second interpretation site | `MetricOrder.worst` / `toward_worse` in the ONE table; signed-delta semantics frozen |
| 17 (operator) | The reflector renderer consumed `history_meta` nothing transported | reflector renders the diagnosis only; planner adds `objective_kind` from the record |
| 18 (operator) | Gate-1 posture left to readiness — the 07a lesson (compute workload semantics before the expensive run) | frozen from source in §7 with the "executed" definition; bypass honestly NOT a PASS requirement |
