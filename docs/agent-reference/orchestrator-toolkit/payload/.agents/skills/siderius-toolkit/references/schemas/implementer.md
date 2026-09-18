# implementer: native schema field inventory

Reference snapshot: SIDERIUS `2df46e2298c017d9df850a85f870a55fbd40723d`. Derived from the actual
Pydantic `model_fields`; the installed classes remain the execution authority.
Defaults below describe the generic API, not permission to override the
frozen task, information treatment, budget, or candidate-selection contract.
Custom validators can impose cross-field requirements not expressible by a
required-field flag. Use `model_validate` / `model_validate_json` before execution.

Return to the [capability guide](../agents/implementer.md).

## ImplementorInput

Import: `agent.schemas.implementor.ImplementorInput`.

| Field | Python type | Required / default | Constraints | Meaning |
| --- | --- | --- | --- | --- |
| candidate_id | str \| None | None | [] | V21 PR E — carried verbatim from ''ProposalOutput.candidate_id'' by the propose->impl protocol. Observational join identity only (O-E-5); None = pre-PR-E or non-proposer candidate. |
| task_composition_ref | agent.schemas.hyperparam_tuning.TaskCompositionRef \| None | None | [] | Frozen task projection; None preserves the uncomposed legacy route. |
| model_name | str | required | [] | snake_case model type key. Used as the filename and PLUGIN_MODEL_TYPE constant. |
| output_type | Literal['classifier', 'regressor'] | 'classifier' | [] | Output representation the proposal committed to, carried verbatim from ''ProposalOutput.output_type''. Decides the emitted ''PLUGIN_OUTPUT_TYPE'' constant and the forward-contract comment, and therefore which shape the generated head must produce (''classifier'' -> [B, C, T], ''regressor'' -> [B, T]). Never inferred from the loss family. The default is a legacy read for fixtures; the production protocol always sets it explicitly. |
| model_description | str | required | [] | Plain-English description of the architecture. Injected into the LLM prompt. |
| mathematical_definition | str | required | [] | Precise layer-by-layer spec from the proposal agent. The LLM uses this to write __init__ and forward. |
| baseline_config | dict[str, Any] | required | [] | Safe starting configuration from the proposal agent. Used to derive sensible default values for the Pydantic config fields. |
| task_description | str | '' | [] | Plain-English description of the research task, sourced from ''configs/task_config.yaml''. Injected into the ''{TASK_DESCRIPTION}'' placeholder in the implementor system prompt at call time. Default empty string is for test fixtures only; production callers (workflow) always populate via ''get_task_description(load_task_config())'' which rejects empty values upstream. |
| forward_contract | agent.schemas.task_config.ForwardContract | factory: ForwardContract | [] | Typed forward-pass contract from ''configs/task_config.yaml''. Rendered into the ''{TASK_BACKGROUND}'' placeholder in the implementor system prompt and the user-prompt contract section. Default ''ForwardContract()'' (all fields empty) is for test fixtures only; production callers always populate via ''ForwardContract(**load_task_config()["forward_contract"])''. |
| implementor_blocks | agent.schemas.implementor.ImplementorTaskBlocks \| None | None | [] | Step 12 / PR-12a C7-4 — the run's task-owned IMPLEMENTOR science, or None. Additive and default-None by contract: every existing caller constructs this input without it. The CALLER supplies it — the workflow's bounded Regime-A adapter on an un-composed run, the composition's own declaration on a composed one. A composed run that declares NOTHING renders no science rather than inheriting TIDMAD's. |
| hardware_context | core.hardware_context.HardwareContext \| None | None | [] | Live hardware manifest from ''core.hardware_context'', populated by the workflow via ''get_or_create''. ''None'' for CPU-only hosts, test fixtures and standalone invocations that bypass the workflow; the capacity bullet then renders its defined magnitude-free form rather than a stale ceiling. |
| vram_budget_gb | float \| None | None | [Ge(ge=0.0)] | Active operator-defined VRAM ceiling (GB) for this iteration, threaded from the workflow exactly as for the proposer. Combined with ''hardware_context'' through ''HardwareContext.effective_cap_gb'', which is the single rule both nodes quote — so their prompts cannot name different caps. |
| plugin_dir | str | '' | [] | Directory where the model plugin file will be written. An omitted value resolves below storage.local.workspace; an explicit value is preserved for orchestrators that own a narrower attempt layout. |
| test_dir | str | '' | [] | Directory where the generated test file will be written. An omitted value resolves below storage.local.workspace; an explicit value is preserved for orchestrators that own a narrower attempt layout. |
| loss_dir | str | '' | [] | Directory where agent-generated loss plugin files will be written when ''custom_loss_spec'' is set. Mirrors ''plugin_dir'' for model plugins. An omitted value resolves below ''storage.local.workspace''; the workflow overrides this with a per-attempt path so retries do not clobber each other's plugins. The executor resolves loss plugins from the directories listed in ''SIDERIUS_LOSS_DIRS'' (set by the sandbox executor), so writing to ''loss_dir'' is sufficient to make the new loss visible to training. See ''docs/design/enable_loss_inventory.md'' § Commit L3. |
| custom_loss_spec | agent.schemas.proposal.CustomLossSpec \| None | None | [] | Specification for a novel loss function the implementor should generate this iteration. Threaded through from ''ProposalOutput.custom_loss_spec'' by the propose→impl protocol. ''None'' when the proposer is using one of the four built-in losses OR when reusing a previously-registered custom loss (in which case the implementor only writes the model plugin and the loss lookup succeeds against the existing registry entry). Wiring of the actual code-generation path lives at L4. |
| max_retries | int | 2 | [Ge(ge=0)] | Maximum self-correction attempts after the initial code commit. On each retry the LLM receives the validation error and its previous code, and produces a targeted fix. Total attempts = 1 + max_retries. Set to 0 to disable self-correction. |
| reference_code | dict[str, str] | factory: dict | [] | Source code of referenced ancestor models. Keyed by model_type. Loaded automatically from inherited_components — the implementor uses this as a template to copy-and-modify rather than writing from scratch. Empty dict = no reference code available. |
| expert_advice | str \| agent.schemas.hyperparam_tuning.ExpertAdvice | '' | [] | Structured guidance from upstream agents or orchestrators. Accepts a plain string or a structured ExpertAdvice object. |
| human_advice | str \| None | None | [] | Optional human-provided guidance (highest priority — overrides expert_advice). When present, injected into the LLM prompt as high-priority context. |
| previous_validation_failure | str \| None | None | [] | Validation error message from the previous implementation attempt for this same proposal. When set, the implementor knows upfront what spec-alignment issue to fix and can target the repair in its reasoning phase rather than discovering the problem after the fact. None on the first attempt. |
| storage | agent.schemas.storage.StorageConfig | factory: ImplementorInput.<lambda> | [] | Where this node reads its inputs and writes its own output record (e.g. implementor_output_{run_name}.json). Omitted generated-code destinations are derived from this local workspace. |

Read the complete nested JSON Schema from the same public class:

```python
import json
from agent.schemas.implementor import ImplementorInput
print(json.dumps(ImplementorInput.model_json_schema(), indent=2))
```

This inspection uses the selected installation and does not instantiate an
agent or call a model provider. It does not grant access to a dataset.

## ImplementorOutput

Import: `agent.schemas.implementor.ImplementorOutput`.

| Field | Python type | Required / default | Constraints | Meaning |
| --- | --- | --- | --- | --- |
| candidate_id | str \| None | None | [] | V21 PR E — echoed verbatim from ImplementorInput. Observational join identity only (O-E-5); None = pre-PR-E or non-proposer candidate. |
| model_type | str | required | [] | The PLUGIN_MODEL_TYPE key written into the plugin file. Same as the input model_name. |
| description_file_path | str | required | [] | Absolute path to the written description.md (e.g. .../agent_generated/models/attn_unet/description.md). Used by result_interpretation_agent to load the model description when interpreting results from this agent-generated model. |
| model_file_path | str | required | [] | Absolute path to the written plugin file (e.g. .../agent_generated/models/attn_unet.py). |
| test_file_path | str | required | [] | Absolute path to the written test file (e.g. .../agent_generated/tests/test_attn_unet.py). |
| config_fields | dict[str, Any] | required | [] | Summary of the Pydantic config fields generated by the LLM. Keys are field names, values are their default values. Used for logging and downstream context. |
| model_description | str | required | [] | Plain-English description of the architecture, passed through from ImplementorInput. Carried forward so ml_code_validator_agent can provide it to the LLM code reviewer. |
| mathematical_definition | str | required | [] | Precise mathematical/architectural specification from the proposal, passed through from ImplementorInput. Used by ml_code_validator_agent to verify implementation matches spec. |
| baseline_config_adjustments | dict[str, agent.schemas.implementor.ConfigAdjustment] | factory: dict | [] | Audit trail of field-level adjustments the implementor made to the proposer's baseline_config['model_config'] in order to satisfy its own pydantic schema. Empty dict (default) means the schema accepted the baseline as-is. Keys are field names; values describe the original value, the adjusted value, and the reason. Consumed by the proposal_to_hyperparam_seeded protocol to override the baseline before tuner-time, and by the interpretation agent to flag any falsifiable_prediction whose target config was mutated. See docs/improving_validation_awareness.md Phase B.1. |
| loss_provenance | agent.schemas.implementor.LossProvenance \| None | None | [] | Audit trail for custom-loss usage. ''None'' when the proposer used a built-in loss type (focal, focal_cw, ce, smooth_l1). Populated when ''baseline_config['loss_config']['loss_type'] == "custom"'' — records whether the loss was reused from a prior iteration or newly generated this iteration, the source iteration's ''run_name'', the absolute path to the plugin file, and whether the dummy-tensor forward pass validated. See ''docs/design/enable_loss_inventory.md'' § Commit L3. |
| model_io_contract | agent.schemas.model_io_contract.ModelIOContract \| None | None | [] | The normalized Model-I/O contract this candidate was generated against — Step 03's semantic authority, echoed verbatim from ''ImplementorInput.forward_contract.model_io'' (Step 04a). It is carried on the OUTPUT rather than re-read downstream so the validator probes the candidate against the declaration the implementor ACTUALLY used, not against a second read of the task config that may have moved. ''None'' = the legacy prose-only compatibility path, where no normalized contract was supplied; consumers must preserve their pre-Step-04a behaviour for it and must NOT treat absence as an error. |
| capability_metadata | core.capability_registry.CapabilityMetadata \| None | None | [] | Registry metadata for a newly-generated model plugin, handed back to the workflow so registration happens ONLY after the validator passes. Mirrors the #92 fix for losses on the model surface: previously the implementor wrote this entry to ''_capability_index.json'' immediately after generating the plugin, before the validator ran — validation failures then left phantom entries in the index that future proposers advertised as Branch B reuse candidates (v16 iter_015 ''gated_dilated_tcn'' failure mode). ''None'' on Branch A (built-in) and Branch B (reuse) paths where no new plugin was generated. See ''feat/v16-fixes'' commit history and ''reports/v16_20260630.md'' §9.10. |
| loss_capability_metadata | core.capability_registry.CapabilityMetadata \| None | None | [] | Registry metadata for a newly-generated loss plugin. The implementor returns this payload without mutating the capability index; the workflow commits it only after the complete candidate passes validation and construction admission. ''None'' means the candidate uses a built-in or already-registered loss. |

Read the complete nested JSON Schema from the same public class:

```python
import json
from agent.schemas.implementor import ImplementorOutput
print(json.dumps(ImplementorOutput.model_json_schema(), indent=2))
```

This inspection uses the selected installation and does not instantiate an
agent or call a model provider. It does not grant access to a dataset.
