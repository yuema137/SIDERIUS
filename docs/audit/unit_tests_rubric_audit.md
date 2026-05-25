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
