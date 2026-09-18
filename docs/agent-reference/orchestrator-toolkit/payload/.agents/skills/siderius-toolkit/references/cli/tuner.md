# tuner: existing standalone CLI arguments

Source inventory at SIDERIUS `1c68bc81d7e44bbdc6e03a445a8422c3f77f45ff`. Argument expressions below are
copied from the existing parser declarations; evaluate dynamic defaults with
the selected executable’s `--help`. These are not an orchestrator launch recipe.
Read the [capability guide](../agents/tuner.md) for Python/CLI differences.

Public module: `nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent`.

| Argument | Type/action | Required | Default expression | Choices | Help |
| --- | --- | --- | --- | --- | --- |
| --provider | str | False | 'gemini' | ['gemini', 'openai'] | 'LLM provider for the planner sub-call (default for reflector when not overridden).' |
| --model_id | str | False | 'gemini-3.1-flash-lite-preview' | — | 'Model ID for the planner sub-call (default for reflector when not overridden).' |
| --reflect_provider | str | False | None | ['gemini', 'openai'] | 'Optional separate provider for the reflector sub-call. When None, the reflector uses --provider.' |
| --reflect_model_id | str | False | None | — | 'Optional separate model for the reflector sub-call (e.g., gemini-2.5-flash). When None, the reflector uses --model_id.' |
| --expert_advice | str | False | 'None' | — | 'Initial advice from a human expert to guide exploration.' |
| --max_rounds | int | False | 10 | — | 'Maximum number of experiment rounds to prevent token drain.' |
| --force_model | str | False | 'auto' | — | f"Force a specific architecture or let the agent decide ('auto'). Built-in choices: {', '.join(builtin_choices)}. Plugin model_types are also accepted when paired with --seed_plugin_path." |
| --seed_plugin_path | str | False | None | — | "Path to a plugin .py file used as the seed model for this run. Required when --force_model is a plugin model_type (i.e. not a built-in). The file's PLUGIN_MODEL_TYPE must equal --force_model. The tuner copies the file into <workspace>/plugins/<run_name>/ at run start so the training subprocess sees it via SIDERIUS_PLUGIN_DIRS. See docs/run_scoped_plugins.md (Phase 3)." |
| --run_name | str | False | 'test_run' | — | 'Run name for the auto-exploration.' |
| --workspace | str | False | './siderius_workspace' | — | 'Root directory for all agent-generated outputs.' |
| --progress_bar | 'store_true' | False | None (argparse default unless action changes it) | — | 'Stream live tqdm progress bars from training/inference subprocesses.' |
| --file_index | int | False | 6 | — | 'Validation/training file index (default: 6). Ignored when --is_trial.' |
| --is_trial | 'store_true' | False | None (argparse default unless action changes it) | — | 'Enable trial-explore mode with multi-file sparse sampling.' |
| --trial_strategy | str | False | 'snapshot' | ['snapshot', 'anchors', 'target'] | 'DEPRECATED no-op (DS7) — warns and is ignored. Use --data_scope.' |
| --trial_portion | float | False | 0.1 | — | 'Fraction of segments per file for training scope (default: 0.1).' |
| --eval_strategy | str | False | 'snapshot' | ['snapshot', 'anchors', 'target'] | 'DEPRECATED no-op (DS7) — warns and is ignored. Use --data_scope.' |
| --eval_portion | float | False | 0.1 | — | 'Fraction of segments per file for validation (default: 0.1).' |
| --train_portion | float | False | 0.1 | — | 'Per-epoch subsample from training scope (default: 0.1).' |
| --formal_strategy | str | False | 'snapshot' | ['snapshot', 'anchors', 'target'] | 'Training-side sampling strategy in formal mode (default: snapshot).' |
| --formal_training_scope_source | str | False | 'operator' | ['operator', 'agent'] | 'Source of formal training portions; formal evaluation stays operator-owned.' |
| --order_strategy_override | str | False | None | ['shuffle', 'sequential'] | "Force the training sample visitation order for every round, overriding any agent proposal. Unset (default) = the agent decides, falling back to 'shuffle' (the pre-V19 behavior)." |
| --file_order_override | str | False | None | — | "Comma-separated file visitation ORDER for --order_strategy_override sequential, e.g. '4,6,5,9,7,8'. Order is preserved as written and must be a full permutation of the resolved DataScope. Range syntax is rejected — a range cannot express an order. Omit for ascending file index." |
| --formal_portion | float | False | 0.1 | — | 'Fraction of segments per file for formal training scope (default: 0.1).' |
| --formal_train_portion | float | False | 1.0 | — | 'Per-epoch iteration fraction for formal training (default: 1.0).' |
| --formal_eval_portion | float | False | 1.0 | — | 'Fraction of segments per file for the formal-mode eval scope (snapshot strategy). Default 1.0 = legacy full-clone behaviour. Lower (e.g. 0.05) for smoke / CI runs that need to fit the formal_time_budget_minutes gate.' |
| --human_advice | str | False | None | — | 'Human guidance for the agent (injected alongside expert_advice).' |
| --cleanup_denoised | 'store_true' | False | None (argparse default unless action changes it) | — | 'Legacy cleanup request; incompatible with --retain_model_outputs.' |
| --retain_model_outputs | 'store_true' | False | None (argparse default unless action changes it) | — | 'Keep per-sample model outputs after scoring and Health (default: retire them).' |
| --retain_training_checkpoints | 'store_true' | False | None (argparse default unless action changes it) | — | 'Keep training checkpoint originals (default: retire after their consumers finish).' |
| --trial_time_budget_minutes | float | False | None | — | 'Trial wall-time budget in minutes. None disables Trial time admission.' |
| --formal_time_budget_minutes | float | False | None | — | 'Formal wall-time budget in minutes. None disables Formal time admission.' |
| --data_dir | str | True | None (argparse default unless action changes it) | — | 'Physical data directory for the declared task. ' |
| --health_checks_config | str | False | None | — | 'Optional external HealthGate YAML override; omitted uses the packaged generic policy.' |
| --data_scope | str | False | None | — | "Restrict the run to a file subset: '4-9', '4,5,6,7,8,9', or mixed '0-3,7'. Omitted = complete dataset. Under a partial scope only 'snapshot' sampling is legal and --health_gate_files is required when gates are enabled. See docs/design/enable_partial_file_list.md." |
| --trial_time_admission_source | str | False | 'measured' | ('forecast', 'measured') | 'Single Trial wall-time admission authority. Forecast skips executing-device enforcement; measured skips advance forecast admission.' |
| --formal_time_admission_source | str | False | 'measured' | ('forecast', 'measured') | 'Single Formal wall-time admission authority. Forecast skips executing-device enforcement; measured skips advance forecast admission.' |
| --health_gate_enabled | argparse.BooleanOptionalAction | False | True | — | 'HealthGate subsystem switch (default: enabled). --no-health_gate_enabled disables gate evaluation entirely; successful finite-score records then count as valid candidates.' |
| --health_gate_files | str | False | None | — | 'Run-level shared monitored-file list for ALL HealthGate checks (same spec format as --data_scope). Omitted + full scope = YAML defaults; omitted + partial scope = startup error.' |
| --resume | 'store_true' | False | None (argparse default unless action changes it) | — | 'Resume from validated completed rounds already in this workspace.' |
| --trial_vram_budget_gb | float | False | None | — | 'Per-mode VRAM ceiling (GB) for the evaluate_vram_skill gate on rounds where plan.is_trial=True. None → skill uses free×0.8 defensive limit.' |
| --formal_vram_budget_gb | float | False | None | — | 'Per-mode VRAM ceiling (GB) for the evaluate_vram_skill gate on rounds where plan.is_trial=False. None → skill uses free×0.8 defensive limit. Sized independently from the trial budget because formal rounds often use larger batch_size / segmentation_size.' |
| --attempts_per_round | int | False | 3 | — | 'Inner attempt budget for trial rounds (default 3). Each round runs up to N attempts; success → break + reset the consecutive-fail counter, exhaustion → bump it. See docs/resource_estimator_implement.md §11.' |
| --attempts_per_formal_round | int | False | 5 | — | 'Inner attempt budget for the formal-promotion round (default 5, intentionally higher than --attempts_per_round). Formal is the only cross-architecture comparable measurement, so an iteration with no formal score is wasted entirely — extra attempts are worth the cost.' |
| --max_fail_rounds | int | False | 3 | — | "Consecutive-failure brake (default 3). The outer loop aborts with termination_reason='aborted_fail_rounds' after this many consecutive rounds exhaust their inner attempt budget." |
| --max_epochs | int | False | None | — | "Hard cap on epochs per round. When set, the tuner clamps the LLM's planned epochs to min(planned_epochs, max_epochs). Wires into HyperparamTuningInput.max_epochs (already enforced in the round loop). Default None = no clamp (LLM plan unchanged). Per-mode overrides: --trial_max_epochs / --formal_max_epochs take precedence for their round role (D-BUD-6)." |
| --vram_probe_step_timeout_seconds | float | False | 180.0 | — | 'Maximum wall time for one training-mode or inference VRAM footprint forward (default 180). It is not a training-step or epoch budget.' |
| --vram_preflight_total_timeout_seconds | float | False | 900.0 | — | 'Maximum wall time for the complete isolated VRAM preflight worker (default 900).' |
| --vram_preflight_host_memory_limit_gb | float | False | None | — | 'Maximum resident host memory in GiB for the complete isolated VRAM-preflight process tree. Omission preserves the deployment default, normally 24 GiB. This is not the GPU VRAM ceiling.' |
| --trial_max_epochs | int | False | None | — | 'TRIAL-role epoch ceiling (campaign decision D-BUD-6). Precedence for a trial round: this value -> --max_epochs -> no clamp; formal rounds never read it. Wires into HyperparamTuningInput.trial_max_epochs (ge=1 — zero/negative refuse loudly at input validation). Default None = trial rounds keep the mode-agnostic --max_epochs.' |
| --formal_max_epochs | int | False | None | — | 'FORMAL-role epoch ceiling (campaign decision D-BUD-6). Precedence for a formal round: this value -> --max_epochs -> no clamp; trial rounds never read it. Wires into HyperparamTuningInput.formal_max_epochs (ge=1 — zero/negative refuse loudly at input validation). Default None = formal rounds keep the mode-agnostic --max_epochs.' |
| --max_steps_per_attempt | int | False | 150000 | — | '§5 guardrail: skip plans whose resolved optimizer-step count exceeds this (planner-visible record). 0 disables. Default 150000 (provisional §5 value).' |
| --min_formal_batch_size | int | False | 0 | — | '§5 guardrail: skip FORMAL rounds planned below this batch size (the V18 launch-overhead pathology; trial rounds exempt). 0 disables. Default 0 (disabled); set an explicit task/campaign value only when its execution contract requires one.' |
| --allow_extreme_steps | 'store_true' | False | None (argparse default unless action changes it) | — | '§5 operator override: bypass both step/batch guardrails (recorded in run provenance).' |
| --runtime_watchdog | 'store_true' | False | None (argparse default unless action changes it) | — | '§4 runtime watchdog: run training/inference subprocesses in their own process group under the deadline max(floor, min(budget, verified_estimate x safety)). Default off.' |
| --runtime_safety_factor | float | False | 1.0 | — | '§2.10 safety multiplier for admission and the watchdog deadline. Default 1.0 (schema-mirroring); V18 production posture is 1.5, passed explicitly by the launch config.' |
| --runtime_trial_safety_factor | float | False | None | — | '§2.10 phase-specific factor for TRIAL attempts; wins over --runtime_safety_factor when set. V18 posture 2.0 (Wave-1A diagnostic: systematic 1.54-1.61x post-verification drift).' |
| --runtime_formal_safety_factor | float | False | None | — | '§2.10 phase-specific factor for FORMAL attempts; wins over --runtime_safety_factor when set. Default None keeps formals on the base factor.' |
| --runtime_watchdog_floor_seconds | float | False | 60.0 | — | '§4 watchdog deadline floor. Default 60.0 (schema-mirroring); V18 production posture is 120.0.' |
| --runtime_verification_max_wall_seconds | float | False | None | — | 'Maximum wall time for adaptive in-subprocess runtime verification. Omit to preserve the verifier default.' |
| --enable_chain_incumbent_formal_gates | 'store_true' | False | None (argparse default unless action changes it) | — | "V19 PR 1: consumption-only switch. When set, the two formal delta gates use chain_incumbent + fixed_delta as their thresholds. Default OFF: incumbent is still reconstructed and recorded; the gates simply do not consume it. OFF is NOT a fixed-0.0 mode. Full semantics: nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.md under 'Chain formal-incumbent reference'." |
| --healthgate_mode | str | False | None | ['blocking', 'observe_only'] | 'V20 PR D: whether HealthGate verdicts ENFORCE (blocking) or only record (observe_only). Declared, never inferred from the config file. No default: a formal campaign that omits it is refused at launch, because defaulting would silently claim authority the run may not have.' |
| --result_authority | str | False | None | ['scientific', 'diagnostic'] | "V20 PR D: whether this run's results may inform science (scientific) or are for diagnosis only (diagnostic). A SEPARATE axis from --healthgate_mode: observe_only+scientific is a contradiction and is refused, while blocking+diagnostic is coherent — enforced, and deliberately not promoted." |
| --task_composition | str | True | None (argparse default unless action changes it) | — | "Path to a required YAML task-composition manifest. Supplied, it binds this run's task data path, dataset profile, metric, declared secondaries, Health family and task description/forward contract EXPLICITLY, and every unresolvable reference fails closed before any LLM call. Same manifest shape and same composition authority the chain launcher's --task_composition already uses (sdsc_submission_scripts/run_chain.sh) — added here (Step 12 / PR-12d D8a) so a SINGLE model can be run composed and --force_model-locked in one launch, without the multi-agent chain's proposer choosing the architecture. docs/design/generic_framework_upgrade/step_10_orchestration_task_binding/pr_10_p1_run_scoped_task_composition.md." |

A CLI flag is not automatically a Python input field or a supported field
of the outer chain launcher. Consult this exact entrypoint. Internal parser
modules are provenance references, not supported import entrypoints.
