# Contract schema names

## Scope and owner

`contract_names.py` in this package is the single owner of the human-facing
name, one-sentence description and kind of every schema a catalog contract
carries. Contract ids in `catalog.CONTRACTS` stay the identity and the
compatibility key; names are presentation only and never decide a connection.

- **Keyed by schema, not by id or module.** `contract_schema(id)` is the
  contract's semantic type where `SEMANTIC_SCHEMAS` declares one, otherwise the
  catalog native type label without an optional `| None` wrapper;
  `SCHEMA_NAMES` maps that label to `SchemaName(name, description, kind)`.
  `contract_name(id)` resolves through the schema, so ids that carry the same
  schema show the same name, and an optional variant shows its base schema's
  name (requiredness is drawn by the socket fill, not the name).
- **Names describe the data.** At most three plain words, no abbreviations
  (for example `LLM`, `id`, `ref`, `spec`), no module/capability word and no
  direction word (`input`, `output`, `request`, `result`, `in`, `out`, ...).
  Direction is drawn on the canvas socket: an incoming arrow before an input's
  label, an outgoing arrow after an output's, with accessible text
  "Receives <name>" / "Sends <name>".
- **Kind** says where a value comes from, never its direction: `produced`
  (made inside the workflow: a module's result, or a brief a declared mapping
  assembles), `external` (a resource you provide) or `setting` (guidance or
  configuration you provide).
- **Compatibility reads as "same schema name"**: a wire joins an output and an
  input only when the server offers it, which today requires the same contract
  id. Future modules and adaptors reuse an existing schema name; a new schema
  gets a new entry here before any surface shows it.
- **Adaptors** are named `adaptor_name(from_id, to_id)` = `"<from name> → <to
  name>"` (for example `Results analysis → Search evidence`); an adaptor between
  contracts carrying the same schema is refused (`ValueError`), and an unknown
  id is a `KeyError`.

## Projection

`tools.workflow_authoring.models.NativeContract` adds computed `name`,
`description` and `kind` fields next to `id` and `native_type`, so every
projected contract (port inventory sockets and results, port choices, protocol
mapping output, node catalog input/output/argument contracts, pending-node
ports) carries them additively. The browser
(`editor-contract-presentation.js`) learns names from those objects and keeps
only colour and shape per id.

## Table

| Contract id | Name | Kind | Description |
| --- | --- | --- | --- |
| `interpretation.input` | Run summaries | produced | Condensed summaries of one or more finished training runs. |
| `interpretation.output` | Results analysis | produced | A reading of run results with per-model scores and the best and worst models. |
| `optional.text` | Data folder | external | The path of the folder that holds the task's data, as you provide it. |
| `optional.expert-advice` | Expert advice | setting | Advice written by a person for a module to consider. |
| `optional.expert-context` | Expert notes | setting | Context items from people or analysis modules that inform a model design. |
| `optional.parameter-rules` | Parameter rules | setting | Limits on which model and training parameters may change and how. |
| `literature.input` | Search evidence | produced | Evidence from earlier analysis that a literature search looks for papers about. |
| `literature.output` | Paper findings | produced | Findings from published papers, with the retrieved papers behind them. |
| `proposal.input` | Design brief | produced | Everything needed to design the next model. |
| `proposal.output` | Model plan | produced | A complete model specification, ready to implement and train. |
| `implementation.input` | Coding brief | produced | A model plan with run context, ready to be turned into code. |
| `implementation.output` | Model code | produced | Paths of the written model source files. |
| `validation.input` | Review brief | produced | Model code with its context, ready to be checked before training. |
| `validation.output` | Code verdict | produced | A verdict on whether the model code is safe to train. |
| `tuning.input` | Training job | produced | A validated model with its training settings, ready to be trained and tuned. |
| `tuning.output` | Training report | produced | The full report of a completed training and tuning run. |
| `native-training.settings` | Training settings | setting | Training launch and startup controls that you provide in a settings file. |
| `storage` | Storage folder | external | Where records and outputs are written; you provide it. |
| `optional.constraint-context` | Run constraints | setting | A statement of the known run restrictions and who declared them. |
| `optional.task-composition-ref` | Task reference | external | A pointer to the run's task declaration, never a second copy of it. |
| `llm-provider` | Language model provider | external | Which language model service is called, such as openai or anthropic. |
| `optional.model-id` | Language model name | external | An exact model name at the chosen service; when omitted, the service's default model is used. |

## Semantic schema types

`optional.text` (the `data_dir` argument) and `optional.model-id` (the
`llm_model_id` argument) both carry native `str | None` but mean different
things and stay separate, not interconnectable, contract ids.
`SEMANTIC_SCHEMAS` keys each by its own semantic type
(`semantic.DataFolderPath`, `semantic.LanguageModelName`), so they read
"Data folder" and "Language model name". These labels are local to the
definition catalog; native signatures, contract ids and wire formats are
unchanged. A future primitive-typed contract with its own meaning gets its own
semantic type here.

## Validation

`tests/unit/workflows/test_contract_names.py` checks catalog coverage, unique
names and descriptions per schema, the word rules above, same schema ⇒ same
name and distinct (semantic) schemas ⇒ distinct names, `produced` ⇔ exchanged by a capability, and the adaptor rule.
`tests/unit/tools/test_workflow_authoring.py` checks the serialized fields;
`tests/browser/port_legibility.mjs` checks names, arrows and the legend in the
browser. `catalog.py`/`contract_names.py` are not inputs to
`agent.prompt_rendering.rendering_assembly_digest`; no prompt changes.
