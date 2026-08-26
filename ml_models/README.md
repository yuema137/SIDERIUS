# `ml_models/` — built-in models, losses, and the plugin loader

**Audience**: a coding agent or engineer touching model/loss loading, or
writing a model plugin by hand. **Authority**: the source. Template:
[`docs/agent-reference/MODULE_README_TEMPLATE.md`](../docs/agent-reference/MODULE_README_TEMPLATE.md).
Plugin identity/provenance semantics:
[plugins mechanism](../docs/agent-reference/mechanisms/plugins.md).

## Purpose

The model side of the system: six built-in architectures, their Pydantic
config schemas, the loss surface, and the loader that lets agent-generated (or
hand-written) plugin files join the same registries at runtime. It does not
decide *which* model runs (the agents do) or *how* training executes
(`execute_tools/train_engine_sandbox.py` does).

## Public interface

| file | surface |
|---|---|
| `models_sandbox.py` | `MODEL_REGISTRY` (`punet`, `fcnet`, `transformer`, `wavenet`, `rnn`, `gated_fno`) · `BUILTIN_OUTPUT_TYPES` · `BUILTIN_INPUT_DTYPES` · `construct_registered_model(model_type, config_obj, *, loss_type)` |
| `models_format_sandbox.py` | the config schemas (`BaseConfig`, per-model configs, `LossConfig`, `TrainConfig`, `ExperimentConfig`) · `PLUGIN_CONFIG_REGISTRY` · `get_config_class` · `OutputSemantic` + the semantic/loss compatibility validators |
| `plugin_loader.py` | `extend_registries` (scan the resolved plugin dirs) · `register_model_in_memory(plugin_path)` (single file) · `preload_global_models()` (startup absorption of the global library) · `get_output_type` |
| `loss_models_sandbox.py` | `LOSS_REGISTRY` / `LOSS_CONFIG_REGISTRY` · `register_loss_in_memory` · `preload_global_losses` · built-ins `FocalLoss1D` / `FocalLoss1DCW` · `get_criterion`, `get_target_torch_dtype` |
| `model_descriptions.py` | `get_model_description(model_type)` — resolves `description.md` from built-ins → legacy global → `${SIDERIUS_CHAIN_WORKSPACE}/plugins/*` (newest first); raises naming every searched path |
| `legacy_baseline_configs.json` | **the paper-spec source of truth** for baseline hyperparameters |
| `{model}/description.md` | one prompt-facing description per built-in |

## Inputs

Plugin directories via `SIDERIUS_PLUGIN_DIRS` / `SIDERIUS_LOSS_DIRS`
(`os.pathsep`-separated). When set, **exactly those** dirs are scanned — no
fallback; when unset, the legacy global `agent_generated/models` is the
default.

## Outputs

Populated registries; constructed `nn.Module`s; criteria; description text for
prompts.

## Owned semantics

- **The plugin file contract** — a plugin module must define:

  ```
  PLUGIN_MODEL_TYPE   : str    unique model key
  PLUGIN_CONFIG_CLASS : type   Pydantic BaseModel subclass
  PLUGIN_MODEL_CLASS  : type   nn.Module subclass
  PLUGIN_OUTPUT_TYPE  : str    "classifier" | "regressor"   (optional)
  ```

  A missing required symbol refuses the file; a *present but illegal*
  `PLUGIN_OUTPUT_TYPE` refuses instead of being silently rewritten (a
  recorded incident fix — issue #234).
- Registry conflict rules: later dirs shadow earlier ones with a printed
  warning; in-memory re-registration of the same type warns and takes the
  most recent.
- Loss/semantic compatibility validation (classification vs regression
  losses) at config time.

## Non-owned semantics

- **The forward contract is the task's, not this package's.** The
  `[B, T] int → [B, 256, T] float` line in the loader docstring is TIDMAD's
  instance of it; the authoritative shape is the task config's
  `forward_contract.model_io` (`ModelIOContract`), which validator and probe
  read. Do not treat the 256 as a framework constant.
- Which plugin dirs a run uses → the workflow / `core/subprocess_env.py`.
- Training/inference execution → `execute_tools/` engines.

## Extension points

- A hand-written model or loss plugin: one `.py` satisfying the contract, in a
  directory named by `SIDERIUS_PLUGIN_DIRS` (losses: `SIDERIUS_LOSS_DIRS`).
  Agent-generated plugins go through the same loader.
- ✅ A composed run's *child processes* inherit the task pack's plugin dirs
  through the run-scoped binding (Step 12 / PR-12d seam P, landed `84d74280`):
  a manifest's `model_plugins:` / `loss_plugins:` sections resolve and pin the
  pack's plugins, and `core/subprocess_env.py` **unions** the binding into
  `SIDERIUS_PLUGIN_DIRS` / `SIDERIUS_LOSS_DIRS` for every child — the binding
  is never dropped, and the ambient environment is deliberately not a third
  source.

## State and filesystem effects

Registers loaded modules in `sys.modules` under `siderius_plugin_*` (so
`inspect.getsource` works for prompt excerpts), rolled back on load failure.
⚠ Reads — and the workflow *writes* — the checkout-level `agent_generated/`
library and its capability index: runs on a shared checkout are not isolated
from each other's generated candidates (recorded product gap; see
[workspaces and resume](../docs/guides/workspaces-and-resume.md)).

## Failure modes

| refusal | meaning |
|---|---|
| plugin file missing a required `PLUGIN_*` symbol | the file is not a plugin — refused at load |
| illegal `PLUGIN_OUTPUT_TYPE` | refused by name, never rewritten |
| `UnknownOutputContractError` | no registry establishes an output contract for the model type |
| `FileNotFoundError` from `get_model_description` | no `description.md` in any of the three search locations — the error lists them |

## Files normally edited

A new built-in model: module + config schema + registry rows + its
`description.md`. **`legacy_baseline_configs.json` only with a paper citation
in the commit message** (train.py line / network.py class / paper section) —
it is the paper-spec source of truth (CLAUDE.md).

## Files normally NOT edited

`FocalLoss1D` — line-for-line identical to TIDMAD's reference implementation;
verify against the paper before touching any loss math. Baseline configs away
from paper spec without written justification.

## Minimal example

```python
# my_plugin_dir/attn_fcnet.py
PLUGIN_MODEL_TYPE = "attn_fcnet"
PLUGIN_CONFIG_CLASS = AttnFcnetConfig      # Pydantic BaseModel
PLUGIN_MODEL_CLASS = AttnFcnet             # nn.Module
PLUGIN_OUTPUT_TYPE = "classifier"
```

```bash
SIDERIUS_PLUGIN_DIRS=/path/to/my_plugin_dir <entrypoint …>
```

## Related tests

`tests/unit/ml_models/` — loader contract refusals, registry shadowing,
output-type vocabulary, loss compatibility; baseline-config pins live with the
comparison-campaign tests.
