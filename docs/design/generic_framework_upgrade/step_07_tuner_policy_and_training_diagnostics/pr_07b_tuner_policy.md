# Step 07 — PR 07b: Tuner policy on the golden metric + planner/reflector rendering (Gate 1) — detailed design

| Field | Value |
|---|---|
| Parent | `../step_07_tuner_policy_and_training_diagnostics.md` (revision 2, FROZEN 2026-08-15) §8.3 — the 07b acceptance contract; §2.2/§2.3 census; §12.1/§12.2/§12.6 invariants; §18 OD-S7-6 (deferred to this child); §20 WHAT/HOW line |
| Roadmap | §7a (couplings, target, Rev 5 policy half), §22.6 (persistence ≠ prompt visibility; consumer split item 5), §22.7 (no hidden multi-objective), §22.8, §22.9a (Pets accuracy↑ / DAVIS mse↓ golden metrics via the PR0 `declared/metric_*.json`), §22.12 row 07b, §22.13 (Gate corpus breadth); §15.1 step-7 row (`§7a`) |
| Design base | `787afa08` (master; 07a MERGED `65804b3d` + finalizer) — every source line below was re-read at this head |
| Depends on | 07a MERGED (record fields `training_history` / `training_diagnosis`, `TrainingDiagnosis` schema, Stub/pseudo multi-epoch histories, hidden-key sets); Step 06 MERGED (`MetricSpec.direction`, `run_metric` bound at run scope); Step 00 goldens PB-1/PB-2/WF-1/WF-2/REC; PR0 packs (`declared/metric_*.json`) |
| Decomposition | ONE PR, six commits **C1 → C6** (§15): replay oracle · P1-order + validity · P1-scale + attempt-transition disposition · P2 authority-rendered task blocks + OD-1 · P3 owned rendering deltas + bridge surfaces · rungs / packs / docs / Checkpoint E + Gate 1 |
| Gates | Gate 1 **REQUIRED, ≥ 2 rounds** (P3 changes LLM-facing SYSTEM prompt bytes; parent §11 row 07b; OD-20-6) · Gate 2 **NOT REQUIRED** (no execution-launch change; flip: any training/inference/scoring launch or execution change → Gate 2) |
| Status | **DRAFT — for operator review (revision 1, 2026-08-16). Implementation NOT started; §14 ledger empty; implementation only under a fresh Implementation Working Rules contract after freeze.** |

`[ ]` = not done · `[x]` = done **and** verified with recorded evidence.

**What this child FREEZES on approval (HOW)**: the ONE order authority
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
                                             (is_better / is_at_least_as_good / best / rank / worst_sentinel /
                                             best_sentinel / signed_margin) — pure, importable by the tuner today and by
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
agent/llm_bridge.py                          plan(..., metric_spec=None) / reflect(..., metric_spec=None,
                                             training_diagnosis=None): substitution of the new tokens (declared additive
                                             kwargs; WF-1/WF-2 additive deltas)
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
MetricOrder(spec: MetricSpec)                       # execute_tools/metric_order.py
  direction            = spec.direction                       ("higher" | "lower")
  is_better(a, b)      = a > b   if higher  else a < b
  is_at_least(a, b)    = a >= b  if higher  else a <= b
  best(items, key)     = max(...) if higher else min(...)     (ties: FIRST item wins — today's max() semantics)
  rank(values, x)      = 1 + #(v strictly better than x)      (== today's sorted(reverse=True).index(x)+1 for higher)
  worst_sentinel       = -inf if higher else +inf             (the "nothing is worse" value)
  best_sentinel        = +inf if higher else -inf             (the "nothing is better" value)
  toward_better(ref, d)= ref + d if higher else ref - d       (a signed margin in the metric's units, §3.3)
```

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
| 7 reflection `best_score`, `best_record`, `rank`, `worst_score`, `is_new_best` | `max / sorted(reverse=True) / min / >` | `order.best / order.rank / order.best with the opposite direction (worst) / order.is_better` |
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

- Source of truth: the 07a record fields (`ExperimentRecord.training_diagnosis`, and `training_history.objective_kind` /
  `comparability` for the label) — never recomputed (§22.6 item 3).
- Renderer: `agent/prompt_templates/tuner/rendering.py::render_training_dynamics_line(diagnosis, history_meta) -> str`
  — ONE compact line, e.g.
  `train R2 2.90→2.35 (decreasing, 5 ep) · val R3 2.95→2.62 (decreasing; best ep 3, +0.07 after best) · gap +0.27 (comparable)`;
  `absent` → `training dynamics: none recorded`; `invalid` → `training dynamics: invalid (non-finite)`;
  `comparability != established` → the gap clause reads `gap n/a (not comparable)`. NO overfitting / plateau /
  converged / underfitting words (07a rule; a test asserts the vocabulary is absent from the renderer's output).
- Planner: the block is built by `get_planner_user_prompt` from the SAME `windowed` records BEFORE `_planner_visible`
  strips the hidden keys — the raw `training_diagnosis` / `training_history` keys stay hidden from the JSON dump
  (Step-06/07a boundary tests keep passing; a new boundary test asserts the block is present AND the raw keys are absent).
- Reflector: the tuner passes the CURRENT attempt's diagnosis (the value it derived at the boundary in 07a) to
  `brain.reflect(..., training_diagnosis=<TrainingDiagnosis | None>)`; the bridge renders the block into the USER
  prompt via the renderer; `actual_results` stays the legacy payload (WF-2 `actual_results_keys` EXACT).
- Cadence / persistence unchanged; nothing new is written to records.

### 3.9 Bridge / kwarg surface deltas (FROZEN on approval — declared additive)

```text
LLMBridge.plan(..., metric_spec: MetricSpec | None = None)          # +1 kwarg → WF-1 kwarg key set 22 → 23 (declared)
LLMBridge.reflect(exp_id, hypothesis, actual_results, reflection_context=None,
                  *, metric_spec: MetricSpec | None = None,
                  training_diagnosis: TrainingDiagnosis | None = None)  # WF-2: actual_results_keys EXACT (9);
                                                                          # reflection_context_keys EXACT (23);
                                                                          # the two new values travel as kwargs, recorded
                                                                          # additively in the WF-2 surface golden
```

- `metric_spec=None` (a caller predating 07b, e.g. the PB fixtures until regenerated) → the renderer emits the
  direction-NEUTRAL wording? **No — fail closed at the bridge**: `None` renders the TIDMAD-compatible words ONLY when
  the caller is the shipped TIDMAD path? That would hardcode TIDMAD in the bridge. **Decision:** `metric_spec` is
  REQUIRED for rendering; the tuner always passes `run_metric.spec`; the bridge raises `ValueError` when it is `None`
  (test fixtures pass the shipped spec via `derive_tidmad_metric_spec(TIDMAD_PROFILE)`; the pseudo bridges accept it).
  Signature default `None` exists only so the WF-1 golden's kwarg surface stays additive and the stub bridges'
  dispatch is unchanged; a real render without it is a contract error.
- WF-1/WF-2 goldens regenerated additively in C5 with the three-part note.

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

## 5. Stage-A parity (Checkpoint 0 / A)

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

## 6. Stage-B rungs (declared REQUIRED by the parent)

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
  direction-only spec, (ii) the Pets `declared/metric_accuracy.json` (accuracy↑, classification phrasing) and (iii)
  the DAVIS `declared/metric_mse.json` (mse↓, regression phrasing) with a Pets / DAVIS 07a fixture history
  (`examples/*/expected/training_diagnosis_l1_fixture.json`) → SCOPED assertions (Step-01 §13.4): the direction
  block carries no higher-is-better residue for `lower`, the diagnosis lines are present, the metric id renders,
  and NO calibrated label word appears; whole-prompt absence is not asserted.
- **B-07b-3 task-content axis (L1):** the Step-02 3-file contrast profile + a contrast model-I/O contract + an
  effective health config with renamed checks → different roster / anchor / contract / gate-name tokens; the
  TEMPLATE constants carry no literal for any rendered token (template-scoped absence pins on `PLANNER_PROMPT` /
  `REFLECTOR_PROMPT` for `4000`, `[B, 256, T]`, `punet | fcnet`, `output_diversity`, `alpha=0.5`, `5%`); the KEPT
  literals of §3.6 are NOT asserted absent (they are recorded gaps).

## 7. Checkpoint C — Gate 1 (≥ 2 rounds)

Real gpt-5.5 planner / reflector / proposer / implementor / validator, pseudo
training (StubSandbox — 07a multi-epoch histories, so diagnosis lines render
from a real trajectory), `max_rounds ≥ 2` so the round-2 planner sees a
rendered round-1 record and the incumbent / skip / bypass path is exercised
across rounds; PLUS the deterministic replay. Precedent shape: Step-06 Gate 1
(`run_one_iteration.py … --max_rounds 2 --max_epochs 1 --data_scope 4-9
--health_gate_files 4,5,6,7,8,9 --is_pseudo_training --llm_config
llm_configs/openai_tiered_pro.json`; the Step-06 run collapsed every pseudo
record under `--healthgate_mode blocking` because pseudo training writes no
deliverables). **07b's Gate 1 needs stub-scored records to be `success`
so incumbent / skip / bypass are exercised** → the readiness packet fixes
the health-gate mode / stub-deliverable posture from source before launch
(§15 C6; the standard's Gate-1 bounds and cost apply; a passive
`_chat_json` tee records every planner / reflector message so the
"direction wording present, raw keys absent" claim is auditable).

## 8. Failure classes (each has a test or a stop rule)

| Failure | Behaviour |
|---|---|
| a consumer bypasses the order authority (keeps `max` / `<`) | strict rung RED (direction flip does not invert that consumer); reachability test: `MetricOrder` monkeypatched to a sentinel-returning object → production selection RED |
| sentinel mutation (`-inf`↔`+inf` under `lower`) | rung RED |
| a scale rule silently reverts to a raw-score default | policy-semantics rung RED |
| penalty float under `lower` | refused at startup with the recorded reason (never a "better" incumbent read by the planner) |
| invalidated result becomes an incumbent | validity outcome test RED under both directions |
| loss rank flips with the metric | pinned test RED |
| a P2 token renders a different byte under TIDMAD | PB-1/PB-2 goldens RED at C4 (nothing regenerated in C4) |
| a P3 delta outside §3.7 | golden diff review + the declared-delta list in the ledger; test that the diff of the regenerated goldens touches ONLY the declared lines (line-set assertion recorded, not a test — reviewed) |
| raw `training_history` / `training_diagnosis` / `metric_*` keys leak into a render | boundary tests RED (both renders) |
| a calibrated label word rendered from the diagnosis | renderer vocabulary test RED |
| `metric_spec=None` at a real render | bridge `ValueError` (fail closed) |
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

- **Gate 1 REQUIRED, ≥ 2 rounds** (P3 changes SYSTEM prompt bytes; OD-20-6): ONE bounded run at the final
  executable head after C6, real `openai_tiered_pro.json`, pseudo training, cold-start; PASS = the standard's Gate-1
  criteria + the 07b property (round-2 planner receives round-1's rendered dynamics line and direction wording;
  reflector receives the diagnosis block; no raw hidden key in any message; skip / bypass / incumbent path executed
  across the two rounds as recorded in `run_output`). **NOT launched without operator approval at launch** (or a
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

*(empty until implementation; each commit's evidence lands here —
Checkpoint-0 captures, counts, wall time, deviations, tests that could not
run and why; the Gate-1 readiness packet, approval, command, result.)*

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
- [ ] Re-read `ml_hyperparameter_tune_agent.py:1534-1704, 1984-2042, 4140-4180, 4360-4400, 4460-4475, 5140-5185, 5787-5900, 6400-6560` and `tests/helpers/step00_pseudo_iteration.py` (line drift check).
- [ ] Author the corpus (each history names the case it exercises); capture the three goldens through the current code; record sha256s + delta list + OD-1 evidence in §14.0.
- [ ] Write the replay test module (loads goldens; asserts deep-equal today — a tautology by construction at C1, the guard for C2/C3).

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
- [ ] Re-read the §0.1 sites (line drift), `test_step06_c6_stage_b_direction_rung.py:79-87`, `test_step06_c2_tuner_metric_binding.py:73-107`.
- [ ] Implement `MetricOrder`; promote `_direction_only_metric` to `tests/helpers/metric_fixtures.py` (original test keeps importing it).
- [ ] Extract `_build_reflection_context` and `_select_best_records` VERBATIM first (parity commit-internal step: replay green), then route ordering through the authority (replay still green), then the strict rung.
- [ ] Rewire the gate helpers + planner incumbent + banners; record the `run()` AST branch count.
- [ ] Tests as listed; UPGRADE the selection pins.

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
- [ ] Re-read `:1620-1704`, `:1984-2042`, `:5846-5878`, `:364-414`, `:4337-4345`, the schema docstrings `:1487-1620`; the startup-validation failure path (audit which helper carries a config refusal; record the choice).
- [ ] Implement rows 1, 4, 5; the constant; the guard; the docstrings; the removal + hazard note.
- [ ] Tests as listed; upgrade / delete per §9.

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
- `agent/llm_bridge.py`: `plan(..., task_render: TunerTaskRender | None = None)`? **No** — to keep WF-1 minimal the
  rendered task facts travel INSIDE the existing `task_description`-style substitution: the tuner builds a typed
  `TunerTaskRender` (profile / contract / health config / registry facts) ONCE at run scope and passes it as ONE
  new kwarg `task_render` (declared additive; WF-1 22 → 23 in C4; C5 adds `metric_spec` → 24). Recorded as such.
- Tests: `test_step07b_c4_task_rendering.py` (renderer units; TIDMAD byte-equality of each token vs the pre-C4
  literal captured in C1's ledger; template absence pins scoped to the rendered tokens; rung B-07b-3 with the
  Step-02 3-file contrast profile + a contrast contract + a renamed-check health config; OD-1: subprocess
  two-render byte equality for a 4-record history + NEW golden `pb1_planner_history4_user.txt` captured in THIS
  commit with provenance); WF-1 regenerated additively (three-part note); PB-1/PB-2 UNCHANGED (asserted by sha256
  in the ledger).
- Non-goals: no direction / metric / diagnosis wording (C5); no new task-config field; the KEPT literals of §3.6 stay.
- Dependencies: C3 (the band constant).

**3. Implementation plan.**
- [ ] Re-read `agent/prompts.py:10-221, 223-310, 852-935, 1044-1108, 1272-1307`, `agent/llm_bridge.py:765-919`, `models_sandbox.py:732-752`, `model_io_contract.py:206-217`, `health_checks/config.py:300-324`, `models_format_sandbox.py:384-387, 637-641`.
- [ ] Implement the renderers + `TunerTaskRender`; the tuner builds it once at run scope from `run_profile`, `run_model_io`, the effective health config path it already materialized, and the registry.
- [ ] Replace the literals by tokens; substitute in the bridge; OD-1 key order.
- [ ] Tests as listed; capture the 4-record golden; regenerate WF-1 additively.

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
  `render_metric_identity_line(spec)`, `render_training_dynamics_line(diagnosis, history_meta)`,
  `render_planner_dynamics_block(records)`, `render_reflector_dynamics_block(diagnosis)`; a vocabulary guard test
  (no calibrated-label words).
- `agent/prompts.py`: the §3.7 wording deltas; the planner USER dynamics block (from the windowed records BEFORE
  hiding); the reflector USER block; the two SYSTEM compensating blocks replaced.
- `agent/llm_bridge.py`: `plan(..., metric_spec=None)`, `reflect(..., metric_spec=None, training_diagnosis=None)`;
  `ValueError` when `metric_spec is None` at a real render; substitution of the direction / identity tokens.
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
- [ ] Re-read `agent/prompts.py` P3 lines (§0.3), `agent/llm_bridge.py:765-967`, the tuner call sites `:4476-4516`, `:5930`, `test_step00_prompt_goldens.py`, both boundary tests, `examples/*/declared/metric_*.json`, `examples/*/expected/training_diagnosis_l1_fixture.json`.
- [ ] Implement renderers + prompt deltas + bridge kwargs + tuner sequencing.
- [ ] Regenerate PB-1/PB-2/WF-1/WF-2 (+ the 4-record golden) in THIS commit; diff reviewed line-by-line vs §3.7; record the touched-line list.
- [ ] Tests as listed.

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
- [ ] Pack rows + pins; node doc; contract doc; governance rows; §14.
- [ ] Full suite from a clean tree; push; PR; exact-head CI (id in the PR body — no trailing docs-only push).
- [ ] Gate-1 readiness packet → approval → launch → record (PASS / FAIL / inconclusive, wall time, cost, the message excerpts).

**4. Validation plan.** pins; full suite once; CI once; Gate 1 once (approved).

**5. Acceptance criteria.** Pack pins green; PR0 governance guards green; full-suite log 0 failed; CI green on the exact final head; Gate 1 PASS with the 07b property (round-2 planner message contains the round-1 dynamics line + the direction block; reflector messages contain the dynamics block; zero raw hidden keys; skip / bypass / incumbent path recorded across the two rounds).

**6. Failure and edge cases.** Gate 1 planner returns a schema-invalid plan on the new wording → FAIL, wording fix, rerun after the fix (never a reroll of unchanged bytes); pseudo records collapse because the health-gate posture peeks absent deliverables → the readiness packet must have fixed the posture (else the Gate is inconclusive for the incumbent path and is re-planned, not rerolled).

**7. Verification commands and evidence.**
- `.venv/bin/python -m pytest tests/unit -m "not real_run" -q > /tmp/07b_full.log 2>&1; rc=$?; tail -20 /tmp/07b_full.log`
- Gate 1: the readiness packet's command; artifacts read from the workspace; recorded in §14.

**8. Commit boundary.** packs + docs; the Gate is evidence, not code; stop and show / record.

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

## 16. Operator decisions — OPEN for the revision-1 review

| ID | Question | Recommendation |
|---|---|---|
| **Q-07b-1** | `AttemptTransition` / `AttemptDecision`: REMOVE (types + tests) and record the `resolved_action` hazard with a proposed owner — vs WIRE with a per-attempt reset (changes round outcomes in the crash-after-scored-attempt case) | **REMOVE** (§3.5): wiring cannot both fix the hazard and keep round semantics unchanged; the fix needs an operator decision on intended semantics |
| **Q-07b-2** | Penalty float under `lower`: fail closed at startup (recommended) vs accept the operator's value verbatim vs reinterpret (negate) | **fail closed** (§3.3 row 5): the outcome invariant is already structural (status filters); reinterpretation would be exactly the "generic by sign-flip" the parent forbids |
| **Q-07b-3** | Metric identity in prompts: keep the `denoising_score` FIELD noun and ADD the `spec.id` identity line (recommended) vs render `spec.id` as the noun (mismatches the record key the LLM reads) | keep field + add identity (§3.7) |
| **Q-07b-4** | Bridge surfaces: `metric_spec` / `training_diagnosis` / `task_render` as declared additive KWARGS (recommended) vs new keys inside `reflection_context` / `task_description` | kwargs (§3.9): typed, WF goldens stay additive-and-declared |
| **Q-07b-5** | OD-1: close by record-order iteration + a 4-record golden (recommended) vs record why not | close (§3.10) — an LLM-visible change only for ≥ 4-record histories, inside this PR's Gate 1 |
| **Q-07b-6** | The two SYSTEM "TRAINING vs VALIDATION" / "GAP ANALYSIS" compensating blocks: REPLACE by the dynamics reading guidance (parent wording "replaced") vs keep AND add | REPLACE (parent §8.3 P3) |
| **Q-07b-7** | Efficiency band constant `0.05`: framework generic (range-normalized) — confirm classification (i) | confirm (§3.3 row 4) |
| **Q-07b-8** | Gate-1 posture: pseudo training with a health-gate mode that lets stub records be `success` (audited from source in the readiness packet) — confirm that the incumbent / skip / bypass path is a required Gate-1 property for 07b | confirm (§7) |
| **Q-07b-9** | The "200 vs 4000" example anchors: render only the full-scope number (4 000) from the profile and keep the example-portion prose literal (recommended) vs derive "200" from a default that does not exist | render 4 000 only (§3.6) |

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
