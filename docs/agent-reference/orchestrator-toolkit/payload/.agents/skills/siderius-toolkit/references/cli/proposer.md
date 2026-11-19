# proposer: existing standalone CLI arguments

The table below lists the options of the parser this module's `main()` builds,
with each option's runtime default value.
Generated from source by
`python -m tools.orchestration_setup.reference_tables --write`;
`tests/unit/tools/test_orchestration_reference_tables.py` fails when a table no
longer matches the installed code.
These are not an orchestrator launch recipe. A `None` model selects
`LLMBridge`'s default model for the chosen provider.
Read the [capability guide](../agents/proposer.md) for Python/CLI differences.

Public module: `nodes.ml_model_proposal_agent.ml_model_proposal_agent`.

<!-- generated: cli nodes.ml_model_proposal_agent.ml_model_proposal_agent -->
| Argument | Type/action | Required | Default | Choices | Help |
| --- | --- | --- | --- | --- | --- |
| --workspace | str | False | './siderius_workspace' | — | 'Root directory for reading interpretation output and writing proposal' |
| --run_name | str | False | 'v1' | — | 'Run name — reads interpretation_{run_name}.json, writes proposal_{run_name}.json' |
| --provider | str | False | 'openai' | ['gemini', 'openai'] | — |
| --model_id | str | False | None | — | — |
| --task_composition | str | True | None | — | "Task-composition manifest that supplies the node's scientific contract" |
| --data_dir | str | True | None | — | 'Physical data root used while the task composition is bound' |
<!-- end generated -->

A CLI flag is not automatically a Python input field or a supported field
of the outer chain launcher. Consult this exact entrypoint. Internal parser
modules are provenance references, not supported import entrypoints.
