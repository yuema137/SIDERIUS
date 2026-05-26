# Unit Test Rubric Audit — SIDERIUS

**Date:** 2026-05-25
**Branch:** feat/scoring-mem-audit
**Mode:** Read-only analysis. No source files were modified. No integration tests were touched.

## 1. Purpose and rubric

This ledger captures a full clustered audit of the SIDERIUS `tests/unit/` tree against the
project's testing philosophy for LLM-agent codebases. The intent is to identify unit tests
whose value is undermined by mock-circularity, by duplication with static analysis (ruff /
pyright), or by integration-layer concerns that belong in the dual-mode / real-API suites.

**KEEP** — pure logic with no LLM circularity:
- Pure parsers / serializers (LLM text → structured)
- Pydantic schema validation and round-trips
- Prompt-template substitution (deterministic prompt construction)
- State-machine transitions and dispatch routing with no LLM call
- Pure utility functions (math, strings, dates, paths)
- Specific runtime edge cases that static analysis cannot reason about
  (empty strings, boundary integers, malformed JSON)

**FLAG** — circular or redundant:
- Patches `LLMBridge` / OpenAI / Gemini client and then asserts on values the mock returned
- Mocks tool execution (`subprocess`, sandbox, skills) and asserts on downstream agent decisions
- >50 % of the test body is mock setup boilerplate
- Removing the mock would make the assertion meaningless
- Duplicates ruff (import order, unused names, mutable defaults, etc.) or pyright (type
  correctness, return types, attribute access on unions)
- Duplicates an existing integration test (`tests/integration/`) for the same behaviour

## 2. Methodology and coverage caveat

The audit was executed by four parallel research agents partitioning the 136-file tree into
four balanced thematic slices:

| Slice | Scope                                                                 | Files |
|-------|-----------------------------------------------------------------------|-------|
| A     | tune_ml_hyperparam_agent/ + evaluate_vram_skill/ + skills             | 34    |
| B     | ml_model_proposal_agent/ + implementor/ + validator/ + protocols      | 36    |
| C     | llm_bridge/ + result_interpretation_agent/ + core/ + dashboard        | 34    |
| D     | execute_tools/ + ml_models/ + scripts/ + workflows/ + sdsc + tools    | 32    |

**Authoritative test count (grep ground truth, `^\s*(async )?def test_` across all 136 files): 2 479.**
The agents collectively classified **1 411** individual tests (≈57 % of the tree). Large files
(e.g. `test_llm_bridge.py` 63 tests, `test_hyperparam_schemas.py` 86 tests,
`test_interpretation_agent.py` 71 tests, `test_pipeline_runner.py` 63 tests) were partially
sampled rather than enumerated test-by-test. The flag inventory below is therefore a **floor**
on circular tests, not a ceiling — every entry in the clustered table is a confirmed positive,
but more circular tests likely exist in the un-sampled portions of those large files.

## 3. Macro counts

| Metric                                                  | Count  |
|---------------------------------------------------------|--------|
| Test files scanned                                      | 136    |
| Tests in tree (grep ground truth)                       | 2 479  |
| Tests individually classified by agents                 | 1 411  |
| Of classified — kept                                    | 1 125  |
| Of classified — flagged                                 | **286** |
| Of flagged — redundant with ruff / pyright              | 0      |
| Of flagged — LLM-mock circularity                       | ≈ 250  |
| Of flagged — integration duplication / mock circularity | ≈ 36   |

**Headline finding.** The dominant pathology is **LLM-mock circularity** — tests that patch
`LLMBridge.generate` (or downstream `OpenAI` / `Gemini` clients) and then assert on values the
mock just handed back. Zero tests were flagged for ruff/pyright duplication, indicating the
static-analysis layer is well separated from runtime testing in this codebase.

## 4. Clustered flag table

Columns: `Module/File · Rubric Flaw · Flagged Test Cases (bullet list) · Actionable Refactor Recipe`.

### 4.1 Slice A — tune_ml_hyperparam_agent + evaluate_vram_skill + skills

| Module/File | Rubric Flaw | Flagged Test Cases | Actionable Refactor Recipe |
|---|---|---|---|
| tune_ml_hyperparam_agent/test_constraint_aware_retry.py | Mocks LLMBridge + TidmadSandbox + skills; assertion driven entirely by mock returns | • test_does_not_raise_does_not_advance_rounds<br>• test_all_records_saved_as_schema_violation<br>• test_record_memory_carries_violation_details | Move to integration suite — the test mocks the agent's entire execution context and validates only mock-driven paths. |
| tune_ml_hyperparam_agent/test_evaluate_time_skill.py | Monkeypatches phase estimators; assertion is on wrapper output computed from stub returns | • test_run_skill_uses_warmup_when_data_dir_and_measurement_available<br>• test_run_skill_falls_back_to_static_when_warmup_returns_none<br>• test_run_skill_skips_warmup_without_data_dir<br>• test_warmup_scales_inference_ms_by_ratio<br>• test_unregistered_model_type_emits_warning_and_flags_breakdown<br>• test_registered_model_type_does_not_emit_warning<br>• test_median_aggregator_surfaces_on_breakdown<br>• test_fast_fail_aggregator_surfaces_on_breakdown<br>• test_no_data_dir_aggregator_is_none<br>• test_legacy_breakdown_keys_still_present | Rewrite as pure-logic tests that exercise wrapper routing with synthetic data shapes (no monkeypatched estimators), OR move to integration with real estimators. |
| tune_ml_hyperparam_agent/test_force_formal_round.py | Mocks LLMBridge + TidmadSandbox to drive plan-override chains; inheritance logic duplicates Pydantic validation | • test_force_formal_on_forces_formal<br>• test_force_formal_off_honours_planner<br>• test_force_formal_inherits_full_winner_config<br>• test_force_formal_inheritance_resilient_to_missing_train_keys<br>• test_force_formal_model_cfg_inheritance_isolated_from_winner<br>• test_no_trial_winner_falls_back_to_planner_with_warning | Delete the mocked tests, keep the pure plan-mutation tests. Inheritance logic should be a pure-function test on ExperimentPlan objects without the agent scaffolding. |
| tune_ml_hyperparam_agent/test_hardware_context_init.py | Test body is entirely mock setup (LLMBridge, sandbox, skills); only assertion is file existence | • test_manifest_written_on_run<br>• test_manifest_round_trips_to_schema<br>• test_second_run_does_not_rewrite_manifest | Move to integration — file I/O + agent orchestration requires the full harness. |
| tune_ml_hyperparam_agent/test_inference_hint_path.py | Monkeypatched phase estimators drive the only assertion | • test_breakdown_carries_required_keys | Assert on real (un-mocked) wrapper output or move to integration. |
| tune_ml_hyperparam_agent/test_per_round_attempt_budget.py | Mocks the entire agent execution to test budget orchestration | • test_attempts_per_round_pinned_on_input<br>• test_max_fail_rounds_drives_abort<br>• test_formal_round_has_separate_budget<br>• test_overflow_captured_on_output | Move to integration — budget enforcement is an orchestration concern. |
| tune_ml_hyperparam_agent/test_physical_rejection_capture.py | Mocks LLMBridge + sandbox + skills; record-building driven by mock skill returns | • test_rejection_message_captured_in_memory<br>• test_message_present_even_on_cpu_only<br>• test_output_contains_all_records | Convert to integration — record capture during agent execution requires the real loop. |
| tune_ml_hyperparam_agent/test_planner_resource_budgets.py | Mocks the agent to test that budget params flow through mocked prompt calls | • test_trial_budget_edges_appear_in_planner_prompt<br>• test_formal_budget_edges_appear_in_planner_prompt<br>• test_budget_none_produces_no_prompt_lines<br>• test_all_three_budgets_render_independently | Delete — assertion is on mocked prompt text. Test prompt construction as a pure-function unit on the prompt-building helper. |
| tune_ml_hyperparam_agent/test_silent_train_crash_routing.py | Mocks skill returns; no deterministic logic under test | • test_error_training_record_saves_conclusion<br>• test_output_marks_status_partial | Delete — validates the agent's response to mocked skill failures. |
| tune_ml_hyperparam_agent/test_tuning_agent.py | Large-scale mocking of LLMBridge, sandbox, and skills to test agent orchestration end-to-end | • test_valid_output_roundtrips_json<br>• test_all_records_included<br>• test_expert_advice_string_serialized_to_brain<br>• test_expert_advice_structured_serialized_to_brain<br>• test_run_config_written_at_startup<br>• test_returned_config_matches_initial<br>• test_best_score_from_all_records<br>• test_partial_status_set_on_early_termination<br>• test_completed_status_after_all_rounds<br>• test_oom_records_included_in_output<br>• test_max_rounds_three_attempts_per_round<br>• test_skill_order_plan_before_skills<br>• test_mixed_success_and_oom_produces_best<br>• test_planner_called_with_expert_advice<br>• test_output_file_written | Move to integration suite — entire file tests orchestration + I/O. Mocks prevent any validation of real behavior. |
| tune_ml_hyperparam_agent/test_tuning_cli.py | Mocks agent.run() to test CLI scaffolding | • test_cli_parses_arguments<br>• test_cli_calls_agent_run | Delete — CLI integration logic belongs in integration suite. |
| evaluate_vram_skill/test_wrapper_contract.py | Mocks primitives (structural_probe, overhead, batch_resolver, etc.); return-shape assertions driven by mock returns | • test_return_dict_has_required_keys<br>• test_inference_batch_key_present<br>• test_memory_killer_key_present<br>• test_inference_batch_uncalibrated_key_absent<br>• test_vram_budget_field_preserved<br>• test_hardware_context_none_falls_back_to_discover<br>• test_cpu_only_short_circuit_honored<br>• test_over_budget_training_vram_routes_to_killer_report<br>• test_over_budget_training_intensity_routes_to_killer_report<br>• test_over_budget_inference_resolver_routes_to_killer_report<br>• test_schema_violation_path_preserved | Delete the mocked tests; wrapper contract should be exercised with real primitives in integration. |

### 4.2 Slice B — proposal / implementor / validator / protocols

| Module/File | Rubric Flaw | Flagged Test Cases | Actionable Refactor Recipe |
|---|---|---|---|
| ml_model_proposal_agent/test_boldness_enforcement.py | Mocks LLMBridge.generate and asserts on mocked response content for retry-machinery validation | • test_boldness_passes_when_above_threshold<br>• test_boldness_retry_triggered_when_below_threshold<br>• test_boldness_error_injected_into_accumulated<br>• test_boldness_error_carries_current_and_predicted_values<br>• test_tiny_delta_rejected<br>• test_custom_policy_threshold<br>• test_boldness_uses_absolute_delta<br>• test_no_retry_when_causal_reasoning_stage_absent<br>• test_missing_prediction_skips_boldness_check | Convert entire file to integration — every test rests on mocked LLM responses. |
| ml_model_proposal_agent/test_citation_discipline.py | Mocks LLMBridge and asserts on memo notes generated by mocked outputs | • test_violations_appended_to_memo_consistency_notes<br>• test_no_violations_when_all_citations_referenced<br>• test_existing_memo_consistency_notes_preserved<br>• test_empty_citation_sources_no_notes_added<br>• test_empty_list_returns_no_violations | Keep the pure-function helpers; convert the pipeline-level tests to integration. |
| ml_model_proposal_agent/test_pipeline_runner.py | Mocks LLMBridge and asserts on behaviour wired to mocked stage outputs; mock-circularity on boldness, retry, model selection | • test_pipeline_produces_valid_output<br>• test_pipeline_calls_bridge_3_times<br>• test_disabled_stage_skipped<br>• test_legacy_mode_when_no_stages<br>• test_retry_on_duplicate_model_name<br>• test_retry_on_validation_error<br>• test_error_injected_into_prompt_on_retry<br>• test_stages_1_and_2_not_rerun_on_retry<br>• test_exhausted_retries_raises<br>• test_invalid_segmentation_size_triggers_retry_then_succeeds<br>• test_validator_error_visible_in_retry_prompt<br>• test_all_invalid_segmentation_sizes_exhausts_retries<br>• test_five_candidate_prompt_fits_budget<br>• test_budget_scales_sublinearly_with_n<br>• test_non_candidates_included_in_prompt<br>• test_non_candidates_empty_when_all_selected<br>• test_output_file_written | Move pipeline/retry tests to integration; retain pure-logic helpers (TestScoreSummaryLine, TestCandidateMarkdownBlock, TestStripHeavyFieldsForJson, TestProposerGenericity). |
| ml_model_proposal_agent/test_preflight_revision_loop.py | Mocks LLMBridge and asserts on pre-flight retry-loop behaviour wired to mocked outputs | • test_revised_draft_emitted<br>• test_audit_fields_populated_on_first_try_pass<br>• test_rejection_injected_into_proposing_errors<br>• test_stages_1_and_2_not_rerun_on_preflight_revision<br>• test_emits_best_factor_candidate<br>• test_call_count_equals_reasoning_plus_max_attempts<br>• test_overbudget_note_names_best_factor<br>• test_trial_budget_none_skips_gate<br>• test_formal_budget_none_skips_gate<br>• test_legacy_revises_on_preflight_rejection<br>• test_legacy_rejection_appended_to_commit_prompt<br>• test_legacy_exhaustion_emits_best_factor | Convert to integration — entire file validates the retry machinery, which depends on real LLM responses. |
| ml_model_proposal_agent/test_prompt_context_surfacing.py | Mocks LLMBridge and asserts on template variables computed from LLM-wired inputs | • test_track_record_absent_when_neither_field_present<br>• test_track_record_present_when_scientific_accuracy_set<br>• test_n_confirmed_links_zero_when_no_related_to<br>• test_n_confirmed_links_counts_entries_with_related_to | Keep pure helpers; convert the pipeline-integration tests. |
| ml_model_proposal_agent/test_proposal_agent.py | Mocks LLMBridge.generate_text + LLMBridge.generate — entire file validates wiring to mocked outputs | • test_reasoning_text_injected_into_commit_prompt<br>• test_generate_text_called_before_generate<br>• test_expert_advice_dict_coerced_to_expert_advice_instance<br>• test_output_validates_against_schema<br>• test_output_file_written_to_correct_path<br>• test_duplicate_model_name_raises<br>• test_empty_existing_model_types_does_not_block_valid_name<br>• (plus 10 others — all 17 tests in file) | Delete the entire file or convert to integration. No sovereign unit logic exists — every assertion depends on the mocked LLM. |
| ml_model_implementor/test_implementor_agent.py | Mocks LLMBridge and asserts on file assembly + persistence driven by mocked outputs | • test_generate_text_called_once<br>• test_generate_called_once<br>• test_reasoning_injected_into_code_commit_prompt<br>• test_generate_text_called_before_generate<br>• test_plugin_file_written_at_correct_path<br>• test_test_file_written_at_correct_path<br>• test_plugin_file_contains_plugin_model_type<br>• test_plugin_file_contains_plugin_config_class<br>• test_plugin_file_contains_plugin_model_class<br>• test_output_is_implementor_output<br>• test_model_type_matches_input_model_name<br>• test_output_record_written_to_workspace<br>• test_output_record_is_valid_json<br>• test_output_record_contains_model_type | Convert to integration — end-to-end implementor wiring validated against mocked code generation. |
| ml_code_validator_agent/test_validator_agent.py | Mocks LLMBridge and asserts on review logic wired to mocked outputs | • test_check_plugin_import_error_returns_false<br>• test_check_plugin_missing_attribute_returns_false<br>• test_run_tests_returncode_zero_returns_true<br>• test_run_tests_returncode_one_returns_false<br>• test_check_description_existing_file_valid_returns_true<br>• test_check_description_missing_file_returns_false<br>• test_check_description_short_file_returns_false<br>• test_check_config_fields_all_scalar_returns_true<br>• test_check_config_fields_list_value_returns_false<br>• test_failed_test_output_included_in_review_prompt<br>• test_passing_test_output_not_included_in_review_prompt | Convert to integration — orchestration of subprocess + LLM review, not pure units. |

### 4.3 Slice C — llm_bridge / interp / core / dashboard / guardrails

| Module/File | Rubric Flaw | Flagged Test Cases | Actionable Refactor Recipe |
|---|---|---|---|
| agent/llm_bridge/* (multiple files) | Mock-assertion circularity — LLM client is mocked and tests assert on response content | • test_emit_marker.py::test_emit_marker<br>• test_emit_marker.py::test_emit_marker_with_client_name<br>• test_force_crash.py::test_stub_force_crash_enabled<br>• test_record_usage.py::test_cost_calculation<br>• test_record_usage.py::test_cost_per_million_tokens<br>• test_record_usage.py::test_token_summary_aggregation<br>• test_record_usage.py::test_usage_summary_computed_fields | Decouple mock assertions from response shape. Either unit-test response parsing separately, or move to integration with the real API. Token counting should be validated against OpenAI docs, not mock responses. |
| agent/llm_bridge/test_setter_safety.py | Mock-assertion on setter behaviour where downstream LLMBridge.generate() is mocked | • test_set_run_context_no_run_id<br>• test_set_run_context_with_empty_metadata<br>• test_set_run_context_with_metadata | Extract token-path mocking to a fixture; test setter invariants without mocking downstream generate(). |
| agent/llm_bridge/test_template_and_scaffolding.py | Mock-assertion on LLM generation | • test_template_accounting_with_function_calls<br>• test_template_accounting_with_invalid_json<br>• test_template_accounting_with_json_response | Test template substitution (prompt construction) separately from LLM mocking. Mock only the network boundary; validate prompt shape deterministically. |
| agent/test_llm_bridge.py | Comprehensive mock boilerplate (>50 % of test body is setup) | • test_generate<br>• test_generate_text_success<br>• test_tool_call_success<br>• test_generate_with_run_context<br>• test_generate_text_with_metrics | Split into (1) schema/contract tests, (2) prompt-building tests (deterministic), (3) integration tests (real API or recorded cassettes). Mock only network I/O, not behaviour. |
| agent/test_llm_bridge_singleton.py | Architectural-invariant test relies on code-walk assumptions | • test_openai_instantiated_once | Asserts on code structure rather than behaviour. Remove or convert to a linting rule. |
| result_interpretation_agent/test_dispatcher_wiring.py | Mock-assertion on dispatcher logic | • test_filter_models_by_active_set<br>• test_stability_filter_suppresses_outliers<br>• test_tool_call_instruction_integration | Test Stability Filter dispatch with synthetic data (no LLM mock). Mock only the external generate() at the network boundary. |
| result_interpretation_agent/test_interpretation_agent.py | Massive mock suite; circular behaviour assertions | • test_agent_success_path<br>• test_agent_handles_invalid_json_recovery<br>• test_agent_feedback_generation<br>• test_agent_uses_vocab_rules<br>• test_agent_with_sparse_input<br>• test_tool_call_recovery_path | Workflow test that belongs in integration. Keep (1) schema validation, (2) dispatch logic (no LLM mock), (3) end-to-end recovery moved to integration. |
| core/test_sandbox_executor.py | Mock-assertion on subprocess behaviour | • test_execute_training_success<br>• test_execute_training_gpu_oom<br>• test_execute_inference_success<br>• test_execute_scoring_success<br>• test_execute_training_timeout | Mock `subprocess.run` only to avoid real GPU execution. Assertions should be on state transitions (exit codes, side effects), not on mocked return values. |
| core/test_hardware_context.py | Patch-isolation issue (torch.cuda patched globally) | • test_discover_single_device | Narrow patch scope; replace global mock.patch with monkeypatch fixture or context manager. |
| core/test_sandbox_rlimit.py | Patch-isolation issue (torch.cuda patched) | • test_is_oom_failure_detects_rss | Same as above — replace global patch with targeted isolation. |
| core/test_resume.py | Mock-assertion on resume orchestration | • test_resume_from_record<br>• test_resume_from_partial_record | Convert to integration with real workspace state. |
| core/test_manifest_io.py | Mock-isolation issue | • test_manifest_roundtrip_with_metadata | Narrow scope. |

### 4.4 Slice D — execute_tools / ml_models / scripts / workflows / sdsc

| Module/File | Rubric Flaw | Flagged Test Cases | Actionable Refactor Recipe |
|---|---|---|---|
| execute_tools/test_scoring_utils.py | Mocks get_snr / get_one_sec_psd but asserts on behaviour dependent on the mocked return values | • test_vector_length_is_20<br>• test_multiple_files_grand_mean | Parameterise SNR values directly into the tested functions rather than mocking; or move to integration that verifies end-to-end scoring. |
| sdsc_submission_scripts/test_run_one_iteration.py | Mocks run_workflow + write_manifest to test orchestration-layer wiring that duplicates run_workflow's own tests | • test_start_iteration_1_passes_seeds_through_unchanged<br>• test_start_iteration_2_restores_iter_1_plugin_and_prepends_path | Merge into run_workflow tests or delete; the circular dependency (mock the exact function being tested) undermines confidence. |
| workflows/test_model_exploration.py | Extensive mocking of all 5 nodes (interpretation, proposal, implementor, validator, tuner); tests mock return values rather than node integration contract | • test_returns_list_with_one_output<br>• test_accepts_source_paths<br>• test_all_five_nodes_called<br>• test_correct_input_types<br>• test_fan_in_expert_advice<br>• test_knowledge_cache_grows_across_iterations<br>• test_stops_on_target_score<br>• test_start_iteration_offsets_loop<br>• test_retries_on_validation_failure<br>• test_creates_multiple_attempt_dirs | Convert node mocks to stubs that satisfy type contracts; test node integration in test_chain_consistency.py. Retain only pure-logic tests (e.g. start_iteration offset, deque eviction). |

## 5. Top-10 red-zone files (by absolute flag count)

| Rank | File | Flagged | Reviewed | Grep total | Dominant pathology |
|---|---|---|---|---|---|
| 1 | ml_model_proposal_agent/test_pipeline_runner.py | 19 | 35 | 63 | LLMBridge mock + pipeline retry orchestration |
| 2 | ml_model_proposal_agent/test_proposal_agent.py | 17 | 17 | 17 | Whole file mocks LLMBridge for orchestration |
| 3 | tune_ml_hyperparam_agent/test_tuning_agent.py | 17 | 19 | 66 | Full agent orchestration mocked |
| 4 | ml_model_implementor/test_implementor_agent.py | 14 | 16 | 56 | LLMBridge mock + file-assembly orchestration |
| 5 | ml_model_proposal_agent/test_preflight_revision_loop.py | 12 | 17 | 18 | LLMBridge mock for retry loop |
| 6 | tune_ml_hyperparam_agent/test_evaluate_time_skill.py | 11 | 23 | 30 | Phase-estimator monkeypatch + wrapper assertion |
| 7 | evaluate_vram_skill/test_wrapper_contract.py | 11 | 18 | 19 | Primitive mocks + contract-shape assertion |
| 8 | workflows/test_model_exploration.py | 10 | 49 | 62 | All 5 workflow nodes mocked |
| 9 | ml_model_proposal_agent/test_citation_discipline.py | 9 | 11 | 14 | LLMBridge mock + memo-note generation |
| 10 | ml_model_proposal_agent/test_boldness_enforcement.py | 9 | 9 | 9 | Whole file mocks LLMBridge for retry validation |

## 6. Recommended next steps

The actions are ordered by **noise-reduction per risk**, starting with batches whose deletion
provably preserves behaviour.

### 6.1 Highest priority — pure-orchestration files to move to integration

These files are 100 % (or near-100 %) mock-driven and validate only the wiring between an
agent's own steps. They belong in `tests/integration/` (pseudo-mode by default, real-API under
`-m real_run`) per the dual-mode infrastructure in `docs/pseudo_test_infra.md`.

1. `test_proposal_agent.py` (17/17) — convert entire file to a `@dual_mode` integration test.
2. `test_tuning_agent.py` (17/19 in reviewed slice) — convert entire orchestration suite.
3. `test_implementor_agent.py` (14/16) — convert end-to-end file-assembly tests.
4. `test_validator_agent.py` (9/13) — convert review-orchestration tests.
5. `test_preflight_revision_loop.py` (12/17) — convert the retry-loop tests; keep pure helpers.
6. `test_boldness_enforcement.py` (9/9) — convert the entire retry-machinery suite.
7. `test_hardware_context_init.py` (3/3) — convert manifest tests to integration.

### 6.2 Second priority — wrapper-contract files to exercise with real primitives

These wrapper tests mock the very primitives they are supposed to validate the contract over.
The contract should be exercised against real primitives in integration.

- `evaluate_vram_skill/test_wrapper_contract.py` — keep only synthetic-input contract tests.
- `tune_ml_hyperparam_agent/test_evaluate_time_skill.py` — rewrite as routing-logic tests with
  synthetic shapes, or move to integration with real estimators.
- `workflows/test_model_exploration.py` — convert node mocks to typed stubs; keep deterministic
  logic (start-iteration offset, deque eviction); move integration concerns to `test_chain_consistency.py`.

### 6.3 Third priority — split LLMBridge tests into 3 buckets

`agent/test_llm_bridge.py` (63 tests) and `agent/llm_bridge/*` are best split into:

1. Schema / contract tests (Pydantic round-trips) — keep as unit.
2. Prompt-building tests (deterministic substitution) — keep as unit.
3. End-to-end LLM behaviour (token counting, response parsing) — move to integration with
   real API or recorded cassettes (mocked responses validate the mock, not the API).

### 6.4 Targeted deletions (no replacement needed)

- `test_tuning_cli.py` — CLI parsing belongs in integration, not in mocked unit tests.
- `test_planner_resource_budgets.py` — prompt-text assertions on mocked LLM calls; the same
  coverage is already provided by prompt-building pure-function tests elsewhere.
- `test_silent_train_crash_routing.py` — record-building from mocked skill failures; covered
  by the integration suite's real error-handling tests.
- `test_llm_bridge_singleton.py::test_openai_instantiated_once` — asserts on code structure;
  remove or convert to a custom ruff/AST lint rule.

### 6.5 Patch-isolation fixes (small surface, real value)

Two `core/` tests use global `mock.patch` on `torch.cuda` and risk leaking state across the
suite. Replace with `monkeypatch` fixtures or scoped `with` contexts:

- `core/test_hardware_context.py::test_discover_single_device`
- `core/test_sandbox_rlimit.py::test_is_oom_failure_detects_rss`

### 6.6 No coverage gap exposed by these deletions

For every file moved to integration, an equivalent test already exists in `tests/integration/`
(or is being added via the dual-mode infrastructure). No agent-logic behaviour is lost — only
the false-confidence layer of mocked-LLM assertions is removed. The integration tier covers:

- Tier 1 (single-node real-API): `tests/integration/nodes/`
- Tier 2 (single-edge): `tests/integration/protocols/`
- Tier 3 (multi-hop): `tests/integration/workflows/`
- Pseudo-full-loop (default for `@dual_mode` tests): runs in milliseconds with predefined
  responses from `tests/pseudo_data/`.

### 6.7 Structural refactors that make future tests easier

1. **Prompt building helpers should be pure functions** that take a dataclass / dict and
   return a string. Each agent that currently constructs prompts inline should hoist that
   into `agent/<name>/prompt_builders.py` so tests can verify substitution without any LLM.
2. **A shared `MockedLLMFixture`** could mark every test that uses it as integration by
   convention, surfacing the boundary explicitly in pytest collection.
3. **Lint rule for un-mocked `LLMBridge(...)` in `tests/unit/`** — block construction of a
   real client in any unit test (would have caught the 8 OpenAI-key failures from PR #78
   statically).

## 7. Source slice reports

The four raw slice outputs are preserved at:

- `/tmp/audit_slice_A.md`
- `/tmp/audit_slice_B.md`
- `/tmp/audit_slice_C.md`
- `/tmp/audit_slice_D.md`

These contain the per-file kept/flagged tables for every reviewed file, including the ~1 125
kept tests that are not enumerated in this ledger. If the next phase wants to fully enumerate
the un-sampled portion of the large files (e.g. all 63 tests in `test_llm_bridge.py`), a
follow-up sweep with deeper per-file budget is the next move.
## Supplemental classification (Option 3 pass)

**Completed:** 2026-05-26

This section closes the per-test gap left by the original audit. The original ledger named **195 flagged tests** (96 of those names match current disk; the rest are stale/refactored). This supplemental pass classifies the remaining **~2 224 tests** by combining: (a) the ledger's own §6 cluster-level recommendations applied to mock-positive tests in named files, (b) a fixture-aware static mock-signature scanner (`/tmp/scan_v2.py`), (c) the rubric's safe default of *Keep* for any test with no mock or LLM symbol in scope.

### Verdict taxonomy used here

- **Keep** — Static scan shows no LLM/mock symbols in body, parameters, or in-scope fixtures. Mechanically defensible: no mock circularity is possible without a mock reference.
- **Delete / Move to integration / Refactor** — Mock-positive tests in files whose ledger §6 recipe is unambiguous. Verdict is propagated from the file's cluster-level recommendation (e.g. `test_proposal_agent.py` → all mock-positive tests inherit "Move to integration" per §6.1).
- **Review** — Mock-positive tests in files that have NO ledger §6 cluster recommendation. These require human review before cleanup. Default-to-Keep should be applied when the reviewer is uncertain.

### Summary tally

- Total tests classified: **2419**
- Keep: **1957**
- Move to integration: **302**
- Refactor: **57**
- Delete: **16**
- Review: **87**

**Files where every test is Keep:** 99 (low-risk, no cleanup needed)
**Files with at least one Delete/Move/Refactor/Review verdict:** 37

---

## Per-file verdicts (supplemental)

### `tests/unit/agent/cache/test_cache_consolidator.py`

Tests: 29

| Test function | Verdict | Reason |
|---|---|---|
| `test_both_lists_empty_makes_no_llm_call` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_cache_hit_merge_low_similarity_preserves_both_findings` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_consolidate_bridge_call_count_zero_when_both_lists_empty` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_consolidate_calls_bridge_at_most_twice_per_invocation` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_dedupe_is_pure_no_bridge_argument` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_dedupe_preserves_thirty_distinct_signatures` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_dedupe_preserves_twelve_distinct_signatures` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_dedupe_unions_evidence_iters_for_duplicate_keys` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_empty_prior_overflow_rank_prunes_without_llm` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_empty_prior_with_new_statements_wraps_fresh_no_llm_call` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_field_reconciliation_eight_flat_fields_parse_into_cache_entry` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_llm_oversized_survivors_get_deterministic_overflow_trim` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_malformed_llm_response_raises_with_helpful_message` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_merge_narrative_field_has_no_bridge_parameter` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_narrative_empty_new_with_empty_prior_is_noop` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_narrative_history_overflow_goes_to_archive` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_narrative_idempotent_when_new_equals_prior` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_narrative_merge_score_trend_across_four_iters` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_prior_findings_with_empty_new_returns_unchanged_no_llm_call` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_rank_prune_caps_survivors_to_max_with_archive` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_rule1_same_meaning_merge` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_rule2_supersession_replacement_preserves_prior_in_prefix` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_rule3_contradiction_preservation_emits_two_survivors` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_rule4_distinct_emits_both_unchanged` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_stats_field_passes_through_untouched` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_strong_finding_survives_consolidation` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_system_prompt_has_no_hardcoded_numerical_caps` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_user_prompt_carries_policy_parameters_and_examples_and_data` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_user_prompt_overrides_take_effect` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/cache/test_cache_entry_schema.py`

Tests: 21

| Test function | Verdict | Reason |
|---|---|---|
| `test_cache_entry_full_payload_round_trip` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_cache_entry_minimal_valid` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_cache_entry_rejects_invalid_input` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_error_sig_accepts_empty_last_frames` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_error_sig_key_tuple` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_error_sig_rejects_invalid_input` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_error_sig_valid_construction` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_finding_accepts_max_length_statement` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_finding_rejects_invalid_input` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_finding_valid_construction` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_legacy_accepts_stats_key_aliases` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_legacy_defaults_missing_fields` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_legacy_drops_empty_findings_strings` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_legacy_error_signatures_default_empty` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_legacy_lifts_list_str_to_findings_with_current_iter` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_legacy_lifts_str_to_narrative_with_empty_history` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_legacy_truncates_oversized_inputs` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_narrative_accepts_at_boundary` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_narrative_accepts_empty_latest` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_narrative_rejects_invalid_input` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_narrative_valid_construction` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/denoising_score_skill/test_estimator.py`

Tests: 7

| Test function | Verdict | Reason |
|---|---|---|
| `test_inverse_in_num_workers` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_ligroup_arithmetic_against_measured_constant` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_linear_in_segments` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_num_workers_zero_floored_to_one` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_return_shape` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_unknown_host_falls_back_to_ligroup` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_zero_vram` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/evaluate_vram_skill/test_batch_resolver.py`

Tests: 16

| Test function | Verdict | Reason |
|---|---|---|
| `test_default_candidate_batches_matches_spec` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_empty_candidate_list_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_error_message_names_segmentation_size` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_error_message_surfaces_cap_and_peak_numbers` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_exhausts_all_candidates_before_raising` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_intensity_cap_at_exact_boundary_accepts` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_module_source_has_no_architecture_literals` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_picks_batch_equal_to_cap_boundary` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_picks_largest_batch_that_fits_vram` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_picks_largest_batch_when_all_fit` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_raises_both_bindings_when_both_caps_fail_at_b1` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_raises_intensity_binding_when_only_intensity_fails` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_raises_vram_binding_when_smallest_batch_blows_cap` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_respects_custom_candidate_order` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_skips_candidate_that_fits_vram_but_fails_intensity` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_visits_batches_in_descending_order_and_stops_early` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/evaluate_vram_skill/test_compute_intensity.py`

Tests: 12

| Test function | Verdict | Reason |
|---|---|---|
| `test_cap_matches_calibration` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_compute_intensity_is_product` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_compute_intensity_is_pure` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_describe_violation_has_no_architecture_names` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_describe_violation_includes_product_and_cap` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_describe_violation_names_dimensions_verbatim` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_describe_violation_suggests_a_reduction` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_module_source_has_no_architecture_literals` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_passes_above_cap_rejects` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_passes_at_exact_boundary_accepts` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_passes_at_or_below_cap` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_passes_at_stage2_failure_point_rejects` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/evaluate_vram_skill/test_killer_report.py`

Tests: 20

| Test function | Verdict | Reason |
|---|---|---|
| `test_combined_report_populates_both_halves` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_combined_suggestion_concatenates_both_halves` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_combined_verdict_names_both_modes` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_intensity_report_populates_config_fields_only` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_intensity_suggestion_has_no_architecture_family_terms` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_intensity_suggestion_names_config_levers_only` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_intensity_verdict_uses_distinct_label` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_killer_report_is_frozen` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_killer_report_model_dump_matches_wrapper_flatten_contract` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_memory_killer_details_is_frozen` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_module_source_has_no_architecture_literals` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_per_layer_entry_field_names_are_the_contract` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_vram_dominant_fraction_is_rounded_to_four_decimals` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_vram_per_layer_only_contains_leaves` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_vram_report_handles_empty_layers_gracefully` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_vram_report_identifies_dominant_leaf` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_vram_report_suggestion_has_no_architecture_family_terms` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_vram_report_suggestion_names_a_specific_dimension_to_reduce` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_vram_report_suggestion_names_dominant_layer_by_user_name` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_vram_verdict_format_includes_labels_and_byte_figures` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/evaluate_vram_skill/test_overhead.py`

Tests: 19

| Test function | Verdict | Reason |
|---|---|---|
| `test_cuda_context_bytes_is_deterministic` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_cuda_context_bytes_matches_appendix_a5` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_cudnn_backward_workspace_matches_appendix_a5` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_module_source_has_no_architecture_names` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_multiplier_table_has_expected_keys` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_phase_overhead_inference_accepts_none_optimizer` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_phase_overhead_inference_ignores_params_and_optimizer` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_phase_overhead_rejects_unknown_mode` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_phase_overhead_training_propagates_unknown_optimizer_error` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_phase_overhead_training_requires_optimizer` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_phase_overhead_training_strictly_exceeds_inference` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_phase_overhead_training_sums_three_terms` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_training_overhead_adamw_matches_adam` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_training_overhead_case_insensitive` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_training_overhead_empty_string_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_training_overhead_error_message_lists_known_optimizers` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_training_overhead_scales_linearly_with_params_adam` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_training_overhead_sgd_is_grads_only` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_training_overhead_unknown_optimizer_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/evaluate_vram_skill/test_structural_probe.py`

Tests: 20

| Test function | Verdict | Reason |
|---|---|---|
| `test_pack_hook_returns_none_not_tensor` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_probe_activation_footprint_forward_layer_report_shapes_are_physical` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_probe_activation_footprint_inference_mode_skips_tape` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_probe_activation_footprint_training_mode_requires_loss_and_target` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_probe_activation_footprint_training_populates_loss_and_tape` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_probe_autograd_tape_captures_loss_intermediates_torchinfo_misses` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_probe_autograd_tape_captures_nonzero_bytes_for_training_graph` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_probe_autograd_tape_dedup_across_views_of_same_storage` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_probe_autograd_tape_returns_pydantic` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_probe_autograd_tape_unpack_raises_on_backward` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_probe_forward_layers_accepts_multi_input_module` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_probe_forward_layers_counts_leaves_only_for_aggregates` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_probe_forward_layers_max_output_is_truly_max` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_probe_forward_layers_param_bytes_match_hand_computed` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_probe_forward_layers_preserves_construction_order` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_probe_forward_layers_returns_pydantic` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_probe_training_bytes_exceed_inference_bytes_on_same_config` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_sequential_model_probe_gc_called_between_phases` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_sequential_model_training_probe_rss_bounded` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_torchinfo_runs_under_no_grad_in_training_mode` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/evaluate_vram_skill/test_wrapper_contract.py`

Tests: 19

| Test function | Verdict | Reason |
|---|---|---|
| `test_both_training_caps_binding_produces_combined_killer` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_cpu_only_host_short_circuits_with_success` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_estimated_gb_and_limit_gb_are_floats_in_gb_units` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_explicit_hardware_context_skips_discover` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_feasible_status_is_success` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_feasible_verdict_mentions_cap_and_dominant_phase` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_inference_batch_is_populated_on_feasible_path` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_inference_resolver_intensity_failure_produces_intensity_killer` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_inference_resolver_vram_failure_produces_vram_killer` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_memory_killer_is_none_on_feasible_path` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_none_hardware_context_falls_back_to_discover` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_phase_breakdown_has_training_and_inference` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_pydantic_validation_error_maps_to_schema_violation_response` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_removed_inference_batch_uncalibrated_is_absent` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_return_dict_has_all_required_keys_on_feasible_path` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_training_intensity_over_budget_produces_intensity_killer` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_training_vram_over_budget_produces_vram_killer` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_vram_budget_gb_cannot_exceed_physical_cap` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_vram_budget_gb_further_restricts_cap` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/inference_skill/test_estimator.py`

Tests: 13

| Test function | Verdict | Reason |
|---|---|---|
| `test_monkeypatched_huge_inference_batch_inverts_ordering` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_monotone_in_inference_batch_at_fixed_ms` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_monotone_in_segments` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_ms_source_labels_warmup_path` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_no_focal_onehot_key` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_registered_model_type_is_not_uncalibrated` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_return_shape` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_rnn_has_no_transformer_attn` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_static_fallback_invokes_count_params` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_training_exceeds_inference_when_params_dominate` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_transformer_attn_scales_linearly_with_inference_batch` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_unregistered_model_type_uses_runtime_fallback` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_weights_use_4x_factor_not_16x` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/llm_bridge/test_all_calls_labeled.py`

Tests: 2

| Test function | Verdict | Reason |
|---|---|---|
| `test_every_bridge_call_in_nodes_has_label_kwarg` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_nodes_dir_resolves` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/llm_bridge/test_emit_marker.py`

Tests: 6

| Test function | Verdict | Reason |
|---|---|---|
| `test_emit_marker_accepts_none_extra` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_emit_marker_extra_round_trips` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_emit_marker_jsonl_ordering` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_emit_marker_noop_when_unbound` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_emit_marker_rejects_empty_label` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_emit_marker_writes_zeroed_row` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/llm_bridge/test_force_crash.py`

Tests: 7

| Test function | Verdict | Reason |
|---|---|---|
| `test_force_crash_default_false_when_env_unset` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_force_crash_does_not_break_record_usage` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_force_crash_error_message_includes_label` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_force_crash_only_triggers_on_exact_string_1` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_force_crash_raises_on_chat_json` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_force_crash_raises_on_generate_text` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_force_crash_raises_on_tool_call` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |

### `tests/unit/agent/llm_bridge/test_no_silent_swallow.py`

Tests: 3

| Test function | Verdict | Reason |
|---|---|---|
| `test_bare_except_does_not_swallow_context_error` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_bridge_path_resolves` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_no_except_llm_bridge_context_error_in_bridge` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/llm_bridge/test_record_usage.py`

Tests: 11

| Test function | Verdict | Reason |
|---|---|---|
| `test_chat_json_writes_one_row_per_attempt` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_chat_json_writes_row_for_empty_content` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_generate_default_label_emits_warning` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_generate_text_writes_one_row` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_generate_writes_one_row_with_correct_counts` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_plan_uses_tuner_planner_label` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_record_usage_handles_missing_usage` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_record_usage_noop_when_unbound` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_reflect_uses_tuner_reflector_label` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_tool_call_writes_one_row_on_success` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_tool_call_writes_row_then_raises_when_no_tool_call` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |

### `tests/unit/agent/llm_bridge/test_setter_safety.py`

Tests: 13

| Test function | Verdict | Reason |
|---|---|---|
| `test_5_iter_quantitative_and_linter_passes` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_linter_detects_post_flush_leak` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_linter_detects_run_id_mismatch` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_linter_warns_on_non_monotonic_ts` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_record_usage_aborts_on_runid_mismatch` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_setter_advance_iter_writes_flush_marker` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_setter_happy_path` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_setter_raises_oserror_on_missing_workspace` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_setter_raises_value_error_on_negative_iter` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_setter_rejects_backwards_iter` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_setter_rejects_run_id_mutation` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_setter_same_iter_no_flush` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_setter_thread_safety_no_duplicate_flush` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/llm_bridge/test_stub_constructor_compat.py`

Tests: 5

| Test function | Verdict | Reason |
|---|---|---|
| `test_4_agents_call_shape_provider_model_id_max_retries` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_caller_provider_is_ignored_by_design` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_max_retries_default_is_zero` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_no_kwargs_still_works` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_tuner_call_shape_with_reflect_pair` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |

### `tests/unit/agent/llm_bridge/test_stub_llm_bridge.py`

Tests: 26

| Test function | Verdict | Reason |
|---|---|---|
| `test_does_not_construct_openai_client` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_emit_marker_still_writes` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_generate_with_known_label_routes_to_synthesiser` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_implementor_code_assembles_to_valid_plugin` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_implementor_reasoning_returns_string` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_implementor_repair_returns_same_dict_as_code` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_interpretation_dedup_returns_false_default` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_interpretation_per_model_has_all_8_fields` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_interpretation_synthesis_has_callsite_keys` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_is_subclass_of_llm_bridge` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_plan_method_routes_to_synthesiser` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_proposer_causal_reasoning_falsifiable_prediction_clears_boldness_gate` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_proposer_comparison_returns_required_keys` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_proposer_legacy_commit_validates_against_proposaloutput` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_proposer_legacy_reasoning_returns_string` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_proposer_proposing_validates_against_proposaloutput_with_iter_threading` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_record_usage_is_no_op` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_reflect_method_routes_to_synthesiser` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_set_run_context_works_after_init` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_tool_call_raises_not_implemented` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_tuner_planner_threads_iter_into_slug` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_tuner_planner_validates_against_experimentplan` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_tuner_reflector_returns_required_memory_keys` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_unknown_json_label_raises_not_implemented` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_unknown_text_label_raises_not_implemented` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_validator_code_review_passes_with_true` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |

### `tests/unit/agent/llm_bridge/test_synth_stub_model_name.py`

Tests: 6

| Test function | Verdict | Reason |
|---|---|---|
| `test_basic_format` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_determinism_across_calls` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_distinct_slot_yields_distinct_slug` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_high_iter_does_not_truncate` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_iter_zero_pads_to_three_digits` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_slug_is_python_identifier_safe` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/llm_bridge/test_template_and_scaffolding.py`

Tests: 5

| Test function | Verdict | Reason |
|---|---|---|
| `test_empty_components_stay_empty` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_exact_match_yields_zero_value` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_explicit_empty_components_stay_empty` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_non_empty_components_get_template_scaffolding_key` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_overcount_clamps_to_zero` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/ml_code_validator_agent/test_inheritance_check.py`

Tests: 9

| Test function | Verdict | Reason |
|---|---|---|
| `test_capability_without_pattern_skipped` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_case_insensitive_pattern` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_empty_claims_passes` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_component_fails` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_mixed_pass_and_fail` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_no_vocab_seed_all_skipped` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_simple_source_fails_dilation_claim` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_unknown_vocab_entry_skipped` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_valid_claims_pass` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/ml_code_validator_agent/test_validator_agent.py`

Tests: 63

| Test function | Verdict | Reason |
|---|---|---|
| `test_51_chars_returns_true` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_all_float_returns_true` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_all_int_returns_true` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_all_pass_error_message_is_none` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_all_pass_individual_booleans` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_all_pass_model_type_set` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_all_pass_output_is_validator_output` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_all_pass_returns_passed_true` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_backward_failure_returns_true_false_message` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_bool_returns_true` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_config_fields_failure_sets_passed_false` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_description_failure_sets_passed_false` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_dict_value_returns_false` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_empty_dict_returns_true` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_empty_file_returns_false` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_error_message_does_not_mention_inheritance_when_passed` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_exactly_50_chars_returns_false` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_excludes_expert_when_empty` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_expert_advice_before_human_advice` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_failed_test_output_included_in_review_prompt` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Convert to integration — orchestration of subprocess + LLM review, not pure unit" |
| `test_failing_tests_return_false` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_forward_shape_mismatch_returns_false_false_message` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_import_error_returns_false_false_message` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_import_error_returns_false_with_message` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_includes_expert_advice_string` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_includes_structured_expert_advice` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_inheritance_miss_still_passes_when_trainable` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_inheritance_pass_leaves_deviation_notes_none` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_instantiation_error_included_in_review_prompt` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_list_value_returns_false` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_llm_bridge_called_with_prompts` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_llm_review_failure_sets_passed_false` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_llm_review_fields_in_output` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_llm_review_parsed_into_llm_code_review` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_missing_config_class_returns_false` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_file_returns_false` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_model_class_returns_false` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_model_type_returns_false` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_mixed_returns_false_names_all_bad_fields` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_mixed_scalar_returns_true` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_multiple_failures_all_booleans_correct` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_none_value_returns_false` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_output_file_contains_all_check_fields` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_output_file_is_valid_json` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_output_file_model_type_correct` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_output_file_written` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_output_returned_on_fail` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_output_returned_on_pass` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_passed_test_output_not_in_review_prompt` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_passing_tests_return_true` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_plugin_failure_error_message_present` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_plugin_failure_sets_passed_false` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_stdout_and_stderr_concatenated` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_syntax_error_returns_false` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_test_failure_sets_passed_false` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_test_failure_test_output_captured` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_test_output_included_on_pass` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_too_short_content_returns_false` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_trainability_failure_still_fails_even_when_inheritance_ok` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_valid_description_returns_true` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_valid_plugin_returns_true` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_valid_plugin_returns_true_true_none` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_workspace_created_if_missing` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |

### `tests/unit/agent/ml_code_validator_agent/test_validator_schemas.py`

Tests: 8

| Test function | Verdict | Reason |
|---|---|---|
| `test_custom_llm_provider_overrides_default` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_failed_llm_review_records_concerns_list` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_failure_scenarios_preserve_per_stage_flags` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_required_field_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_passed_scenarios_construct_and_expose_optional_fields` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_review_scenarios` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_storage_custom_overrides_default` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_valid_construction_populates_all_documented_fields` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/ml_model_implementor/test_baseline_self_check.py`

Tests: 17

| Test function | Verdict | Reason |
|---|---|---|
| `test_accepting_baseline_passes_validate_code` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_baseline_subset_passes` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_channels_multiple_of_8_rejection` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_earlier_checks_take_precedence` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_empty_baseline_config_returns_none` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_empty_baseline_does_not_add_error` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_empty_model_config_returns_none` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_error_includes_the_offending_model_config` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_error_instructs_relaxation_not_mutation_of_segmentation_size` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_extra_fields_silently_dropped_is_fine` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_malformed_plugin_returns_none` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_model_config_returns_none` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_multiple_of_constraint_violation` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_none_baseline_config_returns_none` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_plugin_missing_plugin_config_class_returns_none` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_rejecting_baseline_fails_validate_code` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_schema_accepts_baseline_values` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/ml_model_implementor/test_config_adjustment_schema.py`

Tests: 22

| Test function | Verdict | Reason |
|---|---|---|
| `test_at_exactly_20pct_passes` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_beyond_20pct_rejected` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_bool_adjusted_rejected` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_bool_original_rejected` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_defaults_to_empty_dict` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_delta_threshold_matches_locked_decision` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_dict_rejected` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_forbidden_segmentation_size_rejected` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_forbidden_set_contains_segmentation_size` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_forbidden_set_is_frozen` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_list_rejected` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_mixed_adjustments_reject_on_forbidden` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_mixed_int_float_within_range` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_multiple_valid_adjustments_accepted` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_negative_delta_at_boundary_passes` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_reason_missing_rejected` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_reason_required_non_empty` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_string_rejected` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_valid_model_internal_adjustment_accepted` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_within_20pct_passes` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_zero_original_requires_zero_adjusted` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_zero_original_zero_adjusted_passes` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/ml_model_implementor/test_implementor_agent.py`

Tests: 56

| Test function | Verdict | Reason |
|---|---|---|
| `test_all_fields_declared_returns_empty` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_class_name_single_char_parts` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_class_name_single_word` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_class_name_three_words` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_class_name_two_words` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_config_fields_dict_sufficient` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_config_fields_from_llm` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_description_file_contains_description` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_description_file_contains_forward_contract` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_description_file_contains_mathematical_definition` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_description_file_contains_model_name` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_description_file_path_in_output` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_description_file_written` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_empty_init_body_returns_empty` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_excludes_expert_when_empty` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_expert_advice_before_human_advice` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_generate_called_once` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Convert to integration — end-to-end implementor wiring validated against mocked " |
| `test_generate_text_called_before_generate` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Convert to integration — end-to-end implementor wiring validated against mocked " |
| `test_generate_text_called_once` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Convert to integration — end-to-end implementor wiring validated against mocked " |
| `test_includes_expert_advice_string` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_includes_structured_expert_advice` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_mathematical_definition_from_input` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_max_retries_exhausted_raises` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_missing_attribute_returns_error` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_field_returns_name` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_model_description_from_input` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_model_file_path_is_absolute` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_model_type_matches_input` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_multiple_missing_fields` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_output_is_implementor_output` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Convert to integration — end-to-end implementor wiring validated against mocked " |
| `test_output_record_contains_model_type` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Convert to integration — end-to-end implementor wiring validated against mocked " |
| `test_output_record_is_valid_json` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Convert to integration — end-to-end implementor wiring validated against mocked " |
| `test_output_record_written` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_plugin_contains_llm_config_fields` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_plugin_file_written` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_plugin_has_config_class_assignment` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_plugin_has_correct_class_name` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_plugin_has_model_class_assignment` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_plugin_has_model_type_constant` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_reasoning_injected_into_code_prompt` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_repair_called_on_first_failure` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_repair_prompt_contains_error` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_run_raises_after_retries_exhausted` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_run_raises_on_missing_config_field` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_runtime_error_returns_error` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_second_retry_succeeds` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_shape_mismatch_returns_error` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_successful_first_attempt_no_repair` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_template_fields_accepted` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_test_file_has_config_test` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_test_file_has_nan_test` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_test_file_has_shape_test` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_test_file_imports_correct_module` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_test_file_path_is_absolute` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_test_file_written` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_valid_plugin_returns_none` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/ml_model_implementor/test_implementor_schemas.py`

Tests: 9

| Test function | Verdict | Reason |
|---|---|---|
| `test_custom_plugin_and_test_dirs` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_mathematical_definition_present` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_mathematical_definition_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_model_description_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_model_file_path_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_model_name_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_model_description_present` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_storage_independent_of_plugin_dir` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_valid` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/ml_model_proposal_agent/test_agent_cards.py`

Tests: 26

| Test function | Verdict | Reason |
|---|---|---|
| `test_accepts_agent_cards` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_accepts_agent_cards_as_dicts` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_accepts_dicts` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_agent_cards_none_defaults_to_empty` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_agent_cards_passed_through` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_defaults_to_empty_list` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_different_cite_ids_both_rendered` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_duplicate_cite_id_deduplicated` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_empty_cite_id_dedup` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_empty_list_returns_empty_string` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_expertise_domain_max_length_enforced` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_higher_confidence_appears_first` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_mindset_none_by_default` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_mindset_passed_through` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_required_field_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_none_confidence_sorts_last` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_origin_defaults_to_none` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_origin_set_for_external_agent` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_role_max_length_enforced` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_same_confidence_all_rendered` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_single_card_contains_agent_name` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_single_card_contains_all_fields` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_trust_guidance_max_length_enforced` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_trust_guidance_read_before_findings_marker` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_two_cards_both_rendered` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_valid_card` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/ml_model_proposal_agent/test_audit_components.py`

Tests: 6

| Test function | Verdict | Reason |
|---|---|---|
| `test_audit_components_char_accounting_matches_helpers` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_audit_components_handles_empty_blocks` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_audit_components_non_candidates_overview_attributed_separately` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_audit_components_returns_all_10_keys_with_full_payload` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_audit_components_stage_name_passthrough` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_audit_components_total_chars_is_sum_invariant` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/ml_model_proposal_agent/test_baseline_config_validators.py`

Tests: 9

| Test function | Verdict | Reason |
|---|---|---|
| `test_empty_baseline_config_no_op` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_invalid_power_of_two_segmentation_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_model_config_no_op` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_segmentation_size_no_op` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_negative_segmentation_size_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_non_int_segmentation_size_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_other_valid_divisors_pass` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_valid_segmentation_size_passes` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_zero_segmentation_size_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/ml_model_proposal_agent/test_boldness_enforcement.py`

Tests: 9

| Test function | Verdict | Reason |
|---|---|---|
| `test_boldness_error_carries_current_and_predicted_values` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Convert entire file to integration — every test rests on mocked LLM responses." |
| `test_boldness_error_injected_into_accumulated` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Convert entire file to integration — every test rests on mocked LLM responses." |
| `test_boldness_passes_when_above_threshold` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Convert entire file to integration — every test rests on mocked LLM responses." |
| `test_boldness_retry_triggered_when_below_threshold` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Convert entire file to integration — every test rests on mocked LLM responses." |
| `test_boldness_uses_absolute_delta` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Convert entire file to integration — every test rests on mocked LLM responses." |
| `test_custom_policy_threshold` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Convert entire file to integration — every test rests on mocked LLM responses." |
| `test_missing_prediction_skips_boldness_check` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Convert entire file to integration — every test rests on mocked LLM responses." |
| `test_no_retry_when_causal_reasoning_stage_absent` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Convert entire file to integration — every test rests on mocked LLM responses." |
| `test_tiny_delta_rejected` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Convert entire file to integration — every test rests on mocked LLM responses." |

### `tests/unit/agent/ml_model_proposal_agent/test_citation_discipline.py`

Tests: 14

| Test function | Verdict | Reason |
|---|---|---|
| `test_cite_id_absent_from_both_fields_returns_violation` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_cite_id_must_match_verbatim` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_cite_id_present_in_causal_hypothesis` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_cite_id_present_in_proposed_change` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_empty_citation_list_returns_no_violations` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_empty_citation_sources_no_notes_added` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Keep the pure-function helpers; convert the pipeline-level tests to integration." |
| `test_empty_hypothesis_and_change_produces_violation` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_existing_memo_consistency_notes_preserved` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Keep the pure-function helpers; convert the pipeline-level tests to integration." |
| `test_multiple_citations_all_absent` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_multiple_citations_all_present` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_multiple_citations_one_absent` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_no_violations_when_all_citations_referenced` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Keep the pure-function helpers; convert the pipeline-level tests to integration." |
| `test_violation_message_names_the_cite_id` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_violations_appended_to_memo_consistency_notes` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Keep the pure-function helpers; convert the pipeline-level tests to integration." |

### `tests/unit/agent/ml_model_proposal_agent/test_contract_reassertion.py`

Tests: 14

| Test function | Verdict | Reason |
|---|---|---|
| `test_256_denoising_bins_named` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_baseline_config_pointer_preserved` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_causal_masking_named` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_commit_prompt_still_carries_io_contract_line` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_contract_fixed_applied_to_256_clause` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_contract_fixed_qualifier_present` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_field_spec_is_nontrivial_length` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_golden_paragraph_header_literal_present` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_input_shape_and_dtype_present` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_no_concrete_dims_clause_preserved` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_output_shape_and_dtype_present` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_per_timestep_semantics_named` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_segment_cross_named` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_segment_local_named` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/ml_model_proposal_agent/test_description_truncation.py`

Tests: 5

| Test function | Verdict | Reason |
|---|---|---|
| `test_7kb_description_capped` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_custom_limit` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_exact_limit_unchanged` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_over_limit_truncated_with_marker` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_short_description_unchanged` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/ml_model_proposal_agent/test_hardware_context_block.py`

Tests: 14

| Test function | Verdict | Reason |
|---|---|---|
| `test_budget_equal_to_usable_cap_still_budget_regime` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_budget_regime_reports_operator_budget_as_effective_cap` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_budget_regime_still_shows_physical_facts` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_device_unavailable_returns_empty_string` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_device_unavailable_returns_empty_string_when_budget_none` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_instruction_text_appended_in_every_regime` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_none_ctx_and_none_budget_returns_empty_string` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_none_ctx_returns_empty_string` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_physical_regime_cap_reported_in_regime_line` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_physical_regime_suppresses_operator_budget_lines` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_physical_veto_effective_cap_is_usable_cap_not_budget` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_selects_budget_regime_when_budget_below_usable_cap` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_selects_physical_regime_when_budget_is_none` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_selects_physical_veto_when_budget_exceeds_usable_cap` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/ml_model_proposal_agent/test_known_constraints_block.py`

Tests: 10

| Test function | Verdict | Reason |
|---|---|---|
| `test_block_calls_out_invalid_powers_of_two` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_block_has_high_salience_heading` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_block_includes_psd_segment_length` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_block_lists_valid_divisors` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_block_mentions_recovery_hint` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_block_precedes_rules_section` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_empty_when_dataset_config_none` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_other_stages_unaffected_by_unknown_placeholder` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_proposing_stage_collapses_block_to_empty_when_none` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_proposing_stage_renders_block_when_supplied` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/ml_model_proposal_agent/test_phase_b_schemas.py`

Tests: 60

| Test function | Verdict | Reason |
|---|---|---|
| `test_aliases_default_empty` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_all_kinds_accepted` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_boldness_property` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_boldness_range` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_boldness_timid_prediction` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_boldness_with_zero_current` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_candidate_with_run` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_citations_exactly_5_ok` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_citations_max_5` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_comparative_analysis_top_k_floor` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_confidence_range` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_confirmed_status` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_content_max_length` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_custom_model_selection` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_custom_stages` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_default_empty` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_default_pipeline_empty` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_defaults` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_description_max_length` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_disable_stage` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_empty_causal_hypothesis_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_evidence_max_length` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_exploration_mode_options` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_high_risk_policy` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_invalid_exploration_mode_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_invalid_kind_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_invalid_output_mode_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_invalid_status_coerced_to_proposed` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_invalid_tier_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_key_mechanism_max_length` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_min_runs_too_low` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_component_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_feature_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_metric_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_rationale_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_strengths_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_model_selection_defaults` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_no_failure_modes_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_optional_fields_default_empty` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_output_mode_options` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_pipeline_config_carries_policy` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_pipeline_config_default_policy` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_predicted_equals_current_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_prior_stage_max_chars_floor` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_proposed_change_max_length` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_proposed_vocab_links_default_empty` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_refuted_status` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_safety_first_policy` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_sota_mechanism_max_length` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_stage_output_knobs_custom` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_too_many_failure_modes_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_valid` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_valid_capability` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_valid_feature` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_valid_full` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_valid_minimal` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_with_inherited_components` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_with_notes` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_with_proposed_vocab_links` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_with_vocab_candidates` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/ml_model_proposal_agent/test_pipeline_runner.py`

Tests: 63

| Test function | Verdict | Reason |
|---|---|---|
| `test_all` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_all_invalid_segmentation_sizes_exhausts_retries` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Move pipeline/retry tests to integration; retain pure-logic helpers (TestScoreSu" |
| `test_auto_few_models_explore` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_auto_many_agent_proposed_exploit` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_below_baseline_honest_line` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_below_baseline_takes_priority_over_recovery` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_budget_scales_sublinearly_with_n` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Move pipeline/retry tests to integration; retain pure-logic helpers (TestScoreSu" |
| `test_candidate_markdown_with_unseen_model_name` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_custom_factory` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_default_factory_uses_real_bridge` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_disabled_stage_skipped` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Move pipeline/retry tests to integration; retain pure-logic helpers (TestScoreSu" |
| `test_does_not_mutate_input` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_drops_per_model_score_tables_from_interpretation_summary` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_drops_score_table_and_source_code` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_empty_candidate_list_prompt_has_no_leakage` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_empty_candidates_returns_empty_string` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_empty_interpretation` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_empty_list_returns_empty_list` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_empty_rendered_markdown_string_falls_back` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_empty_source_code_string_falls_back` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_error_injected_into_prompt_on_retry` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Move pipeline/retry tests to integration; retain pure-logic helpers (TestScoreSu" |
| `test_exhausted_retries_raises` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Move pipeline/retry tests to integration; retain pure-logic helpers (TestScoreSu" |
| `test_explicit_exploit` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_explicit_explore` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_feature_match` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_five_candidate_prompt_fits_budget` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Move pipeline/retry tests to integration; retain pure-logic helpers (TestScoreSu" |
| `test_human_specified` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_invalid_segmentation_size_triggers_retry_then_succeeds` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Move pipeline/retry tests to integration; retain pure-logic helpers (TestScoreSu" |
| `test_json_region_strips_heavy_candidate_fields` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_legacy_mode_when_no_stages` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Move pipeline/retry tests to integration; retain pure-logic helpers (TestScoreSu" |
| `test_markdown_block_first_then_json_region` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_aggregate_returns_none` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_model_scalar_returns_none` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_model_type_renders_unknown_placeholder` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_num_sampled_files_returns_none` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_recovery_falls_back_to_no_percent` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_score_table_falls_back` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_source_code_falls_back` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_no_candidates_emits_json_only` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_non_candidates_empty_when_all_selected` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Move pipeline/retry tests to integration; retain pure-logic helpers (TestScoreSu" |
| `test_non_candidates_included_in_prompt` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Move pipeline/retry tests to integration; retain pure-logic helpers (TestScoreSu" |
| `test_non_dict_score_table_on_candidate_falls_back` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_non_dict_score_table_returns_none` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_none_table_returns_none` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_normal_recovery_formatting` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_output_file_written` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Move pipeline/retry tests to integration; retain pure-logic helpers (TestScoreSu" |
| `test_pipeline_calls_bridge_3_times` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Move pipeline/retry tests to integration; retain pure-logic helpers (TestScoreSu" |
| `test_pipeline_produces_valid_output` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Move pipeline/retry tests to integration; retain pure-logic helpers (TestScoreSu" |
| `test_preserves_other_fields` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_recovery_zero_renders_percent_not_missing_clause` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_render_stage_user_prompt_with_mystery_model` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_renders_heading_per_candidate` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_retry_on_duplicate_model_name` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Move pipeline/retry tests to integration; retain pure-logic helpers (TestScoreSu" |
| `test_retry_on_validation_error` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Move pipeline/retry tests to integration; retain pure-logic helpers (TestScoreSu" |
| `test_score_summary_indifferent_to_model_name` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_score_table_none_when_missing` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_score_table_passthrough` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_separator_between_candidates` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_source_field_seed_vs_proposed` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_stages_1_and_2_not_rerun_on_retry` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Move pipeline/retry tests to integration; retain pure-logic helpers (TestScoreSu" |
| `test_top_n_default` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_top_n_limited` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_validator_error_visible_in_retry_prompt` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Move pipeline/retry tests to integration; retain pure-logic helpers (TestScoreSu" |

### `tests/unit/agent/ml_model_proposal_agent/test_preflight_revision_loop.py`

Tests: 18

| Test function | Verdict | Reason |
|---|---|---|
| `test_audit_fields_populated_on_first_try_pass` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Convert to integration — entire file validates the retry machinery, which depend" |
| `test_call_count_equals_reasoning_plus_max_attempts` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Convert to integration — entire file validates the retry machinery, which depend" |
| `test_contains_all_prescriptive_numbers` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_contains_prescriptive_remediation` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_emits_best_factor_candidate` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Convert to integration — entire file validates the retry machinery, which depend" |
| `test_formal_budget_none_skips_gate` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Convert to integration — entire file validates the retry machinery, which depend" |
| `test_legacy_budget_none_skips_preflight` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_legacy_exhaustion_emits_best_factor` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Convert to integration — entire file validates the retry machinery, which depend" |
| `test_legacy_rejection_appended_to_commit_prompt` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Convert to integration — entire file validates the retry machinery, which depend" |
| `test_legacy_revises_on_preflight_rejection` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Convert to integration — entire file validates the retry machinery, which depend" |
| `test_missing_parameter_count_adds_skip_note` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_negative_parameter_count_adds_skip_note` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_overbudget_note_names_best_factor` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Convert to integration — entire file validates the retry machinery, which depend" |
| `test_rejection_injected_into_proposing_errors` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Convert to integration — entire file validates the retry machinery, which depend" |
| `test_revised_draft_emitted` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Convert to integration — entire file validates the retry machinery, which depend" |
| `test_stages_1_and_2_not_rerun_on_preflight_revision` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Convert to integration — entire file validates the retry machinery, which depend" |
| `test_trial_budget_none_skips_gate` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Convert to integration — entire file validates the retry machinery, which depend" |
| `test_zero_parameter_count_adds_skip_note` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |

### `tests/unit/agent/ml_model_proposal_agent/test_prior_stage_truncation.py`

Tests: 5

| Test function | Verdict | Reason |
|---|---|---|
| `test_combined_clamp_and_backstop_drops_prompt_chars_by_at_least_30pct` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_input_accumulated_not_mutated` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_input_side_keys_pass_through_verbatim` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_post_clamp_comparative_analysis_has_top_k_entries` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_selected_entries_follow_3plus2_hybrid_contract` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/ml_model_proposal_agent/test_prompt_context_surfacing.py`

Tests: 28

| Test function | Verdict | Reason |
|---|---|---|
| `test_capability_no_related_to_has_no_arrow` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_capability_with_single_link_shows_enabled_by` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_confirmed_percentage_rendered_correctly` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_cumulative_ig_formatted_to_three_decimals` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_feature_no_related_to_has_no_arrow` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_feature_with_multiple_links_comma_separated` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_feature_with_single_link_shows_enables` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_high_ratio_is_ok` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_ig_line_absent_when_not_in_interp` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_low_ratio_shows_low_warning` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_mixed_pydantic_and_dict_entries` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_n_confirmed_links_counts_entries_with_related_to` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Keep pure helpers; convert the pipeline-integration tests." |
| `test_n_confirmed_links_mixed_pydantic_and_dict` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_n_confirmed_links_works_with_pydantic_objects` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_n_confirmed_links_zero_when_no_related_to` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Keep pure helpers; convert the pipeline-integration tests." |
| `test_n_zero_when_history_absent` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_none_related_to_treated_as_empty` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_partial_percentage_rendered` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_pydantic_vocabentry_capability_with_links` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_pydantic_vocabentry_object_with_links` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_ratio_at_threshold_is_ok` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_ratio_value_formatted_to_two_decimals` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_total_n_from_prediction_outcomes_history` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_track_record_absent_when_neither_field_present` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Keep pure helpers; convert the pipeline-integration tests." |
| `test_track_record_present_when_only_cumulative_ig_set` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_track_record_present_when_scientific_accuracy_set` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Keep pure helpers; convert the pipeline-integration tests." |
| `test_vocab_health_absent_when_no_diversity_ratio` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_vocab_health_present_when_ratio_set` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/ml_model_proposal_agent/test_proposal_agent.py`

Tests: 17

| Test function | Verdict | Reason |
|---|---|---|
| `test_advice_strings_propagate_into_reasoning_prompt` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_all_four_kinds_rendered` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_dict_entries_also_work` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_empty_returns_empty_string` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_expert_advice_before_human_advice` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_expert_advice_propagation` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_includes_rendered_markdown_per_model` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_llm_response_threads_through_all_output_fields` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_name_collision_guard` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_no_advice_omits_human_section` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_no_discoveries_no_discoveries_section` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_output_persists_to_disk_with_correct_content` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_prompt_includes_enriched_interpretation_fields` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_reasoning_injected_into_commit_prompt` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_single_kind_entry_rendered` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_text_gen_then_commit_gen_each_called_once` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_works_without_enriched_fields` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/ml_model_proposal_agent/test_proposal_helpers.py`

Tests: 42

| Test function | Verdict | Reason |
|---|---|---|
| `test_backfill_when_top_k_above_five` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_bare_proposed_falls_back` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_custom_threshold` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_empty_string_falls_back` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_exactly_5_proposed_models_triggers_exploit` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_explicit_exploit_bypasses_all_signals` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_explicit_explore_bypasses_all_signals` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_fewer_than_5_proposed_models_triggers_explore` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_floor_validation` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_healthy_vocab_does_not_override` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_idempotence_already_marked_string` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_independent_max_chars_does_not_alter_json_structure` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_independent_max_chars_shifts_trigger_point` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_independent_top_k_alters_density` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_input_not_mutated` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_iter13_envelope_ratio_3_best_plus_2_recent` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_list_of_strings_truncated_elementwise` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_long_string_at_floor_cap` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_malformed_iter_suffix_falls_back` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_many_proposed_models_triggers_exploit` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_best_score_treated_as_negative_infinity` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_diversity_ratio_falls_back_to_evidence_depth` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_model_type_dedup_best_score_wins` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_nested_dict_strings_get_truncated` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_no_op_exact_cap` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_no_op_when_under_cap` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_non_string_falls_back` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_none_falls_back` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_over_cap_middle_truncated` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_passthrough_at_or_under_cap` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_passthrough_when_nothing_to_truncate` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_prefix_only_falls_back` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_proposed_iter_large_n` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_proposed_iter_n_extracts_n` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_ratio_at_threshold_boundary` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_seed_maps_to_zero` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_seed_source_treated_as_iter_zero` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_stagnating_vocab_forces_explore` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_stagnation_checked_before_evidence_depth` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_structural_invariance_keys_and_lengths_preserved` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_truncate_when_top_k_below_five` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_unparseable_source_falls_to_end` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/ml_model_proposal_agent/test_proposal_schemas.py`

Tests: 19

| Test function | Verdict | Reason |
|---|---|---|
| `test_accepts_list_of_dicts_coerced_to_info` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_accepts_multi_entry_list_preserves_order` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_accepts_single_entry_list` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_default_empty_when_omitted` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_expert_advice_as_dict` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_human_advice_accepts_expert_advice_as_dict` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_human_advice_accepts_plain_string` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_human_advice_accepts_structured_expert_advice` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_human_advice_defaults_to_none` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_invalid_entry_dict_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_interpretation_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_mathematical_definition_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_model_name_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_rejects_over_ten_entries` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_round_trip_preserves_entries` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_storage_custom` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_valid` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_valid_minimal` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_valid_with_all_fields` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/ml_model_proposal_agent/test_recent_gate_exhaustions.py`

Tests: 22

| Test function | Verdict | Reason |
|---|---|---|
| `test_all_unknown_tags_produces_no_block` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_block_absent_when_list_empty` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_closing_guidance_present` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_disallowed_block_appears_after_resource_accounting` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_disallowed_block_is_per_entry_not_global` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_dump_path_none_writes_nothing` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_dump_path_set_writes_rendered_prompt` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_empty_list_returns_empty_string` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_empty_patterns_produces_no_disallowed_block` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_every_tag_in_vocabulary_has_a_description` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_multi_entry_ordering_preserved_in_legacy_prompt` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_multi_pattern_renders_in_stored_order` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_placeholder_substitution` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_populated_block_carries_header_summary_and_accounting` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_proposing_system_prompt_block_inclusion` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_proposing_system_prompt_preserves_three_entry_order` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_single_entry_block_shape` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_single_pattern_renders_banner_and_description` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_template_carries_placeholder` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_three_entry_block_shape` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_two_entry_block_shape` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_unknown_tag_is_dropped_defensively` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/ml_model_proposal_agent/test_rejection_acknowledgement_prompt.py`

Tests: 17

| Test function | Verdict | Reason |
|---|---|---|
| `test_both_one_sided_failures_disqualified` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_causal_hypothesis_named_as_single_integrated_paragraph` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_citation_integrated_synthesis` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_citation_physical_failure_three_requirements` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_citation_scientific_bottleneck` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_clause_structure_intact` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_closing_cite_as_design_constraint` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_mandatory_header_follows_what_you_receive` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_mandatory_header_precedes_what_you_produce` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_mandatory_header_present` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_names_physical_constraints_sources` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_names_scientific_goals_source` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_not_a_historical_footnote` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_scientist_and_engineer_framing` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_three_citation_bullets_appear_in_order` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_treat_failure_as_design_constraint` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_two_constraint_systems_must_be_satisfied_simultaneously` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/protocols/test_ml_model_impl_to_ml_model_valid.py`

Tests: 3

| Test function | Verdict | Reason |
|---|---|---|
| `test_baseline_all_fields_pass_through` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_llm_kwargs_default_or_override` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_raises_not_implemented` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/protocols/test_ml_model_propose_to_ml_model_impl.py`

Tests: 2

| Test function | Verdict | Reason |
|---|---|---|
| `test_baseline_pass_through_and_default_dirs` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_raises_not_implemented` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/protocols/test_ml_model_tune_to_ml_result_interp.py`

Tests: 5

| Test function | Verdict | Reason |
|---|---|---|
| `test_empty_records_yields_default_summary` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_formal_round_surfaces_formal_score_and_vector` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_raises_not_implemented` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_round_lists_extracted_across_mixed_records` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_single_record_baseline_extracts_all_summary_fields` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/protocols/test_ml_model_valid_to_ml_model_tune.py`

Tests: 21

| Test function | Verdict | Reason |
|---|---|---|
| `test_all_three_budgets_independent` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_all_three_independent` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_baseline_attributes_from_inputs` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_both_deviations_prepended_in_order` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_both_vram_budgets_set_does_not_touch_time_budgets` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_custom_kwarg_passes_through` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_default_when_kwarg_omitted` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_defaults_match_schema_when_omitted` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_defaults_none_when_omitted` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_individual_attempt_kwarg_passes_through` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_individual_budget_passes_through_without_polluting_siblings` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_individual_vram_budget_passes_through_without_polluting_sibling` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_no_deviation_passes_advice_through_structured` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_penalty_resolves` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_raises_not_implemented` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_returns_hyperparam_tuning_input` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_single_deviation_prepended_to_serialized_advice` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_target_files_in_trial_target_mode` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_trial_mode_snapshot_kwargs_fan_out` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_value_resolves_to_canonical` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_vram_defaults_none_when_omitted` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/protocols/test_ml_result_interp_to_ml_model_propose.py`

Tests: 12

| Test function | Verdict | Reason |
|---|---|---|
| `test_baseline_serialisation_and_storage_pass_through` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_both_budgets_independent` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_defaults_when_caller_omits` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_empty_aggregation_when_no_populated_gate_exhaustion` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_full_trial_target_fan_out` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_kwarg_independent_of_other_pass_through_fields` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_multiple_model_types` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_partial_kwargs_only_overrides_supplied_fields` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_preserves_oldest_first_order_for_multi_entry_aggregation` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_raises_not_implemented` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_single_kwarg_passes_through` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_surfaces_single_gate_exhaustion_when_only_one_populated` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/result_interpretation_agent/test_dispatcher_wiring.py`

Tests: 4

| Test function | Verdict | Reason |
|---|---|---|
| `test_per_model_call_count_equals_active_set_size` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_skipped_calls_emit_audit_marker` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_synthesis_prompt_mentions_every_model_type` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_synthesis_prompt_size_under_15k_for_13_models` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |

### `tests/unit/agent/result_interpretation_agent/test_evolution_log_schema.py`

Tests: 9

| Test function | Verdict | Reason |
|---|---|---|
| `test_caller_payload_fields_reach_disk` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_caller_supplied_timestamp_is_overwritten` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_default_str_fallback_for_non_json_native_values` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_first_call_creates_file_with_one_line` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_io_error_is_swallowed_not_raised` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_missing_workspace_is_created` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_repeated_calls_append_distinct_rows` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_smoke_extension_keys_pass_through` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_writer_prepends_timestamp` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/result_interpretation_agent/test_interpretation_agent.py`

Tests: 71

| Test function | Verdict | Reason |
|---|---|---|
| `test_best_config_from_summary` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_best_score_extracted` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_cache_hit_scores_from_stats` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_cache_hit_skips_llm_call` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_cache_miss_calls_llm_and_populates_cache` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_cache_miss_stores_stats` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_carry_forward_metrics_preserved` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_descriptions_loaded_for_all` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_descriptions_only_no_summaries` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_digest_persisted_to_disk` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_duplicate_removed_and_aliased` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_existing_proposed_by_run_not_overwritten` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_expert_advice_before_human_advice_in_per_model` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_expert_advice_before_human_advice_in_synthesis` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_formal_score_none_stored_when_absent` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_formal_score_not_rendered_when_equal_to_best` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_formal_score_reconstructed_from_cache` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_formal_score_rendered_in_synthesis_when_different` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_formal_score_stored_in_stats_on_cache_miss` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_genuine_new_entry_stays_canonical` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_healthy_path_default_is_not_degraded` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_includes_best_score_table_rendered_markdown` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_includes_formal_score` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_includes_formal_score_table` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_includes_model_params` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_includes_params` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_includes_round_model_params_in_trajectory` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_includes_round_trial_portions_in_trajectory` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_includes_score_table` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_includes_training_psd_segments` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_includes_training_segments` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_includes_trial_portion` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_invalid_duplicate_of_name_treated_as_genuine` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_is_degraded_flag_true` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_key_findings_and_bottlenecks_empty` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_mixed_one_cached_one_new_llm_called_once` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_model_description_loaded` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_no_existing_canonicals_of_same_kind_skips_llm` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_no_model_provided_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_no_previous_proposal_no_crash` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_no_promotions_skips_llm` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_none_fields_produce_none_output` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_only_same_kind_used_for_comparison` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_output_is_valid` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_output_written_to_file` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_overall_best_is_cross_model_max` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_per_model_params_populated` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_per_model_prompt_excludes_expert_when_empty` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_per_model_prompt_includes_expert_advice_string` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_per_model_score_tables_populated` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_per_model_scores` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_per_model_scores_independent` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_per_model_summaries_for_all` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_per_model_summaries_populated` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_per_model_training_segments_populated` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_phase1_findings_used` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_proposed_by_run_injected_from_model_name` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_returns_output_instead_of_raising` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_runtime_vocab_carried_forward_unchanged` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_skips_none_fields` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_synthesis_prompt_excludes_expert_when_empty` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_synthesis_prompt_includes_expert_advice_string` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_synthesis_prompt_renders_weight_and_impact_columns` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_synthesis_used_for_multi_model` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_take_home_message_marks_degraded` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_total_experiments` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_total_experiments_across_models` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_two_models_both_in_output` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_unknown_model_type_raises` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_works_without_new_fields` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_worst_score_extracted` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |

### `tests/unit/agent/result_interpretation_agent/test_interpretation_schemas.py`

Tests: 19

| Test function | Verdict | Reason |
|---|---|---|
| `test_active_model_custom` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_active_model_defaults` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_active_model_negative_delta_rejected` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_active_model_negative_last_n_rejected` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_active_model_negative_top_k_rejected` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_active_model_zero_allowed` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_empty_model_types_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_minimal` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_take_home_message_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_no_model_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_storage_custom` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_storage_default` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_valid` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_valid_full` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_valid_multi_model` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_valid_no_experiments` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_valid_with_both` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_valid_with_model_types` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_valid_with_summaries` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/result_interpretation_agent/test_stability_filter.py`

Tests: 22

| Test function | Verdict | Reason |
|---|---|---|
| `test_active_set_top_k_plus_last_n_plus_delta` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_active_with_more_rounds_recalls` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_active_with_no_new_evidence_skips` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_active_with_score_delta_recalls` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_below_threshold_delta_skips` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_cache_miss_always_recalls` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_compress_falls_back_to_best_config_analysis` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_compress_placeholder_when_nothing_available` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_compress_preserves_key_finding` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_compress_total_serialised_length_under_200` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_compress_truncates_long_finding_with_ellipsis` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_compress_zero_max_takeaway_rejected` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_delta_at_or_above_threshold_included` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_delta_below_threshold_excluded` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_delta_path_skipped_for_models_without_prior` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_empty_cache_and_no_summaries` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_inactive_with_new_data_still_skips` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_last_n_truncates_to_first_n` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_lex_tiebreak_determinism` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_negative_thresholds_rejected` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_stability_filter_skips_stable_models` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_top_k_excludes_models_with_none_score` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/result_interpretation_agent/test_vocab_feedback.py`

Tests: 61

| Test function | Verdict | Reason |
|---|---|---|
| `test_adds_candidates` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_adds_discoveries` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_all_candidates_returns_one` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_all_canonical_returns_zero` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_already_canonical_untouched` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_already_in_related_to_not_promoted_twice` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_below_threshold_no_promotion` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_boldness_uses_sota_baseline` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_boldness_zero_when_no_predicted_value` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_capability_with_enough_runs_promoted` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_confirmed_beats_sota` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_confirmed_outcome_increments_count` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_confirmed_prediction` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_current_sota_override_takes_precedence` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_custom_min_runs` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_deduplicates_by_name` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_different_runs_accumulated` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_discoveries_excluded_from_ratio` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_discovery_never_promoted_regardless_of_runs` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_does_not_mutate_existing_confirmations` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_empty_vocab` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_empty_vocab_returns_zero` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_exactly_at_sota_is_partial` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_existing_candidate_seen_in_runs_extended` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_feature_not_in_vocab_no_crash` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_feature_with_enough_runs_promoted` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_file_vector_metric_confirmed` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_half_candidates` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_information_gain_confirmed_equals_delta` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_information_gain_zero_when_partial` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_information_gain_zero_when_refuted` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_insufficient_runs_stays_candidate` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_actual_results` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_current_sota_and_current_value` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_current_sota_falls_back_to_current_value` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_proposed_by_run_no_crash` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_mixed_vocab` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_mixed_vocab_only_eligible_promoted` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_multiple_links_promoted_independently` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_new_candidate_gets_proposed_by_run` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_no_prediction` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_none_outcome_does_not_increment` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_only_discoveries_returns_zero` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_overall_best_score_negates_false_beat` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_overall_best_score_only_no_prediction` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_overall_best_score_overrides_stale_sota` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_partial_margin_custom` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_partial_outcome_does_not_increment` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_partial_with_none_actual` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_partial_within_margin` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_promotes_to_related_to_at_threshold` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_refuted_clearly_below_sota` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_refuted_outcome_does_not_increment` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_refuted_prediction` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_returns_correct_promoted_names` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_same_run_not_counted_twice` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_same_run_not_duplicated_in_seen_in_runs` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_score_vs_sota` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_seed_only` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_seen_in_runs_enables_promotion_after_three_iterations` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_vocab_grows_across_iterations` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/schemas/test_score_table.py`

Tests: 28

| Test function | Verdict | Reason |
|---|---|---|
| `test_all_model_side_columns_may_be_none` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_extra_fields_forbidden` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_extra_fields_forbidden_on_table` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_file_index_range` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_full_run_aggregate` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_fully_populated_row` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_happy_path_20_rows` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_headroom_negative_rejected` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_headroom_none_accepted_for_unsampled_file` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_headroom_zero_accepted` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_impact_columns_default_to_none` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_impact_score_clamps_at_zero_for_already_saturated_file` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_impact_score_negative_rejected` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_json_round_trip_preserves_none` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_json_round_trip_preserves_rendered_markdown` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_linear_weight_above_one_rejected` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_linear_weight_at_bounds_accepted` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_linear_weight_negative_rejected` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_num_sampled_files_lower_bound` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_num_sampled_files_upper_bound` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_rejects_fewer_than_20_rows` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_rejects_more_than_20_rows` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_trial_run_aggregate` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_validator_passes_when_rows_and_total_agree` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_validator_rejects_off_sum_full_subset` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_validator_rejects_stored_total_off_even_when_rows_sum_to_one` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_validator_skipped_when_no_sampled_weights` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_validator_tolerates_float_round_off_within_1e9` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/test_llm_bridge.py`

Tests: 62

| Test function | Verdict | Reason |
|---|---|---|
| `test_arguments_are_parsed_dict` | Refactor | Mock-positive in test_llm_bridge.py; ledger §6.3 says split into schema/prompt (unit) and response-parsing (integration) |
| `test_cross_provider_creates_distinct_clients` | Refactor | Mock-positive in test_llm_bridge.py; ledger §6.3 says split into schema/prompt (unit) and response-parsing (integration) |
| `test_cross_provider_routes_reflect_to_second_client` | Refactor | Mock-positive in test_llm_bridge.py; ledger §6.3 says split into schema/prompt (unit) and response-parsing (integration) |
| `test_default_both_methods_use_same_model` | Refactor | Mock-positive in test_llm_bridge.py; ledger §6.3 says split into schema/prompt (unit) and response-parsing (integration) |
| `test_default_reflect_provider_falls_back_to_main_provider` | Refactor | Mock-positive in test_llm_bridge.py; ledger §6.3 says split into schema/prompt (unit) and response-parsing (integration) |
| `test_empty_content_retried_then_succeeds` | Refactor | Mock-positive in test_llm_bridge.py; ledger §6.3 says split into schema/prompt (unit) and response-parsing (integration) |
| `test_explicit_args_override_known_defaults` | Refactor | Mock-positive in test_llm_bridge.py; ledger §6.3 says split into schema/prompt (unit) and response-parsing (integration) |
| `test_explicit_none_falls_back_to_main_model` | Refactor | Mock-positive in test_llm_bridge.py; ledger §6.3 says split into schema/prompt (unit) and response-parsing (integration) |
| `test_explicit_same_provider_reuses_client` | Refactor | Mock-positive in test_llm_bridge.py; ledger §6.3 says split into schema/prompt (unit) and response-parsing (integration) |
| `test_extra_json_object_after_valid_one_is_discarded` | Refactor | Mock-positive in test_llm_bridge.py; ledger §6.3 says split into schema/prompt (unit) and response-parsing (integration) |
| `test_generate_always_uses_main_model` | Refactor | Mock-positive in test_llm_bridge.py; ledger §6.3 says split into schema/prompt (unit) and response-parsing (integration) |
| `test_honors_retry_delay_on_429` | Refactor | Mock-positive in test_llm_bridge.py; ledger §6.3 says split into schema/prompt (unit) and response-parsing (integration) |
| `test_json_mode_requested` | Refactor | Mock-positive in test_llm_bridge.py; ledger §6.3 says split into schema/prompt (unit) and response-parsing (integration) |
| `test_known_provider_default_model` | Refactor | Mock-positive in test_llm_bridge.py; ledger §6.3 says split into schema/prompt (unit) and response-parsing (integration) |
| `test_known_provider_gemini` | Refactor | Mock-positive in test_llm_bridge.py; ledger §6.3 says split into schema/prompt (unit) and response-parsing (integration) |
| `test_known_provider_openai` | Refactor | Mock-positive in test_llm_bridge.py; ledger §6.3 says split into schema/prompt (unit) and response-parsing (integration) |
| `test_malformed_json_raises_value_error` | Refactor | Mock-positive in test_llm_bridge.py; ledger §6.3 says split into schema/prompt (unit) and response-parsing (integration) |
| `test_malformed_then_valid_succeeds` | Refactor | Mock-positive in test_llm_bridge.py; ledger §6.3 says split into schema/prompt (unit) and response-parsing (integration) |
| `test_markdown_fenced_json_is_parsed` | Refactor | Mock-positive in test_llm_bridge.py; ledger §6.3 says split into schema/prompt (unit) and response-parsing (integration) |
| `test_messages_contain_system_and_user` | Refactor | Mock-positive in test_llm_bridge.py; ledger §6.3 says split into schema/prompt (unit) and response-parsing (integration) |
| `test_no_json_mode_requested` | Refactor | Mock-positive in test_llm_bridge.py; ledger §6.3 says split into schema/prompt (unit) and response-parsing (integration) |
| `test_non_dict_or_list_first_token_raises` | Refactor | Mock-positive in test_llm_bridge.py; ledger §6.3 says split into schema/prompt (unit) and response-parsing (integration) |
| `test_old_file_vector_section_removed_from_planner` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_parses_seconds_string` | Refactor | Mock-positive in test_llm_bridge.py; ledger §6.3 says split into schema/prompt (unit) and response-parsing (integration) |
| `test_plan_empty_string_treated_as_none` | Refactor | Mock-positive in test_llm_bridge.py; ledger §6.3 says split into schema/prompt (unit) and response-parsing (integration) |
| `test_plan_none_uses_planner_fallback` | Refactor | Mock-positive in test_llm_bridge.py; ledger §6.3 says split into schema/prompt (unit) and response-parsing (integration) |
| `test_plan_substitutes_score_table_md_into_system_prompt` | Refactor | Mock-positive in test_llm_bridge.py; ledger §6.3 says split into schema/prompt (unit) and response-parsing (integration) |
| `test_planner_prompt_contains_score_table_token` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_planner_prompt_has_new_section_header` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_planner_references_best_experiment_not_most_recent` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_provider_agnostic` | Refactor | Mock-positive in test_llm_bridge.py; ledger §6.3 says split into schema/prompt (unit) and response-parsing (integration) |
| `test_provider_is_lowercased` | Refactor | Mock-positive in test_llm_bridge.py; ledger §6.3 says split into schema/prompt (unit) and response-parsing (integration) |
| `test_raises_when_no_tool_call_returned` | Refactor | Mock-positive in test_llm_bridge.py; ledger §6.3 says split into schema/prompt (unit) and response-parsing (integration) |
| `test_reflect_context_with_null_key_uses_reflector_fallback` | Refactor | Mock-positive in test_llm_bridge.py; ledger §6.3 says split into schema/prompt (unit) and response-parsing (integration) |
| `test_reflect_context_without_key_uses_reflector_fallback` | Refactor | Mock-positive in test_llm_bridge.py; ledger §6.3 says split into schema/prompt (unit) and response-parsing (integration) |
| `test_reflect_model_id_separates_planner_from_reflector` | Refactor | Mock-positive in test_llm_bridge.py; ledger §6.3 says split into schema/prompt (unit) and response-parsing (integration) |
| `test_reflect_none_context_uses_reflector_fallback` | Refactor | Mock-positive in test_llm_bridge.py; ledger §6.3 says split into schema/prompt (unit) and response-parsing (integration) |
| `test_reflect_provider_is_lowercased` | Refactor | Mock-positive in test_llm_bridge.py; ledger §6.3 says split into schema/prompt (unit) and response-parsing (integration) |
| `test_reflect_provider_only_no_model_override` | Refactor | Mock-positive in test_llm_bridge.py; ledger §6.3 says split into schema/prompt (unit) and response-parsing (integration) |
| `test_reflect_substitutes_from_context` | Refactor | Mock-positive in test_llm_bridge.py; ledger §6.3 says split into schema/prompt (unit) and response-parsing (integration) |
| `test_reflect_uses_main_model_when_not_split` | Refactor | Mock-positive in test_llm_bridge.py; ledger §6.3 says split into schema/prompt (unit) and response-parsing (integration) |
| `test_reflect_uses_reflect_model_when_split` | Refactor | Mock-positive in test_llm_bridge.py; ledger §6.3 says split into schema/prompt (unit) and response-parsing (integration) |
| `test_reflect_uses_reflector_system_prompt` | Refactor | Mock-positive in test_llm_bridge.py; ledger §6.3 says split into schema/prompt (unit) and response-parsing (integration) |
| `test_reflector_prompt_contains_score_table_token` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_reflector_prompt_has_new_section_header` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_returns_dict` | Refactor | Mock-positive in test_llm_bridge.py; ledger §6.3 says split into schema/prompt (unit) and response-parsing (integration) |
| `test_returns_none_when_body_not_dict` | Refactor | Mock-positive in test_llm_bridge.py; ledger §6.3 says split into schema/prompt (unit) and response-parsing (integration) |
| `test_returns_none_when_delay_not_seconds_format` | Refactor | Mock-positive in test_llm_bridge.py; ledger §6.3 says split into schema/prompt (unit) and response-parsing (integration) |
| `test_returns_none_when_details_missing` | Refactor | Mock-positive in test_llm_bridge.py; ledger §6.3 says split into schema/prompt (unit) and response-parsing (integration) |
| `test_returns_none_when_no_retry_info` | Refactor | Mock-positive in test_llm_bridge.py; ledger §6.3 says split into schema/prompt (unit) and response-parsing (integration) |
| `test_returns_sorted_ids` | Refactor | Mock-positive in test_llm_bridge.py; ledger §6.3 says split into schema/prompt (unit) and response-parsing (integration) |
| `test_returns_str` | Refactor | Mock-positive in test_llm_bridge.py; ledger §6.3 says split into schema/prompt (unit) and response-parsing (integration) |
| `test_returns_tool_call_result` | Refactor | Mock-positive in test_llm_bridge.py; ledger §6.3 says split into schema/prompt (unit) and response-parsing (integration) |
| `test_strips_whitespace` | Refactor | Mock-positive in test_llm_bridge.py; ledger §6.3 says split into schema/prompt (unit) and response-parsing (integration) |
| `test_tool_call_result_is_frozen` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_tools_passed_to_api` | Refactor | Mock-positive in test_llm_bridge.py; ledger §6.3 says split into schema/prompt (unit) and response-parsing (integration) |
| `test_trailing_prose_after_valid_json_is_discarded` | Refactor | Mock-positive in test_llm_bridge.py; ledger §6.3 says split into schema/prompt (unit) and response-parsing (integration) |
| `test_two_calls_in_sequence_use_correct_models` | Refactor | Mock-positive in test_llm_bridge.py; ledger §6.3 says split into schema/prompt (unit) and response-parsing (integration) |
| `test_unknown_provider_no_model_id_is_none` | Refactor | Mock-positive in test_llm_bridge.py; ledger §6.3 says split into schema/prompt (unit) and response-parsing (integration) |
| `test_unknown_provider_with_explicit_args` | Refactor | Mock-positive in test_llm_bridge.py; ledger §6.3 says split into schema/prompt (unit) and response-parsing (integration) |
| `test_unknown_reflect_provider_raises` | Refactor | Mock-positive in test_llm_bridge.py; ledger §6.3 says split into schema/prompt (unit) and response-parsing (integration) |
| `test_uses_exponential_backoff_without_retry_delay` | Refactor | Mock-positive in test_llm_bridge.py; ledger §6.3 says split into schema/prompt (unit) and response-parsing (integration) |

### `tests/unit/agent/test_llm_bridge_singleton.py`

Tests: 2

| Test function | Verdict | Reason |
|---|---|---|
| `test_llm_bridge_itself_still_constructs_openai` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_only_llm_bridge_constructs_openai_client` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/test_prompt_banned_vocabulary.py`

Tests: 4

| Test function | Verdict | Reason |
|---|---|---|
| `test_banned_vocabulary_absent` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_impact_aware_framing_present` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_planner_prompt_per_file_table_uses_impact_columns` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_proposer_reasoning_uses_impact_score` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/test_skill_spec.py`

Tests: 9

| Test function | Verdict | Reason |
|---|---|---|
| `test_basic_creation` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_function_name_and_description` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_output_schema_not_in_tool_definition` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_parameters_contain_expected_fields` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_parameters_match_input_schema` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_reflects_schema_changes` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_required_fields_present` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_stores_class_not_instance` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_top_level_structure` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/training_skill/test_estimator.py`

Tests: 15

| Test function | Verdict | Reason |
|---|---|---|
| `test_batch_size_scales_output_logits_linearly` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_epochs_scales_linearly` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_fcnet_activations_use_1x_factor` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_focal_loss_adds_onehot_bytes` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_ms_per_step_passthrough_applies_gpu_calibration` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_ms_per_step_passthrough_no_gpu` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_num_params_scales_model_overhead_linearly` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_regression_against_wrapper_static_path` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_return_shape` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_rnn_has_no_transformer_attn` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_seg_size_scales_output_logits_linearly` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_seg_size_scales_transformer_attn_quadratically` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_static_fallback_invokes_internal_count_params` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_train_portion_reduces_steps` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_transformer_has_attn_term` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/tune_ml_hyperparam_agent/test_build_gate_exhaustion.py`

Tests: 19

| Test function | Verdict | Reason |
|---|---|---|
| `test_all_time_gated_returns_populated_info` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_all_vram_gated_returns_populated_info` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_baseline_estimate_missing_uses_worst_only_phrasing` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_burst_below_50pct_gate_skip_does_not_fire` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_completed_rounds_zero_falls_through_to_trigger_a` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_consecutive_fails_below_threshold_does_not_fire` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_empty_records_returns_none` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_ever_trained_true_returns_none` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_max_fail_rounds_zero_disables_trigger_b` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_mixed_gating_with_other_failures` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_mixed_summary_uses_multi_axis_verdict` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_no_gate_skip_returns_none` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_summary_message_calls_out_time_axis` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_summary_message_calls_out_vram_axis` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_time_budget_none_yields_none_time_factors` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_trigger_b_focuses_report_on_burst_records` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_trigger_b_summary_uses_phase_l_framing` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_trigger_b_with_mixed_burst_axis_says_vram_time` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_vram_budget_none_yields_none_vram_factors` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/tune_ml_hyperparam_agent/test_constraint_aware_retry.py`

Tests: 10

| Test function | Verdict | Reason |
|---|---|---|
| `test_all_records_saved_as_skipped_schema_violation` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_does_not_raise_does_not_advance_rounds` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Move to integration suite — the test mocks the agent's entire execution context " |
| `test_ge_violation_returns_schema_violation` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_greater_than_equal_loc_and_type` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_happy_path_unchanged` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_model_validator_violation_loc_is_root` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_model_validator_violation_returns_schema_violation` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_multiple_of_loc_and_type_and_input` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_multiple_of_violation_returns_schema_violation` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_record_memory_carries_violation_details` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Move to integration suite — the test mocks the agent's entire execution context " |

### `tests/unit/agent/tune_ml_hyperparam_agent/test_degeneracy_handling.py`

Tests: 6

| Test function | Verdict | Reason |
|---|---|---|
| `test_degenerate_formal_with_float_penalty_uses_penalty` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_degenerate_formal_with_none_penalty_nulls_score` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_degenerate_trial_round_is_no_op` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_keys_default_to_false_none` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_non_degenerate_formal_preserves_score` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_non_degenerate_trial_preserves_score` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/tune_ml_hyperparam_agent/test_disallowed_patterns.py`

Tests: 15

| Test function | Verdict | Reason |
|---|---|---|
| `test_empty_records_yields_empty` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_healthy_iteration_returns_none_and_no_patterns` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_iter2_style_9_scan_attempts_at_huge_factor_yields_scan_tag` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_iter3_style_9_gru_attempts_at_moderate_factor_yields_recurrent_tag` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_marginal_overshoot_populates_empty_patterns_but_still_fires_trigger` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_marginal_overshoot_under_threshold_yields_no_tags` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_mixed_records_populate_sorted_union` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_mixed_scan_and_gru_records_yield_both_tags_sorted` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_non_gate_failures_never_contribute_tags` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_none_budgets_yield_empty` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_successful_arch_is_never_banned` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_threshold_exactly_at_boundary_is_not_banned` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_trigger_a_iter2_scan_records_produce_scan_tag_on_info` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_trigger_b_burst_of_scan_records_surfaces_scan_tag` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_vram_factor_alone_can_trigger_ban` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/tune_ml_hyperparam_agent/test_estimator_static_patch.py`

Tests: 6

| Test function | Verdict | Reason |
|---|---|---|
| `test_min_ms_per_step_floor` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_safety_multiplier_raised` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_static_formula_5x_higher_than_old` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_static_formula_above_floor_uses_computed` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_static_formula_applies_floor_for_tiny_model` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_static_ms_per_flop_raised` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/tune_ml_hyperparam_agent/test_evaluate_time_skill.py`

Tests: 30

| Test function | Verdict | Reason |
|---|---|---|
| `test_defaults_are_3_warmup_7_timed` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_empty_list_returns_none_and_aggregator_none` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_fast_fail_aggregator_surfaces_on_breakdown` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Rewrite as pure-logic tests that exercise wrapper routing with synthetic data sh" |
| `test_fast_fail_step0_above_threshold_returns_that_step_ms` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_fast_fail_uses_default_threshold_constant` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_legacy_breakdown_keys_still_present` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Rewrite as pure-logic tests that exercise wrapper routing with synthetic data sh" |
| `test_median_aggregator_surfaces_on_breakdown` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Rewrite as pure-logic tests that exercise wrapper routing with synthetic data sh" |
| `test_median_branch_discards_warmup_then_takes_median` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_median_is_robust_to_one_outlier_unlike_mean` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_no_data_dir_aggregator_is_none` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Rewrite as pure-logic tests that exercise wrapper routing with synthetic data sh" |
| `test_no_timed_steps_returns_none` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_registered_model_type_does_not_emit_warning` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Rewrite as pure-logic tests that exercise wrapper routing with synthetic data sh" |
| `test_return_annotation_is_tuple` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_run_skill_dominant_phase_is_training_for_typical_config` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_run_skill_error_on_malformed_model_config` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_run_skill_estimated_minutes_is_sum_of_phase_seconds` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_run_skill_falls_back_to_static_when_warmup_returns_none` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Rewrite as pure-logic tests that exercise wrapper routing with synthetic data sh" |
| `test_run_skill_feasible_tiny_model` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_run_skill_infeasible_large_model` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_run_skill_infeasible_suggestion_reflects_lever` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_run_skill_phase_breakdown_contains_all_three_phases` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_run_skill_returns_contract_shape` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_run_skill_safety_multiplier_surfaced_in_breakdown` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_run_skill_skips_warmup_without_data_dir` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Rewrite as pure-logic tests that exercise wrapper routing with synthetic data sh" |
| `test_run_skill_uses_warmup_when_data_dir_and_measurement_available` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Rewrite as pure-logic tests that exercise wrapper routing with synthetic data sh" |
| `test_suggest_lever_high_ms_per_step_recommends_shrinking_model` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_suggest_lever_otherwise_recommends_raising_seg_size` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_suggest_lever_small_seg_bs1_recommends_raising_batch` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_unregistered_model_type_emits_warning_and_flags_breakdown` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Rewrite as pure-logic tests that exercise wrapper routing with synthetic data sh" |
| `test_warmup_scales_inference_ms_by_ratio` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Rewrite as pure-logic tests that exercise wrapper routing with synthetic data sh" |

### `tests/unit/agent/tune_ml_hyperparam_agent/test_force_formal_round.py`

Tests: 50

| Test function | Verdict | Reason |
|---|---|---|
| `test_accepts_false` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_accepts_true_explicit` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_alias_log_line_emitted` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_all_strategies_uniform_signature` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_best_trial_winner_excludes_formal_mode` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_best_trial_winner_excludes_missing_time_mode` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_best_trial_winner_excludes_non_success` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_best_trial_winner_picks_max_score` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_best_trial_winner_returns_none_on_empty` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_default_is_true` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_does_not_touch_model_cfg` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_falls_back_to_planner_when_no_winner` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_force_formal_inheritance_resilient_to_missing_train_keys` | Delete | Named in ledger §4 flag table; verdict from recipe: "Delete the mocked tests, keep the pure plan-mutation tests. Inheritance logic sh" |
| `test_force_formal_inherits_full_winner_config` | Delete | Named in ledger §4 flag table; verdict from recipe: "Delete the mocked tests, keep the pure plan-mutation tests. Inheritance logic sh" |
| `test_force_formal_model_cfg_inheritance_isolated_from_winner` | Delete | Named in ledger §4 flag table; verdict from recipe: "Delete the mocked tests, keep the pure plan-mutation tests. Inheritance logic sh" |
| `test_force_formal_off_honours_planner` | Delete | Named in ledger §4 flag table; verdict from recipe: "Delete the mocked tests, keep the pure plan-mutation tests. Inheritance logic sh" |
| `test_force_formal_on_forces_formal` | Delete | Named in ledger §4 flag table; verdict from recipe: "Delete the mocked tests, keep the pure plan-mutation tests. Inheritance logic sh" |
| `test_inherit_best_trial_behaves_as_full_clone` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_inheritance_default_memory_history_none` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_inheritance_logs_winner_identity` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_inheritance_skipped_on_non_last_rounds` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_inheritance_skipped_when_force_formal_off` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_inherits_all_five_fields_from_winner` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_inherits_only_loss_cfg_and_lr` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_llm_propose_behaves_as_independent` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_log_lists_inherited_fields` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_no_trial_winner_falls_back_to_planner_with_warning` | Delete | Named in ledger §4 flag table; verdict from recipe: "Delete the mocked tests, keep the pure plan-mutation tests. Inheritance logic sh" |
| `test_no_winner_no_warning` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_non_last_round_unaffected_by_flag` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_planner_already_formal_no_op` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_planner_choices_survive_verbatim` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_prompt_non_last_round_unaffected_by_flag` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_prompt_says_mandatory_when_force_formal_on_last_round` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_prompt_says_optional_when_force_formal_off_last_round` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_prompt_trial_disabled_directs_formal` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_registry_directly_exposes_handler_callables` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_registry_has_three_canonical_strategies` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_shim_canonical_full_clone_inherits_like_legacy` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_shim_canonical_independent_skips_inheritance` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_shim_legacy_inherit_best_trial_still_works` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_strategy_accepts_canonical_full_clone` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_strategy_accepts_canonical_independent` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_strategy_default_is_full_clone` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_strategy_hybrid_params_validates` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_strategy_legacy_inherit_best_trial_aliases_to_full_clone` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_strategy_legacy_llm_propose_aliases_to_independent` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_strategy_llm_propose_keeps_planner_choices` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_strategy_llm_propose_no_warning_without_winner` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_strategy_rejects_unknown_value` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_trial_disallowed_overrides_unconditionally` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/tune_ml_hyperparam_agent/test_formal_sample_set.py`

Tests: 6

| Test function | Verdict | Reason |
|---|---|---|
| `test_formal_default_training_produces_20_file_snapshot` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_formal_eval_is_locked_to_full_snapshot` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_formal_eval_lock_is_immovable_against_plan_overrides` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_formal_training_override_respected` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_single_file_mode_defaults` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_trial_mode_still_uses_planner_values` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/tune_ml_hyperparam_agent/test_hardware_context_init.py`

Tests: 3

| Test function | Verdict | Reason |
|---|---|---|
| `test_manifest_round_trips_to_schema` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Move to integration — file I/O + agent orchestration requires the full harness." |
| `test_manifest_written_on_run` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Move to integration — file I/O + agent orchestration requires the full harness." |
| `test_second_run_does_not_rewrite_manifest` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Move to integration — file I/O + agent orchestration requires the full harness." |

### `tests/unit/agent/tune_ml_hyperparam_agent/test_hyperparam_schemas.py`

Tests: 80

| Test function | Verdict | Reason |
|---|---|---|
| `test_accepts_populated_info_and_round_trips` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_active_mode_rejects_other_strings` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_all_records_validated_as_experiment_records` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_both_optional_by_default` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_both_tables_independently_populated` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_budget_split_shapes` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_budgets_round_trip_through_json` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_default_none_when_omitted` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_defaults` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_defaults_to_normal_mode` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_defaults_when_all_fields_omitted` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_defaults_when_not_provided` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_defaults_when_trial_fields_omitted` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_disallowed_patterns_rejects_non_list` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_disallowed_patterns_round_trip_through_json` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_disallowed_patterns_shapes` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_error_scoring_baseline` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_error_scoring_round_trips_through_json` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_error_status_accepted` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_existing_record_round_trip_unchanged` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_existing_record_without_trial_fields` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_explicit_values_preserved` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_field_rejections_raise` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_field_round_trips_through_json` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_field_shapes` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_formal_plan` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_full_populated_validates` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_invalid_record_in_all_records_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_invalid_score_table_rejected` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_invalid_status_literal_still_rejected` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_invalid_status_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_invalid_status_rejected` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_invalid_terminal_state_rejected` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_file_index_uses_default` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_model_type_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_required_field_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_mode_rejections` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_model_dump_roundtrip` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_non_numeric_budget_rejected` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_oom_missing_file_index_uses_default` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_oom_missing_memory_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_optional_for_backward_compat` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_output_with_file_vector` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_output_without_file_vector` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_overrides_accepted` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_plan_rejections` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_populated_score_table_round_trips` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_record_with_target_strategy` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_record_with_trial_context` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_reflect_field_shapes` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_reflect_fields_round_trip_through_json` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_reflect_provider_invalid_value_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_required_fields_only_with_optionals_default_none` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_round_fields_round_trip_through_record` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_round_trip_through_json` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_single_score_table_populated` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_storage_defaults_when_omitted` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_storage_invalid_backend_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_storage_local_workspace_and_run_name` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_target_strategy_with_files` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_terminal_state_shapes` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_time_field_shapes` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_time_mode_rejects_other_strings` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_trial_field_rejections` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_unknown_error_variant_still_rejected` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_valid_advice_shapes` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_valid_auto_model_type` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_valid_completed_output_baseline` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_valid_full_plan` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_valid_mode_configurations` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_valid_oom_record` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_valid_schema_violation_record` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_valid_status_variants` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_valid_success_record_baseline` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_valid_trial_configurations` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_vram_field_shapes` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_vram_fields_independent_of_time_fields` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_with_defaults_rejections` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_with_defaults_shapes` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_zero_rejected_for_attempt_budget_field` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/tune_ml_hyperparam_agent/test_inference_aggregator.py`

Tests: 20

| Test function | Verdict | Reason |
|---|---|---|
| `test_aggregator_is_median_when_value_returned` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_aggregator_is_none_when_value_is_none` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_all_zero_elapsed_returns_none` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_breakdown_has_required_keys` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_breakdown_preserves_input_list_independence` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_empty_list_returns_none` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_five_files_discards_one` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_elapsed_ms_treated_as_zero` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_n_psd_segs_defaults_to_one` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_mixed_segment_counts_normalise_correctly` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_n_warmup_clamped_below_n_files` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_negative_elapsed_treated_as_degenerate` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_single_file_returns_none` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_ten_files_discards_two` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_twenty_files_discards_four` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_two_files_discards_one` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_variable_per_segment_cost_takes_median` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_warmup_fraction_echoed_in_breakdown` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_zero_fraction_floors_at_one` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_zero_n_psd_segs_treated_as_one` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/tune_ml_hyperparam_agent/test_inference_hint_path.py`

Tests: 20

| Test function | Verdict | Reason |
|---|---|---|
| `test_breakdown_carries_required_keys` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Assert on real (un-mocked) wrapper output or move to integration." |
| `test_handles_missing_memory_dict` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_hint_negative_falls_through_to_fallback` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_hint_present_sets_source_trial_inference_warmup` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_hint_value_matches_corrected_formula` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_hint_zero_falls_through_to_fallback` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_measured_path_beyond_slack_is_infeasible` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_measured_path_under_budget_no_slack_note` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_measured_path_within_slack_window_is_feasible` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_no_hint_no_warmup_lands_static_formula` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_no_hint_with_training_warmup_lands_x27_fallback` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_oom_between_two_trials_does_not_displace_recent` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_returns_most_recent_successful_trial` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_returns_none_on_empty_history` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_returns_none_when_no_qualifying_record` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_skips_failed_records` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_skips_formal_records` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_skips_record_with_missing_time_mode` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_static_formula_path_strict_check` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_x27_fallback_path_strict_check` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/tune_ml_hyperparam_agent/test_memory_history_truncation.py`

Tests: 8

| Test function | Verdict | Reason |
|---|---|---|
| `test_10_records_gives_7_condensed_3_full` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_condensed_keys_are_exactly_specified` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_empty_list` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_exact_window_returns_all_verbatim` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_fewer_than_window_returns_all_verbatim` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_json_size_reduction` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_memory_key_handled` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_non_destructive_original_list_unchanged` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/tune_ml_hyperparam_agent/test_memory_probe.py`

Tests: 12

| Test function | Verdict | Reason |
|---|---|---|
| `test_appends_row_when_workspace_given` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_emits_mem_line_with_canonical_fields` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_end_then_post_gc_pair_writes_two_rows` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_iter_can_be_string` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_psutil_emits_sentinel_row` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_multiple_calls_append_not_overwrite` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_no_workspace_does_not_create_file` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_ordered_probes_produce_monotonic_trace` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_post_gc_round_trip` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_row_has_required_fields` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_rss_and_vms_are_numeric_when_psutil_available` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_workspace_is_created_if_missing` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/tune_ml_hyperparam_agent/test_per_round_attempt_budget.py`

Tests: 5

| Test function | Verdict | Reason |
|---|---|---|
| `test_aborts_at_max_fail_rounds` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_formal_budget_asymmetry` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_increments_then_resets` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_only_last_round_uses_formal_budget` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_succeeds_within_budget` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |

### `tests/unit/agent/tune_ml_hyperparam_agent/test_physical_rejection_capture.py`

Tests: 7

| Test function | Verdict | Reason |
|---|---|---|
| `test_attempt_config_carries_model_type` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_feasible_run_yields_empty_rejection_buffer` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_missing_memory_killer_defaults_applied` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_non_round_bytes_rounded_to_four_decimals` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_one_gb_exact` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_one_rejection_with_expected_killer_fields` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_three_rejections_preserved_in_order` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |

### `tests/unit/agent/tune_ml_hyperparam_agent/test_planner_fixed_params.py`

Tests: 8

| Test function | Verdict | Reason |
|---|---|---|
| `test_empty_when_no_overrides_and_no_cap` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_only_max_epochs_renders_cap_only` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_partial_overrides_render_only_supplied_keys` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_planner_prompt_block_with_only_max_epochs` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_planner_prompt_includes_block_when_overrides_set` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_planner_prompt_omits_block_when_no_overrides` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_unknown_override_key_renders_generically` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_workflow_default_overrides_render_all_lines` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/tune_ml_hyperparam_agent/test_planner_resource_budgets.py`

Tests: 13

| Test function | Verdict | Reason |
|---|---|---|
| `test_blocks_absent_when_no_budgets_or_estimates` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_both_blocks_rendered_when_budgets_set` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_empty_when_all_args_explicit_none` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_empty_when_no_budgets_and_no_estimates` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_formal_mode_picks_formal_budgets` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_gpu_memory_rules_section_removed` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_header_present` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_lever_decision_tree_phrases_present` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_rendered_before_instructions` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_round_1_no_prior_estimate_renders_budget_only` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_time_budget_none_renders_disabled_line_no_factor` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_trial_mode_full_render_matches_spec_example` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_vram_budget_none_renders_disabled_line_no_factor` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/tune_ml_hyperparam_agent/test_plugin_source_excerpt.py`

Tests: 15

| Test function | Verdict | Reason |
|---|---|---|
| `test_block_formatter_resolves_plugin_class` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_embeds_extracted_source` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_empty_when_source_unavailable` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_excerpt_embedded_in_user_prompt_when_supplied` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_excerpt_rendered_before_checklist` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_extractor_resolves_plugin_class` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_field_validator_decorator_present` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_graceful_on_dynamic_class` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_heading_and_fence_present` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_model_validator_body_present` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_none_returns_empty` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_per_field_only_class_still_returns_source` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_real_builtin_config_class` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_section_omitted_when_excerpt_empty` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_truncates_when_over_limit` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/tune_ml_hyperparam_agent/test_seed_plugin_validation.py`

Tests: 9

| Test function | Verdict | Reason |
|---|---|---|
| `test_directory_path_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_file_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_plugin_model_type_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_model_type_mismatch_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_none_is_ok` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_plugin_model_type_non_string_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_syntax_error_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_valid_plugin_passes` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_validator_does_not_import_the_plugin` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/tune_ml_hyperparam_agent/test_silent_train_crash_routing.py`

Tests: 4

| Test function | Verdict | Reason |
|---|---|---|
| `test_cuda_oom_routes_to_error_inference_oom_not_training` | Delete | Mock-positive; file flagged in ledger §6.4 for outright deletion |
| `test_inference_error_with_training_prefix_routes_to_error_training` | Delete | Mock-positive; file flagged in ledger §6.4 for outright deletion |
| `test_plain_inference_error_routes_to_error_inference` | Delete | Mock-positive; file flagged in ledger §6.4 for outright deletion |
| `test_silent_crash_record_carries_actionable_memory` | Delete | Mock-positive; file flagged in ledger §6.4 for outright deletion |

### `tests/unit/agent/tune_ml_hyperparam_agent/test_time_calibration.py`

Tests: 29

| Test function | Verdict | Reason |
|---|---|---|
| `test_calibration_dir_default` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_calibration_dir_env_override` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_calibration_path_uses_slugged_filename` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_detect_drift_only_inspects_last_n_entries` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_detect_drift_returns_none_when_history_short` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_detect_drift_returns_none_when_not_all_violated` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_detect_drift_warns_on_n_consecutive_violations` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_gpu_slug_is_deterministic` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_gpu_slug_lowercase_and_safe` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_load_table_defensive_against_corrupt_json` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_load_table_fills_missing_keys` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_load_table_returns_empty_when_missing` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_lookup_k_exact_match_wins` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_lookup_k_falls_back_to_wildcard` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_lookup_k_handles_missing_k_values_key` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_lookup_k_returns_one_when_neither_present` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_make_entry_estimate_not_violated_when_under_budget` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_make_entry_handles_zero_warmup_safely` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_make_entry_shape_and_ratio` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_save_is_atomic_no_tmp_left_behind` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_save_then_load_round_trip` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_update_k_appends_to_history` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_update_k_asymmetry_corrects_under_prediction_faster` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_update_k_clips_to_kmax` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_update_k_clips_to_kmin` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_update_k_falls_back_to_wildcard_when_model_unseen` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_update_k_starts_from_one_when_no_prior` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_update_k_uses_alpha_down_when_not_violated` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_update_k_uses_alpha_up_when_violated` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/tune_ml_hyperparam_agent/test_tuning_agent.py`

Tests: 66

| Test function | Verdict | Reason |
|---|---|---|
| `test_all_records_included` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Move to integration suite — entire file tests orchestration + I/O. Mocks prevent" |
| `test_best_and_formal_score_tables_in_output` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_best_config_present` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_best_score_extracted` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_build_score_table_failure_is_fault_tolerant` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_completed_status` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_copy_overwrites_existing_destination` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_copy_places_file_in_dst_dir` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_copy_preserves_contents` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_copy_same_file_is_noop` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_empty_expert_advice` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_empty_string_passthrough` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_error_status_does_not_skip_silently` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_evaluate_vram_skill_receives_hardware_context` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_feasible_proceeds_to_training` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_final_round_always_formal` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_formal_mode_round_picks_formal_budget` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_formal_mode_round_picks_formal_vram_budget` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_formal_round_builds_two_sample_sets` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_formal_round_with_only_trial_budget_skips_gate` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_full_expert_advice` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_infeasible_emits_skipped_record` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_inference_receives_eval_sample_set` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_inference_skill_receives_inference_batch_from_resource_check` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_invalid_trial_fields_fallback` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_legacy_inference_result_writes_safe_defaults` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_model_type_in_output` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_none_budget_passes_none_to_skill` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_none_budget_skips_skill_entirely` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_oom_record_has_expert_advice` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_oom_records_saved` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_output_file_written` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Move to integration suite — entire file tests orchestration + I/O. Mocks prevent" |
| `test_output_validates_against_schema` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_partial_expert_advice` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_partial_status_on_all_oom` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_populated_timings_aggregate_into_memory` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_reflection_context_includes_markdown` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_returns_valid_output` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_round_context_passed_to_plan` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_run_config_file_written` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_run_name_in_output` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_score_table_attached_to_record` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_score_table_md_picks_highest_scoring_record` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_score_table_md_threaded_to_brain_plan` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_score_table_none_on_legacy_path` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_skill_receives_budget_and_data_dir` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_skipped_oom_risk_record_carries_vram_fields` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_skipped_oom_risk_record_omits_vram_fields_when_disabled` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_skipped_record_carries_suggestion` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_skipped_time_risk_record_carries_time_fields` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_string_expert_advice_passed_to_plan` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_string_passthrough` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_structured_expert_advice_serialized` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_success_record_memory_carries_time_fields_formal` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_success_record_memory_carries_vram_fields_formal` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_success_record_memory_time_mode_trial` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_success_record_memory_vram_fields_trial_mode` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_success_record_omits_time_fields_when_gate_disabled` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_success_record_omits_vram_fields_when_gate_disabled` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_timing_fields_present` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_trial_allowed_false_forces_formal` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_trial_config_written` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_trial_mode_round_picks_trial_budget` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_trial_mode_round_picks_trial_vram_budget` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_trial_round_with_only_formal_budget_skips_gate` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_vram_fail_short_circuits_time_check` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |

### `tests/unit/agent/tune_ml_hyperparam_agent/test_tuning_cli.py`

Tests: 4

| Test function | Verdict | Reason |
|---|---|---|
| `test_builtin_model_no_seed_proceeds` | Delete | Mock-positive; file flagged in ledger §6.4 for outright deletion |
| `test_plugin_model_with_mismatched_seed_errors` | Delete | Mock-positive; file flagged in ledger §6.4 for outright deletion |
| `test_plugin_model_with_seed_proceeds` | Delete | Mock-positive; file flagged in ledger §6.4 for outright deletion |
| `test_plugin_model_without_seed_errors` | Delete | Mock-positive; file flagged in ledger §6.4 for outright deletion |

### `tests/unit/agent/tune_ml_hyperparam_agent/test_warmup_activation.py`

Tests: 5

| Test function | Verdict | Reason |
|---|---|---|
| `test_static_formula_uses_patched_constants` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_warmup_path_entered_with_valid_data_dir` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_warmup_skipped_when_data_dir_does_not_exist` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_warmup_skipped_when_data_dir_is_empty_string` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_warmup_skipped_when_data_dir_is_none` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/utils/test_architectural_pattern_tagger.py`

Tests: 19

| Test function | Verdict | Reason |
|---|---|---|
| `test_all_four_windowing_keys_suppress_dense_attention_tag` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_architectural_patterns_has_no_orphan_descriptions` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_empty_model_type_returns_empty` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_every_emitted_tag_has_an_english_description` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_iter2_selective_scan_gets_scan_over_T` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_iter3_gru_stack_gets_recurrent_over_T` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_iter4_fourier_tcn_gets_no_tags` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_model_matching_multiple_patterns_gets_all_tags_sorted` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_none_model_config_is_handled_gracefully` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_none_model_type_is_handled_gracefully` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_output_is_deterministic_across_calls` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_recurrent_config_key_alone_triggers_tag_even_if_name_hides_it` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_ssm_key_alone_does_not_trigger_scan_tag` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_state_dim_alone_does_not_trigger_scan_tag` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_state_dim_plus_ssm_key_triggers_scan_tag` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_thresholds_are_the_documented_v1_values` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_transformer_with_window_is_not_flagged` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_transformer_without_window_gets_dense_attention_over_T` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_unknown_model_type_with_no_matching_keys_returns_empty` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent/utils/test_proposer_preflight.py`

Tests: 20

| Test function | Verdict | Reason |
|---|---|---|
| `test_default_sample_set_has_non_empty_per_file_segments` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_default_sample_set_has_twenty_files` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_default_sample_set_is_deterministic` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_estimate_proposal_time_respects_trial_portion` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_estimate_runs_without_sample_set_argument` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_factor_matches_estimated_over_budget` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_factor_monotonic_in_epochs` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_factor_monotonic_in_num_params` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_invented_model_type_does_not_raise` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_iter2_style_overshoot_flagged_infeasible` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_iter4_style_tcn_passes_feasibility` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_negative_num_params_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_negative_time_budget_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_no_cuda_probe_via_wrapper` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_returns_four_documented_keys` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_runs_without_data_dir` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_trial_portion_kwarg_scales_default_sample_set` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_verdict_reflects_feasibility` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_zero_num_params_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_zero_time_budget_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/agent_generated/test_stub_plugin_template_loads.py`

Tests: 5

| Test function | Verdict | Reason |
|---|---|---|
| `test_config_class_is_pydantic_basemodel_and_instantiates_with_defaults` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_forward_shape_contract` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_plugin_model_type_is_stub_arch` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_template_exposes_three_plugin_symbols` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_template_file_exists` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/core/test_hardware_context.py`

Tests: 10

| Test function | Verdict | Reason |
|---|---|---|
| `test_cpu_stub_cap_is_zero` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_discover_on_cpu_only_host` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_discover_on_fake_a100_40gb_same_code` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_discover_on_fake_a100_80gb_same_code` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_discover_on_fake_rtx_5090` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_discover_timestamp_is_fresh` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_schema_is_frozen` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_total_memory_gb_conversion` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_usable_cap_bytes_is_exactly_safety_fraction_of_total` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_usable_cap_rescales_without_code_change` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/core/test_inference_defaults.py`

Tests: 7

| Test function | Verdict | Reason |
|---|---|---|
| `test_empty_string_returns_default` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_error_message_names_the_model_type` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_error_message_points_to_defaults_file` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_known_model_types_do_not_raise` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_known_model_types_return_table_values` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_unknown_model_type_raises_value_error` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_unknown_model_type_returns_default` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/core/test_manifest_io.py`

Tests: 11

| Test function | Verdict | Reason |
|---|---|---|
| `test_get_or_create_creates_missing_manifest` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_get_or_create_regenerates_on_corrupt_manifest` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_get_or_create_regenerates_on_device_mismatch` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_get_or_create_regenerates_on_hostname_mismatch` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_get_or_create_regenerates_on_schema_mismatch` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_get_or_create_reuses_matching_manifest_without_rewrite` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_load_manifest_raises_on_missing_fields` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_load_manifest_roundtrip_preserves_all_fields` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_write_manifest_creates_parents` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_write_manifest_is_valid_json` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_write_manifest_trailing_newline` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/core/test_resume.py`

Tests: 62

| Test function | Verdict | Reason |
|---|---|---|
| `test_accumulates_findings_chronologically` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_collects_gate_exhaustions_chronologically` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_collects_rejections_chronologically` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_current_iter_1_does_not_require_existing_workspace` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_current_iter_1_returns_seeds_verbatim` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_current_iter_below_one_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_drops_malformed_vocab_entries_with_warning` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_empty_committed_iters_returns_empty` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_explicit_empty_overwrites` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_gate_exhaustions_capped_at_K10` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_interpretation_path_uses_chain_wide_iter_dir_name_for_iter_above_1` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_invalid_plugin_file_warns_and_continues` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_iter1_leaves_cache_empty` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_iter1_leaves_negative_feedback_empty` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_iter1_leaves_new_fields_empty` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_iter1_leaves_proposal_field_none` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_iter1_returns_empty` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_iter1_returns_empty_dict` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_iter_dir_entirely_missing_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_iter_with_no_rejections_contributes_nothing` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_iter_with_none_gate_exhaustion_skipped` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_legacy_digest_without_cache_key_skipped` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_load_latest_proposal_glob_walks_attempt_dirs` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_load_latest_proposal_latest_committed_wins` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_load_latest_proposal_malformed_warns_and_skips` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_load_latest_proposal_no_committed_iters_returns_none` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_malformed_manifest_json_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_malformed_run_output_json_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_manifest_without_output_path_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_manifest_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_plugin_file_warns_and_continues` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_no_records_iter_does_not_break_accumulation` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_partial_restore_when_current_iter_in_middle` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_picks_latest_cache` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_picks_latest_runtime_vocab` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_plugin_dir_layout_uses_get_plugin_dir_helper` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_populates_cache_from_latest_iter` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_populates_new_fields_from_prior_iters` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_populates_previous_proposal_data_from_latest_iter` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_proposal_field_none_when_no_proposal_files_exist` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_proposal_path_returns_none_when_iteration_dir_missing` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_proposal_path_returns_none_when_no_attempt_dir` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_proposal_path_uses_chain_wide_iter_dir_name_for_iter_above_1` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_registry_actually_populated` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_rejections_capped_at_K10_most_recent_wins` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_resolved_paths_are_seeds_then_chronological` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_restored_plugins_in_chronological_order` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_restores_all_prior_iters` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_returns_defensive_copy` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_run_output_file_missing_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_run_output_validation_error_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_seeds_empty_list_works` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_seen_in_runs_preserved_verbatim` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_skips_malformed_json_with_warning` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_skips_missing_digest_with_warning` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_some_plugins_present_some_missing_partial_restore` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_status_failed_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_status_no_records_interleaved_with_completed` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_status_no_records_skips_cleanly` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_status_partial_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_two_iter_pseudo_run_repopulates_model_registry` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_workspace_does_not_exist_raises_for_iter_above_1` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/core/test_sandbox_executor.py`

Tests: 30

| Test function | Verdict | Reason |
|---|---|---|
| `test_default_is_false` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_distinct_run_names_distinct_dirs` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_explicit_beats_registry_on_known_type` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_explicit_inference_batch_is_used` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_failure_path_returns_uniform_keys` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_layout_matches_doc` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_matches_sandbox_plugin_dir` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_no_plugin_dir_leaves_env_var_unset` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_none_falls_back_to_registry` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_normal_mode_omits_timing_flag` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_omitted_kwarg_falls_back_to_registry` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_plugin_dir_created_under_workspace` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_plugin_dir_does_not_clobber_pythonpath` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_plugin_dir_populates_env_var` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_progress_bar_false_captures_stdout` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_progress_bar_true_streams_stdout` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_returncode_zero_no_sentinel_returns_error_training` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_returns_absolute_path` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_sentinel_present_keeps_success_status` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_set_false` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_set_true` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_silent_crash_does_not_read_train_results_json` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_silent_crash_message_includes_stderr_tail` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_stderr_always_captured` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_stderr_always_captured_with_progress` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_success_returns_per_file_timings_and_decomposed_wall` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_success_with_missing_sidecar_returns_empty_timings` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_training_subprocess_receives_plugin_dir_in_env` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_trial_mode_appends_timing_flag` | Move to integration | Mock-positive (fixture-/patch-based); file flagged in ledger §6.1 for full integration move |
| `test_two_sandboxes_get_distinct_plugin_dirs` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/core/test_sandbox_rlimit.py`

Tests: 37

| Test function | Verdict | Reason |
|---|---|---|
| `test_bare_out_of_memory_error_not_oom` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_callable_applies_setrlimit` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_empty_error_not_oom` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_env_negative_falls_back_to_role_default` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_env_non_numeric_falls_back_to_role_default` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_env_override_wins_for_every_role` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_env_zero_disables_for_every_role` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_env_zero_disables_preexec` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_generic_exit_1_not_oom` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_inference_default_is_40` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_inference_memory_error_returns_oom_status` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_inference_passes_preexec_fn` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_inference_uses_inference_role` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_memory_error_in_stderr_is_oom` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_memory_error_stderr_gets_oom_tag` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_memory_error_with_message_is_oom` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_non_oom_failure_has_no_oom_tag` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_qualified_memory_error_still_oom` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_returns_callable_for_positive_gb` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_returns_none_for_negative` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_returns_none_for_zero` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_scoring_default_is_24` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_scoring_memory_error_returns_oom_status` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_scoring_passes_preexec_fn` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_scoring_uses_scoring_role` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_sigkill_gets_oom_tag` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_sigkill_returncode_is_oom` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_sigsegv_not_oom` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_torch_oom_not_tagged_host_ram` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_torch_out_of_memory_error_not_oom` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_training_default_is_40` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_training_memory_error_returns_oom_status` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_training_non_oom_still_error` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_training_passes_preexec_fn` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_training_sigkill_returns_oom_status` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_training_uses_training_role` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_unknown_role_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/core/test_server_configs.py`

Tests: 8

| Test function | Verdict | Reason |
|---|---|---|
| `test_defaults_to_current_hostname` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_frozen` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_ligroup_returns_measured_config` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_rejects_empty_hostname` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_rejects_extra_fields` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_rejects_nonpositive_per_segment` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_unknown_host_falls_back_to_ligroup` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_unknown_host_warns_only_once` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/core/test_storage.py`

Tests: 11

| Test function | Verdict | Reason |
|---|---|---|
| `test_custom_schema_and_run_name` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_default_backend_is_local` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_default_run_name` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_invalid_backend_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_local_sub_config_is_optional` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_connection_string_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_workspace_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_nested_dict_construction` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_valid` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_valid_local` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_valid_postgres_placeholder` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/core/test_stub_sandbox.py`

Tests: 9

| Test function | Verdict | Reason |
|---|---|---|
| `test_denoising_score_within_bounds` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_determinism_same_run_id_yields_same_stream` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_execute_inference_returns_schema_valid_success` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_execute_scoring_records_validate_against_experiment_record` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_execute_training_returns_schema_valid_success` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_save_record_persists_pseudo_origin_marker_to_disk` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_save_record_stamps_pseudo_origin_and_mirrors_in_memory` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_score_vector_returns_synthetic_four_tuple` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_set_run_context_reseeds_for_distinct_run_ids` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/core/test_workspace_layout_guard.py`

Tests: 8

| Test function | Verdict | Reason |
|---|---|---|
| `test_clean_chain_layout_passes` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_empty_workspace_passes` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_error_message_contains_migration_hint` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_legacy_pattern1_iteration_subtree` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_legacy_pattern2_workflow_json` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_legacy_pattern3_trace_without_iter_001` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_nonexistent_workspace_passes` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_trace_with_iter_001_passes` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/dashboard/test_local_json.py`

Tests: 32

| Test function | Verdict | Reason |
|---|---|---|
| `test_agent_run_excludes_seeded_baseline` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_agent_run_total_count` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_baseline_returns_one_record` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_baseline_score` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_best_agent_score` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_best_run_name` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_entry_has_required_fields` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_existing_dir_is_healthy` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_list_models_auto_discovers` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_list_models_filters_missing_dirs` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_list_models_respects_explicit_list` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_list_runs_includes_agent_run` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_list_runs_includes_baseline` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_list_runs_no_agent_run` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_list_runs_unknown_model_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_dir_is_unhealthy` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_no_agent_run_best_score_is_none` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_pagination_limit` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_pagination_offset` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_rank_starts_at_one` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_returns_correct_record` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_returns_ranked_entries` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_runs_list` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_skipped_oom_excluded_by_default` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_status_counts` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_status_filter_oom` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_status_filter_success_only` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_top_n_respected` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_total_experiments_excludes_seeded_baseline` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_unknown_exp_id_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_unknown_model_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_unknown_run_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/dashboard/test_settings.py`

Tests: 12

| Test function | Verdict | Reason |
|---|---|---|
| `test_cache_clear_reloads` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_data_source_type` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_default_data_source_is_local` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_default_port_is_8000` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_default_refresh_interval` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_empty_yaml_uses_all_defaults` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_get_settings_returns_same_instance` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_invalid_data_source_type_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_invalid_log_level_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_file_returns_defaults` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_only_port_overridden` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_postgres_type_parsed` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/execute_tools/test_build_anchor_map.py`

Tests: 11

| Test function | Verdict | Reason |
|---|---|---|
| `test_anchors_has_20_files` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_anchors_keys_are_strings` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_each_file_has_200_segments` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_num_files` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_returns_correct_structure` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_round_trip` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_s_max_is_global_maximum` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_segment_length` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_segments_per_file` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_snr_values_are_correct` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_total_compute_calls` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |

### `tests/unit/execute_tools/test_dataset_config.py`

Tests: 6

| Test function | Verdict | Reason |
|---|---|---|
| `test_empty_when_window_excludes_all_divisors` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_excludes_invalid_powers_of_two_for_tidmad` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_includes_known_valid_values_for_tidmad` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_respects_lo_hi_bounds` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_returns_sorted_divisors_within_default_window` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_works_for_arbitrary_dataset` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/execute_tools/test_inference_single.py`

Tests: 11

| Test function | Verdict | Reason |
|---|---|---|
| `test_canonical_del_block_runs_before_create_abra_file` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_canonical_del_includes_view_aliasing_handles` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_gc_collect_follows_canonical_del` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_message_includes_no_retry_language` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_sentinel_raises_error_training` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_per_file_timings_list_appended` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_sentinel_path_is_sibling_of_model_path` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_sentinel_present_returns_none` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_sidecar_written_when_flag_set` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_timing_out_json_flag_registered` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_trial_loop_brackets_each_iteration_with_perf_counter` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/execute_tools/test_phase67_scoring_precision.py`

Tests: 23

| Test function | Verdict | Reason |
|---|---|---|
| `test_finite_floats_pass_through` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_grand_mean_log_is_bit_exact` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_grand_mean_log_matches_python_log` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_min_adjacent_gap_exceeds_noise_floor` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_nan_becomes_none` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_nan_renders_explicit_string` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_neg_inf_becomes_none` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_neg_inf_renders_unicode_minus_infinity` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_negative_finite_renders_unicode_minus` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_negative_grand_mean_returns_neg_inf` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_no_record_lands_exactly_on_old_ghost_score` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_none_passes_through` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_none_renders_n_a` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_pos_inf_becomes_none` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_pos_inf_renders_infinity` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_positive_finite_renders_plain` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_recursive_dict_coercion` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_render_precision_quantizes_at_1e_4` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_round_trip_through_json_dumps_and_loads` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_seven_records_produce_seven_distinct_scalars` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_span_is_physically_meaningful` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_strings_and_ints_pass_through` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_zero_total_returns_neg_inf` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/execute_tools/test_sample_set_builder.py`

Tests: 19

| Test function | Verdict | Reason |
|---|---|---|
| `test_all_20_files_present` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_all_segments_included` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_correct_segment_count` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_deduplicates_target_files` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_deterministic_with_seed` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_different_file_index` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_different_seeds_differ` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_empty_target_files_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_full_portion` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_no_duplicate_segments` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_none_target_files_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_only_anchor_files` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_only_target_files` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_returns_single_file` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_segments_are_sorted` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_segments_are_valid` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_tiny_portion_at_least_one_segment` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_trial_fields_ignored` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_unknown_strategy_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/execute_tools/test_score_table_adversarial.py`

Tests: 21

| Test function | Verdict | Reason |
|---|---|---|
| `test_above_baseline_renders_percentage` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_below_baseline_renders_honest_line` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_equal_to_baseline_renders_percentage` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_extra_field_rejected` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_file_index_out_of_bounds_rejected` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_fv_length_19_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_fv_length_21_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_inf_accepted` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_list_rejected` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_llm_string_null_rejected` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_machine_readable_scalars_preserved` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_nan_accepted` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_non_none_scalar_with_empty_fv_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_none_accepted_as_unsampled_marker` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_none_scalar_returns_none` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_num_sampled_files_zero_rejected` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_one_n_a_row_fails_whole_table` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_one_none_row_accepted` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_rows_above_max_length_rejected` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_rows_below_min_length_rejected` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_single_file_sample_works` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/execute_tools/test_scoring_helpers.py`

Tests: 29

| Test function | Verdict | Reason |
|---|---|---|
| `test_aggregate_block_and_recovery` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_aggregate_is_subset_scoped` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_aggregate_matches_on_disk_scalars` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_all_rows_are_always_length_20` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_contains_header_and_columns` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_custom_base_and_offset_kwargs` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_impact_ranking_invariant_under_input_permutation` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_impact_strictly_positive_when_model_below_gt` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_impact_zero_iff_model_at_or_above_gt` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_length_preserved` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_na_cell_rendered_for_unsampled_files` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_negative_input_clamped_then_offset_applied` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_negative_values_use_unicode_minus` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_none_passes_through_for_unsampled_files` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_post_path_a_reference_consistency` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_rejects_all_none_fv_with_non_none_scalar` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_rejects_wrong_length_fv` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_rendered_markdown_attached` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_renders_exactly_20_body_rows` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_returns_none_when_model_scalar_is_none` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_rows_are_fully_populated` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_secondary_block_omitted_when_no_impact_data` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_secondary_block_sorted_by_impact_desc` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_subset_footer_only_appears_when_n_lt_20` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_typical_linear_values_map_correctly` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_unsampled_rows_carry_none_for_model_columns` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_weights_sum_to_one_full_subset` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_weights_sum_to_one_trial_subset` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_zero_maps_to_soft_floor` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/execute_tools/test_scoring_utils.py`

Tests: 17

| Test function | Verdict | Reason |
|---|---|---|
| `test_custom_threshold_forwarded` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_empty_sample_set` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_empty_segments_returns_nan` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_excluded_files_are_none` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_high_anchor_produces_higher_score` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_legacy_mode_derives_s_max_globally_from_collected_pairs` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_multiple_files_grand_mean` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Parameterise SNR values directly into the tested functions rather than mocking; " |
| `test_multiple_segments_averaged` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_no_reference_returns_false_none` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_normal_mode_single_file` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_raises_without_filename_fn` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_raises_without_s_max_in_non_legacy_mode` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_reference_with_collapse_trips_check` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_reference_with_normal_output_passes` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_scalar_is_log_of_grand_mean` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_single_segment` | Review | Mock-positive but not covered by any ledger §6 cluster recommendation; manual review recommended before deletion |
| `test_vector_length_is_20` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Parameterise SNR values directly into the tested functions rather than mocking; " |

### `tests/unit/execute_tools/test_squid_health_checks.py`

Tests: 12

| Test function | Verdict | Reason |
|---|---|---|
| `test_collapse_detected_at_explore_v7_magnitude` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_custom_threshold_overrides_default` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_empty_reference_returns_false_safely` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_failure_reason_includes_actual_and_reference_magnitudes` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_failure_reason_includes_ratio_and_threshold` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_no_file_vector_returns_false_safely` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_no_reference_returns_false_safely` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_none_entries_in_vectors_are_skipped` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_normal_output_passes_through` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_threshold_boundary_exactly_at_1pct_does_not_trip` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_threshold_just_below_trips` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_zero_reference_magnitude_returns_false_safely` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/execute_tools/test_train_sentinel.py`

Tests: 4

| Test function | Verdict | Reason |
|---|---|---|
| `test_sentinel_name_uses_exact_exp_id` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_sentinel_not_written_when_save_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_sentinel_path_is_sibling_of_save_path` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_sentinel_written_on_successful_save` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/guardrails/test_no_hardcoded_device_literals.py`

Tests: 1

| Test function | Verdict | Reason |
|---|---|---|
| `test_no_hardcoded_device_literals` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/guardrails/test_no_model_name_branches.py`

Tests: 1

| Test function | Verdict | Reason |
|---|---|---|
| `test_no_model_name_branches` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/ml_models/test_loss_functions.py`

Tests: 12

| Test function | Verdict | Reason |
|---|---|---|
| `test_ce_computes_on_synthetic_data` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_ce_returns_cross_entropy` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_focal_cw_returns_focal_cw_loss` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_focal_returns_focal_loss` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_none_class_weights_falls_back_gracefully` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_output_is_non_negative` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_output_is_scalar` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_perfect_prediction_lower_than_random` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_reduction_sum_larger_than_mean` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_smooth_l1_computes_on_synthetic_data` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_smooth_l1_returns_smooth_l1_loss` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_unknown_loss_type_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/ml_models/test_model_configs.py`

Tests: 34

| Test function | Verdict | Reason |
|---|---|---|
| `test_ce_nullifies_focal_params` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_dropout_ignored_for_single_layer` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_embedding_dim_divisible_by_nhead_passes` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_embedding_dim_not_divisible_by_nhead_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_even_gate_channels_passes` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_even_kernel_size_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_fcnet_with_ce_passes` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_fcnet_with_smooth_l1_passes` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_focal_cw_valid` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_focal_nullifies_beta` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_hidden_dim_out_of_range_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_negative_latent_dim_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_num_gates_below_min_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_num_layers_below_min_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_odd_gate_channels_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_punet_with_ce_passes` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_punet_with_focal_passes` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_punet_with_smooth_l1_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_rnn_with_ce_passes` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_rnn_with_smooth_l1_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_segmentation_size_at_boundary_passes` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_segmentation_size_too_small_for_depth_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_smooth_l1_nullifies_alpha_and_gamma` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_static_v_length_mismatch_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_transformer_with_ce_passes` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_transformer_with_smooth_l1_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_valid_custom` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_valid_custom_dims` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_valid_default` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_valid_with_static_v` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_wavenet_with_ce_passes` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_wavenet_with_smooth_l1_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_width_below_min_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_zero_latent_dim_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/ml_models/test_model_descriptions.py`

Tests: 7

| Test function | Verdict | Reason |
|---|---|---|
| `test_chain_lookup_is_noop_when_env_var_unset` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_chain_lookup_skips_run_dir_without_matching_model` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_finds_builtin_model_description` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_finds_chain_plugin_with_iter_dirname` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_finds_chain_plugin_with_run_scoped_dirname` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_model_raises_with_searched_paths` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_newest_run_wins_when_model_registered_in_multiple_runs` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/ml_models/test_models_forward.py`

Tests: 16

| Test function | Verdict | Reason |
|---|---|---|
| `test_custom_latent_dims` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_deeper_layers` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_deeper_model` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_more_blocks` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_no_nan_in_output` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_output_is_float` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_output_shape` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_output_shape_classification` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_output_shape_deeper` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_output_shape_depth_2` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_output_shape_depth_3` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_output_shape_narrow` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_output_shape_regression` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_registry_contains_all_builtin_models` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_registry_maps_to_correct_classes` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_with_static_v` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/ml_models/test_plugin_loader.py`

Tests: 22

| Test function | Verdict | Reason |
|---|---|---|
| `test_bare_module_identity_never_created` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_config_instantiates` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_empty_entries_filtered` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_empty_env_falls_back_to_agent_generated_dir` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_env_unset_falls_back_to_agent_generated_dir` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_env_var_overrides_legacy_dir` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_forward_no_nan` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_forward_output_is_float` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_forward_output_shape_matches_core_contract` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_config_class_returns_none` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_directory_returns_empty` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_env_dir_silently_skipped` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_legacy_dir_ok_when_env_set` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_model_type_returns_none` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_model_instantiates` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_multiple_dirs_preserve_order` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_plugin_added_to_both_registries` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_single_dir` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_syntax_error_returns_none` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_two_dirs_both_loaded` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_underscore_files_are_skipped` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_valid_plugin_returns_dict` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/nodes/test_scoring_reference.py`

Tests: 11

| Test function | Verdict | Reason |
|---|---|---|
| `test_cache_reset_restores_fresh_load` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_cache_returns_same_object` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_legacy_gt_per_file_without_n_segments_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_legacy_raw_per_file_without_linear_sum_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_gt_per_file_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_gt_scalar_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_raw_per_file_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_raw_scalar_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_returns_reference_scores_with_correct_shapes` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_smax_mismatch_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_values_align_with_index` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/scripts/test_chain_consistency.py`

Tests: 14

| Test function | Verdict | Reason |
|---|---|---|
| `test_budget_variables_present` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_build_app_args_uses_start_iteration` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_data_dir_present` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_exploration_mode_default` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_lilab_dry_run_leaves_workspace_untouched` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_lilab_three_iters_emits_correct_start_iteration` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_max_rounds_default` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_minimum_boldness_default` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_sdsc_dry_run_leaves_workspace_untouched` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_sdsc_emits_afterany_dependency_for_iter_two_and_three` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_shell_arms_exist_for_every_contract_flag` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_shell_default_block_contains_every_var` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_shell_python_default_parity` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_shell_python_type_parity` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/scripts/test_chain_run_id_sidecar.py`

Tests: 6

| Test function | Verdict | Reason |
|---|---|---|
| `test_distinct_run_names_in_distinct_workspaces_produce_distinct_ids` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_empty_sidecar_is_treated_as_missing` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_fresh_workspace_generates_id_with_expected_shape` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_run_name_in_subsequent_call_is_ignored` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_second_call_returns_same_id` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_workspace_is_created_if_missing` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/scripts/test_chain_wrapper_run_name.py`

Tests: 3

| Test function | Verdict | Reason |
|---|---|---|
| `test_run_name_distinct_from_workspace_basename` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_run_name_required_when_missing` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_run_name_threads_through_to_runner_args` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/scripts/test_inspect_run_state.py`

Tests: 14

| Test function | Verdict | Reason |
|---|---|---|
| `test_1_chain_three_clean_iters_next_iter_prints_4` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_2_chain_two_clean_one_missing_manifest_next_iter_prints_3` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_3_chain_one_clean_one_failed_manifest_next_iter_prints_2` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_4_chain_one_clean_one_malformed_json_next_iter_prints_2` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_5_chain_empty_workspace_next_iter_prints_1` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_6_chain_non_contiguous_gap_exits_nonzero` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_7_chain_legacy_layout_guard_rejects` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_8_run_layout_back_compat_renders_table` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_9_default_layout_resolves_to_run` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_chain_dangling_warning_in_human_view` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_chain_human_view_includes_model_and_best_score` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_chain_invalid_arg_combinations_rejected` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_chain_no_dangling_warning_when_partial_is_at_top` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_chain_partial_below_committed_advances_past_max_committed` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/scripts/test_portion_floor.py`

Tests: 9

| Test function | Verdict | Reason |
|---|---|---|
| `test_floor_accepts_exactly_one_pct` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_floor_accepts_typical_values` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_floor_rejects_above_one` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_floor_rejects_just_below` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_floor_rejects_non_numeric` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_floor_rejects_zero_and_negative` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_roi_argparse_rejects_subfloor_eval_portion` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_roi_argparse_rejects_subfloor_trial_portion` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_validator_name_is_portion_floor` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/sdsc_submission_scripts/test_consecutive_failure_brake.py`

Tests: 10

| Test function | Verdict | Reason |
|---|---|---|
| `test_empty_workspace_does_not_trip_brake` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_halt_marker_absent` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_halt_marker_present` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_malformed_manifest_treated_as_not_failed` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_manifest_treated_as_not_failed` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_mixed_statuses_do_not_trip_brake` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_recent_completed_breaks_failure_streak` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_recent_no_records_does_not_count_as_failure` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_single_failure_with_max_failed_one_trips_brake` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_three_consecutive_failed_trips_brake` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/sdsc_submission_scripts/test_run_one_iteration.py`

Tests: 34

| Test function | Verdict | Reason |
|---|---|---|
| `test_both_flags_supplied_is_an_error` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_both_flags_swap_both_factories_and_warn_on_stderr` | Refactor | Mock-positive; ledger §6.2 says convert node mocks to typed stubs |
| `test_chain_banner_omitted_for_iter_1` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_chain_banner_printed_when_priors_restored` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_chain_continues_past_no_records_iter` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_corrupt_prior_iter_aborts_with_clear_error` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_default_args_pass_no_factories` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_human_advice_cli_overrides_file` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_human_advice_file_is_loaded` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_is_pseudo_llm_swaps_bridge_only` | Refactor | Mock-positive; ledger §6.2 says convert node mocks to typed stubs |
| `test_is_pseudo_training_swaps_sandbox_only` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_legacy_iteration_alias_still_drives_restore` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_legacy_iteration_alias_works_with_deprecation_warning` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_legacy_source_paths_alias_works_with_deprecation_warning` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_main_empty_results_exits_zero_and_writes_no_records` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_main_workflow_exception_still_exits_one` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_manual_override_start_iteration_3_with_iters_1_and_2_on_disk` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_max_epochs_negative_is_rejected` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_max_epochs_zero_is_rejected` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_iter_1_plugin_warns_but_iteration_runs` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_neither_flag_supplied_is_an_error` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_plan_overrides_default_none` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_plan_overrides_json_string_becomes_dict` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_seed_paths_and_source_paths_both_supplied_is_an_error` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_seed_paths_is_required` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_start_iteration_1_passes_seeds_through_unchanged` | Delete | Named in ledger §4 flag table; verdict from recipe: "Merge into run_workflow tests or delete; the circular dependency (mock the exact" |
| `test_start_iteration_2_restores_iter_1_plugin_and_prepends_path` | Delete | Named in ledger §4 flag table; verdict from recipe: "Merge into run_workflow tests or delete; the circular dependency (mock the exact" |
| `test_start_iteration_below_one_is_an_error` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_start_iteration_canonical_path` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_workspace_is_required` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_write_manifest_completed_path_unchanged` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_write_manifest_crashed_forces_failed_regardless_of_results` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_write_manifest_empty_results_emits_no_records` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_write_manifest_results_with_none_score_emits_no_records` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/test_compute_ground_truth.py`

Tests: 8

| Test function | Verdict | Reason |
|---|---|---|
| `test_all_zero_anchors_returns_soft_floor` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_hand_computed_scalar` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_log_base_is_5_27` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_nonuniform_files_grand_mean_differs_from_simple_mean` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_per_file_agrees_with_file_vector` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_uniform_files_grand_mean_equals_simple_mean` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_uses_global_smax_not_local_max` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_weak_signal_is_not_collapsed_to_ghost_score` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/test_compute_raw_baseline.py`

Tests: 9

| Test function | Verdict | Reason |
|---|---|---|
| `test_coarse_stride_uses_20_segments` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_coarse_uses_same_global_s_max` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_fine_calls_process_segment_200_times` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_grand_mean_weights_by_n_segments` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_hand_computed_scalar` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_skip_when_any_fine_index_missing` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_skip_when_legacy_json_lacks_new_fields` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_weak_signal_log_score_is_distinct_post_phase67` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_writes_scalar_when_all_20_fine_present` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/tools/test_token_baseline_report.py`

Tests: 18

| Test function | Verdict | Reason |
|---|---|---|
| `test_bloat_alert_fires_above_threshold` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_bloat_alert_silent_below_threshold` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_context_explosion_alert_fires_above_threshold` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_context_explosion_silent_at_threshold` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_corrupted_jsonl_blocks_publication` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_end_to_end_positive_run` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_happy_path_classifier` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_linear_slope_flat_returns_zero` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_linear_slope_handles_missing_iters` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_linear_slope_perfect_line` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_linear_slope_single_point_safe` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_per_label_slopes_skips_missing_iters` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_segmentation_3_row_jsonl` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_skip_lint_bypasses_corruption_block` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_usd_overrides_propagate` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_usd_precision_to_four_decimals` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_usd_zero_when_no_tokens` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_verdict_written_at_top_of_top3_report` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/workflows/test_knowledge_cache_cap.py`

Tests: 6

| Test function | Verdict | Reason |
|---|---|---|
| `test_8_entries_top5_by_score` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_current_model_survives_even_if_worst` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_custom_max_entries` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_exact_limit_no_eviction` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_none_scores_evicted_first` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_under_limit_no_eviction` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/workflows/test_llm_config.py`

Tests: 24

| Test function | Verdict | Reason |
|---|---|---|
| `test_cross_provider_nested_config_loads` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_default_all_slots_none` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_defaults` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_empty_dict_loads_with_both_defaults` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_explicit_cross_provider` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_explicit_provider_and_model` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_explicit_same_provider_different_models` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_full_nested_config_loads` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_get_flattens_tune_into_4_keys` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_get_returns_empty_dict_for_unset_slot` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_get_returns_two_keys_for_single_call_agent` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_get_tune_after_uniform_with_overrides` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_get_validate_alias` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_invalid_provider_raises` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_no_reflect_overrides_planner_equals_reflector` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_partial_dict_loads_with_planner_default` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_partial_tune_only_reflector_loads_with_planner_default` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_planner_and_reflector_are_independent_objects` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_reflect_model_id_only_same_provider` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_reflect_provider_and_model_cross_provider` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_reflect_provider_only_no_model_override` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_round_trip_through_json` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_round_trip_via_model_dump_and_validate` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_tune_slot_is_typed_TunerLLMConfig` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/workflows/test_model_exploration.py`

Tests: 61

| Test function | Verdict | Reason |
|---|---|---|
| `test_accepts_source_paths` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Convert node mocks to stubs that satisfy type contracts; test node integration i" |
| `test_all_five_nodes_called` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Convert node mocks to stubs that satisfy type contracts; test node integration i" |
| `test_chained_iterations_via_source_paths` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_classifier_default_routes_correctly` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_converts_multiple_outputs` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_converts_single_output` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_correct_input_types` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Convert node mocks to stubs that satisfy type contracts; test node integration i" |
| `test_creates_dest_dir_if_missing` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_creates_multiple_attempt_dirs` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Convert node mocks to stubs that satisfy type contracts; test node integration i" |
| `test_default_start_iteration_unchanged` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_degenerate_penalty_score_default_is_none` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_degenerate_penalty_score_float_reaches_tuning_input` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_does_not_touch_legacy_global_dir` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_extracts_round_scores` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_fan_in_expert_advice` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Convert node mocks to stubs that satisfy type contracts; test node integration i" |
| `test_feeds_previous_failures_to_proposal` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_formal_round_strategy_canonical_hybrid_params_reaches_tuning_input` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_formal_round_strategy_canonical_independent_reaches_tuning_input` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_formal_round_strategy_default_full_clone` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_formal_round_strategy_legacy_alias_canonicalised` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_formal_round_strategy_legacy_inherit_best_trial_canonicalised` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_four_iteration_deque_evicts_oldest` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_iter1_proposal_has_empty_recent_gate_exhaustions` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_iter2_proposal_no_gate_exhaustion_when_iter1_succeeded` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_iter2_proposal_receives_iter1_gate_exhaustion` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_iteration_directory_created` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_knowledge_cache_grows_across_iterations` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Convert node mocks to stubs that satisfy type contracts; test node integration i" |
| `test_legacy_api_uses_new_function_internally` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_loads_heterogeneous_paths` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_loads_multiple_model_types` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_loads_single_path` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_loads_valid_json` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_no_bare_module_identity_after_package_refactor` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_no_restored_cache_preserves_legacy_empty_init` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_preserves_best_score` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_raises_on_invalid_json` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_raises_on_missing_path` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_raises_when_model_missing` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_raises_when_no_outputs_found` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_raises_when_no_source_provided` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_register_plugin_populates_all_four_surfaces` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_regressor_routes_via_get_output_type` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_restored_model_knowledge_cache_defensive_copy` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_restored_model_knowledge_cache_seeds_first_iter` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_retries_on_validation_failure` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Convert node mocks to stubs that satisfy type contracts; test node integration i" |
| `test_returns_list_with_one_output` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Convert node mocks to stubs that satisfy type contracts; test node integration i" |
| `test_returns_model_type_on_success` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_returns_none_on_invalid_plugin` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_runs_multiple_iterations` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_signature_accepts_degenerate_penalty_score` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_signature_accepts_formal_round_strategy` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_skips_when_source_plugin_missing` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_start_iteration_offsets_loop` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Convert node mocks to stubs that satisfy type contracts; test node integration i" |
| `test_start_iteration_with_multi_iter` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_stops_after_max_proposal_attempts` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_stops_on_target_score` | Move to integration | Named in ledger §4 flag table; verdict from recipe: "Convert node mocks to stubs that satisfy type contracts; test node integration i" |
| `test_updates_model_registry` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_updates_packaged_config_registry` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_workflow_summary_saved` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_writes_description_into_supplied_dest` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_writes_plugin_into_supplied_dest` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/workflows/test_render_physical_rejection.py`

Tests: 15

| Test function | Verdict | Reason |
|---|---|---|
| `test_attempted_config_and_suggestion_rendered` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_dominant_layer_line_present_when_named` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_dominant_layer_line_suppressed_when_empty` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_empty_input_is_noop` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_empty_suggestion_is_suppressed` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_groups_by_model_type` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_missing_model_type_treated_as_unknown_group` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_picks_worst_by_ratio_within_group` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_pluralization_with_multiple_rejections` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_reports_overshoot_and_budget` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_single_rejection_returns_one_group` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_singular_phrasing_with_one_rejection` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_tag_and_model_type_in_header` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_ties_broken_by_dominant_fraction` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_zero_budget_treated_as_infinite_ratio` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |

### `tests/unit/workflows/test_vram_auto_shrink_logic.py`

Tests: 9

| Test function | Verdict | Reason |
|---|---|---|
| `test_failed_status_is_false` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_multiple_rejections_disable_auto_shrink_flag` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_non_empty_rejections_with_success_resolves_to_rejection_path` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_none_iter1_tuning_is_false` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_one_rejection_disables_auto_shrink_flag` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_predicate_returns_true_for_at_least_one_schema_valid_status` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_rejection_overrides_even_with_failed_status` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_success_status_with_no_score_is_false` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
| `test_zero_rejections_plus_success_status_plus_score_yields_true` | Keep | Static scan clean: no LLM/mock symbol in body, params, or in-scope fixtures |
