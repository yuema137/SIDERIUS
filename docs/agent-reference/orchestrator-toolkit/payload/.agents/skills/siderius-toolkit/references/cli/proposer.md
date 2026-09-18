# proposer: existing standalone CLI arguments

Source inventory at SIDERIUS `1c68bc81d7e44bbdc6e03a445a8422c3f77f45ff`. Argument expressions below are
copied from the existing parser declarations; evaluate dynamic defaults with
the selected executable’s `--help`. These are not an orchestrator launch recipe.
Read the [capability guide](../agents/proposer.md) for Python/CLI differences.

Public module: `nodes.ml_model_proposal_agent.ml_model_proposal_agent`.

| Argument | Type/action | Required | Default expression | Choices | Help |
| --- | --- | --- | --- | --- | --- |
| --workspace | str | False | './siderius_workspace' | — | 'Root directory for reading interpretation output and writing proposal' |
| --run_name | str | False | 'v1' | — | 'Run name — reads interpretation_{run_name}.json, writes proposal_{run_name}.json' |
| --provider | str | False | 'gemini' | ['gemini', 'openai'] | — |
| --model_id | str | False | 'gemini-3.1-flash-lite-preview' | — | — |
| --task_composition | str | True | None (argparse default unless action changes it) | — | "Task-composition manifest that supplies the node's scientific contract" |
| --data_dir | str | True | None (argparse default unless action changes it) | — | 'Physical data root used while the task composition is bound' |

A CLI flag is not automatically a Python input field or a supported field
of the outer chain launcher. Consult this exact entrypoint. Internal parser
modules are provenance references, not supported import entrypoints.
