# interpretation: existing standalone CLI arguments

Source inventory at SIDERIUS `1c68bc81d7e44bbdc6e03a445a8422c3f77f45ff`. Argument expressions below are
copied from the existing parser declarations; evaluate dynamic defaults with
the selected executable’s `--help`. These are not an orchestrator launch recipe.
The provider and model rows were re-synced to `5ccb436f` (v1.1.0); a `None`
model selects `LLMBridge`'s default model for the chosen provider. Options
added after the inventory can be missing from this table; confirm with `--help`.
Read the [capability guide](../agents/interpretation.md) for Python/CLI differences.

Public module: `nodes.result_interpretation_agent.result_interpretation_agent`.

| Argument | Type/action | Required | Default expression | Choices | Help |
| --- | --- | --- | --- | --- | --- |
| --workspace | str | False | './siderius_workspace' | — | 'Root directory for reading summaries and writing output' |
| --run_name | str | False | 'v1' | — | 'Run name — reads summary_{run_name}.json, writes interpretation_{run_name}.json' |
| --model_type | str | True | None (argparse default unless action changes it) | — | "Model architecture (e.g. 'punet')." |
| --provider | str | False | DEFAULT_LLM_PROVIDER (= 'openai') | ['gemini', 'openai'] | — |
| --model_id | str | False | None | — | — |

A CLI flag is not automatically a Python input field or a supported field
of the outer chain launcher. Consult this exact entrypoint. Internal parser
modules are provenance references, not supported import entrypoints.
