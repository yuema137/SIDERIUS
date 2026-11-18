# literature-review: existing standalone CLI arguments

Source inventory at SIDERIUS `1c68bc81d7e44bbdc6e03a445a8422c3f77f45ff`. Argument expressions below are
copied from the existing parser declarations; evaluate dynamic defaults with
the selected executable’s `--help`. These are not an orchestrator launch recipe.
The provider and model rows were re-synced to `5ccb436f` (v1.1.0); a `None`
model selects `LLMBridge`'s default model for the chosen provider. Options
added after the inventory can be missing from this table; confirm with `--help`.
Read the [capability guide](../agents/literature-review.md) for Python/CLI differences.

Public module: `nodes.ml_literature_review.ml_literature_review`.

| Argument | Type/action | Required | Default expression | Choices | Help |
| --- | --- | --- | --- | --- | --- |
| --workspace | str | False | './siderius_workspace' | — | 'Root directory for reading the upstream interpretation output and writing ml_literature_review_{run_name}.json' |
| --run_name | str | False | 'v1' | — | 'Run name — reads interpretation_{run_name}.json (unless --experiment-history overrides), writes ml_literature_review_{run_name}.json' |
| --experiment-history, --experiment_history | str | False | None | — | "Explicit path to the upstream InterpretationOutput JSON. Default: {workspace}/interpretation_{run_name}.json — the same persisted record the proposal agent's CLI reads." |
| --lit_review_config | str | True | None (argparse default unless action changes it) | — | "Node-knob YAML (root_papers / dynamic_search / synthesis / confidence_rubric / findings_verbosity) — the same file and key mapping the workflow uses. A relative path resolves against the repo root. The YAML's top-level 'enabled:' key gates the workflow stage only and is ignored here — invoking this CLI is the enablement." |
| --provider | str | False | DEFAULT_LLM_PROVIDER (= 'openai') | ['gemini', 'openai'] | — |
| --model_id | str | False | None | — | — |
| --task_composition | str | True | None (argparse default unless action changes it) | — | 'Task-composition manifest supplying the scientific contract and metric' |
| --data_dir | str | True | None (argparse default unless action changes it) | — | 'Existing physical data root required by the full task-composition binding; literature review does not train or score the data' |

A CLI flag is not automatically a Python input field or a supported field
of the outer chain launcher. Consult this exact entrypoint. Internal parser
modules are provenance references, not supported import entrypoints.
