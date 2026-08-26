# MLModelImplementor

> Reads a `ProposalOutput` and writes three files: a runnable PyTorch plugin (`{model_name}.py`), a description doc (`description.md`), and a test file (`test_{model_name}.py`). Two-call chain-of-thought (reasoning → code) wrapped in a 5-check validation pipeline plus a self-correction repair loop.

## Position in the pipeline

- **Node type**: **standalone-capable** — `nodes/ml_model_implementor/ml_model_implementor.py` exposes a CLI `main()` that reads `proposal_{run_name}.json` from the workspace, builds an `ImplementorInput`, runs the agent, and writes the plugin + description + test files to `agent_generated/`.
- **Upstream**: `ml_model_proposal_agent` (provides `model_name`, `output_type`, `model_description`, `mathematical_definition`, `baseline_config`, `custom_loss_spec` via `ml_model_propose_to_ml_model_impl.py::local_full_spec` in `agent/schemas/protocols/`).
- **Downstream**: `ml_code_validator_agent` (consumes the three file paths + `model_description` + `mathematical_definition` for the eight-check validation pass via the `ml_model_impl_to_ml_model_valid` protocol).
- **Protocol (upstream)**: `ml_model_propose_to_ml_model_impl.py::local_full_spec` — maps `ProposalOutput.{candidate_id, model_name, output_type, model_description, mathematical_definition, baseline_config, custom_loss_spec}` into this node's `ImplementorInput`. The `reference_code` for any `inherited_components` (ancestor model source the implementor can read) is NOT loaded by the protocol — the workflow attaches it after the protocol returns (`workflows/model_exploration.py:2696`).

## Input

**Schema**: `ImplementorInput` in `agent/schemas/implementor.py`

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `model_name` | `str` | Yes | — | snake_case model type key. Used as the plugin filename and the `PLUGIN_MODEL_TYPE` constant. |
| `model_description` | `str` | Yes | — | Plain-English description of the architecture from the proposer. Injected into the reasoning prompt and written into the description.md file. |
| `mathematical_definition` | `str` | Yes | — | Precise layer-by-layer spec from the proposer. The LLM uses this to write `__init__` and `forward`. |
| `baseline_config` | `dict[str, Any]` | Yes | — | Safe starting configuration from the proposer. Used to derive sensible default values for the Pydantic config fields AND for the Phase B.2a baseline-schema-compatibility check (instantiate `PLUGIN_CONFIG_CLASS` with `baseline_config.model_config` to catch implementor-invented constraints). |
| `plugin_dir` | `str` | No | `"agent_generated/models"` | Directory where the model plugin file is written. **Fixed output destination independent of `storage.local.workspace`** — agent-generated plugins live in a single common pool so `MODEL_REGISTRY` can pick them up at runtime. |
| `test_dir` | `str` | No | `"agent_generated/tests"` | Directory where the test file is written. **Fixed output destination independent of `storage.local.workspace`**. |
| `max_retries` | `int` | No | `2` | Maximum self-correction attempts after the initial code commit. On each retry the LLM receives the validation error and its previous code via `IMPLEMENTOR_REPAIR_PROMPT`. |
| `reference_code` | `dict[str, str]` | No | `{}` | Source code of referenced ancestor models, keyed by `model_type`. Loaded automatically from `inherited_components`. The implementor uses this as inline context so it can faithfully carry over claimed components. |
| `expert_advice` | `str \| ExpertAdvice` | No | `""` | Structured guidance from upstream agents or orchestrators. Accepts a plain string or a structured `ExpertAdvice` object. |
| `human_advice` | `str \| None` | No | `None` | Optional human-provided guidance — **highest priority**, overrides `expert_advice` when present. Injected into the reasoning prompt as high-priority context. |
| `previous_validation_failure` | `str \| None` | No | `None` | Validation error message from a previous implementation attempt for this same proposal. When set, the implementor knows upfront what spec-vs-code mismatch to avoid. Populated by the workflow when retrying after the downstream validator rejected the plugin. |

### Workflow-populated fields

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `storage` | `StorageConfig` | Yes | — | Where this node reads its inputs and writes its own output record (e.g. `implementor_output_{run_name}.json`). Note that `plugin_dir` and `test_dir` above are independent of this — the plugin and test files go to `agent_generated/` regardless. |
| `task_description` | `str` | No | `""` | Plain-English task description from `configs/task_config.yaml`, injected into the reasoning prompt's `{TASK_BACKGROUND}` block. |
| `forward_contract` | `ForwardContract` | No | `ForwardContract()` | The typed forward-pass contract from `configs/task_config.yaml`. Its `model_io` field carries the normalized Step-03 `ModelIOContract`, which since Step 04a is the authority for every contract-owned fact the implementor derives: the self-check probe, the generated plugin's contract comments, the generated test's class count, and the custom-loss probe pair. `None` = the legacy prose-only path, which reproduces the shipped behaviour exactly. |
| `hardware_context` | `HardwareContext \| None` | No | `None` | Live hardware manifest (Step 04a / OD-S4-1). Combined with `vram_budget_gb` through `HardwareContext.effective_cap_gb` to render the reasoning prompt's GPU-budget bullet. `None` (CPU-only host, test fixture, standalone invocation) renders a defined magnitude-free form — never a stale literal. |
| `vram_budget_gb` | `float \| None` | No | `None` | Active operator VRAM ceiling (GB) for this iteration, threaded from the workflow exactly as for the proposer. A budget above the physical 80% cap does not raise it. |

## Output

**Schema**: `ImplementorOutput` in `agent/schemas/implementor.py`

| Field | Type | Description |
|---|---|---|
| `model_type` | `str` | The `PLUGIN_MODEL_TYPE` key written into the plugin file. Same as the input `model_name`. |
| `model_file_path` | `str` | Absolute path to the written plugin file (e.g. `.../agent_generated/models/attn_unet.py`). |
| `description_file_path` | `str` | Absolute path to the written `description.md` (e.g. `.../agent_generated/models/attn_unet/description.md`). Used by `result_interpretation_agent` to load architecture knowledge for the next iteration. |
| `test_file_path` | `str` | Absolute path to the written test file (e.g. `.../agent_generated/tests/test_attn_unet.py`). |
| `model_io_contract` | `ModelIOContract \| None` | The normalized declaration this candidate was generated against, echoed from `forward_contract.model_io` (Step 04a). Mapped verbatim to `ValidatorInput` by the impl→valid protocol, so the validator probes against the declaration the implementor actually used rather than a second read of the task config. `None` on the legacy prose-only path. |
| `config_fields` | `dict[str, Any]` | Summary of the Pydantic config fields generated by the LLM. Keys are field names, values are their default values. Read by the downstream validator + the tuner. |
| `model_description` | `str` | Plain-English description of the architecture, passed through from `ImplementorInput`. Carried forward so the downstream validator can provide it to its LLM-review step. |
| `mathematical_definition` | `str` | Precise mathematical/architectural specification from the proposal, passed through from `ImplementorInput`. Used by the validator's LLM-review step to assess spec-vs-implementation alignment. |
| `baseline_config_adjustments` | `dict[str, ConfigAdjustment]` | Audit trail of field-level adjustments the implementor made to the proposer's `baseline_config["model_config"]` to satisfy its own Pydantic field constraints. Empty when the implementor accepted the proposer's values verbatim. |

## CLI usage

```bash
.venv/bin/python nodes/ml_model_implementor/ml_model_implementor.py \
    --workspace ./siderius_workspace \
    --run_name v1 \
    --provider gemini \
    --model_id gemini-3.1-pro-preview
```

The CLI reads `{workspace}/proposal_{run_name}.json` (the upstream proposal agent's output), builds a minimal `ImplementorInput` (no `reference_code`, no `expert_advice`, default `plugin_dir` / `test_dir`), runs the agent, and writes:
- `agent_generated/models/{model_name}.py` (the plugin)
- `agent_generated/models/{model_name}/description.md` (the description)
- `agent_generated/tests/test_{model_name}.py` (the test)

**Limitations of standalone CLI use**:

- **No `reference_code`** — inherited-component carryover from past winning runs is skipped. The implementor reasons from `mathematical_definition` alone.
- **No `previous_validation_failure`** — if the downstream validator rejected a prior plugin, the CLI cannot replay that feedback.
- **No `expert_advice` / `human_advice`** — fresh attempt, no guidance carryover.

### CLI arguments

| Argument | Type | Default | Description |
|---|---|---|---|
| `--workspace` | `str` | `./siderius_workspace` | Root directory for reading `proposal_{run_name}.json`. The plugin/test files always land under `agent_generated/`, NOT here. |
| `--run_name` | `str` | `v1` | Filename suffix shared across the chain (proposal, implementor). |
| `--provider` | `str` (`gemini` \| `openai`) | `gemini` | LLM provider for both the reasoning and code calls. |
| `--model_id` | `str` | `gemini-3.1-pro-preview` | Specific model id. Note the default is `gemini-3.1-pro-preview` (not `flash-lite`) — code generation benefits from the stronger model. |

## Python API usage

```python
from nodes.ml_model_implementor.ml_model_implementor import MLModelImplementor
from agent.schemas.implementor import ImplementorInput
from agent.schemas.storage import StorageConfig, LocalStorageConfig

inp = ImplementorInput(
    model_name="attn_unet",
    model_description="UNet with multi-head self-attention in the bottleneck...",
    mathematical_definition="Encoder: Conv1d(1->32, k=7) -> MaxPool(2) -> ...",
    baseline_config={
        "model_config": {
            "segmentation_size": 16384,
            "batch_size": 4,
            "embed_dim": 32,
            "num_heads": 4,
        },
        # ... train_config, loss_config, sample_set_config, ...
    },
    # Optional inherited-component carryover:
    reference_code={"wavenet": "<source of wavenet.py>"},
    # Optional guidance + retry signal:
    expert_advice="prefer GroupNorm over BatchNorm",
    previous_validation_failure=None,  # set if the validator rejected a prior plugin
    # Storage for the output record:
    storage=StorageConfig(
        backend="local",
        local=LocalStorageConfig(workspace="./workspace", run_name="iter_001"),
    ),
)

agent = MLModelImplementor(provider="gemini", model_id="gemini-3.1-pro-preview")
output = agent.run(inp)  # -> ImplementorOutput
```

The constructor accepts `bridge_factory` (test injection — defaults to `LLMBridge`) and `max_retries` (defaults to `None`, infinite quota retry per project policy). Note `max_retries` on the constructor is the LLMBridge-level network retry; the **code self-correction repair count** is a separate field on `ImplementorInput` (`inp.max_retries`, default `2`).

## Storage outputs

This node writes **four files**, on two different paths:

- **Plugin file** (independent of workspace): `{inp.plugin_dir}/{inp.model_name}.py` — runnable PyTorch plugin assembled from `PLUGIN_TEMPLATE` with LLM-generated sections substituted in. Defines `PLUGIN_MODEL_TYPE`, `PLUGIN_CONFIG_CLASS`, `PLUGIN_MODEL_CLASS`, `PLUGIN_OUTPUT_TYPE`. Default location: `agent_generated/models/{model_name}.py`.
- **Description file** (independent of workspace): `{inp.plugin_dir}/{inp.model_name}/description.md` — markdown description carried over from `model_description` + a code block with the `baseline_config`. Read by `result_interpretation_agent` to surface architecture knowledge in subsequent iterations. Default location: `agent_generated/models/{model_name}/description.md`.
- **Test file** (independent of workspace): `{inp.test_dir}/test_{inp.model_name}.py` — pytest file assembled from `TEST_TEMPLATE`. Tests forward-pass shape, NaN-freeness, and config instantiation. The test file's `sys.path.insert(0, "../models")` line resolves at test runtime to `agent_generated/models/`, where the plugin lives. Default location: `agent_generated/tests/test_{model_name}.py`.
- **Output record JSON** (in the workspace): `{storage.local.workspace}/implementor_output_{run_name}.json` — the validated `ImplementorOutput` (file paths + config_fields + adjustments + passthrough description/spec). Audit log only; the downstream node receives data through the protocol in memory.

The plugin + description + test paths are **deliberately independent of `storage.local.workspace`**: `MODEL_REGISTRY` scans `agent_generated/models/` at runtime via the plugin loader, so plugins from any workspace pool together. Test discovery follows the same convention.

## Key behavioral notes

- **Two-call chain-of-thought.** Call 1 = `bridge.generate_text(IMPLEMENTOR_REASONING_PROMPT, ...)` — free-form reasoning about PyTorch modules, shape handling, config-field choices. Call 2 = `bridge.generate(IMPLEMENTOR_CODE_PROMPT, ...)` — commit to specific code sections as strict JSON. The LLM never writes raw plugin boilerplate — it writes only the marked sections (`init_body`, `forward_body`, `config_fields_code`, `helper_class_defs`, etc.) and `_assemble_plugin` substitutes them into `PLUGIN_TEMPLATE`.
- **5-check validation pipeline** runs after every commit/repair call (`_validate_code`):
  1. **Config field consistency** — every `config.<field>` referenced in `init_body` must have a corresponding `Field` declaration in `config_fields_code`.
  2. **Scalar-only config fields** — all config field values must be `int`, `float`, or `bool`. The hyperparameter tuner only searches scalar dimensions; strings/lists/dicts are rejected.
  3. **Syntax check** — `ast.parse(plugin_src)` on the fully-assembled plugin source.
  4. **Smoke test** — `_smoke_test_plugin` instantiates `PLUGIN_CONFIG_CLASS` from its own declarations, builds `PLUGIN_MODEL_CLASS(config)`, and runs a forward pass on a probe input, asserting the shape the plugin's declared contract requires. Since Step 04a both the probe and the expected shape come from `agent/skills/model_io_probe_skill.py`, derived from `forward_contract.model_io` — `[1, 64] → [1, 256, 64]` under the shipped TIDMAD declaration, `[1, 64] → [1, 16, 64]` under a task declaring 16 classes. With no contract the shipped geometry is reproduced exactly. When the baseline declared no `segmentation_size` the generated class declares it REQUIRED (see "Segmentation size is declared, never invented" below), so this check supplies the value `model_io_probe_skill.probe_config_kwargs(PLUGIN_CONFIG_CLASS)` returns — `PROBE_SYMBOLIC_EXTENT` (64), the same symbolic extent the probe input is realized at. A candidate that DID declare a size gets `{}` and is constructed with no arguments, exactly as before. That helper is the **one** owner of the rule; `ml_code_validator_agent`'s check 6 calls the same function on the same class, and neither node may keep a copy.
  5. **Baseline schema compatibility** (Phase B.2a) — instantiate `PLUGIN_CONFIG_CLASS` with the proposer's actual `baseline_config["model_config"]` (NOT defaults) to catch implementor-invented constraints (e.g. `multiple_of=2`) that reject the proposer's values. Adjustments the implementor itself made to `model_config` to fit its constraints are recorded in `ImplementorOutput.baseline_config_adjustments`. A rejection consisting of NOTHING but `segmentation_size` being missing is not reported: the baseline cannot satisfy a key it never stated, and the repair prompt forbids the LLM to touch that field, so reporting it would spend every repair attempt on an unsatisfiable instruction. Any other error — including a real violation arriving alongside it — is reported in full.
- **Self-correction repair loop.** On any validation failure, the implementor calls `bridge.generate(IMPLEMENTOR_REPAIR_PROMPT, ...)` with the previous code + the validation error message — up to `inp.max_retries` times (default 2). Total worst-case LLM calls per run: 1 reasoning + 1 commit + 2 repairs = 4.
- **Common-mistake patching** (`_patch_common_mistakes`). Before validation, known LLM quirks get rewritten in-place: `self.embedding(input)` → `self.embedding(x)` (Python keyword collision), trailing `$` artefacts stripped, etc. This avoids burning a repair slot on cosmetic LLM errors.
- **Plugin contract enforced by `PLUGIN_TEMPLATE`.** Every generated plugin defines exactly four module-level attributes — `PLUGIN_MODEL_TYPE`, `PLUGIN_CONFIG_CLASS`, `PLUGIN_MODEL_CLASS`, `PLUGIN_OUTPUT_TYPE` — in that order. The plugin loader (`core/plugin_loader.py`) refuses to register a plugin missing any of these. The LLM never writes the contract; only the section bodies.
- **Forward-pass shape contract follows the declared `output_type`** (V21 PR A). The input is always `[B, T] int`; the output depends on the contract the proposal committed to:

  | `ImplementorInput.output_type` | emitted `PLUGIN_OUTPUT_TYPE` | forward output |
  |---|---|---|
  | `classifier` (default) | `"classifier"` | `[B, C, T]` float — per-timestep class logits, `C` from the task's declared cardinality (256 under TIDMAD) |
  | `regressor` | `"regressor"` | `[B, T]` float — the denoised waveform |

  The DECLARATION selects the form; the task's `ModelIOContract` supplies the facts inside it. A `classifier` declaration under a task that declares no class alphabet fails closed rather than guessing a cardinality.

  Derived once by `_render_output_contract` and used in three places, which must stay in step: the emitted `PLUGIN_OUTPUT_TYPE` constant and forward-contract comment, `TEST_TEMPLATE.test_forward_shape` (which reads `PLUGIN_OUTPUT_TYPE` from the generated plugin), and `_smoke_test_plugin`. An architecture that fails the shape its own declaration requires fails the smoke test and triggers a repair. The default is a legacy read; a production proposal always sets `output_type` explicitly.
- **Segmentation size is declared, never invented** (C12-P / F-12e-G1). `_assemble_plugin` does not *consume* a `segmentation_size` — it *writes a declaration* into the generated class. It therefore emits one of exactly two lines:

  | baseline `model_config` / `train_config` | emitted into `PLUGIN_TEMPLATE` |
  |---|---|
  | declares `segmentation_size: N` | `segmentation_size: int = Field(default=N, ge=1)` |
  | declares none | `segmentation_size: int = Field(ge=1)` — **required, no default** |

  Before this the framework filled an absent key with `40000`. That literal became the generated class's own default, was registered, and came back through `get_config_class` → `estimator.resolve_model_field` → the tuner's `_resolve_declared_segmentation_size` as if the task had declared it — so that helper could never return `None` for a plugin, and the task's named refusal in `execute_tools/tidmad_data_path.py` was unreachable from outside. It also mis-priced VRAM by 278× for a Pets-scale (144) candidate, rejecting a feasible architecture and burning a tuner attempt.

  The field always EXISTS on the generated class (`train_engine_sandbox.py` and `inference_single.py` read it as an attribute) and `_TEMPLATE_CONFIG_FIELDS` still forbids the LLM to declare it. **Behaviour change**: a run whose proposal *and* plan both omit the key now reaches a named task refusal instead of silently training and pricing at 40000. Built-in models declare the field in their own config classes and are unaffected. The generated test file (`TEST_TEMPLATE`) constructs with `segmentation_size=64` in the undeclared case and with no arguments — byte-identical to the shipped text — otherwise. The implementor prompt's `train_config` context line is likewise rendered only when a value was declared, so a foreign composed run never sees a TIDMAD-scale number it did not state.
- **`reference_code` carries ancestor source verbatim.** When `inherited_components` claims a primitive from a prior model (e.g. "spectral_conv from gated_fno"), the workflow loads the source of `gated_fno.py` into `reference_code["gated_fno"]` and injects it into the reasoning prompt. The downstream validator's inheritance check verifies the claimed primitive's regex actually matches the new plugin's source.

## Dependencies

- **LLM**: 2–4 call sites per run, all via `LLMBridge`:
  - **Reasoning** — exactly one `bridge.generate_text(IMPLEMENTOR_REASONING_PROMPT, ...)` call per run.
  - **Code commit** — one `bridge.generate(IMPLEMENTOR_CODE_PROMPT, ...)` call (strict JSON).
  - **Repair** — up to `inp.max_retries` (default 2) `bridge.generate(IMPLEMENTOR_REPAIR_PROMPT, ...)` calls when validation fails.
- **GPU**: not required. The `_smoke_test_plugin` forward pass runs on CPU with a tiny probe input; no GPU needed even when the eventual training will use one. `hardware_context` is read only to render the prompt's capacity bullet, never to select a device.
- **External services**: none. Depends on the upstream proposal file (in CLI mode) or upstream protocol (in workflow mode). No network calls outside `LLMBridge`. Filesystem dependencies: writes plugin + description + test under `agent_generated/`, writes the output record JSON under the workspace; reads the upstream proposal JSON when running standalone.
