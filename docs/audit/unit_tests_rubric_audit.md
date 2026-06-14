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
## Supplemental classification (per-source-read pass)

**Completed:** 2026-05-26

This section closes the per-test gap by reading every test's actual source code. The prior "Option 3" pass used a fixture-aware AST static scanner plus file-level recipe propagation from §6 — a heuristic which produced wrong verdicts at scale (e.g. `test_force_formal_round.py` had 6 pure plan-mutation tests marked "Delete" because the §4 recipe text *"Delete the mocked tests, keep the pure plan-mutation tests"* was captured by a `'delete' in recipe` substring match). This pass was redone with 8 parallel general-purpose subagents, each reading the full body, decorators, fixture parameters, and conftest chain of every test in its slice.

### Methodology

- 136 test files / 2419 tests on disk partitioned into 8 balanced slices (~17 files / ~310 tests per slice) by greedy bin-packing on test count.
- Each slice dispatched to a `general-purpose` subagent (Tools: `*`, including `Write`) with these per-test requirements: read the full function body, all decorators (`@patch`, `@pytest.mark.*`, fixture params), all fixtures in scope (local + parent conftest.py), and the file's module-level imports. No file-level verdict inheritance, no name-based inference.
- Each subagent wrote its verdict table to `/tmp/slice_N_verdicts.md` before returning — verbal summaries were not accepted.
- Reasons must cite concrete code from the actual test body (e.g. `assert result == mock_llm.return_value`), not generic phrases like "uses mocks".
- 5 tests dropped by one subagent's output were classified manually (each test's source body read individually): all 5 verdict Keep.

### Verdict rubric

- **Delete** — assertions are entirely on a mock's own return value (circular), or verify something already enforced by ruff/pyright. No deterministic logic lost by deletion.
- **Refactor** — contains genuine deterministic logic wrapped in unnecessary mock scaffolding; after removing mocks a meaningful non-circular assertion would remain.
- **Move to integration** — entire purpose is to verify behavior requiring a real external call (real LLM, DB, network) with no deterministic logic worth preserving as a unit test. Rare.
- **Keep** — default. Deterministic side-effect-free logic; mocks are minimal and assertions are on real business logic, not the mock's return.
- **Review** — genuinely uncertain after reading full body.

Tie-break: when in doubt between Delete↔Keep → Keep. Between Move-to-integration↔anything → Keep or Refactor.

### Verdict tally

| Verdict | Count | % of total |
|---|---|---|
| Keep | 2417 | 99.9% |
| Refactor | 2 | 0.1% |
| Move to integration | 0 | 0.0% |
| Delete | 0 | 0.0% |
| Review | 0 | 0.0% |
| **Total** | **2419** | 100.0% |

### Overturn vs. prior heuristic pass

The prior supplemental classification (now replaced) judged 2419 tests as Keep 1957 / Move-to-integration 302 / Review 87 / Refactor 57 / Delete 16. After reading each test body individually, the matrix collapses almost entirely to Keep — confirming the prior pass over-flagged based on file-level cluster recipes rather than per-test behavior.

- **Unchanged verdicts:** 1957
- **Overturned verdicts:** 462

| Prior verdict | → | New verdict | Count |
|---|---|---|---|
| Move to integration | → | Keep | 300 |
| Review | → | Keep | 87 |
| Refactor | → | Keep | 57 |
| Delete | → | Keep | 16 |
| Move to integration | → | Refactor | 2 |

### Non-Keep verdicts (full list)

All 2419 tests verdict Keep except the following 2 Refactor cases:

| File | Test | Verdict | Reason |
|---|---|---|---|
| `tests/unit/agent/ml_model_implementor/test_implementor_agent.py` | `test_generate_text_called_once` | Refactor | `agent_with_mocks.bridge.generate_text.assert_called_once()` — assertion is only on the mock's own call count; the logic under test (that generate_text is called exactly once) is real but the sole assertion is a mock-call count with no content verification |
| `tests/unit/agent/ml_model_implementor/test_implementor_agent.py` | `test_generate_called_once` | Refactor | `agent_with_mocks.bridge.generate.assert_called_once()` — assertion is only on mock call count; same issue as test_generate_text_called_once |

---

## Per-file verdicts

One H3 section per test file. Reasons are concrete and cite actual code from the test body. Files with all-Keep verdicts and unanimous "pure logic" rationale are abbreviated in the per-file tables for brevity but every test row remains present.

### `tests/unit/agent/cache/test_cache_consolidator.py`

Tests: 29

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_both_lists_empty_makes_no_llm_call` | Keep | `assert bridge.call_count == 0` with `MockBridge(responses=[])` and `consolidate(bridge, prior=prior, new_llm_response=_empty_new_response(), ...)` — tests that the fast-path bypasses LLM entirely; mock is not circular, assertion is on real side-effect count of deterministic l... |
| `test_cache_hit_merge_low_similarity_preserves_both_findings` | Keep | `assert "VRAM spike at 16 GB" in statements` and `assert "model OOMs at 18 GB on long sequences" in statements` — regression for the verbatim-copy bug that would have dropped the iter-2 finding |
| `test_consolidate_bridge_call_count_zero_when_both_lists_empty` | Keep | `assert bridge.call_count == 0` — short-circuit to zero calls under empty inputs; cost bound guard |
| `test_consolidate_calls_bridge_at_most_twice_per_invocation` | Keep | `assert bridge.call_count == 2` and `assert all(label == "cache_consolidator.list_merge" for label in labels)` — verifies that narrative/error_sig paths never touch bridge; not circular, tests call budget enforcement |
| `test_dedupe_is_pure_no_bridge_argument` | Keep | `assert "bridge" not in sig_params` via `inspect.signature(_dedupe_error_signatures).parameters` — structural contract ensuring LLM can never accidentally be wired into forensic dedup |
| `test_dedupe_preserves_thirty_distinct_signatures` | Keep | `assert len(merged) == 30` — Gate G3 at scale; verifies no numerical cap is applied even for 30 distinct signatures |
| `test_dedupe_preserves_twelve_distinct_signatures` | Keep | `assert len(merged) == 12` for 12 distinct `(error_type, failure_class, top_frame)` tuples — Gate G3 invariant, pure deterministic set-merge with no cap |
| `test_dedupe_unions_evidence_iters_for_duplicate_keys` | Keep | `assert merged[0].evidence_iters == [2, 7, 10]` — verifies full union (not max, not concat) of evidence_iters for duplicate key tuples |
| `test_empty_prior_overflow_rank_prunes_without_llm` | Keep | `assert len(merged.key_findings) == LIST_FIELD_MAX_SURVIVORS` and `assert len(overflow) == 4` and `assert all(a["reason"] == "rank_prune_cap_no_prior" for a in overflow)` — verifies rank-prune overflow tagging is deterministic and never invokes LLM |
| `test_empty_prior_with_new_statements_wraps_fresh_no_llm_call` | Keep | `assert {f.statement for f in merged.key_findings} == {"finding A", "finding B"}` and `assert all(f.evidence_iters == [5] for f in merged.key_findings)` — verifies fresh-wrap logic correctly sets evidence_iters and strength without LLM; mock's call_count==0 confirms fast-path |
| `test_field_reconciliation_eight_flat_fields_parse_into_cache_entry` | Keep | `assert merged.best_config_analysis.latest == "best config so far is dropout=0.3"` and `assert merged.error_signatures == []` and `assert merged.stats == stats` — verifies all 8 flat LLM response fields parse correctly into CacheEntry; no mock needed |
| `test_llm_oversized_survivors_get_deterministic_overflow_trim` | Keep | `assert len(merged.key_findings) == LIST_FIELD_MAX_SURVIVORS` and `assert len(overflow) == 3` and `all(a.get("reason") == "rank_prune_cap_overflow")` — guards defensive trim when LLM returns too many survivors |
| `test_malformed_llm_response_raises_with_helpful_message` | Keep | `with pytest.raises(RuntimeError, match="malformed merge decision")` when mock returns `{"strength": "extra-strong"}` — validates that Pydantic validation error is caught and re-raised with the correct message |
| `test_merge_narrative_field_has_no_bridge_parameter` | Keep | `assert "bridge" not in params` via `inspect.signature(_merge_narrative_field).parameters` — structural guard that narrative merge can never accidentally trigger an LLM call |
| `test_narrative_empty_new_with_empty_prior_is_noop` | Keep | `assert merged is narr` and `assert archived == []` — identity test on the returned object, confirming pure no-op behavior of `_merge_narrative_field` with empty inputs |
| `test_narrative_history_overflow_goes_to_archive` | Keep | `assert len(narr.history) == 3` and `assert overflowed_texts == ["iter-1 narrative"]` and `assert arch4[0]["reason"] == "narrative_history_cap"` — verifies archive reason string and overflow logic with specific expected values |
| `test_narrative_idempotent_when_new_equals_prior` | Keep | `assert merged is narr` and `assert archived == []` — confirms byte-identical duplicate suppresses history accumulation (no spurious churn) |
| `test_narrative_merge_score_trend_across_four_iters` | Keep | `assert narr.latest == "iter-10 narrative"` and `assert history_iters == [7, 4, 1]` and `assert history_texts == ["iter-7 narrative", "iter-4 narrative", "iter-1 narrative"]` — pure deterministic narrative history accumulation, no mock |
| `test_prior_findings_with_empty_new_returns_unchanged_no_llm_call` | Keep | `assert merged.key_findings[0].statement == "ridge near 50 Hz dominates"` and `assert merged.key_findings[0].evidence_iters == [2]` — verifies prior-preserved-verbatim fast path with deterministic logic; MockBridge never called |
| `test_rank_prune_caps_survivors_to_max_with_archive` | Keep | `assert len(merged.key_findings) == LIST_FIELD_MAX_SURVIVORS` and `assert all(a["reason"] == "llm_archive" for a in archived_kf)` — verifies archive reason tagging and count; not circular with mock |
| `test_rule1_same_meaning_merge` | Keep | `assert f.statement == "ridge near 50 Hz dominates"` and `assert f.evidence_iters == [2, 5]` — mock LLM returns the merge response; assertion is on parsed output fields of the *consolidate()* routing logic, not on the mock return value directly |
| `test_rule2_supersession_replacement_preserves_prior_in_prefix` | Keep | `assert f.statement.startswith("[SUPERSEDES iter-2:")` and `assert "VRAM ceiling measured at 15.8 GB" in f.statement` — tests that the supersession prefix parsing and statement assembly logic produces the correct output shape |
| `test_rule3_contradiction_preservation_emits_two_survivors` | Keep | `assert len(merged.key_findings) == 2` and `assert any(s.startswith("[CONFLICT iter-5 vs iter-2]") for s in statements)` — verifies that contradiction rule emits two survivors with the correct conflict prefix; load-bearing semantic correctness test |
| `test_rule4_distinct_emits_both_unchanged` | Keep | `assert len(merged.key_findings) == 2` and `statements == {"ridge near 50 Hz dominates", "training time scales linearly with batch_size"}` — verifies both items pass through when distinct, real post-processing logic |
| `test_stats_field_passes_through_untouched` | Keep | `assert merged.stats == stats` where stats contains seven distinct fields including nested dict — verifies consolidator never mutates, drops, or filters the stats dict |
| `test_strong_finding_survives_consolidation` | Keep | `assert len(strong) >= 1` where `strong = [f for f in merged.key_findings if f.strength == "strong"]` — behavioral guard that strength=="strong" findings are not silently dropped by rank-prune |
| `test_system_prompt_has_no_hardcoded_numerical_caps` | Keep | `assert needle not in _LIST_MERGE_SYSTEM_PROMPT` for `forbidden_numbers = [" 8 ", " 80 ", " 500 "]` and `assert "MAX_SURVIVORS" in _LIST_MERGE_SYSTEM_PROMPT` — pins Principle-#4 separation that tuning knobs stay in Python, not system prompts |
| `test_user_prompt_carries_policy_parameters_and_examples_and_data` | Keep | `assert "POLICY PARAMETERS" in prompt` and `assert "MAX_SURVIVORS = 8" in prompt` and `assert f"MAX_STATEMENT_CHARS = {FINDING_STATEMENT_MAX_CHARS}" in prompt` — verifies runtime-computed values are injected correctly into the user prompt |
| `test_user_prompt_overrides_take_effect` | Keep | `assert "MAX_SURVIVORS = 12" in prompt` and `assert "MAX_PRIOR_SUMMARY_CHARS = 60" in prompt` — verifies that per-call override kwargs actually replace the module defaults in the rendered prompt |

### `tests/unit/agent/cache/test_cache_entry_schema.py`

Tests: 21

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_cache_entry_full_payload_round_trip` | Keep | `CacheEntry.model_validate(dumped)` and `assert re_parsed.error_signatures[0].key() == e.error_signatures[0].key()` — end-to-end round-trip catching cross-field Pydantic composition bugs |
| `test_cache_entry_minimal_valid` | Keep | `e = CacheEntry(model_type="punet")` with assertions on all 6 default-accumulator fields — documents required defaults |
| `test_cache_entry_rejects_invalid_input` | Keep | `pytest.raises(ValidationError)` for missing model_type, empty model_type, extra field — shields against LLM schema drift |
| `test_error_sig_accepts_empty_last_frames` | Keep | `_valid_error_sig(last_frames=[], top_user_frame="")` with `assert sig.last_frames == []` — documents spec §2.2 non-Python failure mode path |
| `test_error_sig_key_tuple` | Keep | `assert sig.key() == ("vram", "ml_models/foo.py:42 in forward", "torch.cuda.OutOfMemoryError")` — pins the dedup contract tuple order so a refactor cannot silently change it |
| `test_error_sig_rejects_invalid_input` | Keep | `pytest.raises(ValidationError)` parametrized over unknown failure_class, oversized short_message, empty evidence_iters, empty error_type, extra field |
| `test_error_sig_valid_construction` | Keep | `sig = _valid_error_sig()` with `assert sig.failure_class == "vram"` — real construction path exercised |
| `test_finding_accepts_max_length_statement` | Keep | `statement="x" * FINDING_STATEMENT_MAX_CHARS` with `assert len(f.statement) == FINDING_STATEMENT_MAX_CHARS` — off-by-one boundary guard on a real schema constraint |
| `test_finding_rejects_invalid_input` | Keep | `pytest.raises(ValidationError)` with parametrized invalid inputs (empty statement, oversized, negative iter, unknown strength, extra field) — verifies Pydantic enforcement |
| `test_finding_valid_construction` | Keep | `f = ConsolidatedFinding(statement="ridge near 50 Hz dominates", evidence_iters=[2, 5], strength="strong")` followed by field assertions — real Pydantic construction, no mocks |
| `test_legacy_accepts_stats_key_aliases` | Keep | Tests both `_stats` and `stats` key acceptance with `assert entry.stats == expected` — real key-alias adapter logic |
| `test_legacy_defaults_missing_fields` | Keep | `CacheEntry.from_legacy_dict({"key_findings": ["lone finding"]})` with checks on empty bottlenecks, empty error_signatures — real missing-field defaults |
| `test_legacy_drops_empty_findings_strings` | Keep | `legacy["key_findings"] = ["valid finding", "", "   ", "another valid one"]` then `assert len(entry.key_findings) == 2` — tests the adapter's whitespace-filter logic |
| `test_legacy_error_signatures_default_empty` | Keep | `assert entry.error_signatures == []` — pins that pre-6.3 chains without error_signatures get `[]`, not `None`, for iterable-safety |
| `test_legacy_lifts_list_str_to_findings_with_current_iter` | Keep | `CacheEntry.from_legacy_dict(_legacy_entry(), model_type="punet", current_iter=7)` with `assert f.evidence_iters == [7]` — exercises real adapter logic |
| `test_legacy_lifts_str_to_narrative_with_empty_history` | Keep | `assert entry.best_config_analysis.latest == "depth=6, width=128 outperforms"` and checks all 6 narrative fields — real adapter field-mapping |
| `test_legacy_truncates_oversized_inputs` | Keep | `assert len(val) == expected_len` after feeding oversized strings — real truncation logic, not a mock |
| `test_narrative_accepts_at_boundary` | Keep | `ConsolidatedNarrative(latest="x" * NARRATIVE_LATEST_MAX_CHARS)` with `assert len(getattr(n, attr)) == expected_len` — boundary guard at cap |
| `test_narrative_accepts_empty_latest` | Keep | `n = ConsolidatedNarrative(latest="")` with `assert n.latest == ""` — documents intentional empty-latest semantics, catches any `min_length` regression |
| `test_narrative_rejects_invalid_input` | Keep | `pytest.raises(ValidationError)` with parametrized oversized latest, over-cap history, negative history iter, extra field — verifies rejection contract |
| `test_narrative_valid_construction` | Keep | `n = ConsolidatedNarrative(latest="best config is depth=6, width=128", history=[(2, "depth=4 was too shallow"), ...])` — real construction with assertions on fields |

### `tests/unit/agent/denoising_score_skill/test_estimator.py`

Tests: 7

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_inverse_in_num_workers` | Keep | `assert few["seconds"] == pytest.approx(2 * many["seconds"], rel=1e-6)` — confirms inverse-proportional worker scaling in real `estimate_wall_time_seconds`, no mocks |
| `test_ligroup_arithmetic_against_measured_constant` | Keep | `assert out["seconds"] == pytest.approx(400 * 2.21 / 8, rel=1e-6)` — regression pin for the calibrated 2.21 s/segment constant; guards against coefficient drift |
| `test_linear_in_segments` | Keep | `assert big["seconds"] == pytest.approx(4 * small["seconds"], rel=1e-6)` — exercises real arithmetic: 400-segment vs 100-segment result must be 4×, no mocks |
| `test_num_workers_zero_floored_to_one` | Keep | `assert zero["seconds"] == pytest.approx(one["seconds"])` and `assert zero["breakdown"]["num_workers"] == 1` — tests edge-case floor of 0 workers to 1, exercises real guard logic |
| `test_return_shape` | Keep | `assert set(out.keys()) == {"phase", "seconds", "breakdown"}` — calls real `estimate_wall_time_seconds` with a real helper-built sample_set, asserts shape and required breakdown keys |
| `test_unknown_host_falls_back_to_ligroup` | Keep | `with pytest.warns(UserWarning): out = est.estimate_wall_time_seconds(_sample_set(400), hostname="fake-host-xyz")` — exercises fallback branch + warning emission, monkeypatches only `_WARNED_HOSTS` set to reset global state |
| `test_zero_vram` | Keep | `assert out["total_bytes"] == 0` — calls real `estimate_peak_bytes()` with no mocks, asserts deterministic pure-function output |

### `tests/unit/agent/evaluate_vram_skill/test_batch_resolver.py`

Tests: 16

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_default_candidate_batches_matches_spec` | Keep | `assert _DEFAULT_CANDIDATE_BATCHES == (64, 32, 16, 8, 4, 2, 1)` — spec regression guard |
| `test_empty_candidate_list_raises` | Keep | `pytest.raises(ValueError, match="candidate_batches must be non-empty")` — deterministic error path |
| `test_error_message_names_segmentation_size` | Keep | `pytest.raises(ValueError, match="segmentation_size=12345")` — error message includes T for proposer |
| `test_error_message_surfaces_cap_and_peak_numbers` | Keep | `assert "predicted_peak=" in msg` and `assert "cap_bytes=" in msg` — verifies error message contains actionable numeric fields |
| `test_exhausts_all_candidates_before_raising` | Keep | `assert calls == list(_DEFAULT_CANDIDATE_BATCHES)` — verifies no short-circuit on partial failure |
| `test_intensity_cap_at_exact_boundary_accepts` | Keep | `assert got == 20` with `segmentation_size=40_000, candidate_batches=[32, 20, 10]` — pins `<=` boundary for intensity |
| `test_module_source_has_no_architecture_literals` | Keep | `assert f'"{banned}"' not in source` scanning actual source file bytes — Principle 2 enforcement that static analysis cannot catch |
| `test_picks_batch_equal_to_cap_boundary` | Keep | `assert got == 4` with `cap = params + 4 * per_B + cuda_context_bytes()` — pins `peak <= cap` (not `<`) boundary acceptance |
| `test_picks_largest_batch_that_fits_vram` | Keep | `assert got == 8` after computing `cap = params + 8 * per_B + cuda_context_bytes()` — verifies exact byte-accounting boundary |
| `test_picks_largest_batch_when_all_fit` | Keep | `assert resolve_inference_batch(_NoOp(), segmentation_size=1000, cap_bytes=cap) == 64` — real resolver logic with deterministic probe stub, non-trivial descending-search and boundary check |
| `test_raises_both_bindings_when_both_caps_fail_at_b1` | Keep | `assert label == "vram+compute_intensity"` — compound binding label correctness |
| `test_raises_intensity_binding_when_only_intensity_fails` | Keep | `assert label == "compute_intensity"` — distinguishes intensity-only binding from VRAM |
| `test_raises_vram_binding_when_smallest_batch_blows_cap` | Keep | `assert label == "vram"` extracted via `_binding_label(str(exc_info.value))` — verifies diagnostic label correctness |
| `test_respects_custom_candidate_order` | Keep | `assert got == 128` — ensures caller-supplied descending candidate list is honored |
| `test_skips_candidate_that_fits_vram_but_fails_intensity` | Keep | `assert got == 16` with `segmentation_size=40_000` — verifies intensity cap overrides VRAM acceptance |
| `test_visits_batches_in_descending_order_and_stops_early` | Keep | `assert calls == [64, 32, 16]` with probe call-order tracking — verifies early-stop behavior |

### `tests/unit/agent/evaluate_vram_skill/test_compute_intensity.py`

Tests: 12

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_cap_matches_calibration` | Keep | `assert _MAX_BATCH_TIMESTEPS == 800_000` — pins a calibrated constant to a physical failure point; static analysis cannot catch a drift of this value |
| `test_compute_intensity_is_product` | Keep | `assert compute_intensity(B, T) == B * T` — parametrized over 6 boundary-relevant (B,T) pairs; verifies deterministic arithmetic with no mocks |
| `test_compute_intensity_is_pure` | Keep | `assert compute_intensity(10, 20_000) == compute_intensity(10, 20_000)` — pins no-hidden-state guarantee; trivial but explicit regression guard |
| `test_describe_violation_has_no_architecture_names` | Keep | `for banned in ["wavenet","punet","fcnet","transformer","rnn","attention","conv","unet","lstm"]: assert banned not in msg` — enforces Principle 2 contract; no static analysis can catch runtime string generation |
| `test_describe_violation_includes_product_and_cap` | Keep | `assert "1,000,000" in msg or "1000000" in msg` and `assert "800,000" in msg or "800000" in msg` — pins that both observed value and limit appear in the message |
| `test_describe_violation_names_dimensions_verbatim` | Keep | `assert "batch_size" in msg` and `assert "segmentation_size" in msg` — verifies that the violation message surfaces config levers the Proposer can tune |
| `test_describe_violation_suggests_a_reduction` | Keep | `assert "reduce" in msg` and both dimension names in msg — exercises message content required by downstream Proposer guidance |
| `test_module_source_has_no_architecture_literals` | Keep | `source = Path(ci.__file__).read_text().lower()` then checks banned string literals in source — enforces architecture-agnostic module contract by reading the actual file |
| `test_passes_above_cap_rejects` | Keep | `assert passes(B, T) is False` with parametrized values strictly over cap — regression guard against cap drift upward |
| `test_passes_at_exact_boundary_accepts` | Keep | `assert passes(1, _MAX_BATCH_TIMESTEPS) is True` and `assert passes(800, 1000) is True` — explicitly pins `<=` not `<` semantics; a future change to `<` would silently tighten the gate |
| `test_passes_at_or_below_cap` | Keep | `assert passes(B, T) is True` with parametrized inputs below cap boundary — exercises the acceptance predicate at boundary region |
| `test_passes_at_stage2_failure_point_rejects` | Keep | `assert passes(25, 40_000) is False` — regression test for the exact (B=25, T=40000) that caused `cudaErrorLaunchTimeout`; if cap drifts this must fail |

### `tests/unit/agent/evaluate_vram_skill/test_killer_report.py`

Tests: 20

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_combined_report_populates_both_halves` | Keep | `assert d.binding_cap == "vram+compute_intensity"` and both VRAM fields (`d.dominant_layer == "huge_op"`) and intensity fields (`d.batch_size == 25`) present — verifies combined renderer merges both attributions |
| `test_combined_suggestion_concatenates_both_halves` | Keep | `assert "my_layer" in sugg` and `assert "segmentation_size" in sugg` and numeric product/cap values in sugg — verifies both fix halves are present for Proposer |
| `test_combined_verdict_names_both_modes` | Keep | `assert "VRAM" in report.verdict` and `assert "Compute-intensity" in report.verdict` — pins that combined verdict identifies both failure modes |
| `test_intensity_report_populates_config_fields_only` | Keep | `assert d.binding_cap == "compute_intensity"` and `assert d.dominant_layer is None` etc — verifies VRAM half stays empty and only config fields are populated |
| `test_intensity_suggestion_has_no_architecture_family_terms` | Keep | `for banned in ["wavenet","punet","fcnet","transformer","rnn","attention","conv","unet","lstm"]: assert banned not in sugg` — Principle 2 guard on intensity suggestion |
| `test_intensity_suggestion_names_config_levers_only` | Keep | `assert "batch_size" in sugg` and `assert "segmentation_size" in sugg` and `assert "layer" not in sugg` — enforces that intensity suggestion names config knobs, not architecture |
| `test_intensity_verdict_uses_distinct_label` | Keep | `assert "OVER-BUDGET (Compute-intensity)" in report.verdict` and `assert "OVER-BUDGET (VRAM)" not in report.verdict` — pins disjoint labels for two failure modes |
| `test_killer_report_is_frozen` | Keep | `with pytest.raises(ValidationError): r.verdict = "z"` — pins frozen-model constraint on KillerReport |
| `test_killer_report_model_dump_matches_wrapper_flatten_contract` | Keep | `assert set(dumped.keys()) == {"status", "verdict", "memory_killer", "suggestion"}` — pins exact serialization keys consumed by downstream wrapper flatten |
| `test_memory_killer_details_is_frozen` | Keep | `with pytest.raises(ValidationError): d.binding_cap = "compute_intensity"` — pins frozen-model constraint; Pydantic `model_config = ConfigDict(frozen=True)` behavioral test |
| `test_module_source_has_no_architecture_literals` | Keep | `source = Path(killer_report.__file__).read_text().lower()` with banned literal checks — reads module source to enforce architecture-agnostic invariant |
| `test_per_layer_entry_field_names_are_the_contract` | Keep | `assert set(e.model_dump().keys()) == {"name", "class_name", "output_shape", "bytes"}` — pins field names as contract; a rename would break prompt template reads |
| `test_vram_dominant_fraction_is_rounded_to_four_decimals` | Keep | `assert report.memory_killer.dominant_fraction == 0.3333` — pins rounding behavior (333.../1000... = 0.3333) to exactly 4 decimals |
| `test_vram_per_layer_only_contains_leaves` | Keep | `assert names == ["stage1.conv", "stage1.bn"]` — verifies non-leaf containers are filtered out of per_layer list, preventing double-counted bytes |
| `test_vram_report_handles_empty_layers_gracefully` | Keep | `assert report.memory_killer.dominant_layer is None` and `assert "whole model" in report.suggestion.lower() or "total parameter" in report.suggestion.lower()` — edge-case: empty layer list, verifies fallback suggestion text |
| `test_vram_report_identifies_dominant_leaf` | Keep | `assert d.dominant_layer == "block3_big"` and `assert d.dominant_layer_bytes == 8_000_000_000` — exercises dominant-layer attribution logic on hand-built `ProbeResult` fixtures with multiple competing layers |
| `test_vram_report_suggestion_has_no_architecture_family_terms` | Keep | `for banned in ["multiheadattention","self-attention","transformer",...]: assert banned not in sugg` — enforces Principle 2 on generated suggestion strings |
| `test_vram_report_suggestion_names_a_specific_dimension_to_reduce` | Keep | `assert "segmentation_size" in sugg` and `assert "channel" in sugg` and `assert "reduce" in sugg or "shrink" in sugg` — pins actionable levers in suggestion |
| `test_vram_report_suggestion_names_dominant_layer_by_user_name` | Keep | `assert "my_attn_block" in report.suggestion` and `assert "InternalClassName" not in report.suggestion` — pins that user-visible var_name appears, not the class name |
| `test_vram_verdict_format_includes_labels_and_byte_figures` | Keep | `assert "OVER-BUDGET (VRAM)" in report.verdict` and `assert "50.0 GB" in report.verdict` and `assert "78% of" in report.verdict` — pins verdict format including GB labels and percentage computation |

### `tests/unit/agent/evaluate_vram_skill/test_overhead.py`

Tests: 19

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_cuda_context_bytes_is_deterministic` | Keep | `assert cuda_context_bytes() == cuda_context_bytes()` — documents pure-function invariant; low cost, meaningful contract |
| `test_cuda_context_bytes_matches_appendix_a5` | Keep | `assert _CUDA_CONTEXT_BYTES == 185 * 1024**2` — regression pin for calibrated constant; static analysis cannot catch value drift |
| `test_cudnn_backward_workspace_matches_appendix_a5` | Keep | `assert _CUDNN_BACKWARD_WORKSPACE_BYTES == 50 * 1024**2` — regression pin for second calibrated constant |
| `test_module_source_has_no_architecture_names` | Keep | `assert f'"{banned}"' not in source` for banned in `["wavenet", "punet", "fcnet", "transformer", "rnn"]` — reads the actual module file and checks no architecture-specific literals appear; static analysis does not enforce this design principle |
| `test_multiplier_table_has_expected_keys` | Keep | `assert set(_OPTIMIZER_STATE_MULTIPLIER.keys()) == {"adam", "adamw", "sgd"}` — regression pin: the table is a contract with the Proposer's config schema |
| `test_phase_overhead_inference_accepts_none_optimizer` | Keep | `result = phase_overhead_bytes(1024, "inference", optimizer=None)` — edge-case: None optimizer in inference mode must not raise |
| `test_phase_overhead_inference_ignores_params_and_optimizer` | Keep | `assert phase_overhead_bytes(params_bytes, "inference") == _CUDA_CONTEXT_BYTES` — tests that inference path ignores params (no mocks) |
| `test_phase_overhead_rejects_unknown_mode` | Keep | `with pytest.raises(ValueError, match="Unknown mode"): phase_overhead_bytes(1024, "eval", optimizer="adam")` — error path for invalid mode string |
| `test_phase_overhead_training_propagates_unknown_optimizer_error` | Keep | `with pytest.raises(ValueError, match="Unknown optimizer"): phase_overhead_bytes(1024, "training", optimizer="adafactor")` — error propagation from inner function |
| `test_phase_overhead_training_requires_optimizer` | Keep | `with pytest.raises(ValueError, match="training mode requires an optimizer"): phase_overhead_bytes(1024, "training", optimizer=None)` — error path for missing optimizer in training mode |
| `test_phase_overhead_training_strictly_exceeds_inference` | Keep | `assert tr > inf` and `assert tr - inf == training_overhead_bytes(params, "adam") + _CUDNN_BACKWARD_WORKSPACE_BYTES` — physical sanity invariant with multi-part assertion |
| `test_phase_overhead_training_sums_three_terms` | Keep | `assert phase_overhead_bytes(params, "training", optimizer="adamw") == expected` where expected is `training_overhead_bytes(params, "adamw") + _CUDA_CONTEXT_BYTES + _CUDNN_BACKWARD_WORKSPACE_BYTES` — arithmetic aggregation contract |
| `test_training_overhead_adamw_matches_adam` | Keep | `assert training_overhead_bytes(params_bytes, "adamw") == training_overhead_bytes(params_bytes, "adam")` — pins AdamW/Adam state-shape parity, no mocks |
| `test_training_overhead_case_insensitive` | Keep | `for name in ["adam", "Adam", "ADAM", "AdAm"]: assert training_overhead_bytes(p, name) == 3 * p` — tests case normalization logic, no mocks |
| `test_training_overhead_empty_string_raises` | Keep | `with pytest.raises(ValueError, match="Unknown optimizer"): training_overhead_bytes(1024, "")` — edge-case empty-string input to error path |
| `test_training_overhead_error_message_lists_known_optimizers` | Keep | `assert "adam" in msg and "adamw" in msg and "sgd" in msg` — pins error message content so callers can self-correct; static analysis cannot verify runtime message text |
| `test_training_overhead_scales_linearly_with_params_adam` | Keep | `assert training_overhead_bytes(params_bytes, "adam") == 3 * params_bytes` — parametrized over 5 values; validates the 3× multiplier arithmetic in real `training_overhead_bytes` |
| `test_training_overhead_sgd_is_grads_only` | Keep | `assert training_overhead_bytes(params_bytes, "sgd") == params_bytes` — verifies the 0-multiplier path for SGD (grads only) in real function |
| `test_training_overhead_unknown_optimizer_raises` | Keep | `with pytest.raises(ValueError, match="Unknown optimizer"): training_overhead_bytes(1024, "lion")` — tests error branch for unsupported optimizer |

### `tests/unit/agent/evaluate_vram_skill/test_structural_probe.py`

Tests: 20

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_pack_hook_returns_none_not_tensor` | Keep | `assert report.total_saved_bytes > 0` after verifying baseline count and using real `probe_autograd_tape` — OOM fix correctness |
| `test_probe_activation_footprint_forward_layer_report_shapes_are_physical` | Keep | `assert out_layer.output_shape == [2, 16, 20]` and `assert out_layer.output_bytes == 2 * 16 * 20 * 4` — shape reporting accuracy |
| `test_probe_activation_footprint_inference_mode_skips_tape` | Keep | `assert result.autograd_tape is None` and `assert result.input_bytes == 2 * 8 * 4` — inference mode byte-counting |
| `test_probe_activation_footprint_training_mode_requires_loss_and_target` | Keep | `pytest.raises(ValueError, match="training mode requires both loss_module")` — input validation |
| `test_probe_activation_footprint_training_populates_loss_and_tape` | Keep | `assert result.loss_forward.module_name == "FocalLikeLoss"` and `assert result.autograd_tape.total_saved_bytes > 0` — training path completeness |
| `test_probe_autograd_tape_captures_loss_intermediates_torchinfo_misses` | Keep | `assert report.total_saved_bytes >= floor` where `floor = B * C * T * 4` — motivating-case regression |
| `test_probe_autograd_tape_captures_nonzero_bytes_for_training_graph` | Keep | `assert report.total_saved_bytes > 0` — confirms real autograd storage is captured |
| `test_probe_autograd_tape_dedup_across_views_of_same_storage` | Keep | `assert report.total_saved_bytes <= upper_bound_if_dedup_ok` using computed `base_bytes + w1_bytes + w2_bytes` — storage-ptr dedup correctness |
| `test_probe_autograd_tape_returns_pydantic` | Keep | `assert isinstance(report, AutogradTapeReport)` with real Linear forward — schema contract |
| `test_probe_autograd_tape_unpack_raises_on_backward` | Keep | `pytest.raises(RuntimeError, match=r"backward.*must not be called")` with real `saved_tensors_hooks` — backward guard |
| `test_probe_forward_layers_accepts_multi_input_module` | Keep | `assert isinstance(report, ForwardLayerReport)` with real `FocalLikeLoss` passed `[logits, target]` — multi-input path |
| `test_probe_forward_layers_counts_leaves_only_for_aggregates` | Keep | `assert report.total_param_bytes == leaf_params` by summing `li.param_bytes for li in report.layers if li.is_leaf` — double-count regression |
| `test_probe_forward_layers_max_output_is_truly_max` | Keep | `assert report.forward_output_bytes_max == manual_max` computed over all leaves — aggregation correctness |
| `test_probe_forward_layers_param_bytes_match_hand_computed` | Keep | `assert report.total_param_bytes == expected_params * 4` where `expected_params = (8 * 16 + 16) + (16 * 4 + 4)` — hardcoded arithmetic vs real probe |
| `test_probe_forward_layers_preserves_construction_order` | Keep | `assert leaf_vars == ["fc1", "act", "fc2"]` — construction order preservation |
| `test_probe_forward_layers_returns_pydantic` | Keep | `assert isinstance(report, ForwardLayerReport)` and `assert all(isinstance(li, LayerReport) for li in report.layers)` — real torch model, real probe, schema validation |
| `test_probe_training_bytes_exceed_inference_bytes_on_same_config` | Keep | `assert tr_peak > inf_peak` with computed `inf_peak` and `tr_peak` from real probes — physical sanity |
| `test_sequential_model_probe_gc_called_between_phases` | Keep | `assert len(gc_calls) >= 2` with real `probe_activation_footprint` and patched `gc.collect` — GC call count |
| `test_sequential_model_training_probe_rss_bounded` | Keep | `assert delta_mb < 500` using real `psutil.Process().memory_info().rss` — memory regression test |
| `test_torchinfo_runs_under_no_grad_in_training_mode` | Keep | `assert grad_states[0] is True` and `assert gs is False for i, gs in enumerate(grad_states[1:], start=1)` — no_grad enforcement |

### `tests/unit/agent/evaluate_vram_skill/test_wrapper_contract.py`

Tests: 19

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_both_training_caps_binding_produces_combined_killer` | Keep | `assert out["memory_killer"]["binding_cap"] == "vram+compute_intensity"` — tests the real wrapper's combined-failure path when both VRAM and intensity fail; derived from real logic |
| `test_cpu_only_host_short_circuits_with_success` | Keep | `p.probe.assert_not_called()` and `assert "CPU mode" in out["verdict"]` — verifies that the CPU-only short-circuit path in the real wrapper skips the probe and generates the correct verdict string |
| `test_estimated_gb_and_limit_gb_are_floats_in_gb_units` | Keep | `assert out["limit_gb"] == pytest.approx(25.6, abs=0.01)` — pins the GB conversion formula; value derived from real wrapper logic |
| `test_explicit_hardware_context_skips_discover` | Keep | `mock_discover.assert_not_called()` — pins the other branch: when context is provided, `discover` is skipped; asserts real branching logic |
| `test_feasible_status_is_success` | Keep | `assert out["status"] == "success"` — tests real wrapper routing; status is derived from wrapper logic, not directly from any mock return |
| `test_feasible_verdict_mentions_cap_and_dominant_phase` | Keep | `assert "25.6 GB" in out["verdict"]` and `assert "Dominant phase" in out["verdict"]` — tests real string rendering in wrapper; the specific values come from real computation |
| `test_inference_batch_is_populated_on_feasible_path` | Keep | `p.resolved_batch = 16` then `assert out["inference_batch"] == 16` — the mock controls the resolver's resolved value, assertion is on whether the wrapper correctly threads it into the output dict; tests real plumbing, not a circular mock |
| `test_inference_resolver_intensity_failure_produces_intensity_killer` | Keep | `p.resolve.side_effect = ValueError("...Binding cap(s): compute_intensity.")` then `assert out["memory_killer"]["segmentation_size"] == 900_000` — tests the wrapper's no-re-probe branch for intensity failures |
| `test_inference_resolver_vram_failure_produces_vram_killer` | Keep | `p.resolve.side_effect = ValueError("...Binding cap(s): vram.")` then `assert out["memory_killer"]["binding_cap"] == "vram"` — tests that wrapper parses the error message and re-probes correctly |
| `test_memory_killer_is_none_on_feasible_path` | Keep | `assert out["feasible"] is True` and `assert out["memory_killer"] is None` — verifies real wrapper logic: on success path killer slot stays None |
| `test_none_hardware_context_falls_back_to_discover` | Keep | `mock_discover.assert_called_once()` — tests the real control-flow branching in wrapper when `hardware_context=None`; non-circular, asserts on side effect of real wrapper code |
| `test_phase_breakdown_has_training_and_inference` | Keep | `assert set(out["phase_breakdown"].keys()) >= {"training", "inference"}` — tests that wrapper constructs the breakdown dict from both probe phases |
| `test_pydantic_validation_error_maps_to_schema_violation_response` | Keep | builds a real `ValidationError`, sets `p.build_model.side_effect = real_ve`, then asserts `out["status"] == "schema_violation"` and `"violations" in out` — tests real error-handling path in wrapper |
| `test_removed_inference_batch_uncalibrated_is_absent` | Keep | `assert "inference_batch_uncalibrated" not in out` — pins removal of a deprecated key; real wrapper logic produces the dict, mock prevents GPU/probe calls |
| `test_return_dict_has_all_required_keys_on_feasible_path` | Keep | `assert _REQUIRED_KEYS.issubset(out.keys())` — verifies real contract of `wrapper.run_skill` return dict; mocks replace only the five external collaborators (probe, batch resolver, etc.), assertion is on the real wrapper's output structure |
| `test_training_intensity_over_budget_produces_intensity_killer` | Keep | `p.intensity_passes.return_value = False` then `assert out["memory_killer"]["binding_cap"] == "compute_intensity"` and `assert out["memory_killer"]["batch_size"] == 25` — tests real wrapper routing to the intensity-killer path |
| `test_training_vram_over_budget_produces_vram_killer` | Keep | `assert out["memory_killer"]["binding_cap"] == "vram"` and `assert out["memory_killer"]["dominant_layer"] == "big_layer"` — a huge probe result is configured; the real wrapper's budget check logic produces the killer dict; assertion is on real computation, not mock return |
| `test_vram_budget_gb_cannot_exceed_physical_cap` | Keep | `assert out["limit_gb"] == pytest.approx(25.6, abs=0.01)` — pins the deterministic formula `0.80 * 32.0 = 25.6` and verifies `vram_budget_gb=30.0` (larger) is correctly vetoed |
| `test_vram_budget_gb_further_restricts_cap` | Keep | `vram_budget_gb=1e-12` then `assert out["memory_killer"]["binding_cap"] == "vram"` — tests that the real `min(physical, budget)` logic in the wrapper correctly restricts when budget < physical |

### `tests/unit/agent/inference_skill/test_estimator.py`

Tests: 13

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_monkeypatched_huge_inference_batch_inverts_ordering` | Keep | `monkeypatch.setattr(est, "inference_batch_for", lambda mt: 10_000)` then `assert inference["total_bytes"] > training["total_bytes"]` — documents and tests inversion regime; monkeypatch is purpose-built to manufacture the crossover condition |
| `test_monotone_in_inference_batch_at_fixed_ms` | Keep | `monkeypatch.setattr(est, "inference_batch_for", ...)` then `assert large_bs["seconds"] < small_bs["seconds"]` — isolates batch-size effect at fixed ms/step; the without-fix case would be batch-invariant, so monkeypatch is necessary |
| `test_monotone_in_segments` | Keep | `assert big["seconds"] > small["seconds"]` — monotonicity property: 400 PSD steps must take longer than 100; no mocks |
| `test_ms_source_labels_warmup_path` | Keep | `assert out["breakdown"]["ms_source"] == "derived_from_training_warmup"` — pins label string for a specific input path; static analysis cannot verify runtime dict values |
| `test_no_focal_onehot_key` | Keep | `assert "focal_onehot_bytes" not in out["breakdown"]` — tests absence of a key that would be a bug; static analysis cannot verify dict key presence |
| `test_registered_model_type_is_not_uncalibrated` | Keep | `assert out["breakdown"]["inference_batch_uncalibrated"] is False` — mirrors above test for known model_types; prevents spurious flagging |
| `test_return_shape` | Keep | `assert set(out.keys()) == {"phase", "total_bytes", "breakdown"}` and `assert "inference_batch" in out["breakdown"]` — validates output schema of real `estimate_peak_bytes`, no mocks |
| `test_rnn_has_no_transformer_attn` | Keep | `assert out["breakdown"]["transformer_attn_bytes"] == 0` — tests model-type-specific routing: RNN must produce 0 attention bytes |
| `test_static_fallback_invokes_count_params` | Keep | `monkeypatch.setattr(est, "_count_params", _stub)` then `assert calls == ["rnn"]` and `assert out["breakdown"]["ms_source"] == "static_formula"` — verifies that `_count_params` is called with correct model_type in the static fallback branch |
| `test_training_exceeds_inference_when_params_dominate` | Keep | `assert training["total_bytes"] > inference["total_bytes"]` — physical sanity check comparing two different estimator calls; no mocks |
| `test_transformer_attn_scales_linearly_with_inference_batch` | Keep | `assert large["breakdown"]["transformer_attn_bytes"] == 2 * small["breakdown"]["transformer_attn_bytes"]` — uses `monkeypatch.setattr(est, "inference_batch_for", ...)` to isolate inference_batch as a variable; asserts real linear scaling arithmetic |
| `test_unregistered_model_type_uses_runtime_fallback` | Keep | `assert out["breakdown"]["inference_batch"] == 25` and `assert out["breakdown"]["inference_batch_uncalibrated"] is True` — K.2.5-8 regression guard: unregistered model must not crash, must use fallback batch and flag it |
| `test_weights_use_4x_factor_not_16x` | Keep | `assert out["breakdown"]["weights_bytes"] == 100_000 * 4` — regression pin: inference must use 4 B/param not 16 B (training value) |

### `tests/unit/agent/llm_bridge/test_all_calls_labeled.py`

Tests: 2

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_every_bridge_call_in_nodes_has_label_kwarg` | Keep | `assert not offenders` after walking AST of every `*.py` in `nodes/` — static structural contract that a future developer adding `bridge.generate(...)` without `label=` would violate; pure deterministic logic catching a runtime warning-class bug |
| `test_nodes_dir_resolves` | Keep | `assert _NODES_DIR.is_dir()` — deterministic filesystem assertion that guards against silent relocation of the nodes directory; no mocking, catches real misconfiguration |

### `tests/unit/agent/llm_bridge/test_emit_marker.py`

Tests: 6

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_emit_marker_accepts_none_extra` | Keep | `bridge.emit_marker(label="interpretation.per_model_skipped")` (no extra kwarg) with `assert rows[0]["extra"] == {}` — documents None-to-empty-dict serialization |
| `test_emit_marker_extra_round_trips` | Keep | `assert rows[0]["extra"] == payload` where payload is a nested dict — real JSONL serialization round-trip |
| `test_emit_marker_jsonl_ordering` | Keep | Loop emitting 3 markers then `assert [r["extra"]["ord"] for r in rows] == [1, 2, 3]` — verifies append-only JSONL ordering |
| `test_emit_marker_noop_when_unbound` | Keep | `assert list(tmp_path.iterdir()) == []` after calling emit_marker with `_token_usage_path=None` — verifies the real no-op path |
| `test_emit_marker_rejects_empty_label` | Keep | `pytest.raises(ValueError, match="non-empty label")` followed by `assert not bridge._token_usage_path.exists()` — real validation and pre-write-rejection logic |
| `test_emit_marker_writes_zeroed_row` | Keep | After `bridge.emit_marker(...)`, reads JSONL and asserts `row["label"] == "interpretation.per_model_skipped"`, `row["tokens"] == {"prompt": None, ...}`, `row["chars"] == {"system": 0, ...}` — assertions on real file I/O, not on mock return values |

### `tests/unit/agent/llm_bridge/test_force_crash.py`

Tests: 7

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_force_crash_default_false_when_env_unset` | Keep | `assert bridge._force_crash is False` and `assert isinstance(result, dict)` after `bridge._chat_json(...)` — real env-var-to-attribute logic, no mocks |
| `test_force_crash_does_not_break_record_usage` | Keep | `assert bridge._record_usage(response=object(), label="anything") is None` — asserts _record_usage is NOT hooked even under force_crash, preventing audit-trail corruption |
| `test_force_crash_error_message_includes_label` | Keep | `assert "interpretation.synthesis" in message` and `assert "force_crash" in message` and `assert "Commit 4.6" in message` — pins specific error-message content for forensic visibility |
| `test_force_crash_only_triggers_on_exact_string_1` | Keep | `monkeypatch.setenv("SIDERIUS_STUB_FORCE_CRASH", value)` parametrized over `["", "0", "true", "True", "yes", "on", "2"]` with `assert bridge._force_crash is False` — real exact-match logic guard |
| `test_force_crash_raises_on_chat_json` | Keep | `monkeypatch.setenv("SIDERIUS_STUB_FORCE_CRASH", "1")` then `pytest.raises(RuntimeError, match=r"force_crash.*tuner\.planner")` — real env-var-triggered RuntimeError path |
| `test_force_crash_raises_on_generate_text` | Keep | `pytest.raises(RuntimeError, match=r"force_crash.*implementor\.reasoning")` — separate entry-point coverage |
| `test_force_crash_raises_on_tool_call` | Keep | `pytest.raises(RuntimeError, match=r"force_crash")` — ensures RuntimeError fires before NotImplementedError on tool_call |

### `tests/unit/agent/llm_bridge/test_no_silent_swallow.py`

Tests: 3

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_bare_except_does_not_swallow_context_error` | Keep | `_has_risky_call(stmt)` inside `ast.walk(tree)` — real AST analysis checking that bare/broad `except` blocks in `llm_bridge.py` don't wrap risky method calls; deterministic logic on actual source code |
| `test_bridge_path_resolves` | Keep | `assert _BRIDGE_PATH.is_file()` — filesystem sanity check that the file the AST tests depend on exists; prevents silent false-passes if the path drifts |
| `test_no_except_llm_bridge_context_error_in_bridge` | Keep | `hits = _collect_handlers_naming(tree, "LLMBridgeContextError")` then `assert not hits` — real AST walk of the production source file; catches a regression static analysis alone won't catch |

### `tests/unit/agent/llm_bridge/test_record_usage.py`

Tests: 11

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_chat_json_writes_one_row_per_attempt` | Keep | `assert len(rows) == 3` and `assert [r["extra"]["status"] for r in rows] == ["json_decode_error", "json_decode_error", "ok"]` — tests multi-attempt retry produces one row per attempt with correct status; mock provides the bad/good JSON sequence |
| `test_chat_json_writes_row_for_empty_content` | Keep | `assert rows[0]["extra"]["status"] == "empty_content"` and `assert rows[1]["extra"]["status"] == "ok"` — tests empty-content status classification in the retry loop |
| `test_generate_default_label_emits_warning` | Keep | `assert "[LLMBridge.generate] WARNING: called without label=" in captured.err` and `assert rows[0]["label"] == "unlabeled"` — tests that calling `generate()` without a label triggers the expected warning |
| `test_generate_text_writes_one_row` | Keep | `assert row["label"] == "proposer.causal_reasoning"` and `assert row["tokens"] == {"prompt": 20, "completion": 10, "total": 30}` — tests `generate_text()` telemetry path; mock replaces network, assertions are on real row construction |
| `test_generate_writes_one_row_with_correct_counts` | Keep | `assert row["tokens"] == {"prompt": 100, "completion": 50, "total": 150}` and `assert row["chars"]["system"] == 3` — mock is the OpenAI SDK transport layer; assertions are on the real telemetry-row construction logic including token counts, char counts, labels |
| `test_plan_uses_tuner_planner_label` | Keep | `assert rows[0]["label"] == "tuner.planner"` and `assert "WARNING: called without label=" not in captured.err` — tests that `plan()` uses the correct internal label without emitting the unlabeled warning |
| `test_record_usage_handles_missing_usage` | Keep | `assert row["tokens"] == {"prompt": None, "completion": None, "total": None}` and `assert row["chars"]["system"] == len("sys-prompt")` — tests graceful degradation when `response.usage` is None; real char-count logic is asserted |
| `test_record_usage_noop_when_unbound` | Keep | `assert bridge._token_usage_path is None` then `assert list(tmp_path.iterdir()) == []` — verifies that no file is created when run-context is unbound; mock replaces only the network transport |
| `test_reflect_uses_tuner_reflector_label` | Keep | `assert rows[0]["label"] == "tuner.reflector"` and `assert "WARNING: called without label=" not in captured.err` — tests that `reflect()` uses the correct internal label |
| `test_tool_call_writes_one_row_on_success` | Keep | `assert rows[0]["extra"] == {"attempt": 0, "status": "ok"}` and `assert rows[0]["label"] == "validator.code_review"` — tests `tool_call()` telemetry on successful call; mock provides the tool response |
| `test_tool_call_writes_row_then_raises_when_no_tool_call` | Keep | `with pytest.raises(ValueError, match="did not return a tool call"):` and `assert rows[0]["extra"] == {"attempt": 0, "status": "no_tool_call"}` — tests that telemetry is written BEFORE the raise in the no-tool-call path |

### `tests/unit/agent/llm_bridge/test_setter_safety.py`

Tests: 13

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_5_iter_quantitative_and_linter_passes` | Keep | `assert len(data_rows) == 60; assert len(flush_rows) == 4; assert [r["iter"] for r in flush_rows] == [0, 1, 2, 3]` plus `errors, _warnings = lint(bridge._token_usage_path); assert errors == []` — quantitative invariant on 5-iter run + real linter exercised |
| `test_linter_detects_post_flush_leak` | Keep | `assert any("[LEAK]" in e for e in errors); assert main([str(log)]) == 1` — linter's detection of post-flush-leak rows; writes fixture JSONL and verifies real linter logic |
| `test_linter_detects_run_id_mismatch` | Keep | `assert any("[RUN_ID_MISMATCH]" in e for e in errors)` — linter error for mismatched run_ids across rows; deterministic logic check |
| `test_linter_warns_on_non_monotonic_ts` | Keep | `assert errors == []; assert any("non-monotonic ts" in w for w in warnings)` — linter warning (not error) for out-of-order timestamps; deterministic classification logic |
| `test_record_usage_aborts_on_runid_mismatch` | Keep | `with pytest.raises(LLMBridgeContextError, match="run_id mismatch")` and `assert len(rows) == 1; assert rows[0]["run_id"] == "OTHER-RUN"` — pre-seeded JSONL with different run_id triggers abort; file stays unchanged |
| `test_setter_advance_iter_writes_flush_marker` | Keep | `assert rows[1]["label"] == "_iter_flush"; assert rows[1]["extra"] == {"marker": "iter_end"}` — exercises the flush-marker write logic triggered by iter advancement; deterministic assertion on real file content |
| `test_setter_happy_path` | Keep | `rows = _read_rows(bridge._token_usage_path); assert rows[0]["iter"] == 0; assert rows[0]["run_id"] == "r-001"; assert rows[0]["label"] == "proposer.proposing"` — exercises real JSONL write path with real file I/O; assertion is on written file content, not mock return value |
| `test_setter_raises_oserror_on_missing_workspace` | Keep | `with pytest.raises(OSError, match="does not exist")` and `assert bridge._token_usage_path is None` — error-path contract that missing workspace raises loud error and leaves bridge unbound |
| `test_setter_raises_value_error_on_negative_iter` | Keep | `with pytest.raises(ValueError, match="non-negative")` — validates input rejection for negative iter; deterministic guard |
| `test_setter_rejects_backwards_iter` | Keep | `with pytest.raises(LLMBridgeContextError, match="backwards iter")` and `assert bridge._iter == 5` — deterministic backwards-iter guard with state-preservation assertion |
| `test_setter_rejects_run_id_mutation` | Keep | `with pytest.raises(LLMBridgeContextError, match="run_id mutation forbidden")` and `assert bridge._run_id == "r-A"` — verifies the immutability invariant and state rollback; deterministic guard |
| `test_setter_same_iter_no_flush` | Keep | `assert all(r["label"] != "_iter_flush" for r in rows)` — verifies same-iter re-entry suppresses the flush marker; deterministic logic, real file I/O |
| `test_setter_thread_safety_no_duplicate_flush` | Keep | `assert flush_rows == []` after 8 threads racing on `set_run_context(iter=0)` — concurrent-access invariant proving the lock prevents duplicate flush markers; deterministic threading test |

### `tests/unit/agent/llm_bridge/test_stub_constructor_compat.py`

Tests: 5

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_4_agents_call_shape_provider_model_id_max_retries` | Keep | `assert bridge.provider == "stub"` and `assert bridge.max_retries == 3` — verifies stub silently drops caller-supplied `provider` and preserves `max_retries` |
| `test_caller_provider_is_ignored_by_design` | Keep | `assert bridge.provider == "stub"` after `StubLLMBridge(provider="anthropic", model_id="claude-opus-4-7")` — documents contract that caller `provider` is dropped |
| `test_max_retries_default_is_zero` | Keep | `assert bridge.max_retries == 0` — pins schema default for absent-vs-disabled distinction |
| `test_no_kwargs_still_works` | Keep | `assert bridge.provider == "stub"` with bare `StubLLMBridge()` — regression guard for no-kwarg construction |
| `test_tuner_call_shape_with_reflect_pair` | Keep | `assert bridge.reflect_provider == "stub"` — verifies tuner's 5-kwarg shape doesn't crash and `reflect_provider` is normalised |

### `tests/unit/agent/llm_bridge/test_stub_llm_bridge.py`

Tests: 26

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_does_not_construct_openai_client` | Keep | `assert bridge.client is None` and `assert bridge.reflect_client is None` — verifies no-API-key-needed property |
| `test_emit_marker_still_writes` | Keep | After `set_run_context` and `emit_marker`, reads JSONL and `assert rows[0]["tokens"]["prompt"] is None` — verifies emit_marker is inherited not overridden |
| `test_generate_with_known_label_routes_to_synthesiser` | Keep | `bridge.generate("system", "user", label="interpretation.dedup")` then `assert raw["is_duplicate"] is False` — verifies generate() label routing |
| `test_implementor_code_assembles_to_valid_plugin` | Keep | `err = MLModelImplementor._validate_code(code, inp)` and `assert err is None` plus `ast.parse(plugin_src)` — real end-to-end plugin validation |
| `test_implementor_reasoning_returns_string` | Keep | `assert isinstance(text, str) and len(text) > 0` — real text dispatch |
| `test_implementor_repair_returns_same_dict_as_code` | Keep | `assert code == repair` — pins symmetry contract between implementor.code and implementor.repair |
| `test_interpretation_dedup_returns_false_default` | Keep | `assert raw["is_duplicate"] is False` and `assert raw["duplicate_of"] is None` — pins no-spurious-merge default |
| `test_interpretation_per_model_has_all_8_fields` | Keep | `assert expected_fields.issubset(raw.keys())` and checks all 6 scalar fields are non-empty strings — pins field completeness contract |
| `test_interpretation_synthesis_has_callsite_keys` | Keep | `assert isinstance(raw.get("key_findings"), list)` and `assert raw["take_home_message"]` — pins callsite-read keys from result_interpretation_agent.py lines 953-955 |
| `test_is_subclass_of_llm_bridge` | Keep | `assert isinstance(bridge, LLMBridge)` — wiring contract; isinstance check catches inheritance breakage |
| `test_plan_method_routes_to_synthesiser` | Keep | `raw = bridge.plan(memory_history=[])` then `ExperimentPlan.model_validate(raw)` — verifies inherited plan() routes through stub dispatch |
| `test_proposer_causal_reasoning_falsifiable_prediction_clears_boldness_gate` | Keep | `FalsifiablePrediction.model_validate(raw["falsifiable_prediction"])` then `assert pred.predicted_value != pred.current_value` and `assert pred.boldness == pytest.approx(1.0)` — real schema validation |
| `test_proposer_comparison_returns_required_keys` | Keep | `assert isinstance(raw.get("proposed_vocab_links"), list)` — pins keys downstream stage renders from |
| `test_proposer_legacy_commit_validates_against_proposaloutput` | Keep | `ProposalOutput.model_validate(raw)` and `assert proposal.model_name == "stub_arch_003_a"` — real schema round-trip |
| `test_proposer_legacy_reasoning_returns_string` | Keep | `text = bridge._synthesise_text("proposer.legacy_reasoning")` then `assert isinstance(text, str) and len(text) > 0` — real dispatch and return type |
| `test_proposer_proposing_validates_against_proposaloutput_with_iter_threading` | Keep | `ProposalOutput.model_validate(raw)` then `assert proposal.model_name == "stub_arch_005_a"` with iter=5 — iter-threading contract |
| `test_record_usage_is_no_op` | Keep | Sets `bridge._token_usage_path = Path("/tmp/should_never_be_written")` then calls `_record_usage(...)` and `assert not bridge._token_usage_path.exists()` — real no-op contract |
| `test_reflect_method_routes_to_synthesiser` | Keep | `raw = bridge.reflect("exp_001", "stub hypothesis", {"final_loss": 0.5})` then `assert raw["conclusion"]` — verifies reflect() routes through stub |
| `test_set_run_context_works_after_init` | Keep | `bridge.set_run_context(workspace=tmp_path, iter=0, ...)` then `assert bridge._token_usage_path == tmp_path / "token_usage.jsonl"` — real context-binding |
| `test_tool_call_raises_not_implemented` | Keep | `pytest.raises(NotImplementedError)` and `assert "tool_call" in str(excinfo.value)` — loud refusal contract |
| `test_tuner_planner_threads_iter_into_slug` | Keep | `bridge._iter = 7` then `assert plan.model_type == "stub_arch_007_a"` — real iter-threading logic |
| `test_tuner_planner_validates_against_experimentplan` | Keep | `plan = ExperimentPlan.model_validate(raw)` and `assert plan.model_type == _synth_stub_model_name(0, "a")` — real schema round-trip on stub output |
| `test_tuner_reflector_returns_required_memory_keys` | Keep | `for key in ("conclusion", "key_factor", "discovery", "memory_update"): assert key in raw` — pins keys the tuner agent reads verbatim |
| `test_unknown_json_label_raises_not_implemented` | Keep | `pytest.raises(NotImplementedError)` and `assert "nonexistent.label" in str(excinfo.value)` with known-label listing check — drift detection |
| `test_unknown_text_label_raises_not_implemented` | Keep | `pytest.raises(NotImplementedError)` on `_synthesise_text("nonexistent.text_label")` with check that known labels appear in error message |
| `test_validator_code_review_passes_with_true` | Keep | `review = LLMCodeReview.model_validate(raw)` then `assert review.passed is True` and `assert review.trainability_concerns == []` — real schema round-trip |

### `tests/unit/agent/llm_bridge/test_synth_stub_model_name.py`

Tests: 6

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_basic_format` | Keep | `assert _synth_stub_model_name(1, "a") == "stub_arch_001_a"` — pins the exact format string; pure function, no mocks |
| `test_determinism_across_calls` | Keep | `a = _synth_stub_model_name(5, "b"); b = _synth_stub_model_name(5, "b"); assert a == b` — pure function determinism |
| `test_distinct_slot_yields_distinct_slug` | Keep | `assert _synth_stub_model_name(3, "a") != _synth_stub_model_name(3, "b")` — tests that slot param differentiates output |
| `test_high_iter_does_not_truncate` | Keep | `assert _synth_stub_model_name(1234, "x") == "stub_arch_1234_x"` — tests that padding is a floor, not a cap |
| `test_iter_zero_pads_to_three_digits` | Keep | `assert _synth_stub_model_name(7, "a") == "stub_arch_007_a"` — deterministic boundary test for zero-padding |
| `test_slug_is_python_identifier_safe` | Keep | `assert _SLUG_PATTERN.match(slug)` with regex `r"^stub_arch_\d{3}_[a-zA-Z0-9_]+$"` — validates identifier-safety contract |

### `tests/unit/agent/llm_bridge/test_template_and_scaffolding.py`

Tests: 5

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_empty_components_stay_empty` | Keep | `assert row["components"] == {}` and `assert "template_and_scaffolding" not in row["components"]` — pins contract that non-proposer calls with `components=None` are not augmented; real guard against accidental 10th-key injection |
| `test_exact_match_yields_zero_value` | Keep | `assert row["components"]["template_and_scaffolding"] == 0` and `assert sum(row["components"].values()) == 100` — pins boundary where 9 keys exactly cover total; verifies key is still present (not omitted) at zero value |
| `test_explicit_empty_components_stay_empty` | Keep | `assert row["components"] == {}` when `components={}` explicitly — pins that an explicit empty dict also does not trigger augmentation; separate code path from None |
| `test_non_empty_components_get_template_scaffolding_key` | Keep | `assert "template_and_scaffolding" in out` and `assert sum(out.values()) == expected_total` — exercises real bridge recording logic that computes the 10th catch-all key; the lossless sum invariant is genuine deterministic business logic |
| `test_overcount_clamps_to_zero` | Keep | `assert row["components"]["template_and_scaffolding"] == 0` when `system_prompt: 1000` but `chars.total = 20` — exercises `max(0, ...)` clamping logic; a real edge case that would produce a negative value without the clamp |

### `tests/unit/agent/ml_code_validator_agent/test_inheritance_check.py`

Tests: 9

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_capability_without_pattern_skipped` | Keep | `assert passed is True` and `assert any("SKIPPED" in n for n in notes)` for `"receptive_field"` with `pattern: None` — verifies pattern=None short-circuits to skip |
| `test_case_insensitive_pattern` | Keep | `source = "self.embed = nn.embedding(256, 32)"` (lowercase) with `assert passed is True` — tests that `re.IGNORECASE` flag is applied; would catch a regression if flags were removed |
| `test_empty_claims_passes` | Keep | `passed, notes = _check_inherited_components(WAVENET_LIKE_SOURCE, [], SAMPLE_VOCAB)` then `assert passed is True` and `assert notes == []` — empty-list boundary case, verifies no vacuous failures |
| `test_missing_component_fails` | Keep | `assert passed is False` and `assert any("NOT FOUND" in n for n in notes)` — verifies that claiming spectral_conv (FFT) when source has none triggers a real failure result |
| `test_mixed_pass_and_fail` | Keep | `assert len(found) == 1` and `assert len(not_found) == 1` — verifies that partial failure produces correct per-item verdicts and `passed is False` when any item fails |
| `test_no_vocab_seed_all_skipped` | Keep | `_check_inherited_components(WAVENET_LIKE_SOURCE, claims, None)` then `assert passed is True` and `assert all("SKIPPED" in n for n in notes)` — verifies None vocab_seed skips all checks gracefully |
| `test_simple_source_fails_dilation_claim` | Keep | `passed, _notes = _check_inherited_components(SIMPLE_CNN_SOURCE, claims, SAMPLE_VOCAB)` then `assert passed is False` — verifies plain CNN (no dilation keyword) correctly fails the dilated_causal_conv claim |
| `test_unknown_vocab_entry_skipped` | Keep | `assert passed is True` and `assert any("SKIPPED" in n for n in notes)` — verifies soft-skip for component not in vocab; tests the branching logic for unknown vocab entries |
| `test_valid_claims_pass` | Keep | `passed, notes = _check_inherited_components(WAVENET_LIKE_SOURCE, claims, SAMPLE_VOCAB)` with `assert passed is True` and `assert all("FOUND" in n for n in notes)` — real regex matching against hardcoded Python source; pure deterministic function, no mocks |

### `tests/unit/agent/ml_code_validator_agent/test_validator_agent.py`

Tests: 63

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_51_chars_returns_true` | Keep | `assert ok is True` with `"x" * 51` — boundary |
| `test_all_float_returns_true` | Keep | `assert ok is True` with `{"lr": 1e-3, "dropout": 0.1}` |
| `test_all_int_returns_true` | Keep | `assert ok is True` with `{"depth": 2, "channels": 64}` — real `_check_config_fields` logic |
| `test_all_pass_error_message_is_none` | Keep | `assert out.error_message is None` — no spurious error message |
| `test_all_pass_individual_booleans` | Keep | `assert out.plugin_registered is True` through `assert out.llm_review_passed is True` — all boolean fields |
| `test_all_pass_model_type_set` | Keep | `assert out.model_type == "test_model"` — model_type propagation |
| `test_all_pass_output_is_validator_output` | Keep | `assert isinstance(out, ValidatorOutput)` — schema contract |
| `test_all_pass_returns_passed_true` | Keep | `assert out.passed is True` with real plugin, passing subprocess mock, and LLM mock — integration of all checks |
| `test_backward_failure_returns_true_false_message` | Keep | `assert inst_ok is True` and `assert grad_ok is False` — shape ok but detached output fails gradient check |
| `test_bool_returns_true` | Keep | `assert ok is True` with `{"use_bias": True, "depth": 3}` |
| `test_config_fields_failure_sets_passed_false` | Keep | `assert out.config_fields_valid is False` with `{"depth": 2, "bad": [1, 2, 3]}` |
| `test_description_failure_sets_passed_false` | Keep | `assert out.description_valid is False` with `"too short"` description |
| `test_dict_value_returns_false` | Keep | `assert "nested" in err` with `{"nested": {"a": 1}}` |
| `test_empty_dict_returns_true` | Keep | `assert ok is True` with `{}` — empty dict edge case |
| `test_empty_file_returns_false` | Keep | `assert ok is False` with empty string — edge case |
| `test_error_message_does_not_mention_inheritance_when_passed` | Keep | `assert out.error_message is None` when only inheritance fails — error_message must remain None |
| `test_exactly_50_chars_returns_false` | Keep | `assert ok is False` with `"x" * 50` — boundary (50 chars fails, must be >50) |
| `test_excludes_expert_when_empty` | Keep | `assert "Expert Guidance" not in prompt` with `expert_advice = ""` — empty string guard |
| `test_expert_advice_before_human_advice` | Keep | `assert expert_pos < human_pos` by `prompt.index("Expert Guidance")` and `prompt.index("Human Guidance")` — ordering |
| `test_failed_test_output_included_in_review_prompt` | Keep | `assert "FAILED test_forward" in user_prompt` and `assert "Pytest Output" in user_prompt` — prompt construction |
| `test_failing_tests_return_false` | Keep | `assert ok is False` with `returncode=1` — routing logic |
| `test_forward_shape_mismatch_returns_false_false_message` | Keep | `assert "shape" in err.lower() or "does not match" in err.lower()` with real WrongShapeModel returning `[B, T, 32]` |
| `test_import_error_returns_false_false_message` | Keep | `assert inst_ok is False` and `assert grad_ok is False` — both fail on import error |
| `test_import_error_returns_false_with_message` | Keep | `assert ok is False` and `assert "Import error" in err` with `"import nonexistent_module_xyz"` — real import error path |
| `test_includes_expert_advice_string` | Keep | `assert "Expert Guidance" in prompt` and `assert "gradient flow" in prompt` with real `_build_review_prompt` call |
| `test_includes_structured_expert_advice` | Keep | `assert "residual connections" in prompt` and `assert "vanishing gradients" in prompt` with `ExpertAdvice` object |
| `test_inheritance_miss_still_passes_when_trainable` | Keep | `assert out.passed is True` and `assert out.inheritance_check_passed is False` and `assert "spectral_conv" in out.inheritance_deviation_notes` — inheritance decoupling |
| `test_inheritance_pass_leaves_deviation_notes_none` | Keep | `assert out.inheritance_check_passed is True` and `assert out.inheritance_deviation_notes is None` and `assert out.unverified_inherited_components == []` |
| `test_instantiation_error_included_in_review_prompt` | Keep | `assert "Runtime Error" in user_prompt` with broken-shape plugin — instantiation error injected into review prompt |
| `test_list_value_returns_false` | Keep | `assert "kernel_sizes" in err` with `{"kernel_sizes": [3, 5, 7]}` — field name in error message |
| `test_llm_bridge_called_with_prompts` | Keep | `assert inp.model_description in user_prompt` and `assert inp.mathematical_definition in user_prompt` — prompt content validation |
| `test_llm_review_failure_sets_passed_false` | Keep | `assert out.llm_review_passed is False` and `assert out.passed is False` with failing review dict |
| `test_llm_review_fields_in_output` | Keep | `assert out.llm_review_spec_alignment is True` and `assert out.llm_review_trainability_concerns == []` — LLM review fields in output |
| `test_llm_review_parsed_into_llm_code_review` | Keep | `assert out.llm_review_passed is True` and `assert "matches specification" in out.llm_review_notes` — LLM response parsed into correct fields |
| `test_missing_config_class_returns_false` | Keep | `assert "PLUGIN_CONFIG_CLASS" in err` — attribute detection |
| `test_missing_file_returns_false` | Keep | `assert "not found" in err` for nonexistent path — error handling |
| `test_missing_model_class_returns_false` | Keep | `assert "PLUGIN_MODEL_CLASS" in err` — attribute detection |
| `test_missing_model_type_returns_false` | Keep | `assert "PLUGIN_MODEL_TYPE" in err` after replacing attribute name — attribute detection logic |
| `test_mixed_returns_false_names_all_bad_fields` | Keep | `assert "bad_list" in err` and `assert "bad_dict" in err` — all bad fields named |
| `test_mixed_scalar_returns_true` | Keep | `assert ok is True` with `VALID_CONFIG_FIELDS` |
| `test_multiple_failures_all_booleans_correct` | Keep | `assert out.plugin_registered is False` and `assert out.tests_passed is False` and `assert out.config_fields_valid is False` — multi-failure combination |
| `test_none_value_returns_false` | Keep | `assert "optional_field" in err` — None rejection |
| `test_output_file_contains_all_check_fields` | Keep | `assert field in data` for all 7 fields — field presence |
| `test_output_file_is_valid_json` | Keep | `assert "passed" in data` and `assert "model_type" in data` from `json.loads(...)` — JSON validity |
| `test_output_file_model_type_correct` | Keep | `assert data["model_type"] == "test_model"` — correct model_type in file |
| `test_output_file_written` | Keep | `assert (tmp_path / "validation_myrun.json").exists()` — file persistence |
| `test_output_returned_on_fail` | Keep | `assert "FAILED" in output` — output captured on failure path |
| `test_output_returned_on_pass` | Keep | `assert "3 passed" in output` — output captured on success path |
| `test_passed_test_output_not_in_review_prompt` | Keep | `assert "Pytest Output" not in user_prompt` — passing tests not forwarded to LLM |
| `test_passing_tests_return_true` | Keep | `assert ok is True` after patching `subprocess.run` with `returncode=0` — return-code routing logic (mock is necessary; assertion is on routing not mock value) |
| `test_plugin_failure_error_message_present` | Keep | `assert out.error_message is not None` — error message set on failure |
| `test_plugin_failure_sets_passed_false` | Keep | `assert out.passed is False` and `assert out.plugin_registered is False` with bad import plugin |
| `test_stdout_and_stderr_concatenated` | Keep | `assert "stdout content" in output` and `assert "stderr content" in output` — concatenation logic |
| `test_syntax_error_returns_false` | Keep | `assert ok is False` with `"def broken(:\n    pass\n"` — syntax error handling |
| `test_test_failure_sets_passed_false` | Keep | `assert out.passed is False` and `assert out.tests_passed is False` with `returncode=1` |
| `test_test_failure_test_output_captured` | Keep | `assert "FAILED" in out.test_output` — test output captured on failure |
| `test_test_output_included_on_pass` | Keep | `assert "passed" in out.test_output` — test output present on success |
| `test_too_short_content_returns_false` | Keep | `assert "too short" in err` with `"short"` content — length check |
| `test_trainability_failure_still_fails_even_when_inheritance_ok` | Keep | `assert out.passed is False` and `assert out.tests_passed is False` — inheritance cannot rescue non-trainable |
| `test_valid_description_returns_true` | Keep | `assert ok is True` with real file write of `VALID_DESCRIPTION` — file-read logic |
| `test_valid_plugin_returns_true` | Keep | `assert ok is True` and `assert err is None` after writing `VALID_PLUGIN_SRC` to disk and calling real `_check_plugin(str(path))` |
| `test_valid_plugin_returns_true_true_none` | Keep | `inst_ok, grad_ok, _otype_ok, err = _check_instantiation_and_gradient(str(path))` then `assert inst_ok is True` and `assert grad_ok is True` — real torch model loaded and gradient check run |
| `test_workspace_created_if_missing` | Keep | `assert (nested / "validation_r1.json").exists()` with deep non-existent path — mkdir-on-write |

### `tests/unit/agent/ml_code_validator_agent/test_validator_schemas.py`

Tests: 8

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_custom_llm_provider_overrides_default` | Keep | `ValidatorInput(**VALID_INPUT_KWARGS, llm_provider="openai")` then `assert inp.llm_provider == "openai"` — verifies explicit override propagates |
| `test_failed_llm_review_records_concerns_list` | Keep | `assert len(out.llm_review_trainability_concerns) == 1` — pins list cardinality as a separate invariant from the parametrized failure scenarios |
| `test_failure_scenarios_preserve_per_stage_flags` | Keep | `assert getattr(out, expected_field) == expected_value` across 6 failure shapes — verifies per-stage flags round-trip correctly through Pydantic |
| `test_missing_required_field_raises` | Keep | `with pytest.raises(ValidationError) as exc: ValidatorInput(**kwargs)` and `assert missing_field in str(exc.value)` — parametrized over 6 required fields; pins that each triggers a named ValidationError |
| `test_passed_scenarios_construct_and_expose_optional_fields` | Keep | `assert out.error_message is None` and `assert out.test_output is None` for no-override case — pins optional field defaults |
| `test_review_scenarios` | Keep | `assert review.passed is expected_passed` and `assert len(review.trainability_concerns) == expected_concerns_len` — validates LLMCodeReview schema with both pass and fail shapes |
| `test_storage_custom_overrides_default` | Keep | `assert inp.storage.local.workspace == "/reports"` — verifies nested storage override |
| `test_valid_construction_populates_all_documented_fields` | Keep | `assert inp.storage.backend == "local"` and `assert inp.llm_provider == "gemini"` and `assert inp.llm_model_id == "gemini-3.1-flash-lite-preview"` — pins default values for documented fields |

### `tests/unit/agent/ml_model_implementor/test_baseline_self_check.py`

Tests: 17

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_accepting_baseline_passes_validate_code` | Keep | `result = MLModelImplementor._validate_code(self._build_valid_code(), inp)` then `assert result is None` — integration test: valid baseline passes the full validate_code gate |
| `test_baseline_subset_passes` | Keep | `assert _check_baseline_schema_compatibility(_PLUGIN_MULTIPLE_OF_2, "m", bc) is None` where `bc = {"model_config": {"channels": 64}}` — partial dict fills from defaults |
| `test_channels_multiple_of_8_rejection` | Keep | `err = _check_baseline_schema_compatibility(_PLUGIN_CHANNELS_MULTIPLE_OF_8, "m", bc)` where `bc = {"model_config": {"channels": 35}}` — tests a specific multiple_of=8 violation |
| `test_earlier_checks_take_precedence` | Keep | `bad_code["config_fields_code"] = "    this is = not valid python"` then `assert "Baseline self-check" not in result` — ordering guarantee: syntax check fires before baseline check |
| `test_empty_baseline_config_returns_none` | Keep | `assert _check_baseline_schema_compatibility(_PLUGIN_NO_CONSTRAINTS, "m", {}) is None` — deterministic: empty baseline → no error; tests a boundary condition in the compatibility helper |
| `test_empty_baseline_does_not_add_error` | Keep | `inp = self._inp({})` → `assert result is None` — empty baseline is a no-op; backward-compat guard |
| `test_empty_model_config_returns_none` | Keep | `assert _check_baseline_schema_compatibility(_PLUGIN_NO_CONSTRAINTS, "m", bc) is None` where `bc = {"model_config": {}}` — guard for empty model_config dict |
| `test_error_includes_the_offending_model_config` | Keep | `assert "refiner_kernel_size" in err; assert "5" in err` — verifies offending values are embedded in error text for LLM actionability |
| `test_error_instructs_relaxation_not_mutation_of_segmentation_size` | Keep | `assert "segmentation_size" in err` and `assert "not change" in low or "may not change" in low or ...` — ownership boundary instruction; verifies specific error text |
| `test_extra_fields_silently_dropped_is_fine` | Keep | `assert _check_baseline_schema_compatibility(_PLUGIN_MULTIPLE_OF_2, "m", bc) is None` where `bc` has `unused_extra_field: 99` — confirms Pydantic's default extra='ignore' behavior |
| `test_malformed_plugin_returns_none` | Keep | `malformed = "this is not valid python ]]]"` → `assert _check_baseline_schema_compatibility(malformed, "m", bc) is None` — graceful error: unparseable plugin doesn't raise |
| `test_missing_model_config_returns_none` | Keep | `assert _check_baseline_schema_compatibility(_PLUGIN_NO_CONSTRAINTS, "m", bc) is None` where `bc = {"train_config": {"lr": 1e-4}}` — guard for baseline without model_config key |
| `test_multiple_of_constraint_violation` | Keep | `err = _check_baseline_schema_compatibility(_PLUGIN_MULTIPLE_OF_2, "m", bc)` then `assert "Baseline self-check failed" in err; assert "refiner_kernel_size" in err; assert "RELAX" in err or "relax" in err` — the canonical exploit_cnn failure case; verifies exact error message c... |
| `test_none_baseline_config_returns_none` | Keep | `assert _check_baseline_schema_compatibility(_PLUGIN_NO_CONSTRAINTS, "m", None) is None` — defensive: None baseline doesn't crash |
| `test_plugin_missing_plugin_config_class_returns_none` | Keep | plugin with `x = 1` and no PLUGIN_CONFIG_CLASS → `assert _check_baseline_schema_compatibility(plugin_no_class, "m", bc) is None` — missing class is not an error for this helper |
| `test_rejecting_baseline_fails_validate_code` | Keep | `result = MLModelImplementor._validate_code(self._build_valid_code(), inp)` with `refiner_kernel_size=5` → `assert "Baseline self-check failed" in result` — the check is wired into the existing validate gate |
| `test_schema_accepts_baseline_values` | Keep | `assert _check_baseline_schema_compatibility(_PLUGIN_MULTIPLE_OF_2, "m", bc) is None` where `bc` has `refiner_kernel_size: 4` — validates that conforming values pass |

### `tests/unit/agent/ml_model_implementor/test_config_adjustment_schema.py`

Tests: 22

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_at_exactly_20pct_passes` | Keep | `ConfigAdjustment(original_value=100, adjusted_value=120, ...)` — pins inclusive boundary; `adjusted_value=120` is exactly 20% |
| `test_beyond_20pct_rejected` | Keep | `with pytest.raises(ValidationError) as exc: ConfigAdjustment(original_value=100, adjusted_value=75, ...)` and `assert "exceeding" in msg or "deviates" in msg` and `assert "20" in msg` — pins rejection message content |
| `test_bool_adjusted_rejected` | Keep | `ConfigAdjustment(original_value=1, adjusted_value=True, ...)` raises with `"bool"` in message — pins bool subclasses int but must still be rejected |
| `test_bool_original_rejected` | Keep | `with pytest.raises(ValidationError) as exc: ConfigAdjustment(original_value=True, adjusted_value=False, ...)` and `assert "bool" in str(exc.value).lower()` — bool is categorical, must be rejected |
| `test_defaults_to_empty_dict` | Keep | `out = ImplementorOutput(**_BASE_OUTPUT_KW)` then `assert out.baseline_config_adjustments == {}` — pins backward compat default |
| `test_delta_threshold_matches_locked_decision` | Keep | `assert _MAX_ADJUSTMENT_DELTA == 0.20` — pins the ±20% threshold to its locked design decision |
| `test_dict_rejected` | Keep | `with pytest.raises(ValidationError): ConfigAdjustment(original_value={"a":1}, adjusted_value={"a":2}, ...)` — dict type rejected |
| `test_forbidden_segmentation_size_rejected` | Keep | `with pytest.raises(ValidationError) as exc:` for `"segmentation_size"` key and `assert "proposer" in msg.lower()` — pins ownership boundary and error message |
| `test_forbidden_set_contains_segmentation_size` | Keep | `assert "segmentation_size" in _FORBIDDEN_ADJUSTMENT_FIELDS` — pins the documented ownership rule |
| `test_forbidden_set_is_frozen` | Keep | `assert isinstance(_FORBIDDEN_ADJUSTMENT_FIELDS, frozenset)` — guards against accidental runtime mutation |
| `test_list_rejected` | Keep | `with pytest.raises(ValidationError): ConfigAdjustment(original_value=[1,2,3], adjusted_value=[1,2], ...)` — list type rejected |
| `test_mixed_adjustments_reject_on_forbidden` | Keep | `with pytest.raises(ValidationError) as exc:` with one valid and one forbidden key — verifies single forbidden key rejects the whole dict |
| `test_mixed_int_float_within_range` | Keep | `ConfigAdjustment(original_value=10, adjusted_value=10.5, ...)` then `assert adj.adjusted_value == 10.5` — pins mixed int/float within 5% passes |
| `test_multiple_valid_adjustments_accepted` | Keep | `assert len(out.baseline_config_adjustments) == 2` — two valid model-internal adjustments both accepted |
| `test_negative_delta_at_boundary_passes` | Keep | `ConfigAdjustment(original_value=5, adjusted_value=4, ...)` — 5→4 is exactly 20% down; pins boundary applies symmetrically |
| `test_reason_missing_rejected` | Keep | `with pytest.raises(ValidationError): ConfigAdjustment(original_value=100, adjusted_value=110)` without reason — missing required field |
| `test_reason_required_non_empty` | Keep | `with pytest.raises(ValidationError) as exc: ConfigAdjustment(original_value=100, adjusted_value=110, reason="")` and `assert "reason" in str(exc.value).lower()` — empty reason rejected |
| `test_string_rejected` | Keep | `ConfigAdjustment(original_value="relu", adjusted_value="gelu", ...)` raises with `"numeric"` in message — string values must be rejected |
| `test_valid_model_internal_adjustment_accepted` | Keep | `assert "refiner_kernel_size" in out.baseline_config_adjustments` and `assert out.baseline_config_adjustments["refiner_kernel_size"].adjusted_value == 4` — end-to-end valid adjustment |
| `test_within_20pct_passes` | Keep | `ConfigAdjustment(original_value=100, adjusted_value=110, reason="snap to multiple_of=10")` then `assert adj.adjusted_value == 110` — verifies in-range numeric passes |
| `test_zero_original_requires_zero_adjusted` | Keep | `with pytest.raises(ValidationError) as exc: ConfigAdjustment(original_value=0, adjusted_value=5, ...)` and `assert "undefined" in ... or "zero" in ...` — pins that zero original with nonzero adjusted (undefined relative delta) is rejected |
| `test_zero_original_zero_adjusted_passes` | Keep | `ConfigAdjustment(original_value=0, adjusted_value=0, ...)` passes — zero→zero no-op is valid |

### `tests/unit/agent/ml_model_implementor/test_implementor_agent.py`

Tests: 56

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_all_fields_declared_returns_empty` | Keep | `assert _check_config_field_consistency(code) == []` — pure function with hardcoded config dict, tests that declared fields satisfy config.x references |
| `test_class_name_single_char_parts` | Keep | `assert _class_name("s4_model") == "S4Model"` — edge case with single-char prefix |
| `test_class_name_single_word` | Keep | `assert _class_name("tcn") == "Tcn"` — pure function, deterministic, no mock |
| `test_class_name_three_words` | Keep | `assert _class_name("gated_dilated_tcn") == "GatedDilatedTcn"` — three-part conversion |
| `test_class_name_two_words` | Keep | `assert _class_name("attn_unet") == "AttnUnet"` — pure CamelCase conversion |
| `test_config_fields_dict_sufficient` | Keep | `assert _check_config_field_consistency(code) == []` when field in dict but not code string — verifies alternative declaration path |
| `test_config_fields_from_llm` | Keep | `assert output.config_fields == {"channels": 64, "depth": 4}` — verifies that `FAKE_CODE_RESPONSE["config_fields"]` flows through to the output schema |
| `test_description_file_contains_description` | Keep | `assert "A gated dilated TCN for signal denoising." in content` — verifies description text from input flows into description file |
| `test_description_file_contains_forward_contract` | Keep | `assert "[B, T] int64" in content` and `assert "[B, 256, T] float32" in content` — verifies forward contract strings appear in description |
| `test_description_file_contains_mathematical_definition` | Keep | `assert "tanh" in content` — verifies math definition content appears in description file |
| `test_description_file_contains_model_name` | Keep | `assert "GatedDilatedTcn" in content` — verifies CamelCase model name appears in description file |
| `test_description_file_path_in_output` | Keep | `assert os.path.isabs(output.description_file_path)` and `assert output.description_file_path.endswith("description.md")` and `assert os.path.exists(output.description_file_path)` — verifies description path contract in output schema |
| `test_description_file_written` | Keep | `assert desc_path.exists()` where `desc_path = tmp_path / "models" / "gated_dilated_tcn" / "description.md"` — verifies file I/O side effect |
| `test_empty_init_body_returns_empty` | Keep | `assert _check_config_field_consistency(code) == []` with empty init_body — boundary case |
| `test_excludes_expert_when_empty` | Keep | `assert "Expert Guidance" not in prompt` when `inp.expert_advice = ""` — verifies conditional section exclusion |
| `test_expert_advice_before_human_advice` | Keep | `expert_pos = prompt.index("Expert Guidance")` and `human_pos = prompt.index("Human Guidance")` then `assert expert_pos < human_pos` — verifies prompt ordering |
| `test_generate_called_once` | Refactor | `agent_with_mocks.bridge.generate.assert_called_once()` — assertion is only on mock call count; same issue as test_generate_text_called_once |
| `test_generate_text_called_before_generate` | Keep | `assert call_order == ["generate_text", "generate"]` using side_effect to capture ordering — tests the two-step plan's sequential execution order, not just call counts |
| `test_generate_text_called_once` | Refactor | `agent_with_mocks.bridge.generate_text.assert_called_once()` — assertion is only on the mock's own call count; the logic under test (that generate_text is called exactly once) is real but the sole assertion is a mock-call count with no content verification |
| `test_includes_expert_advice_string` | Keep | `prompt = _build_reasoning_prompt(inp)` then `assert "Expert Guidance" in prompt` and `assert "grouped convolutions" in prompt` — pure function test on prompt assembly with real string content |
| `test_includes_structured_expert_advice` | Keep | `assert "efficient conv layers" in prompt` and `assert "depthwise separable" in prompt` — verifies ExpertAdvice fields are rendered into the prompt |
| `test_mathematical_definition_from_input` | Keep | `assert output.mathematical_definition == inp.mathematical_definition` — verifies pass-through of mathematical definition |
| `test_max_retries_exhausted_raises` | Keep | `with pytest.raises(ValueError, match="Code generation failed after 3 attempts")` and `assert agent.bridge.generate.call_count == 3` — tests exact retry count (1 initial + 2 retries = 3) |
| `test_missing_attribute_returns_error` | Keep | `assert "PLUGIN_MODEL_CLASS" in result` — verifies that missing attribute produces an error string containing the missing name |
| `test_missing_field_returns_name` | Keep | `assert _check_config_field_consistency(code) == ["embed_dim"]` — verifies detection of config.embed_dim reference when embed_dim not in config_fields |
| `test_model_description_from_input` | Keep | `assert output.model_description == inp.model_description` — verifies pass-through of model description |
| `test_model_file_path_is_absolute` | Keep | `assert os.path.isabs(output.model_file_path)` — verifies path absoluteness contract |
| `test_model_type_matches_input` | Keep | `assert output.model_type == "gated_dilated_tcn"` — verifies output.model_type propagation from input.model_name |
| `test_multiple_missing_fields` | Keep | `assert "embed_dim" in missing` and `assert "hidden_dim" in missing` — verifies detection of multiple missing fields simultaneously |
| `test_output_is_implementor_output` | Keep | `assert isinstance(output, ImplementorOutput)` — verifies the run() method returns the correct Pydantic type |
| `test_output_record_contains_model_type` | Keep | `assert data["model_type"] == "gated_dilated_tcn"` — verifies model_type field in persisted JSON |
| `test_output_record_is_valid_json` | Keep | `data = json.loads((tmp_path / "implementor_unit_test.json").read_text())` then `assert isinstance(data, dict)` — verifies JSON round-trip |
| `test_output_record_written` | Keep | `assert (tmp_path / "implementor_unit_test.json").exists()` — verifies persistence side effect |
| `test_plugin_contains_llm_config_fields` | Keep | `assert "channels" in content` and `assert "depth" in content` — verifies that LLM-returned `config_fields_code` with "channels" and "depth" is injected into the generated plugin |
| `test_plugin_file_written` | Keep | `assert os.path.exists(os.path.join(inp.plugin_dir, "gated_dilated_tcn.py"))` — verifies file I/O side effect; cannot be checked by static analysis |
| `test_plugin_has_config_class_assignment` | Keep | `assert "PLUGIN_CONFIG_CLASS = GatedDilatedTcnConfig" in content` — verifies class name derivation is embedded correctly in the generated plugin |
| `test_plugin_has_correct_class_name` | Keep | `assert "class GatedDilatedTcnConfig(BaseModel):" in content` and `assert "class GatedDilatedTcn(nn.Module):" in content` — verifies CamelCase class name derivation embedded in template |
| `test_plugin_has_model_class_assignment` | Keep | `assert "PLUGIN_MODEL_CLASS = GatedDilatedTcn" in content` — verifies model class assignment in generated file |
| `test_plugin_has_model_type_constant` | Keep | `assert 'PLUGIN_MODEL_TYPE = "gated_dilated_tcn"' in content` — reads written file and checks template assembly produced correct constant string |
| `test_reasoning_injected_into_code_prompt` | Keep | `code_user_prompt = agent_with_mocks.bridge.generate.call_args[0][1]` then `assert FAKE_REASONING in code_user_prompt` — inspects the actual prompt string passed to generate; tests that reasoning text flows into the code prompt |
| `test_repair_called_on_first_failure` | Keep | `assert agent.bridge.generate.call_count == 2` and `isinstance(output, ImplementorOutput)` with `side_effect = [bad_code, good_code]` — verifies repair is triggered and succeeds; count==2 confirms exactly one repair |
| `test_repair_prompt_contains_error` | Keep | `repair_user_prompt = agent.bridge.generate.call_args_list[1][0][1]` then `assert "embed_dim" in repair_user_prompt` and `assert "Error" in repair_user_prompt` — verifies the error content is embedded in the repair prompt |
| `test_run_raises_after_retries_exhausted` | Keep | `with pytest.raises(ValueError, match="Code generation failed after")` — tests retry loop exhaustion; bridge is mocked but assertion is on the error message pattern |
| `test_run_raises_on_missing_config_field` | Keep | `with pytest.raises(ValueError, match="embed_dim")` — integration: run() raises ValueError with specific field name when config_field is missing; mocks bridge but assertion is on the raised error content |
| `test_runtime_error_returns_error` | Keep | `assert "embed_dim" in result` when code references undefined `config.embed_dim` — verifies runtime error capture |
| `test_second_retry_succeeds` | Keep | `assert isinstance(output, ImplementorOutput)` and `assert agent.bridge.generate.call_count == 3` with `side_effect = [bad_code, bad_code, good_code]` — verifies second repair path |
| `test_shape_mismatch_returns_error` | Keep | `assert "shape mismatch" in result` when `nn.Conv1d(config.channels, 128, 1)` returns wrong shape — verifies runtime shape checking |
| `test_successful_first_attempt_no_repair` | Keep | `assert agent_with_mocks.bridge.generate.call_count == 1` — verifies repair loop is NOT entered when first attempt succeeds; not just call count, but the count being 1 specifically means no spurious repair |
| `test_template_fields_accepted` | Keep | `assert _check_config_field_consistency(code) == []` with `"config.segmentation_size"` — verifies template-provided fields are not flagged as missing |
| `test_test_file_has_config_test` | Keep | `assert "def test_config_instantiation" in content` — verifies test scaffold contains config test |
| `test_test_file_has_nan_test` | Keep | `assert "def test_forward_no_nan" in content` — verifies test scaffold contains the NaN test |
| `test_test_file_has_shape_test` | Keep | `assert "def test_forward_shape" in content` — verifies test scaffold contains the required shape test function |
| `test_test_file_imports_correct_module` | Keep | `assert "from gated_dilated_tcn import PLUGIN_MODEL_CLASS, PLUGIN_CONFIG_CLASS" in content` — verifies the generated test file imports from the correct module name |
| `test_test_file_path_is_absolute` | Keep | `assert os.path.isabs(output.test_file_path)` — verifies path absoluteness contract for test file |
| `test_test_file_written` | Keep | `assert os.path.exists(os.path.join(inp.test_dir, "test_gated_dilated_tcn.py"))` — verifies test file I/O side effect |
| `test_valid_plugin_returns_none` | Keep | `assert _smoke_test_plugin(self.VALID_PLUGIN, "test_model") is None` — executes real plugin code via sandbox, verifies shape-correct plugin passes |

### `tests/unit/agent/ml_model_implementor/test_implementor_schemas.py`

Tests: 9

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_custom_plugin_and_test_dirs` | Keep | `assert inp.plugin_dir == "/custom/models"` and `assert inp.test_dir == "/custom/tests"` — validates that custom override fields are preserved through Pydantic construction |
| `test_mathematical_definition_present` | Keep | `assert "tanh" in out.mathematical_definition` — validates math string content survives schema construction |
| `test_missing_mathematical_definition_raises` | Keep | `with pytest.raises(ValidationError)` when `mathematical_definition` is omitted — real required-field validation |
| `test_missing_model_description_raises` | Keep | `assert "model_description" in str(exc.value)` — required-field enforcement |
| `test_missing_model_file_path_raises` | Keep | `with pytest.raises(ValidationError)` when `model_file_path` is omitted — required-field enforcement on output schema |
| `test_missing_model_name_raises` | Keep | `with pytest.raises(ValidationError) as exc:` and `assert "model_name" in str(exc.value)` — real Pydantic required-field enforcement; catches schema regressions |
| `test_model_description_present` | Keep | `assert "gated TCN" in out.model_description` — validates string content survives schema round-trip without truncation |
| `test_storage_independent_of_plugin_dir` | Keep | `assert inp.storage.local.workspace == "/runs"` and `assert inp.plugin_dir == "agent_generated/models"` — pins that storage config and plugin_dir are orthogonal fields and do not interfere |
| `test_valid` | Keep | Asserts default field values after `ImplementorInput(...)` construction (plugin_dir, test_dir, storage.backend) — pure Pydantic schema test |

### `tests/unit/agent/ml_model_proposal_agent/test_agent_cards.py`

Tests: 26

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_accepts_agent_cards` | Keep | `inp = ProposalInput(..., agent_cards=[card]); assert len(inp.agent_cards) == 1; assert inp.agent_cards[0].agent_name == "ml_literature_review"` — schema coercion of typed list |
| `test_accepts_agent_cards_as_dicts` | Keep | `inp = ProposalInput(..., agent_cards=[_make_card().model_dump()])` — Pydantic coercion from dict |
| `test_accepts_dicts` | Keep | `result = render_agent_cards([_make_card().model_dump()]); assert "ml_literature_review" in result` — accepts dict input |
| `test_agent_cards_none_defaults_to_empty` | Keep | `inp = local_full_context(output, storage, agent_cards=None); assert inp.agent_cards == []` — None coerced to empty list |
| `test_agent_cards_passed_through` | Keep | `inp = local_full_context(output, storage, agent_cards=[card]); assert len(inp.agent_cards) == 1; assert inp.agent_cards[0].agent_name == "ml_literature_review"` — protocol kwarg pass-through |
| `test_defaults_to_empty_list` | Keep | `inp = ProposalInput(...); assert inp.agent_cards == []` — default value on schema field |
| `test_different_cite_ids_both_rendered` | Keep | `assert "arxiv_001" in result; assert "arxiv_002" in result` — distinct cite_ids both appear |
| `test_duplicate_cite_id_deduplicated` | Keep | `result = render_expert_context(items)` with two same `cite_id` → `assert result.count("arxiv_001") == 1; assert "second version" in result; assert "first version" not in result` — last-wins dedup logic |
| `test_empty_cite_id_dedup` | Keep | two items with `cite_id=""` → `assert "second empty" in result; assert "first empty" not in result` — dedup on empty string key |
| `test_empty_list_returns_empty_string` | Keep | `assert render_agent_cards([]) == ""` — deterministic: empty input → empty string |
| `test_expertise_domain_max_length_enforced` | Keep | `with pytest.raises(ValidationError): _make_card(expertise_domain="x" * 301)` — max_length=300 constraint |
| `test_higher_confidence_appears_first` | Keep | `pos_high = result.index("high confidence finding"); pos_low = result.index("low confidence finding"); assert pos_high < pos_low` — confidence-based sort order |
| `test_mindset_none_by_default` | Keep | `inp = local_full_context(output, storage); assert inp.mindset is None` — default None |
| `test_mindset_passed_through` | Keep | `inp = local_full_context(output, storage, mindset="Focus on low-freq recovery."); assert inp.mindset == "Focus on low-freq recovery."` — protocol pass-through |
| `test_missing_required_field_raises` | Keep | `with pytest.raises(ValidationError): AgentCard(role="r", expertise_domain="e", ...)` (missing agent_name) — required field enforcement |
| `test_none_confidence_sorts_last` | Keep | `pos_has = result.index("has confidence"); pos_none = result.index("no confidence"); assert pos_has < pos_none` — None confidence sorts after numeric |
| `test_origin_defaults_to_none` | Keep | `entry = VocabEntry(name="dilated_causal_conv", ...); assert entry.origin is None` — default None for optional field |
| `test_origin_set_for_external_agent` | Keep | `entry = VocabEntry(..., origin="ml_literature_review"); assert entry.origin == "ml_literature_review"; assert entry.proposed_by_run is None` — field set, sibling stays None |
| `test_role_max_length_enforced` | Keep | `with pytest.raises(ValidationError): _make_card(role="x" * 201)` — Pydantic max_length constraint fires at 201 chars |
| `test_same_confidence_all_rendered` | Keep | `assert "item A" in result; assert "item B" in result` — no items dropped when confidence is equal |
| `test_single_card_contains_agent_name` | Keep | `result = render_agent_cards([_make_card()]); assert "ml_literature_review" in result; assert "## External Contributors" in result` — template rendering check |
| `test_single_card_contains_all_fields` | Keep | `assert "Role:" in result; assert "Expertise Domain:" in result; assert "Coverage:" in result; assert "Limitations:" in result; assert "Trust Guidance:" in result` — all fields present in rendered output |
| `test_trust_guidance_max_length_enforced` | Keep | `with pytest.raises(ValidationError): _make_card(trust_guidance="x" * 401)` — max_length=400 constraint |
| `test_trust_guidance_read_before_findings_marker` | Keep | `assert "Read each contributor" in result` — specific instruction string in template |
| `test_two_cards_both_rendered` | Keep | `assert "ml_literature_review" in result; assert "physics_literature_review" in result` — both cards appear in output |
| `test_valid_card` | Keep | `card = _make_card(); assert card.agent_name == "ml_literature_review"; assert card.trust_guidance.startswith("Treat as")` — Pydantic schema validation with real field access |

### `tests/unit/agent/ml_model_proposal_agent/test_audit_components.py`

Tests: 6

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_audit_components_char_accounting_matches_helpers` | Keep | `assert result["components"]["candidates_markdown"] == expected_md_chars` where `expected_md_chars = len(build_candidate_markdown_block([fake_candidate]))` — audit vs helper agreement |
| `test_audit_components_handles_empty_blocks` | Keep | `assert components[k] == 0 for k in (...)` and `assert components["interpretation_json"] == 2` — zero-value and `{}` serialization semantics |
| `test_audit_components_non_candidates_overview_attributed_separately` | Keep | `assert components["non_candidates_overview"] == expected_chars` and `assert components["prior_stage_outputs"] < expected_chars` — no double-counting regression |
| `test_audit_components_returns_all_10_keys_with_full_payload` | Keep | `assert set(result["components"].keys()) == _EXPECTED_KEYS` and `assert result["total_chars"] == sum(result["components"].values())` — 10-key set and sum invariant |
| `test_audit_components_stage_name_passthrough` | Keep | `assert result["stage_name"] == stage_name` for each of three stages — passthrough correctness |
| `test_audit_components_total_chars_is_sum_invariant` | Keep | `assert result["total_chars"] == sum(result["components"].values())` and `assert result["total_chars"] > 0` — property-style invariant |

### `tests/unit/agent/ml_model_proposal_agent/test_baseline_config_validators.py`

Tests: 9

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_empty_baseline_config_no_op` | Keep | `ProposalOutput(..., baseline_config={})` then `assert out.baseline_config == {}` — backward compat |
| `test_invalid_power_of_two_segmentation_raises` | Keep | `with pytest.raises(ValidationError) as exc: _make_output(expert_advice, model_config={"segmentation_size": 16384})` and `assert "16384" in msg; assert "Valid segmentation_size values" in msg` — the LLM's persistent bad value is rejected |
| `test_missing_model_config_no_op` | Keep | `ProposalOutput(..., baseline_config={"train_config": ...})` then `assert "model_config" not in out.baseline_config` — no model_config key → validator is silent |
| `test_missing_segmentation_size_no_op` | Keep | `out = _make_output(expert_advice, model_config={"depth": 4}); assert "segmentation_size" not in out.baseline_config["model_config"]` — validator skips when key absent |
| `test_negative_segmentation_size_raises` | Keep | `with pytest.raises(ValidationError) as exc: _make_output(..., model_config={"segmentation_size": -100})` — negative rejected |
| `test_non_int_segmentation_size_raises` | Keep | `with pytest.raises(ValidationError) as exc: _make_output(..., model_config={"segmentation_size": "16000"})` — string not accepted |
| `test_other_valid_divisors_pass` | Keep | `for seg in (100, 1000, 1250, 16000, 50000): assert TIDMAD.psd_segment_length % seg == 0` and each passes → deterministic loop over known valid values |
| `test_valid_segmentation_size_passes` | Keep | `out = _make_output(expert_advice, model_config={"segmentation_size": 16000}); assert out.baseline_config["model_config"]["segmentation_size"] == 16000` — divisor 16000 of 10_000_000 passes Pydantic validator |
| `test_zero_segmentation_size_raises` | Keep | `with pytest.raises(ValidationError) as exc: _make_output(..., model_config={"segmentation_size": 0})` — zero rejected |

### `tests/unit/agent/ml_model_proposal_agent/test_boldness_enforcement.py`

Tests: 9

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_boldness_error_carries_current_and_predicted_values` | Keep | `assert "5.5" in boldness_error` and `assert "5.75" in boldness_error` — error message includes values |
| `test_boldness_error_injected_into_accumulated` | Keep | `assert any("BOLDNESS_TOO_LOW" in e for e in errors)` extracted from retry prompt via `extract_accumulated_json` |
| `test_boldness_passes_when_above_threshold` | Keep | `assert mock.generate.call_count == 3` with `predicted=6.5` (boldness≈0.18 > 0.05) — no retry when bold |
| `test_boldness_retry_triggered_when_below_threshold` | Keep | `assert mock.generate.call_count == 4` with timid `predicted=5.75` then bold retry — retry logic |
| `test_boldness_uses_absolute_delta` | Keep | `assert mock.generate.call_count == 3` with `predicted=4.5` (negative delta, boldness≈0.18) — absolute value |
| `test_custom_policy_threshold` | Keep | `assert mock.generate.call_count == 4` with `minimum_boldness=0.20` rejecting 0.18 — custom threshold |
| `test_missing_prediction_skips_boldness_check` | Keep | `assert mock.generate.call_count == 3` with `"falsifiable_prediction": None` — None skip |
| `test_no_retry_when_causal_reasoning_stage_absent` | Keep | `assert mock.generate.call_count == 2` when pipeline has no causal_reasoning stage — graceful skip |
| `test_tiny_delta_rejected` | Keep | `assert mock.generate.call_count == 4` with `predicted=5.501` (boldness≈0.000182 < 0.05) — near-zero delta caught |

### `tests/unit/agent/ml_model_proposal_agent/test_citation_discipline.py`

Tests: 14

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_cite_id_absent_from_both_fields_returns_violation` | Keep | `assert len(violations) == 1` and `assert "data_psd_50hz" in violations[0]` and `assert "CITATION_NOT_REFERENCED" in violations[0]` — verifies violation message format |
| `test_cite_id_must_match_verbatim` | Keep | `assert len(violations) == 1` when hypothesis contains `"data_psd_50hz"` but full id is `"data_psd_50hz_peak"` — verifies exact string match (not substring of cite_id) |
| `test_cite_id_present_in_causal_hypothesis` | Keep | `assert violations == []` when `"data_psd_50hz"` appears in causal_hypothesis — verifies substring matching in causal_hypothesis field |
| `test_cite_id_present_in_proposed_change` | Keep | `assert violations == []` when `"data_psd_50hz"` appears in proposed_change — verifies substring matching in proposed_change field |
| `test_empty_citation_list_returns_no_violations` | Keep | `violations = _check_citation_discipline(citation_sources=[], ...)` then `assert violations == []` — pure function, no mock, tests empty-list boundary case |
| `test_empty_citation_sources_no_notes_added` | Keep | `assert violation_notes == []` when `"citation_sources": []` — verifies no phantom violations with empty citations |
| `test_empty_hypothesis_and_change_produces_violation` | Keep | `assert len(violations) == 1` and `assert "data_psd" in violations[0]` with empty hypothesis and change — boundary case |
| `test_existing_memo_consistency_notes_preserved` | Keep | `assert "LLM noted: slight deviation from memo." in output.memo_consistency_notes` — verifies that pre-existing notes from LLM are not overwritten |
| `test_multiple_citations_all_absent` | Keep | `assert len(violations) == 2` and `assert len(cited_ids) == 2` — verifies one violation per absent citation |
| `test_multiple_citations_all_present` | Keep | `assert violations == []` when both `"cite_a"` and `"cite_b"` appear in the text — verifies multi-citation all-present case |
| `test_multiple_citations_one_absent` | Keep | `assert len(violations) == 1` and `assert "cite_b" in violations[0]` — verifies exactly one violation when one of two citations is absent |
| `test_no_violations_when_all_citations_referenced` | Keep | `assert violation_notes == []` — verifies no false positives when all citations are referenced |
| `test_violation_message_names_the_cite_id` | Keep | `assert "phys_axion_mass_bound" in violations[0]` — verifies that the cite_id is embedded verbatim in the violation string |
| `test_violations_appended_to_memo_consistency_notes` | Keep | `violation_notes = [n for n in output.memo_consistency_notes if "CITATION_NOT_REFERENCED" in n]` then `assert len(violation_notes) == 1` — verifies that citation violations are appended to the output schema field; uses mocked LLM bridge but assertion is on the pipeline integra... |

### `tests/unit/agent/ml_model_proposal_agent/test_contract_reassertion.py`

Tests: 14

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_256_denoising_bins_named` | Keep | `assert "256 denoising bins" in spec` — pins fixed output dimension reference |
| `test_baseline_config_pointer_preserved` | Keep | `assert "belong in baseline_config" in spec` — preserved routing instruction |
| `test_causal_masking_named` | Keep | `assert "causal masking" in spec` — pins required design decision label |
| `test_commit_prompt_still_carries_io_contract_line` | Keep | `assert "The forward contract is fixed: input [B, T] int64" in PROPOSAL_COMMIT_PROMPT` — verifies the hard-constraint block in the top-level prompt, not just the field spec |
| `test_contract_fixed_applied_to_256_clause` | Keep | `re.search(r"256 denoising bins[^\"]{0,60}contract-fixed", spec, re.DOTALL) is not None` — pins co-occurrence of both tokens in the same clause |
| `test_contract_fixed_qualifier_present` | Keep | `assert "contract-fixed" in spec` — pins the qualifier that marks 256 as non-tunable |
| `test_field_spec_is_nontrivial_length` | Keep | `assert len(spec) >= 600` — guards against accidental wipe of the Golden Paragraph spec |
| `test_golden_paragraph_header_literal_present` | Keep | `assert "Golden Paragraph" in spec` — pins explicit label so LLM knows the three-sentence opening is a contract |
| `test_input_shape_and_dtype_present` | Keep | `assert "[B, T] int64" in spec` — pins verbatim token in PROPOSAL_COMMIT_PROMPT; a rename silently breaks plugin loader contract |
| `test_no_concrete_dims_clause_preserved` | Keep | `assert "Do NOT include concrete layer dimensions" in spec` — preserved pre-WS-B guardrail |
| `test_output_shape_and_dtype_present` | Keep | `assert "[B, 256, T] float32" in spec` — pins output contract token |
| `test_per_timestep_semantics_named` | Keep | `assert "per-timestep" in spec` — pins semantic label required for LLM contract understanding |
| `test_segment_cross_named` | Keep | `assert "segment-cross" in spec` — pins segmentation semantic label |
| `test_segment_local_named` | Keep | `assert "segment-local" in spec` — pins segmentation semantic label |

### `tests/unit/agent/ml_model_proposal_agent/test_description_truncation.py`

Tests: 5

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_7kb_description_capped` | Keep | `text = "A" * 7168` then `assert len(result) < 1600` and `assert result.startswith("A" * 1500)` and `assert "[...truncated]" in result` — the design-doc example case |
| `test_custom_limit` | Keep | `result = _truncate_description(text, max_chars=200)` then `assert result[:200] == text[:200]` and `assert result.endswith("\n[...truncated]")` — verifies custom max_chars parameter works |
| `test_exact_limit_unchanged` | Keep | `text = "x" * 1500` then `assert _truncate_description(text) == text` — exact-boundary case, verifies no off-by-one in limit check |
| `test_over_limit_truncated_with_marker` | Keep | `assert len(result) == 1500 + len("\n[...truncated]")` and `assert result.endswith("\n[...truncated]")` and `assert result[:1500] == "x" * 1500` — verifies truncation length and marker content |
| `test_short_description_unchanged` | Keep | `assert _truncate_description(text) == text` where `text = "A simple wavenet model..."` — pure function, no mock, verifies pass-through for short text |

### `tests/unit/agent/ml_model_proposal_agent/test_hardware_context_block.py`

Tests: 14

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_budget_equal_to_usable_cap_still_budget_regime` | Keep | `assert "Regime:            BUDGET" in block` with `vram_budget_gb=ctx.usable_cap_gb` — float-epsilon boundary |
| `test_budget_regime_reports_operator_budget_as_effective_cap` | Keep | `assert "Operator budget:   20.00 GB" in block` and `assert "Effective cap:     20.00 GB" in block` |
| `test_budget_regime_still_shows_physical_facts` | Keep | `assert "Total VRAM:        32.00 GB" in block` and `assert "Usable cap (80%):  25.60 GB" in block` |
| `test_device_unavailable_returns_empty_string` | Keep | `assert _render_hardware_context_block(ctx, vram_budget_gb=20.0) == ""` with `device_available=False` |
| `test_device_unavailable_returns_empty_string_when_budget_none` | Keep | `assert _render_hardware_context_block(ctx, vram_budget_gb=None) == ""` with CPU-only ctx |
| `test_instruction_text_appended_in_every_regime` | Keep | `assert "must fit within the **effective cap**" in block` for all three parametrized regimes |
| `test_none_ctx_and_none_budget_returns_empty_string` | Keep | `assert _render_hardware_context_block(None, vram_budget_gb=None) == ""` |
| `test_none_ctx_returns_empty_string` | Keep | `assert _render_hardware_context_block(None, vram_budget_gb=20.0) == ""` — None guard |
| `test_physical_regime_cap_reported_in_regime_line` | Keep | `assert "cap = 25.60 GB" in block` — cap embedded in regime line |
| `test_physical_regime_suppresses_operator_budget_lines` | Keep | `assert "Operator budget" not in block` and `assert "Effective cap" not in block` |
| `test_physical_veto_effective_cap_is_usable_cap_not_budget` | Keep | `assert "Effective cap:     6.40 GB" in block` — cap is usable, not budget |
| `test_selects_budget_regime_when_budget_below_usable_cap` | Keep | `assert "Regime:            BUDGET" in block` with `vram_budget_gb=20.0` and 32 GB GPU |
| `test_selects_physical_regime_when_budget_is_none` | Keep | `assert "Regime:            PHYSICAL" in block` and `assert "no operator budget set" in block` |
| `test_selects_physical_veto_when_budget_exceeds_usable_cap` | Keep | `assert "Regime:            PHYSICAL VETO" in block` with 8 GB GPU and 20 GB budget |

### `tests/unit/agent/ml_model_proposal_agent/test_known_constraints_block.py`

Tests: 10

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_block_calls_out_invalid_powers_of_two` | Keep | `assert "16384" in block` and `assert "INVALID" in block` — tests that specific invalid power-of-two values appear explicitly in the block |
| `test_block_has_high_salience_heading` | Keep | `assert "SYSTEM-ENFORCED DATASET CONSTRAINTS" in block` — tests that the high-salience heading is rendered by the real function |
| `test_block_includes_psd_segment_length` | Keep | `assert "10,000,000" in block or "10000000" in block` — tests that the real `TIDMAD` config's psd_segment_length appears in the rendered block |
| `test_block_lists_valid_divisors` | Keep | `assert "16000" in block` and `assert "1250" in block` and `assert "100" in block` — tests real divisor enumeration logic in the block formatter |
| `test_block_mentions_recovery_hint` | Keep | `assert "16000" in block` — tests that 16000 is the specific recovery hint mentioned in the block, addressing a known LLM failure mode |
| `test_block_precedes_rules_section` | Keep | `constraints_idx = prompt.index("SYSTEM-ENFORCED DATASET CONSTRAINTS")` then `assert constraints_idx < rules_idx` — tests ordering within the rendered prompt: constraints before rules |
| `test_empty_when_dataset_config_none` | Keep | `assert _format_known_constraints_block(None) == ""` — tests the None-input branch of a real formatting function |
| `test_other_stages_unaffected_by_unknown_placeholder` | Keep | `assert "SYSTEM-ENFORCED DATASET CONSTRAINTS" not in prompt` for `comparison_stage` and `causal_reasoning_stage` — tests that other stage templates do not inadvertently include the constraints block content |
| `test_proposing_stage_collapses_block_to_empty_when_none` | Keep | `assert "{known_constraints_block}" not in prompt` — tests placeholder substitution; verifies no leftover braces when block is empty |
| `test_proposing_stage_renders_block_when_supplied` | Keep | `assert "SYSTEM-ENFORCED DATASET CONSTRAINTS" in prompt` — tests real prompt template rendering when `known_constraints_block` is filled in; no mocks |

### `tests/unit/agent/ml_model_proposal_agent/test_phase_b_schemas.py`

Tests: 60

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_aliases_default_empty` | Keep | `assert ve.aliases == []` and two more empty defaults |
| `test_all_kinds_accepted` | Keep | Loop over all valid `kind` values asserting `eci.kind == kind` — enum completeness check |
| `test_boldness_property` | Keep | `expected = abs(2.0 - 1.5) / abs(1.5)` then `assert abs(fp.boldness - expected) < 1e-10` — real computed property logic |
| `test_boldness_range` | Keep | `pytest.raises(ValidationError)` for `minimum_boldness=1.5` |
| `test_boldness_timid_prediction` | Keep | `assert fp.boldness < 0.01` — boundary check for near-equal values |
| `test_boldness_with_zero_current` | Keep | `assert fp.boldness == 0.5 / 1e-6` — pins floor-at-1e-6 logic for zero current_value |
| `test_candidate_with_run` | Keep | `assert ve.tier == "candidate"` and `assert len(ve.seen_in_runs) == 2` |
| `test_citations_exactly_5_ok` | Keep | `assert len(memo.citation_sources) == 5` — boundary at cap |
| `test_citations_max_5` | Keep | `valid_memo["citation_sources"] = ["a","b","c","d","e","f"]` then `pytest.raises(ValidationError)` |
| `test_comparative_analysis_top_k_floor` | Keep | `pytest.raises(ValidationError)` for `comparative_analysis_top_k=0` — floor constraint |
| `test_confidence_range` | Keep | `pytest.raises(ValidationError)` for `confidence=1.5` — range constraint |
| `test_confirmed_status` | Keep | `assert link.status == "confirmed"` — status field acceptance |
| `test_content_max_length` | Keep | `pytest.raises(ValidationError)` for content of length 100001 |
| `test_custom_model_selection` | Keep | `assert config.model_selection.params["models"] == ["wavenet", "gated_fno"]` |
| `test_custom_stages` | Keep | `assert config.stages[0].name == "physics_check"` — stage construction |
| `test_default_empty` | Keep | `assert out.memo_consistency_notes == []` — default for optional list field |
| `test_default_pipeline_empty` | Keep | `assert len(config.stages) == 0` and `assert config.exploration_mode == "auto"` — defaults |
| `test_defaults` | Keep | `assert policy.minimum_boldness == 0.05` and 6 more field assertions — documents all ResearchPolicy defaults |
| `test_description_max_length` | Keep | `pytest.raises(ValidationError)` for description of length 1001 |
| `test_disable_stage` | Keep | `enabled = [s for s in config.stages if s.enabled]` then `assert len(enabled) == 1` — filter logic |
| `test_empty_causal_hypothesis_raises` | Keep | `valid_memo["causal_hypothesis"] = "   "` then `pytest.raises(ValidationError, match="causal_hypothesis cannot be empty")` — whitespace validation |
| `test_evidence_max_length` | Keep | `pytest.raises(ValidationError)` for `contribution_evidence` of length 1001 |
| `test_exploration_mode_options` | Keep | Loop over `["auto", "explore", "exploit"]` asserting acceptance |
| `test_high_risk_policy` | Keep | `assert policy.minimum_boldness == 0.15` and `assert policy.min_runs_for_promotion == 2` |
| `test_invalid_exploration_mode_raises` | Keep | `pytest.raises(ValidationError)` for `exploration_mode="invalid"` |
| `test_invalid_kind_raises` | Keep | `pytest.raises(ValidationError)` for `kind="invalid_kind"` — closed-enum enforcement |
| `test_invalid_output_mode_raises` | Keep | `pytest.raises(ValidationError)` for `output_mode="xml"` |
| `test_invalid_status_coerced_to_proposed` | Keep | `link = ProposedVocabLink.model_validate({..."status": "maybe",...})` then `assert link.status == "proposed"` — coercion-not-rejection behavior |
| `test_invalid_tier_raises` | Keep | `pytest.raises(ValidationError)` for `tier="promoted"` — closed enum |
| `test_key_mechanism_max_length` | Keep | `pytest.raises(ValidationError)` for key_mechanism of length 1001 |
| `test_min_runs_too_low` | Keep | `pytest.raises(ValidationError)` for `min_runs_for_promotion=1` — floor=2 constraint |
| `test_missing_component_raises` | Keep | `pytest.raises(ValidationError)` on missing `component` field |
| `test_missing_feature_raises` | Keep | `pytest.raises(ValidationError)` on missing `feature` field |
| `test_missing_metric_raises` | Keep | `del valid_prediction["metric"]` then `pytest.raises(ValidationError)` — required-field enforcement |
| `test_missing_rationale_raises` | Keep | `del valid_prediction["rationale"]` then `pytest.raises(ValidationError)` — required-field enforcement |
| `test_missing_strengths_raises` | Keep | `del valid_comparison["strengths"]` then `pytest.raises(ValidationError)` |
| `test_model_selection_defaults` | Keep | `assert config.model_selection.method == "top_n"` and `assert config.model_selection.params == {"n": 5}` |
| `test_no_failure_modes_raises` | Keep | `valid_memo["predicted_failure_modes"] = []` then `pytest.raises(ValidationError)` — min-length list constraint |
| `test_optional_fields_default_empty` | Keep | `assert memo.inherited_components == []` and checks two other list defaults |
| `test_output_mode_options` | Keep | `assert s1.output_mode == "json"` and `assert s2.output_mode == "text"` — enum values |
| `test_pipeline_config_carries_policy` | Keep | `assert config.policy.minimum_boldness == 0.2` — nested policy field |
| `test_pipeline_config_default_policy` | Keep | `assert config.policy.minimum_boldness == 0.05` — nested default |
| `test_predicted_equals_current_raises` | Keep | `pytest.raises(ValidationError, match="predicted_value must differ")` — pins cross-field validator |
| `test_prior_stage_max_chars_floor` | Keep | `pytest.raises(ValidationError)` for `prior_stage_max_chars=0` |
| `test_proposed_change_max_length` | Keep | `pytest.raises(ValidationError)` for proposed_change of length 1001 |
| `test_proposed_vocab_links_default_empty` | Keep | `assert memo.proposed_vocab_links == []` |
| `test_refuted_status` | Keep | `assert link.status == "refuted"` — status field acceptance |
| `test_safety_first_policy` | Keep | `assert policy.minimum_boldness == 0.02` |
| `test_sota_mechanism_max_length` | Keep | `pytest.raises(ValidationError)` for sota_mechanism of length 1001 |
| `test_stage_output_knobs_custom` | Keep | `assert policy.comparative_analysis_top_k == 10` — custom knob values |
| `test_too_many_failure_modes_raises` | Keep | `valid_memo["predicted_failure_modes"] = ["a", "b", "c", "d"]` then `pytest.raises(ValidationError)` — max-length list constraint |
| `test_valid` | Keep | `fp = FalsifiablePrediction.model_validate(valid_prediction)` then `assert fp.predicted_value == 2.0` — real Pydantic construction |
| `test_valid_capability` | Keep | `assert ve.tier == "candidate"` and `assert ve.pattern is None` — capability defaults |
| `test_valid_feature` | Keep | `assert ve.tier == "canonical"` and `assert ve.pattern is not None` — feature VocabEntry |
| `test_valid_full` | Keep | `assert ic.from_run == "hpt_full_v1"` — optional field population |
| `test_valid_minimal` | Keep | `assert ic.from_run is None and ic.citation_source is None` — optional field defaults |
| `test_with_inherited_components` | Keep | `assert len(memo.inherited_components) == 1` — nested schema composition |
| `test_with_notes` | Keep | `assert len(out.memo_consistency_notes) == 2` — non-empty list |
| `test_with_proposed_vocab_links` | Keep | `assert memo.proposed_vocab_links[0].status == "proposed"` — default status check |
| `test_with_vocab_candidates` | Keep | `assert len(memo.proposed_vocab_candidates) == 1` |

### `tests/unit/agent/ml_model_proposal_agent/test_pipeline_runner.py`

Tests: 63

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_all` | Keep | `assert len(result) == 4` — exercises `method="all"` selection path |
| `test_all_invalid_segmentation_sizes_exhausts_retries` | Keep | `with pytest.raises(RuntimeError, match="failed after")` — exercises exhaustion when segmentation_size is always invalid |
| `test_auto_few_models_explore` | Keep | `assert resolve_exploration_mode(interp, pipeline) == "explore"` when only built-in models present — exercises auto-detection logic |
| `test_auto_many_agent_proposed_exploit` | Keep | `assert resolve_exploration_mode(interp, pipeline) == "exploit"` when 5+ agent-proposed models — exercises threshold logic in auto-detection |
| `test_below_baseline_honest_line` | Keep | `assert line == "log_scalar=-7.50, below raw baseline on 17 files"` — pins below-baseline guard that suppresses misleading recovery percentage |
| `test_below_baseline_takes_priority_over_recovery` | Keep | `assert line == "log_scalar=-7.50, below raw baseline on 20 files"` and `assert "%" not in line` — pins priority ordering of below-baseline guard over percent_of_ceiling_log when value is non-None |
| `test_budget_scales_sublinearly_with_n` | Keep | `assert len(large) < len(small) * 2.5` — guards against quadratic growth when doubling candidates |
| `test_candidate_markdown_with_unseen_model_name` | Keep | `assert "### Candidate: mystery_model_x" in block` and `for name in self._BASELINE_NAMES: assert name not in block` — baseline-name leakage guardrail via litmus scan |
| `test_custom_factory` | Keep | `factory.assert_called_once()` and `assert agent.bridge is fake_bridge` — verifies DI contract that custom factory is used and stored; `agent.bridge is fake_bridge` is a real identity check on agent state |
| `test_default_factory_uses_real_bridge` | Keep | `MockBridge.assert_called_once()` after `MLModelProposalAgent(provider="gemini", model_id="test")` — verifies constructor wiring for default factory; the assertion is on call count of the patched class, not on its return value |
| `test_disabled_stage_skipped` | Keep | `assert mock.generate.call_count == 2` after `inp.reasoning_pipeline.stages[1].enabled = False` — exercises stage-enabled flag logic |
| `test_does_not_mutate_input` | Keep | `assert "score_table" in candidates[0]` after calling `strip_heavy_fields_for_json(candidates)` — verifies immutability of input |
| `test_drops_per_model_score_tables_from_interpretation_summary` | Keep | `assert "per_model_score_tables" not in payload["interpretation_summary"]` — verifies redundant heavy field is dropped from JSON region |
| `test_drops_score_table_and_source_code` | Keep | `assert stripped[0] == {"model_type": "wavenet", "best_score": 5.5, "model_params": 120_000, "description": "dilated causal conv"}` — verifies exact field removal from JSON region |
| `test_empty_candidate_list_prompt_has_no_leakage` | Keep | `for name in self._BASELINE_NAMES: assert name not in prompt` in fall-through JSON-only path — regression guard for empty candidate path |
| `test_empty_candidates_returns_empty_string` | Keep | `assert build_candidate_markdown_block([]) == ""` — exercises empty-list edge case |
| `test_empty_interpretation` | Keep | `assert result == []` — exercises empty-model_types edge case in selection helper |
| `test_empty_list_returns_empty_list` | Keep | `assert strip_heavy_fields_for_json([]) == []` — exercises empty-list edge case |
| `test_empty_rendered_markdown_string_falls_back` | Keep | `assert "_Score table unavailable._" in block` when `rendered_markdown=""` — pins falsy-string fallback (empty string vs missing key) |
| `test_empty_source_code_string_falls_back` | Keep | `assert "_Source code unavailable._" in block` and `assert "```python\n\n```" not in block` — pins that empty string does not produce an empty fence |
| `test_error_injected_into_prompt_on_retry` | Keep | `assert "wavenet" in errors[0]` after parsing `retry_data["proposing_stage_errors"]` from the actual retry prompt — verifies error feedback injection into retry prompt |
| `test_exhausted_retries_raises` | Keep | `with pytest.raises(RuntimeError, match="failed after")` and `assert mock_bridge.generate.call_count == 2 + (_MAX_PROPOSING_RETRIES + 1)` — exercises retry exhaustion path |
| `test_explicit_exploit` | Keep | `assert resolve_exploration_mode(FAKE_INTERPRETATION, pipeline) == "exploit"` — exercises explicit override path |
| `test_explicit_explore` | Keep | `assert resolve_exploration_mode(FAKE_INTERPRETATION, pipeline) == "explore"` — exercises explicit override path |
| `test_feature_match` | Keep | `assert len(result) == 1` and `assert result[0]["model_type"] == "wavenet"` — exercises `method="feature_match"` substring search over model descriptions |
| `test_five_candidate_prompt_fits_budget` | Keep | `assert n_chars < 200_000` after assembling a worst-case n=5 prompt — real size-budget enforcement with substantive computation |
| `test_human_specified` | Keep | `assert types == {"wavenet", "gated_fno"}` — exercises `method="human_specified"` filter path |
| `test_invalid_segmentation_size_triggers_retry_then_succeeds` | Keep | `assert output.baseline_config["model_config"]["segmentation_size"] == 16000` and `assert mock_bridge.generate.call_count == 4` — exercises ProposalOutput.segmentation_size validator triggering retry |
| `test_json_region_strips_heavy_candidate_fields` | Keep | `assert "score_table" not in payload["candidates"][0]` and `assert "| wavenet-rendered |" in prompt` — verifies field removal in JSON while markdown block retains them |
| `test_legacy_mode_when_no_stages` | Keep | `assert mock_bridge.generate_text.call_count == 1` and `assert mock_bridge.generate.call_count == 1` — exercises legacy 2-call fallback when no stages configured |
| `test_markdown_block_first_then_json_region` | Keep | `assert md_idx < json_idx` where `md_idx = prompt.index("## Candidate Models — detailed view")` — pins ordering of markdown and JSON regions in assembled prompt |
| `test_missing_aggregate_returns_none` | Keep | `assert build_score_summary_line({"rows": []}) is None` — exercises missing aggregate key guard |
| `test_missing_model_scalar_returns_none` | Keep | `assert build_score_summary_line({"aggregate": {"num_sampled_files": 20}}) is None` — exercises missing model_scalar guard |
| `test_missing_model_type_renders_unknown_placeholder` | Keep | `assert "### Candidate: <unknown>" in block` — exercises missing model_type fallback |
| `test_missing_num_sampled_files_returns_none` | Keep | `assert build_score_summary_line({"aggregate": {"model_scalar": 1.0}}) is None` — exercises missing num_sampled_files guard |
| `test_missing_recovery_falls_back_to_no_percent` | Keep | `assert line == "log_scalar=3.20 on 20 files"` when `percent_of_ceiling_log=None` — exercises None-recovery fallback |
| `test_missing_score_table_falls_back` | Keep | `assert "_Score table unavailable._" in block` — exercises fallback sentinel when score_table absent |
| `test_missing_source_code_falls_back` | Keep | `assert "_Source code unavailable._" in block` — exercises fallback sentinel when source_code absent |
| `test_no_candidates_emits_json_only` | Keep | `assert prompt.startswith("## Accumulated context")` and `assert "## Candidate Models — detailed view" not in prompt` — exercises fall-through JSON-only path |
| `test_non_candidates_empty_when_all_selected` | Keep | `assert stage1_data.get("non_candidates_overview") == []` — exercises complementary path: when all models are candidates, non_candidates_overview is empty |
| `test_non_candidates_included_in_prompt` | Keep | `assert "punet" in non_candidate_types` and `for entry in non_candidates: assert entry.get("key_findings")` — exercises prompt-assembly logic; parses actual JSON from stage prompt and checks field completeness |
| `test_non_dict_score_table_on_candidate_falls_back` | Keep | `for bad_table in (None, "N/A", [], 42): ... assert "_Score table unavailable._" in block` — exercises isinstance guard for four non-dict cases |
| `test_non_dict_score_table_returns_none` | Keep | `assert build_score_summary_line("N/A") is None` and `assert build_score_summary_line([]) is None` — exercises isinstance guard against non-dict inputs |
| `test_none_table_returns_none` | Keep | `assert build_score_summary_line(None) is None` — exercises None-input guard |
| `test_normal_recovery_formatting` | Keep | `assert line == "log_scalar=5.58, recovery=82.3% on 20 files"` — pin exact output format of `build_score_summary_line` with numeric precision |
| `test_output_file_written` | Keep | `assert os.path.exists(out_path)` and `assert data["model_name"] == "spectral_wavenet"` — verifies storage side-effect: output JSON file written to workspace |
| `test_pipeline_calls_bridge_3_times` | Keep | `assert mock.generate.call_count == 3` — pins that the 3-stage pipeline makes exactly 3 LLM calls; guards against short-circuit or double-call regressions |
| `test_pipeline_produces_valid_output` | Keep | `assert isinstance(output, ProposalOutput)` and `assert output.model_name == "spectral_wavenet"` — verifies end-to-end pipeline constructs a valid Pydantic output from mock LLM responses |
| `test_preserves_other_fields` | Keep | `assert stripped[0]["training_segments"] == 200` and `assert "score_table" not in stripped[0]` — exercises targeted subtraction (non-whitelist) behavior |
| `test_recovery_zero_renders_percent_not_missing_clause` | Keep | `assert line == "log_scalar=1.00, recovery=0.0% on 20 files"` — pins boundary: `percent_of_ceiling_log=0.0` is falsy but must NOT fall into the None-recovery branch |
| `test_render_stage_user_prompt_with_mystery_model` | Keep | `for name in self._BASELINE_NAMES: assert name not in prompt` — litmus scan for directive #5; full assembled prompt must not leak baseline model names |
| `test_renders_heading_per_candidate` | Keep | `assert "### Candidate: wavenet" in block` and `assert "```python\nclass WaveNet: pass\n```" in block` — exercises `build_candidate_markdown_block` markdown rendering logic |
| `test_retry_on_duplicate_model_name` | Keep | `assert output.model_name == "spectral_wavenet"` and `assert mock_bridge.generate.call_count == 4` — exercises retry-on-duplicate logic; real business logic path |
| `test_retry_on_validation_error` | Keep | `assert mock_bridge.generate.call_count == 4` when first response has `{"model_name": ""}` — exercises retry-on-ValidationError path |
| `test_score_summary_indifferent_to_model_name` | Keep | `for name in (*self._BASELINE_NAMES, "mystery_model_x"): assert name not in line` — pins that model name never appears in summary line (by design) |
| `test_score_table_none_when_missing` | Keep | `assert result[0]["score_table"] is None` — exercises None-propagation when model has no score table |
| `test_score_table_passthrough` | Keep | `assert summary["score_table"] == interp["per_model_score_tables"]["punet"]` and `assert "file_vector" not in summary` — pins schema migration (old key removed, new key passed through) |
| `test_separator_between_candidates` | Keep | `assert block.count("\n---\n") == 2` — pins separator count for multi-candidate block |
| `test_source_field_seed_vs_proposed` | Keep | `assert sources["wavenet"] == "seed"` — validates that `source` field is correctly set on candidates returned from selection |
| `test_stages_1_and_2_not_rerun_on_retry` | Keep | `assert mock_bridge.generate.call_count == 4` — pins that comparison + causal_reasoning run exactly once even across retries |
| `test_top_n_default` | Keep | `assert result[0]["model_type"] == "wavenet"` and `assert result[0]["best_score"] == 5.5` — exercises `select_candidate_models` sorting logic on synthetic data; real deterministic computation |
| `test_top_n_limited` | Keep | `assert len(result) == 2` and `assert result[1]["model_type"] == "gated_fno"` — exercises `n=2` truncation in the selection helper |
| `test_validator_error_visible_in_retry_prompt` | Keep | `assert "segmentation_size" in err` and `assert "16384" in err` after parsing retry prompt JSON — verifies validator error details reach the retry prompt |

### `tests/unit/agent/ml_model_proposal_agent/test_preflight_revision_loop.py`

Tests: 18

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_audit_fields_populated_on_first_try_pass` | Keep | `assert out.preflight_estimated_minutes is not None` and `assert bridge.generate.call_count == 3` — asserts audit fields are populated and call count matches single-pass path |
| `test_call_count_equals_reasoning_plus_max_attempts` | Keep | `assert bridge.generate.call_count == 2 + _MAX_PREFLIGHT_ATTEMPTS` — verifies the maximum-attempt count contract in the exhaustion path |
| `test_contains_all_prescriptive_numbers` | Keep | `assert "10,000,000" in block` and `assert "200.0 min" in block` and `assert "10.0x" in block` and `assert "20.0 min budget" in block` — tests that `_build_preflight_rejection_block` includes all four required numeric substitutions |
| `test_contains_prescriptive_remediation` | Keep | `assert "parameter_count_estimate" in block` and `assert any(tag in block for tag in ("TCN", "FFT", "windowed"))` — tests that the rejection block contains actionable remediation content |
| `test_emits_best_factor_candidate` | Keep | `assert out.parameter_count_estimate == 100_000_000` and `assert any("PREFLIGHT_OVERBUDGET_EMITTED" in n for n in out.memo_consistency_notes)` — tests exhaustion path picks best-factor candidate from three over-budget drafts |
| `test_formal_budget_none_skips_gate` | Keep | `assert out.preflight_factor is None` and `assert bridge.generate.call_count == 3` — tests formal-mode skip when formal_budget is None |
| `test_legacy_budget_none_skips_preflight` | Keep | `assert out.preflight_factor is None` and `assert bridge.generate.call_count == 1` — tests legacy skip path when trial_budget is None |
| `test_legacy_exhaustion_emits_best_factor` | Keep | `assert out.parameter_count_estimate == 100_000_000` and `assert any("PREFLIGHT_OVERBUDGET_EMITTED" in n for n in out.memo_consistency_notes)` and `assert bridge.generate.call_count == _MAX_PREFLIGHT_ATTEMPTS` — tests legacy exhaustion path emits best-factor candidate |
| `test_legacy_rejection_appended_to_commit_prompt` | Keep | `assert "[PRE-FLIGHT REJECTION]" not in captured[0]` and `assert "[PRE-FLIGHT REJECTION]" in captured[1]` — verifies the rejection is appended only to the revision prompt, not the first prompt |
| `test_legacy_revises_on_preflight_rejection` | Keep | `assert out.parameter_count_estimate == 50_000` and `assert bridge.generate.call_count == 2` — tests legacy (2-call) mode also loops on rejection |
| `test_missing_parameter_count_adds_skip_note` | Keep | `assert out.preflight_factor is None` and `assert any("PREFLIGHT_SKIPPED" in n for n in out.memo_consistency_notes)` — tests None param-count produces PREFLIGHT_SKIPPED note |
| `test_negative_parameter_count_adds_skip_note` | Keep | `assert any("PREFLIGHT_SKIPPED" in n for n in out.memo_consistency_notes)` — tests negative param-count triggers skip note |
| `test_overbudget_note_names_best_factor` | Keep | `assert "factor=" in note` and `assert "20.0 min budget" in note` — tests that the overbudget memo note includes the winning factor and budget string |
| `test_rejection_injected_into_proposing_errors` | Keep | `assert any("[PRE-FLIGHT REJECTION]" in e for e in errors)` and `assert "500,000,000" in rejection` and `assert "20.0 min budget" in rejection` — captures real user_prompt argument to verify rejection block content is injected with the correct numeric substitutions |
| `test_revised_draft_emitted` | Keep | `assert out.parameter_count_estimate == 50_000` and `assert out.preflight_factor <= 1.0` — mock provides 4 staged LLM responses; asserts the real pre-flight loop's output selects the feasible draft |
| `test_stages_1_and_2_not_rerun_on_preflight_revision` | Keep | `assert bridge.generate.call_count == 4` — verifies that reasoning stages (1+2) are called only once even when proposing stage loops; tests call-count logic of the pre-flight revision loop |
| `test_trial_budget_none_skips_gate` | Keep | `assert out.preflight_estimated_minutes is None` and `assert bridge.generate.call_count == 3` — tests skip condition: None budget disables gate entirely and prevents revision loop |
| `test_zero_parameter_count_adds_skip_note` | Keep | `assert any("PREFLIGHT_SKIPPED" in n for n in out.memo_consistency_notes)` — tests zero param-count also triggers skip note |

### `tests/unit/agent/ml_model_proposal_agent/test_prior_stage_truncation.py`

Tests: 5

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_combined_clamp_and_backstop_drops_prompt_chars_by_at_least_30pct` | Keep | `assert ratio <= 0.7` where `ratio = clamped_chars / raw_chars` — quantitative regression gate on compression |
| `test_input_accumulated_not_mutated` | Keep | `assert accumulated == snapshot` after calling `clamp_and_backstop_accumulated` — pins non-mutation contract |
| `test_input_side_keys_pass_through_verbatim` | Keep | `assert clamped[key] is accumulated[key]` for every key in `_PROPOSER_INPUT_KEYS` and `assert len(long_blob) == 5000` — pins that input-side keys are not mutated |
| `test_post_clamp_comparative_analysis_has_top_k_entries` | Keep | `assert len(clamped["comparison"]["comparative_analysis"]) == policy.comparative_analysis_top_k` — verifies clamp function reduces 13 entries to policy.top_k=5 |
| `test_selected_entries_follow_3plus2_hybrid_contract` | Keep | `assert selected_types == {"m00", "m03", "m10", "m11", "m12"}` — pins the exact 3-best+2-recent hybrid selection logic with a constructed fixture that has a known score pattern |

### `tests/unit/agent/ml_model_proposal_agent/test_prompt_context_surfacing.py`

Tests: 28

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_capability_no_related_to_has_no_arrow` | Keep | `assert "← enabled by" not in block` — capability with empty related_to |
| `test_capability_with_single_link_shows_enabled_by` | Keep | `assert "← enabled by: dilated_causal_conv" in block` |
| `test_confirmed_percentage_rendered_correctly` | Keep | `assert "confirmed=60%" in prompt` and `assert "refuted=40%" in prompt` — percentage formatting |
| `test_cumulative_ig_formatted_to_three_decimals` | Keep | `assert "1.235" in prompt` with `cumulative_information_gain=1.23456` — 3dp rounding |
| `test_feature_no_related_to_has_no_arrow` | Keep | `assert "→ enables" not in block` with empty `related_to` |
| `test_feature_with_multiple_links_comma_separated` | Keep | `assert "→ enables: receptive_field, temporal_context" in block` — comma separation |
| `test_feature_with_single_link_shows_enables` | Keep | `assert "→ enables: receptive_field" in block` |
| `test_high_ratio_is_ok` | Keep | `assert "OK" in prompt` and `assert "LOW" not in prompt` with `vocab_diversity_ratio=0.5` |
| `test_ig_line_absent_when_not_in_interp` | Keep | `assert "information gain" not in prompt.lower()` when `cumulative_information_gain` absent |
| `test_low_ratio_shows_low_warning` | Keep | `assert "LOW" in prompt` with `vocab_diversity_ratio=0.05` |
| `test_mixed_pydantic_and_dict_entries` | Keep | `assert "→ enables: frequency_resolution" in block` and `assert "← enabled by: dilated_causal_conv" in block` — mixed type handling |
| `test_n_confirmed_links_counts_entries_with_related_to` | Keep | `assert "2 confirmed" in sys_prompt` with 2 entries having `related_to` |
| `test_n_confirmed_links_mixed_pydantic_and_dict` | Keep | `assert "2 confirmed" in sys_prompt` with mixed types |
| `test_n_confirmed_links_works_with_pydantic_objects` | Keep | `assert "1 confirmed" in sys_prompt` with VocabEntry objects |
| `test_n_confirmed_links_zero_when_no_related_to` | Keep | `assert "0 confirmed" in sys_prompt` extracted from Stage 1 LLM call — template variable |
| `test_n_zero_when_history_absent` | Keep | `assert "N=0" in prompt` when `prediction_outcomes_history` absent |
| `test_none_related_to_treated_as_empty` | Keep | `assert "→ enables" not in block` with `related_to=None` — None vs [] equivalence |
| `test_partial_percentage_rendered` | Keep | `assert "partial=30%" in prompt` — partial percentage |
| `test_pydantic_vocabentry_capability_with_links` | Keep | `assert "← enabled by: spectral_conv" in block` with Pydantic object |
| `test_pydantic_vocabentry_object_with_links` | Keep | `assert "→ enables: frequency_resolution" in block` with real `VocabEntry` Pydantic object |
| `test_ratio_at_threshold_is_ok` | Keep | `assert "OK" in prompt` and `assert "LOW" not in prompt` with `vocab_diversity_ratio=0.1` — exact boundary |
| `test_ratio_value_formatted_to_two_decimals` | Keep | `assert "0.12" in prompt` with `vocab_diversity_ratio=0.12345` — 2dp formatting |
| `test_total_n_from_prediction_outcomes_history` | Keep | `assert "N=6" in prompt` with history `{"confirmed": 3, "refuted": 3, "partial": 0}` |
| `test_track_record_absent_when_neither_field_present` | Keep | `assert "Prediction Track Record" not in prompt` with minimal interp — absence check |
| `test_track_record_present_when_only_cumulative_ig_set` | Keep | `assert "Prediction Track Record" in prompt` with `cumulative_information_gain=0.42` only |
| `test_track_record_present_when_scientific_accuracy_set` | Keep | `assert "Prediction Track Record" in prompt` with `scientific_accuracy={"confirmed": 0.6, ...}` |
| `test_vocab_health_absent_when_no_diversity_ratio` | Keep | `assert "Vocabulary Health" not in prompt` — absence check |
| `test_vocab_health_present_when_ratio_set` | Keep | `assert "Vocabulary Health" in prompt` with `vocab_diversity_ratio=0.15` |

### `tests/unit/agent/ml_model_proposal_agent/test_proposal_agent.py`

Tests: 17

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_advice_strings_propagate_into_reasoning_prompt` | Keep | `assert substr in prompt` for multiple substr values — tests real prompt-construction logic `_build_reasoning_prompt` for both plain-string and structured advice |
| `test_all_four_kinds_rendered` | Keep | `assert "Features" in rendered; assert "Discoveries" in rendered` — tests that all four section headers appear when all kinds present |
| `test_dict_entries_also_work` | Keep | tests `_render_vocabulary` with a plain dict; `assert "Discoveries" in rendered` — tests duck-typing path in the function |
| `test_empty_returns_empty_string` | Keep | `assert MLModelProposalAgent._render_vocabulary([]) == ""` — pure function, no mocks, edge-case behavior |
| `test_expert_advice_before_human_advice` | Keep | `expert_pos = prompt.index("Expert Guidance"); human_pos = prompt.index("Human Expert Advice"); assert expert_pos < human_pos` — tests ordering of sections in real prompt output |
| `test_expert_advice_propagation` | Keep | `assert s in prompt` and `assert s not in prompt` — tests real rendering of different advice types (empty string, plain string, structured) in `_build_reasoning_prompt` |
| `test_includes_rendered_markdown_per_model` | Keep | `assert "### Per-model score tables" in prompt` and `assert "(test)" in prompt` — calls real `_build_reasoning_prompt` with no mocks; tests real template logic |
| `test_llm_response_threads_through_all_output_fields` | Keep | `assert output.model_name == "attn_unet"` and `assert isinstance(output.expert_advice, ExpertAdvice)` — tests that the agent correctly maps LLM response fields to `ProposalOutput` schema, including type coercion of `expert_advice` |
| `test_name_collision_guard` | Keep | `with pytest.raises(ValueError, match="already exists in existing_model_types")` — tests real duplicate-name guard in agent |
| `test_no_advice_omits_human_section` | Keep | `assert "Human Expert Advice" not in prompt` — tests negative case: no-advice path suppresses the section header |
| `test_no_discoveries_no_discoveries_section` | Keep | `assert "Discoveries" not in rendered` — tests that section is suppressed when no entries of that kind |
| `test_output_persists_to_disk_with_correct_content` | Keep | `assert out_path.exists()` and `assert data["model_name"] == "attn_unet"` — tests real filesystem write logic; path naming, JSON serialization |
| `test_prompt_includes_enriched_interpretation_fields` | Keep | `prompt = _build_reasoning_prompt(inp); assert substr in prompt` — calls real function directly; tests that specific enriched fields appear under their documented headings |
| `test_reasoning_injected_into_commit_prompt` | Keep | `assert FAKE_REASONING in user_prompt` — tests that the agent reads the reasoning result and injects it into the commit prompt; real wiring logic |
| `test_single_kind_entry_rendered` | Keep | `rendered = MLModelProposalAgent._render_vocabulary(vocab); assert s in rendered` — tests real rendering logic for each vocab kind; pure function |
| `test_text_gen_then_commit_gen_each_called_once` | Keep | `assert call_order == ["text", "json"]` — tests real ordering of LLM calls within `agent.run()`; the mock captures order but the assertion is on the agent's internal sequencing logic |
| `test_works_without_enriched_fields` | Keep | `assert "punet" in prompt` and `assert "File Vector" not in prompt` — tests graceful degradation when optional fields are absent |

### `tests/unit/agent/ml_model_proposal_agent/test_proposal_helpers.py`

Tests: 42

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_backfill_when_top_k_above_five` | Keep | `assert {"m00","m01","m02","m12","m11"}.issubset(out_mts)` for top_k=10 |
| `test_bare_proposed_falls_back` | Keep | `assert _iter_index_from_source("proposed") == -1` — legacy format fallback |
| `test_custom_threshold` | Keep | `vocab_diversity_ratio=0.25` below custom threshold 0.3 then `assert ... == "explore"` — knob coverage |
| `test_empty_string_falls_back` | Keep | `assert _iter_index_from_source("") == -1` |
| `test_exactly_5_proposed_models_triggers_exploit` | Keep | `assert resolve_exploration_mode(interp, pipeline) == "exploit"` — boundary at 5 |
| `test_explicit_exploit_bypasses_all_signals` | Keep | `assert resolve_exploration_mode(interp, pipeline) == "exploit"` — explicit override logic |
| `test_explicit_explore_bypasses_all_signals` | Keep | `assert resolve_exploration_mode(interp, pipeline) == "explore"` with stagnating vocab — pure function, no mocks |
| `test_fewer_than_5_proposed_models_triggers_explore` | Keep | `assert resolve_exploration_mode(interp, pipeline) == "explore"` with 2 agent-proposed models — evidence-depth threshold logic |
| `test_floor_validation` | Keep | `pytest.raises(ValueError)` for max_chars < 40, accepts at 40 — floor contract |
| `test_healthy_vocab_does_not_override` | Keep | `vocab_diversity_ratio=0.3` above threshold then `assert ... == "exploit"` |
| `test_idempotence_already_marked_string` | Keep | `assert once == twice` — truncating already-truncated string produces no change |
| `test_independent_max_chars_does_not_alter_json_structure` | Keep | `json.loads(json.dumps(out))` shape check at multiple caps |
| `test_independent_max_chars_shifts_trigger_point` | Keep | Knob sweep asserting `len(out) <= k` for k in `(500, 1000, 2000, 4000)` |
| `test_independent_top_k_alters_density` | Keep | Loop over k in `(2,3,5,7,10)` asserting `len(out) == k` — knob sweep |
| `test_input_not_mutated` | Keep | `assert entries == snapshot` after `clamp_comparative_analysis` — immutability contract |
| `test_iter13_envelope_ratio_3_best_plus_2_recent` | Keep | `assert {"m00","m01","m02","m12","m11"}.issubset(...)` — hybrid clamp algorithm with anti-correlated data |
| `test_list_of_strings_truncated_elementwise` | Keep | `assert len(out[1]) <= 4000` while `out[0] == "short"` — element-wise truncation |
| `test_long_string_at_floor_cap` | Keep | `assert len(out["big"]) <= 40` at `max_chars=40` — boundary at floor |
| `test_malformed_iter_suffix_falls_back` | Keep | `assert _iter_index_from_source("proposed_iter_abc") == -1` and `"proposed_iter_5x"` |
| `test_many_proposed_models_triggers_exploit` | Keep | `assert resolve_exploration_mode(interp, pipeline) == "exploit"` with 10 models |
| `test_missing_best_score_treated_as_negative_infinity` | Keep | `assert len(out) == 5` with a record missing best_score — crash-resistance |
| `test_missing_diversity_ratio_falls_back_to_evidence_depth` | Keep | `interp = {"model_types": ...}` without vocab_diversity_ratio then `assert ... == "exploit"` — legacy/first-iteration path |
| `test_model_type_dedup_best_score_wins` | Keep | `assert alpha_entries[0]["best_score"] == 0.9` — dedup logic keeps higher-score entry |
| `test_nested_dict_strings_get_truncated` | Keep | `assert " chars elided ...]" in out["outer"]["inner"]` — recursive walker |
| `test_no_op_exact_cap` | Keep | `assert len(out) == 5` at exactly cap=5 |
| `test_no_op_when_under_cap` | Keep | `assert [e["model_type"] for e in out] == ["a", "b"]` — passthrough when under cap |
| `test_non_string_falls_back` | Keep | `assert _iter_index_from_source(42) == -1` and `_iter_index_from_source([]) == -1` |
| `test_none_falls_back` | Keep | `assert _iter_index_from_source(None) == -1` |
| `test_over_cap_middle_truncated` | Keep | `assert " chars elided ...]" in out` and `assert len(out) <= 4000` — real truncation logic |
| `test_passthrough_at_or_under_cap` | Keep | `assert out == s` for inputs at or below max_chars — no-op path |
| `test_passthrough_when_nothing_to_truncate` | Keep | `assert out == payload` parametrized over short/scalar/empty inputs |
| `test_prefix_only_falls_back` | Keep | `assert _iter_index_from_source("Xproposed_iter_5") == -1` — anchored regex |
| `test_proposed_iter_large_n` | Keep | `assert _iter_index_from_source("proposed_iter_123") == 123` |
| `test_proposed_iter_n_extracts_n` | Keep | `assert _iter_index_from_source("proposed_iter_7") == 7` — happy-path regex |
| `test_ratio_at_threshold_boundary` | Keep | `vocab_diversity_ratio=0.1` exactly at threshold then `assert ... == "exploit"` — strict-less-than semantics |
| `test_seed_maps_to_zero` | Keep | `assert _iter_index_from_source("seed") == 0` — regex parser edge case |
| `test_seed_source_treated_as_iter_zero` | Keep | `assert "p9" in out_mts` — seed gets iter=0 so recent draws come from p9/p8 |
| `test_stagnating_vocab_forces_explore` | Keep | `vocab_diversity_ratio=0.05` below threshold with 10 models then `assert ... == "explore"` — stagnation overrides evidence-depth |
| `test_stagnation_checked_before_evidence_depth` | Keep | Both signals agree on explore; documents priority ordering |
| `test_structural_invariance_keys_and_lengths_preserved` | Keep | `assert set(out.keys()) == set(payload.keys())` and nested structure checks — structure preservation |
| `test_truncate_when_top_k_below_five` | Keep | `assert {e["model_type"] for e in out} == {"m0", "m1", "m2"}` for top_k=3 |
| `test_unparseable_source_falls_to_end` | Keep | `assert "good" in out_mts` — entry with iter=5 wins recency draw over iter=-1 entries |

### `tests/unit/agent/ml_model_proposal_agent/test_proposal_schemas.py`

Tests: 19

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_accepts_list_of_dicts_coerced_to_info` | Keep | `assert isinstance(inp.recent_gate_exhaustions[0], GateExhaustionInfo)` and `assert inp.recent_gate_exhaustions[0].summary_message.startswith("All 9 attempts")` — verifies dict coercion path |
| `test_accepts_multi_entry_list_preserves_order` | Keep | `assert inp.recent_gate_exhaustions[0].vram_gated_attempts == 9` and `assert inp.recent_gate_exhaustions[1].time_gated_attempts == 3` — verifies oldest-first order preservation |
| `test_accepts_single_entry_list` | Keep | `assert len(inp.recent_gate_exhaustions) == 1` and `assert inp.recent_gate_exhaustions[0].total_attempts == 9` — verifies single-item list parsing |
| `test_default_empty_when_omitted` | Keep | `assert inp.recent_gate_exhaustions == []` — verifies default empty list |
| `test_expert_advice_as_dict` | Keep | `assert isinstance(out.expert_advice, ExpertAdvice)` when `expert_advice=valid_expert_advice.model_dump()` — verifies dict-to-model coercion on output |
| `test_human_advice_accepts_expert_advice_as_dict` | Keep | `assert isinstance(inp.human_advice, ExpertAdvice)` when dict is passed — verifies dict-to-model coercion |
| `test_human_advice_accepts_plain_string` | Keep | `assert inp.human_advice == "Focus on reducing parameter count."` — verifies union type accepts str |
| `test_human_advice_accepts_structured_expert_advice` | Keep | `assert isinstance(inp.human_advice, ExpertAdvice)` and `assert inp.human_advice.rationale == "prior runs show width saturation"` — verifies coercion to ExpertAdvice |
| `test_human_advice_defaults_to_none` | Keep | `assert inp.human_advice is None` — verifies default value |
| `test_invalid_entry_dict_raises` | Keep | `with pytest.raises(ValidationError)` for dict missing required fields like `vram_budget_gb` — verifies strict validation |
| `test_missing_interpretation_raises` | Keep | `with pytest.raises(ValidationError) as exc` and `assert "interpretation" in str(exc.value)` — verifies required field validation |
| `test_missing_mathematical_definition_raises` | Keep | `with pytest.raises(ValidationError) as exc` and `assert "mathematical_definition" in str(exc.value)` — verifies required field |
| `test_missing_model_name_raises` | Keep | `with pytest.raises(ValidationError) as exc` and `assert "model_name" in str(exc.value)` — verifies required field |
| `test_rejects_over_ten_entries` | Keep | `with pytest.raises(ValidationError) as exc` and `assert "maximum allowed is 10" in str(exc.value)` — verifies list length cap |
| `test_round_trip_preserves_entries` | Keep | `round_tripped = ProposalInput.model_validate_json(inp.model_dump_json())` then `assert round_tripped.recent_gate_exhaustions[0].model_dump() == gate_exhaustion.model_dump()` — JSON round-trip test |
| `test_storage_custom` | Keep | `assert inp.storage.local.run_name == "r1"` — verifies nested storage config parsing |
| `test_valid` | Keep | `out = ProposalOutput(...)` then `assert out.model_name == "attn_unet"` and `assert isinstance(out.expert_advice, ExpertAdvice)` — verifies output schema construction |
| `test_valid_minimal` | Keep | `inp = ProposalInput(interpretation={"take_home_message": "need new arch"})` then `assert inp.existing_model_types == []` and `assert inp.storage.backend == "local"` — verifies Pydantic defaults |
| `test_valid_with_all_fields` | Keep | `assert "punet" in inp.existing_model_types` and `assert "VRAM < 10 GB" in inp.constraints` — verifies field assignment |

### `tests/unit/agent/ml_model_proposal_agent/test_recent_gate_exhaustions.py`

Tests: 22

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_all_unknown_tags_produces_no_block` | Keep | `assert "[DISALLOWED PATTERNS]" not in block` when all tags unknown |
| `test_block_absent_when_list_empty` | Keep | `assert "[RECENT GATE EXHAUSTIONS" not in prompt` in legacy reasoning prompt |
| `test_closing_guidance_present` | Keep | `assert "same architecture family or scale" in block` and `assert "different family" in block` |
| `test_disallowed_block_appears_after_resource_accounting` | Keep | `assert pos_accounting < pos_disallowed` — position invariant |
| `test_disallowed_block_is_per_entry_not_global` | Keep | `assert block.count("[DISALLOWED PATTERNS] DO NOT PROPOSE:") == 1` and `assert pos_older < pos_banner < pos_newer` |
| `test_dump_path_none_writes_nothing` | Keep | `assert not debug_dir.exists()` — no side effects when path is None |
| `test_dump_path_set_writes_rendered_prompt` | Keep | `assert dump_path.exists()` and `assert "[RECENT GATE EXHAUSTIONS" in contents` — debug dump |
| `test_empty_list_returns_empty_string` | Keep | `assert _format_recent_gate_exhaustions_block([]) == ""` — empty input returns empty string |
| `test_empty_patterns_produces_no_disallowed_block` | Keep | `assert "[DISALLOWED PATTERNS]" not in block` — zero-noise path |
| `test_every_tag_in_vocabulary_has_a_description` | Keep | `assert set(ARCHITECTURAL_PATTERNS) == {"recurrent_over_T", "scan_over_T", "dense_attention_over_T"}` — vocabulary completeness |
| `test_multi_entry_ordering_preserved_in_legacy_prompt` | Keep | `assert prompt.index("OLD:") < prompt.index("NEW:")` — ordering |
| `test_multi_pattern_renders_in_stored_order` | Keep | `assert pos_dense < pos_rec < pos_scan` — order preserved |
| `test_placeholder_substitution` | Keep | `assert "{recent_gate_exhaustions_block}" not in prompt` after substitution — parametrized |
| `test_populated_block_carries_header_summary_and_accounting` | Keep | `assert "Mode active:       trial" in prompt` and `assert "VRAM 1.60×" in prompt` — accounting fields |
| `test_proposing_system_prompt_block_inclusion` | Keep | `assert "[RECENT GATE EXHAUSTIONS" in system_prompt` or absence depending on input — end-to-end via `agent.run` |
| `test_proposing_system_prompt_preserves_three_entry_order` | Keep | `assert system_prompt.index("OLD:") < system_prompt.index("MID:")` end-to-end order |
| `test_single_entry_block_shape` | Keep | `assert "[RECENT GATE EXHAUSTIONS (last 1 iteration)]" in block` and `assert "iter N-1 (most recent):" in block` and `assert "-" * 68 not in block` |
| `test_single_pattern_renders_banner_and_description` | Keep | `assert ARCHITECTURAL_PATTERNS["scan_over_T"] in block` — single source of truth |
| `test_template_carries_placeholder` | Keep | `assert "{recent_gate_exhaustions_block}" in prompt` from real `load_stage_prompt` |
| `test_three_entry_block_shape` | Keep | `assert block.count("-" * 68) == 2` and ordering `block.index("iter N-3:") < block.index("iter N-2:") < block.index("iter N-1 (most recent):")` |
| `test_two_entry_block_shape` | Keep | `assert block.count("-" * 68) == 1` and `assert block.index("iter N-2:") < block.index("iter N-1 (most recent):")` |
| `test_unknown_tag_is_dropped_defensively` | Keep | `assert "unknown_future_tag" not in block` and `assert "- scan_over_T:" in block` — defensive drop |

### `tests/unit/agent/ml_model_proposal_agent/test_rejection_acknowledgement_prompt.py`

Tests: 17

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_both_one_sided_failures_disqualified` | Keep | `assert re.search(r"only the scientific bottleneck with\s+no mention of the physical rejection", ...)` and `assert re.search(r"only the VRAM\s+cap with no scientific rationale", ...)` — pins both failure modes explicitly |
| `test_causal_hypothesis_named_as_single_integrated_paragraph` | Keep | `assert "single integrated paragraph" in PROPOSAL_REASONING_PROMPT` and `assert "causal_hypothesis" in PROPOSAL_REASONING_PROMPT` — pins the paragraph-form requirement for causal_hypothesis |
| `test_citation_integrated_synthesis` | Keep | `assert re.search(r"scientific\s+improvement", PROPOSAL_REASONING_PROMPT) is not None` and `assert "remaining strictly within" in PROPOSAL_REASONING_PROMPT` and `assert "defeated the previous proposal" in PROPOSAL_REASONING_PROMPT` — pins v3 integrated-synthesis citation |
| `test_citation_physical_failure_three_requirements` | Keep | `assert "rejected \`model_type\`" in PROPOSAL_REASONING_PROMPT` and `assert "dominant layer that caused the OOM" in PROPOSAL_REASONING_PROMPT` and `assert "Effective cap vs Predicted peak" in PROPOSAL_REASONING_PROMPT` — pins v1 preservation of three citation requirements |
| `test_citation_scientific_bottleneck` | Keep | `assert "scientific bottleneck" in PROPOSAL_REASONING_PROMPT` and `assert "from the Stage 1" in PROPOSAL_REASONING_PROMPT` — pins that scientific bottleneck scope is identified correctly |
| `test_clause_structure_intact` | Keep | `assert pattern.search(PROPOSAL_REASONING_PROMPT) is not None` where pattern is a DOTALL regex spanning header → framing → constraint list → closing — drift-detector for the whole clause's internal ordering |
| `test_closing_cite_as_design_constraint` | Keep | `assert re.search(r"Cite the previous failure\s+as a design constraint to be solved alongside", PROPOSAL_REASONING_PROMPT) is not None` — pins terminal instruction sentence |
| `test_mandatory_header_follows_what_you_receive` | Keep | `assert receive_idx < header_idx` — pins that input blocks are declared before the reasoning mandate |
| `test_mandatory_header_precedes_what_you_produce` | Keep | `assert header_idx < produce_idx` via `PROPOSAL_REASONING_PROMPT.index(...)` — pins ordering invariant: MANDATORY clause before JSON schema |
| `test_mandatory_header_present` | Keep | `assert "## MANDATORY — Integrated reasoning (science + engineering)" in PROPOSAL_REASONING_PROMPT` — pins required header in the live staged template |
| `test_names_physical_constraints_sources` | Keep | `assert "[PHYSICAL REJECTION]" in PROPOSAL_REASONING_PROMPT` and `assert "[HARDWARE CONTEXT]" in PROPOSAL_REASONING_PROMPT` and `assert "Effective cap" in PROPOSAL_REASONING_PROMPT` — pins physical constraints sources |
| `test_names_scientific_goals_source` | Keep | `assert "scientific goals" in PROPOSAL_REASONING_PROMPT` and `assert "DiscoveryMemo" in PROPOSAL_REASONING_PROMPT` — pins that scientific-goals source is identified |
| `test_not_a_historical_footnote` | Keep | `assert re.search(r"not a historical\s+footnote", PROPOSAL_REASONING_PROMPT) is not None` — pins the "not a historical footnote" phrasing with regex to allow line-wrap |
| `test_scientist_and_engineer_framing` | Keep | `assert "You are both a scientist and an engineer" in PROPOSAL_REASONING_PROMPT` — pins the v3 cognitive framing sentence |
| `test_three_citation_bullets_appear_in_order` | Keep | `assert pattern.search(PROPOSAL_REASONING_PROMPT) is not None` where pattern is a multi-line regex checking bullets appear in correct order — structural ordering invariant |
| `test_treat_failure_as_design_constraint` | Keep | `assert "design constraint to be solved alongside" in PROPOSAL_REASONING_PROMPT` — pins load-bearing v3 distinction phrase |
| `test_two_constraint_systems_must_be_satisfied_simultaneously` | Keep | `assert "two constraint systems" in PROPOSAL_REASONING_PROMPT` and `assert "simultaneously" in PROPOSAL_REASONING_PROMPT` and `assert "not\nsequentially" in PROPOSAL_REASONING_PROMPT` — pins all three tokens of the v3 opening |

### `tests/unit/agent/protocols/test_ml_model_impl_to_ml_model_valid.py`

Tests: 3

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_baseline_all_fields_pass_through` | Keep | `result = local_all_fields(implementor_output, storage)` then `assert result.model_type == "gated_tcn"` and `assert result.config_fields == {"depth": 6, "channels": 64, "use_bias": True}` — tests real field-mapping logic in the protocol function; no mocks |
| `test_llm_kwargs_default_or_override` | Keep | `result = local_all_fields(implementor_output, storage, **kwargs); assert getattr(result, expected_attr) == expected_value` — tests protocol's default/override logic for LLM kwargs; deterministic parametrized |
| `test_raises_not_implemented` | Keep | `with pytest.raises(NotImplementedError): database_all_fields(implementor_output, storage)` — tests contract that database variant is not yet implemented |

### `tests/unit/agent/protocols/test_ml_model_propose_to_ml_model_impl.py`

Tests: 2

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_baseline_pass_through_and_default_dirs` | Keep | `assert result.model_name == "gated_dilated_tcn"` and `assert result.plugin_dir == "agent_generated/models"` — calls real `local_full_spec` with real Pydantic fixture objects; asserts field pass-through and schema defaults; no circular mock assertion |
| `test_raises_not_implemented` | Keep | `with pytest.raises(NotImplementedError): database_full_spec(proposal_output, storage)` — tests that the placeholder raises as documented |

### `tests/unit/agent/protocols/test_ml_model_tune_to_ml_result_interp.py`

Tests: 5

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_empty_records_yields_default_summary` | Keep | `assert summary.completed_rounds == 0; assert summary.best_file_vector is None; assert summary.round_scores == []` — empty records → defaults |
| `test_formal_round_surfaces_formal_score_and_vector` | Keep | `assert summary.formal_score == 1.2; assert summary.formal_file_vector is not None; assert len(summary.formal_file_vector) == 20` — formal round extraction path |
| `test_raises_not_implemented` | Keep | `with pytest.raises(NotImplementedError): database_all_records(output, storage)` — placeholder contract |
| `test_round_lists_extracted_across_mixed_records` | Keep | `assert summary.round_scores == [1.5, None]; assert "OOM" in summary.round_conclusions[1]; assert summary.round_trial_portions == [0.05, None]` — mixed success/oom record handling |
| `test_single_record_baseline_extracts_all_summary_fields` | Keep | `assert summary.model_type == "fcnet"; assert summary.best_denoising_score == 1.5; assert summary.best_file_vector[7] == 78.0; assert summary.training_psd_segments == 200; assert summary.formal_score is None` — multi-field extraction from protocol function; real deterministic ... |

### `tests/unit/agent/protocols/test_ml_model_valid_to_ml_model_tune.py`

Tests: 21

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_all_three_budgets_independent` | Keep | `assert result.trial_time_budget_minutes == 30.0; assert result.formal_time_budget_minutes == 240.0; assert result.data_dir == "/data/tidmad"` — all three survive together |
| `test_all_three_independent` | Keep | `assert result.attempts_per_round == 2; assert result.attempts_per_formal_round == 4; assert result.max_fail_rounds == 1` — all three survive together |
| `test_baseline_attributes_from_inputs` | Keep | `assert result.model_type == "gated_tcn"; assert "receptive field size" in result.expert_advice.focus_areas; assert result.storage.local.workspace == "/tmp/tune_test"` — multi-field protocol pass-through |
| `test_both_deviations_prepended_in_order` | Keep | `spec_pos = ea.index("spec deviation detail"); inherit_pos = ea.index("inheritance deviation detail"); advice_pos = ea.index("receptive field size"); assert spec_pos < inherit_pos < advice_pos` — ordering logic |
| `test_both_vram_budgets_set_does_not_touch_time_budgets` | Keep | `assert result.trial_vram_budget_gb == 6.0; assert result.formal_vram_budget_gb == 24.0; assert result.trial_time_budget_minutes is None; assert result.formal_time_budget_minutes is None` — cross-category independence |
| `test_custom_kwarg_passes_through` | Keep | parametrized: `result = local_validated_model(..., **{kwarg: value}); assert getattr(result, attr) == value` — each kwarg reaches the downstream schema |
| `test_default_when_kwarg_omitted` | Keep | parametrized: `assert getattr(result, attr) == expected_default` for max_rounds=50, file_index=6, llm_provider="gemini", is_trial=False — documents and pins default values |
| `test_defaults_match_schema_when_omitted` | Keep | `assert result.attempts_per_round == 3; assert result.attempts_per_formal_round == 5; assert result.max_fail_rounds == 3` — exact schema defaults pinned |
| `test_defaults_none_when_omitted` | Keep | `assert result.trial_time_budget_minutes is None; assert result.formal_time_budget_minutes is None; assert result.data_dir is None` — default None |
| `test_individual_attempt_kwarg_passes_through` | Keep | parametrized: `assert getattr(result, set_field) == set_value` and `for sib, sib_default in sibling_defaults.items(): assert getattr(result, sib) == sib_default` — attempt budget independence |
| `test_individual_budget_passes_through_without_polluting_siblings` | Keep | parametrized: `assert getattr(result, set_field) == set_value` and `for f in other_fields_must_stay_none: assert getattr(result, f) is None` — budget independence |
| `test_individual_vram_budget_passes_through_without_polluting_sibling` | Keep | parametrized: `assert getattr(result, set_field) == set_value; assert getattr(result, sibling_to_check) is None` — VRAM budget independence |
| `test_no_deviation_passes_advice_through_structured` | Keep | `assert isinstance(result.expert_advice, ExpertAdvice)` — no deviation → structured type preserved |
| `test_penalty_resolves` | Keep | parametrized: `assert result.degenerate_penalty_score == expected` for None and -2.5 — default and float passthrough |
| `test_raises_not_implemented` | Keep | `with pytest.raises(NotImplementedError): database_validated_model(validator_output, storage)` — placeholder contract |
| `test_returns_hyperparam_tuning_input` | Keep | `result = local_validated_model(validator_output, proposal_output, storage); assert isinstance(result, HyperparamTuningInput)` — type contract |
| `test_single_deviation_prepended_to_serialized_advice` | Keep | parametrized: `setattr(validator_output, attr_to_set, note)` then `assert isinstance(result.expert_advice, str); assert expected_substr in result.expert_advice; assert "receptive field size" in result.expert_advice` — deviation note prepended with original advice preserved |
| `test_target_files_in_trial_target_mode` | Keep | `result = local_validated_model(..., is_trial=True, trial_strategy="target", target_files=[0, 5, 10]); assert result.target_files == [0, 5, 10]` — target-mode sub-path |
| `test_trial_mode_snapshot_kwargs_fan_out` | Keep | `assert result.is_trial is True; assert result.trial_strategy == "snapshot"; assert result.trial_portion == 0.2; assert result.train_portion == 0.15; assert result.eval_strategy == "anchors"` — 9-field fan-out |
| `test_value_resolves_to_canonical` | Keep | parametrized: `assert result.formal_round_strategy == expected_canonical` for default ("full_clone"), canonical ("independent"), legacy aliases — aliasing/canonicalization logic |
| `test_vram_defaults_none_when_omitted` | Keep | `assert result.trial_vram_budget_gb is None; assert result.formal_vram_budget_gb is None` — default None |

### `tests/unit/agent/protocols/test_ml_result_interp_to_ml_model_propose.py`

Tests: 12

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_baseline_serialisation_and_storage_pass_through` | Keep | `assert interp["take_home_message"] == "A new architecture is needed..."` and `assert interp["best_denoising_score"] == 1.5` — tests real serialization and field-mapping in `local_full_context`; no mocks |
| `test_both_budgets_independent` | Keep | `assert result.trial_time_budget_minutes == 30.0; assert result.formal_time_budget_minutes == 240.0` — tests cross-contamination doesn't happen |
| `test_defaults_when_caller_omits` | Keep | `assert result.is_trial is False; assert result.trial_strategy == "snapshot"` — tests that all schema defaults are honoured when no kwargs passed |
| `test_empty_aggregation_when_no_populated_gate_exhaustion` | Keep | `assert result.recent_gate_exhaustions == []` for both the omitted-kwarg and all-None-gate-exhaustion routes — tests filtering logic |
| `test_full_trial_target_fan_out` | Keep | nine distinct field assertions like `assert result.trial_strategy == "target"` — tests complete fan-out of all trial fields through the protocol |
| `test_kwarg_independent_of_other_pass_through_fields` | Keep | `assert len(result.recent_gate_exhaustions) == 1; assert result.trial_time_budget_minutes == 60.0; assert result.formal_time_budget_minutes is None` — tests that gate aggregation doesn't clobber other kwargs |
| `test_multiple_model_types` | Keep | `assert len(result.existing_model_types) == 3` — distinct from baseline; pins list cardinality with 3-element input |
| `test_partial_kwargs_only_overrides_supplied_fields` | Keep | `assert result.trial_time_budget_minutes == 60.0; assert result.formal_time_budget_minutes is None` — tests partial plumbing doesn't reset untouched fields |
| `test_preserves_oldest_first_order_for_multi_entry_aggregation` | Keep | `assert result.recent_gate_exhaustions[0].model_dump() == gate_exhaustion.model_dump()` — tests ordering contract |
| `test_raises_not_implemented` | Keep | `with pytest.raises(NotImplementedError): database_full_context(output, storage)` — pins placeholder contract |
| `test_single_kwarg_passes_through` | Keep | `result = local_full_context(interp_output, storage, **{kwarg: value}); assert getattr(result, expected_attr) == expected_value` — tests each run-level kwarg threads through protocol; includes side_check for budget independence |
| `test_surfaces_single_gate_exhaustion_when_only_one_populated` | Keep | `assert len(result.recent_gate_exhaustions) == 1; assert isinstance(result.recent_gate_exhaustions[0], GateExhaustionInfo)` — tests that None entries are filtered and only populated entries remain |

### `tests/unit/agent/result_interpretation_agent/test_dispatcher_wiring.py`

Tests: 4

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_per_model_call_count_equals_active_set_size` | Keep | `assert len(per_model_calls) == 3` and `assert len(synthesis_calls) == 1` and `assert len(consolidator_calls) == 6` and `assert agent.bridge.generate.call_count == 10` — call counts test specific dispatch logic (active-set filtering, consolidator wiring), not just mock return ... |
| `test_skipped_calls_emit_audit_marker` | Keep | `assert len(marker_calls) == 9` and `assert call.kwargs["label"] == "interpretation.per_model_skipped"` and `assert call.kwargs["extra"]["reason"] == "stable"` and `assert skipped_mts == {f"m{i:02d}" for i in range(3, 12)}` — verifies audit marker content and identity of skipp... |
| `test_synthesis_prompt_mentions_every_model_type` | Keep | `missing = [mt for mt in cache if mt not in user_prompt]` then `assert not missing` and `assert "compressed for context budget" in user_prompt` and `assert full_block_count == 3` — verifies no model is silently dropped from synthesis prompt |
| `test_synthesis_prompt_size_under_15k_for_13_models` | Keep | `assert prompt_chars < 15_000` — verifies actual compression ratio of the synthesis prompt; tests a performance contract on real business logic |

### `tests/unit/agent/result_interpretation_agent/test_evolution_log_schema.py`

Tests: 9

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_caller_payload_fields_reach_disk` | Keep | `for k, v in payload.items(): assert row[k] == v` — verifies all four production payload fields round-trip through json.dumps unchanged |
| `test_caller_supplied_timestamp_is_overwritten` | Keep | `assert row["timestamp"] == "1999-12-31T23:59:59"` when caller passes timestamp in payload — documents and pins current override behavior |
| `test_default_str_fallback_for_non_json_native_values` | Keep | `when = datetime(2026, 5, 6, 12, 0, 0)` passed in payload then `assert row["started_at"] == str(when)` — verifies `default=str` serialization fallback |
| `test_first_call_creates_file_with_one_line` | Keep | `_append_evolution_log(str(tmp_path), {"iteration": 1})` then `assert log_path.exists()` and `assert len(lines) == 1` — verifies file creation and single-row write |
| `test_io_error_is_swallowed_not_raised` | Keep | with `patch("nodes.result_interpretation_agent.open", side_effect=OSError(...))` then verifies no raise and `assert "[evolution_log] WARN" in err` — verifies error swallowing contract and warning output |
| `test_missing_workspace_is_created` | Keep | `deep = tmp_path / "nested" / "fresh_chain" / "agent_ws"` then `assert not deep.exists()` then call then `assert deep.is_dir()` — verifies mkdirs behavior |
| `test_repeated_calls_append_distinct_rows` | Keep | `assert [r["iteration"] for r in rows] == [1, 2, 3, 4]` — verifies append-only mode ('a') in correct order |
| `test_smoke_extension_keys_pass_through` | Keep | `assert row["is_degraded"] is True` and `assert row["_smoke_marker"] == "iter_7"` — verifies transparent passthrough of non-standard keys |
| `test_writer_prepends_timestamp` | Keep | `assert "timestamp" in row` and `assert _ISO_SECONDS.match(row["timestamp"])` and `datetime.fromisoformat(row["timestamp"])` — verifies timestamp format and parseability |

### `tests/unit/agent/result_interpretation_agent/test_interpretation_agent.py`

Tests: 71

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_best_config_from_summary` | Keep | `assert output.best_config["model_config"]["depth"] == 4` — exercises config pass-through logic |
| `test_best_score_extracted` | Keep | `output = agent.run(inp); assert output.best_denoising_score == 1.8` — exercises pre-computation from PUNET_SUMMARY.best_denoising_score through the full run() path; the LLM is mocked but the numeric extraction logic is real |
| `test_cache_hit_scores_from_stats` | Keep | `assert output.per_model_best["punet"] == 1.8; assert output.per_model_worst["punet"] == 1.2; assert output.total_experiments == 3` — scores reconstructed from cache _stats |
| `test_cache_hit_skips_llm_call` | Keep | `assert agent.bridge.generate.call_count == call_count_before; assert output.model_knowledge_cache["punet"] == _PUNET_CACHED_ENTRY` — cache hit path; call_count proves no LLM call, content equality proves cache pass-through |
| `test_cache_miss_calls_llm_and_populates_cache` | Keep | `call_count_before = agent.bridge.generate.call_count; output = agent.run(inp); assert agent.bridge.generate.call_count > call_count_before; assert "punet" in output.model_knowledge_cache` — mock call count used to verify code path (cache miss triggers LLM), not to assert mock... |
| `test_cache_miss_stores_stats` | Keep | `stats = output.model_knowledge_cache["punet"]["_stats"]; assert stats["best_denoising_score"] == 1.8; assert stats["worst_denoising_score"] == 1.2; assert stats["completed_rounds"] == 3` — _stats populated from ModelRunSummary |
| `test_carry_forward_metrics_preserved` | Keep | `assert output.cumulative_information_gain == 2.5; assert output.prediction_outcomes_history == {"confirmed": 3, ...}; assert output.vocab_link_confirmations == {...}` — cumulative metrics not zeroed |
| `test_descriptions_loaded_for_all` | Keep | `assert "punet" in output.model_descriptions; assert "fcnet" in output.model_descriptions` |
| `test_descriptions_only_no_summaries` | Keep | `output = agent.run(inp); assert "punet" in output.model_types; assert "punet" in output.model_descriptions; assert output.total_experiments == 0; assert output.best_denoising_score is None` — model_types-only path |
| `test_digest_persisted_to_disk` | Keep | `out_path = tmp_path / "interpretation_degraded_persist.json"; assert out_path.exists(); data = json.loads(out_path.read_text()); assert data["is_degraded"] is True` — file persisted even on failure |
| `test_duplicate_removed_and_aliased` | Keep | `agent.bridge.generate.return_value = {"is_duplicate": True, "duplicate_of": "dilated_causal_conv", ...}; updated_vocab, changes = agent._dedup_promoted(["dilated_conv_alt"], vocab); assert "dilated_conv_alt" not in names; assert "dilated_conv_alt" in canon.aliases; assert len... |
| `test_existing_proposed_by_run_not_overwritten` | Keep | `assert "earlier_model" in entry.seen_in_runs; assert "attn_wavenet" not in entry.seen_in_runs` — injection is conditional, no overwrite |
| `test_expert_advice_before_human_advice_in_per_model` | Keep | `expert_pos = prompt.index("Expert Guidance"); human_pos = prompt.index("Human Guidance"); assert expert_pos < human_pos` — ordering logic |
| `test_expert_advice_before_human_advice_in_synthesis` | Keep | analogous ordering assertion in synthesis prompt |
| `test_formal_score_none_stored_when_absent` | Keep | `assert "formal_score" in stats; assert stats["formal_score"] is None` — explicit None stored when absent |
| `test_formal_score_not_rendered_when_equal_to_best` | Keep | `assert "Formal score" not in prompt` when `per_model_formal={"punet": 1.8}` == best — suppression logic |
| `test_formal_score_reconstructed_from_cache` | Keep | `assert "punet" in output.model_knowledge_cache; assert output.model_knowledge_cache["punet"]["_stats"]["formal_score"] == 1.5` — formal_score passes through from cache |
| `test_formal_score_rendered_in_synthesis_when_different` | Keep | `assert "Formal score" in prompt; assert "1.5" in prompt; assert "trial" in prompt` — conditional rendering in synthesis prompt |
| `test_formal_score_stored_in_stats_on_cache_miss` | Keep | `stats = output.model_knowledge_cache["punet"]["_stats"]; assert "formal_score" in stats; assert stats["formal_score"] == 1.5` — formal_score stored in cache |
| `test_genuine_new_entry_stays_canonical` | Keep | `agent.bridge.generate.return_value = {"is_duplicate": False, ...}; updated_vocab, changes = agent._dedup_promoted(["log_fno"], vocab); assert any(e.name == "log_fno" for e in updated_vocab); assert changes == []` — LLM says not a dup → entry stays; logic post-LLM call |
| `test_healthy_path_default_is_not_degraded` | Keep | `output = agent.run(inp); assert output.is_degraded is False` — sanity guard: healthy path flag |
| `test_includes_best_score_table_rendered_markdown` | Keep | `prompt = _build_per_model_prompt(ENRICHED_SUMMARY, "PUNet description"); assert "Per-file performance (best experiment)" in prompt; assert "(test fixture)" in prompt` — real prompt builder logic |
| `test_includes_formal_score` | Keep | `assert "Formal round score" in prompt; assert "1.6" in prompt` — formal score rendered in prompt |
| `test_includes_formal_score_table` | Keep | `assert "Per-file performance (formal round" in prompt` |
| `test_includes_model_params` | Keep | `assert "55,000" in prompt` — formatted number in prompt |
| `test_includes_params` | Keep | `assert "55,000" in prompt` for per_model_params kwarg |
| `test_includes_round_model_params_in_trajectory` | Keep | `assert "params=55,000" in prompt` |
| `test_includes_round_trial_portions_in_trajectory` | Keep | `assert "portion=0.05" in prompt; assert "portion=0.1" in prompt  # round 3 increased portion` |
| `test_includes_score_table` | Keep | `assert "Per-file performance (best experiment)" in prompt; assert "(test fixture)" in prompt; assert "Weak Frequency" not in prompt` — deprecated block absent |
| `test_includes_training_psd_segments` | Keep | `assert "200" in prompt; assert "4000" in prompt  # baseline reference` |
| `test_includes_training_segments` | Keep | `assert "200" in prompt` for per_model_training_segments kwarg |
| `test_includes_trial_portion` | Keep | `assert "0.05" in prompt` |
| `test_invalid_duplicate_of_name_treated_as_genuine` | Keep | `return_value = {"is_duplicate": True, "duplicate_of": "nonexistent_entry", ...}` → `assert any(e.name == "log_fno" for e in updated_vocab); assert changes == []` — nonexistent merge target → treated as genuine |
| `test_is_degraded_flag_true` | Keep | `assert output.is_degraded is True` — degraded flag set |
| `test_key_findings_and_bottlenecks_empty` | Keep | `assert output.key_findings == []; assert output.bottlenecks == []; assert output.new_discoveries == []` — degraded output is empty, not invented |
| `test_mixed_one_cached_one_new_llm_called_once` | Keep | `calls_made = agent.bridge.generate.call_count - call_count_before; assert calls_made == 2` — call count verifies one Phase 1 + one Phase 2 call; real routing logic |
| `test_model_description_loaded` | Keep | `assert "punet" in output.model_descriptions; assert len(output.model_descriptions["punet"]) > 100` — description loaded from disk file |
| `test_no_existing_canonicals_of_same_kind_skips_llm` | Keep | `call_count_before = agent.bridge.generate.call_count; updated_vocab, changes = agent._dedup_promoted(["log_fno"], [promoted]); assert agent.bridge.generate.call_count == call_count_before; assert changes == []` — skip condition when only entry of its kind |
| `test_no_model_provided_raises` | Keep | `with pytest.raises(Exception, match="At least one model type"): InterpretationInput()` — schema validation |
| `test_no_previous_proposal_no_crash` | Keep | `output = agent.run(inp)` with `previous_proposal=None` → `assert "log_fno_gates" not in candidate_names` — first iteration path, no crash |
| `test_no_promotions_skips_llm` | Keep | `call_count_before = agent.bridge.generate.call_count; updated_vocab, changes = agent._dedup_promoted([], vocab); assert agent.bridge.generate.call_count == call_count_before` — early-exit path (no promotions → LLM not called); call count verifies code path |
| `test_none_fields_produce_none_output` | Keep | `assert output.per_model_score_tables is None; assert output.per_model_params is None; assert output.per_model_training_segments is None` — old-style summary → None enriched fields |
| `test_only_same_kind_used_for_comparison` | Keep | `call_args = agent.bridge.generate.call_args[0]; assert "dilated_causal_conv" not in call_args[1]` — kind-filtering logic for what goes into the LLM prompt |
| `test_output_is_valid` | Keep | `assert isinstance(output, InterpretationOutput); assert "punet" in output.model_types` — schema type validation |
| `test_output_written_to_file` | Keep | `out_path = tmp_path / "interpretation_myrun.json"; assert out_path.exists(); data = json.loads(out_path.read_text()); assert "punet" in data["model_types"]; assert data["best_denoising_score"] == 1.8` — file persistence contract |
| `test_overall_best_is_cross_model_max` | Keep | `assert output.best_denoising_score == 1.8; assert output.worst_denoising_score == 0.5` — cross-model aggregation |
| `test_per_model_params_populated` | Keep | `assert output.per_model_params["punet"] == 55000` |
| `test_per_model_prompt_excludes_expert_when_empty` | Keep | `assert "Expert Guidance" not in prompt` when `expert_advice_str=""` — conditional |
| `test_per_model_prompt_includes_expert_advice_string` | Keep | `assert "Expert Guidance" in prompt; assert "Focus on low-frequency performance" in prompt` — injection |
| `test_per_model_score_tables_populated` | Keep | `table = output.per_model_score_tables["punet"]; assert isinstance(table, ScoreComparisonTable); assert len(table.rows) == 20` — score table extracted |
| `test_per_model_scores` | Keep | `assert output.per_model_best["punet"] == 1.8; assert output.per_model_worst["punet"] == 1.2` — per-model score dict construction |
| `test_per_model_scores_independent` | Keep | `assert output.per_model_best["punet"] == 1.8; assert output.per_model_best["fcnet"] == 0.9` — independent per-model dicts |
| `test_per_model_summaries_for_all` | Keep | `assert "punet" in output.model_knowledge_cache; assert "fcnet" in output.model_knowledge_cache` |
| `test_per_model_summaries_populated` | Keep | `assert "punet" in output.model_knowledge_cache; assert output.model_knowledge_cache["punet"]["key_findings"] == FAKE_PER_MODEL_RESPONSE["key_findings"]` — cache population |
| `test_per_model_training_segments_populated` | Keep | `assert output.per_model_training_segments["punet"] == 200` |
| `test_phase1_findings_used` | Keep | `assert output.key_findings == FAKE_PER_MODEL_RESPONSE["key_findings"]` — LLM response merged into output for single-model path |
| `test_proposed_by_run_injected_from_model_name` | Keep | `entry = next((e for e in output.runtime_vocab if e.name == "log_fno_gates"), None); assert "attn_wavenet" in entry.seen_in_runs` — injection logic: model_name → proposed_by_run |
| `test_returns_output_instead_of_raising` | Keep | `agent = self._make_failing_agent(); output = agent.run(inp); assert isinstance(output, InterpretationOutput)` — degraded path: LLM failure → catches and returns output |
| `test_runtime_vocab_carried_forward_unchanged` | Keep | `out_names = sorted(e.name for e in output.runtime_vocab); in_names = sorted(e["name"] for e in self.INCOMING_VOCAB); assert out_names == in_names` — vocab preservation on failure |
| `test_skips_none_fields` | Keep | `prompt = _build_per_model_prompt(PUNET_SUMMARY, "PUNet description"); assert "Per-file performance" not in prompt; assert "Formal round score" not in prompt; assert "Training PSD segments" not in prompt` — None fields omitted |
| `test_synthesis_prompt_excludes_expert_when_empty` | Keep | `assert "Expert Guidance" not in prompt` |
| `test_synthesis_prompt_includes_expert_advice_string` | Keep | `assert "Expert Guidance" in prompt; assert "Compare all models on same data volume" in prompt` |
| `test_synthesis_prompt_renders_weight_and_impact_columns` | Keep | builds real `impact_table` via `build_score_table(...)` then `assert "Weight %" in prompt; assert "Impact" in prompt; assert "Sampled files re-ranked by Impact_Score" in prompt` — real scoring helper used to build a non-fixture table |
| `test_synthesis_used_for_multi_model` | Keep | `assert output.key_findings == FAKE_SYNTHESIS_RESPONSE["key_findings"]; assert output.take_home_message == FAKE_SYNTHESIS_RESPONSE["take_home_message"]` — synthesis path used for multi-model |
| `test_take_home_message_marks_degraded` | Keep | `assert "DEGRADED" in output.take_home_message` — specific marker in message |
| `test_total_experiments` | Keep | `assert output.total_experiments == 3` — completed_rounds extraction |
| `test_total_experiments_across_models` | Keep | `assert output.total_experiments == 5  # 3 + 2` — summing completed_rounds across models |
| `test_two_models_both_in_output` | Keep | `assert "punet" in output.model_types; assert "fcnet" in output.model_types` — multi-model run |
| `test_unknown_model_type_raises` | Keep | `with pytest.raises(FileNotFoundError, match="nonexistent_model")` — model description file not found |
| `test_works_without_new_fields` | Keep | `assert "punet" in prompt; assert "Per-file performance" not in prompt` — None fields → sections absent |
| `test_worst_score_extracted` | Keep | `assert output.worst_denoising_score == 1.2` — analogous to above for worst score |

### `tests/unit/agent/result_interpretation_agent/test_interpretation_schemas.py`

Tests: 19

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_active_model_custom` | Keep | `assert inp.active_model_top_k == 5` and `assert inp.active_model_last_n == 1` and `assert inp.active_model_score_delta == 0.1` — custom override propagation |
| `test_active_model_defaults` | Keep | `assert inp.active_model_top_k == 3` and `assert inp.active_model_last_n == 2` and `assert inp.active_model_score_delta == 0.05` — pins three design-doc defaults |
| `test_active_model_negative_delta_rejected` | Keep | `with pytest.raises(ValidationError, match="greater than or equal to 0"): InterpretationInput(model_types=["punet"], active_model_score_delta=-0.01)` — negative delta rejected |
| `test_active_model_negative_last_n_rejected` | Keep | `with pytest.raises(ValidationError, match="greater than or equal to 0"): InterpretationInput(model_types=["punet"], active_model_last_n=-1)` — negative N rejected |
| `test_active_model_negative_top_k_rejected` | Keep | `with pytest.raises(ValidationError, match="greater than or equal to 0"): InterpretationInput(model_types=["punet"], active_model_top_k=-1)` — negative K rejected |
| `test_active_model_zero_allowed` | Keep | `assert inp.active_model_top_k == 0` etc — pins K=N=Δ=0 is valid (disables pathways) |
| `test_empty_model_types_raises` | Keep | `with pytest.raises(ValidationError, match="model_types cannot be an empty list"): InterpretationInput(model_types=[])` — pins specific error message |
| `test_minimal` | Keep | `assert s.round_scores == []` and `assert s.best_denoising_score is None` — pins optional field defaults |
| `test_missing_take_home_message_raises` | Keep | `with pytest.raises(ValidationError) as exc:` and `assert "take_home_message" in str(exc.value)` — required field rejection |
| `test_no_model_raises` | Keep | `with pytest.raises(ValidationError, match="At least one model type"): InterpretationInput()` — pins cross-field validation error message |
| `test_storage_custom` | Keep | `assert inp.storage.local.workspace == "/runs"` — verifies nested storage override |
| `test_storage_default` | Keep | `assert inp.storage.local.workspace == "./siderius_workspace"` — pins default workspace path |
| `test_valid` | Keep | `assert s.model_type == "punet"` and `assert s.completed_rounds == 10` and `assert len(s.round_scores) == 4` — baseline field population |
| `test_valid_full` | Keep | `assert out.total_experiments == 10` and `assert out.per_model_best["punet"] == 1.5` and `assert out.worst_denoising_score == 0.3` — full output schema baseline |
| `test_valid_multi_model` | Keep | `assert len(out.model_types) == 2` and `assert out.per_model_best["fcnet"] == 0.8` — multi-model output |
| `test_valid_no_experiments` | Keep | `assert out.best_denoising_score is None` and `assert out.best_config is None` and `assert out.per_model_best == {}` — zero experiments defaults |
| `test_valid_with_both` | Keep | `assert len(inp.summaries) == 1` and `assert "fcnet" in inp.model_types` — valid with both fields |
| `test_valid_with_model_types` | Keep | `assert inp.model_types == ["punet", "fcnet"]` and `assert inp.summaries == []` — pins default empty summaries |
| `test_valid_with_summaries` | Keep | `assert inp.storage.backend == "local"` — verifies default storage backend when summaries provided |

### `tests/unit/agent/result_interpretation_agent/test_stability_filter.py`

Tests: 22

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_active_set_top_k_plus_last_n_plus_delta` | Keep | `assert active == {"mt_e", "mt_d", "mt_c", "mt_x", "mt_y", "mt_b"}` — exercises union of Top-K + Last-N + Delta paths with non-trivial 7-model cache; real set logic |
| `test_active_with_more_rounds_recalls` | Keep | `should_recall_per_model(..., rounds=8, active_set={"mt"}) is True` — exercises new-rounds-trigger path |
| `test_active_with_no_new_evidence_skips` | Keep | `should_recall_per_model(..., best=2.0, rounds=5, active_set={"mt"}) is False` — exercises subtle skip: active but unchanged |
| `test_active_with_score_delta_recalls` | Keep | `should_recall_per_model(..., best=3.0, ..., score_delta_threshold=0.05) is True` — exercises score-delta-trigger path |
| `test_below_threshold_delta_skips` | Keep | `should_recall_per_model(..., best=2.01, ..., score_delta_threshold=0.05) is False` — pins delta=0.01 < 0.05 boundary exclusion |
| `test_cache_miss_always_recalls` | Keep | `should_recall_per_model(..., cache_entry=None, ..., active_set=set()) is True` — exercises cache-miss → always-recall contract |
| `test_compress_falls_back_to_best_config_analysis` | Keep | `assert "hidden=128" in result["one_line_takeaway"]` when key_findings is empty — exercises fallback logic |
| `test_compress_placeholder_when_nothing_available` | Keep | `assert result["one_line_takeaway"] == "(no cached takeaway)"` — exercises terminal fallback |
| `test_compress_preserves_key_finding` | Keep | `assert result["one_line_takeaway"] == finding` and `assert result["best_score"] == 4.5` — exercises deterministic compressor on well-formed entry |
| `test_compress_total_serialised_length_under_200` | Keep | `assert len(rendered) <= 200` for a rendered summary string — pins prompt-space budget contract |
| `test_compress_truncates_long_finding_with_ellipsis` | Keep | `assert len(result["one_line_takeaway"]) == 50` and `assert result["one_line_takeaway"].endswith("…")` — pins truncation arithmetic |
| `test_compress_zero_max_takeaway_rejected` | Keep | `with pytest.raises(ValueError, match="must be positive")` for `max_takeaway_chars=0` — exercises input validation |
| `test_delta_at_or_above_threshold_included` | Keep | `assert active == {"changed"}` when `delta=0.5 == threshold=0.5` — pins exact boundary inclusion |
| `test_delta_below_threshold_excluded` | Keep | `assert active == set()` when delta=0.01 < 0.05 threshold — pins boundary exclusion |
| `test_delta_path_skipped_for_models_without_prior` | Keep | `assert active == {"brand_new"}` with empty cache — exercises Last-N contribution without Delta path |
| `test_empty_cache_and_no_summaries` | Keep | `assert active == set()` — exercises empty-input edge case |
| `test_inactive_with_new_data_still_skips` | Keep | `should_recall_per_model(..., best=5.0, rounds=10, active_set=set()) is False` — exercises master-gate: inactive overrides new data |
| `test_last_n_truncates_to_first_n` | Keep | `assert active == {"mt_0", "mt_1"}` from 5 summaries with `last_n=2` — exercises first-N slicing |
| `test_lex_tiebreak_determinism` | Keep | `assert active == {"apple", "mango"}` with 3 equal-score models — pins lexicographic tiebreak contract |
| `test_negative_thresholds_rejected` | Keep | `with pytest.raises(ValueError, match="non-negative")` for `top_k=-1`, `last_n=-1`, and `score_delta_threshold=-0.1` — exercises input validation guards |
| `test_stability_filter_skips_stable_models` | Keep | `assert skip_decisions == {"mt_0": False, ..., "mt_5": False, "mt_6": False}` — pins V12 regression: active-set membership alone (without new data) must NOT trigger recall |
| `test_top_k_excludes_models_with_none_score` | Keep | `assert active == {"rank_me"}` when `no_score` has `best=None` — exercises None-score exclusion from Top-K ranking |

### `tests/unit/agent/result_interpretation_agent/test_vocab_feedback.py`

Tests: 61

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_adds_candidates` | Keep | `assert len(result) == 2` after adding candidate dict — exercises candidate dict → VocabEntry coercion |
| `test_adds_discoveries` | Keep | `assert "discovery_1" in names` — exercises discovery addition |
| `test_all_candidates_returns_one` | Keep | `assert compute_vocab_diversity_ratio(vocab) == 1.0` — exercises all-candidate ratio |
| `test_all_canonical_returns_zero` | Keep | `assert compute_vocab_diversity_ratio(vocab) == 0.0` with all canonical — exercises zero-candidate ratio |
| `test_already_canonical_untouched` | Keep | `assert promoted == []` and `assert vocab[0].tier == "canonical"` — exercises idempotency of promotion |
| `test_already_in_related_to_not_promoted_twice` | Keep | `assert promoted == []` and `assert feat.related_to.count("receptive_field") == 1` — exercises idempotency guard |
| `test_below_threshold_no_promotion` | Keep | `assert promoted == []` and `assert "receptive_field" not in feat.related_to` with 2 < min_runs=3 — exercises below-threshold non-promotion |
| `test_boldness_uses_sota_baseline` | Keep | `assert abs(result["boldness"] - 0.2) < 1e-4` — exercises boldness formula `|predicted - sota| / |sota|` |
| `test_boldness_zero_when_no_predicted_value` | Keep | `assert result["boldness"] == 0.0` when no `predicted_value` key — exercises missing-key guard |
| `test_capability_with_enough_runs_promoted` | Keep | `assert promoted == ["freq_selectivity"]` — exercises capability-kind promotion |
| `test_confirmed_beats_sota` | Keep | `assert result["outcome"] == "confirmed"` and `assert result["delta_from_sota"] > 0` for actual=5.5 > sota=5.0 — real comparison logic |
| `test_confirmed_outcome_increments_count` | Keep | `assert confs["dilated_causal_conv:receptive_field"] == ["run_a"]` — exercises confirmation counting for confirmed outcome |
| `test_confirmed_prediction` | Keep | `assert any("CONFIRMED" in d.description for d in discoveries)` and `assert all(d.kind == "discovery" for d in discoveries)` — exercises discovery generation for confirmed outcome |
| `test_current_sota_override_takes_precedence` | Keep | `assert result["outcome"] == "confirmed"` and `assert result["current_sota"] == 6.0` — exercises current_sota override parameter |
| `test_custom_min_runs` | Keep | `assert promoted == ["log_fno"]` with `min_runs=2` and 2 runs — exercises configurable threshold |
| `test_deduplicates_by_name` | Keep | `assert len(result) == 1` and `assert result[0].description == "updated"` — exercises name-dedup: discovery overwrites seed entry |
| `test_different_runs_accumulated` | Keep | `assert set(confs["dilated_causal_conv:receptive_field"]) == {"run_a", "run_b", "run_c"}` — exercises multi-run accumulation |
| `test_discoveries_excluded_from_ratio` | Keep | `assert compute_vocab_diversity_ratio(vocab) == 0.0` with 1 canonical feature + 2 discovery candidates — exercises discovery exclusion from denominator |
| `test_discovery_never_promoted_regardless_of_runs` | Keep | `assert promoted == []` for `kind="discovery"` with 5 runs — exercises discovery exclusion from promotion |
| `test_does_not_mutate_existing_confirmations` | Keep | `assert existing["dilated_causal_conv:receptive_field"] is original_list` and `assert "run_b" not in original_list` — exercises immutability contract |
| `test_empty_vocab` | Keep | `assert vocab == []` and `assert promoted == []` — exercises empty-list edge case |
| `test_empty_vocab_returns_zero` | Keep | `assert compute_vocab_diversity_ratio([]) == 0.0` — exercises empty-input edge case |
| `test_exactly_at_sota_is_partial` | Keep | `assert result["outcome"] == "partial"` when actual==sota — pins strict-greater-than boundary |
| `test_existing_candidate_seen_in_runs_extended` | Keep | `assert set(entry.seen_in_runs) == {"model_a", "model_b"}` across two iterations — exercises run accumulation |
| `test_feature_not_in_vocab_no_crash` | Keep | `assert promoted == []` when feature not in runtime_vocab — exercises graceful skip |
| `test_feature_with_enough_runs_promoted` | Keep | `assert promoted == ["log_fno"]` and `assert vocab[0].tier == "canonical"` with 3 seen_in_runs — exercises promotion threshold |
| `test_file_vector_metric_confirmed` | Keep | `assert result["actual_value"] == 2.0` (mean of slice) and `assert result["outcome"] == "confirmed"` — exercises file-vector metric computation |
| `test_half_candidates` | Keep | `assert abs(compute_vocab_diversity_ratio(vocab) - 0.5) < 1e-9` — exercises fractional ratio computation |
| `test_information_gain_confirmed_equals_delta` | Keep | `assert abs(result["information_gain"] - result["delta_from_sota"]) < 1e-6` — pins information_gain formula for confirmed outcome |
| `test_information_gain_zero_when_partial` | Keep | `assert result["information_gain"] == 0.0` for partial outcome — exercises outcome-gated information_gain |
| `test_information_gain_zero_when_refuted` | Keep | `assert result["information_gain"] == 0.0` for refuted outcome — exercises outcome-gated information_gain |
| `test_insufficient_runs_stays_candidate` | Keep | `assert promoted == []` and `assert vocab[0].tier == "candidate"` with only 2 runs — exercises below-threshold non-promotion |
| `test_missing_actual_results` | Keep | `assert result["outcome"] == "partial"` and `assert "Could not compute" in result.get("notes", "")` — exercises missing-data fallback |
| `test_missing_current_sota_and_current_value` | Keep | `assert result["current_sota"] is None` — exercises None-sota path |
| `test_missing_current_sota_falls_back_to_current_value` | Keep | `assert result["current_sota"] == 5.0` — exercises fallback from prediction dict's current_value |
| `test_missing_proposed_by_run_no_crash` | Keep | `assert entry.seen_in_runs == []` — exercises missing-key defensive handling |
| `test_mixed_vocab` | Keep | `assert abs(ratio - 1 / 3) < 1e-9` for 2 canonical + 1 candidate + 3 discoveries — exercises mixed-kind ratio |
| `test_mixed_vocab_only_eligible_promoted` | Keep | `assert promoted == ["feat_a"]` with mixed feature/discovery/canonical entries — exercises eligibility filtering |
| `test_multiple_links_promoted_independently` | Keep | `assert len(promoted) == 2` and both `related_to` fields populated — exercises multi-link independent promotion |
| `test_new_candidate_gets_proposed_by_run` | Keep | `assert entry.seen_in_runs == ["wavenet_v2"]` — exercises proposed_by_run → seen_in_runs tracking |
| `test_no_prediction` | Keep | `assert all(d.kind == "discovery" for d in discoveries)` — exercises no-prediction path (prediction_eval=None) |
| `test_none_outcome_does_not_increment` | Keep | `assert confs.get("dilated_causal_conv:receptive_field", []) == []` for `prediction_outcome=None` — exercises None-outcome guard |
| `test_only_discoveries_returns_zero` | Keep | `assert compute_vocab_diversity_ratio(vocab) == 0.0` with only discovery — exercises zero-denominator guard |
| `test_overall_best_score_negates_false_beat` | Keep | `assert "beating" not in score_disc.description` when real SOTA=6.0 > actual=5.8 — exercises guard against false "beating" when real SOTA is higher |
| `test_overall_best_score_only_no_prediction` | Keep | `assert "beating" in score_disc.description` when `prediction_eval=None` and `overall_best_score=5.5` — exercises overall_best_score-only path |
| `test_overall_best_score_overrides_stale_sota` | Keep | `assert "beating" in score_disc.description` and `assert "6.2" in score_disc.description` — exercises overall_best_score override: must use 6.2 not stale 5.5 |
| `test_partial_margin_custom` | Keep | `assert result["outcome"] == "partial"` for actual=4.6 with custom `partial_margin=0.10` — exercises configurable margin |
| `test_partial_outcome_does_not_increment` | Keep | `assert confs.get("dilated_causal_conv:receptive_field", []) == []` — exercises non-counting for partial outcome |
| `test_partial_with_none_actual` | Keep | `assert any("PARTIAL" in d.description for d in discoveries)` and `assert any("N/A" in d.description for d in discoveries)` — regression test for `actual_value=None` format-string crash |
| `test_partial_within_margin` | Keep | `assert result["outcome"] == "partial"` for actual=4.8 within 5% of sota=5.0 — exercises margin band logic |
| `test_promotes_to_related_to_at_threshold` | Keep | `assert "dilated_causal_conv:receptive_field" in promoted` and `assert "receptive_field" in feat.related_to` — exercises link promotion at min_runs threshold |
| `test_refuted_clearly_below_sota` | Keep | `assert result["outcome"] == "refuted"` for actual=4.0 below 5% threshold — exercises refutation boundary |
| `test_refuted_outcome_does_not_increment` | Keep | `assert confs.get("dilated_causal_conv:receptive_field", []) == []` — exercises non-counting for refuted outcome |
| `test_refuted_prediction` | Keep | `assert any("REFUTED" in d.description for d in discoveries)` — exercises discovery generation for refuted outcome |
| `test_returns_correct_promoted_names` | Keep | `assert set(promoted) == {"a", "c"}` from mixed-runs list — exercises multi-entry promotion |
| `test_same_run_not_counted_twice` | Keep | `assert confs["dilated_causal_conv:receptive_field"].count("run_a") == 1` — exercises run deduplication |
| `test_same_run_not_duplicated_in_seen_in_runs` | Keep | `assert entry.seen_in_runs.count("model_a") == 1` when same run proposes twice — exercises deduplication |
| `test_score_vs_sota` | Keep | `assert any("beating" in d.description for d in score_discoveries)` — exercises score-vs-sota comparison logic |
| `test_seed_only` | Keep | `assert len(result) == 2` — exercises build_runtime_vocab with seed-only input |
| `test_seen_in_runs_enables_promotion_after_three_iterations` | Keep | `assert "log_fno" in promoted` after 3 iterations with different runs — exercises end-to-end promotion via seen_in_runs |
| `test_vocab_grows_across_iterations` | Keep | `assert len(vocab) == 4` after 3 iterations adding discoveries and candidates — exercises multi-iteration vocab accumulation |

### `tests/unit/agent/schemas/test_score_table.py`

Tests: 28

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_all_model_side_columns_may_be_none` | Keep | `row = PerFileRow(..., model=None, gain_vs_raw=None, headroom_vs_gt=None)` then `assert row.model is None` — tests that nullable model-side columns are accepted |
| `test_extra_fields_forbidden` | Keep | `with pytest.raises(ValidationError): PerFileRow(..., whatever="nope")` — tests that extra fields raise due to `model_config = ConfigDict(extra="forbid")` |
| `test_extra_fields_forbidden_on_table` | Keep | `with pytest.raises(ValidationError): ScoreComparisonTable(..., who="knows")` — tests extra="forbid" on table level |
| `test_file_index_range` | Keep | `with pytest.raises(ValidationError): PerFileRow(file_index=20, ...)` and `PerFileRow(file_index=-1, ...)` — tests Pydantic ge/le range validation on file_index |
| `test_full_run_aggregate` | Keep | `agg = AggregateScalars(..., num_sampled_files=20)` then `assert agg.num_sampled_files == 20` — tests valid construction of AggregateScalars |
| `test_fully_populated_row` | Keep | `row = PerFileRow(file_index=12, ...)` then `assert row.file_index == 12` — tests valid Pydantic construction and attribute access |
| `test_happy_path_20_rows` | Keep | `tbl = ScoreComparisonTable(rows=rows, ...)` then `assert len(tbl.rows) == 20` — tests valid construction of table with exactly 20 rows |
| `test_headroom_negative_rejected` | Keep | `with pytest.raises(ValidationError): PerFileRow(..., headroom_vs_gt=-5.0)` — tests ge=0 constraint on headroom_vs_gt |
| `test_headroom_none_accepted_for_unsampled_file` | Keep | `assert row.headroom_vs_gt is None` — tests that None is accepted for optional headroom |
| `test_headroom_zero_accepted` | Keep | `assert row.headroom_vs_gt == 0.0` — tests that boundary value 0.0 is accepted |
| `test_impact_columns_default_to_none` | Keep | `assert row.linear_weight is None` and `assert row.impact_score is None` — tests backward compatibility: new fields default to None |
| `test_impact_score_clamps_at_zero_for_already_saturated_file` | Keep | `row = _row_with_impact(3, model=1.5, weight=0.05, impact=0.0)` then `assert row.impact_score == 0.0` — tests boundary value 0.0 accepted for impact_score |
| `test_impact_score_negative_rejected` | Keep | `with pytest.raises(ValidationError): _row_with_impact(0, model=0.0, weight=0.05, impact=-0.1)` — tests ge=0 constraint on impact_score |
| `test_json_round_trip_preserves_none` | Keep | `restored = PerFileRow.model_validate_json(row.model_dump_json())` then `assert restored == row` — tests None-preservation through JSON serialization round-trip |
| `test_json_round_trip_preserves_rendered_markdown` | Keep | `restored = ScoreComparisonTable.model_validate_json(tbl.model_dump_json())` then `assert restored.rendered_markdown == tbl.rendered_markdown` — tests markdown string survives JSON round-trip |
| `test_linear_weight_above_one_rejected` | Keep | `with pytest.raises(ValidationError): _row_with_impact(0, model=0.0, weight=1.000001, impact=0.0)` — tests le=1 constraint on linear_weight |
| `test_linear_weight_at_bounds_accepted` | Keep | `for w in (0.0, 1.0, 0.5): row = _row_with_impact(0, model=0.0, weight=w, impact=0.0)` — tests valid boundary values for linear_weight |
| `test_linear_weight_negative_rejected` | Keep | `with pytest.raises(ValidationError): _row_with_impact(0, model=0.0, weight=-0.1, impact=0.0)` — tests ge=0 constraint on linear_weight |
| `test_num_sampled_files_lower_bound` | Keep | `with pytest.raises(ValidationError): AggregateScalars(..., num_sampled_files=0)` — tests ge=1 constraint |
| `test_num_sampled_files_upper_bound` | Keep | `with pytest.raises(ValidationError): AggregateScalars(..., num_sampled_files=21)` — tests le=20 constraint |
| `test_rejects_fewer_than_20_rows` | Keep | `with pytest.raises(ValidationError): ScoreComparisonTable(rows=[_row(...) for i in range(19)], ...)` — tests min_length=20 constraint |
| `test_rejects_more_than_20_rows` | Keep | `with pytest.raises(ValidationError): ScoreComparisonTable(rows=[...] * 21, ...)` — tests max_length=20 constraint |
| `test_trial_run_aggregate` | Keep | `agg = AggregateScalars(..., num_sampled_files=5)` then `assert agg.num_sampled_files == 5` — tests partial-run (trial) aggregate |
| `test_validator_passes_when_rows_and_total_agree` | Keep | `tbl = self._build_table(weights=[0.05]*20, stored_total=1.0)` then `assert tbl.linear_weight_total == pytest.approx(1.0)` — tests validator pass condition |
| `test_validator_rejects_off_sum_full_subset` | Keep | `weights = [0.04] * 20` then `with pytest.raises(ValidationError, match="sum to"): self._build_table(...)` — tests custom Pydantic validator that checks Σ linear_weight ≈ 1.0 |
| `test_validator_rejects_stored_total_off_even_when_rows_sum_to_one` | Keep | `with pytest.raises(ValidationError, match="linear_weight_total"): self._build_table(weights=[0.05]*20, stored_total=0.95)` — tests that stored_total mismatch is caught even when rows sum correctly |
| `test_validator_skipped_when_no_sampled_weights` | Keep | `tbl = self._build_table(weights=[None]*20, stored_total=0.0)` then `assert tbl.linear_weight_total == 0.0` — tests validator early-return for all-None weights |
| `test_validator_tolerates_float_round_off_within_1e9` | Keep | `for i in (3, 7, 9, 11, 14): weights[i] = 0.2` then passes — tests float tolerance in the sum validator; `0.2 * 5 = 1.0000000000000002` in binary, which is within 1e-9 tolerance |

### `tests/unit/agent/test_llm_bridge.py`

Tests: 62

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_arguments_are_parsed_dict` | Keep | `assert isinstance(result.arguments, dict)` and `assert result.arguments["max_results"] == 5` — verifies JSON parsing of arguments |
| `test_cross_provider_creates_distinct_clients` | Keep | `assert bridge.client is not bridge.reflect_client` and `assert MockOpenAI.call_count == 2` — verifies two distinct clients created |
| `test_cross_provider_routes_reflect_to_second_client` | Keep | `assert main_client.chat.completions.create.call_count == 1` (unchanged) and `assert reflect_client.chat.completions.create.call_count == 1` after reflect() call — verifies routing to second client |
| `test_default_both_methods_use_same_model` | Keep | `assert bridge.model_name == "planner-model"` and `assert bridge.reflect_model_name == "planner-model"` — verifies backward-compat default |
| `test_default_reflect_provider_falls_back_to_main_provider` | Keep | `assert bridge.provider == "gemini"` and `assert bridge.reflect_provider == "gemini"` — verifies default provider fallback |
| `test_empty_content_retried_then_succeeds` | Keep | `assert result == VALID_JSON_DICT` and `assert mock_create.call_count == 3` with two empty then one valid — deepseek failure mode regression |
| `test_explicit_args_override_known_defaults` | Keep | `assert bridge.model_name == "override-model"` and `assert call_kwargs.kwargs["base_url"] == "https://override.com/v1"` — verifies explicit args override known defaults |
| `test_explicit_none_falls_back_to_main_model` | Keep | `assert bridge.reflect_model_name == "planner-model"` when `reflect_model_id=None` — verifies explicit None falls back |
| `test_explicit_same_provider_reuses_client` | Keep | `assert bridge.client is bridge.reflect_client` — verifies client identity (reuse, not duplicate) |
| `test_extra_json_object_after_valid_one_is_discarded` | Keep | `result = bridge.generate(SYSTEM_PROMPT, USER_PROMPT)` then `assert result == VALID_JSON_DICT` with double-object payload — regression test for explore_novel_v4_0425 crash |
| `test_generate_always_uses_main_model` | Keep | `assert mock_create.call_args.kwargs["model"] == "planner-model"` — verifies generate() always uses main model even when split |
| `test_honors_retry_delay_on_429` | Keep | `mock_sleep.assert_called_once_with(300.0)` — verifies that retryDelay from API body is honored over exponential backoff |
| `test_json_mode_requested` | Keep | `assert call_kwargs["response_format"] == {"type": "json_object"}` — verifies generate() passes json_object mode to API |
| `test_known_provider_default_model` | Keep | `assert bridge.model_name == _KNOWN_PROVIDERS["gemini"]["default_model"]` — verifies default model fallback |
| `test_known_provider_gemini` | Keep | `assert bridge.provider == "gemini"` and `assert call_kwargs.kwargs["base_url"] == _KNOWN_PROVIDERS["gemini"]["base_url"]` — verifies provider resolution and correct URL passed to OpenAI constructor |
| `test_known_provider_openai` | Keep | `assert "base_url" not in call_kwargs.kwargs` — verifies OpenAI provider does not inject a base_url override |
| `test_malformed_json_raises_value_error` | Keep | `with pytest.raises(ValueError, match="not valid JSON")` and `assert mock_create.call_count == bridge._CONTENT_RETRY_BUDGET + 1` — verifies retry budget and final ValueError |
| `test_malformed_then_valid_succeeds` | Keep | `assert result == VALID_JSON_DICT` and `assert mock_create.call_count == 2` — retry recovery test |
| `test_markdown_fenced_json_is_parsed` | Keep | `assert result == VALID_JSON_DICT` when response is ` ```json\n...\n``` ` — verifies fenced JSON stripping |
| `test_messages_contain_system_and_user` | Keep | `assert messages[0] == {"role": "system", "content": SYSTEM_PROMPT}` and `assert messages[1] == {"role": "user", "content": USER_PROMPT}` — verifies message format |
| `test_no_json_mode_requested` | Keep | `assert "response_format" not in call_kwargs` — verifies generate_text() does not request JSON mode |
| `test_non_dict_or_list_first_token_raises` | Keep | `with pytest.raises(ValueError, match="not valid JSON")` and `assert mock_create.call_count == bridge._CONTENT_RETRY_BUDGET + 1` — verifies bare primitive triggers retry budget exhaustion |
| `test_old_file_vector_section_removed_from_planner` | Keep | `assert "FILE VECTOR AND SCORING" not in PLANNER_PROMPT` and `assert "per-file score of ~1.0" not in PLANNER_PROMPT` — verifies §9.1 rewrite removed deprecated content |
| `test_parses_seconds_string` | Keep | `assert LLMBridge._parse_retry_delay(exc) == 28890.0` — pure parsing logic test |
| `test_plan_empty_string_treated_as_none` | Keep | `assert _PLANNER_SCORE_TABLE_FALLBACK in sent_system` when `score_table_md=""` — verifies falsy empty string triggers fallback |
| `test_plan_none_uses_planner_fallback` | Keep | `assert _PLANNER_SCORE_TABLE_FALLBACK in sent_system` and `assert "{SCORE_COMPARISON_TABLE}" not in sent_system` — verifies fallback when no table provided |
| `test_plan_substitutes_score_table_md_into_system_prompt` | Keep | `assert _TABLE_MARKER in sent_system` and `assert "{SCORE_COMPARISON_TABLE}" not in sent_system` and `assert _PLANNER_SCORE_TABLE_FALLBACK not in sent_system` — verifies substitution pipeline |
| `test_planner_prompt_contains_score_table_token` | Keep | `assert "{SCORE_COMPARISON_TABLE}" in PLANNER_PROMPT` — pins required token in live prompt |
| `test_planner_prompt_has_new_section_header` | Keep | `assert "### PER-FILE PERFORMANCE TABLE:" in PLANNER_PROMPT` — pins new section header |
| `test_planner_references_best_experiment_not_most_recent` | Keep | `assert "best experiment" in PLANNER_PROMPT` — pins user-locked design choice about anchor |
| `test_provider_agnostic` | Keep | `assert result == VALID_JSON_DICT` and `mock_create.assert_called_once()` for both "gemini" and "openai" — verifies single code path |
| `test_provider_is_lowercased` | Keep | `assert bridge.provider == "openai"` when `provider="OPENAI"` — verifies lowercase normalization |
| `test_raises_when_no_tool_call_returned` | Keep | `with pytest.raises(ValueError, match="did not return a tool call")` — verifies error when model returns text instead of tool call |
| `test_reflect_context_with_null_key_uses_reflector_fallback` | Keep | `assert _REFLECTOR_SCORE_TABLE_FALLBACK in sent_system` when `"score_comparison_table": None` in context — verifies explicit None treated as absent |
| `test_reflect_context_without_key_uses_reflector_fallback` | Keep | `assert _REFLECTOR_SCORE_TABLE_FALLBACK in sent_system` when context has `"baseline_score"` but no `"score_comparison_table"` key |
| `test_reflect_model_id_separates_planner_from_reflector` | Keep | `assert bridge.model_name == "planner-model"` and `assert bridge.reflect_model_name == "reflector-model"` — verifies split when reflect_model_id is set |
| `test_reflect_none_context_uses_reflector_fallback` | Keep | `assert _REFLECTOR_SCORE_TABLE_FALLBACK in sent_system` when `reflection_context=None` — verifies fallback |
| `test_reflect_provider_is_lowercased` | Keep | `assert bridge.reflect_provider == "gemini"` when `reflect_provider="GEMINI"` and `assert bridge.client is bridge.reflect_client` — verifies normalization and same-after-lowercase reuses client |
| `test_reflect_provider_only_no_model_override` | Keep | `assert bridge.reflect_model_name == "shared-model-name"` and `assert bridge.client is not bridge.reflect_client` — verifies provider-only split uses shared model name |
| `test_reflect_substitutes_from_context` | Keep | `assert _TABLE_MARKER in sent_system` and `assert "{SCORE_COMPARISON_TABLE}" not in sent_system` and `assert _REFLECTOR_SCORE_TABLE_FALLBACK not in sent_system` — verifies reflect() substitution |
| `test_reflect_uses_main_model_when_not_split` | Keep | `assert mock_create.call_args.kwargs["model"] == "single-model"` — backward-compat path |
| `test_reflect_uses_reflect_model_when_split` | Keep | `assert mock_create.call_args.kwargs["model"] == "reflector-model"` — verifies reflect() uses reflect model |
| `test_reflect_uses_reflector_system_prompt` | Keep | `assert self.REFLECT_PROMPT_FRAGMENT in messages[0]["content"]` — verifies REFLECTOR_PROMPT (not PLANNER_PROMPT) is used |
| `test_reflector_prompt_contains_score_table_token` | Keep | `assert "{SCORE_COMPARISON_TABLE}" in REFLECTOR_PROMPT` — pins required token in live reflector prompt |
| `test_reflector_prompt_has_new_section_header` | Keep | `assert "### PER-FILE COMPARISON" in REFLECTOR_PROMPT` — pins new section header in reflector |
| `test_returns_dict` | Keep | `assert result == VALID_JSON_DICT` — verifies JSON parsing returns dict from string response |
| `test_returns_none_when_body_not_dict` | Keep | `assert LLMBridge._parse_retry_delay(exc) is None` — tests non-dict body |
| `test_returns_none_when_delay_not_seconds_format` | Keep | `assert LLMBridge._parse_retry_delay(exc) is None` for `"1h30m"` format — verifies strict seconds-format matching |
| `test_returns_none_when_details_missing` | Keep | `assert LLMBridge._parse_retry_delay(exc) is None` — tests missing details key |
| `test_returns_none_when_no_retry_info` | Keep | `assert LLMBridge._parse_retry_delay(exc) is None` — tests missing RetryInfo entry in details |
| `test_returns_sorted_ids` | Keep | `assert result == ["model-a", "model-b"]` — verifies sort order of list_models() |
| `test_returns_str` | Keep | `assert isinstance(result, str)` and `assert result == PLAIN_TEXT` — verifies generate_text() returns string |
| `test_returns_tool_call_result` | Keep | `assert isinstance(result, ToolCallResult)` and `assert result.name == "search"` and `assert result.arguments == {"query": "dark matter"}` and `assert result.call_id == "call_001"` — verifies full ToolCallResult construction |
| `test_strips_whitespace` | Keep | `assert result == "hello"` when response is `"  hello  \n"` — verifies whitespace stripping behavior |
| `test_tool_call_result_is_frozen` | Keep | `with pytest.raises(AttributeError)` when `result.name = "y"` — verifies frozen dataclass immutability |
| `test_tools_passed_to_api` | Keep | `assert call_kwargs["tools"] == SAMPLE_TOOLS` and `assert call_kwargs["tool_choice"] == "auto"` — verifies tools and tool_choice passed correctly |
| `test_trailing_prose_after_valid_json_is_discarded` | Keep | `assert result == VALID_JSON_DICT` with payload containing trailing commentary — robustness contract |
| `test_two_calls_in_sequence_use_correct_models` | Keep | `assert first_model == "planner-model"` and `assert second_model == "reflector-model"` — end-to-end model routing test |
| `test_unknown_provider_no_model_id_is_none` | Keep | `assert bridge.model_name is None` — verifies default None for unknown provider without model_id |
| `test_unknown_provider_with_explicit_args` | Keep | `assert bridge.model_name == "my-model"` and `assert call_kwargs.kwargs["base_url"] == "https://example.com/v1"` — verifies explicit args flow through for unknown provider |
| `test_unknown_reflect_provider_raises` | Keep | `with pytest.raises(ValueError, match="Unknown reflect_provider")` — verifies fail-fast construction error |
| `test_uses_exponential_backoff_without_retry_delay` | Keep | `mock_sleep.assert_called_once_with(2.5)` — verifies backoff value when no retryDelay present |

### `tests/unit/agent/test_llm_bridge_singleton.py`

Tests: 2

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_llm_bridge_itself_still_constructs_openai` | Keep | `assert PATTERN.search(text)` on the bridge file content — sanity check that the singleton invariant is meaningful |
| `test_only_llm_bridge_constructs_openai_client` | Keep | Scans `agent/`, `nodes/`, `workflows/` with `re.compile(r"\bOpenAI\s*\(")` and `raise AssertionError` on hits — real filesystem scan enforcing architectural invariant, not a mock |

### `tests/unit/agent/test_prompt_banned_vocabulary.py`

Tests: 4

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_banned_vocabulary_absent` | Keep | `assert token not in prompt_text` for each of 11 banned tokens across 5 production prompt strings — regression guard against V9 cognitive alignment drift; no static analysis can check runtime string content |
| `test_impact_aware_framing_present` | Keep | `assert "Impact_Score" in prompt_text` and `assert "Linear_Weight" in prompt_text` and `assert "Log-of-Mean" in prompt_text` for interpretation prompts — pins three required framing tokens |
| `test_planner_prompt_per_file_table_uses_impact_columns` | Keep | `assert "Impact_Score" in PLANNER_PROMPT` and `assert "Linear_Weight" in PLANNER_PROMPT` — pins required column headers in planner prompt |
| `test_proposer_reasoning_uses_impact_score` | Keep | `assert "Impact_Score" in PROPOSAL_REASONING_PROMPT` — pins impact-aware framing in proposer |

### `tests/unit/agent/test_skill_spec.py`

Tests: 9

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_basic_creation` | Keep | `assert spec.name == "search"` and `assert spec.input_schema is DummyInput` and `assert spec.output_schema is DummyOutput` — baseline construction verification |
| `test_function_name_and_description` | Keep | `assert func["name"] == "search"` and `assert func["description"] == "Search the knowledge base."` — pins name/description threading |
| `test_output_schema_not_in_tool_definition` | Keep | `assert "output" not in tool["function"]` and `assert "results" not in tool["function"].get("parameters", {}).get("properties", {})` — verifies output schema does not leak |
| `test_parameters_contain_expected_fields` | Keep | `assert "query" in props` and `assert "max_results" in props` — verifies specific field names in generated schema |
| `test_parameters_match_input_schema` | Keep | `assert params == DummyInput.model_json_schema()` — verifies JSON schema is generated from the actual Pydantic class |
| `test_reflects_schema_changes` | Keep | `params = spec.to_openai_tool()["function"]["parameters"]` then `assert "x" in params["properties"]` — verifies generation uses live class, not a cached copy |
| `test_required_fields_present` | Keep | `assert "query" in required` — verifies field without default is marked required |
| `test_stores_class_not_instance` | Keep | `assert isinstance(spec.input_schema, type)` and `assert issubclass(spec.input_schema, BaseModel)` — pins that the class object (not an instance) is stored |
| `test_top_level_structure` | Keep | `assert tool["type"] == "function"` and `assert "function" in tool` — verifies OpenAI tool format top-level keys |

### `tests/unit/agent/training_skill/test_estimator.py`

Tests: 15

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_batch_size_scales_output_logits_linearly` | Keep | `assert b["breakdown"]["output_logits_bytes"] == 4 * a["breakdown"]["output_logits_bytes"]` — pins batch_size scaling |
| `test_epochs_scales_linearly` | Keep | `assert b["seconds"] == pytest.approx(3 * a["seconds"], rel=1e-6)` — pins epochs linear scaling |
| `test_fcnet_activations_use_1x_factor` | Keep | `assert fc["breakdown"]["activations_bytes"] * 2 == rnn["breakdown"]["activations_bytes"]` — pins the 1× vs 2× activation factor distinction between fcnet and RNN |
| `test_focal_loss_adds_onehot_bytes` | Keep | `assert focal["total_bytes"] > ce["total_bytes"]` and `assert ce["breakdown"]["focal_onehot_bytes"] == 0` — exercises CE vs focal loss path difference |
| `test_ms_per_step_passthrough_applies_gpu_calibration` | Keep | `assert out["breakdown"]["k_correction"] == pytest.approx(2.0)` after monkeypatching `calibration.lookup_k` — exercises GPU calibration path with real numeric check |
| `test_ms_per_step_passthrough_no_gpu` | Keep | `assert out["seconds"] == pytest.approx(1625.0, rel=1e-3)` and `assert out["breakdown"]["k_correction"] == 1.0` — exercises no-gpu passthrough path |
| `test_num_params_scales_model_overhead_linearly` | Keep | `assert b["breakdown"]["model_overhead_bytes"] == 2 * a["breakdown"]["model_overhead_bytes"]` — pins linear scaling invariant |
| `test_regression_against_wrapper_static_path` | Keep | `assert out["seconds"] == pytest.approx(1560.0, rel=1e-3)` and `assert out["breakdown"]["total_train_steps"] == 250_000` — locks K.2.5 lift-only invariant; hand-computed arithmetic pins exact numeric output |
| `test_return_shape` | Keep | Asserts dict shape of real `est.estimate_peak_bytes(...)` output (keys + total_bytes > 0 + breakdown keys) — pure logic, no mocks |
| `test_rnn_has_no_transformer_attn` | Keep | `assert out["breakdown"]["transformer_attn_bytes"] == 0` for model_type="rnn" — exercises model-type-conditional attention term |
| `test_seg_size_scales_output_logits_linearly` | Keep | `assert b["breakdown"]["output_logits_bytes"] == 4 * a["breakdown"]["output_logits_bytes"]` — pins seg_size linear scaling |
| `test_seg_size_scales_transformer_attn_quadratically` | Keep | `assert b["breakdown"]["transformer_attn_bytes"] == 4 * a["breakdown"]["transformer_attn_bytes"]` when seg doubles — pins quadratic attention scaling |
| `test_static_fallback_invokes_internal_count_params` | Keep | `assert calls == [("tinynet", "ce")]` and `assert out["seconds"] == pytest.approx(780.0, rel=1e-3)` — exercises static fallback with monkeypatch; pinned arithmetic |
| `test_train_portion_reduces_steps` | Keep | `assert half["seconds"] == pytest.approx(full["seconds"] / 2, rel=1e-3)` — pins train_portion halving effect |
| `test_transformer_has_attn_term` | Keep | `assert out["breakdown"]["transformer_attn_bytes"] > 0` for model_type="transformer" — exercises transformer attention computation |

### `tests/unit/agent/tune_ml_hyperparam_agent/test_build_gate_exhaustion.py`

Tests: 19

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_all_time_gated_returns_populated_info` | Keep | `assert info.baseline_time_factor == 1.5` (30/20) and `assert info.worst_time_factor == 2.25` (45/20) |
| `test_all_vram_gated_returns_populated_info` | Keep | `assert info.baseline_vram_factor == 1.6` (6.4/4.0) and `assert info.worst_vram_factor == 2.025` (8.1/4.0) — factor computation |
| `test_baseline_estimate_missing_uses_worst_only_phrasing` | Keep | `assert "baseline estimate not recorded" in msg` and `assert "1.50×" in msg` from `_render_gate_exhaustion_summary` |
| `test_burst_below_50pct_gate_skip_does_not_fire` | Keep | `assert _build_gate_exhaustion(...) is None` with 1 gate-skip + 2 schema-violations (33%) |
| `test_completed_rounds_zero_falls_through_to_trigger_a` | Keep | `assert "All 3 attempt" in info.summary_message` and `assert "Model too large" not in info.summary_message` |
| `test_consecutive_fails_below_threshold_does_not_fire` | Keep | `assert _build_gate_exhaustion(...) is None` with `consecutive_fail_rounds_at_exit=1 < max_fail_rounds=3` |
| `test_empty_records_returns_none` | Keep | `assert _build_gate_exhaustion(records=[], ...) is None` — empty trigger guard |
| `test_ever_trained_true_returns_none` | Keep | `assert _build_gate_exhaustion(records=[_vram_gated(), _success(), ...], ...) is None` — success short-circuit |
| `test_max_fail_rounds_zero_disables_trigger_b` | Keep | `assert _build_gate_exhaustion(...) is None` with success+vram-gated records when `max_fail_rounds` defaults to 0 |
| `test_mixed_gating_with_other_failures` | Keep | `assert info.baseline_vram_factor == 1.25` (5/4) and `assert info.worst_time_factor == 1.25` (25/20) |
| `test_mixed_summary_uses_multi_axis_verdict` | Keep | `assert "Both parameter count AND per-step compute" in info.summary_message` |
| `test_no_gate_skip_returns_none` | Keep | `assert _build_gate_exhaustion(records=[_schema_violation(), _error(), ...], ...) is None` — non-gate failures don't trigger |
| `test_summary_message_calls_out_time_axis` | Keep | `assert "time gate" in info.summary_message` and `assert "too slow" in info.summary_message` |
| `test_summary_message_calls_out_vram_axis` | Keep | `assert "VRAM gate" in info.summary_message` and `assert "too heavy" in info.summary_message` and `assert "Reduce parameter count" in info.summary_message` |
| `test_time_budget_none_yields_none_time_factors` | Keep | `assert info.baseline_time_factor is None` and `assert info.worst_time_factor is None` |
| `test_trigger_b_focuses_report_on_burst_records` | Keep | `assert info.baseline_vram_estimate_gb == 8.0` (burst first, not records[0]=1.0) and `assert info.worst_vram_factor == 3.0` (12.0/4.0) |
| `test_trigger_b_summary_uses_phase_l_framing` | Keep | `assert "Model too large" in msg` and `assert "3 consecutive rounds" in msg` and `assert "after 2 successful round(s)" in msg` |
| `test_trigger_b_with_mixed_burst_axis_says_vram_time` | Keep | `assert "VRAM/time gate" in info.summary_message` |
| `test_vram_budget_none_yields_none_vram_factors` | Keep | `assert info.baseline_vram_factor is None` and `assert info.worst_vram_factor is None` but `assert info.baseline_vram_estimate_gb == 6.0` |

### `tests/unit/agent/tune_ml_hyperparam_agent/test_constraint_aware_retry.py`

Tests: 10

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_all_records_saved_as_skipped_schema_violation` | Keep | `assert all(r["status"] == "skipped_schema_violation" for r in saved)` — verifies record-saving side effect via sandbox mock's side_effect capture |
| `test_does_not_raise_does_not_advance_rounds` | Keep | `output = agent.run(...)` then `assert output.status == "partial"` and `assert output.completed_rounds == 0` and `assert output.termination_reason == "aborted_fail_rounds"` — end-to-end tuner behavior |
| `test_ge_violation_returns_schema_violation` | Keep | `assert result["violations"][0]["type"] == "greater_than_equal"` |
| `test_greater_than_equal_loc_and_type` | Keep | `_MockMultOfCfg(channels=0)` raises, then asserts `ge` violation type and loc |
| `test_happy_path_unchanged` | Keep | Uses real `rnn` plugin with valid config and `assert result["status"] == "success"` — sanity check that new ValidationError branch doesn't intercept healthy configs |
| `test_model_validator_violation_loc_is_root` | Keep | `_MockMonotoneCfg(a=5, b=3, c=3)` raises ValidationError, then `assert v["loc"] == "__root__"` and `assert "nondecreasing" in v["msg"]` — real extractor logic on real Pydantic error |
| `test_model_validator_violation_returns_schema_violation` | Keep | `patch("...get_config_class", return_value=_MockMonotoneCfg)` then `result["status"] == "schema_violation"` and `"nondecreasing" in v["msg"]` — mock patches only config resolution, assertion is on real wrapper business logic |
| `test_multiple_of_loc_and_type_and_input` | Keep | `_MockMultOfCfg(channels=9)` raises, then `assert offending[0]["loc"] == "channels"` and `assert offending[0]["input"] == 9` |
| `test_multiple_of_violation_returns_schema_violation` | Keep | `assert v["type"] == "multiple_of"` and `assert v["loc"] == "channels"` — wrapper correctly classifies per-field violations |
| `test_record_memory_carries_violation_details` | Keep | `assert "__root__" in r["memory"]["conclusion"]` and `assert "nondecreasing" in r["memory"]["memory_update"]` and `assert "DO NOT" in ...` — specific memory content |

### `tests/unit/agent/tune_ml_hyperparam_agent/test_degeneracy_handling.py`

Tests: 6

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_degenerate_formal_with_float_penalty_uses_penalty` | Keep | `assert score_results["denoising_score"] == -2.5` — exercises policy: float penalty replaces score |
| `test_degenerate_formal_with_none_penalty_nulls_score` | Keep | `assert score_results["denoising_score"] is None` and `assert reason == "amplitude collapse: 0.0005% of reference"` — exercises policy: penalty_score=None → null score for formal round |
| `test_degenerate_trial_round_is_no_op` | Keep | `assert score_results["denoising_score"] == 0.5` despite `is_degenerate=True` on a trial round — exercises trial-round immunity policy |
| `test_missing_keys_default_to_false_none` | Keep | `assert is_degen is False` and `assert reason is None` and `assert score_results["denoising_score"] == 1.0` for score_results without is_degenerate key — exercises missing-key defensive default |
| `test_non_degenerate_formal_preserves_score` | Keep | `assert score_results["denoising_score"] == 5.45` — exercises pass-through for healthy formal rounds |
| `test_non_degenerate_trial_preserves_score` | Keep | `assert score_results["denoising_score"] == 0.42` — exercises pass-through for healthy trial rounds |

### `tests/unit/agent/tune_ml_hyperparam_agent/test_disallowed_patterns.py`

Tests: 15

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_empty_records_yields_empty` | Keep | `assert _collect_disallowed_patterns([], ...) == []` |
| `test_healthy_iteration_returns_none_and_no_patterns` | Keep | `assert info is None` for success records — backward compat |
| `test_iter2_style_9_scan_attempts_at_huge_factor_yields_scan_tag` | Keep | `assert out == ["scan_over_T"]` after 9 scan records at factor≈18,772× — real threshold logic |
| `test_iter3_style_9_gru_attempts_at_moderate_factor_yields_recurrent_tag` | Keep | `assert out == ["recurrent_over_T"]` for factor≈28× — moderate-factor threshold |
| `test_marginal_overshoot_populates_empty_patterns_but_still_fires_trigger` | Keep | `assert info is not None` and `assert info.disallowed_architectural_patterns == []` — exhaustion fires without ban |
| `test_marginal_overshoot_under_threshold_yields_no_tags` | Keep | `assert out == []` for factor=1.3× — below-threshold no-ban |
| `test_mixed_records_populate_sorted_union` | Keep | `assert info.disallowed_architectural_patterns == ["recurrent_over_T", "scan_over_T"]` |
| `test_mixed_scan_and_gru_records_yield_both_tags_sorted` | Keep | `assert out == ["recurrent_over_T", "scan_over_T"]` — sorted union |
| `test_non_gate_failures_never_contribute_tags` | Keep | `"status": "skipped_schema_violation"` and `"status": "error_runtime"` records then `assert out == []` |
| `test_none_budgets_yield_empty` | Keep | `assert out == []` when `time_budget_minutes=None` — can't compute factor |
| `test_successful_arch_is_never_banned` | Keep | `assert out == []` for gated_fourier_tcn — non-infeasible arch never banned |
| `test_threshold_exactly_at_boundary_is_not_banned` | Keep | `at_threshold_minutes = TIME_FACTOR_THRESHOLD * 20.0` then `assert out == []` — strict-greater-than boundary |
| `test_trigger_a_iter2_scan_records_produce_scan_tag_on_info` | Keep | `assert info.disallowed_architectural_patterns == ["scan_over_T"]` via `_build_gate_exhaustion` — end-to-end integration |
| `test_trigger_b_burst_of_scan_records_surfaces_scan_tag` | Keep | `assert info.disallowed_architectural_patterns == ["scan_over_T"]` after round 1 success + round 2 burst |
| `test_vram_factor_alone_can_trigger_ban` | Keep | `vram_estimate_gb=VRAM_FACTOR_THRESHOLD * 8.0 + 1.0` then `assert out == ["recurrent_over_T"]` — OR symmetry |

### `tests/unit/agent/tune_ml_hyperparam_agent/test_estimator_static_patch.py`

Tests: 6

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_min_ms_per_step_floor` | Keep | `assert _MIN_MS_PER_STEP == 2.0` — pins floor constant |
| `test_safety_multiplier_raised` | Keep | `assert SAFETY_MULTIPLIER == 1.3` — pins tuned constant after relaxation from 2.0 |
| `test_static_formula_5x_higher_than_old` | Keep | `assert _STATIC_MS_PER_FLOP / old_coeff == 5.0` — pins the 5x relationship between old and new coefficients |
| `test_static_formula_above_floor_uses_computed` | Keep | `computed = 1_000_000 * 2000 * 8 * 3e-9` and `assert computed > 2.0` and `assert ms == computed` — verifies formula above floor |
| `test_static_formula_applies_floor_for_tiny_model` | Keep | `ms = _static_ms_per_step(num_params=100, seg_size=100, batch_size=1)` then `assert ms == 2.0` — verifies floor is applied when computed value is far below floor |
| `test_static_ms_per_flop_raised` | Keep | `assert _STATIC_MS_PER_FLOP == 3e-9` — pins tuned constant; if someone reverts the Phase 6.8 patch, this fails |

### `tests/unit/agent/tune_ml_hyperparam_agent/test_evaluate_time_skill.py`

Tests: 30

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_defaults_are_3_warmup_7_timed` | Keep | `sig = inspect.signature(ts._measure_ms_per_step)` then `assert sig.parameters["n_warmup_batches"].default == 3` — pins function signature defaults; guards against regression to old 1+2 warmup |
| `test_empty_list_returns_none_and_aggregator_none` | Keep | `ms, bd = ts._aggregate_warmup_timings([], n_warmup_batches=3)` then `assert ms is None` and `assert bd["aggregator"] is None` — tests empty-input edge case of the pure aggregator function |
| `test_fast_fail_aggregator_surfaces_on_breakdown` | Keep | `assert bd["warmup_aggregator"] == "fast_fail"` and `assert bd["warmup_n_timed_batches"] == 0` — tests fast-fail breakdown propagation |
| `test_fast_fail_step0_above_threshold_returns_that_step_ms` | Keep | `ms, bd = ts._aggregate_warmup_timings([7000.0, 6000.0, 6000.0], ..., fast_fail_threshold_ms=5000.0)` then `assert ms == 7000.0` and `assert bd["aggregator"] == "fast_fail"` — tests fast-fail branch triggers on step-0 above threshold |
| `test_fast_fail_uses_default_threshold_constant` | Keep | `ms, bd = ts._aggregate_warmup_timings([ts._WARMUP_FAST_FAIL_MS + 1.0], ...)` then `assert ms == ts._WARMUP_FAST_FAIL_MS + 1.0` — pins that the default threshold comes from the module constant |
| `test_legacy_breakdown_keys_still_present` | Keep | `assert legacy_keys.issubset(set(result["breakdown"].keys()))` where `legacy_keys` includes `"source"`, `"gpu_name"` etc. — backward compatibility: new warmup_* keys must coexist with pre-K.2.5 keys |
| `test_median_aggregator_surfaces_on_breakdown` | Keep | `assert bd["warmup_aggregator"] == "median"` and `assert bd["warmup_n_warmup_batches"] == 3` — monkeypatches `_measure_ms_per_step`; asserts propagation of warmup breakdown fields to flat breakdown |
| `test_median_branch_discards_warmup_then_takes_median` | Keep | `ms, bd = ts._aggregate_warmup_timings([50.0, 40.0, 30.0, 10.0, 12.0, 14.0, 16.0], n_warmup_batches=3)` then `assert ms == pytest.approx(13.0)` and `assert bd["aggregator"] == "median"` — tests median aggregation with warmup discard |
| `test_median_is_robust_to_one_outlier_unlike_mean` | Keep | `ms, _bd = ts._aggregate_warmup_timings([0.0, *([10.0]*6 + [5000.0])], n_warmup_batches=1, fast_fail_threshold_ms=10000.0)` then `assert ms == pytest.approx(10.0)` — tests median robustness to outlier, also checks that the legacy mean would have been inflated (`legacy_mean > 7... |
| `test_no_data_dir_aggregator_is_none` | Keep | `assert bd["warmup_aggregator"] is None` and `assert bd["warmup_timings_ms"] == []` — tests that no-data-dir path sets aggregator to None |
| `test_no_timed_steps_returns_none` | Keep | `ms, bd = ts._aggregate_warmup_timings([10.0, 10.0, 10.0], n_warmup_batches=3)` then `assert ms is None` — tests that exactly-warmup-count inputs yield None |
| `test_registered_model_type_does_not_emit_warning` | Keep | `assert result["inference_batch_uncalibrated"] is False` and `assert "!!! [evaluate_time_skill]" not in captured.out` — regression: known model_types must not emit the uncalibrated warning |
| `test_return_annotation_is_tuple` | Keep | `sig = inspect.signature(ts._measure_ms_per_step)` then `assert "tuple" in str(ret).lower()` and `assert "dict" in str(ret).lower()` — pins return type annotation contract for callers |
| `test_run_skill_dominant_phase_is_training_for_typical_config` | Keep | `assert result["dominant_phase"] == "training"` — tests that training dominates for a typical 100k-param config |
| `test_run_skill_error_on_malformed_model_config` | Keep | `result = ts.run_skill(FakeSandbox(), **_base_kwargs(model_type="nonexistent_model"))` then `assert result["status"] == "error"` — tests error-handling path in `run_skill` wrapper |
| `test_run_skill_estimated_minutes_is_sum_of_phase_seconds` | Keep | `total_sec = sum(p["seconds"] for p in result["phase_breakdown"].values())` then `assert result["estimated_minutes"] == pytest.approx(total_sec / 60.0, rel=1e-3)` — tests arithmetic invariant of the sum aggregator |
| `test_run_skill_falls_back_to_static_when_warmup_returns_none` | Keep | `monkeypatch.setattr(ts, "_measure_ms_per_step", lambda **kw: (None, ...))` then `assert result["breakdown"]["source"] == "static_formula_phase_b"` — tests fallback path when warmup returns None |
| `test_run_skill_feasible_tiny_model` | Keep | `assert result["feasible"] is True` and `assert "FITS" in result["verdict"]` and `assert result["estimated_minutes"] < 120.0` — tests feasibility gate pass for small model |
| `test_run_skill_infeasible_large_model` | Keep | `assert result["feasible"] is False` and `assert "OVER BUDGET" in result["verdict"]` and `assert result["estimated_minutes"] > 60.0` — tests feasibility gate fail for large model |
| `test_run_skill_infeasible_suggestion_reflects_lever` | Keep | `assert "model depth/width" in result["suggestion"]` — tests that the lever-based suggestion string flows through from `_suggest_lever` into the result dict |
| `test_run_skill_phase_breakdown_contains_all_three_phases` | Keep | `assert set(result["phase_breakdown"].keys()) == {"training", "inference", "scoring"}` and checks each phase has `seconds >= 0.0` — tests three-phase aggregation structure |
| `test_run_skill_returns_contract_shape` | Keep | `assert set(result.keys()) == _EXPECTED_KEYS` and `assert set(result["breakdown"].keys()) >= {...}` — monkeypatches only `_count_params` (avoids torch); asserts real contract shape of `run_skill` output |
| `test_run_skill_safety_multiplier_surfaced_in_breakdown` | Keep | `assert result["breakdown"]["safety_multiplier"] == te.SAFETY_MULTIPLIER` and arithmetic check `train_minutes == pytest.approx(raw * train_bd["k_correction"] * te.SAFETY_MULTIPLIER, rel=1e-3)` — tests that the safety multiplier constant is applied and surfaced in breakdown |
| `test_run_skill_skips_warmup_without_data_dir` | Keep | `monkeypatch.setattr(ts, "_measure_ms_per_step", _should_not_be_called)` then `assert calls == []` — tests that warmup is never called when no data_dir given |
| `test_run_skill_uses_warmup_when_data_dir_and_measurement_available` | Keep | `monkeypatch.setattr(ts, "_measure_ms_per_step", lambda **kw: (3.5, ...))` then `assert result["breakdown"]["source"] == "real_dataset_warmup"` — monkeypatches warmup to avoid GPU; asserts warmup path is selected when data_dir provided |
| `test_suggest_lever_high_ms_per_step_recommends_shrinking_model` | Keep | `assert "model depth/width" in ts._suggest_lever(ms_per_step=80.0, seg_size=1000, batch_size=1)` — tests real branch logic in `_suggest_lever` with a specific input; no mocks |
| `test_suggest_lever_otherwise_recommends_raising_seg_size` | Keep | `assert "segmentation_size" in msg` — tests third branch of `_suggest_lever` |
| `test_suggest_lever_small_seg_bs1_recommends_raising_batch` | Keep | `assert "batch_size" in ts._suggest_lever(ms_per_step=2.0, seg_size=1000, batch_size=1)` — tests second branch of `_suggest_lever` |
| `test_unregistered_model_type_emits_warning_and_flags_breakdown` | Keep | `assert result["inference_batch_uncalibrated"] is True` and `assert "!!! [evaluate_time_skill]" in captured.out` — tests soft-fallback for unregistered model_type: no crash, warning emitted, flag set |
| `test_warmup_scales_inference_ms_by_ratio` | Keep | `assert inf_bd["ms_per_step"] == pytest.approx(measured * _INFERENCE_VS_TRAINING_RATIO, rel=1e-6)` — tests that warmup ms/step is multiplied by the ratio constant before passing to inference estimator |

### `tests/unit/agent/tune_ml_hyperparam_agent/test_force_formal_round.py`

Tests: 50

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_accepts_false` | Keep | `inp = _make_input(force_formal_round=False); assert inp.force_formal_round is False` — tests schema accepts False |
| `test_accepts_true_explicit` | Keep | `inp = _make_input(force_formal_round=True); assert inp.force_formal_round is True` — tests explicit True accepted |
| `test_alias_log_line_emitted` | Keep | `assert "[STRATEGY] formal_round_strategy=full_clone" in out; assert "(alias_of:inherit_best_trial)" in out` — audit log alias annotation |
| `test_all_strategies_uniform_signature` | Keep | `assert len(params) == 2` and smoke-call `handler(plan, winner)` then `assert isinstance(inherited, list)` — tests that all handlers have correct signature and return type |
| `test_best_trial_winner_excludes_formal_mode` | Keep | `assert winner["exp_id"] == "trial_low"` when formal record has higher score — tests filtering logic |
| `test_best_trial_winner_excludes_missing_time_mode` | Keep | `rec["memory"].pop("time_mode"); winner = _best_trial_winner([rec]); assert winner is None` — tests missing-field exclusion |
| `test_best_trial_winner_excludes_non_success` | Keep | `assert winner["exp_id"] == "good"` after records with error/skipped status are added — tests status filter |
| `test_best_trial_winner_picks_max_score` | Keep | `winner = _best_trial_winner(history); assert winner["exp_id"] == "r2"` — tests real max-score selection logic |
| `test_best_trial_winner_returns_none_on_empty` | Keep | `assert _best_trial_winner([]) is None` — edge case |
| `test_default_is_true` | Keep | `assert inp.force_formal_round is True` — tests schema default; no mocks |
| `test_does_not_touch_model_cfg` | Keep | `assert plan.model_cfg == {"untouched": True}` — hybrid_params must never clone model_cfg |
| `test_falls_back_to_planner_when_no_winner` | Keep | `assert plan.loss_cfg["loss_type"] == "focal_cw"; assert "WARNING" in out` — full_clone fallback |
| `test_force_formal_inheritance_resilient_to_missing_train_keys` | Keep | `assert plan.train_cfg["epochs"] == 5; assert plan.train_cfg["batch_size"] == 16` — tests that missing keys in winner don't crash; planner's values survive |
| `test_force_formal_inherits_full_winner_config` | Keep | `assert plan.loss_cfg["loss_type"] == "focal"` and `assert plan.model_cfg == winner_model` — tests all 5 fields inherited from winner |
| `test_force_formal_model_cfg_inheritance_isolated_from_winner` | Keep | `plan.model_cfg["kernel_size"] = 99; assert history[0]["params"]["model_config"]["kernel_size"] == 3` — tests defensive copy |
| `test_force_formal_off_honours_planner` | Keep | `_apply_mode_override_chain(..., force_formal_round=False); assert plan.is_trial is True` — tests the off-branch of override |
| `test_force_formal_on_forces_formal` | Keep | `_apply_mode_override_chain(plan, trial_allowed=True, is_formal_round=True, force_formal_round=True); assert plan.is_trial is False` — tests real override logic |
| `test_inherit_best_trial_behaves_as_full_clone` | Keep | `assert plan.loss_cfg["loss_type"] == "focal"; assert plan.train_cfg["batch_size"] == 8` — alias resolution test |
| `test_inheritance_default_memory_history_none` | Keep | `_apply_mode_override_chain(...) # memory_history omitted; assert plan.loss_cfg["loss_type"] == "focal_cw"` — tests None treated as empty history |
| `test_inheritance_logs_winner_identity` | Keep | `assert "[STRATEGY] formal_round_strategy=full_clone" in out; assert "winner='r2'" in out; assert "inherited=model_cfg,loss_cfg,lr,epochs,batch_size" in out` — tests audit log format |
| `test_inheritance_skipped_on_non_last_rounds` | Keep | `assert plan.loss_cfg["loss_type"] == "focal_cw"` — non-last round doesn't inherit |
| `test_inheritance_skipped_when_force_formal_off` | Keep | `assert plan.loss_cfg["loss_type"] == "focal_cw"; assert plan.train_cfg["lr"] == 1e-3` — planner choices preserved when force_formal off |
| `test_inherits_all_five_fields_from_winner` | Keep | `assert plan.model_cfg == winner_model; assert plan.train_cfg["batch_size"] == 8` — explicit per-§7.2 full_clone statement |
| `test_inherits_only_loss_cfg_and_lr` | Keep | `assert plan.loss_cfg["loss_type"] == "focal"; assert plan.model_cfg == {"kernel_size": 5, "num_blocks": 8}` — hybrid_params inherits only 2 fields, preserves model_cfg |
| `test_llm_propose_behaves_as_independent` | Keep | `assert plan.loss_cfg["loss_type"] == "focal_cw"; assert plan.model_cfg["kernel_size"] == 2` — alias resolution test |
| `test_log_lists_inherited_fields` | Keep | `assert "inherited=loss_cfg,lr" in out` — pins hybrid_params audit log format |
| `test_no_trial_winner_falls_back_to_planner_with_warning` | Keep | `assert "WARNING" in out; assert "no successful trial" in out.lower()` — tests fallback with capsys |
| `test_no_winner_no_warning` | Keep | `assert "WARNING" not in out; assert "[FORMAL OVERRIDE] strategy=independent" in out; assert "winner=none" in out` — independent no-warning + uniform audit line |
| `test_non_last_round_unaffected_by_flag` | Keep | `assert plan.is_trial is True, f"flag={flag} flipped a non-last round"` — tests that is_formal_round=False gate works correctly |
| `test_planner_already_formal_no_op` | Keep | `plan = _make_plan(is_trial=False); _apply_mode_override_chain(...); assert plan.is_trial is False` — no-op when already formal |
| `test_planner_choices_survive_verbatim` | Keep | `assert plan.loss_cfg["loss_type"] == "focal_cw"; assert plan.model_cfg["kernel_size"] == 2` — independent strategy preserves all planner choices |
| `test_prompt_non_last_round_unaffected_by_flag` | Keep | `assert "MANDATORY" not in prompt` and `assert "FINAL ROUND" not in prompt` — tests that flag doesn't leak into non-last round prompt |
| `test_prompt_says_mandatory_when_force_formal_on_last_round` | Keep | `assert "MANDATORY" in prompt` and `assert "You MUST set \`is_trial\`: false" in prompt` — tests real prompt template output from `get_planner_user_prompt` |
| `test_prompt_says_optional_when_force_formal_off_last_round` | Keep | `assert "OPTIONAL" in prompt` and `assert "MAY use trial mode" in prompt` — tests opposite branch of prompt |
| `test_prompt_trial_disabled_directs_formal` | Keep | `assert "MANDATORY" in prompt_t` and `assert "Trial mode is DISABLED" in prompt_f` — tests two different prompt branches |
| `test_registry_directly_exposes_handler_callables` | Keep | `assert _FORMAL_STRATEGY_REGISTRY["full_clone"] is _strategy_full_clone` — pins identity contract for each handler |
| `test_registry_has_three_canonical_strategies` | Keep | `assert set(_FORMAL_STRATEGY_REGISTRY.keys()) == {"full_clone", "hybrid_params", "independent"}` — pins registry invariant |
| `test_shim_canonical_full_clone_inherits_like_legacy` | Keep | `assert plan.loss_cfg["loss_type"] == "focal"; assert plan.model_cfg["kernel_size"] == 3` — regression guard: canonical name hits same code path |
| `test_shim_canonical_independent_skips_inheritance` | Keep | `assert plan.loss_cfg["loss_type"] == "focal_cw"; assert "alias_of" not in out` — canonical name without alias annotation |
| `test_shim_legacy_inherit_best_trial_still_works` | Keep | `assert plan.loss_cfg["loss_type"] == "focal"; assert plan.train_cfg["lr"] == 5e-5` — backward-compat regression guard |
| `test_strategy_accepts_canonical_full_clone` | Keep | `inp = _make_input(formal_round_strategy="full_clone"); assert inp.formal_round_strategy == "full_clone"` |
| `test_strategy_accepts_canonical_independent` | Keep | `assert inp.formal_round_strategy == "independent"` — canonical value accepted |
| `test_strategy_default_is_full_clone` | Keep | `assert inp.formal_round_strategy == "full_clone"` — pins schema default after rename |
| `test_strategy_hybrid_params_validates` | Keep | `inp = _make_input(formal_round_strategy="hybrid_params"); assert inp.formal_round_strategy == "hybrid_params"` — pins Phase 2 addition |
| `test_strategy_legacy_inherit_best_trial_aliases_to_full_clone` | Keep | `inp = _make_input(formal_round_strategy="inherit_best_trial"); assert inp.formal_round_strategy == "full_clone"` — tests alias canonicalization in schema validator |
| `test_strategy_legacy_llm_propose_aliases_to_independent` | Keep | `inp = _make_input(formal_round_strategy="llm_propose"); assert inp.formal_round_strategy == "independent"` — tests second alias |
| `test_strategy_llm_propose_keeps_planner_choices` | Keep | `assert plan.loss_cfg["loss_type"] == "focal_cw"; assert "[STRATEGY] formal_round_strategy=independent (alias_of:llm_propose)" in out` — tests independent strategy path and alias log |
| `test_strategy_llm_propose_no_warning_without_winner` | Keep | `assert "WARNING" not in out` — tests that independent strategy doesn't emit warning for missing winner |
| `test_strategy_rejects_unknown_value` | Keep | `try: _make_input(formal_round_strategy="freestyle") except pydantic.ValidationError: return` — tests schema rejects unknown values |
| `test_trial_disallowed_overrides_unconditionally` | Keep | `for flag in (True, False): for is_formal in (True, False): ... assert plan.is_trial is False` — tests that `trial_allowed=False` always wins |

### `tests/unit/agent/tune_ml_hyperparam_agent/test_formal_sample_set.py`

Tests: 6

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_formal_default_training_produces_20_file_snapshot` | Keep | `assert cfg["trial_strategy"] == "snapshot"` and `assert len(sample_set) == NUM_FILES == 20` and `assert len(segs) == expected_per_file` — regression guard for the formal-mode sample-set bug; exercises `_resolve_sample_set_cfg` and `build_sample_set` |
| `test_formal_eval_is_locked_to_full_snapshot` | Keep | `assert cfg["eval_strategy"] == "snapshot"` and `assert cfg["eval_portion"] == 1.0` and `assert len(segs) == SEGMENTS_PER_FILE == 200` — verifies eval lock ignoring planner's `"anchors"` choice |
| `test_formal_eval_lock_is_immovable_against_plan_overrides` | Keep | `assert cfg["eval_strategy"] == "snapshot"` and `assert cfg["eval_portion"] == 1.0` even when `plan = _make_plan(eval_strategy="anchors", eval_portion=0.01)` — strong regression guard |
| `test_formal_training_override_respected` | Keep | `assert cfg["trial_portion"] == 0.5` and `assert len(segs) == expected_per_file` where `expected_per_file = round(0.5 * SEGMENTS_PER_FILE)` — operator override propagates |
| `test_single_file_mode_defaults` | Keep | `assert cfg["trial_strategy"] == "snapshot"` and `assert cfg["eval_strategy"] == "snapshot"` and `assert cfg["eval_portion"] == 1.0` and `assert cfg["trial_portion"] == 0.03` — single-file mode contracts |
| `test_trial_mode_still_uses_planner_values` | Keep | `assert cfg["trial_strategy"] == "anchors"` and `assert set(sample_set.keys()) == {0, 10, 19}` — pins that trial mode is untouched |

### `tests/unit/agent/tune_ml_hyperparam_agent/test_hardware_context_init.py`

Tests: 3

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_manifest_round_trips_to_schema` | Keep | `ctx = load_manifest(tmp_path / "test_run_hardware.json")` then `assert isinstance(ctx, HardwareContext)` and `assert ctx.usable_cap_bytes == int(0.80 * ctx.total_memory_bytes)` — verifies writer/reader schema compatibility |
| `test_manifest_written_on_run` | Keep | `assert manifest_path.exists()` after `agent.run(agent_input)` — verifies that hardware manifest file is created at the expected path |
| `test_second_run_does_not_rewrite_manifest` | Keep | `assert second_mtime == first_mtime` — verifies immutability contract: get_or_create returns stored manifest without rewriting on second run |

### `tests/unit/agent/tune_ml_hyperparam_agent/test_hyperparam_schemas.py`

Tests: 80

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_accepts_populated_info_and_round_trips` | Keep | `assert out.gate_exhaustion.vram_gated_attempts == 9` and full JSON round-trip `assert reloaded.gate_exhaustion == out.gate_exhaustion` — nested GateExhaustionInfo in output |
| `test_active_mode_rejects_other_strings` | Keep | `with pytest.raises(ValidationError) as exc:` for `"snapshot"` active_mode and `assert "active_mode" in str(exc.value)` — Literal constraint |
| `test_all_records_validated_as_experiment_records` | Keep | `assert out.all_records[0].status == "success"` and `assert out.all_records[1].status == "skipped_oom_risk"` — validates nested list elements |
| `test_both_optional_by_default` | Keep | `assert out.best_score_table is None` and `assert out.formal_score_table is None` — both optional |
| `test_both_tables_independently_populated` | Keep | `assert out.best_score_table.aggregate.num_sampled_files == 5` and `assert out.formal_score_table.aggregate.num_sampled_files == 20` — independent tables |
| `test_budget_split_shapes` | Keep | `assert inp.trial_vram_budget_gb == expected_trial` and `assert inp.formal_vram_budget_gb == expected_formal` across four configurations — independent budget fields |
| `test_budgets_round_trip_through_json` | Keep | `reloaded = HyperparamTuningInput.model_validate_json(inp.model_dump_json())` then budget field assertions — JSON round-trip |
| `test_default_none_when_omitted` | Keep | `assert out.gate_exhaustion is None` — optional field default |
| `test_defaults` | Keep | `assert agent_input.attempts_per_round == 3` and `assert agent_input.attempts_per_formal_round == 5` and `assert agent_input.max_fail_rounds == 3` — Phase L defaults |
| `test_defaults_to_normal_mode` | Keep | `assert inp.is_trial is False` and `assert inp.trial_portion == 0.1` and `assert inp.trial_strategy == "snapshot"` — documented normal-mode defaults |
| `test_defaults_when_all_fields_omitted` | Keep | `assert plan.model_type == "fcnet"` and `assert plan.model_cfg == {}` — all-default plan |
| `test_defaults_when_not_provided` | Keep | `assert out.attempts_per_round == 3` and `assert out.termination_reason == "completed"` — pre-Phase-L output forward compat |
| `test_defaults_when_trial_fields_omitted` | Keep | `assert plan.is_trial is True` and `assert plan.trial_strategy == "snapshot"` and `assert plan.trial_portion == 0.02` — documented defaults |
| `test_disallowed_patterns_rejects_non_list` | Keep | `with pytest.raises(ValidationError) as exc:` for bare string `"recurrent_over_T"` and `assert "disallowed_architectural_patterns" in str(exc.value)` — common LLM mistake |
| `test_disallowed_patterns_round_trip_through_json` | Keep | `reloaded.disallowed_architectural_patterns == ["scan_over_T","dense_attention_over_T"]` and also default-empty round-trip — JSON persistence |
| `test_disallowed_patterns_shapes` | Keep | `assert info.disallowed_architectural_patterns == expected` for None and populated list — new Fix-1 field |
| `test_error_scoring_baseline` | Keep | `assert rec.status == "error_scoring"` and `assert "Scoring crashed" in rec.memory.conclusion` and `assert "RuntimeError" in rec.memory.discovery` — Fix 2a schema contract |
| `test_error_scoring_round_trips_through_json` | Keep | `reloaded = ExperimentRecord.model_validate(json.loads(as_json))` then `assert reloaded.status == "error_scoring"` — JSON persistence of error_scoring records |
| `test_error_status_accepted` | Keep | `assert rec.status == status` for four error statuses — each schema literal validated |
| `test_existing_record_round_trip_unchanged` | Keep | `assert rec.memory.time_estimate_minutes is None` etc — backward compat: pre-Phase-J records still validate |
| `test_existing_record_without_trial_fields` | Keep | `assert rec.is_trial is False` and many None field assertions — backward compat for pre-trial records |
| `test_explicit_values_preserved` | Keep | `assert mem.round_index == 2` and `assert mem.attempt_in_round == 5` — explicit values preserved |
| `test_field_rejections_raise` | Keep | `with pytest.raises(ValidationError) as exc:` and `assert named_in_error in str(exc.value)` for invalid provider, zero max_rounds, negative file_index — three business-rule rejections |
| `test_field_round_trips_through_json` | Keep | `reloaded = ExperimentMemory.model_validate_json(mem.model_dump_json())` then `assert reloaded.inference_batch_uncalibrated is True` — JSON round-trip |
| `test_field_shapes` | Keep | `assert mem.inference_batch_uncalibrated == expected` across three parametrized cases — inference_batch_uncalibrated field |
| `test_formal_plan` | Keep | `assert plan.is_trial is False` — `is_trial=False` validates |
| `test_full_populated_validates` | Keep | `assert info.total_attempts == 9` and many specific field assertions — full GateExhaustionInfo validation |
| `test_invalid_record_in_all_records_raises` | Keep | `valid_output_dict["all_records"] = [{"status": "bad_status", "exp_id": "x"}]` then `with pytest.raises(ValidationError)` — invalid nested record |
| `test_invalid_score_table_rejected` | Keep | `bad["rows"] = bad["rows"][:19]` then `with pytest.raises(ValidationError)` — 19 rows when schema requires 20 |
| `test_invalid_status_literal_still_rejected` | Keep | `r["status"] = "skipped_something_else"` then `with pytest.raises(ValidationError) as exc:` and `assert "status" in str(exc.value)` — Literal not opened too wide |
| `test_invalid_status_raises` | Keep | `valid_success_record["status"] = "running"` then `with pytest.raises(ValidationError) as exc:` and `assert "status" in str(exc.value)` — closed Literal |
| `test_invalid_status_rejected` | Keep | `with pytest.raises(ValidationError): ExperimentRecord.model_validate(self._make_error_record("error_storage"))` — fabricated status rejected |
| `test_invalid_terminal_state_rejected` | Keep | `with pytest.raises(ValidationError)` for invalid termination_reason and negative fail_rounds — Literal and ge=0 constraints |
| `test_missing_file_index_uses_default` | Keep | `del valid_success_record["file_index"]` then `assert record.file_index == ExperimentRecord.model_fields["file_index"].default` — optional field default |
| `test_missing_model_type_raises` | Keep | `del valid_input_dict["model_type"]` then `with pytest.raises(ValidationError) as exc:` and `assert "model_type" in str(exc.value)` — required field rejection |
| `test_missing_required_field_raises` | Keep | `del cursor[drop_path[-1]]` then `with pytest.raises(ValidationError) as exc:` and `assert named_in_error in str(exc.value)` — parametrized required field rejections |
| `test_mode_rejections` | Keep | `with pytest.raises(ValidationError, match=error_match)` for single_file without file_index, target with empty files, invalid mode — TrialConfig business rules |
| `test_model_dump_roundtrip` | Keep | `restored = TrialConfig.model_validate(dumped)` then `assert restored == cfg` and seed field assertions — serialization round-trip |
| `test_non_numeric_budget_rejected` | Keep | `with pytest.raises(ValidationError) as exc:` for `"not a number"` budget and `assert "trial_vram_budget_gb" in str(exc.value)` — type rejection |
| `test_oom_missing_file_index_uses_default` | Keep | `assert record.file_index == ExperimentRecord.model_fields["file_index"].default` — default for optional field |
| `test_oom_missing_memory_raises` | Keep | `rec = ExperimentRecord.model_validate(valid_oom_record)` after `del valid_oom_record["memory"]` then `assert rec.memory is None` — Optional memory is valid |
| `test_optional_for_backward_compat` | Keep | `assert mem.round_index is None` and `assert mem.attempt_in_round is None` — pre-Phase-L records still validate |
| `test_output_with_file_vector` | Keep | `assert out.best_file_vector[6] == 1.23` and `assert len(out.best_file_vector) == 20` — file vector field |
| `test_output_without_file_vector` | Keep | `assert out.best_file_vector is None` — optional output field |
| `test_overrides_accepted` | Keep | `assert agent_input.attempts_per_round == 2` and `assert agent_input.attempts_per_formal_round == 8` and `assert agent_input.max_fail_rounds == 4` — override propagation |
| `test_plan_rejections` | Keep | `with pytest.raises(ValidationError, match=error_match)` for four plan validation errors — business rule rejections |
| `test_populated_score_table_round_trips` | Keep | `assert record.score_table.aggregate.num_sampled_files == 20` and `assert len(record.score_table.rows) == 20` — score table round-trip |
| `test_record_with_target_strategy` | Keep | `assert rec.target_files == [0, 10, 19]` — target strategy in record |
| `test_record_with_trial_context` | Keep | `assert rec.is_trial is True` and `assert rec.trial_strategy == "snapshot"` and `assert rec.file_vector[6] == 0.85` — trial context fields |
| `test_reflect_field_shapes` | Keep | `assert inp.reflect_provider == expected_provider` and `assert inp.reflect_model_id == expected_model_id` across three parametrized configurations — reflect fields |
| `test_reflect_fields_round_trip_through_json` | Keep | `reloaded = HyperparamTuningInput.model_validate_json(inp.model_dump_json())` then `assert reloaded.reflect_provider == expected_provider` — JSON serialization round-trip |
| `test_reflect_provider_invalid_value_raises` | Keep | `with pytest.raises(ValidationError) as exc:` for `"anthropic"` and `assert "reflect_provider" in str(exc.value)` — constrained Literal |
| `test_required_fields_only_with_optionals_default_none` | Keep | `assert info.vram_budget_gb is None` and multiple other None assertions — optional defaults |
| `test_round_fields_round_trip_through_record` | Keep | `assert record.memory.round_index == 1` and `assert record.memory.attempt_in_round == 2` — round fields in ExperimentRecord |
| `test_round_trip_through_json` | Keep | `reloaded = GateExhaustionInfo.model_validate_json(info.model_dump_json())` then `assert reloaded == info` — full JSON round-trip |
| `test_single_score_table_populated` | Keep | `assert populated.aggregate.num_sampled_files == num_sampled` for best and formal tables — single table population |
| `test_storage_defaults_when_omitted` | Keep | `inp = HyperparamTuningInput(model_type="punet")` then `assert inp.storage.local.workspace == "./siderius_workspace"` — default storage path |
| `test_storage_invalid_backend_raises` | Keep | `with pytest.raises(ValidationError) as exc:` for `"redis"` backend and `assert "backend" in str(exc.value)` — closed Literal rejection |
| `test_storage_local_workspace_and_run_name` | Keep | `assert inp.storage.backend == "local"` and `assert inp.storage.local.workspace == "./workspace"` and `assert inp.storage.local.run_name == "v1"` — nested storage fields |
| `test_target_strategy_with_files` | Keep | `assert plan.target_files == [0, 10, 19]` — target strategy field |
| `test_terminal_state_shapes` | Keep | `assert out.termination_reason == expected_reason` and `assert out.consecutive_fail_rounds_at_exit == expected_fail_rounds` for two terminal states — terminal state validation |
| `test_time_field_shapes` | Keep | `assert mem.time_estimate_minutes == expected_estimate` across three parametrized configurations — time field defaults and values |
| `test_time_mode_rejects_other_strings` | Keep | `with pytest.raises(ValidationError) as exc:` for `"snapshot"` time_mode and `assert "time_mode" in str(exc.value)` — Literal constraint |
| `test_trial_field_rejections` | Keep | `with pytest.raises(ValidationError, match=error_match)` for invalid strategy, empty target_files, out-of-range portion — business rule rejections |
| `test_unknown_error_variant_still_rejected` | Keep | `bad["status"] = "error_storage"` then `with pytest.raises(ValidationError) as exc:` — sanity check Literal not opened too wide |
| `test_valid_advice_shapes` | Keep | `assert expected_check(inp)` with two parametrized advice shapes (plain str, structured ExpertAdvice) — validates both union branches |
| `test_valid_auto_model_type` | Keep | `assert inp.model_type == "auto"` — pins "auto" is an accepted Literal value |
| `test_valid_completed_output_baseline` | Keep | `assert out.status == "completed"` and `assert out.best_denoising_score == 1.23` and `assert len(out.all_records) == 1` — output schema baseline |
| `test_valid_full_plan` | Keep | `assert plan.model_type == "punet"` and `assert plan.is_trial is True` and `assert plan.train_validation_align is False` — full ExperimentPlan |
| `test_valid_mode_configurations` | Keep | `assert key_check(cfg)` across four TrialConfig mode configurations — exercises mode-specific cross-field validation |
| `test_valid_oom_record` | Keep | `assert rec.status == "skipped_oom_risk"` and `assert rec.timing is None` — OOM record shape |
| `test_valid_schema_violation_record` | Keep | `assert rec.status == "skipped_schema_violation"` and `assert "DO NOT repeat" in rec.memory.memory_update` — combined assertions on schema violation record |
| `test_valid_status_variants` | Keep | `assert out.status == expected_status` and `assert out.best_denoising_score == expected_best_score` for "partial" and "failed" — status variants |
| `test_valid_success_record_baseline` | Keep | `assert rec.status == "success"` and `assert rec.denoising_score == 1.23` and timing sub-fields — baseline success record validation |
| `test_valid_trial_configurations` | Keep | `assert key_check(inp)` across three parametrized trial configurations — valid trial field combinations |
| `test_vram_field_shapes` | Keep | `assert mem.vram_estimate_gb == expected_estimate` and `assert mem.vram_budget_gb == expected_budget` — VRAM memory fields |
| `test_vram_fields_independent_of_time_fields` | Keep | `assert mem.time_estimate_minutes is None` etc when only VRAM fields set — independence between VRAM and time gates |
| `test_with_defaults_rejections` | Keep | `with pytest.raises(error_type, match=error_match)` for multi-element list and non-dict — `with_defaults` error paths |
| `test_with_defaults_shapes` | Keep | `assert getattr(plan, expected_attr) == expected_value` across three `with_defaults()` shapes — tests fallback logic and single-list unwrapping |
| `test_zero_rejected_for_attempt_budget_field` | Keep | `valid_input_dict[field] = 0` then `with pytest.raises(ValidationError)` — ge=1 bound rejection for three budget fields |

### `tests/unit/agent/tune_ml_hyperparam_agent/test_inference_aggregator.py`

Tests: 20

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_aggregator_is_median_when_value_returned` | Keep | `assert bd["aggregator"] == "median"` when value is not None — pins aggregation method label |
| `test_aggregator_is_none_when_value_is_none` | Keep | `assert bd["aggregator"] is None` for empty input — exercises degenerate label |
| `test_all_zero_elapsed_returns_none` | Keep | `assert value is None` and `assert bd["aggregator"] is None` — exercises all-zero degenerate path |
| `test_breakdown_has_required_keys` | Keep | `for key in ("aggregator", "n_warmup_files", "n_timed_files", "warmup_fraction", "timings_ms"): assert key in bd` — pins breakdown schema |
| `test_breakdown_preserves_input_list_independence` | Keep | `bd["timings_ms"].append({"sentinel": True}); assert all("sentinel" not in r for r in rows)` — exercises immutability of input list |
| `test_empty_list_returns_none` | Keep | `assert value is None` and `assert bd["n_timed_files"] == 0` and `assert bd["timings_ms"] == []` — exercises empty-list degenerate path |
| `test_five_files_discards_one` | Keep | `assert value == pytest.approx(6.25)` and `assert bd["n_warmup_files"] == 1` — pins per-PSD median computation for n=5 with hand-computed expected value |
| `test_missing_elapsed_ms_treated_as_zero` | Keep | `assert value is None` when timed files lack `elapsed_ms` — exercises all-zero degenerate path via missing-key default |
| `test_missing_n_psd_segs_defaults_to_one` | Keep | `assert value == pytest.approx(40.0)` for rows without `n_psd_segs` key — exercises missing-key defensive default |
| `test_mixed_segment_counts_normalise_correctly` | Keep | `assert value == pytest.approx(10.0)` — pins per-PSD-segment normalisation: raw elapsed 20ms/2segs = 80ms/8segs both yield 10 ms/seg |
| `test_n_warmup_clamped_below_n_files` | Keep | `assert bd["n_warmup_files"] == 2` and `assert bd["n_timed_files"] == 1` with `warmup_fraction=0.99` — exercises `min(..., n_files-1)` clamp |
| `test_negative_elapsed_treated_as_degenerate` | Keep | `assert value is None` for rows with `elapsed_ms=-10.0` — exercises negative-elapsed guard |
| `test_single_file_returns_none` | Keep | `assert value is None` and `assert len(bd["timings_ms"]) == 1` — exercises single-file degenerate path (warmup would dominate) |
| `test_ten_files_discards_two` | Keep | `assert bd["n_warmup_files"] == 2` and `assert bd["n_timed_files"] == 8` — pins n=10 warmup formula |
| `test_twenty_files_discards_four` | Keep | `assert bd["n_warmup_files"] == 4` and `assert bd["n_timed_files"] == 16` — pins n=20 warmup formula |
| `test_two_files_discards_one` | Keep | `assert value == pytest.approx(50.0)` and `assert bd["n_warmup_files"] == 1` and `assert bd["n_timed_files"] == 1` — pins warmup math for n=2 |
| `test_variable_per_segment_cost_takes_median` | Keep | `assert value == pytest.approx(13.75)` — pins median robustness to outlier (1000ms file) with hand-computed expected value |
| `test_warmup_fraction_echoed_in_breakdown` | Keep | `assert bd["warmup_fraction"] == 0.30` — exercises round-trip of caller-supplied fraction |
| `test_zero_fraction_floors_at_one` | Keep | `assert bd["n_warmup_files"] == 1` with `warmup_fraction=0.0` — exercises `max(1, ...)` floor |
| `test_zero_n_psd_segs_treated_as_one` | Keep | `assert value == pytest.approx(40.0)` — exercises `max(n_psd_segs, 1)` floor for zero-divide guard |

### `tests/unit/agent/tune_ml_hyperparam_agent/test_inference_hint_path.py`

Tests: 20

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_breakdown_carries_required_keys` | Keep | `assert "slack_applied" in result["breakdown"]` and `assert "effective_budget_minutes" in result["breakdown"]` — required keys contract |
| `test_handles_missing_memory_dict` | Keep | `history = [{"status": "success", "memory": None}]` then `assert ... is None` — None-memory tolerance |
| `test_hint_negative_falls_through_to_fallback` | Keep | `inference_per_psd_seg_ms_hint=-5.0` then `assert result["breakdown"]["inference_ms_source"] != "trial_inference_warmup"` |
| `test_hint_present_sets_source_trial_inference_warmup` | Keep | `monkeypatch` replaces phase estimators; `assert result["breakdown"]["inference_ms_source"] == "trial_inference_warmup"` — real branch selection logic |
| `test_hint_value_matches_corrected_formula` | Keep | `capture["inference_ms_per_step"]` captured then `assert capture["inference_ms_per_step"] == pytest.approx(expected)` where `expected = hint * inf_batch / ml_per_psd` — regression guard for the §3.5 inversion bug |
| `test_hint_zero_falls_through_to_fallback` | Keep | `inference_per_psd_seg_ms_hint=0.0` then `assert result["breakdown"]["inference_ms_source"] == "static_formula"` — zero-is-no-hint guard |
| `test_measured_path_beyond_slack_is_infeasible` | Keep | Total=70 min (117%) then `assert result["feasible"] is False` — beyond slack window |
| `test_measured_path_under_budget_no_slack_note` | Keep | `assert "slack" not in result["verdict"].lower()` when total well under budget |
| `test_measured_path_within_slack_window_is_feasible` | Keep | Total=63 min, budget=60 then `assert result["feasible"] is True` and `assert result["breakdown"]["slack_applied"] is True` — 10% slack rule |
| `test_no_hint_no_warmup_lands_static_formula` | Keep | `assert result["breakdown"]["inference_ms_source"] == "static_formula"` — branch 3 |
| `test_no_hint_with_training_warmup_lands_x27_fallback` | Keep | `monkeypatch.setattr(ts, "_measure_ms_per_step", lambda **kwargs: (5.0, {...}))` then `assert ... == "training_warmup_x2.7_fallback"` — branch 2 |
| `test_oom_between_two_trials_does_not_displace_recent` | Keep | `[success(0.30), oom_killed, success(0.50)]` then `assert ... == pytest.approx(0.50)` — most-recent wins |
| `test_returns_most_recent_successful_trial` | Keep | `assert _latest_trial_inference_marginal(history) == pytest.approx(0.55)` — picks most recent |
| `test_returns_none_on_empty_history` | Keep | `assert _latest_trial_inference_marginal([]) is None` |
| `test_returns_none_when_no_qualifying_record` | Keep | `assert _latest_trial_inference_marginal(history) is None` for all-disqualified records |
| `test_skips_failed_records` | Keep | `assert _latest_trial_inference_marginal(history) == pytest.approx(0.42)` skipping oom_killed |
| `test_skips_formal_records` | Keep | `assert _latest_trial_inference_marginal(history) == pytest.approx(0.40)` skipping formal record |
| `test_skips_record_with_missing_time_mode` | Keep | Memory exists but time_mode key absent then `assert ... is None` — partial-write tolerance |
| `test_static_formula_path_strict_check` | Keep | `assert result["breakdown"]["slack_applied"] is False` and `assert result["feasible"] is False` at 63/60 without hint — strict path |
| `test_x27_fallback_path_strict_check` | Keep | Training-warmup path at 63/60 with `assert result["breakdown"]["slack_applied"] is False` — only measured path gets slack |

### `tests/unit/agent/tune_ml_hyperparam_agent/test_memory_history_truncation.py`

Tests: 8

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_10_records_gives_7_condensed_3_full` | Keep | `assert "params" not in rec` for condensed records and `assert result[i] is records[i]` for full records — pins exact condensed vs. full partitioning and key removal |
| `test_condensed_keys_are_exactly_specified` | Keep | `assert top_keys <= _CONDENSED_KEYS` and `assert set(rec["memory"].keys()) <= _CONDENSED_MEMORY_KEYS` — pins allowed key sets against module-level constants |
| `test_empty_list` | Keep | `assert _truncate_memory_history([], full_window=3) == []` — exercises empty-list edge case |
| `test_exact_window_returns_all_verbatim` | Keep | `for orig, out in zip(records, result, strict=True): assert out == orig` — exercises identity at window boundary |
| `test_fewer_than_window_returns_all_verbatim` | Keep | `assert result == records` for 2 records with `full_window=3` — exercises pass-through path |
| `test_json_size_reduction` | Keep | `assert truncated_size < full_size * 0.7` — pins minimum 30% size reduction; real token-budget regression test |
| `test_missing_memory_key_handled` | Keep | `assert "memory" not in rec` for condensed records without memory key — exercises missing-key defensive handling |
| `test_non_destructive_original_list_unchanged` | Keep | `assert records == original` after calling `_truncate_memory_history` — exercises immutability contract |

### `tests/unit/agent/tune_ml_hyperparam_agent/test_memory_probe.py`

Tests: 12

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_appends_row_when_workspace_given` | Keep | `assert trace_path.exists()` and `assert len(rows) == 1` — file created |
| `test_emits_mem_line_with_canonical_fields` | Keep | `assert "[MEM]" in out` and `assert "scope=workflow" in out` and `assert "iter=3" in out` with real `probe_memory` call |
| `test_end_then_post_gc_pair_writes_two_rows` | Keep | `assert [r["phase"] for r in rows] == ["end", "post_gc"]` — production sequence |
| `test_iter_can_be_string` | Keep | `assert "iter=seed" in capsys.readouterr().out` — any JSON-serialisable value |
| `test_missing_psutil_emits_sentinel_row` | Keep | `assert row["rss_gb"] is None` and `assert row.get("note") == "psutil_unavailable"` with patched `_PSUTIL_AVAILABLE=False` |
| `test_multiple_calls_append_not_overwrite` | Keep | `assert len(rows) == 4` and `assert [r["phase"] for r in rows] == ["start", "pre_score", "post_score", "end"]` |
| `test_no_workspace_does_not_create_file` | Keep | `assert not (tmp_path / TRACE_FILENAME).exists()` after `os.chdir(tmp_path)` |
| `test_ordered_probes_produce_monotonic_trace` | Keep | `assert iters == sorted(iters)` and per-iteration phase order check |
| `test_post_gc_round_trip` | Keep | `assert row["phase"] == "post_gc"` and `assert persisted["phase"] == "post_gc"` — new phase string accepted |
| `test_row_has_required_fields` | Keep | `assert key in row for key in ("scope", "iter", "phase", "rss_gb", "vms_gb", "timestamp")` and `assert persisted == row` |
| `test_rss_and_vms_are_numeric_when_psutil_available` | Keep | `assert row["vms_gb"] >= row["rss_gb"]` — physical invariant |
| `test_workspace_is_created_if_missing` | Keep | `assert (target / TRACE_FILENAME).exists()` with non-existent `target` dir |

### `tests/unit/agent/tune_ml_hyperparam_agent/test_per_round_attempt_budget.py`

Tests: 5

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_aborts_at_max_fail_rounds` | Keep | `assert output.total_attempts == 4` and `assert counter["i"] == 4` — tests that abort fires at `max_fail_rounds=2` and the remaining 3 round slots are not consumed |
| `test_formal_budget_asymmetry` | Keep | `assert output.total_attempts == 4` and `r2` has 3 records showing `[skipped, skipped, success]` — round 2 burning 3 attempts is impossible under `attempts_per_round=1`; proves formal budget asymmetry |
| `test_increments_then_resets` | Keep | `assert output.total_attempts == 4` and `assert output.termination_reason == "aborted_fail_rounds"` and `statuses.count("success") == 1` — the 4-attempt count is the only outcome consistent with both increment AND reset working correctly |
| `test_only_last_round_uses_formal_budget` | Keep | `assert output.total_attempts == 6` and `assert len(r3) == 4` and `assert [r["memory"]["attempt_in_round"] for r in r3] == [1, 2, 3, 4]` — round 3 burning 4 attempts is impossible under trial budget of 2; proves formal budget only activated on last round |
| `test_succeeds_within_budget` | Keep | `assert output.status == "completed"` and `assert output.total_attempts == 4` and `assert r1[0]["status"] == "skipped_oom_risk"` — tests inner-loop logic: 2 OOMs then success in round 1; asserts attempt-in-round tracking |

### `tests/unit/agent/tune_ml_hyperparam_agent/test_physical_rejection_capture.py`

Tests: 7

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_attempt_config_carries_model_type` | Keep | `assert rej.attempt_config.get("model_type") == "punet"` — tests that model_type is captured in the attempt_config snapshot |
| `test_feasible_run_yields_empty_rejection_buffer` | Keep | `assert output.physical_rejections == []` — tests that successful run produces no rejections |
| `test_missing_memory_killer_defaults_applied` | Keep | `assert rej.dominant_layer == ""` and `assert rej.binding_cap == "vram"` — tests degenerate path when `memory_killer` is absent |
| `test_non_round_bytes_rounded_to_four_decimals` | Keep | `assert abs(gb - 2.3283) < 1e-4` — pins rounding formula for non-round byte counts |
| `test_one_gb_exact` | Keep | `assert output.physical_rejections[0].dominant_layer_gb == 1.0` — pins GB conversion formula |
| `test_one_rejection_with_expected_killer_fields` | Keep | `assert rej.dominant_layer == "encoder.attention.block7.mha"` and `assert abs(rej.dominant_layer_gb - 13.4) < 1e-3` — tests that real tuner run loop correctly captures rejection fields from mocked skill payload; non-trivial wiring |
| `test_three_rejections_preserved_in_order` | Keep | `assert [r.dominant_layer for r in output.physical_rejections] == ["layer_A", "layer_B", "layer_C"]` — tests accumulation order across multiple rounds |

### `tests/unit/agent/tune_ml_hyperparam_agent/test_planner_fixed_params.py`

Tests: 8

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_empty_when_no_overrides_and_no_cap` | Keep | `assert _format_fixed_params_block(None, None) == ""` and `assert _format_fixed_params_block({}, None) == ""` — exercises empty-output paths |
| `test_only_max_epochs_renders_cap_only` | Keep | `assert "SYSTEM-FIXED PARAMETERS" in block` and `assert "epochs (cap)" in block` and `assert "trial_portion    =" not in block` — pins cap-only rendering without override lines |
| `test_partial_overrides_render_only_supplied_keys` | Keep | `assert "trial_portion    = 0.1" in block` and `assert "train_portion" not in block` — pins targeted rendering of only supplied keys |
| `test_planner_prompt_block_with_only_max_epochs` | Keep | `assert "SYSTEM-FIXED PARAMETERS" in prompt` and `assert "epochs (cap)     ≤ 1" in prompt` — exercises max_epochs-only integration into planner prompt |
| `test_planner_prompt_includes_block_when_overrides_set` | Keep | `assert prompt.index("SYSTEM-FIXED PARAMETERS") < prompt.index("Human Expert Advice")` — pins block ordering in assembled prompt |
| `test_planner_prompt_omits_block_when_no_overrides` | Keep | `assert "SYSTEM-FIXED PARAMETERS" not in prompt` — exercises absence of block in unforced prompt |
| `test_unknown_override_key_renders_generically` | Keep | `assert "some_new_field" in block` and `assert "abc" in block` — exercises generic fallback for unknown keys |
| `test_workflow_default_overrides_render_all_lines` | Keep | `assert "is_trial         = True" in block` and `assert "final round auto-flips to formal" in block` and `assert "phase-progression" in block` — pins full workflow override rendering with annotations |

### `tests/unit/agent/tune_ml_hyperparam_agent/test_planner_resource_budgets.py`

Tests: 13

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_blocks_absent_when_no_budgets_or_estimates` | Keep | `assert "[ACTIVE RESOURCE BUDGETS" not in prompt` and `assert "[RESOURCE GATE — RESOLVING OVER-BUDGET CONFIGS]" not in prompt` — verifies no regression for existing callers without resource args |
| `test_both_blocks_rendered_when_budgets_set` | Keep | `assert "[ACTIVE RESOURCE BUDGETS — round 2, mode=trial]" in prompt` and `assert "[RESOURCE GATE — RESOLVING OVER-BUDGET CONFIGS]" in prompt` and `assert prompt.index("[ACTIVE RESOURCE BUDGETS") < prompt.index("[RESOURCE GATE")` — verifies both blocks render and in correct order |
| `test_empty_when_all_args_explicit_none` | Keep | `assert out == ""` when all args are explicit None — verifies all-None still produces empty string |
| `test_empty_when_no_budgets_and_no_estimates` | Keep | `assert out == ""` when `_format_active_resource_budgets_block()` called with no args — verifies no-render when nothing to show |
| `test_formal_mode_picks_formal_budgets` | Keep | `assert "mode=formal" in out` and `assert "budget 24.00 GB" in out` and `assert "budget 4.00 GB" not in out` — verifies formal mode selects formal budget values, not trial |
| `test_gpu_memory_rules_section_removed` | Keep | `assert "GPU MEMORY RULES" not in PLANNER_PROMPT` — pins K.6 removal of abstract section from system prompt |
| `test_header_present` | Keep | `assert "[RESOURCE GATE — RESOLVING OVER-BUDGET CONFIGS]" in RESOURCE_GATE_GUIDANCE_BLOCK` — pins required header in static guidance block |
| `test_lever_decision_tree_phrases_present` | Keep | `assert "If both factors are <= 1: continue" in text` and `assert "Lowering batch_size reduces vram_factor" in text` and `assert "do NOT change segmentation_size" in text` — pins load-bearing decision-tree phrases |
| `test_rendered_before_instructions` | Keep | `assert prompt.index("[ACTIVE RESOURCE BUDGETS") < prompt.index("### INSTRUCTIONS")` and `assert prompt.index("[RESOURCE GATE") < prompt.index("### INSTRUCTIONS")` — verifies blocks appear before INSTRUCTIONS section |
| `test_round_1_no_prior_estimate_renders_budget_only` | Keep | `assert "(no prior estimate)" in out` and `assert "budget 4.00 GB" in out` and `assert "factor" not in out` and `assert "Current batch_size: (not yet set)" in out` — verifies no-prior-estimate edge case |
| `test_time_budget_none_renders_disabled_line_no_factor` | Keep | `assert "Time:  (no budget — gate disabled)" in out` and `assert "factor 0.50" in out` (VRAM axis still renders) — verifies disabled time axis |
| `test_trial_mode_full_render_matches_spec_example` | Keep | `assert "[ACTIVE RESOURCE BUDGETS — round 3, mode=trial]" in out` and `assert "factor 1.30" in out` and `assert "(over)" in out` and `assert "factor 0.42" in out` — verifies full §10.3 example rendering |
| `test_vram_budget_none_renders_disabled_line_no_factor` | Keep | `assert "VRAM:  (no budget — gate disabled)" in out` and `assert "factor 0.40" in out` (time axis still renders) — verifies disabled-axis handling |

### `tests/unit/agent/tune_ml_hyperparam_agent/test_plugin_source_excerpt.py`

Tests: 15

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_block_formatter_resolves_plugin_class` | Keep | `block = format_plugin_source_excerpt_block(plugin["config_class"]); assert "## PLUGIN CONFIG SCHEMA" in block; assert "@model_validator" in block` — formatter works on loaded plugin |
| `test_embeds_extracted_source` | Keep | `assert "check_monotone" in block; assert "nondecreasing" in block` — source embedded in block |
| `test_empty_when_source_unavailable` | Keep | `DynCfg = type("DynCfg2", (BaseModel,), {"__module__": __name__}); assert format_plugin_source_excerpt_block(DynCfg) == ""` — no empty heading |
| `test_excerpt_embedded_in_user_prompt_when_supplied` | Keep | `bridge.plan(memory_history=[], plugin_source_excerpt=block); assert "## PLUGIN CONFIG SCHEMA" in user_prompt; assert "check_monotone" in user_prompt; assert "nondecreasing" in user_prompt` — D.1 wiring: excerpt appears in assembled prompt |
| `test_excerpt_rendered_before_checklist` | Keep | `i_schema = user_prompt.find("## PLUGIN CONFIG SCHEMA"); i_checklist = user_prompt.find("sentinel_checklist_marker"); assert i_schema < i_checklist` — ordering: schema before checklist |
| `test_extractor_resolves_plugin_class` | Keep | `plugin = _load_plugin(str(plugin_path)); src = _extract_config_class_source(plugin["config_class"]); assert "class MonotoneTestCfg" in src; assert "@model_validator" in src; assert "nondecreasing" in src` — regression guard: sys.modules registration fix |
| `test_field_validator_decorator_present` | Keep | `src = _extract_config_class_source(_FieldValidatorCfg); assert "@field_validator" in src; assert "kernel_size must be odd" in src` |
| `test_graceful_on_dynamic_class` | Keep | `DynCfg = type("DynCfg", (BaseModel,), {"__module__": __name__}); assert _extract_config_class_source(DynCfg) == ""` — dynamic class has no source → graceful return |
| `test_heading_and_fence_present` | Keep | `block = format_plugin_source_excerpt_block(_MonotoneCfg); assert "## PLUGIN CONFIG SCHEMA" in block; assert "authoritative" in block; assert "```python" in block; assert block.rstrip().endswith("```")` — template structure |
| `test_model_validator_body_present` | Keep | `src = _extract_config_class_source(_MonotoneCfg); assert "class _MonotoneCfg" in src; assert "@model_validator" in src; assert "nondecreasing" in src` — the core D.1 contract: validator body is visible |
| `test_none_returns_empty` | Keep | `assert _extract_config_class_source(None) == ""` — guard for None input |
| `test_per_field_only_class_still_returns_source` | Keep | `src = _extract_config_class_source(_PerFieldOnlyCfg); assert "class _PerFieldOnlyCfg" in src; assert "multiple_of=8" in src` — no validators → still returns source |
| `test_real_builtin_config_class` | Keep | `src = _extract_config_class_source(PUNetConfig); assert "class PUNetConfig" in src; assert "@model_validator" in src or "@field_validator" in src` — regression guard on production class |
| `test_section_omitted_when_excerpt_empty` | Keep | `bridge.plan(memory_history=[], plugin_source_excerpt=""); assert "## PLUGIN CONFIG SCHEMA" not in captured["user_prompt"]` — empty excerpt → section suppressed |
| `test_truncates_when_over_limit` | Keep | `prompts_mod.inspect.getsource = lambda _cls: "x = 1\n" * 3000; src = _extract_config_class_source(_MonotoneCfg); assert src.endswith("... (truncated)"); assert len(src) <= _PLUGIN_SOURCE_EXCERPT_MAX_CHARS + len("\n... (truncated)")` — truncation path |

### `tests/unit/agent/tune_ml_hyperparam_agent/test_seed_plugin_validation.py`

Tests: 9

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_directory_path_raises` | Keep | `base_input_dict["seed_plugin_path"] = str(tmp_path); with pytest.raises(ValidationError, match="does not exist or is not a file")` — directory rejected |
| `test_missing_file_raises` | Keep | `base_input_dict["seed_plugin_path"] = str(tmp_path / "does_not_exist.py"); with pytest.raises(ValidationError, match="does not exist")` — missing file rejected |
| `test_missing_plugin_model_type_raises` | Keep | plugin has no PLUGIN_MODEL_TYPE → `with pytest.raises(ValidationError, match="does not declare a top-level")` |
| `test_model_type_mismatch_raises` | Keep | plugin declares `PLUGIN_MODEL_TYPE = "some_other_type"` while input has `model_type="attn_fcnet"` → `with pytest.raises(ValidationError, match="PLUGIN_MODEL_TYPE")` — type mismatch |
| `test_none_is_ok` | Keep | `agent_input = HyperparamTuningInput.model_validate(base_input_dict); assert agent_input.seed_plugin_path is None` — no seed_plugin_path → valid |
| `test_plugin_model_type_non_string_raises` | Keep | `PLUGIN_MODEL_TYPE = 42` → `with pytest.raises(ValidationError, match="does not declare a top-level")` — int not accepted |
| `test_syntax_error_raises` | Keep | malformed Python → `with pytest.raises(ValidationError, match="not valid Python")` |
| `test_valid_plugin_passes` | Keep | `path = _write_plugin(tmp_path, "attn_fcnet_plugin.py", _VALID_PLUGIN_BODY); base_input_dict["seed_plugin_path"] = path; agent_input = HyperparamTuningInput.model_validate(base_input_dict); assert agent_input.seed_plugin_path == path` — valid file passes |
| `test_validator_does_not_import_the_plugin` | Keep | after `HyperparamTuningInput.model_validate(base_input_dict)`, checks `for key in sys.modules: assert not key.endswith(stem)` — AST-only validation contract: no side-effect import |

### `tests/unit/agent/tune_ml_hyperparam_agent/test_silent_train_crash_routing.py`

Tests: 4

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_cuda_oom_routes_to_error_inference_oom_not_training` | Keep | `assert rec["status"] == "error_inference_oom"` for `CUDA_OOM_INFERENCE_ERROR` — OOM disambiguation not over-matched |
| `test_inference_error_with_training_prefix_routes_to_error_training` | Keep | `error_records = [r for r in saved if r.get("status", "").startswith("error_")]; assert rec["status"] == "error_training"` when inference returns `SILENT_CRASH_INFERENCE_ERROR` containing `"error_training:"` — routing logic uses substring detection |
| `test_plain_inference_error_routes_to_error_inference` | Keep | `assert error_records[0]["status"] == "error_inference"` for `PLAIN_INFERENCE_ERROR` without `error_training:` — negative control |
| `test_silent_crash_record_carries_actionable_memory` | Keep | `assert "silently" in mem["conclusion"].lower(); assert "fix the inference" not in mem["memory_update"].lower()` — memory text points at trainer, not inference |

### `tests/unit/agent/tune_ml_hyperparam_agent/test_time_calibration.py`

Tests: 29

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_calibration_dir_default` | Keep | `assert cal.calibration_dir() == expected` where expected uses `os.path.expanduser("~")` and `cal._DEFAULT_SUBDIR` — pure path computation |
| `test_calibration_dir_env_override` | Keep | `monkeypatch.setenv(cal._ENV_VAR, str(tmp_path))` then `assert cal.calibration_dir() == str(tmp_path)` — env var override |
| `test_calibration_path_uses_slugged_filename` | Keep | `assert p.endswith("time_calibration_nvidia_rtx_5090.json")` — path computation |
| `test_detect_drift_only_inspects_last_n_entries` | Keep | `assert cal.detect_drift(table, last_n=3) is None` with 3 old violations followed by 1 clean entry — sliding window |
| `test_detect_drift_returns_none_when_history_short` | Keep | `assert cal.detect_drift(table, last_n=3) is None` with only 2 history entries — short history edge case |
| `test_detect_drift_returns_none_when_not_all_violated` | Keep | `assert cal.detect_drift(table, last_n=3) is None` with mixed violations — not all violated |
| `test_detect_drift_warns_on_n_consecutive_violations` | Keep | `assert msg is not None` and `assert "RTX 5090" in msg` and `assert "drift" in msg.lower()` — drift detection |
| `test_gpu_slug_is_deterministic` | Keep | `assert cal.gpu_slug(name) == cal.gpu_slug(name)` — pure function pin |
| `test_gpu_slug_lowercase_and_safe` | Keep | `assert cal.gpu_slug("NVIDIA GeForce RTX 5090") == "nvidia_geforce_rtx_5090"` and fallback `assert cal.gpu_slug("???") == "unknown_gpu"` — slug determinism with pathological inputs |
| `test_load_table_defensive_against_corrupt_json` | Keep | writes `"{not: valid json"` then `assert table["k_values"] == {}` — defensive against corrupt JSON |
| `test_load_table_fills_missing_keys` | Keep | writes JSON without `k_values`/`history` then `assert table["k_values"] == {}` — backwards-compat key fill |
| `test_load_table_returns_empty_when_missing` | Keep | `assert table == {"gpu_name": "RTX 5090", "k_values": {}, "history": []}` — defensive default structure |
| `test_lookup_k_exact_match_wins` | Keep | `assert cal.lookup_k(table, "wavenet") == 1.5` — exact match over wildcard |
| `test_lookup_k_falls_back_to_wildcard` | Keep | `assert cal.lookup_k(table, "punet") == 1.1` — wildcard fallback |
| `test_lookup_k_handles_missing_k_values_key` | Keep | `assert cal.lookup_k({}, "anything") == 1.0` — missing key defensive |
| `test_lookup_k_returns_one_when_neither_present` | Keep | `assert cal.lookup_k(table, "anything") == 1.0` — final fallback to 1.0 |
| `test_make_entry_estimate_not_violated_when_under_budget` | Keep | `assert e["estimate_violated"] is False` and `assert e["ratio"] == pytest.approx(0.5)` — under-budget path |
| `test_make_entry_handles_zero_warmup_safely` | Keep | `assert e["ratio"] == pytest.approx(1.0)` when warmup_ms_per_step=0.0 — div-by-zero guard |
| `test_make_entry_shape_and_ratio` | Keep | `assert e["ratio"] == pytest.approx(1.5)` and `assert e["estimate_violated"] is True` and timestamp ends with `"Z"` — entry shape and arithmetic |
| `test_save_is_atomic_no_tmp_left_behind` | Keep | `assert files == ["time_calibration_rtx_5090.json"]` — atomic write: no temp file left behind |
| `test_save_then_load_round_trip` | Keep | `assert loaded["k_values"] == {"wavenet": 1.42, "*": 1.10}` and `assert loaded["history"] == [{"foo": "bar"}]` — save/load round-trip |
| `test_update_k_appends_to_history` | Keep | `assert len(table["history"]) == 2` after two updates — history append |
| `test_update_k_asymmetry_corrects_under_prediction_faster` | Keep | `assert delta_up > delta_dn, "α_up must dominate α_down for safety"` — asymmetry safety property |
| `test_update_k_clips_to_kmax` | Keep | `assert table["k_values"]["m"] == cal.K_MAX` — upper clipping |
| `test_update_k_clips_to_kmin` | Keep | `assert table["k_values"]["m"] == cal.K_MIN` after 20 applications — lower clipping |
| `test_update_k_falls_back_to_wildcard_when_model_unseen` | Keep | `assert table["k_values"]["m"] == pytest.approx(1.7)` — wildcard-seeded EMA |
| `test_update_k_starts_from_one_when_no_prior` | Keep | `assert table["k_values"]["m"] == pytest.approx(1.5)` — k_old fallback to 1.0 |
| `test_update_k_uses_alpha_down_when_not_violated` | Keep | `assert table["k_values"]["m"] == pytest.approx(0.95)` — EMA with alpha_down=0.1 |
| `test_update_k_uses_alpha_up_when_violated` | Keep | `assert table["k_values"]["m"] == pytest.approx(1.5)` — EMA with alpha_up=0.5 |

### `tests/unit/agent/tune_ml_hyperparam_agent/test_tuning_agent.py`

Tests: 66

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_all_records_included` | Keep | `assert output.completed_rounds == 2` and `assert len(output.all_records) == 2` — tests that all records from 2 rounds are included in output |
| `test_best_and_formal_score_tables_in_output` | Keep | `assert output.best_score_table is not None` and `assert output.formal_score_table is not None` — tests dual-track table selection in HyperparamTuningOutput |
| `test_best_config_present` | Keep | `assert output.best_config is not None` and `assert output.best_config["model_type"] == "punet"` — tests best config is populated from the plan response |
| `test_best_score_extracted` | Keep | `assert output.best_denoising_score == 1.75` — tests that the best score is extracted from the FAKE_SCORE_RESULT (1.75); asserts real extraction logic |
| `test_build_score_table_failure_is_fault_tolerant` | Keep | `with patch("nodes.ml_hyperparameter_tune_agent.build_score_table", side_effect=_boom): output = agent.run(...)` then `assert output.status == "completed"` and `assert saved_records[0]["score_table"] is None` — tests that rendering failure does not crash the tuner |
| `test_completed_status` | Keep | `assert output.status == "completed"` and `assert output.completed_rounds == 1` — tests that a successful run sets completed status and round count |
| `test_copy_overwrites_existing_destination` | Keep | `assert f.read() == "FRESH\n"` — tests that stale copy is overwritten by newer source |
| `test_copy_places_file_in_dst_dir` | Keep | `assert os.path.isfile(result)` and `assert os.path.dirname(result) == str(dst_dir)` — tests real file-system operation of `_copy_seed_plugin`; no mocks |
| `test_copy_preserves_contents` | Keep | `assert f.read() == payload` — tests file contents are preserved in destination |
| `test_copy_same_file_is_noop` | Keep | `assert result == os.path.join(str(run_dir), "seed.py")` — tests that same-source-and-dest does not raise `SameFileError` |
| `test_empty_expert_advice` | Keep | `assert result == ""` — tests empty ExpertAdvice produces empty string |
| `test_empty_string_passthrough` | Keep | `assert _serialize_expert_advice("") == ""` — edge case: empty string must pass through unchanged |
| `test_error_status_does_not_skip_silently` | Keep | `assert output.completed_rounds == 0` and `assert not saved_records` — tests that skill status=error propagates as error (not treated as feasible) |
| `test_evaluate_vram_skill_receives_hardware_context` | Keep | `assert "hardware_context" in params` and `assert isinstance(params["hardware_context"], HardwareContext)` — A.11 wiring: verifies hardware_context is passed to every evaluate_vram_skill call |
| `test_feasible_proceeds_to_training` | Keep | `assert output.status == "completed"` and `assert "training_skill" in called_skills` and `assert saved_records[0]["status"] == "success"` — tests that time-gate FITS verdict allows training to proceed |
| `test_final_round_always_formal` | Keep | `assert saved_records[0].get("is_trial", False) is False` — tests that last round is forced formal even when LLM returns is_trial=True |
| `test_formal_mode_round_picks_formal_budget` | Keep | `assert time_calls[0]["time_budget_minutes"] == 240.0` — tests formal round gets formal_budget |
| `test_formal_mode_round_picks_formal_vram_budget` | Keep | `assert vram_calls[0]["vram_budget_gb"] == 24.0` — tests formal round gets formal_vram_budget |
| `test_formal_round_builds_two_sample_sets` | Keep | `assert len(build_calls) == 2` and `assert 1.0 in portions` and `assert train_calls[0][1].get("train_portion") == 1.0` — tests formal round builds two separate sample sets (train + eval) with correct portions |
| `test_formal_round_with_only_trial_budget_skips_gate` | Keep | `assert "evaluate_time_skill" not in called_skills` and `assert "training_skill" in called_skills` — tests that formal round skips gate when only trial_budget is set |
| `test_full_expert_advice` | Keep | `assert "Focus areas: depth; width" in result` and `assert "Constraints: VRAM < 8 GB" in result` — tests real serialization logic of ExpertAdvice to string |
| `test_infeasible_emits_skipped_record` | Keep | `assert all(r["status"] == "skipped_time_risk" for r in saved_records)` and `assert not any(s == "training_skill" for s, _ in skill_calls)` — tests that time-gate OVER BUDGET blocks training and emits skipped_time_risk records |
| `test_inference_receives_eval_sample_set` | Keep | `assert "eval_sample_set" in inf_params` — tests wiring: inference skill must receive eval_sample_set not train sample_set |
| `test_inference_skill_receives_inference_batch_from_resource_check` | Keep | `assert inference_calls[0].get("inference_batch") == 7` and `assert success_records[0]["params"].get("inference_batch") == 7` — tests that VRAM resource_check's inference_batch flows into inference_skill call and saved record params |
| `test_invalid_trial_fields_fallback` | Keep | `assert output.status == "completed"` — tests that invalid trial_portion=5.0 causes fallback without crash |
| `test_legacy_inference_result_writes_safe_defaults` | Keep | `assert mem["inference_per_psd_seg_ms_measured"] is None` and `assert mem["inference_n_timed_files"] == 0` — tests backward compatibility: legacy inference result (no timings) produces safe default keys |
| `test_model_type_in_output` | Keep | `assert output.model_type == "fcnet"` — tests that model_type from input appears in output |
| `test_none_budget_passes_none_to_skill` | Keep | `assert vram_calls[0]["vram_budget_gb"] is None` — tests that None VRAM budget passes None to skill (defensive floor still runs inside skill) |
| `test_none_budget_skips_skill_entirely` | Keep | `assert "evaluate_time_skill" not in called_skills` and `assert "training_skill" in called_skills` — tests that None budget means evaluate_time_skill is never called but training proceeds |
| `test_oom_record_has_expert_advice` | Keep | `assert saved_records[0]["memory"]["expert_advice_followed"] == "test advice"` — tests that expert advice is threaded through to OOM records |
| `test_oom_records_saved` | Keep | `assert len(saved_records) == 3` and `assert all(r["status"] == "skipped_oom_risk" for r in saved_records)` — tests that OOM records are saved with correct status |
| `test_output_file_written` | Keep | `assert output_path.exists()` and `assert data["status"] == "completed"` — tests file-system side effect: output JSON is written and contains the correct status |
| `test_output_validates_against_schema` | Keep | `HyperparamTuningOutput.model_validate(output.model_dump())` — re-validates output against schema; catches any field that passes construction but fails round-trip |
| `test_partial_expert_advice` | Keep | `assert "Focus areas: learning rate" in result` and `assert "Constraints" not in result` — tests that empty fields are omitted from serialization |
| `test_partial_status_on_all_oom` | Keep | `assert output.status == "partial"` and `assert output.completed_rounds == 0` — tests that all-OOM leads to partial status with 0 completed rounds |
| `test_populated_timings_aggregate_into_memory` | Keep | `assert mem["inference_per_psd_seg_ms_measured"] == pytest.approx(10.0)` and `assert mem["inference_warmup_aggregator"] == "median"` and `assert mem["inference_n_timed_files"] == 4` — tests that rich inference timing results are aggregated into memory keys correctly |
| `test_reflection_context_includes_markdown` | Keep | `assert "score_comparison_table" in context` and `assert isinstance(md, str) and md.startswith("### Per-file performance")` — tests that brain.reflect() receives score_table markdown in its context argument |
| `test_returns_valid_output` | Keep | `assert isinstance(output, HyperparamTuningOutput)` — end-to-end agent run returns the correct output type |
| `test_round_context_passed_to_plan` | Keep | `assert call_kwargs.kwargs.get("current_round") is not None` and `assert call_kwargs.kwargs.get("trial_allowed") is True` — tests that round context (current_round, max_rounds, trial_allowed) is passed to brain.plan() |
| `test_run_config_file_written` | Keep | `assert config_path.exists()` and `assert data["force_model"] == "punet"` and `assert data["max_rounds"] == 1` — tests run config file is written with correct content |
| `test_run_name_in_output` | Keep | `assert output.run_name == "test_run"` — tests run_name is propagated to output |
| `test_score_table_attached_to_record` | Keep | `assert rec["score_table"] is not None` and `assert len(rec["score_table"]["rows"]) == 20` and `assert rec["score_table"]["aggregate"]["model_scalar"] == pytest.approx(2.5)` — tests score_table is built and attached to record with correct structure |
| `test_score_table_md_picks_highest_scoring_record` | Keep | `assert threaded == "### HIGH-TABLE"` — seeded two records (HIGH score=9.99, LOW score=0.01); tests that highest-scoring record's markdown is selected |
| `test_score_table_md_threaded_to_brain_plan` | Keep | `assert first_kwargs.get("score_table_md") is None` and `assert second_kwargs["score_table_md"] == saved_records[0]["score_table"]["rendered_markdown"]` — tests that prior best record's markdown is threaded to round-2 planner call |
| `test_score_table_none_on_legacy_path` | Keep | `assert saved[0]["score_table"] is None` — tests that formal-only (no anchor_map) path produces None score_table |
| `test_skill_receives_budget_and_data_dir` | Keep | `assert time_calls[0]["time_budget_minutes"] == 45.0` and `assert time_calls[0]["data_dir"] == "/mnt/tidmad"` — tests that budget and data_dir kwargs are forwarded to evaluate_time_skill |
| `test_skipped_oom_risk_record_carries_vram_fields` | Keep | `assert mem["vram_estimate_gb"] == 12.0` and `assert mem["vram_budget_gb"] == 8.0` — tests that skipped_oom_risk records carry VRAM fields from the resource check |
| `test_skipped_oom_risk_record_omits_vram_fields_when_disabled` | Keep | `assert "vram_estimate_gb" not in mem` and `assert "vram_budget_gb" not in mem` — tests absence when no VRAM budget set even if OOM was triggered |
| `test_skipped_record_carries_suggestion` | Keep | `assert rec["memory"]["memory_update"] == "Reduce model depth/width."` and `assert "OVER BUDGET" in rec["memory"]["discovery"]` — tests that skipped_time_risk record carries the suggestion and discovery from the skill result |
| `test_skipped_time_risk_record_carries_time_fields` | Keep | `assert mem["time_estimate_minutes"] == 90.0` and `assert mem["time_mode"] == "formal"` — Phase J §J.3: skipped record carries same time fields as success record |
| `test_string_expert_advice_passed_to_plan` | Keep | `mock_brain.plan.assert_called_once()` then `assert kwargs["expert_advice"] == "focus on depth"` — asserts real wiring: the string expert advice from input is forwarded verbatim to `brain.plan()` |
| `test_string_passthrough` | Keep | `assert _serialize_expert_advice("try deeper models") == "try deeper models"` — tests real `_serialize_expert_advice` function on string input; no mocks |
| `test_structured_expert_advice_serialized` | Keep | `assert "Focus areas: depth" in kwargs["expert_advice"]` — asserts that ExpertAdvice is serialized before being passed to `brain.plan()` |
| `test_success_record_memory_carries_time_fields_formal` | Keep | `assert mem["time_estimate_minutes"] == 12.0` and `assert mem["time_budget_minutes"] == 30.0` and `assert mem["time_mode"] == "formal"` — tests that time estimator fields are written to memory on gate-pass |
| `test_success_record_memory_carries_vram_fields_formal` | Keep | `assert mem["vram_estimate_gb"] == 2.5` and `assert mem["vram_budget_gb"] == 6.0` — tests VRAM fields written to memory on gate-pass |
| `test_success_record_memory_time_mode_trial` | Keep | `assert trial_rec["memory"]["time_mode"] == "trial"` — tests time_mode="trial" in trial round's memory |
| `test_success_record_memory_vram_fields_trial_mode` | Keep | `assert trial_rec["memory"]["vram_estimate_gb"] == 2.5` — tests VRAM memory fields in trial mode |
| `test_success_record_omits_time_fields_when_gate_disabled` | Keep | `assert "time_estimate_minutes" not in mem` — tests that when gate is disabled, memory dict has no time keys (not None, but absent) |
| `test_success_record_omits_vram_fields_when_gate_disabled` | Keep | `assert "vram_estimate_gb" not in mem` and `assert "vram_budget_gb" not in mem` — tests absence of VRAM keys when both budgets are None |
| `test_timing_fields_present` | Keep | `assert output.started_at` and `assert output.finished_at` — tests that timing fields are populated (not None) |
| `test_trial_allowed_false_forces_formal` | Keep | `assert saved_records[0].get("is_trial", False) is False` — tests that is_trial=False on input forces all rounds to formal |
| `test_trial_config_written` | Keep | `assert len(trial_configs) >= 1` and `assert "is_trial" in tc` and `assert "mode" in tc` — tests that trial_config JSON is written with required fields |
| `test_trial_mode_round_picks_trial_budget` | Keep | `assert time_calls[0]["time_budget_minutes"] == 15.0` — tests per-mode budget pick: trial round gets trial_budget=15.0 not formal_budget=240.0 |
| `test_trial_mode_round_picks_trial_vram_budget` | Keep | `assert vram_calls[0]["vram_budget_gb"] == 6.0` — tests per-mode VRAM budget pick: trial round gets trial_vram_budget |
| `test_trial_round_with_only_formal_budget_skips_gate` | Keep | `assert len(time_calls) == 1` and `assert time_calls[0]["time_budget_minutes"] == 240.0` — tests that when trial_budget is None, trial round skips gate; only formal round fires |
| `test_vram_fail_short_circuits_time_check` | Keep | `assert "evaluate_vram_skill" in called` and `assert "evaluate_time_skill" not in called` — tests that VRAM gate failure short-circuits before time check |

### `tests/unit/agent/tune_ml_hyperparam_agent/test_tuning_cli.py`

Tests: 4

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_builtin_model_no_seed_proceeds` | Keep | `mock_agent.run.assert_called_once()` and `assert agent_input.model_type == "fcnet"` and `assert agent_input.seed_plugin_path is None` — tests CLI argparse wiring for built-in model; HyperparamTuningAgent is mocked but asserts are on the constructed HyperparamTuningInput |
| `test_plugin_model_with_mismatched_seed_errors` | Keep | `with pytest.raises(Exception, match="PLUGIN_MODEL_TYPE"): main()` and `mock_agent_cls.assert_not_called()` — tests Pydantic schema catches model_type/PLUGIN_MODEL_TYPE mismatch before agent construction |
| `test_plugin_model_with_seed_proceeds` | Keep | `assert agent_input.model_type == "attn_fcnet"` and `assert agent_input.seed_plugin_path == seed_path` — tests that seed path is wired into HyperparamTuningInput |
| `test_plugin_model_without_seed_errors` | Keep | `with pytest.raises(SystemExit): main()` and `assert "--force_model='attn_fcnet'" in err` and `mock_agent_cls.assert_not_called()` — tests CLI preflight raises SystemExit with actionable error message before agent construction |

### `tests/unit/agent/tune_ml_hyperparam_agent/test_warmup_activation.py`

Tests: 5

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_static_formula_uses_patched_constants` | Keep | `assert _STATIC_MS_PER_FLOP == 3e-9` and `assert SAFETY_MULTIPLIER == 1.3` and `assert bd["safety_multiplier"] == 1.3` — constant regression guard |
| `test_warmup_path_entered_with_valid_data_dir` | Keep | `assert ms is None` with valid `data_dir` (confirms past early-return guard) — path entry verification |
| `test_warmup_skipped_when_data_dir_does_not_exist` | Keep | `assert ms is None` with `data_dir="/nonexistent/path/that/does/not/exist"` |
| `test_warmup_skipped_when_data_dir_is_empty_string` | Keep | `assert ms is None` with `data_dir=""` — empty string guard |
| `test_warmup_skipped_when_data_dir_is_none` | Keep | `assert ms is None` and `assert breakdown["aggregator"] is None` with `data_dir=None` — real function call |

### `tests/unit/agent/utils/test_architectural_pattern_tagger.py`

Tests: 19

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_all_four_windowing_keys_suppress_dense_attention_tag` | Keep | `assert tag_architecture("attention_stack", model_config) == []` for each of 4 window keys — exercises all four key names as suppression guards |
| `test_architectural_patterns_has_no_orphan_descriptions` | Keep | `assert not orphans` where `orphans = ARCHITECTURAL_PATTERNS.keys() - reachable` — reverse invariant: no dead descriptions |
| `test_empty_model_type_returns_empty` | Keep | `assert tag_architecture("", {}) == []` — exercises empty-string edge case |
| `test_every_emitted_tag_has_an_english_description` | Keep | `assert not missing` where `missing = emitted - ARCHITECTURAL_PATTERNS.keys()` — completeness invariant: all emitted tags must have descriptions |
| `test_iter2_selective_scan_gets_scan_over_T` | Keep | `assert tag_architecture("selective_bidirectional_scan_conv", model_config) == ["scan_over_T"]` — exercises SSM conjunctive pattern using real failure-case config |
| `test_iter3_gru_stack_gets_recurrent_over_T` | Keep | `assert tag_architecture("dual_path_gated_gru_stack", model_config) == ["recurrent_over_T"]` — exercises GRU recurrent pattern using real failure-case config |
| `test_iter4_fourier_tcn_gets_no_tags` | Keep | `assert tag_architecture("gated_fourier_tcn", model_config) == []` — exercises true-negative: TCN must NOT be flagged |
| `test_model_matching_multiple_patterns_gets_all_tags_sorted` | Keep | `assert tags == ["dense_attention_over_T", "recurrent_over_T"]` — pins multi-tag sorted output |
| `test_none_model_config_is_handled_gracefully` | Keep | `assert tag_architecture("some_model", None) == []` — exercises None model_config defensive guard |
| `test_none_model_type_is_handled_gracefully` | Keep | `assert tag_architecture(None, {}) == []` — exercises None defensive guard |
| `test_output_is_deterministic_across_calls` | Keep | `assert out1 == out2 == out3` — exercises stable determinism across repeated calls |
| `test_recurrent_config_key_alone_triggers_tag_even_if_name_hides_it` | Keep | `assert tag_architecture("custom_block_stack", {"lstm_hidden_size": 64}) == ["recurrent_over_T"]` — exercises config-key trigger independent of model_type name |
| `test_ssm_key_alone_does_not_trigger_scan_tag` | Keep | `assert tag_architecture("custom_block_stack", {"ssm_dt_rank": 8}) == []` — exercises other half of conjunction guard |
| `test_state_dim_alone_does_not_trigger_scan_tag` | Keep | `assert tag_architecture("custom_block_stack", {"state_dim": 16}) == []` — exercises half-conjunction false-positive guard |
| `test_state_dim_plus_ssm_key_triggers_scan_tag` | Keep | `assert tag_architecture("custom_block_stack", {"state_dim": 16, "ssm_dt_rank": 8}) == ["scan_over_T"]` — exercises conjunctive trigger |
| `test_thresholds_are_the_documented_v1_values` | Keep | `assert TIME_FACTOR_THRESHOLD == 5.0` and `assert VRAM_FACTOR_THRESHOLD == 2.0` — pins exported constant values to documented v1 thresholds |
| `test_transformer_with_window_is_not_flagged` | Keep | `assert tag_architecture("transformer_base", model_config) == []` with `window_size=128` — exercises windowing suppression |
| `test_transformer_without_window_gets_dense_attention_over_T` | Keep | `assert tag_architecture("transformer_base", model_config) == ["dense_attention_over_T"]` — exercises attention tag |
| `test_unknown_model_type_with_no_matching_keys_returns_empty` | Keep | `assert tag_architecture("some_novel_fft_variant", {"hidden_channels": 64}) == []` — exercises unknown-model empty-output contract |

### `tests/unit/agent/utils/test_proposer_preflight.py`

Tests: 20

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_default_sample_set_has_non_empty_per_file_segments` | Keep | `for fi, segs in ss.items(): assert len(segs) > 0` — no empty segment lists |
| `test_default_sample_set_has_twenty_files` | Keep | `ss = _synthesise_default_sample_set(); assert len(ss) == 20` — shape contract |
| `test_default_sample_set_is_deterministic` | Keep | `a = _synthesise_default_sample_set(); b = _synthesise_default_sample_set(); assert a == b` — same seed → identical output |
| `test_estimate_proposal_time_respects_trial_portion` | Keep | `expected_ratio = 0.2; actual_ratio = out_small["estimated_minutes"] / out_default["estimated_minutes"]; assert abs(actual_ratio - expected_ratio) < 0.05` — quantitative scaling |
| `test_estimate_runs_without_sample_set_argument` | Keep | `out = estimate_proposal_time(...); assert out["estimated_minutes"] > 0.0` — caller can omit sample_set |
| `test_factor_matches_estimated_over_budget` | Keep | `expected = round(out["estimated_minutes"] / 20.0, 3); assert out["factor"] == pytest.approx(expected, rel=1e-2)` — internal consistency between fields |
| `test_factor_monotonic_in_epochs` | Keep | `assert many["factor"] > few["factor"]` for 20 vs 2 epochs — monotonicity |
| `test_factor_monotonic_in_num_params` | Keep | `assert bigger["factor"] > base["factor"]` where base has 1M params and bigger has 10M — monotonicity property |
| `test_invented_model_type_does_not_raise` | Keep | `out = estimate_proposal_time(model_type="completely_invented_architecture_v42", ...)` then `assert "estimated_minutes" in out; assert out["estimated_minutes"] > 0.0` — unregistered type doesn't raise |
| `test_iter2_style_overshoot_flagged_infeasible` | Keep | `assert out["feasible"] is False; assert out["factor"] > 10.0` — the real-world failing config from live run reads as infeasible |
| `test_iter4_style_tcn_passes_feasibility` | Keep | `assert out["feasible"] is True; assert out["factor"] < 5.0` — the real-world succeeding config passes |
| `test_negative_num_params_raises` | Keep | `with pytest.raises(ValueError, match="num_params must be positive")` |
| `test_negative_time_budget_raises` | Keep | `with pytest.raises(ValueError, match="time_budget_minutes must be positive")` |
| `test_no_cuda_probe_via_wrapper` | Keep | `monkeypatch.setattr(sys.modules["torch"].cuda, "is_available", _boom)` then runs successfully — verifies no CUDA touch in pre-flight path |
| `test_returns_four_documented_keys` | Keep | `assert set(out.keys()) == {"estimated_minutes", "factor", "verdict", "feasible"}` — return shape contract |
| `test_runs_without_data_dir` | Keep | `out = estimate_proposal_time(...); assert out["estimated_minutes"] >= 0.0` — no data_dir needed |
| `test_trial_portion_kwarg_scales_default_sample_set` | Keep | `n_small = sum(len(v) for v in ss_small.values()); assert n_small < n_default` for trial_portion=0.02 vs 0.1 — scaling logic |
| `test_verdict_reflects_feasibility` | Keep | `assert "OVER BUDGET" in infeasible["verdict"]; assert "FITS" in feasible["verdict"]` — verdict string content |
| `test_zero_num_params_raises` | Keep | `with pytest.raises(ValueError, match="num_params must be positive")` |
| `test_zero_time_budget_raises` | Keep | `with pytest.raises(ValueError, match="time_budget_minutes must be positive")` |

### `tests/unit/agent_generated/test_stub_plugin_template_loads.py`

Tests: 5

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_config_class_is_pydantic_basemodel_and_instantiates_with_defaults` | Keep | `assert issubclass(mod.PLUGIN_CONFIG_CLASS, BaseModel)` and `assert cfg.model_type == "stub_arch"` — exercises Pydantic subclass check and default instantiation |
| `test_forward_shape_contract` | Keep | `assert y.shape == (B, 256, T)` and `assert y.dtype.is_floating_point` — pins `[B,T]int → [B,256,T]float` forward contract using real torch tensor |
| `test_plugin_model_type_is_stub_arch` | Keep | `assert mod.PLUGIN_MODEL_TYPE == "stub_arch"` — pins the model type slug used by synth name builder |
| `test_template_exposes_three_plugin_symbols` | Keep | `for attr in ("PLUGIN_MODEL_TYPE", "PLUGIN_CONFIG_CLASS", "PLUGIN_MODEL_CLASS"): assert hasattr(mod, attr)` — exercises plugin contract symbol presence |
| `test_template_file_exists` | Keep | `assert os.path.isfile(_TEMPLATE_PATH)` — exercises file existence check; catches missing B1 commit artefact |

### `tests/unit/core/test_hardware_context.py`

Tests: 10

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_cpu_stub_cap_is_zero` | Keep | `assert ctx.usable_cap_bytes == 0; assert ctx.device_available is False` — tests CPU-only schema |
| `test_discover_on_cpu_only_host` | Keep | `ctx = discover(); assert ctx.device_available is False; assert ctx.device_name == "cpu"` — tests real `discover()` with monkeypatched `torch.cuda`; no mocks, real function |
| `test_discover_on_fake_a100_40gb_same_code` | Keep | `assert ctx.usable_cap_gb == pytest.approx(32.0, rel=1e-9)` — validates same code path for different GPU |
| `test_discover_on_fake_a100_80gb_same_code` | Keep | `assert ctx.usable_cap_gb == pytest.approx(64.0, rel=1e-9)` — validates 80GB scaling |
| `test_discover_on_fake_rtx_5090` | Keep | `assert ctx.usable_cap_bytes == int(0.80 * 32 * 1024**3)` — tests discover with patched GPU properties; actual formula execution |
| `test_discover_timestamp_is_fresh` | Keep | `assert before <= ctx.discovered_at <= after` — tests that discovered_at is UTC-aware and actually fresh |
| `test_schema_is_frozen` | Keep | `with pytest.raises(ValidationError): ctx.device_name = "CHANGED"` — tests Pydantic frozen model behavior |
| `test_total_memory_gb_conversion` | Keep | `assert ctx.total_memory_gb == pytest.approx(32.0, rel=1e-9)` — pins bytes-to-GB formula |
| `test_usable_cap_bytes_is_exactly_safety_fraction_of_total` | Keep | `assert ctx.usable_cap_bytes == int(_SAFETY_FRACTION * total)` and `assert _SAFETY_FRACTION == 0.80` — pins the formula and the safety fraction constant |
| `test_usable_cap_rescales_without_code_change` | Keep | `for total_gib in [16, 24, 32, 40, 80]: assert ctx.usable_cap_bytes == int(0.80 * total)` — tests Principle 5; same code adapts to any GPU size |

### `tests/unit/core/test_inference_defaults.py`

Tests: 7

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_empty_string_returns_default` | Keep | `assert inference_batch_for("") == 25` — edge case |
| `test_error_message_names_the_model_type` | Keep | `pytest.raises(ValueError, match="'my_plugin'")` — model_type in message |
| `test_error_message_points_to_defaults_file` | Keep | `pytest.raises(ValueError, match=r"core/inference_defaults.py")` — actionable error |
| `test_known_model_types_do_not_raise` | Keep | `assert assert_inference_batch_registered(model_type) is None` — registered types pass silently |
| `test_known_model_types_return_table_values` | Keep | `assert inference_batch_for(model_type) == expected` parametrized for punet/wavenet/fcnet/rnn/transformer — table correctness |
| `test_unknown_model_type_raises_value_error` | Keep | `pytest.raises(ValueError, match="no registered inference batch")` — loud raise |
| `test_unknown_model_type_returns_default` | Keep | `assert inference_batch_for("some_plugin_model") == 25` — silent fallback |

### `tests/unit/core/test_manifest_io.py`

Tests: 11

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_get_or_create_creates_missing_manifest` | Keep | `monkeypatch.setattr(hc, "discover", lambda: fresh)` then `assert result == fresh` and file existence — real lifecycle |
| `test_get_or_create_regenerates_on_corrupt_manifest` | Keep | `path.write_text("{ this is not json ")` then recovery checked and log message verified |
| `test_get_or_create_regenerates_on_device_mismatch` | Keep | `assert result.device_name == "NVIDIA A100-SXM4-80GB"` and `assert load_manifest(path) == fresh` and log message check |
| `test_get_or_create_regenerates_on_hostname_mismatch` | Keep | `assert result.hostname == "expanse-17"` |
| `test_get_or_create_regenerates_on_schema_mismatch` | Keep | Old-schema JSON triggers regeneration and `assert result == fresh` |
| `test_get_or_create_reuses_matching_manifest_without_rewrite` | Keep | `assert path.stat().st_mtime_ns == mtime_before` — no-rewrite contract |
| `test_load_manifest_raises_on_missing_fields` | Keep | `path.write_text(json.dumps({"device_name": "only-this-field"}))` then `pytest.raises(ValidationError)` — corrupt manifest detection |
| `test_load_manifest_roundtrip_preserves_all_fields` | Keep | `loaded == original` and `assert isinstance(loaded.compute_capability, tuple)` — round-trip and type preservation |
| `test_write_manifest_creates_parents` | Keep | `assert path.exists()` and `assert path.parent.is_dir()` — real filesystem side effect |
| `test_write_manifest_is_valid_json` | Keep | `raw = json.loads(path.read_text())` then asserts field values including `raw["compute_capability"] == [12, 0]` — real JSON serialization |
| `test_write_manifest_trailing_newline` | Keep | `assert path.read_text().endswith("\n")` — POSIX compliance |

### `tests/unit/core/test_resume.py`

Tests: 62

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_accumulates_findings_chronologically` | Keep | `assert findings == ["A", "B", "C"]` — tests dedup + chronological union |
| `test_collects_gate_exhaustions_chronologically` | Keep | `assert msgs == ["iter1", "iter2", "iter3"]` — tests gate exhaustion accumulation |
| `test_collects_rejections_chronologically` | Keep | `assert order == ["arch_a", "arch_b", "arch_c"]` — tests accumulation from run_output overrides |
| `test_current_iter_1_does_not_require_existing_workspace` | Keep | `ws = tmp_path / "nonexistent_yet"; state = restore_prior_state(str(ws), 1, [])` — tests that iter-1 doesn't need existing directory |
| `test_current_iter_1_returns_seeds_verbatim` | Keep | `assert state.resolved_source_paths == seeds; assert state.committed_iters == []` — tests real no-op path of `restore_prior_state` |
| `test_current_iter_below_one_raises` | Keep | `with pytest.raises(ResumeError, match="current_iter must be >= 1")` — tests input validation |
| `test_drops_malformed_vocab_entries_with_warning` | Keep | `with pytest.warns(UserWarning, match="dropped malformed runtime_vocab entry"); assert names == ["good_a", "good_b"]` — tests per-entry validation |
| `test_empty_committed_iters_returns_empty` | Keep | `cache = load_latest_knowledge_cache(str(tmp_path), 5, []); assert cache == {}` — edge case |
| `test_explicit_empty_overwrites` | Keep | `_write_interp_digest_with_cache(..., model_knowledge_cache={}); cache = ...; assert cache == {}` — tests that explicit empty dict overwrites previous |
| `test_gate_exhaustions_capped_at_K10` | Keep | `assert msgs[0] == "iter03"; assert msgs[-1] == "iter12"` — tests cap with eviction order |
| `test_interpretation_path_uses_chain_wide_iter_dir_name_for_iter_above_1` | Keep | `assert "iter_007" in path and "iteration_007" in path` — regression guard for same drift on knowledge channel |
| `test_invalid_plugin_file_warns_and_continues` | Keep | `with pytest.warns(UserWarning, match="failed _load_plugin validation"); assert state.committed_iters == [1]` — tests invalid plugin handling |
| `test_iter1_leaves_cache_empty` | Keep | `state = restore_prior_state(..., 1, []); assert state.model_knowledge_cache == {}` — full-stack test |
| `test_iter1_leaves_negative_feedback_empty` | Keep | `assert state.accumulated_physical_rejections == []; assert state.accumulated_gate_exhaustions == []` |
| `test_iter1_leaves_new_fields_empty` | Keep | `assert state.runtime_vocab == []; assert state.accumulated_physical_rejections == []` — tests all new fields empty at iter 1 |
| `test_iter1_leaves_proposal_field_none` | Keep | `assert state.previous_proposal_data is None` — tests iter-1 initial state |
| `test_iter1_returns_empty` | Keep | `vocab, findings = load_latest_knowledge(str(tmp_path), 1, []); assert vocab == []; assert findings == []` — tests short-circuit |
| `test_iter1_returns_empty_dict` | Keep | `cache = load_latest_knowledge_cache(str(tmp_path), 1, []); assert cache == {}` — short-circuit test |
| `test_iter_dir_entirely_missing_raises` | Keep | `with pytest.raises(ResumeError, match=r"iter 002: manifest")` — tests error for missing iter dir |
| `test_iter_with_no_rejections_contributes_nothing` | Keep | `assert order == ["arch_a", "arch_c"]` — tests that empty rejection list contributes nothing |
| `test_iter_with_none_gate_exhaustion_skipped` | Keep | `assert msgs == ["iter1", "iter3"]` — tests that None gate_exhaustion is skipped |
| `test_legacy_digest_without_cache_key_skipped` | Keep | `assert sorted(cache.keys()) == ["early"]` — tests backward-compat: missing key = no update |
| `test_load_latest_proposal_glob_walks_attempt_dirs` | Keep | `assert out == {"id": "iter3_attempt2_accepted"}` — tests that highest attempt number wins |
| `test_load_latest_proposal_latest_committed_wins` | Keep | `out = load_latest_proposal(str(tmp_path), [1, 2, 3]); assert out == {"id": "iter3_proposal"}` — tests latest-wins |
| `test_load_latest_proposal_malformed_warns_and_skips` | Keep | `with pytest.warns(UserWarning, match=r"iter 002.*cannot read proposal"); assert out == {"id": "iter1_proposal"}` — tests fallback on malformed JSON |
| `test_load_latest_proposal_no_committed_iters_returns_none` | Keep | `assert load_latest_proposal(str(tmp_path), []) is None` — edge case |
| `test_malformed_manifest_json_raises` | Keep | `with pytest.raises(ResumeError, match=r"manifest.json is malformed")` — tests JSON parse error |
| `test_malformed_run_output_json_raises` | Keep | `with pytest.raises(ResumeError, match="run_output failed validation")` — tests JSON parse failure |
| `test_manifest_without_output_path_raises` | Keep | `with pytest.raises(ResumeError, match="no output_path")` — tests missing output_path field |
| `test_missing_manifest_raises` | Keep | `with pytest.raises(ResumeError, match=r"iter 002: manifest\.json not found")` — tests error for missing manifest |
| `test_missing_plugin_file_warns_and_continues` | Keep | `with pytest.warns(UserWarning, match="plugin file not found"); assert state.restored_plugins == []` — tests warning + continuation |
| `test_no_records_iter_does_not_break_accumulation` | Keep | `assert len(state.accumulated_physical_rejections) == 2; assert state.committed_iters == [1, 3]` — tests no_records iter handling |
| `test_partial_restore_when_current_iter_in_middle` | Keep | `state = restore_prior_state(str(workspace), 3, []); assert state.committed_iters == [1, 2]` — tests partial restore |
| `test_picks_latest_cache` | Keep | `assert sorted(cache.keys()) == ["c"]; assert "a" not in cache and "b" not in cache` — tests latest-wins (NOT union) |
| `test_picks_latest_runtime_vocab` | Keep | `names = sorted(v.name for v in vocab); assert names == ["feat_iter2_a", "feat_iter2_b"]` — tests latest-wins semantics |
| `test_plugin_dir_layout_uses_get_plugin_dir_helper` | Keep | `expected = get_plugin_dir(str(tmp_path), "iter_001"); assert os.path.isfile(plugin_file)` — pins layout contract |
| `test_populates_cache_from_latest_iter` | Keep | `assert sorted(state.model_knowledge_cache.keys()) == ["resume_cache_arch_a", "resume_cache_arch_b"]` — tests full-stack cache carry-over |
| `test_populates_new_fields_from_prior_iters` | Keep | `names = sorted(v.name for v in state.runtime_vocab); assert names == ["feat_iter1", "feat_iter2"]` — tests full-stack knowledge carry-over |
| `test_populates_previous_proposal_data_from_latest_iter` | Keep | `assert state.previous_proposal_data["id"] == "p2"` — tests latest-wins for proposal carry-over |
| `test_proposal_field_none_when_no_proposal_files_exist` | Keep | `assert state.committed_iters == [1]; assert state.previous_proposal_data is None` — tests None when files absent |
| `test_proposal_path_returns_none_when_iteration_dir_missing` | Keep | `assert _proposal_path(str(tmp_path), 5) is None` — tests missing dir |
| `test_proposal_path_returns_none_when_no_attempt_dir` | Keep | `assert _proposal_path(str(tmp_path), 1) is None` — tests silent None |
| `test_proposal_path_uses_chain_wide_iter_dir_name_for_iter_above_1` | Keep | `assert "iteration_005" in str(path)` and `assert "iter_005" in resolved and "iteration_005" in resolved` — regression guard for cc198ad path drift |
| `test_registry_actually_populated` | Keep | `assert mt in MODEL_REGISTRY; assert get_output_type(mt) == "classifier"` — tests that real plugin loading populates registries |
| `test_rejections_capped_at_K10_most_recent_wins` | Keep | `assert len(state.accumulated_physical_rejections) == _MAX_ACCUMULATED_REJECTIONS` and first/last model_type checks — tests cap logic |
| `test_resolved_paths_are_seeds_then_chronological` | Keep | `assert "iter_001" in state.resolved_source_paths[2]` — tests path ordering contract |
| `test_restored_plugins_in_chronological_order` | Keep | `assert state.restored_plugins == ["resume_test_arch_a", "resume_test_arch_b", "resume_test_arch_c"]` — tests plugin ordering |
| `test_restores_all_prior_iters` | Keep | `assert state.committed_iters == [1, 2, 3]` — tests that all prior iters are collected |
| `test_returns_defensive_copy` | Keep | `cache_a["mutated"] = {"sentinel": True}; cache_b = load_latest_knowledge_cache(...); assert "mutated" not in cache_b` — tests that returned dict is a defensive copy |
| `test_run_output_file_missing_raises` | Keep | `with pytest.raises(ResumeError, match=r"output_path .* does not exist")` — tests missing run_output file |
| `test_run_output_validation_error_raises` | Keep | `with pytest.raises(ResumeError, match="run_output failed validation")` — tests Pydantic validation failure |
| `test_seeds_empty_list_works` | Keep | `assert len(state.resolved_source_paths) == 3` — edge case: empty seeds |
| `test_seen_in_runs_preserved_verbatim` | Keep | `assert vocab[0].seen_in_runs == ["iter_001"]` — tests non-mutation contract |
| `test_skips_malformed_json_with_warning` | Keep | `with pytest.warns(UserWarning, match="iter 002.*cannot read"); assert findings == ["finding_iter1"]` — tests malformed JSON handling |
| `test_skips_missing_digest_with_warning` | Keep | `with pytest.warns(UserWarning, match="iter 002.*digest not found"); assert [v.name for v in vocab] == ["feat_iter1"]` — tests graceful skip |
| `test_some_plugins_present_some_missing_partial_restore` | Keep | `assert state.restored_plugins == ["resume_test_arch_b"]` — tests partial plugin restoration |
| `test_status_failed_raises` | Keep | `with pytest.raises(ResumeError, match="status='failed'")` — tests failed status rejection |
| `test_status_no_records_interleaved_with_completed` | Keep | `assert state.committed_iters == [1, 3]; assert "iter_003" in state.resolved_source_paths[2]` — tests interleaved no_records iters |
| `test_status_no_records_skips_cleanly` | Keep | `assert state.committed_iters == []; assert state.resolved_source_paths == seeds` — tests silent skip for no_records |
| `test_status_partial_raises` | Keep | `with pytest.raises(ResumeError, match="status='partial'")` — tests partial status rejection |
| `test_two_iter_pseudo_run_repopulates_model_registry` | Keep | `assert mt in MODEL_REGISTRY; assert mt in PLUGIN_CONFIG_REGISTRY` — high-fidelity pseudo-integration with real plugin loading |
| `test_workspace_does_not_exist_raises_for_iter_above_1` | Keep | `with pytest.raises(ResumeError, match="workspace does not exist")` — tests missing workspace error |

### `tests/unit/core/test_sandbox_executor.py`

Tests: 30

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_default_is_false` | Keep | `assert sb.progress_bar is False` — pins attribute initialization |
| `test_distinct_run_names_distinct_dirs` | Keep | `assert a != b` — isolation per run_name |
| `test_explicit_beats_registry_on_known_type` | Keep | `assert self._cli_token_after(cmd, "--inference_batch_size") == "4"` even though `fcnet` has a registry entry — explicit always wins |
| `test_explicit_inference_batch_is_used` | Keep | `assert self._cli_token_after(cmd, "--inference_batch_size") == "8"` — verifies explicit batch overrides registry value |
| `test_failure_path_returns_uniform_keys` | Keep | `assert result["per_file_timings_ms"] == []` and `assert result["subprocess_wall_ms"] is None` after `CalledProcessError` — uniform key contract on error |
| `test_layout_matches_doc` | Keep | `assert result == expected` where `expected = _os.path.join(str(tmp_path), "plugins", "run_a")` — documented path layout |
| `test_matches_sandbox_plugin_dir` | Keep | `assert get_plugin_dir(str(tmp_path), "run_x") == sb.plugin_dir` — helper and sandbox agree on path |
| `test_no_plugin_dir_leaves_env_var_unset` | Keep | `assert "SIDERIUS_PLUGIN_DIRS" not in env` — no plugin_dir = no env var |
| `test_none_falls_back_to_registry` | Keep | `assert self._cli_token_after(cmd, "--inference_batch_size") == "25"` — None falls back to fcnet registry value |
| `test_normal_mode_omits_timing_flag` | Keep | `assert "--timing_out_json" not in cmd` — baseline runs do not get timing sidecar |
| `test_omitted_kwarg_falls_back_to_registry` | Keep | `assert self._cli_token_after(cmd, "--inference_batch_size") == "25"` — omitted kwarg uses default=None path |
| `test_plugin_dir_created_under_workspace` | Keep | `assert sb.plugin_dir == expected` and `assert _os.path.isdir(sb.plugin_dir)` — plugin dir created at construction |
| `test_plugin_dir_does_not_clobber_pythonpath` | Keep | `assert "PYTHONPATH" in env` and `assert project_root in env["PYTHONPATH"]` etc — regression guard that plugin_dir wiring doesn't break PYTHONPATH |
| `test_plugin_dir_populates_env_var` | Keep | `assert env["SIDERIUS_PLUGIN_DIRS"] == str(tmp_path)` — plugin_dir wired into env |
| `test_progress_bar_false_captures_stdout` | Keep | `assert kwargs["stdout"] == subprocess.PIPE` after `mock_run.side_effect = _make_train_success_side_effect(...)` — verifies subprocess.run called with correct stdout kwarg |
| `test_progress_bar_true_streams_stdout` | Keep | `assert kwargs["stdout"] is None` — verifies stdout=None when progress_bar=True |
| `test_returncode_zero_no_sentinel_returns_error_training` | Keep | `assert out["status"] == "error"` and `assert out["message"].startswith("error_training:")` and `assert EXP_ID in out["message"]` — silent-crash detection |
| `test_returns_absolute_path` | Keep | `assert _os.path.isabs(result)` for relative workspace input — absolute path contract |
| `test_sentinel_present_keeps_success_status` | Keep | `assert out["status"] == "success"` and `assert "error_training:" not in out.get("message", "")` — sentinel present = success, no false positive |
| `test_set_false` | Keep | `assert sandbox.progress_bar is False` — fixture-verified attribute |
| `test_set_true` | Keep | `assert sandbox_progress.progress_bar is True` — fixture-verified attribute |
| `test_silent_crash_does_not_read_train_results_json` | Keep | `assert out["status"] == "error"` and `assert "results" not in out` — short-circuit before reading nonexistent JSON |
| `test_silent_crash_message_includes_stderr_tail` | Keep | `assert "--- stderr tail (last 20 lines) ---" in out["message"]` and `assert "line 24: noisy warning" in out["message"]` and `assert "line 4: noisy warning" not in out["message"]` — 20-line tail behavior |
| `test_stderr_always_captured` | Keep | `assert kwargs["stderr"] == subprocess.PIPE` — stderr is always captured regardless of progress_bar |
| `test_stderr_always_captured_with_progress` | Keep | `assert kwargs["stderr"] == subprocess.PIPE` with progress_bar=True sandbox — stderr captured even in streaming mode |
| `test_success_returns_per_file_timings_and_decomposed_wall` | Keep | `assert result["per_file_timings_ms"] == payload` and `assert result["process_startup_ms"] >= 0.0` — timing decomposition contract |
| `test_success_with_missing_sidecar_returns_empty_timings` | Keep | `assert result["per_file_timings_ms"] == []` and `assert result["process_startup_ms"] is None` — missing sidecar fallback |
| `test_training_subprocess_receives_plugin_dir_in_env` | Keep | `assert kwargs["env"]["SIDERIUS_PLUGIN_DIRS"] == sandbox.plugin_dir` — end-to-end env wiring in execute_training |
| `test_trial_mode_appends_timing_flag` | Keep | `assert "--timing_out_json" in cmd` and `assert cmd[idx + 1] == self._expected_timing_path(sandbox)` — verifies CLI flag appended in trial mode |
| `test_two_sandboxes_get_distinct_plugin_dirs` | Keep | `assert sb1.plugin_dir != sb2.plugin_dir` — per-run isolation |

### `tests/unit/core/test_sandbox_rlimit.py`

Tests: 37

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_bare_out_of_memory_error_not_oom` | Keep | `e = _called_process_error(returncode=1, stderr="OutOfMemoryError: GPU allocation failed\n"); assert _is_oom_failure(e) is False` |
| `test_callable_applies_setrlimit` | Keep | `with patch.object(_resource_mod, "setrlimit") as mock_setrlimit: fn = _limited_preexec(gb); fn(); mock_setrlimit.assert_called_once_with(_resource_mod.RLIMIT_AS, (expected_bytes, expected_bytes))` — mock is used to verify the call args of a syscall we can't safely invoke in-p... |
| `test_empty_error_not_oom` | Keep | `e = _called_process_error(returncode=2); assert _is_oom_failure(e) is False` |
| `test_env_negative_falls_back_to_role_default` | Keep | `monkeypatch.setenv("SIDERIUS_SUBPROCESS_RSS_GB", "-5"); assert _subprocess_rss_gb("training") == _ROLE_DEFAULT_RSS_GB["training"]` — negative falls back |
| `test_env_non_numeric_falls_back_to_role_default` | Keep | `monkeypatch.setenv("SIDERIUS_SUBPROCESS_RSS_GB", "not_a_number"); assert _subprocess_rss_gb("training") == _ROLE_DEFAULT_RSS_GB["training"]` — fallback on bad env |
| `test_env_override_wins_for_every_role` | Keep | `monkeypatch.setenv("SIDERIUS_SUBPROCESS_RSS_GB", "12"); assert _subprocess_rss_gb("training") == 12; assert _subprocess_rss_gb("inference") == 12; assert _subprocess_rss_gb("scoring") == 12` — env override |
| `test_env_zero_disables_for_every_role` | Keep | `monkeypatch.setenv("SIDERIUS_SUBPROCESS_RSS_GB", "0"); assert _subprocess_rss_gb("training") == 0` — explicit zero passes through |
| `test_env_zero_disables_preexec` | Keep | `monkeypatch.setenv("SIDERIUS_SUBPROCESS_RSS_GB", "0"); sandbox.execute_training(...); assert kwargs["preexec_fn"] is None` — zero disables preexec |
| `test_generic_exit_1_not_oom` | Keep | `e = _called_process_error(returncode=1, stderr="ValueError: bad config"); assert _is_oom_failure(e) is False` |
| `test_inference_default_is_40` | Keep | `assert _subprocess_rss_gb("inference") == 40; assert _ROLE_DEFAULT_RSS_GB["inference"] == 40` |
| `test_inference_memory_error_returns_oom_status` | Keep | `out = sandbox.execute_inference(...); assert out["status"] == "oom_host_ram"` |
| `test_inference_passes_preexec_fn` | Keep | `mock_run.return_value = _ok_result(); sandbox.execute_inference(...); assert "preexec_fn" in kwargs; assert callable(kwargs["preexec_fn"])` |
| `test_inference_uses_inference_role` | Keep | `mock_rss.assert_called_with("inference")` |
| `test_memory_error_in_stderr_is_oom` | Keep | `e = _called_process_error(returncode=1, stderr="...MemoryError\n"); assert _is_oom_failure(e) is True` |
| `test_memory_error_stderr_gets_oom_tag` | Keep | `e = _called_process_error(returncode=1, stderr="MemoryError\n"); msg = _format_subprocess_error(e, "Train"); assert "[oom_host_ram]" in msg; assert "MemoryError" in msg` — tag present + original error preserved |
| `test_memory_error_with_message_is_oom` | Keep | `e = _called_process_error(returncode=1, stderr="MemoryError: Unable to allocate 1.5 GiB...\n"); assert _is_oom_failure(e) is True` — message after colon still matches |
| `test_non_oom_failure_has_no_oom_tag` | Keep | `e = _called_process_error(returncode=1, stderr="ValueError: bad"); msg = _format_subprocess_error(e, "Inference"); assert "[oom_host_ram]" not in msg` |
| `test_qualified_memory_error_still_oom` | Keep | `e = _called_process_error(returncode=1, stderr="builtins.MemoryError: Unable to allocate\n"); assert _is_oom_failure(e) is True` — qualified name still matches |
| `test_returns_callable_for_positive_gb` | Keep | `fn = _limited_preexec(8); assert callable(fn)` |
| `test_returns_none_for_negative` | Keep | `assert _limited_preexec(-1) is None` |
| `test_returns_none_for_zero` | Keep | `assert _limited_preexec(0) is None` |
| `test_scoring_default_is_24` | Keep | `monkeypatch.delenv("SIDERIUS_SUBPROCESS_RSS_GB", raising=False); assert _subprocess_rss_gb("scoring") == 24; assert _ROLE_DEFAULT_RSS_GB["scoring"] == 24` — default value pinned |
| `test_scoring_memory_error_returns_oom_status` | Keep | `out = sandbox.execute_scoring(...); assert out["status"] == "oom_host_ram"` |
| `test_scoring_passes_preexec_fn` | Keep | analogous for scoring |
| `test_scoring_uses_scoring_role` | Keep | `mock_rss.assert_called_with("scoring")` |
| `test_sigkill_gets_oom_tag` | Keep | `e = _called_process_error(returncode=-9); msg = _format_subprocess_error(e, "Scoring"); assert "[oom_host_ram]" in msg; assert "SIGKILL" in msg` |
| `test_sigkill_returncode_is_oom` | Keep | `e = _called_process_error(returncode=-9); assert _is_oom_failure(e) is True` — SIGKILL pattern recognition |
| `test_sigsegv_not_oom` | Keep | `e = _called_process_error(returncode=-11); assert _is_oom_failure(e) is False` — SIGSEGV not OOM |
| `test_torch_oom_not_tagged_host_ram` | Keep | `e = _called_process_error(returncode=1, stderr="torch.OutOfMemoryError..."); msg = _format_subprocess_error(e, "Train"); assert "[oom_host_ram]" not in msg; assert "OutOfMemoryError" in msg` — regression: false positive was fixed |
| `test_torch_out_of_memory_error_not_oom` | Keep | `stderr = "torch.OutOfMemoryError: CUDA out of memory..."; assert _is_oom_failure(e) is False` — word boundary regex must not false-positive on OutOfMemoryError |
| `test_training_default_is_40` | Keep | `assert _subprocess_rss_gb("training") == 40; assert _ROLE_DEFAULT_RSS_GB["training"] == 40` — default value pinned |
| `test_training_memory_error_returns_oom_status` | Keep | `mock_run.side_effect = _called_process_error(returncode=1, stderr="...MemoryError\n"); out = sandbox.execute_training(...); assert out["status"] == "oom_host_ram"; assert "[oom_host_ram]" in out["message"]` |
| `test_training_non_oom_still_error` | Keep | `out = sandbox.execute_training(...); assert out["status"] == "error"; assert "[oom_host_ram]" not in out["message"]` |
| `test_training_passes_preexec_fn` | Keep | `mock_run.side_effect = _train_success_side_effect(sandbox); sandbox.execute_training(...); _, kwargs = mock_run.call_args; assert "preexec_fn" in kwargs; assert callable(kwargs["preexec_fn"])` — subprocess receives preexec_fn |
| `test_training_sigkill_returns_oom_status` | Keep | `mock_run.side_effect = _called_process_error(returncode=-9); out = sandbox.execute_training(...); assert out["status"] == "oom_host_ram"` |
| `test_training_uses_training_role` | Keep | `mock_rss.return_value = 40; sandbox.execute_training(...); mock_rss.assert_called_with("training")` — role string "training" passed to rss helper |
| `test_unknown_role_raises` | Keep | `with pytest.raises(ValueError, match="unknown role"): _subprocess_rss_gb("bogus")` |

### `tests/unit/core/test_server_configs.py`

Tests: 8

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_defaults_to_current_hostname` | Keep | `monkeypatch.setattr(sc.socket, "gethostname", _fake)` then `assert calls == [None]` and `assert cfg.hostname == "ligroup"` — verifies socket.gethostname() is called when hostname=None |
| `test_frozen` | Keep | `with pytest.raises(ValidationError)` when `cfg.hostname = "y"` — verifies frozen model behavior |
| `test_ligroup_returns_measured_config` | Keep | `assert cfg.per_psd_segment_seconds == pytest.approx(2.21)` — pins the recalibrated constant; intentionally noisy if re-tuned |
| `test_rejects_empty_hostname` | Keep | `with pytest.raises(ValidationError)` for `hostname=""` — verifies min_length validation |
| `test_rejects_extra_fields` | Keep | `with pytest.raises(ValidationError)` for extra field `per_segment_seconds` — verifies extra="forbid" catches typos |
| `test_rejects_nonpositive_per_segment` | Keep | `with pytest.raises(ValidationError)` for `per_psd_segment_seconds=0.0` and `per_psd_segment_seconds=-0.5` — verifies validator |
| `test_unknown_host_falls_back_to_ligroup` | Keep | `with pytest.warns(UserWarning, match="No server config for hostname 'nonsense-host'")` and `assert cfg.hostname == "ligroup"` — verifies fallback and warning text |
| `test_unknown_host_warns_only_once` | Keep | `assert len(first) == 1` and `assert len(second) == 0` — verifies dedup logic for warning suppression |

### `tests/unit/core/test_storage.py`

Tests: 11

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_custom_schema_and_run_name` | Keep | `assert cfg.schema_name == "research"` and `assert cfg.run_name == "exp_42"` — exercises custom field values |
| `test_default_backend_is_local` | Keep | `assert cfg.backend == "local"` — exercises default backend value |
| `test_default_run_name` | Keep | `assert cfg.run_name == "v1"` without providing run_name — exercises default value |
| `test_invalid_backend_raises` | Keep | `with pytest.raises(ValidationError)` and `assert "backend" in str(exc.value)` — exercises backend enum enforcement |
| `test_local_sub_config_is_optional` | Keep | `assert cfg.local is None` for `StorageConfig(backend="local")` — pins runtime-only enforcement; schema allows None |
| `test_missing_connection_string_raises` | Keep | `with pytest.raises(ValidationError)` and `assert "connection_string" in str(exc.value)` — exercises required-field enforcement |
| `test_missing_workspace_raises` | Keep | `with pytest.raises(ValidationError) as exc: LocalStorageConfig()` and `assert "workspace" in str(exc.value)` — exercises required-field enforcement |
| `test_nested_dict_construction` | Keep | `cfg = StorageConfig.model_validate({...})` and `assert cfg.local.workspace == "/data/runs"` — exercises dict-based construction path |
| `test_valid` | Keep | Asserts `cfg.workspace == "/data/runs"` and `cfg.run_name == "v1"` after Pydantic `LocalStorageConfig(...)` construction — pure schema validation |
| `test_valid_local` | Keep | `assert cfg.backend == "local"` and `assert cfg.postgres is None` — exercises local config construction and None-for-unused field |
| `test_valid_postgres_placeholder` | Keep | `assert cfg.backend == "postgres"` and `assert cfg.local is None` — exercises postgres config with None-for-unused local |

### `tests/unit/core/test_stub_sandbox.py`

Tests: 9

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_denoising_score_within_bounds` | Keep | `assert -3.0 <= s <= -2.0` and loop over `fv` values — tests that synthetic denoising_score and file_vector values are within the specified contract range |
| `test_determinism_same_run_id_yields_same_stream` | Keep | `assert out_a["results"]["final_loss"] == out_b["results"]["final_loss"]` — tests that two distinct StubSandbox instances with the same run_id produce identical output |
| `test_execute_inference_returns_schema_valid_success` | Keep | `assert out["per_file_timings_ms"] == []` and `assert out["process_startup_ms"] == pytest.approx(10.0)` — tests inference stub output shape including timing fields consumed by the chain |
| `test_execute_scoring_records_validate_against_experiment_record` | Keep | `ExperimentRecord.model_validate(record)` — tests that stub outputs assembled into a record pass the real ExperimentRecord schema validation gate |
| `test_execute_training_returns_schema_valid_success` | Keep | `assert isinstance(results["final_loss"], float)` and `assert isinstance(results["model_params"], int)` and `assert results["model_params"] > 0` — tests that StubSandbox.execute_training returns correctly shaped output |
| `test_save_record_persists_pseudo_origin_marker_to_disk` | Keep | `assert on_disk["_pseudo_origin"] == "stub_sandbox"` and `assert any(r.get("_pseudo_origin") == "stub_sandbox" for r in summary)` — tests both detail file and summary file carry the marker |
| `test_save_record_stamps_pseudo_origin_and_mirrors_in_memory` | Keep | `assert stub.saved_records[0]["_pseudo_origin"] == "stub_sandbox"` and `assert record["_pseudo_origin"] == "stub_sandbox"` — tests that audit marker is injected and the record is mirrored in-memory |
| `test_score_vector_returns_synthetic_four_tuple` | Keep | `fv, fs, deg, fr = stub.score_vector(...)` then `assert isinstance(fv, list) and len(fv) == 9` and bounds checks — tests four-tuple contract of stub's score_vector method |
| `test_set_run_context_reseeds_for_distinct_run_ids` | Keep | `assert s_alpha != s_beta` and `assert s_alpha == s_alpha_again` — tests that set_run_context changes the stream and that re-seeding with the original run_id reproduces the original output |

### `tests/unit/core/test_workspace_layout_guard.py`

Tests: 8

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_clean_chain_layout_passes` | Keep | creates `iter_001/iteration_001/some_model` and `iter_002/...` then `validate_workspace_layout(ws)` — clean chain layout |
| `test_empty_workspace_passes` | Keep | `validate_workspace_layout(ws)` on empty tmp dir — empty workspace passes |
| `test_error_message_contains_migration_hint` | Keep | `with pytest.raises(ResumeError, match="migrate_workspace")` — pins migration hint in error message |
| `test_legacy_pattern1_iteration_subtree` | Keep | creates `some_run/iteration_001/` then `with pytest.raises(ResumeError, match="Legacy workspace layout")` — legacy pattern detection |
| `test_legacy_pattern2_workflow_json` | Keep | creates `workflow_summary.json` then `with pytest.raises(ResumeError, match="Legacy workspace layout")` — legacy pattern 2 |
| `test_legacy_pattern3_trace_without_iter_001` | Keep | creates `memory_trace.jsonl` without `iter_001/` then `with pytest.raises(ResumeError, match="Legacy workspace layout")` — legacy pattern 3 |
| `test_nonexistent_workspace_passes` | Keep | `validate_workspace_layout(str(tmp_path / "does_not_exist"))` completes without raising — nonexistent path is not an error |
| `test_trace_with_iter_001_passes` | Keep | creates both `iter_001/` and `memory_trace.jsonl` then `validate_workspace_layout(ws)` passes — valid chain workspace with trace |

### `tests/unit/dashboard/test_local_json.py`

Tests: 32

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_agent_run_excludes_seeded_baseline` | Keep | `assert "baseline_punet_001" not in exp_ids` — seeded-record exclusion logic |
| `test_agent_run_total_count` | Keep | `assert total == 3` (2 success + 1 oom) |
| `test_baseline_returns_one_record` | Keep | `assert total == 1` and `assert records[0]["exp_id"] == "baseline_punet_001"` |
| `test_baseline_score` | Keep | `assert ov["baseline_score"] == pytest.approx(-2.1)` |
| `test_best_agent_score` | Keep | `assert ov["best_agent_score"] == pytest.approx(-1.8)` — max across agent records |
| `test_best_run_name` | Keep | `assert ov["best_run_name"] == "v1"` |
| `test_entry_has_required_fields` | Keep | `for field in ("rank", "exp_id", "run_name", ...): assert field in entry` |
| `test_existing_dir_is_healthy` | Keep | `assert ds.health_check() is True` |
| `test_list_models_auto_discovers` | Keep | `assert set(ds.list_models()) == {"punet", "wavenet"}` from synthetic dir fixture — real directory scanning |
| `test_list_models_filters_missing_dirs` | Keep | `models=["punet", "transformer"]` then `assert ds.list_models() == ["punet"]` — missing-dir filtering |
| `test_list_models_respects_explicit_list` | Keep | `LocalJsonDataSource(data_dir, models=["punet"])` then `assert ds.list_models() == ["punet"]` |
| `test_list_runs_includes_agent_run` | Keep | `assert "v1" in runs` |
| `test_list_runs_includes_baseline` | Keep | `assert "baseline" in runs` |
| `test_list_runs_no_agent_run` | Keep | `assert runs == ["baseline"]` for wavenet |
| `test_list_runs_unknown_model_raises` | Keep | `pytest.raises(KeyError)` for `"transformer"` |
| `test_missing_dir_is_unhealthy` | Keep | `assert ds.health_check() is False` for nonexistent dir |
| `test_no_agent_run_best_score_is_none` | Keep | `assert ov["best_agent_score"] is None` for wavenet (no agent run) |
| `test_pagination_limit` | Keep | `assert len(records) == 2` with limit=2, total=3 |
| `test_pagination_offset` | Keep | `assert len(records) == 1` with offset=2 |
| `test_rank_starts_at_one` | Keep | `assert entries[0]["rank"] == 1` |
| `test_returns_correct_record` | Keep | `assert rec["exp_id"] == "punet_v1_agent_001"` |
| `test_returns_ranked_entries` | Keep | `assert scores == sorted(scores, reverse=True)` — sort order |
| `test_runs_list` | Keep | `assert set(ov["runs"]) == {"baseline", "v1"}` |
| `test_skipped_oom_excluded_by_default` | Keep | `assert all(e["denoising_score"] is not None for e in entries)` with status_filter="success" |
| `test_status_counts` | Keep | `assert ov["status_counts"]["success"] == 2` and oom count |
| `test_status_filter_oom` | Keep | `assert total == 1` for oom filter |
| `test_status_filter_success_only` | Keep | `assert total == 2` and `assert all(r["status"] == "success" for r in records)` |
| `test_top_n_respected` | Keep | `assert len(entries) == 1` with top_n=1 |
| `test_total_experiments_excludes_seeded_baseline` | Keep | `assert ov["total_experiments"] == 3` — seeded baseline excluded |
| `test_unknown_exp_id_raises` | Keep | `pytest.raises(KeyError)` for unknown exp_id |
| `test_unknown_model_raises` | Keep | `pytest.raises(KeyError)` for `"transformer"` |
| `test_unknown_run_raises` | Keep | `pytest.raises(KeyError)` for `"v99"` |

### `tests/unit/dashboard/test_settings.py`

Tests: 12

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_cache_clear_reloads` | Keep | `get_settings.cache_clear()` then `assert a.server.port == b.server.port` — both valid settings, cache cleared between calls |
| `test_data_source_type` | Keep | `assert s.data_source.type == "local"` and `assert s.data_source.local.root_data_dir == "/tmp/test_data"` etc — full YAML parsing |
| `test_default_data_source_is_local` | Keep | `assert settings.data_source.type == "local"` — default data source |
| `test_default_port_is_8000` | Keep | `assert settings.server.port == 8000` — default port |
| `test_default_refresh_interval` | Keep | `assert settings.dashboard.refresh_interval_seconds == 30` — default refresh |
| `test_empty_yaml_uses_all_defaults` | Keep | `assert s.data_source.type == "local"` and `assert s.server.port == 8000` — empty YAML uses all defaults |
| `test_get_settings_returns_same_instance` | Keep | `assert a is b` for two calls to `get_settings()` — caching uses `is` identity check |
| `test_invalid_data_source_type_raises` | Keep | `with pytest.raises(ValidationError): load_settings(path)` for `type: mongodb` — invalid Literal rejected |
| `test_invalid_log_level_raises` | Keep | `with pytest.raises(ValidationError): load_settings(path)` for `log_level: verbose` — invalid Literal rejected |
| `test_missing_file_returns_defaults` | Keep | `settings = load_settings(str(tmp_path / "nonexistent.yaml"))` then `assert isinstance(settings, DashboardSettings)` — missing file returns default object |
| `test_only_port_overridden` | Keep | `assert s.server.port == 7777` and `assert s.server.host == "0.0.0.0"` and `assert s.data_source.type == "local"` — partial YAML merges with defaults |
| `test_postgres_type_parsed` | Keep | `assert s.data_source.type == "postgres"` and `assert "localhost" in s.data_source.postgres.connection_string` — postgres config parsing |

### `tests/unit/execute_tools/test_build_anchor_map.py`

Tests: 11

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_anchors_has_20_files` | Keep | `assert len(result["anchors"]) == NUM_FILES` — tests real logic of building per-file dict |
| `test_anchors_keys_are_strings` | Keep | `for key in result["anchors"]: assert isinstance(key, str)` — tests JSON-serialization-friendly key type |
| `test_each_file_has_200_segments` | Keep | `assert len(segments) == SEGMENTS_PER_FILE` — tests inner loop logic |
| `test_num_files` | Keep | `assert NUM_FILES == 20` — pins constant |
| `test_returns_correct_structure` | Keep | `assert "s_max" in result; assert result["segments_per_file"] == SEGMENTS_PER_FILE` — mock replaces only the I/O-bound `_compute_ch2_snr`; assertion is on real `build_anchor_map` structure |
| `test_round_trip` | Keep | writes JSON to `tmp_path`, calls `load_anchor_map`, asserts `loaded["anchors"]["0"] == [1.0, 2.0, 3.0]` — no mocks; real I/O round-trip |
| `test_s_max_is_global_maximum` | Keep | `assert result["s_max"] == 19199.0` — deterministic expected value computed from mock formula; tests real max-finding logic |
| `test_segment_length` | Keep | `assert SEGMENT_LENGTH == 10_000_000` — pins constant value |
| `test_segments_per_file` | Keep | `assert SEGMENTS_PER_FILE == 200` — pins constant |
| `test_snr_values_are_correct` | Keep | `assert result["anchors"]["5"][42] == 5042.0` — spot-checks that mock SNR values are stored correctly at computed positions |
| `test_total_compute_calls` | Keep | `assert mock_compute.call_count == NUM_FILES * SEGMENTS_PER_FILE` — tests that the loop iterates over all (file, segment) pairs |

### `tests/unit/execute_tools/test_dataset_config.py`

Tests: 6

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_empty_when_window_excludes_all_divisors` | Keep | `sizes = TIDMAD.valid_segmentation_sizes(lo=10001, hi=10239); assert sizes == []` — empty not crash |
| `test_excludes_invalid_powers_of_two_for_tidmad` | Keep | `assert 16384 not in sizes; assert 8192 not in sizes; assert 4096 not in sizes` — LLM-proposed bad values are absent |
| `test_includes_known_valid_values_for_tidmad` | Keep | `assert 16000 in sizes; assert 1250 in sizes; assert 1000 in sizes; assert 100 in sizes` — known good values present |
| `test_respects_lo_hi_bounds` | Keep | `sizes = TIDMAD.valid_segmentation_sizes(lo=1000, hi=20000); for s in sizes: assert 1000 <= s <= 20000; assert 100 not in sizes; assert 50000 not in sizes` — bounds filtering |
| `test_returns_sorted_divisors_within_default_window` | Keep | `sizes = TIDMAD.valid_segmentation_sizes(); assert sizes == sorted(sizes); for s in sizes: assert psd % s == 0; assert 100 <= s <= 100_000` — sorted, all divide psd_segment_length, within bounds |
| `test_works_for_arbitrary_dataset` | Keep | `cfg = DatasetConfig(psd_segment_length=1000, ...); sizes = cfg.valid_segmentation_sizes(lo=1, hi=1000); assert 100 in sizes; assert 125 in sizes; assert 3 not in sizes` — parameterized on DatasetConfig |

### `tests/unit/execute_tools/test_inference_single.py`

Tests: 11

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_canonical_del_block_runs_before_create_abra_file` | Keep | `assert canonical_del_idx < create_call_idx` via AST inspection of the trial loop — pins structural ordering contract that buffer-free block precedes create_abra_file |
| `test_canonical_del_includes_view_aliasing_handles` | Keep | `assert "train_loader" in names` and `assert "target_loader" in names` via AST inspection — pins regression: partial del leaves buffers reachable through views |
| `test_gc_collect_follows_canonical_del` | Keep | `assert call.func.attr == "collect"` and `assert call.func.value.id == "gc"` via AST inspection of statement after canonical del — pins gc.collect() placement |
| `test_message_includes_no_retry_language` | Keep | `for forbidden in ("retry", "retrying", "backoff", "will try again"): assert forbidden not in msg` — negative guard against retry semantics in error message |
| `test_missing_sentinel_raises_error_training` | Keep | `assert msg.startswith("error_training:")` and `assert model_path in msg` — pins the exact error prefix that the orchestrator pattern-matches for failure classification |
| `test_per_file_timings_list_appended` | Keep | `assert {"file_index", "n_psd_segs", "elapsed_ms"}.issubset(keys)` via AST inspection of `per_file_timings_ms.append({...})` — pins the three required columns |
| `test_sentinel_path_is_sibling_of_model_path` | Keep | `assert expected_sentinel in str(exc_info.value)` where `expected_sentinel = str(tmp_path / "cached_models" / "_OK_exp_xyz")` — pins the path convention |
| `test_sentinel_present_returns_none` | Keep | `sentinel_path.write_bytes(b"")` then `result = _assert_training_sentinel(model_path, "exp_001")` then `assert result is None` — verifies happy path returns None when sentinel exists |
| `test_sidecar_written_when_flag_set` | Keep | `found = True` only when `json.dump(per_file_timings_ms, ...)` is inside `if args.timing_out_json:` block — pins the gating and variable name via AST walk |
| `test_timing_out_json_flag_registered` | Keep | `assert "--timing_out_json" in flags` via AST walk of `get_parser` function — pins CLI flag existence without requiring subprocess execution |
| `test_trial_loop_brackets_each_iteration_with_perf_counter` | Keep | `assert len(perf_counter_calls) >= 2` via AST walk of trial loop — pins that both start and end timing calls are present |

### `tests/unit/execute_tools/test_phase67_scoring_precision.py`

Tests: 23

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_finite_floats_pass_through` | Keep | `assert coerce_nonfinite_to_none(-2.7708) == -2.7708` — verifies finite values pass through unchanged |
| `test_grand_mean_log_is_bit_exact` | Keep | `assert first == second` (deliberate `==`, not `approx`) — pins bit-exact reproducibility |
| `test_grand_mean_log_matches_python_log` | Keep | `assert got == expected` and `assert abs(got - legacy) > 1e-3` — verifies helper equals hand-computed math.log AND differs from legacy round-then-eps formula |
| `test_min_adjacent_gap_exceeds_noise_floor` | Keep | `assert min_gap > _NOISE_FLOOR_LOG_UNITS` and `assert min_gap > 1e-4` — verifies scores are distinguishable above noise floor and render precision |
| `test_nan_becomes_none` | Keep | `assert coerce_nonfinite_to_none(float("nan")) is None` — verifies NaN coerced |
| `test_nan_renders_explicit_string` | Keep | `assert _fmt_log(float("nan")) == "NaN"` — pins NaN rendering |
| `test_neg_inf_becomes_none` | Keep | `assert coerce_nonfinite_to_none(float("-inf")) is None` — pins sentinel-to-None conversion |
| `test_neg_inf_renders_unicode_minus_infinity` | Keep | `assert _fmt_log(float("-inf")) == "\u2212\u221e"` — pins exact unicode characters, no garbage suffix |
| `test_negative_finite_renders_unicode_minus` | Keep | `assert _fmt_log(-2.7708) == "\u22122.7708"` — verifies unicode minus for negative finite |
| `test_negative_grand_mean_returns_neg_inf` | Keep | `assert _grand_mean_log_scalar(total_linear=-1.0, total_n=10) == float("-inf")` — guard against math.log raising on negative |
| `test_no_record_lands_exactly_on_old_ghost_score` | Keep | `assert new_scalar != _OLD_GHOST_SCORE` for each record — pins that the legacy ghost value is never reproduced |
| `test_none_passes_through` | Keep | `assert coerce_nonfinite_to_none(None) is None` — verifies None pass-through |
| `test_none_renders_n_a` | Keep | `assert _fmt_log(None) == "N/A"` — pins None rendering |
| `test_pos_inf_becomes_none` | Keep | `assert coerce_nonfinite_to_none(float("inf")) is None` — verifies pos-inf also coerced |
| `test_pos_inf_renders_infinity` | Keep | `assert _fmt_log(float("inf")) == "\u221e"` — pins infinity glyph |
| `test_positive_finite_renders_plain` | Keep | `assert _fmt_log(0.5) == "0.5000"` — verifies 4-decimal format |
| `test_recursive_dict_coercion` | Keep | `assert safe["denoising_score"] is None` and `assert safe["file_vector"] == [0.5, None, 1.5, None]` and `assert safe["nested"]["best_score"] is None` and `assert record["denoising_score"] == float("-inf")` (mutation check) — verifies recursive coercion and non-mutation of orig... |
| `test_render_precision_quantizes_at_1e_4` | Keep | `assert _fmt_log(0.12340) == _fmt_log(0.12341)` and `assert _fmt_log(0.12340) != _fmt_log(0.12350)` — pins render precision floor |
| `test_round_trip_through_json_dumps_and_loads` | Keep | `text = json.dumps(safe, allow_nan=False)` and `assert "Infinity" not in text` and `parsed = json.loads(text)` and `assert parsed["denoising_score"] is None` — end-to-end RFC-8259 compliance test |
| `test_seven_records_produce_seven_distinct_scalars` | Keep | `assert len(set(new_scalars.values())) == 7` using real `math.log(gm, _LOG_BASE)` on seven historical grand_means — pins ghost-score killer: all seven collapse differently under new formula |
| `test_span_is_physically_meaningful` | Keep | `assert span > 0.2` — verifies the 0.34 log-unit span survives |
| `test_strings_and_ints_pass_through` | Keep | `assert coerce_nonfinite_to_none("hello") == "hello"` and `assert coerce_nonfinite_to_none(42) == 42` — verifies non-float types pass through |
| `test_zero_total_returns_neg_inf` | Keep | `assert _grand_mean_log_scalar(total_linear=0.0, total_n=0) == float("-inf")` — boundary/guard case |

### `tests/unit/execute_tools/test_sample_set_builder.py`

Tests: 19

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_all_20_files_present` | Keep | `assert sorted(ss.keys()) == list(range(NUM_FILES))` — snapshot strategy coverage |
| `test_all_segments_included` | Keep | `assert ss[6] == list(range(SEGMENTS_PER_FILE))` — tests that all 200 segments included |
| `test_correct_segment_count` | Keep | `expected = max(1, round(0.1 * SEGMENTS_PER_FILE)); assert len(segs) == expected` — tests formula |
| `test_deduplicates_target_files` | Keep | `ss = build_sample_set(..., target_files=[3, 3, 3, 1]); assert sorted(ss.keys()) == [1, 3]` — dedup logic |
| `test_deterministic_with_seed` | Keep | `assert ss1 == ss2` — tests reproducibility |
| `test_different_file_index` | Keep | `ss = build_sample_set(is_trial=False, file_index=0); assert list(ss.keys()) == [0]` — different input |
| `test_different_seeds_differ` | Keep | `differ = any(ss1[fi] != ss2[fi] for fi in ss1); assert differ` — tests that seeds actually have effect |
| `test_empty_target_files_raises` | Keep | `with pytest.raises(ValueError, match="non-empty target_files")` — error for empty list |
| `test_full_portion` | Keep | `assert len(segs) == SEGMENTS_PER_FILE` — boundary: portion=1.0 |
| `test_no_duplicate_segments` | Keep | `assert len(segs) == len(set(segs))` — no duplicates |
| `test_none_target_files_raises` | Keep | `with pytest.raises(ValueError, match="non-empty target_files")` — error for None |
| `test_only_anchor_files` | Keep | `assert sorted(ss.keys()) == sorted(ANCHOR_FILES)` — tests anchors strategy file selection |
| `test_only_target_files` | Keep | `assert sorted(ss.keys()) == [0, 1, 2, 3]` — target strategy |
| `test_returns_single_file` | Keep | `ss = build_sample_set(is_trial=False, file_index=6); assert list(ss.keys()) == [6]` — pure logic; no mocks |
| `test_segments_are_sorted` | Keep | `assert segs == sorted(segs)` — tests sorted output contract |
| `test_segments_are_valid` | Keep | `assert all(0 <= s < SEGMENTS_PER_FILE for s in segs)` — boundary check |
| `test_tiny_portion_at_least_one_segment` | Keep | `assert len(segs) >= 1` — tests minimum-one guarantee |
| `test_trial_fields_ignored` | Keep | `ss = build_sample_set(is_trial=False, ..., trial_strategy="target", target_files=[0,1,2]); assert list(ss.keys()) == [6]` — tests that trial params are ignored when not in trial mode |
| `test_unknown_strategy_raises` | Keep | `with pytest.raises(ValueError, match="Unknown trial_strategy")` — error for invalid strategy |

### `tests/unit/execute_tools/test_score_table_adversarial.py`

Tests: 21

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_above_baseline_renders_percentage` | Keep | `assert "of ceiling" in md` and `assert "< 0%" not in md` — regression: normal path keeps % framing |
| `test_below_baseline_renders_honest_line` | Keep | `assert "Recovery: < 0% (Model performance is below raw baseline)." in md` and `assert "of ceiling" not in md` — verifies below-baseline relabel guard |
| `test_equal_to_baseline_renders_percentage` | Keep | `assert "of ceiling" in md` and `assert "< 0%" not in md` when model_scalar exactly equals raw_baseline_scalar — verifies strict `<` boundary |
| `test_extra_field_rejected` | Keep | `with pytest.raises(ValidationError)` for extra field `foo=1` — verifies extra="forbid" |
| `test_file_index_out_of_bounds_rejected` | Keep | `with pytest.raises(ValidationError)` for `file_index=20` — verifies bounds validation |
| `test_fv_length_19_raises` | Keep | `assert "length 20" in str(exc_info.value)` — verifies length validation error message |
| `test_fv_length_21_raises` | Keep | `assert "length 20" in str(exc_info.value)` — verifies length validation both directions |
| `test_inf_accepted` | Keep | `assert math.isinf(row.model)` — verifies inf accepted |
| `test_list_rejected` | Keep | `with pytest.raises(ValidationError)` for `model=[]` — verifies list type rejected |
| `test_llm_string_null_rejected` | Keep | `with pytest.raises(ValidationError)` for `model="n/a"` etc. and `assert "number" in err["msg"].lower()` — verifies LLM string nulls are rejected with informative message |
| `test_machine_readable_scalars_preserved` | Keep | `assert agg.model_scalar == -7.5` and `assert agg.raw_baseline_scalar == ref.raw_scalar_full` — verifies raw scalars in Pydantic object are untouched by markdown relabeling |
| `test_nan_accepted` | Keep | `assert math.isnan(row.model)` — verifies NaN accepted as a valid float |
| `test_non_none_scalar_with_empty_fv_raises` | Keep | `with pytest.raises(ValueError) as exc_info` and `assert "all-None" in str(exc_info.value)` — verifies upstream inconsistency surfaces loudly |
| `test_none_accepted_as_unsampled_marker` | Keep | `row = PerFileRow(**_good_row_kwargs(model=None))` then `assert row.model is None` — verifies None is the canonical unsampled marker |
| `test_none_scalar_returns_none` | Keep | `assert build_score_table([None] * 20, model_scalar=None, reference=ref) is None` — verifies graceful None return for fully-failed run |
| `test_num_sampled_files_zero_rejected` | Keep | `with pytest.raises(ValidationError)` for `num_sampled_files=0` — verifies ge=1 constraint |
| `test_one_n_a_row_fails_whole_table` | Keep | `assert err["loc"] == ("rows", 19, "model")` — verifies exact field location in validation error |
| `test_one_none_row_accepted` | Keep | `assert tbl.rows[19].model is None` — verifies None passes table-level validation |
| `test_rows_above_max_length_rejected` | Keep | `assert "at most 20" in str(exc_info.value)` — verifies max_length error message |
| `test_rows_below_min_length_rejected` | Keep | `assert "at least 20" in str(exc_info.value)` — verifies min_length error message |
| `test_single_file_sample_works` | Keep | `assert tbl.aggregate.num_sampled_files == 1` and `assert tbl.rows[7].model == 3.0` and `assert all(r.model is None for i, r in enumerate(tbl.rows) if i != 7)` — verifies single-file sampling |

### `tests/unit/execute_tools/test_scoring_helpers.py`

Tests: 29

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_aggregate_block_and_recovery` | Keep | `assert "| **model**            | **5.5763** |" in md` and `assert f"Recovery: **{expected_recovery:.1f}% of ceiling**" in md` — pins exact aggregate block and recovery formatting |
| `test_aggregate_is_subset_scoped` | Keep | `assert tbl.aggregate.raw_baseline_scalar == pytest.approx(expected_raw, abs=1e-12)` computed from `math.log(0.20, _LOG_BASE)` — pins subset-aware aggregate against hand-computed values |
| `test_aggregate_matches_on_disk_scalars` | Keep | `assert tbl.aggregate.raw_baseline_scalar == pytest.approx(ref.raw_scalar_full, abs=1e-12)` — exercises full-20 aggregate computation with precise numeric pin |
| `test_all_rows_are_always_length_20` | Keep | `assert len(tbl.rows) == 20` — exercises fixed-length invariant |
| `test_contains_header_and_columns` | Keep | `assert "| file | raw_baseline | ground_truth | **model** | gain vs raw | headroom vs gt | Impact | Weight % |" in md` — pins rendered column header exact format |
| `test_custom_base_and_offset_kwargs` | Keep | `assert out_base_e[0] == pytest.approx(math.log(1.0 + 1e-10, math.e), rel=1e-12)` — exercises configurable base and offset parameters |
| `test_impact_ranking_invariant_under_input_permutation` | Keep | `for a, b in zip(impacts_a, impacts_b, strict=True): assert a == pytest.approx(b, abs=1e-12)` — permutation invariant proves impact is per-pair not positional |
| `test_impact_strictly_positive_when_model_below_gt` | Keep | `assert r.impact_score > 0.0` for model below gt — exercises positive impact |
| `test_impact_zero_iff_model_at_or_above_gt` | Keep | `assert r.impact_score == pytest.approx(0.0, abs=1e-12)` for model at/above ceiling — exercises max(0, ...) clipping |
| `test_length_preserved` | Keep | `assert len(out) == len(fv)` for mixed list — exercises length invariant |
| `test_na_cell_rendered_for_unsampled_files` | Keep | `assert row0.count("N/A") == 5` and `assert "N/A" not in row4` — exercises N/A cell rendering for unsampled vs sampled files |
| `test_negative_input_clamped_then_offset_applied` | Keep | `assert out[0] == pytest.approx(floor, rel=1e-12)` for negative inputs — exercises clamp-then-offset defensive handling |
| `test_negative_values_use_unicode_minus` | Keep | `assert "\u221213.8540" in row0` — pins U+2212 unicode minus usage for negative values |
| `test_none_passes_through_for_unsampled_files` | Keep | `assert out[1] is None` and `assert out[3] is None` for None input positions — exercises None passthrough |
| `test_post_path_a_reference_consistency` | Keep | uses `pytest.skip` when data file absent; when present `assert per_file["score"] == pytest.approx(expected_log, rel=1e-9)` — load-bearing regression test for production formula alignment; gracefully skips in CI |
| `test_rejects_all_none_fv_with_non_none_scalar` | Keep | `with pytest.raises(ValueError, match="inconsistent")` — exercises inconsistency validation |
| `test_rejects_wrong_length_fv` | Keep | `with pytest.raises(ValueError, match="length 20")` for 19-element fv — exercises length validation |
| `test_rendered_markdown_attached` | Keep | `assert tbl.rendered_markdown.startswith("### Per-file performance")` — exercises that rendered_markdown is populated |
| `test_renders_exactly_20_body_rows` | Keep | `assert len(main_body) == 20` after filtering secondary block — exercises 20-row invariant in markdown |
| `test_returns_none_when_model_scalar_is_none` | Keep | `assert build_score_table([1.0]*20, model_scalar=None, reference=ref) is None` — exercises degenerate-input guard |
| `test_rows_are_fully_populated` | Keep | `assert row.gain_vs_raw == pytest.approx(model_fv[i] - ref.raw_per_file_log[i])` and `assert row.headroom_vs_gt == pytest.approx(max(..., 0.0))` — exercises per-row column computations |
| `test_secondary_block_omitted_when_no_impact_data` | Keep | `assert "### Sampled files re-ranked by Impact_Score" not in md` when rows have no impact data — exercises conditional omission |
| `test_secondary_block_sorted_by_impact_desc` | Keep | `assert impacts_in_render_order == sorted(impacts_in_render_order, reverse=True)` and file order matches sorted tbl.rows — exercises secondary block rendering order |
| `test_subset_footer_only_appears_when_n_lt_20` | Keep | `assert "scalars computed over" not in full_tbl.rendered_markdown` and `assert "_Note: scalars computed over 3 sampled files._" in sub_tbl.rendered_markdown` — exercises subset footer conditional rendering |
| `test_typical_linear_values_map_correctly` | Keep | `assert out == pytest.approx(expected, rel=1e-12)` where `expected = [math.log(v + _LOG_OFFSET, _LOG_BASE) for v in fv_lin]` — exercises log-space conversion formula |
| `test_unsampled_rows_carry_none_for_model_columns` | Keep | `assert tbl.rows[17].model is None` and `assert tbl.rows[17].raw_baseline is not None` — exercises None-propagation for unsampled files with reference columns still populated |
| `test_weights_sum_to_one_full_subset` | Keep | `assert sum(weights) == pytest.approx(1.0, abs=1e-9)` and `assert tbl.linear_weight_total == pytest.approx(1.0, abs=1e-9)` — pins linear weight normalization invariant |
| `test_weights_sum_to_one_trial_subset` | Keep | `assert sum(r.linear_weight for r in sampled) == pytest.approx(1.0, abs=1e-9)` and `assert all(r.impact_score is None for r in unsampled)` — exercises subset-scoped weight sum |
| `test_zero_maps_to_soft_floor` | Keep | `assert out[0] == pytest.approx(-13.854049, abs=1e-4)` and `assert math.isfinite(out[0])` — pins soft-floor value for zero input |

### `tests/unit/execute_tools/test_scoring_utils.py`

Tests: 17

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_custom_threshold_forwarded` | Keep | `assert is_degen_default is False` and `assert is_degen_custom is True` for 25× reference with 1% vs 5% threshold — threshold parameter forwarding |
| `test_empty_sample_set` | Keep | `assert all(v is None for v in vector)` and `assert scalar == float("-inf")` — empty sample set returns -inf scalar |
| `test_empty_segments_returns_nan` | Keep | `assert math.isnan(result)` for `segment_indices=[]` — empty segment edge case |
| `test_excluded_files_are_none` | Keep | `assert vector[6] is not None and not math.isnan(vector[6])` and `for i in range(NUM_FILES): if i != 6: assert vector[i] is None` — files not in sample_set are None |
| `test_high_anchor_produces_higher_score` | Keep | `assert high > low` comparing file 19 seg 199 vs file 0 seg 0 with same mocked SNR — verifies weight scaling monotonicity |
| `test_legacy_mode_derives_s_max_globally_from_collected_pairs` | Keep | `expected = math.log(2.0, 5.27)` then `assert abs(scalar_legacy - expected) < 1e-12` — legacy mode s_max derivation logic |
| `test_multiple_files_grand_mean` | Keep | `grand_mean = (vector[0] + vector[19]) / 2.0; expected = math.log(grand_mean, 5.27)` then `assert abs(scalar - expected) < 1e-12` — grand mean is not mean-of-file-means |
| `test_multiple_segments_averaged` | Keep | `expected = (w0 + w9) / 2.0` then `assert abs(result - expected) < 1e-10` — multi-segment mean computation |
| `test_no_reference_returns_false_none` | Keep | `assert is_degen is False` and `assert reason is None` — reference=None skips health check |
| `test_normal_mode_single_file` | Keep | `assert len(present) == 1` and `assert vector[6] is not None` — normal mode single file scoring |
| `test_raises_without_filename_fn` | Keep | `with pytest.raises(ValueError, match="denoised_filename_fn is required")` — explicit error for missing fn |
| `test_raises_without_s_max_in_non_legacy_mode` | Keep | `with pytest.raises(ValueError, match="Non-legacy mode requires s_max")` — explicit error for missing s_max |
| `test_reference_with_collapse_trips_check` | Keep | `reference_huge[6] = 10000.0` then `assert is_degen is True` and `assert "amplitude_collapse" in reason` — large reference triggers collapse |
| `test_reference_with_normal_output_passes` | Keep | uses same vector as reference then `assert is_degen is False` and `assert reason is None` — parity reference passes |
| `test_scalar_is_log_of_grand_mean` | Keep | `expected = math.log(vector[6], 5.27)` then `assert abs(scalar - expected) < 1e-12` — pins exact log base-5.27 formula with no quantization |
| `test_single_segment` | Keep | `assert abs(result - expected) < 1e-10` where `expected = 2.0 * (1.0 / 4000.0)` — arithmetic of weighted SNR with predictable anchor map |
| `test_vector_length_is_20` | Keep | `assert len(vector) == NUM_FILES` — score_vector always returns 20-element vector |

### `tests/unit/execute_tools/test_squid_health_checks.py`

Tests: 12

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_collapse_detected_at_explore_v7_magnitude` | Keep | `file_vec = [0.005] * 20; ref_vec = [8.6] * 20; is_degen, reason = check_amplitude_collapse(file_vec, ref_vec); assert is_degen is True; assert "0.005" in reason; assert "8.6" in reason; assert "amplitude_collapse" in reason` — exact real-world collapse magnitudes from live run |
| `test_custom_threshold_overrides_default` | Keep | `is_degen, reason = check_amplitude_collapse(file_vec, ref_vec, threshold_ratio=0.05); assert is_degen is True; assert "5%" in reason` — custom threshold + reason includes threshold |
| `test_empty_reference_returns_false_safely` | Keep | `is_degen, reason = check_amplitude_collapse([0.005], []); assert is_degen is False` |
| `test_failure_reason_includes_actual_and_reference_magnitudes` | Keep | `is_degen, reason = check_amplitude_collapse([0.123], [45.6]); assert "0.123" in reason; assert "45.6" in reason` — magnitudes in reason string |
| `test_failure_reason_includes_ratio_and_threshold` | Keep | `assert "0.500%" in reason or "0.5%" in reason; assert "1%" in reason` — ratio and threshold in reason |
| `test_no_file_vector_returns_false_safely` | Keep | `is_degen, reason = check_amplitude_collapse(None, [8.6]); assert is_degen is False` |
| `test_no_reference_returns_false_safely` | Keep | `is_degen, reason = check_amplitude_collapse([0.005], None); assert is_degen is False; assert reason is None` — missing reference → safe pass |
| `test_none_entries_in_vectors_are_skipped` | Keep | `file_vec = [7.2, None, 7.2, None, 7.2]; ref_vec = [8.6, 8.6, 8.6, 8.6, 8.6]; is_degen, _ = check_amplitude_collapse(file_vec, ref_vec); assert is_degen is False` — None entries skipped, not treated as zero |
| `test_normal_output_passes_through` | Keep | `file_vec = [7.2] * 20; ref_vec = [8.6] * 20; is_degen, reason = check_amplitude_collapse(...); assert is_degen is False; assert reason is None` — healthy output |
| `test_threshold_boundary_exactly_at_1pct_does_not_trip` | Keep | `is_degen, _ = check_amplitude_collapse([1.0], [100.0], threshold_ratio=0.01); assert is_degen is False` — strict < semantics at boundary |
| `test_threshold_just_below_trips` | Keep | `is_degen, reason = check_amplitude_collapse([0.99], [100.0], threshold_ratio=0.01); assert is_degen is True` — just below boundary |
| `test_zero_reference_magnitude_returns_false_safely` | Keep | `is_degen, reason = check_amplitude_collapse([0.005], [0.0, 0.0]); assert is_degen is False` — divide-by-zero avoided |

### `tests/unit/execute_tools/test_train_sentinel.py`

Tests: 4

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_sentinel_name_uses_exact_exp_id` | Keep | `assert (tmp_path / f"_OK_{weird_exp_id}").exists()` — no slugging/hashing |
| `test_sentinel_not_written_when_save_raises` | Keep | `fake_save` raises RuntimeError, then `assert not sentinel.exists()` — atomicity: no orphan sentinel |
| `test_sentinel_path_is_sibling_of_save_path` | Keep | `assert (cached_dir / "_OK_exp_xyz").exists()` and `assert not (tmp_path / "_OK_exp_xyz").exists()` — exact path convention |
| `test_sentinel_written_on_successful_save` | Keep | `monkeypatch.setattr(tes.torch, "save", fake_save)` (stubs torch dependency only), then `assert sentinel.exists()` and `assert sentinel.stat().st_size == 0` — tests atomicity of the write-sentinel logic |

### `tests/unit/guardrails/test_no_hardcoded_device_literals.py`

Tests: 1

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_no_hardcoded_device_literals` | Keep | `assert not all_violations` after scanning `core/`, `agent/`, `nodes/` directories with `_DEVICE_TOKEN_PATTERN` and docstring/provenance allowlisting — mechanical enforcement of Principle 5 that requires reading actual source files |

### `tests/unit/guardrails/test_no_model_name_branches.py`

Tests: 1

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_no_model_name_branches` | Keep | `assert not all_violations` with `pytest.xfail(...)` for pending-cleanup files — exercises a real grep-based lint scan over production source files; catches Principle 2 regression that static analysis does not |

### `tests/unit/ml_models/test_loss_functions.py`

Tests: 12

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_ce_computes_on_synthetic_data` | Keep | `assert loss.item() >= 0.0` — exercises CE forward pass on real tensor |
| `test_ce_returns_cross_entropy` | Keep | `assert isinstance(criterion, torch.nn.CrossEntropyLoss)` — exercises factory dispatch for "ce" |
| `test_focal_cw_returns_focal_cw_loss` | Keep | `assert isinstance(criterion, FocalLoss1DCW)` — exercises factory dispatch for "focal_cw" |
| `test_focal_returns_focal_loss` | Keep | `assert isinstance(criterion, FocalLoss1D)` — exercises factory dispatch for "focal" |
| `test_none_class_weights_falls_back_gracefully` | Keep | `assert loss.shape == torch.Size([])` when `class_weights=None` — exercises None fallback path |
| `test_output_is_non_negative` | Keep | Asserts `loss.item() >= 0.0` on real FocalLoss1D — pure non-negativity check on real loss output, no mocks |
| `test_output_is_scalar` | Keep | Asserts `loss.shape == torch.Size([])` on real FocalLoss1D applied to real tensors — pure tensor shape check, no mocks |
| `test_perfect_prediction_lower_than_random` | Keep | `assert loss_perfect < loss_random` — exercises that near-perfect logits produce lower focal loss than random; real ML property |
| `test_reduction_sum_larger_than_mean` | Keep | `assert loss_sum(...) > loss_mean(...)` — exercises that sum reduction is larger than mean; real computation |
| `test_smooth_l1_computes_on_synthetic_data` | Keep | `assert loss.item() >= 0.0` — exercises SmoothL1 forward pass on real tensor |
| `test_smooth_l1_returns_smooth_l1_loss` | Keep | `assert isinstance(criterion, torch.nn.SmoothL1Loss)` — exercises factory dispatch for "smooth_l1" |
| `test_unknown_loss_type_raises` | Keep | `with pytest.raises(ValueError, match="Unknown loss_type")` after `cfg.loss_type = "unknown"` — exercises unknown-type guard in factory |

### `tests/unit/ml_models/test_model_configs.py`

Tests: 34

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_ce_nullifies_focal_params` | Keep | `assert cfg.alpha is None` and `assert cfg.gamma is None` and `assert cfg.beta is None` — tests CE nullification |
| `test_dropout_ignored_for_single_layer` | Keep | `cfg = RNNSeq2SeqConfig(num_layers=1, dropout=0.3)` then `assert cfg.dropout == 0.3` — documents and tests that dropout=0.3 with num_layers=1 is valid |
| `test_embedding_dim_divisible_by_nhead_passes` | Keep | `cfg = TransformerConfig(embedding_dim=32, nhead=4)` then `assert cfg.embedding_dim == 32` — tests boundary: 32/4=8 is valid |
| `test_embedding_dim_not_divisible_by_nhead_raises` | Keep | `with pytest.raises(ValidationError): TransformerConfig(embedding_dim=33, nhead=4)` — tests cross-field divisibility validator |
| `test_even_gate_channels_passes` | Keep | `cfg = WaveNetConfig(gate_channels=32)` then `assert cfg.gate_channels == 32` — tests boundary for gate_channels |
| `test_even_kernel_size_raises` | Keep | `with pytest.raises(ValidationError, match="odd"): PUNetConfig(kernel_size=8)` — tests custom validator that requires odd kernel_size |
| `test_fcnet_with_ce_passes` | Keep | cross-validation: fcnet+ce is valid |
| `test_fcnet_with_smooth_l1_passes` | Keep | `cfg = ExperimentConfig(**_make_experiment("fcnet", "smooth_l1"))` — cross-validation: fcnet+smooth_l1 is valid |
| `test_focal_cw_valid` | Keep | `cfg = LossConfig(loss_type="focal_cw", gamma=4.0)` then `assert cfg.loss_type == "focal_cw"` — tests valid focal_cw type |
| `test_focal_nullifies_beta` | Keep | `cfg = LossConfig(loss_type="focal", alpha=0.25, gamma=2.0, beta=5.0)` then `assert cfg.beta is None` — tests model_validator nullification logic |
| `test_hidden_dim_out_of_range_raises` | Keep | `with pytest.raises(ValidationError): RNNSeq2SeqConfig(hidden_dim=2000)` — tests upper bound on hidden_dim |
| `test_negative_latent_dim_raises` | Keep | `with pytest.raises(ValidationError, match="positive"): AEConfig(latent_dims=[-1])` — tests that negative values are rejected |
| `test_num_gates_below_min_raises` | Keep | `with pytest.raises(ValidationError): GatedFNOConfig(num_gates=4)` — tests minimum num_gates constraint |
| `test_num_layers_below_min_raises` | Keep | `with pytest.raises(ValidationError): GatedFNOConfig(num_layers=0)` — tests minimum num_layers constraint |
| `test_odd_gate_channels_raises` | Keep | `with pytest.raises(ValidationError, match="even"): WaveNetConfig(gate_channels=33)` — tests even-number constraint on gate_channels |
| `test_punet_with_ce_passes` | Keep | `cfg = ExperimentConfig(**_make_experiment("punet", "ce"))` — cross-validation: punet+ce is valid |
| `test_punet_with_focal_passes` | Keep | `cfg = ExperimentConfig(**_make_experiment("punet", "focal"))` then `assert cfg.model_type == "punet"` — cross-validation: punet+focal is valid |
| `test_punet_with_smooth_l1_raises` | Keep | `with pytest.raises(ValidationError, match="smooth_l1"): ExperimentConfig(**_make_experiment("punet", "smooth_l1"))` — cross-validation: punet+smooth_l1 is invalid |
| `test_rnn_with_ce_passes` | Keep | cross-validation: rnn+ce is valid |
| `test_rnn_with_smooth_l1_raises` | Keep | `with pytest.raises(ValidationError, match="smooth_l1")` — cross-validation rejection |
| `test_segmentation_size_at_boundary_passes` | Keep | `cfg = PUNetConfig(segmentation_size=1000, depth=3)` then `assert cfg.segmentation_size == 1000` — tests boundary value passes for depth=3 |
| `test_segmentation_size_too_small_for_depth_raises` | Keep | `with pytest.raises(ValidationError): PUNetConfig(segmentation_size=100, depth=4)` — tests cross-field validator: segmentation_size must be large enough for depth |
| `test_smooth_l1_nullifies_alpha_and_gamma` | Keep | `assert cfg.alpha is None` and `assert cfg.gamma is None` and `assert cfg.use_class_weights is False` — tests smooth_l1 nullification of focal params |
| `test_static_v_length_mismatch_raises` | Keep | `with pytest.raises(ValidationError, match="static_v length"): GatedFNOConfig(num_gates=64, static_v=[0.5]*32)` — tests cross-field length validator for static_v |
| `test_transformer_with_ce_passes` | Keep | cross-validation: transformer+ce is valid |
| `test_transformer_with_smooth_l1_raises` | Keep | `with pytest.raises(ValidationError, match="smooth_l1")` — cross-validation rejection |
| `test_valid_custom` | Keep | `cfg = PUNetConfig(segmentation_size=10000, depth=3, multi=32, kernel_size=7)` then assertions — tests custom construction with non-default values |
| `test_valid_custom_dims` | Keep | `cfg = AEConfig(latent_dims=[500, 50], segmentation_size=1000)` — tests custom latent_dims construction |
| `test_valid_default` | Keep | `cfg = PUNetConfig()` then `assert cfg.model_type == "punet"` and `assert cfg.kernel_size == 9` — tests default field values of real Pydantic config |
| `test_valid_with_static_v` | Keep | `v = [0.5] * 64; cfg = GatedFNOConfig(num_gates=64, static_v=v)` — tests optional static_v with matching length |
| `test_wavenet_with_ce_passes` | Keep | cross-validation: wavenet+ce is valid |
| `test_wavenet_with_smooth_l1_raises` | Keep | `with pytest.raises(ValidationError, match="smooth_l1")` — cross-validation rejection |
| `test_width_below_min_raises` | Keep | `with pytest.raises(ValidationError): GatedFNOConfig(width=8)` — tests minimum width constraint |
| `test_zero_latent_dim_raises` | Keep | `with pytest.raises(ValidationError, match="positive"): AEConfig(latent_dims=[500, 0, 50])` — tests that zero values are rejected in latent_dims |

### `tests/unit/ml_models/test_model_descriptions.py`

Tests: 7

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_chain_lookup_is_noop_when_env_var_unset` | Keep | `monkeypatch.delenv("SIDERIUS_CHAIN_WORKSPACE", raising=False)` then `assert model_descriptions._chain_workspace_candidates("anything") == []` — tests that absent env var returns empty candidates |
| `test_chain_lookup_skips_run_dir_without_matching_model` | Keep | `assert model_descriptions._chain_workspace_candidates("missing_model") == []` — tests robustness: a subdir without the matching model's description.md must not produce a candidate |
| `test_finds_builtin_model_description` | Keep | `text = model_descriptions.get_model_description("punet")` then `assert text.strip()` — tests that the built-in punet description file is found and non-empty |
| `test_finds_chain_plugin_with_iter_dirname` | Keep | `assert model_descriptions.get_model_description("spectral_skip_cyclic_tcn") == body` — tests the production `iter_NNN` naming still works |
| `test_finds_chain_plugin_with_run_scoped_dirname` | Keep | `_write_plugin_description(chain_workspace, "stage2_iter_001", ...)` then `assert model_descriptions.get_model_description("positional_gated_tcn") == body` — regression guard for Gate 2 Run-4 bug: `stage2_iter_001` dirname was rejected by old regex |
| `test_missing_model_raises_with_searched_paths` | Keep | `with pytest.raises(FileNotFoundError) as exc:` then `assert "nonexistent_arch_xyz" in msg` and `assert "Searched" in msg` — tests error message quality: must name the model and list searched paths |
| `test_newest_run_wins_when_model_registered_in_multiple_runs` | Keep | `assert model_descriptions.get_model_description("shared_model") == "new description\n"` — tests that highest-sorted dirname wins when model appears in multiple runs |

### `tests/unit/ml_models/test_models_forward.py`

Tests: 16

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_custom_latent_dims` | Keep | `cfg = AEConfig(..., latent_dims=[500, 100, 10]); assert out.shape == (BATCH, 256, SEG_SIZE)` — tests flexible architecture |
| `test_deeper_layers` | Keep | `model = self._make_model(num_layers=2, hidden_dim=32); assert out.shape == (BATCH, 256, SEG_SIZE)` |
| `test_deeper_model` | Keep | `model = self._make_model(num_layers=3, width=32); assert out.shape == (BATCH, 256, SEG_SIZE)` |
| `test_more_blocks` | Keep | `model = self._make_model(num_blocks=5); assert out.shape == (BATCH, 256, SEG_SIZE)` |
| `test_no_nan_in_output` | Keep | `assert not torch.isnan(out).any()` for PositionalUNet — catches numerical issues |
| `test_output_is_float` | Keep | `assert out.dtype == torch.float32` for PositionalUNet |
| `test_output_shape` | Keep | `assert out.shape == (BATCH, 256, SEG_SIZE)` for PositionalUNet — real forward pass on CPU; no mocks |
| `test_output_shape_classification` | Keep | `assert out.shape == (BATCH, 256, SEG_SIZE)` for AE CE mode |
| `test_output_shape_deeper` | Keep | `model = self._make_model(num_layers=4); assert out.shape == (BATCH, 256, SEG_SIZE)` |
| `test_output_shape_depth_2` | Keep | `model = self._make_model(depth=2); assert out.shape == (BATCH, 256, SEG_SIZE)` — tests non-default depth |
| `test_output_shape_depth_3` | Keep | `model = self._make_model(depth=3); assert out.shape == (BATCH, 256, SEG_SIZE)` — tests deeper architecture |
| `test_output_shape_narrow` | Keep | `model = self._make_model(width=16, num_layers=1); assert out.shape == (BATCH, 256, SEG_SIZE)` |
| `test_output_shape_regression` | Keep | `assert out.shape == (BATCH, SEG_SIZE)` for AE smooth_l1 mode — different output shape |
| `test_registry_contains_all_builtin_models` | Keep | `assert expected.issubset(set(MODEL_REGISTRY.keys()))` — pins that all 6 built-in models are registered |
| `test_registry_maps_to_correct_classes` | Keep | `assert MODEL_REGISTRY["punet"] is PositionalUNet` — tests identity of each registry entry |
| `test_with_static_v` | Keep | `model = self._make_model(num_gates=32, static_v=v); assert out.shape == (BATCH, 256, SEG_SIZE)` — tests static_v parameter path |

### `tests/unit/ml_models/test_plugin_loader.py`

Tests: 22

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_bare_module_identity_never_created` | Keep | `result = subprocess.run([sys.executable, "-c", _NO_BARE_IDENTITY_SCRIPT, ...])` then `assert result.returncode == 0` — runs in a subprocess to test the import invariant in isolation; the assertion is that the bare `models_format_sandbox` module identity is never created |
| `test_config_instantiates` | Keep | `cfg = ConfigClass(segmentation_size=1000)` then `assert cfg.segmentation_size == 1000` — tests that the loaded config class is actually instantiable |
| `test_empty_entries_filtered` | Keep | `assert _resolve_plugin_dirs() == ["/tmp/dir_a", "/tmp/dir_b"]` — tests that empty segments from leading/trailing/duplicate separators are filtered |
| `test_empty_env_falls_back_to_agent_generated_dir` | Keep | `monkeypatch.setenv(_PLUGIN_DIRS_ENV_VAR, "")` then `assert _resolve_plugin_dirs() == [pl.AGENT_GENERATED_DIR]` — tests empty and whitespace env var fall back |
| `test_env_unset_falls_back_to_agent_generated_dir` | Keep | `assert _resolve_plugin_dirs() == [pl.AGENT_GENERATED_DIR]` — tests fallback behavior when env var is unset |
| `test_env_var_overrides_legacy_dir` | Keep | `assert "run_plugin" in loaded` and `assert "legacy_plugin" not in loaded` — tests that env var overrides AGENT_GENERATED_DIR |
| `test_forward_no_nan` | Keep | `assert not torch.isnan(out).any()` — tests output has no NaN values |
| `test_forward_output_is_float` | Keep | `assert out.dtype == torch.float32` — tests output dtype contract |
| `test_forward_output_shape_matches_core_contract` | Keep | `out = model(x)` then `assert out.shape == (batch, 256, seg_size)` — tests the `[B, T] int → [B, 256, T] float` forward contract |
| `test_missing_config_class_returns_none` | Keep | `assert _load_plugin(str(p)) is None` — tests that plugin missing `PLUGIN_CONFIG_CLASS` returns None |
| `test_missing_directory_returns_empty` | Keep | `assert loaded == []` and `assert model_reg == {}` — tests that a nonexistent plugin dir returns empty lists without raising |
| `test_missing_env_dir_silently_skipped` | Keep | `assert loaded == ["real_plugin"]` — tests that a nonexistent dir in the env var is silently skipped |
| `test_missing_legacy_dir_ok_when_env_set` | Keep | `assert loaded == ["run_only_plugin"]` — tests that AGENT_GENERATED_DIR not existing does not break the env-var path |
| `test_missing_model_type_returns_none` | Keep | `assert _load_plugin(str(p)) is None` — tests that plugin missing `PLUGIN_MODEL_TYPE` returns None gracefully |
| `test_model_instantiates` | Keep | `model = ModelClass(cfg)` then `assert isinstance(model, torch.nn.Module)` — tests that the loaded model class is instantiable and is an nn.Module |
| `test_multiple_dirs_preserve_order` | Keep | `assert _resolve_plugin_dirs() == ["/tmp/dir_a", "/tmp/dir_b", "/tmp/dir_c"]` — tests that colon-separated dirs preserve order |
| `test_plugin_added_to_both_registries` | Keep | `assert "test_plugin_model" in model_reg` and `assert "test_plugin_model" in config_reg` — tests that `extend_registries` adds the plugin to both model and config registries |
| `test_single_dir` | Keep | `monkeypatch.setenv(_PLUGIN_DIRS_ENV_VAR, "/tmp/dir_a")` then `assert _resolve_plugin_dirs() == ["/tmp/dir_a"]` — tests single-dir env var |
| `test_syntax_error_returns_none` | Keep | `p.write_text("def (: pass\n")` then `assert _load_plugin(str(p)) is None` — tests that syntax error returns None without raising |
| `test_two_dirs_both_loaded` | Keep | `assert "plugin_a" in loaded and "plugin_b" in loaded` — tests that plugins from both dirs in a multi-dir env var are loaded |
| `test_underscore_files_are_skipped` | Keep | `assert loaded == []` — tests that files starting with underscore (e.g. `__init__.py`, `_private.py`) are skipped |
| `test_valid_plugin_returns_dict` | Keep | `result = _load_plugin(plugin_file)` then `assert result["model_type"] == "test_plugin_model"` — tests real `_load_plugin` with a valid plugin file |

### `tests/unit/nodes/test_scoring_reference.py`

Tests: 11

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_cache_reset_restores_fresh_load` | Keep | `pytest.raises(FileNotFoundError)` after `_reset_cache()` and removing file 0 — cache invalidation |
| `test_cache_returns_same_object` | Keep | `assert second is first` (identity) after removing file 0 — cache correctness |
| `test_legacy_gt_per_file_without_n_segments_raises` | Keep | `pytest.raises(KeyError, match="n_segments")` with legacy JSON |
| `test_legacy_raw_per_file_without_linear_sum_raises` | Keep | `pytest.raises(KeyError, match="linear_sum")` with legacy JSON lacking `linear_sum` |
| `test_missing_gt_per_file_raises` | Keep | `pytest.raises(FileNotFoundError, match="ground_truth_score_file_0011")` |
| `test_missing_gt_scalar_raises` | Keep | `pytest.raises(FileNotFoundError, match=_GT_SCALAR_FILE)` |
| `test_missing_raw_per_file_raises` | Keep | `pytest.raises(FileNotFoundError, match="raw_baseline_score_file_0007")` after removing file 7 |
| `test_missing_raw_scalar_raises` | Keep | `pytest.raises(FileNotFoundError, match=_RAW_SCALAR_FILE)` |
| `test_returns_reference_scores_with_correct_shapes` | Keep | `assert len(ref.raw_per_file_log) == 20` and `assert ref.s_max == pytest.approx(295715680.14)` — shape and value contract |
| `test_smax_mismatch_raises` | Keep | `pytest.raises(ValueError, match="s_max mismatch")` with `raw_smax=1.0, gt_smax=2.0` |
| `test_values_align_with_index` | Keep | `assert ref.raw_per_file_log[i] == pytest.approx(1.0 * i)` for all 20 indices — index alignment |

### `tests/unit/scripts/test_chain_consistency.py`

Tests: 14

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_budget_variables_present` | Keep | checks that `TRIAL_TIME_BUDGET_MINUTES`, `FORMAL_TIME_BUDGET_MINUTES`, `TRIAL_VRAM_BUDGET_GB`, `FORMAL_VRAM_BUDGET_GB` all have defaults in the shell file — guards against missing budget variable declarations |
| `test_build_app_args_uses_start_iteration` | Keep | `assert "--start_iteration" in content` — verifies shell uses `--start_iteration` not the deprecated `--iteration` |
| `test_data_dir_present` | Keep | `assert "DATA_DIR=" in content` — verifies DATA_DIR variable is present in shell file |
| `test_exploration_mode_default` | Keep | `assert re.search(r'^EXPLORATION_MODE="auto"', content, re.MULTILINE)` — reads shell file, checks default for EXPLORATION_MODE |
| `test_lilab_dry_run_leaves_workspace_untouched` | Keep | `assert not workspace.exists()` after dry-run — tests side-effect-free contract: dry-run must not create any filesystem artifacts |
| `test_lilab_three_iters_emits_correct_start_iteration` | Keep | `rc, stdout, stderr = _run_dry("lilab", workspace, 3, seed_path)` then `assert rc == 0` and `assert marker in stdout` for n in (1,2,3) — runs real shell script in dry-run mode; tests that 3 iterations emit correct `--start_iteration N` markers |
| `test_max_rounds_default` | Keep | `assert re.search(r"^MAX_ROUNDS=3\b", content, re.MULTILINE)` — reads real `_chain_common.sh` file and checks default value; static analysis cannot verify shell file content |
| `test_minimum_boldness_default` | Keep | `assert re.search(r'^MINIMUM_BOLDNESS="0\.05"', content, re.MULTILINE)` — reads shell file, checks default |
| `test_sdsc_dry_run_leaves_workspace_untouched` | Keep | `assert not workspace.exists()` after sdsc dry-run — mirrors lilab test for sdsc mode |
| `test_sdsc_emits_afterany_dependency_for_iter_two_and_three` | Keep | `assert "--dependency=afterany:DRYRUN_iter_001" in stdout` and `assert "--dependency=afterany:DRYRUN_iter_002" in stdout` and `assert "--dependency" not in first_submit` — tests SDSC Slurm dependency chaining in dry-run output |
| `test_shell_arms_exist_for_every_contract_flag` | Keep | `missing = [f for f in CONTRACT_FLAGS if f not in shell_arms]` then `assert not missing` — parses real shell case arms and checks every §3.2 contract flag has an arm |
| `test_shell_default_block_contains_every_var` | Keep | `missing = [f for f in CONTRACT_FLAGS if _shell_var_name(f) not in shell_defaults]` then `assert not missing` — checks all contract flags have top-of-file default declarations in shell |
| `test_shell_python_default_parity` | Keep | `assert not diffs` where diffs contain per-flag `python_default` vs `shell_norm` mismatches — tests default-value parity across Python argparse and shell defaults for all CONTRACT_FLAGS |
| `test_shell_python_type_parity` | Keep | `assert not diffs` where diffs show `python_shape` vs `shell_shape` for each flag — tests that shell handler shape (scalar/boolean/list) matches Python argparse action type |

### `tests/unit/scripts/test_chain_run_id_sidecar.py`

Tests: 6

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_distinct_run_names_in_distinct_workspaces_produce_distinct_ids` | Keep | `assert rid_a.startswith("explore_alpha-")` and `assert rid_a != rid_b` |
| `test_empty_sidecar_is_treated_as_missing` | Keep | Whitespace-only sidecar then `assert _ID_SHAPE.match(rid)` and sidecar content check — edge case |
| `test_fresh_workspace_generates_id_with_expected_shape` | Keep | `assert _ID_SHAPE.match(rid)` and `assert rid.startswith(f"{run_name}-")` and `open(sidecar).read().strip() == rid` — real file I/O and format contract |
| `test_run_name_in_subsequent_call_is_ignored` | Keep | `assert first == second` and `assert second.startswith("explore_v12_test-")` — sidecar wins over argument |
| `test_second_call_returns_same_id` | Keep | `assert first == second` — idempotency contract |
| `test_workspace_is_created_if_missing` | Keep | `assert not os.path.exists(workspace)` before, then `assert os.path.isdir(workspace)` after — mkdirs behavior |

### `tests/unit/scripts/test_chain_wrapper_run_name.py`

Tests: 3

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_run_name_distinct_from_workspace_basename` | Keep | `assert "operator_chose_beta" in after` where `after = out[rn_idx : rn_idx + 200]` and workspace is `ws_named_alpha` — pins that run_name is not silently derived from workspace basename |
| `test_run_name_required_when_missing` | Keep | `assert proc.returncode != 0` and `assert "run_name" in proc.stderr` — executes `run_chain.sh --dry-run` with no `--run_name` arg and verifies non-zero exit |
| `test_run_name_threads_through_to_runner_args` | Keep | `assert "--run_name" in out` and `assert "my_chain_v99_test" in out` after real subprocess execution — verifies flag and value appear in dry-run output |

### `tests/unit/scripts/test_inspect_run_state.py`

Tests: 14

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_1_chain_three_clean_iters_next_iter_prints_4` | Keep | `assert stdout.strip() == "4"` and `assert stdout.strip().isdigit()` — real chain-walking and output formatting |
| `test_2_chain_two_clean_one_missing_manifest_next_iter_prints_3` | Keep | `assert stdout.strip() == "3"` — missing-manifest handling |
| `test_3_chain_one_clean_one_failed_manifest_next_iter_prints_2` | Keep | `assert stdout.strip() == "2"` — failed-manifest handling |
| `test_4_chain_one_clean_one_malformed_json_next_iter_prints_2` | Keep | `assert stdout.strip() == "2"` — malformed JSON recovery |
| `test_5_chain_empty_workspace_next_iter_prints_1` | Keep | `assert stdout.strip() == "1"` — empty workspace starts at iter 1 |
| `test_6_chain_non_contiguous_gap_exits_nonzero` | Keep | `assert rc != 0` and `assert "iter_002" in stderr` and `assert "non-contiguous" in stderr` and `assert stdout == ""` |
| `test_7_chain_legacy_layout_guard_rejects` | Keep | Writes `workflow_old_run.json` then `assert rc != 0` and `assert "Legacy workspace layout" in stderr` |
| `test_8_run_layout_back_compat_renders_table` | Keep | `assert "COMMITTED" in stdout` and column headers present — human-readable table |
| `test_9_default_layout_resolves_to_run` | Keep | `assert "Last committed iteration:" in stdout` and `assert "COMMITTED" in stdout` — default mode back-compat |
| `test_chain_dangling_warning_in_human_view` | Keep | `assert "dangling" in stderr.lower()` and `assert "iter_002" in stderr` — warning logic |
| `test_chain_human_view_includes_model_and_best_score` | Keep | `assert "posenc_causal_dilated_stack" in stdout` and `assert "-3.221148" in stdout` and `assert "Last committed iter: iter_002" in stdout` |
| `test_chain_invalid_arg_combinations_rejected` | Keep | `pytest.raises(SystemExit)` for three invalid arg combinations — argparse validation |
| `test_chain_no_dangling_warning_when_partial_is_at_top` | Keep | `assert stdout.strip() == "3"` and `assert "dangling" not in stderr.lower()` — partial at top is not dangling |
| `test_chain_partial_below_committed_advances_past_max_committed` | Keep | `assert stdout.strip() == "6"` for [1c,2c,3c,4-failed,5c] — advance past max committed |

### `tests/unit/scripts/test_portion_floor.py`

Tests: 9

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_floor_accepts_exactly_one_pct` | Keep | `assert roi_floor("0.01") == 0.01` — documented minimum |
| `test_floor_accepts_typical_values` | Keep | `assert roi_floor("0.05") == 0.05` etc — normal value acceptance |
| `test_floor_rejects_above_one` | Keep | `pytest.raises(argparse.ArgumentTypeError)` for `"1.5"` |
| `test_floor_rejects_just_below` | Keep | `pytest.raises(argparse.ArgumentTypeError)` for `"0.005"` and checks `"0.01" in msg` and segment-integrity mention |
| `test_floor_rejects_non_numeric` | Keep | `pytest.raises(argparse.ArgumentTypeError)` for `"abc"` |
| `test_floor_rejects_zero_and_negative` | Keep | Loop over `["0", "0.0", "-0.5"]` each raising `ArgumentTypeError` |
| `test_roi_argparse_rejects_subfloor_eval_portion` | Keep | Same for `"--eval_portion", "0.005"` |
| `test_roi_argparse_rejects_subfloor_trial_portion` | Keep | `parser.parse_args([..."--trial_portion", "0.005"])` then `pytest.raises(SystemExit)` with `exc.value.code == 2` — end-to-end argparse integration |
| `test_validator_name_is_portion_floor` | Keep | `assert roi_floor.__name__ == "_portion_floor"` — name contract used by chain-consistency suite |

### `tests/unit/sdsc_submission_scripts/test_consecutive_failure_brake.py`

Tests: 10

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_empty_workspace_does_not_trip_brake` | Keep | `assert result is None` for empty workspace — exercises no-history edge case |
| `test_halt_marker_absent` | Keep | `assert _check_halt_marker(str(tmp_path)) is False` — exercises absent-marker path |
| `test_halt_marker_present` | Keep | `assert _check_halt_marker(str(tmp_path)) is True` after writing `.chain_halted` — exercises present-marker detection |
| `test_malformed_manifest_treated_as_not_failed` | Keep | `assert result is None` with `{not valid json` in manifest — exercises fail-open guard #2 |
| `test_missing_manifest_treated_as_not_failed` | Keep | `assert result is None` when iter dir exists but manifest.json absent — exercises fail-open guard #1 |
| `test_mixed_statuses_do_not_trip_brake` | Keep | `assert result is None` with interleaved failed/no_records/completed — exercises non-contiguous streak non-trip |
| `test_recent_completed_breaks_failure_streak` | Keep | `assert result is None` with 2 failed + 1 completed at top — exercises streak-breaking on completed status |
| `test_recent_no_records_does_not_count_as_failure` | Keep | `assert result is None` with 3 failed + most-recent no_records — exercises no_records ≠ failure semantic |
| `test_single_failure_with_max_failed_one_trips_brake` | Keep | `assert result == [1]` with `max_failed=1` — exercises boundary: single failure triggers at max_failed=1 |
| `test_three_consecutive_failed_trips_brake` | Keep | `assert result == [3, 2, 1]` after writing 3 failed manifests — exercises streak detection with exact iter list |

### `tests/unit/sdsc_submission_scripts/test_run_one_iteration.py`

Tests: 34

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_both_flags_supplied_is_an_error` | Keep | `with pytest.raises(SystemExit): runner.normalize_args(args); assert "mutually exclusive" in err` — mutex |
| `test_both_flags_swap_both_factories_and_warn_on_stderr` | Keep | `assert kwargs["bridge_factory"] is StubLLMBridge; assert kwargs["sandbox_factory"] is StubSandbox; assert "[PSEUDO-MODE ACTIVE]" in err; assert "LLM + training" in err` |
| `test_chain_banner_omitted_for_iter_1` | Keep | `assert "[CHAIN] Restored" not in out` — no banner for iter 1 |
| `test_chain_banner_printed_when_priors_restored` | Keep | `assert "[CHAIN] Restored 1 prior plugin(s) from iters [1]" in out; assert "c8_test_arch_a" in out` — banner printed |
| `test_chain_continues_past_no_records_iter` | Keep | `mock_wf.assert_called_once(); kwargs = mock_wf.call_args.kwargs; assert kwargs["source_paths"] == [str(seed)]; assert kwargs["run_name"] == "iter_002"` — no_records iter doesn't block chain |
| `test_corrupt_prior_iter_aborts_with_clear_error` | Keep | `assert code == 1; mock_wf.assert_not_called(); assert "FAIL: restore_prior_state refused" in out` — corrupt manifest → abort with message |
| `test_default_args_pass_no_factories` | Keep | `assert kwargs["bridge_factory"] is None; assert kwargs["sandbox_factory"] is None` — default no factories |
| `test_human_advice_cli_overrides_file` | Keep | `assert normalized.human_advice_propose == "from CLI"` — CLI flag overrides file |
| `test_human_advice_file_is_loaded` | Keep | `normalized = runner.normalize_args(args); assert normalized.human_advice_interpret == "interp text"; assert normalized.human_advice_propose == "propose text"` — file loaded |
| `test_is_pseudo_llm_swaps_bridge_only` | Keep | `assert kwargs["bridge_factory"] is StubLLMBridge; assert kwargs["sandbox_factory"] is None` — only bridge factory swapped |
| `test_is_pseudo_training_swaps_sandbox_only` | Keep | `assert kwargs["bridge_factory"] is None; assert kwargs["sandbox_factory"] is StubSandbox` |
| `test_legacy_iteration_alias_still_drives_restore` | Keep | `assert code == 0; assert "c8_test_arch_a" in MODEL_REGISTRY; assert len(depr) >= 1` — deprecated alias still triggers restore |
| `test_legacy_iteration_alias_works_with_deprecation_warning` | Keep | `normalized = runner.normalize_args(args); assert normalized.start_iteration == 2; assert len(depr) == 1; assert "use --start_iteration" in str(depr[0].message)` — deprecated alias behavior |
| `test_legacy_source_paths_alias_works_with_deprecation_warning` | Keep | `normalized = runner.normalize_args(args); assert normalized.seed_paths == ["/tmp/seed.json"]; assert len(depr) == 1` — --source_paths deprecated alias |
| `test_main_empty_results_exits_zero_and_writes_no_records` | Keep | `assert code == 0; manifest = json.loads(manifest_path.read_text()); assert manifest["status"] == "no_records"; assert "[CHAIN] No models passed gates" in out` — end-to-end for empty results |
| `test_main_workflow_exception_still_exits_one` | Keep | `assert code == 1; manifest = json.loads(manifest_path.read_text()); assert manifest["status"] == "failed"` — true crash still exits 1 |
| `test_manual_override_start_iteration_3_with_iters_1_and_2_on_disk` | Keep | `assert "c8_test_arch_a" in MODEL_REGISTRY; assert "c8_test_arch_b" in MODEL_REGISTRY; assert kwargs["source_paths"] == [str(seed), iter1, iter2]; assert kwargs["run_name"] == "iter_003"` — both priors restored, correct source_paths |
| `test_max_epochs_negative_is_rejected` | Keep | `with pytest.raises(SystemExit): runner.build_parser().parse_args(..., "--max_epochs", "-1")` |
| `test_max_epochs_zero_is_rejected` | Keep | `with pytest.raises(SystemExit): runner.build_parser().parse_args(..., "--max_epochs", "0"); assert ">= 1" in err or "positive integer" in err` |
| `test_missing_iter_1_plugin_warns_but_iteration_runs` | Keep | `assert code == 0; assert iter1_output in kwargs["source_paths"]; assert len(plugin_warnings) >= 1` — missing plugin warns but iteration continues |
| `test_neither_flag_supplied_is_an_error` | Keep | `with pytest.raises(SystemExit): runner.normalize_args(args); assert "one of --start_iteration / --iteration is required" in err` |
| `test_plan_overrides_default_none` | Keep | `assert normalized.plan_overrides is None` — default None |
| `test_plan_overrides_json_string_becomes_dict` | Keep | `normalized = runner.normalize_args(args); assert normalized.plan_overrides == {"trial_portion": 0.2}` — JSON string → dict parsing |
| `test_seed_paths_and_source_paths_both_supplied_is_an_error` | Keep | `with pytest.raises(SystemExit): runner.normalize_args(args); assert "mutually exclusive" in err` |
| `test_seed_paths_is_required` | Keep | `with pytest.raises(SystemExit): runner.normalize_args(args); assert "one of --seed_paths / --source_paths is required" in err` |
| `test_start_iteration_1_passes_seeds_through_unchanged` | Keep | `kwargs = mock_wf.call_args.kwargs; assert kwargs["source_paths"] == [str(seed_file)]; assert kwargs["run_name"] == "iter_001"` — iter 1 gets seed verbatim |
| `test_start_iteration_2_restores_iter_1_plugin_and_prepends_path` | Keep | `assert "c8_test_arch_a" in MODEL_REGISTRY; assert kwargs["source_paths"] == [str(seed_file), iter1_output]; assert kwargs["run_name"] == "iter_002"` — plugin restored, source_paths updated |
| `test_start_iteration_below_one_is_an_error` | Keep | `with pytest.raises(SystemExit): runner.normalize_args(args); assert ">= 1" in err` |
| `test_start_iteration_canonical_path` | Keep | `args = runner.build_parser().parse_args(..., "--start_iteration", "3"); normalized = runner.normalize_args(args); assert normalized.start_iteration == 3; assert not hasattr(normalized, "iteration_legacy")` — argparse parsing + normalization |
| `test_workspace_is_required` | Keep | `with pytest.raises(SystemExit): runner.build_parser().parse_args(["--start_iteration", "1", "--seed_paths", "/tmp/seed.json"])` (missing --workspace) — argparse required |
| `test_write_manifest_completed_path_unchanged` | Keep | `manifest = runner.write_manifest(..., results=[_StubResult("c8_test_arch_a", score=0.71)]); assert manifest["status"] == "completed"; assert manifest["best_score"] == 0.71` |
| `test_write_manifest_crashed_forces_failed_regardless_of_results` | Keep | `manifest = runner.write_manifest(..., crashed=True); assert manifest["status"] == "failed"; assert manifest["output_path"] is None` — crashed overrides |
| `test_write_manifest_empty_results_emits_no_records` | Keep | `manifest = runner.write_manifest(str(tmp_path), "iter_001", results=[]); assert manifest["status"] == "no_records"; assert manifest["output_path"] is None; assert manifest["best_score"] is None` — deterministic write_manifest logic |
| `test_write_manifest_results_with_none_score_emits_no_records` | Keep | `manifest = runner.write_manifest(..., results=[_StubResult("c8_test_arch_a", score=None)]); assert manifest["status"] == "no_records"` |

### `tests/unit/test_compute_ground_truth.py`

Tests: 8

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_all_zero_anchors_returns_soft_floor` | Keep | `log_score, linear_sum, n = _global_per_file_ceiling([0.0, 0.0, 0.0], s_max=10.0); expected = math.log(1e-10, 5.27); assert abs(log_score - expected) < 1e-12` — soft floor for zero input |
| `test_hand_computed_scalar` | Keep | `anchors = [1.0, 2.0, 3.0, 4.0]; log_score, linear_sum, n = _global_per_file_ceiling(anchors, s_max=4.0); expected = math.log(1.875 + 1e-10, 5.27); assert abs(log_score - expected) < 1e-12` — hand-computed expected value, deterministic formula test |
| `test_log_base_is_5_27` | Keep | `_, scalar = _anchor_normalized_ceiling({"0": [math.sqrt(2.0)]}, s_max=1.0); expected = math.log(2.0 + 1e-10, 5.27); assert abs(scalar - expected) < 1e-12; assert abs(scalar - math.log(2.0)) > 1e-3; assert abs(scalar - math.log10(2.0)) > 1e-3` — log base pinned |
| `test_nonuniform_files_grand_mean_differs_from_simple_mean` | Keep | `file_vector, scalar = _anchor_normalized_ceiling(anchors, s_max); assert file_vector == [10.0, 0.1]; expected_scalar = math.log(2.08 + 1e-10, 5.27)` — non-uniform segment counts |
| `test_per_file_agrees_with_file_vector` | Keep | `for f_str, fv in zip(sorted(anchors, key=int), file_vector, strict=True): direct_log, _, _ = _global_per_file_ceiling(anchors[f_str], s_max); via_fv = math.log(fv + 1e-10, 5.27); assert abs(direct_log - via_fv) < 1e-12` — cross-consistency between per-file and grand-mean paths |
| `test_uniform_files_grand_mean_equals_simple_mean` | Keep | `file_vector, scalar = _anchor_normalized_ceiling(anchors, s_max); assert file_vector == [0.625, 3.125]; expected_scalar = math.log(1.875 + 1e-10, 5.27); assert abs(scalar - expected_scalar) < 1e-12` — hand-computed grand mean |
| `test_uses_global_smax_not_local_max` | Keep | `log_small, _, _ = _global_per_file_ceiling(anchors, s_max=2.0); log_large, _, _ = _global_per_file_ceiling(anchors, s_max=4.0); assert log_small > log_large; expected_delta = math.log((5.0 + 1e-10) / (2.5 + 1e-10), 5.27); assert abs((log_small - log_large) - expected_delta) <... |
| `test_weak_signal_is_not_collapsed_to_ghost_score` | Keep | `_, scalar = _anchor_normalized_ceiling({"0": [0.03]}, s_max=1.0); expected = math.log(0.0009 + 1e-10, 5.27); assert abs(scalar - expected) < 1e-12; ghost = -2.7708098959837675; assert abs(scalar - ghost) > 0.5` — regression guard for Phase 6.7 ghost-score killer |

### `tests/unit/test_compute_raw_baseline.py`

Tests: 9

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_coarse_stride_uses_20_segments` | Keep | `assert len(collected) == 20; assert all(c is True for (_, c) in collected)` — tests coarse mode count and flag |
| `test_coarse_uses_same_global_s_max` | Keep | `expected_delta = math.log(2.0 + 1e-10, 5.27) - math.log(1.0 + 1e-10, 5.27); assert abs((log_small - log_large) - expected_delta) < 1e-12` — pins the global s_max division formula |
| `test_fine_calls_process_segment_200_times` | Keep | `assert sorted(collected) == list(range(200))` — tests that fine mode iterates over all 200 segments |
| `test_grand_mean_weights_by_n_segments` | Keep | `expected_scalar = math.log(0.25 + 1e-10, 5.27); assert abs(got["scalar_score"] - expected_scalar) < 1e-12` — tests segment-count-weighted grand mean formula |
| `test_hand_computed_scalar` | Keep | `expected_log = math.log(1.5 + 1e-10, 5.27); assert abs(log_score - expected_log) < 1e-12` — hand-computed expected value; tests real aggregation formula |
| `test_skip_when_any_fine_index_missing` | Keep | `assert not (tmp_path / "scalar_anchor_normalized.json").exists(); assert "missing fine indices" in captured.out` — tests guard against incomplete fine set |
| `test_skip_when_legacy_json_lacks_new_fields` | Keep | `assert not (tmp_path / "scalar_anchor_normalized.json").exists(); assert "linear_sum/n_segments" in captured.out` — tests backward-compat guard for old JSONs |
| `test_weak_signal_log_score_is_distinct_post_phase67` | Keep | `assert abs(log_score - (-2.7708098959837675)) > 0.5` and `assert abs(log_score - math.log(1e-10, 5.27)) > 0.5` — regression guard: ghost scores must not appear |
| `test_writes_scalar_when_all_20_fine_present` | Keep | `expected_scalar = math.log(0.5 + 1e-10, 5.27); assert abs(got["scalar_score"] - expected_scalar) < 1e-12` — real file I/O test with hand-computed expected scalar |

### `tests/unit/tools/test_token_baseline_report.py`

Tests: 18

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_bloat_alert_fires_above_threshold` | Keep | `assert len(bloats) == 1` and `assert round(bloats[0].usd, 4) == 2.0000` — threshold logic |
| `test_bloat_alert_silent_below_threshold` | Keep | `assert bloats == []` for $1.20 < $1.50 threshold |
| `test_context_explosion_alert_fires_above_threshold` | Keep | `assert len(explosions) == 1` and `assert explosions[0].prompt_tok == 60_000` |
| `test_context_explosion_silent_at_threshold` | Keep | `assert explosions == []` for `prompt=50_000` (= threshold, strict >) |
| `test_corrupted_jsonl_blocks_publication` | Keep | `subprocess.run([...])` with malformed JSONL then `assert proc.returncode != 0` and `assert "AUDIT LOG CORRUPTION DETECTED" in proc.stderr` |
| `test_end_to_end_positive_run` | Keep | `rc = main([...])` then `assert rc == 0`, reads report files, checks section headers — full pipeline |
| `test_happy_path_classifier` | Keep | `assert is_happy_path(happy) is True` and `assert is_happy_path(retry) is False` and `assert is_happy_path(error) is False` — real classifier logic |
| `test_linear_slope_flat_returns_zero` | Keep | `assert slope == 0.0` and `assert r2 == 0.0` — flat-line convention |
| `test_linear_slope_handles_missing_iters` | Keep | `pts = [(1, 3.0), (3, 7.0), (5, 11.0)]` then same slope=2 — missing-iter robustness |
| `test_linear_slope_perfect_line` | Keep | `assert round(slope, 6) == 2.0` and `assert round(r2, 6) == 1.0` — regression math |
| `test_linear_slope_single_point_safe` | Keep | `assert linear_slope([(1, 5.0)]) == (0.0, 0.0)` and empty list — edge case |
| `test_per_label_slopes_skips_missing_iters` | Keep | `assert round(s["tok_slope"], 2) == 1100.0` and `assert round(s["tok_r2"], 4) == 1.0` — per-label slope computation |
| `test_segmentation_3_row_jsonl` | Keep | `assert a.happy.prompt_tok == 1000` and `assert a.recovery.prompt_tok == 5000` — real aggregation |
| `test_skip_lint_bypasses_corruption_block` | Keep | `main([..."--skip-lint"])` then `assert rc == 0` and output file exists — escape hatch |
| `test_usd_overrides_propagate` | Keep | `assert round(cs.usd(rate_prompt=5.0, rate_completion=15.0), 4) == 5.0` |
| `test_usd_precision_to_four_decimals` | Keep | `assert round(usd, 4) == 1.3000` for 100K prompt + 10K completion at default rates — real arithmetic |
| `test_usd_zero_when_no_tokens` | Keep | `assert cs.usd(DEFAULT_RATE_PROMPT, DEFAULT_RATE_COMPLETION) == 0.0` |
| `test_verdict_written_at_top_of_top3_report` | Keep | `assert "Verdict" in head` and `assert verdict in head` — spec §1.9.2 rendering |

### `tests/unit/workflows/test_knowledge_cache_cap.py`

Tests: 6

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_8_entries_top5_by_score` | Keep | `assert "model_0" in capped; assert "model_7" in capped; assert evicted == {"model_1", "model_2", "model_3"}` — tests top-N eviction and current-model survival |
| `test_current_model_survives_even_if_worst` | Keep | `assert "bad_current" in capped; assert "good_5" in evicted; assert "good_6" in evicted` — tests that worst-scored current model survives |
| `test_custom_max_entries` | Keep | `capped, evicted = _cap_knowledge_cache(cache, ..., max_entries=3); assert len(capped) == 3; assert len(evicted) == 7` — tests custom cap |
| `test_exact_limit_no_eviction` | Keep | `assert len(capped) == 5; assert evicted == set()` — boundary at exact limit |
| `test_none_scores_evicted_first` | Keep | `assert "none_1" in evicted; assert "none_2" in evicted` — tests None scores rank below all scored models |
| `test_under_limit_no_eviction` | Keep | `capped, evicted = _cap_knowledge_cache(cache, current_model="model_0"); assert len(capped) == 4; assert evicted == set()` — pure function; no mocks |

### `tests/unit/workflows/test_llm_config.py`

Tests: 24

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_cross_provider_nested_config_loads` | Keep | `assert cfg.tune.reflector.provider == "openai"` |
| `test_default_all_slots_none` | Keep | `assert cfg.interpret is None; assert cfg.tune is None` — WorkflowLLMConfig default |
| `test_defaults` | Keep | `c = NodeLLMConfig(); assert c.provider == "gemini"; assert c.model_id == "gemini-3.1-flash-lite-preview"` — pins schema defaults |
| `test_empty_dict_loads_with_both_defaults` | Keep | `loaded = TunerLLMConfig.model_validate({}); assert loaded.planner.model_id == "gemini-3.1-pro-preview"` |
| `test_explicit_cross_provider` | Keep | `assert c.reflector.provider == "openai"; assert c.reflector.model_id == "gpt-4o-mini"` — cross-provider config |
| `test_explicit_provider_and_model` | Keep | `c = NodeLLMConfig(provider="openai", model_id="gpt-4o-mini"); assert c.provider == "openai"` |
| `test_explicit_same_provider_different_models` | Keep | `assert c.planner.model_id != c.reflector.model_id` — tests independent model IDs |
| `test_full_nested_config_loads` | Keep | `cfg = WorkflowLLMConfig.model_validate(data); assert cfg.validate_model.model_id == "gemini-3.1-flash-lite-preview"` |
| `test_get_flattens_tune_into_4_keys` | Keep | `assert result == {"provider": "gemini", "model_id": ..., "reflect_provider": "openai", "reflect_model_id": "gpt-4o-mini"}` — tests 4-key flattening |
| `test_get_returns_empty_dict_for_unset_slot` | Keep | `assert cfg.get("interpret") == {}; assert cfg.get("tune") == {}` — tests get() with None slot |
| `test_get_returns_two_keys_for_single_call_agent` | Keep | `assert result == {"provider": "gemini", "model_id": "gemini-2.5-flash"}; assert "reflect_provider" not in result` — tests flattening |
| `test_get_tune_after_uniform_with_overrides` | Keep | `assert flat["reflect_provider"] == "openai"; assert flat["reflect_model_id"] == "gpt-4o-mini"` |
| `test_get_validate_alias` | Keep | `cfg = WorkflowLLMConfig(validate=...); result = cfg.get("validate"); assert result == {...}` — tests alias resolution |
| `test_invalid_provider_raises` | Keep | `with pytest.raises(ValidationError): NodeLLMConfig(provider="anthropic", model_id="claude-3")` — tests Literal validation |
| `test_no_reflect_overrides_planner_equals_reflector` | Keep | `assert cfg.tune.planner.model_id == cfg.tune.reflector.model_id` — uniform() same-model case |
| `test_partial_dict_loads_with_planner_default` | Keep | `assert loaded.planner.model_id == "gemini-3.1-pro-preview"` — partial dict falls back to default |
| `test_partial_tune_only_reflector_loads_with_planner_default` | Keep | `assert cfg.tune.planner.model_id == "gemini-3.1-pro-preview"` — partial JSON load |
| `test_planner_and_reflector_are_independent_objects` | Keep | `assert c.planner is not c.reflector` — tests that two distinct default_factory instances are created |
| `test_reflect_model_id_only_same_provider` | Keep | `assert cfg.tune.reflector.model_id == "gemini-2.5-flash"; assert cfg.tune.reflector.provider == "gemini"` |
| `test_reflect_provider_and_model_cross_provider` | Keep | `assert cfg.tune.reflector.provider == "openai"; assert cfg.tune.reflector.model_id == "gpt-4o-mini"` |
| `test_reflect_provider_only_no_model_override` | Keep | `assert cfg.tune.reflector.provider == "openai"; assert cfg.tune.reflector.model_id == "shared-model-name"` |
| `test_round_trip_through_json` | Keep | `loaded = NodeLLMConfig.model_validate_json(c.model_dump_json()); assert loaded.model_id == "gemini-2.5-flash"` — tests JSON round-trip |
| `test_round_trip_via_model_dump_and_validate` | Keep | `loaded = WorkflowLLMConfig.model_validate(dumped); assert loaded.tune.reflector.model_id == "gemini-2.5-flash"` |
| `test_tune_slot_is_typed_TunerLLMConfig` | Keep | `cfg = WorkflowLLMConfig(tune=TunerLLMConfig()); assert isinstance(cfg.tune, TunerLLMConfig)` — type check |

### `tests/unit/workflows/test_model_exploration.py`

Tests: 61

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_accepts_source_paths` | Keep | `assert isinstance(results[0], HyperparamTuningOutput)` via `source_paths=` API |
| `test_all_five_nodes_called` | Keep | `workflow_env["interp"].return_value.run.assert_called_once()` through all 5 nodes |
| `test_chained_iterations_via_source_paths` | Keep | `assert len(interp_input_2.summaries) == 2` after chaining iteration 1 output into iteration 2 |
| `test_classifier_default_routes_correctly` | Keep | `assert get_output_type("test_classifier_plugin_c6") == "classifier"` |
| `test_converts_multiple_outputs` | Keep | `assert len(summaries) == 2` |
| `test_converts_single_output` | Keep | `assert summaries[0].model_type == "punet"` with real `tuning_outputs_to_summaries` |
| `test_correct_input_types` | Keep | `assert isinstance(workflow_env["interp"].return_value.run.call_args[0][0], InterpretationInput)` for all input types |
| `test_creates_dest_dir_if_missing` | Keep | `assert (dest / "gated_tcn.py").is_file()` with non-existent dest |
| `test_creates_multiple_attempt_dirs` | Keep | `assert os.path.isdir(os.path.join(iter_dir, "attempt_002_gated_tcn"))` |
| `test_default_start_iteration_unchanged` | Keep | `assert interp_input.iteration == 1` — default start iteration |
| `test_degenerate_penalty_score_default_is_none` | Keep | `assert tune_input.degenerate_penalty_score is None` |
| `test_degenerate_penalty_score_float_reaches_tuning_input` | Keep | `assert tune_input.degenerate_penalty_score == -2.5` with `degenerate_penalty_score=-2.5` |
| `test_does_not_touch_legacy_global_dir` | Keep | `assert not legacy.exists()` after monkeypatching cwd — regression guard |
| `test_extracts_round_scores` | Keep | `assert summaries[0].round_scores[0] == 1.5` |
| `test_fan_in_expert_advice` | Keep | `assert "receptive field" in tune_arg.expert_advice.focus_areas` — fan-in wiring |
| `test_feeds_previous_failures_to_proposal` | Keep | `assert "shape mismatch" in second_call_input.previous_failures[0]` — error propagated |
| `test_formal_round_strategy_canonical_hybrid_params_reaches_tuning_input` | Keep | `assert tune_input.formal_round_strategy == "hybrid_params"` — new strategy accepted |
| `test_formal_round_strategy_canonical_independent_reaches_tuning_input` | Keep | `assert tune_input.formal_round_strategy == "independent"` — forwarded through workflow |
| `test_formal_round_strategy_default_full_clone` | Keep | `assert tune_input.formal_round_strategy == "full_clone"` — default value |
| `test_formal_round_strategy_legacy_alias_canonicalised` | Keep | `assert tune_input.formal_round_strategy == "independent"` when passed `"llm_propose"` |
| `test_formal_round_strategy_legacy_inherit_best_trial_canonicalised` | Keep | `assert tune_input.formal_round_strategy == "full_clone"` when passed `"inherit_best_trial"` |
| `test_four_iteration_deque_evicts_oldest` | Keep | `assert summaries5 == ["SENTINEL-iter2", "SENTINEL-iter3", "SENTINEL-iter4"]` — deque eviction |
| `test_iter1_proposal_has_empty_recent_gate_exhaustions` | Keep | `assert iter1_propose_input.recent_gate_exhaustions == []` |
| `test_iter2_proposal_no_gate_exhaustion_when_iter1_succeeded` | Keep | `assert iter2_propose_input.recent_gate_exhaustions == []` when `iter1_tune.gate_exhaustion is None` |
| `test_iter2_proposal_receives_iter1_gate_exhaustion` | Keep | `assert surfaced[0].model_dump() == gate.model_dump()` — full round-trip equality |
| `test_iteration_directory_created` | Keep | `assert os.path.isdir(os.path.join(iter_dir, "attempt_001_gated_tcn"))` |
| `test_knowledge_cache_grows_across_iterations` | Keep | `assert "punet" in iter2_inp.model_knowledge_cache` and `assert len(iter2_inp.summaries) == 1` |
| `test_legacy_api_uses_new_function_internally` | Keep | `assert legacy_result[0].model_type == new_result[0].model_type` — API parity |
| `test_loads_heterogeneous_paths` | Keep | `assert len(results) == 3` with mixed seed and iteration paths |
| `test_loads_multiple_model_types` | Keep | `assert {r.model_type for r in results} == {"punet", "wavenet"}` |
| `test_loads_single_path` | Keep | `assert results[0].model_type == "punet"` via `load_tuning_outputs_from_paths` |
| `test_loads_valid_json` | Keep | `assert results[0].model_type == "punet"` with real file write and `load_tuning_outputs` |
| `test_no_bare_module_identity_after_package_refactor` | Keep | `assert sys.modules.get("models_format_sandbox") is None` — package refactor invariant |
| `test_no_restored_cache_preserves_legacy_empty_init` | Keep | `assert iter1_inp.model_knowledge_cache == {}` when kwarg omitted |
| `test_preserves_best_score` | Keep | `assert summaries[0].best_denoising_score == 1.5` |
| `test_raises_on_invalid_json` | Keep | `pytest.raises(FileNotFoundError)` with `"not valid json {{{"` |
| `test_raises_on_missing_path` | Keep | `pytest.raises(FileNotFoundError, match="not found")` |
| `test_raises_when_model_missing` | Keep | `pytest.raises(FileNotFoundError, match="wavenet")` when only punet present |
| `test_raises_when_no_outputs_found` | Keep | `pytest.raises(FileNotFoundError, match="Missing or invalid source files")` |
| `test_raises_when_no_source_provided` | Keep | `pytest.raises(ValueError, match="Must provide either source_paths")` |
| `test_register_plugin_populates_all_four_surfaces` | Keep | `assert PLUGIN_OUTPUT_TYPE_REGISTRY.get("test_regressor_plugin_c6") == "regressor"` and three other registry checks |
| `test_regressor_routes_via_get_output_type` | Keep | `assert get_output_type("test_regressor_plugin_c6") == "regressor"` — latent-bug regression |
| `test_restored_model_knowledge_cache_defensive_copy` | Keep | `assert list(caller_cache.keys()) == ["punet"]` after workflow mutates its own copy |
| `test_restored_model_knowledge_cache_seeds_first_iter` | Keep | `assert iter1_inp.model_knowledge_cache["punet"]["_stats"]["best_denoising_score"] == 1.42` |
| `test_retries_on_validation_failure` | Keep | `assert workflow_env["propose"].return_value.run.call_count == 2` with first validation failing |
| `test_returns_list_with_one_output` | Keep | `assert isinstance(results[0], HyperparamTuningOutput)` — output type |
| `test_returns_model_type_on_success` | Keep | `assert result == "test_regressor_plugin_c6"` with real plugin load |
| `test_returns_none_on_invalid_plugin` | Keep | `assert _add_plugin_to_registries(str(bad)) is None` with missing attrs |
| `test_runs_multiple_iterations` | Keep | `assert len(results) == 3` with `max_iterations=3` |
| `test_signature_accepts_degenerate_penalty_score` | Keep | `assert "degenerate_penalty_score" in sig.parameters` and `assert sig.parameters["degenerate_penalty_score"].default is None` |
| `test_signature_accepts_formal_round_strategy` | Keep | `assert "formal_round_strategy" in sig.parameters` via `inspect.signature(run_workflow)` |
| `test_skips_when_source_plugin_missing` | Keep | `assert "plugin file not found" in captured.out` and `assert not (dest / "ghost.py").exists()` |
| `test_start_iteration_offsets_loop` | Keep | `assert calls[0][0][0].iteration == 5` with `start_iteration=5` and dir `iteration_005` |
| `test_start_iteration_with_multi_iter` | Keep | `assert [c[0][0].iteration for c in calls] == [3, 4]` with `start_iteration=3, max_iterations=2` |
| `test_stops_after_max_proposal_attempts` | Keep | `assert len(results) == 0` and `workflow_env["tune"].return_value.run.assert_not_called()` |
| `test_stops_on_target_score` | Keep | `assert len(results) == 1` when score 2.5 >= target 2.0 |
| `test_updates_model_registry` | Keep | `assert "test_classifier_plugin_c6" in MODEL_REGISTRY` after real plugin load |
| `test_updates_packaged_config_registry` | Keep | `assert "test_classifier_plugin_c6" in PLUGIN_CONFIG_REGISTRY` |
| `test_workflow_summary_saved` | Keep | `assert summary["status"] == "completed"` from disk file |
| `test_writes_description_into_supplied_dest` | Keep | `assert "Test plugin description" in ...read_text()` |
| `test_writes_plugin_into_supplied_dest` | Keep | `assert (dest / "gated_tcn.py").is_file()` and `assert "PLUGIN_MODEL_TYPE" in ...read_text()` |

### `tests/unit/workflows/test_render_physical_rejection.py`

Tests: 15

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_attempted_config_and_suggestion_rendered` | Keep | `assert "'batch_size': 16" in out; assert "Suggestion: Drop hidden_dim to 512." in out` |
| `test_dominant_layer_line_present_when_named` | Keep | `assert "Dominant layer: encoder.attention.block7.mha" in out; assert "13.40 GB" in out; assert "46% of peak" in out` |
| `test_dominant_layer_line_suppressed_when_empty` | Keep | `assert "Dominant layer" not in out; assert "0% of peak" not in out; assert "binding cap: compute_intensity" in out` — tests suppression logic |
| `test_empty_input_is_noop` | Keep | `assert _aggregate_worst_offender_rejections([]) == []` — pure function edge case |
| `test_empty_suggestion_is_suppressed` | Keep | `r = _mk("deep_punet", ..., suggestion=""); assert "Suggestion:" not in out` — tests suppression of empty suggestion |
| `test_groups_by_model_type` | Keep | `assert set(by_mt.keys()) == {"deep_punet", "wide_transformer"}; assert by_mt["deep_punet"][0] is a2` — tests grouping and worst selection |
| `test_missing_model_type_treated_as_unknown_group` | Keep | `r = PhysicalRejection(attempt_config={"batch_size": 4}, ...); out = _aggregate_worst_offender_rejections([r]); assert len(out) == 1` — tests fallback to 'unknown' |
| `test_picks_worst_by_ratio_within_group` | Keep | `assert worst is worse` where `worse` has higher estimated_gb — tests ratio comparison logic |
| `test_pluralization_with_multiple_rejections` | Keep | `assert "rejected 3 attempts by the VRAM gate" in out` — tests plural form |
| `test_reports_overshoot_and_budget` | Keep | `assert "estimated 29.10 GB" in out; assert "budget 20.00 GB" in out; assert "binding cap: vram" in out` |
| `test_single_rejection_returns_one_group` | Keep | `worst, count = out[0]; assert worst is r; assert count == 1` — tests identity of returned object and count |
| `test_singular_phrasing_with_one_rejection` | Keep | `assert "rejected 1 attempt by the VRAM gate" in out; assert "1 attempts" not in out` — tests singular form |
| `test_tag_and_model_type_in_header` | Keep | `assert out.startswith("[PHYSICAL REJECTION] deep_punet:")` — tests real render output |
| `test_ties_broken_by_dominant_fraction` | Keep | `assert worst is b` where b has higher dominant_fraction — tests tie-breaking logic |
| `test_zero_budget_treated_as_infinite_ratio` | Keep | `assert worst is degenerate` where degenerate has `budget_gb=0.0` — tests +inf ratio handling |

### `tests/unit/workflows/test_vram_auto_shrink_logic.py`

Tests: 9

| Test function | Verdict | Reason (cite actual code) |
|---|---|---|
| `test_failed_status_is_false` | Keep | `assert decide_iter1_auto_shrunk(iter1, []) is False` with `status=_FAILURE_STATUS` |
| `test_multiple_rejections_disable_auto_shrink_flag` | Keep | `assert decide_iter1_auto_shrunk(iter1, rej) is False` with two rejections |
| `test_non_empty_rejections_with_success_resolves_to_rejection_path` | Keep | `assert decide_iter1_auto_shrunk(iter1, rej) is False` when both signals present — rejection wins |
| `test_none_iter1_tuning_is_false` | Keep | `assert decide_iter1_auto_shrunk(None, []) is False` — None guard |
| `test_one_rejection_disables_auto_shrink_flag` | Keep | `assert decide_iter1_auto_shrunk(iter1, rej) is False` with one rejection string — rejection takes precedence |
| `test_predicate_returns_true_for_at_least_one_schema_valid_status` | Keep | loops `_SUCCESS_STATUSES` calling `decide_iter1_auto_shrunk` to assert at least one reaches `True` — dead-code regression guard |
| `test_rejection_overrides_even_with_failed_status` | Keep | `assert decide_iter1_auto_shrunk(iter1, rej) is False` with `status=_FAILURE_STATUS` and rejection |
| `test_success_status_with_no_score_is_false` | Keep | `assert decide_iter1_auto_shrunk(iter1, []) is False` parametrized with `score=None` |
| `test_zero_rejections_plus_success_status_plus_score_yields_true` | Keep | `assert decide_iter1_auto_shrunk(iter1, rej) is True` parametrized for both `"completed"` and `"partial"` |
