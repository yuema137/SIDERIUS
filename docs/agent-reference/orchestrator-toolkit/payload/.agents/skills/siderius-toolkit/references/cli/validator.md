# validator: existing standalone CLI arguments

Source inventory at SIDERIUS `1c68bc81d7e44bbdc6e03a445a8422c3f77f45ff`. Argument expressions below are
copied from the existing parser declarations; evaluate dynamic defaults with
the selected executable’s `--help`. These are not an orchestrator launch recipe.
The provider and model rows were re-synced to `5ccb436f` (v1.1.0); a `None`
model selects `LLMBridge`'s default model for the chosen provider. Options
added after the inventory can be missing from this table; confirm with `--help`.
Read the [capability guide](../agents/validator.md) for Python/CLI differences.

Public module: `nodes.ml_code_validator_agent.ml_code_validator_agent`.

| Argument | Type/action | Required | Default expression | Choices | Help |
| --- | --- | --- | --- | --- | --- |
| --model_type | str | True | None (argparse default unless action changes it) | — | — |
| --model_file_path | str | True | None (argparse default unless action changes it) | — | — |
| --test_file_path | str | True | None (argparse default unless action changes it) | — | — |
| --description_file_path | str | True | None (argparse default unless action changes it) | — | — |
| --config_fields | str | True | None (argparse default unless action changes it) | — | 'JSON dict of field names → default values' |
| --model_description | str | True | None (argparse default unless action changes it) | — | — |
| --mathematical_definition | str | True | None (argparse default unless action changes it) | — | — |
| --llm_provider | str | False | DEFAULT_LLM_PROVIDER (= 'openai') | ['gemini', 'openai'] | — |
| --llm_model_id | str | False | None | — | — |
| --workspace | str | False | './siderius_workspace' | — | — |
| --run_name | str | False | 'v1' | — | — |

A CLI flag is not automatically a Python input field or a supported field
of the outer chain launcher. Consult this exact entrypoint. Internal parser
modules are provenance references, not supported import entrypoints.
