# implementer: existing standalone CLI arguments

The table below lists the options of the parser this module's `main()` builds,
with each option's runtime default value.
Generated from source by
`python -m tools.orchestration_setup.reference_tables --write`;
`tests/unit/tools/test_orchestration_reference_tables.py` fails when a table no
longer matches the installed code.
These are not an orchestrator launch recipe. A `None` model selects
`LLMBridge`'s default model for the chosen provider.
Read the [capability guide](../agents/implementer.md) for Python/CLI differences.

Public module: `nodes.ml_model_implementor.ml_model_implementor`.

<!-- generated: cli nodes.ml_model_implementor.ml_model_implementor -->
| Argument | Type/action | Required | Default | Choices | Help |
| --- | --- | --- | --- | --- | --- |
| --workspace | str | False | './siderius_workspace' | — | — |
| --run_name | str | False | 'v1' | — | — |
| --provider | str | False | 'openai' | ['gemini', 'openai'] | — |
| --model_id | str | False | None | — | — |
| --run_seed | run_seed_argument | False | None | — | 'Run seed for model probes (issue #983); generated and printed when omitted.' |
<!-- end generated -->

A CLI flag is not automatically a Python input field or a supported field
of the outer chain launcher. Consult this exact entrypoint. Internal parser
modules are provenance references, not supported import entrypoints.
