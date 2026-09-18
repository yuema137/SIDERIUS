# implementer: existing standalone CLI arguments

Source inventory at SIDERIUS `1c68bc81d7e44bbdc6e03a445a8422c3f77f45ff`. Argument expressions below are
copied from the existing parser declarations; evaluate dynamic defaults with
the selected executable’s `--help`. These are not an orchestrator launch recipe.
Read the [capability guide](../agents/implementer.md) for Python/CLI differences.

Public module: `nodes.ml_model_implementor.ml_model_implementor`.

| Argument | Type/action | Required | Default expression | Choices | Help |
| --- | --- | --- | --- | --- | --- |
| --workspace | str | False | './siderius_workspace' | — | — |
| --run_name | str | False | 'v1' | — | — |
| --provider | str | False | 'gemini' | ['gemini', 'openai'] | — |
| --model_id | str | False | 'gemini-3.1-pro-preview' | — | — |

A CLI flag is not automatically a Python input field or a supported field
of the outer chain launcher. Consult this exact entrypoint. Internal parser
modules are provenance references, not supported import entrypoints.
