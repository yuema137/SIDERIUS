# literature-review: existing standalone CLI arguments

The table below lists the options of the parser this module's `main()` builds,
with each option's runtime default value.
Generated from source by
`python -m tools.orchestration_setup.reference_tables --write`;
`tests/unit/tools/test_orchestration_reference_tables.py` fails when a table no
longer matches the installed code.
These are not an orchestrator launch recipe. A `None` model selects
`LLMBridge`'s default model for the chosen provider.
Read the [capability guide](../agents/literature-review.md) for Python/CLI differences.

Public module: `nodes.ml_literature_review.ml_literature_review`.

<!-- generated: cli nodes.ml_literature_review.ml_literature_review -->
| Argument | Type/action | Required | Default | Choices | Help |
| --- | --- | --- | --- | --- | --- |
| --workspace | str | False | './siderius_workspace' | — | 'Root directory for reading the upstream interpretation output and writing ml_literature_review_{run_name}.json' |
| --run_name | str | False | 'v1' | — | 'Run name — reads interpretation_{run_name}.json (unless --experiment-history overrides), writes ml_literature_review_{run_name}.json' |
| --experiment-history, --experiment_history | str | False | None | — | "Explicit path to the upstream InterpretationOutput JSON. Default: {workspace}/interpretation_{run_name}.json — the same persisted record the proposal agent's CLI reads." |
| --lit_review_config | str | True | None | — | "Node-knob YAML (root_papers / dynamic_search / synthesis / confidence_rubric / findings_verbosity) — the same file and key mapping the workflow uses. A relative path resolves against the repo root. The YAML's top-level 'enabled:' key gates the workflow stage only and is ignored here — invoking this CLI is the enablement." |
| --provider | str | False | 'openai' | ['gemini', 'openai'] | — |
| --model_id | str | False | None | — | — |
| --task_composition | str | True | None | — | 'Task-composition manifest supplying the scientific contract and metric' |
| --data_dir | str | True | None | — | 'Existing physical data root required by the full task-composition binding; literature review does not train or score the data' |
<!-- end generated -->

A CLI flag is not automatically a Python input field or a supported field
of the outer chain launcher. Consult this exact entrypoint. Internal parser
modules are provenance references, not supported import entrypoints.
