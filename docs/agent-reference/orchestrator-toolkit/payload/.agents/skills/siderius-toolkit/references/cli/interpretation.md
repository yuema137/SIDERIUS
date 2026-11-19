# interpretation: existing standalone CLI arguments

The table below lists the options of the parser this module's `main()` builds,
with each option's runtime default value.
Generated from source by
`python -m tools.orchestration_setup.reference_tables --write`;
`tests/unit/tools/test_orchestration_reference_tables.py` fails when a table no
longer matches the installed code.
These are not an orchestrator launch recipe. A `None` model selects
`LLMBridge`'s default model for the chosen provider.
Read the [capability guide](../agents/interpretation.md) for Python/CLI differences.

Public module: `nodes.result_interpretation_agent.result_interpretation_agent`.

<!-- generated: cli nodes.result_interpretation_agent.result_interpretation_agent -->
| Argument | Type/action | Required | Default | Choices | Help |
| --- | --- | --- | --- | --- | --- |
| --workspace | str | False | './siderius_workspace' | — | 'Root directory for reading summaries and writing output' |
| --run_name | str | False | 'v1' | — | 'Run name — reads summary_{run_name}.json, writes interpretation_{run_name}.json' |
| --model_type | str | True | None | — | "Model architecture (e.g. 'punet')." |
| --provider | str | False | 'openai' | ['gemini', 'openai'] | — |
| --model_id | str | False | None | — | — |
| --required_gate_ids | str | False | None | — | "Scientific gate IDs resolved from the producing run's effective Health policy. Omit to retain unknown validity; pass with no IDs only for an explicitly empty roster." |
<!-- end generated -->

A CLI flag is not automatically a Python input field or a supported field
of the outer chain launcher. Consult this exact entrypoint. Internal parser
modules are provenance references, not supported import entrypoints.
